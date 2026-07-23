from pathlib import Path

import pytest

from keiltool.gui.project_config import LoadedProjectTargets, load_project_targets, resolve_target_facts


PROJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Project>
  <Targets>
    <Target>
      <TargetName>App</TargetName>
      <TargetOption>
        <TargetCommonOption><Device>GD32F303CC</Device></TargetCommonOption>
        <TargetArmAds><ArmAdsMisc><Cpu>IRAM(0x20000000,0x00010000) IROM(0x08000000,0x00040000)</Cpu></ArmAdsMisc></TargetArmAds>
      </TargetOption>
    </Target>
    <Target>
      <TargetName>NoRam</TargetName>
      <TargetOption><TargetCommonOption><Device>GD32F303CC</Device></TargetCommonOption></TargetOption>
    </Target>
  </Targets>
</Project>
"""


def _project_file(tmp_path: Path, name: str = "motor") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    project_file = tmp_path / f"{name}.uvprojx"
    project_file.write_text(PROJECT_XML, encoding="utf-8")
    return project_file


def _scripts_dir(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    (scripts / "target").mkdir(parents=True)
    (scripts / "target" / "stm32f3x.cfg").write_text("# target\n", encoding="utf-8")
    (scripts / "target" / "custom.cfg").write_text("# custom\n", encoding="utf-8")
    (scripts / "target" / "custom.CFG").write_text("# custom\n", encoding="utf-8")
    (scripts / "target" / "not-a-config.txt").write_text("# not a config\n", encoding="utf-8")
    return scripts


def test_load_project_targets_returns_an_immutable_project_context(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))

    assert isinstance(loaded, LoadedProjectTargets)
    assert loaded.project_root == tmp_path
    assert isinstance(loaded.targets, tuple)
    assert [target.name for target in loaded.targets] == ["App", "NoRam"]


def test_resolve_target_facts_uses_verified_family_mapping(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)

    facts = resolve_target_facts(
        loaded.targets[0],
        loaded.project_root,
        openocd_path="D:/tools/openocd.exe",
        scripts_dir=scripts,
    )

    assert facts.ready is True
    assert facts.target_cfg == "target/stm32f3x.cfg"
    assert facts.resolution_status == "family_mapping_verified"
    assert facts.ram_origin == 0x20000000
    assert facts.ram_size == 0x10000
    assert facts.default_log_dir == str(tmp_path / ".keilbridge" / "logs")


def test_resolve_target_facts_accepts_verified_relative_and_absolute_overrides(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)
    absolute_cfg = tmp_path / "outside.CFG"
    absolute_cfg.write_text("# target\n", encoding="utf-8")

    relative = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override="target/custom.CFG")
    absolute = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override=absolute_cfg)

    assert relative.ready is True
    assert relative.target_cfg == "target/custom.CFG"
    assert relative.resolution_status == "override_verified"
    assert absolute.ready is True
    assert absolute.target_cfg == str(absolute_cfg)
    assert absolute.resolution_status == "override_verified"


def test_unavailable_target_cfg_fails_closed_and_missing_ram_is_reported(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)

    unavailable = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=tmp_path / "empty-scripts")
    missing_ram = resolve_target_facts(loaded.targets[1], loaded.project_root, scripts_dir=scripts)

    assert unavailable.ready is False
    assert unavailable.resolution_reason
    assert missing_ram.ready is True
    assert missing_ram.ram_origin is None
    assert missing_ram.ram_size is None


def test_overrides_must_be_cfg_files_and_relative_paths_cannot_escape_scripts(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)
    plain_file = tmp_path / "outside.txt"
    plain_file.write_text("# not a config\n", encoding="utf-8")
    outside_cfg = tmp_path / "outside.cfg"
    outside_cfg.write_text("# target\n", encoding="utf-8")
    absolute_directory = tmp_path / "absolute-directory.cfg"
    absolute_directory.mkdir()
    (scripts / "target" / "relative-directory.cfg").mkdir()

    absolute = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override=plain_file)
    relative = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override="target/not-a-config.txt")
    escaped = resolve_target_facts(loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override="../outside.cfg")
    absolute_directory_facts = resolve_target_facts(
        loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override=absolute_directory
    )
    relative_directory_facts = resolve_target_facts(
        loaded.targets[0], loaded.project_root, scripts_dir=scripts, target_override="target/relative-directory.cfg"
    )

    assert absolute.ready is False
    assert absolute.target_cfg == ""
    assert relative.ready is False
    assert relative.target_cfg == ""
    assert escaped.ready is False
    assert escaped.target_cfg == ""
    assert absolute_directory_facts.ready is False
    assert absolute_directory_facts.target_cfg == ""
    assert relative_directory_facts.ready is False
    assert relative_directory_facts.target_cfg == ""


def test_two_loaded_projects_keep_their_own_default_log_directories(tmp_path):
    first = load_project_targets(_project_file(tmp_path / "first", "first"))
    second = load_project_targets(_project_file(tmp_path / "second", "second"))
    scripts = _scripts_dir(tmp_path)

    first_facts = resolve_target_facts(first.targets[0], first.project_root, scripts_dir=scripts)
    second_facts = resolve_target_facts(second.targets[0], second.project_root, scripts_dir=scripts)

    assert first_facts.default_log_dir == str(first.project_root / ".keilbridge" / "logs")
    assert second_facts.default_log_dir == str(second.project_root / ".keilbridge" / "logs")


def test_resolve_target_facts_requires_project_root(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))

    with pytest.raises(TypeError):
        resolve_target_facts(loaded.targets[0])
