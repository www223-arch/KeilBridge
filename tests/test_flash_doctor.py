from keiltool.core.doctor import _resolve_openocd_cfg, classify_openocd_log
from keiltool.core.project_model import KeilTargetModel, MemoryRegion


def test_flash_doctor_finds_debug_only_openocd_config(tmp_path):
    generated = tmp_path / "generated"
    cfg = generated / "debug-only" / "openocd" / "App_stlink.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("source [find interface/stlink.cfg]\n", encoding="utf-8")

    assert _resolve_openocd_cfg(generated, "App", "stlink") == cfg


def test_flash_doctor_prefers_default_openocd_config(tmp_path):
    generated = tmp_path / "generated"
    default_cfg = generated / "openocd" / "App_stlink.cfg"
    debug_cfg = generated / "debug-only" / "openocd" / "App_stlink.cfg"
    default_cfg.parent.mkdir(parents=True)
    debug_cfg.parent.mkdir(parents=True)
    default_cfg.write_text("default\n", encoding="utf-8")
    debug_cfg.write_text("debug\n", encoding="utf-8")

    assert _resolve_openocd_cfg(generated, "App", "stlink") == default_cfg


def test_flash_doctor_classifies_probe_open_failed():
    findings = classify_openocd_log(
        "xPack Open On-Chip Debugger\nError: open failed\n",
        "openocd",
        KeilTargetModel(name="App", device="GD32F303CC"),
        "stlink",
    )

    assert any(item.code == "OPENOCD_PROBE_OPEN_FAILED" and item.severity == "fail" for item in findings)


def test_flash_doctor_reports_unresolved_generated_target(tmp_path):
    generated = tmp_path / "generated"
    cfg = generated / "openocd" / "App_stlink.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# KeilBridge OpenOCD target unresolved: no mapping\n", encoding="utf-8")

    from keiltool.core.doctor import _static_flash_findings

    findings = _static_flash_findings(KeilTargetModel(name="App"), "openocd", cfg, "stlink")

    assert any(item.code == "OPENOCD_TARGET_UNRESOLVED" and item.severity == "fatal" for item in findings)


def test_reset_state_finding_reports_register_values_and_checked_ranges():
    target = KeilTargetModel(
        name="App",
        device="GD32F303CC",
        memory=[
            MemoryRegion("FLASH", "0x08000000", "256K"),
            MemoryRegion("RAM", "0x20000000", "64K"),
        ],
    )

    findings = classify_openocd_log(
        "Info : pc: 0x08001234\nInfo : msp: 0x20010000\n",
        "openocd",
        target,
        "stlink",
    )

    finding = next(item for item in findings if item.code == "RESET_STATE_LOOKS_VALID")
    assert finding.title == "复位寄存器地址范围检查通过"
    assert "PC=0x08001234" in finding.message
    assert "MSP=0x20010000" in finding.message
    assert "FLASH [0x08000000, 0x08040000)" in finding.message
    assert "RAM [0x20000000, 0x20010000]" in finding.message
    assert "范围来源: Keil 工程内存定义" in finding.message
    assert "仅验证地址范围" in finding.message
    assert "program/verify" in finding.message
    assert "pc: 0x08001234" in finding.evidence
    assert "msp: 0x20010000" in finding.evidence
