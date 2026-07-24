import importlib
import argparse
import queue
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest


def test_gui_module_imports_without_creating_a_root_window(monkeypatch):
    import tkinter

    def unexpected_root(*args, **kwargs):
        raise AssertionError("Importing the GUI must not create a Tk root window.")

    monkeypatch.setattr(tkinter, "Tk", unexpected_root)

    module = importlib.import_module("keiltool.gui.app")

    assert callable(module.launch_gui)
    assert module.KeilToolGui is not None


def test_cli_gui_parser_and_help_do_not_create_a_tk_root(monkeypatch, capsys):
    import tkinter

    from keiltool.cli import build_parser

    def unexpected_root(*args, **kwargs):
        raise AssertionError("Parsing GUI commands must not create a Tk root window.")

    monkeypatch.setattr(tkinter, "Tk", unexpected_root)

    args = build_parser().parse_args(["gui"])
    assert args.command == "gui"

    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["gui", "--help"])

    assert exit_info.value.code == 0
    assert "gui" in capsys.readouterr().out


def test_cmd_gui_lazily_imports_launcher_and_returns_after_close(monkeypatch):
    from keiltool import cli

    calls: list[str] = []
    gui = ModuleType("keiltool.gui")
    gui.launch_gui = lambda: calls.append("closed")
    monkeypatch.setitem(sys.modules, "keiltool.gui", gui)

    assert cli.cmd_gui(argparse.Namespace()) == 0
    assert calls == ["closed"]


def test_build_flash_request_accepts_hex_without_parsing_bin_address(tmp_path):
    from keiltool.gui.workbench_model import build_flash_request

    firmware = tmp_path / "application.hex"
    firmware.write_text(":00000001FF\n", encoding="ascii")

    request = build_flash_request(firmware, "not-used-for-hex")

    assert request.firmware == firmware
    assert request.base_address == 0x08000000


def test_build_flash_request_requires_existing_hex_or_bin(tmp_path):
    from keiltool.gui.workbench_model import build_flash_request

    unsupported = tmp_path / "application.elf"
    unsupported.write_bytes(b"elf")

    with pytest.raises(ValueError, match=r"\.hex or \.bin"):
        build_flash_request(unsupported, "0x08000000")
    with pytest.raises(ValueError, match="does not exist"):
        build_flash_request(tmp_path / "missing.hex", "0x08000000")


def test_build_flash_request_parses_bin_address(tmp_path):
    from keiltool.gui.workbench_model import build_flash_request

    firmware = tmp_path / "application.bin"
    firmware.write_bytes(b"\x00")

    request = build_flash_request(firmware, "0x08004000")

    assert request.base_address == 0x08004000


def test_build_rtt_request_uses_project_ram_in_auto_mode():
    from keiltool.gui.workbench_model import build_rtt_request

    request = build_rtt_request(
        manual=False,
        address="ignored",
        ram_origin=0x20000000,
        ram_size=0x10000,
        port="19021",
        channel="0",
    )

    assert request.scan_address == 0x20000000
    assert request.scan_size == 0x10000


def test_build_rtt_request_uses_small_scan_window_in_manual_mode():
    from keiltool.gui.workbench_model import build_rtt_request

    request = build_rtt_request(
        manual=True,
        address="0x20001000",
        ram_origin=None,
        ram_size=None,
        port="19022",
        channel="1",
    )

    assert request.scan_address == 0x20001000
    assert request.scan_size == 0x100
    assert request.port == 19022
    assert request.channel == 1


def test_build_rtt_log_paths_keeps_channel_and_openocd_evidence_together(tmp_path):
    from keiltool.gui.workbench_model import build_rtt_log_paths

    paths = build_rtt_log_paths(tmp_path, "Debug Target", "20260723-120000-000000")

    assert paths.channel == tmp_path / "rtt_Debug_Target_20260723-120000-000000.log"
    assert paths.stdout == tmp_path / "rtt_openocd_Debug_Target_20260723-120000-000000.out.log"
    assert paths.stderr == tmp_path / "rtt_openocd_Debug_Target_20260723-120000-000000.err.log"


def test_target_facts_display_maps_read_only_operational_fields():
    from keiltool.gui.workbench_model import target_facts_display

    display = target_facts_display(
        SimpleNamespace(
            device="GD32F303CC",
            flash_summary="FLASH: 0x08000000 (256K)",
            ram_summary="RAM: 0x20000000 (64K)",
            target_cfg="target/stm32f3x.cfg",
            resolution_reason="Verified family mapping.",
            resolution_status="family_mapping_verified",
        )
    )

    assert display.device == "GD32F303CC"
    assert display.flash == "FLASH: 0x08000000 (256K)"
    assert display.ram == "RAM: 0x20000000 (64K)"
    assert display.target_cfg == "target/stm32f3x.cfg"
    assert display.resolution == "Verified family mapping."


def test_target_facts_display_uses_placeholders_without_facts():
    from keiltool.gui.workbench_model import target_facts_display

    display = target_facts_display(None, empty_reason="请选择 Target")

    assert (display.device, display.flash, display.ram, display.target_cfg) == ("—", "—", "—", "—")
    assert display.resolution == "请选择 Target"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "manual": False,
                "address": "",
                "ram_origin": None,
                "ram_size": None,
                "port": "19021",
                "channel": "0",
            },
            "RAM",
        ),
        (
            {
                "manual": True,
                "address": "invalid",
                "ram_origin": None,
                "ram_size": None,
                "port": "19021",
                "channel": "0",
            },
            "valid integer",
        ),
    ],
)
def test_build_rtt_request_rejects_invalid_scan_settings(kwargs, message):
    from keiltool.gui.workbench_model import build_rtt_request

    with pytest.raises(ValueError, match=message):
        build_rtt_request(**kwargs)


def test_high_rate_rtt_poll_yields_to_unrelated_tk_callback():
    from keiltool.core.rtt import RttEvent
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.workbench_controller import BoundedEventPoller

    class FakeRoot:
        def __init__(self):
            self.callbacks = []

        def after(self, delay, callback):
            self.callbacks.append((delay, callback))

        def run_next(self):
            _delay, callback = self.callbacks.pop(0)
            callback()

    root = FakeRoot()
    unrelated_ran = []
    root.after(0, lambda: unrelated_ran.append(True))
    rtt_events = queue.Queue()
    for _index in range(5000):
        rtt_events.put(RttEvent("data", text="x"))
    handled = []
    gui = SimpleNamespace(
        _destroyed=False,
        _events=queue.Queue(),
        _rtt_session=SimpleNamespace(events=rtt_events),
        _event_poller=BoundedEventPoller(max_events=64, time_budget=1.0),
        _handle_ui_event=lambda event: None,
        _handle_rtt_event=handled.append,
        _update_elapsed=lambda: None,
        _poll_events=lambda: None,
        root=root,
    )

    KeilToolGui._poll_events(gui)

    assert len(handled) == 1
    assert handled[0].text == "x" * 64
    assert root.callbacks[-1][0] == 0
    root.run_next()
    assert unrelated_ran == [True]


def test_gui_applies_theme_and_filters_structured_rtt_records(tmp_path):
    import tkinter as tk

    from keiltool.core.rtt import RttEvent
    from keiltool.core.rtt_log import RttLevel
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import SettingsStore
    from keiltool.gui.theme import PALETTE

    root = tk.Tk()
    root.withdraw()
    gui = KeilToolGui(root, settings_store=SettingsStore(tmp_path / "settings.json"))
    try:
        assert gui.rtt_display_level_var.get() == "VERBOSE"
        assert tuple(gui.output.rtt_level_combo.cget("values")) == (
            "VERBOSE",
            "DEBUG",
            "INFO",
            "WARN",
            "ERROR",
            "ASSERT",
        )
        assert root.cget("background") == PALETTE["background"]
        assert gui.output._rtt_text.tag_cget("ERROR", "foreground") == PALETTE["error"]

        gui._handle_rtt_event(RttEvent("data", text="I/ready\n", level=RttLevel.INFO, terminal=0))
        gui._handle_rtt_event(RttEvent("data", text="D/loop\n", level=RttLevel.DEBUG, terminal=1))
        gui.rtt_display_level_var.set("INFO")
        gui._on_rtt_level_changed()

        assert gui.output._rtt_text.get("1.0", "end-1c") == "I/ready\n"
        assert gui.rtt_visible_counts_var.get() == "1 可见 / 2 缓存"
    finally:
        if not gui._destroyed:
            gui._on_close()


def test_gui_removes_visible_record_evicted_from_rtt_cache(tmp_path):
    import tkinter as tk

    from keiltool.core.rtt import RttEvent
    from keiltool.core.rtt_log import RttLevel
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.rtt_display import RttDisplayBuffer
    from keiltool.gui.settings import SettingsStore

    root = tk.Tk()
    root.withdraw()
    gui = KeilToolGui(root, settings_store=SettingsStore(tmp_path / "settings.json"))
    try:
        gui._rtt_display = RttDisplayBuffer(max_records=2)
        gui._clear_rtt_display()
        for text in ("I/one\n", "I/two\n", "I/three\n"):
            gui._handle_rtt_event(
                RttEvent("data", text=text, level=RttLevel.INFO, terminal=0)
            )

        assert gui.output._rtt_text.get("1.0", "end-1c") == "I/two\nI/three\n"
        assert gui.rtt_visible_counts_var.get() == "2 可见 / 2 缓存"
    finally:
        if not gui._destroyed:
            gui._on_close()
