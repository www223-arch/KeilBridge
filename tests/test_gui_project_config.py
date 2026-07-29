from pathlib import Path

import pytest

from keiltool.core.device_catalog import CatalogDevice, CatalogMemory, CatalogSource
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


GD32E235_PROJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Project>
  <Targets>
    <Target>
      <TargetName>DragonFocus_app_debug</TargetName>
      <TargetOption>
        <TargetCommonOption>
          <Device>GD32E235CB</Device>
          <Vendor>GigaDevice</Vendor>
          <Cpu>IRAM(0x20000000,0x04000) IROM(0x08002000,0x0A000) CPUTYPE("Cortex-M23") CLOCK(72000000) ELITTLE</Cpu>
          <FlashDriverDll>UL2CM3(-FN1 -FF0GD32E23x -FS08000000 -FL020000 -FP0($$Device:GD32E235CB$Flash\\GD32E23x.FLM))</FlashDriverDll>
        </TargetCommonOption>
      </TargetOption>
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
    (scripts / "interface").mkdir(parents=True)
    (scripts / "target").mkdir(parents=True)
    (scripts / "interface" / "stlink.cfg").write_text("# interface\n", encoding="utf-8")
    (scripts / "target" / "stm32f3x.cfg").write_text("# target\n", encoding="utf-8")
    (scripts / "target" / "custom.cfg").write_text("# custom\n", encoding="utf-8")
    (scripts / "target" / "custom.CFG").write_text("# custom\n", encoding="utf-8")
    (scripts / "target" / "not-a-config.txt").write_text("# not a config\n", encoding="utf-8")
    return scripts


def _openocd_file(tmp_path: Path) -> Path:
    executable = tmp_path / "openocd.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"fake")
    return executable


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
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )

    assert facts.ready is True
    assert facts.target_cfg == "target/stm32f3x.cfg"
    assert facts.resolution_status == "family_mapping_verified"
    assert facts.flash_origin == 0x08000000
    assert facts.flash_size == 0x40000
    assert facts.ram_origin == 0x20000000
    assert facts.ram_size == 0x10000
    assert facts.default_log_dir == str(tmp_path / ".keilbridge" / "logs")


def test_unlisted_gd32e235_uses_keil_facts_and_verified_openocd_family_mapping(tmp_path):
    project_file = tmp_path / "DragonFocus_userapp.uvprojx"
    project_file.write_text(GD32E235_PROJECT_XML, encoding="utf-8")
    loaded = load_project_targets(project_file)
    target = loaded.targets[0]
    scripts = _scripts_dir(tmp_path)
    (scripts / "target" / "gd32e23x.cfg").write_text("# gd32e23x\n", encoding="utf-8")

    facts = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )

    assert target.device == "GD32E235CB"
    assert target.device_info.matched is False
    assert target.core == "cortex-m23"
    assert [(region.name, region.origin, region.length) for region in target.memory] == [
        ("RAM", "0x20000000", "16K"),
        ("FLASH", "0x08002000", "40K"),
    ]
    assert target.flash_algorithm == "GD32E23x.FLM"
    assert facts.target_cfg == "target/gd32e23x.cfg"
    assert facts.resolution_status == "family_mapping_verified"
    assert facts.ready is True


def test_complete_flash_range_prefers_exact_device_catalog_over_project_partition(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    target = loaded.targets[0]
    target.memory[0] = target.memory[0].__class__("FLASH", "0x08005800", "150K")

    facts = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=_scripts_dir(tmp_path),
        catalog_device=_catalog_device(),
    )

    assert facts.flash_origin == 0x08000000
    assert facts.flash_size == 0x40000
    assert facts.flash_range_complete is True
    assert facts.flash_range_source == "device_catalog"
    assert "工程" in facts.flash_summary
    assert "0x08005800" in facts.flash_summary


def test_resolve_target_facts_accepts_verified_relative_and_absolute_overrides(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path))
    scripts = _scripts_dir(tmp_path)
    absolute_cfg = tmp_path / "outside.CFG"
    absolute_cfg.write_text("# target\n", encoding="utf-8")

    openocd = _openocd_file(tmp_path)
    relative = resolve_target_facts(
        loaded.targets[0],
        loaded.project_root,
        openocd_path=openocd,
        scripts_dir=scripts,
        target_override="target/custom.CFG",
    )
    absolute = resolve_target_facts(
        loaded.targets[0],
        loaded.project_root,
        openocd_path=openocd,
        scripts_dir=scripts,
        target_override=absolute_cfg,
    )

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
    missing_ram = resolve_target_facts(
        loaded.targets[1],
        loaded.project_root,
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )

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


def test_hardware_readiness_validates_executable_scripts_interface_and_target_cfg(tmp_path):
    loaded = load_project_targets(_project_file(tmp_path / "project"))
    target = loaded.targets[0]
    openocd = _openocd_file(tmp_path / "valid")
    scripts = _scripts_dir(tmp_path / "valid")

    valid = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=openocd,
        scripts_dir=scripts,
    )
    missing_executable = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=tmp_path / "missing-openocd.exe",
        scripts_dir=scripts,
    )
    missing_interface_scripts = _scripts_dir(tmp_path / "missing-interface")
    (missing_interface_scripts / "interface" / "stlink.cfg").unlink()
    missing_interface = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=openocd,
        scripts_dir=missing_interface_scripts,
    )
    missing_target_scripts = _scripts_dir(tmp_path / "missing-target")
    (missing_target_scripts / "target" / "stm32f3x.cfg").unlink()
    missing_target = resolve_target_facts(
        target,
        loaded.project_root,
        openocd_path=openocd,
        scripts_dir=missing_target_scripts,
    )

    assert valid.ready is True
    assert missing_executable.ready is False
    assert "executable" in missing_executable.resolution_reason.lower()
    assert missing_interface.ready is False
    assert "interface" in missing_interface.resolution_reason.lower()
    assert missing_target.ready is False
    assert "target" in missing_target.resolution_reason.lower()


def _catalog_device(*, target="target/stm32f3x.cfg", memory=None):
    return CatalogDevice(
        vendor="GigaDevice",
        device="GD32F303CC",
        family="GD32F30x Series",
        sub_family="GD32F303",
        core="Cortex-M4",
        fpu="FPU",
        endian="Little-endian",
        memory=tuple(
            memory
            or (
                CatalogMemory("Flash", 0x08000000, 0x40000, "rx", True, True),
                CatalogMemory("SRAM", 0x20000000, 0x10000, "rwx", True, False),
            )
        ),
        flash_algorithms=(),
        openocd_target=target,
        openocd_status="explicit_pack_compatibility" if target else "unresolved",
        source=CatalogSource("embedded", "GigaDevice", "GD32F30x_DFP", "2.5.0", "official", "abc"),
    )


def test_catalog_device_resolves_ready_hardware_facts_without_project(tmp_path):
    from keiltool.gui.project_config import facts_from_catalog_device

    facts = facts_from_catalog_device(
        _catalog_device(),
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=_scripts_dir(tmp_path),
        default_log_dir=tmp_path / "logs",
    )

    assert facts.target_name == ""
    assert facts.device == "GD32F303CC"
    assert facts.flash_origin == 0x08000000
    assert facts.flash_size == 0x40000
    assert facts.ram_origin == 0x20000000
    assert facts.ram_size == 0x10000
    assert facts.target_cfg == "target/stm32f3x.cfg"
    assert facts.resolution_status == "catalog_verified"
    assert facts.resolution_reason == "Device catalog OpenOCD target mapping was verified."
    assert facts.ready is True


def test_catalog_device_fails_closed_for_missing_target_cfg_or_writable_ram(tmp_path):
    from keiltool.gui.project_config import facts_from_catalog_device

    scripts = _scripts_dir(tmp_path)
    unresolved = facts_from_catalog_device(
        _catalog_device(target=""),
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )
    missing_cfg = facts_from_catalog_device(
        _catalog_device(target="target/not-present.cfg"),
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )
    no_ram = facts_from_catalog_device(
        _catalog_device(memory=(CatalogMemory("Flash", 0x08000000, 0x40000, "rx"),)),
        openocd_path=_openocd_file(tmp_path),
        scripts_dir=scripts,
    )

    assert unresolved.ready is False
    assert unresolved.target_cfg == ""
    assert missing_cfg.ready is False
    assert missing_cfg.target_cfg == ""
    assert no_ram.ready is True
    assert no_ram.ram_origin is None
    assert "writable RAM" in no_ram.resolution_reason
