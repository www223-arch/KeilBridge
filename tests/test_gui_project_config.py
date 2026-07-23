from pathlib import Path

from keiltool.gui.project_config import load_project_targets, resolve_target_facts


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


def _project_file(tmp_path: Path) -> Path:
    project_file = tmp_path / "motor.uvprojx"
    project_file.write_text(PROJECT_XML, encoding="utf-8")
    return project_file


def _scripts_dir(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    (scripts / "target").mkdir(parents=True)
    (scripts / "target" / "stm32f3x.cfg").write_text("# target\n", encoding="utf-8")
    (scripts / "target" / "custom.cfg").write_text("# custom\n", encoding="utf-8")
    return scripts


def test_load_project_targets_reads_each_keil_target(tmp_path):
    targets = load_project_targets(_project_file(tmp_path))

    assert [target.name for target in targets] == ["App", "NoRam"]


def test_resolve_target_facts_uses_verified_family_mapping(tmp_path):
    target = load_project_targets(_project_file(tmp_path))[0]
    scripts = _scripts_dir(tmp_path)

    facts = resolve_target_facts(target, openocd_path="D:/tools/openocd.exe", scripts_dir=scripts)

    assert facts.ready is True
    assert facts.target_cfg == "target/stm32f3x.cfg"
    assert facts.resolution_status == "family_mapping_verified"
    assert facts.ram_origin == 0x20000000
    assert facts.ram_size == 0x10000
    assert facts.default_log_dir == str(tmp_path / ".keilbridge" / "logs")


def test_resolve_target_facts_accepts_verified_relative_and_absolute_overrides(tmp_path):
    target = load_project_targets(_project_file(tmp_path))[0]
    scripts = _scripts_dir(tmp_path)
    absolute_cfg = tmp_path / "outside.cfg"
    absolute_cfg.write_text("# target\n", encoding="utf-8")

    relative = resolve_target_facts(target, scripts_dir=scripts, target_override="target/custom.cfg")
    absolute = resolve_target_facts(target, scripts_dir=scripts, target_override=absolute_cfg)

    assert relative.ready is True
    assert relative.target_cfg == "target/custom.cfg"
    assert relative.resolution_status == "override_verified"
    assert absolute.ready is True
    assert absolute.target_cfg == str(absolute_cfg)
    assert absolute.resolution_status == "override_verified"


def test_unavailable_target_cfg_fails_closed_and_missing_ram_is_reported(tmp_path):
    targets = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)

    unavailable = resolve_target_facts(targets[0], scripts_dir=tmp_path / "empty-scripts")
    missing_ram = resolve_target_facts(targets[1], scripts_dir=scripts)

    assert unavailable.ready is False
    assert unavailable.resolution_reason
    assert missing_ram.ready is True
    assert missing_ram.ram_origin is None
    assert missing_ram.ram_size is None
