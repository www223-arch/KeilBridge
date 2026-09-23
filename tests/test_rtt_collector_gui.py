from __future__ import annotations

from dataclasses import replace
from pathlib import Path


def test_rtt_collector_mode_only_exposes_collection_controls(tmp_path):
    import tkinter as tk

    from keiltool.core.stlink_probe import StLinkDiscovery
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import SettingsStore

    root = tk.Tk()
    root.withdraw()
    try:
        gui = KeilToolGui(
            root,
            settings_store=SettingsStore(tmp_path / "settings.json"),
            probe_discovery=lambda _openocd: StLinkDiscovery(()),
            mode="rtt_collector",
        )

        assert root.title() == "KeilTool RTT 日志采集器"
        assert gui.device_source_mode_var.get() == "device"
        assert gui.controls.project_section.cget("text") == "采集设备"

        for visible in (
            gui.controls.device_combo,
            gui.controls.probe_combo,
            gui.controls.logs_entry,
            gui.controls.rtt_start_button,
            gui.controls.rtt_stop_button,
            gui.controls.collector_device_status,
            gui.controls.probe_driver_button,
        ):
            assert visible.winfo_manager() == "grid"

        for hidden in (
            gui.controls.project_entry,
            gui.controls.target_combo,
            gui.controls.project_source_radio,
            gui.controls.firmware_entry,
            gui.controls.connect_button,
            gui.controls.flash_read_button,
            gui.controls.flash_button,
            gui.controls.auto_radio,
            gui.controls.manual_radio,
            gui.controls.rtt_address_entry,
            gui.controls.channel_spin,
            gui.controls.vofa_start_button,
            gui.controls.advanced_button,
        ):
            assert hidden.winfo_manager() == "" or hidden.master.winfo_manager() == ""
    finally:
        root.destroy()


def test_rtt_collector_raises_saved_short_scan_timeout_to_thirty_seconds(tmp_path):
    import tkinter as tk

    from keiltool.core.stlink_probe import StLinkDiscovery
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import GuiSettings, SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    store.save(replace(GuiSettings(), rtt_timeout_ms=5000))
    root = tk.Tk()
    root.withdraw()
    try:
        gui = KeilToolGui(
            root,
            settings_store=store,
            probe_discovery=lambda _openocd: StLinkDiscovery(()),
            mode="rtt_collector",
        )

        assert gui.rtt_timeout_var.get() == "30000"
    finally:
        root.destroy()


def test_rtt_collector_replaces_stale_onefile_tool_paths_and_does_not_persist_them(
    monkeypatch, tmp_path
):
    import tkinter as tk

    import keiltool.gui.app as app_module
    from keiltool.core.stlink_probe import StLinkDiscovery
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import GuiSettings, SettingsStore

    current_openocd = tmp_path / "current" / "openocd" / "bin" / "openocd.exe"
    current_scripts = tmp_path / "current" / "openocd" / "scripts"
    current_openocd.parent.mkdir(parents=True)
    current_openocd.write_bytes(b"openocd")
    current_scripts.mkdir(parents=True)
    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        replace(
            GuiSettings(),
            openocd_path="C:/Users/test/AppData/Local/Temp/_MEI111/openocd/bin/openocd.exe",
            scripts_dir="C:/Users/test/AppData/Local/Temp/_MEI111/openocd/scripts",
        )
    )
    monkeypatch.setattr(app_module, "find_openocd", lambda: str(current_openocd))
    monkeypatch.setattr(
        app_module,
        "find_openocd_scripts",
        lambda _openocd: str(current_scripts),
    )
    root = tk.Tk()
    root.withdraw()
    try:
        gui = KeilToolGui(
            root,
            settings_store=store,
            probe_discovery=lambda _openocd: StLinkDiscovery(()),
            mode="rtt_collector",
        )

        assert Path(gui.openocd_var.get()) == current_openocd
        assert Path(gui.scripts_var.get()) == current_scripts
        saved = gui._current_settings()
        assert saved.openocd_path == ""
        assert saved.scripts_dir == ""
    finally:
        root.destroy()


def test_rtt_collector_does_not_pin_the_only_probe_by_usb_location(tmp_path):
    import tkinter as tk

    from keiltool.core.stlink_probe import StLinkDiscovery, StLinkProbe
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import SettingsStore

    root = tk.Tk()
    root.withdraw()
    try:
        gui = KeilToolGui(
            root,
            settings_store=SettingsStore(tmp_path / "settings.json"),
            probe_discovery=lambda _openocd: StLinkDiscovery(
                (
                    StLinkProbe(
                        "usb:2-1.4",
                        0x3748,
                        adapter_usb_location="2-1.4",
                    ),
                )
            ),
            mode="rtt_collector",
        )
        root.update()

        assert gui._selected_probe_identity == ""
        assert gui.probe_choice_var.get().startswith("自动选择")
    finally:
        root.destroy()
