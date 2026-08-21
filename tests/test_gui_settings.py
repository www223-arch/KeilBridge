import json
from pathlib import Path

from keiltool.gui.settings import GuiSettings, SettingsStore, default_devices_path


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
        rtt_display_level="INFO",
        logs_dir="D:/fw/logs",
        device_vendor="GigaDevice",
        device_name="GD32F303CC",
        device_source_mode="device",
        project_firmware="D:/fw/project.hex",
        device_firmware="D:/fw/device.bin",
        vofa_path="D:/tools/VOFA+/vofa+.exe",
        vofa_listen="127.0.0.1:1347",
        vofa_up_channel=3,
        vofa_up_port=19101,
        vofa_up_name="Plot",
        vofa_down_channel=4,
        vofa_down_port=19102,
        vofa_down_name="Commands",
        vofa_expected_float_count=6,
    )

    store.save(settings)

    assert store.load() == settings
    assert json.loads((tmp_path / "gui-settings.json").read_text(encoding="utf-8"))["version"] == 1
    assert not (tmp_path / "gui-settings.json.tmp").exists()


def test_legacy_settings_infer_exclusive_device_source_contexts():
    project = GuiSettings.from_dict(
        {
            "version": 1,
            "project": "D:/fw/app.uvprojx",
            "target": "Debug",
            "firmware": "D:/fw/project.hex",
        }
    )
    standalone = GuiSettings.from_dict(
        {
            "version": 1,
            "firmware": "D:/fw/device.bin",
            "device_vendor": "GigaDevice",
            "device_name": "GD32F303CC",
        }
    )

    assert project.device_source_mode == "project"
    assert project.project_firmware == "D:/fw/project.hex"
    assert project.device_firmware == ""
    assert standalone.device_source_mode == "device"
    assert standalone.project_firmware == ""
    assert standalone.device_firmware == "D:/fw/device.bin"


def test_damaged_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text("{broken", encoding="utf-8")

    assert SettingsStore(path).load() == GuiSettings()


def test_settings_from_dict_uses_defaults_for_invalid_values():
    settings = GuiSettings.from_dict(
        {"version": 1, "project": 42, "rtt_channel": "bad", "rtt_port": True, "rtt_timeout_ms": 9.5}
    )

    assert settings == GuiSettings(rtt_timeout_ms=9)


def test_settings_accepts_known_rtt_display_level_and_rejects_unknown_value():
    assert GuiSettings().rtt_display_level == "VERBOSE"
    assert GuiSettings.from_dict({"rtt_display_level": "INFO"}).rtt_display_level == "INFO"
    assert GuiSettings.from_dict({"rtt_display_level": "invalid"}).rtt_display_level == "VERBOSE"


def test_incompatible_settings_version_falls_back_to_defaults(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text('{"version": 99, "project": "D:/fw/motor.uvprojx"}', encoding="utf-8")

    assert SettingsStore(path).load() == GuiSettings()


def test_missing_settings_is_normal_and_has_no_diagnostic(tmp_path):
    result = SettingsStore(tmp_path / "missing.json").load_result()

    assert result.settings == GuiSettings()
    assert result.diagnostic is None


def test_corrupt_settings_returns_a_diagnostic(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text("{broken", encoding="utf-8")

    result = SettingsStore(path).load_result()

    assert result.settings == GuiSettings()
    assert result.diagnostic is not None
    assert result.diagnostic.code == "settings_corrupt"


def test_unreadable_settings_returns_a_diagnostic(tmp_path, monkeypatch):
    path = tmp_path / "gui-settings.json"
    path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("access denied")
        return original_read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)

    result = SettingsStore(path).load_result()

    assert result.settings == GuiSettings()
    assert result.diagnostic is not None
    assert result.diagnostic.code == "settings_unreadable"


def test_incompatible_settings_returns_a_diagnostic(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text('{"version": 99}', encoding="utf-8")

    result = SettingsStore(path).load_result()

    assert result.settings == GuiSettings()
    assert result.diagnostic is not None
    assert result.diagnostic.code == "settings_incompatible"


def test_settings_diagnostic_renders_in_openocd_output():
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import SettingsDiagnostic

    rendered = []
    gui = object.__new__(KeilToolGui)
    gui._append_openocd = rendered.append

    gui._render_settings_diagnostic(SettingsDiagnostic("settings_corrupt", "Settings JSON is invalid."))

    assert rendered
    assert "settings_corrupt" in rendered[0]
    assert "Settings JSON is invalid." in rendered[0]


def test_default_devices_path_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert default_devices_path() == tmp_path / "KeilTool" / "devices"
