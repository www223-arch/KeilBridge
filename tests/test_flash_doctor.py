from keiltool.core.doctor import _resolve_openocd_cfg


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
