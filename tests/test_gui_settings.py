import json

from keiltool.gui.settings import GuiSettings, SettingsStore


def test_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "gui-settings.json")
    settings = GuiSettings(
        project="D:/fw/motor.uvprojx",
        target="Release",
        firmware="D:/fw/motor.bin",
        bin_address="0x08004000",
        openocd_path="D:/tools/openocd.exe",
        scripts_dir="D:/tools/scripts",
        target_override="target/custom.cfg",
        rtt_address="0x20001000",
        rtt_channel=2,
        rtt_port=19022,
        rtt_timeout_ms=6000,
        logs_dir="D:/fw/logs",
    )

    store.save(settings)

    assert store.load() == settings
    assert json.loads((tmp_path / "gui-settings.json").read_text(encoding="utf-8"))["version"] == 1
    assert not (tmp_path / "gui-settings.json.tmp").exists()


def test_damaged_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text("{broken", encoding="utf-8")

    assert SettingsStore(path).load() == GuiSettings()


def test_settings_from_dict_uses_defaults_for_invalid_values():
    settings = GuiSettings.from_dict(
        {"version": 1, "project": 42, "rtt_channel": "bad", "rtt_port": True, "rtt_timeout_ms": 9.5}
    )

    assert settings == GuiSettings(rtt_timeout_ms=9)


def test_incompatible_settings_version_falls_back_to_defaults(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text('{"version": 99, "project": "D:/fw/motor.uvprojx"}', encoding="utf-8")

    assert SettingsStore(path).load() == GuiSettings()
