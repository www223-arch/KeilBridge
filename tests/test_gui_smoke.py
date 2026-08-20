import importlib
import argparse
from pathlib import Path
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


def test_build_flash_read_request_uses_complete_primary_flash(tmp_path):
    from keiltool.gui.workbench_model import build_flash_read_request

    facts = SimpleNamespace(
        flash_origin=0x08000000,
        flash_size=0x40000,
        flash_range_complete=True,
    )
    output = tmp_path / "board-flash.bin"

    request = build_flash_read_request(facts, output)

    assert request.output == output
    assert request.address == 0x08000000
    assert request.size == 0x40000


def test_build_flash_read_request_rejects_unknown_flash_range(tmp_path):
    from keiltool.gui.workbench_model import build_flash_read_request

    facts = SimpleNamespace(
        flash_origin=None,
        flash_size=None,
        flash_range_complete=False,
    )

    with pytest.raises(ValueError, match="Flash range"):
        build_flash_read_request(facts, tmp_path / "board-flash.bin")


def test_build_flash_read_request_rejects_unverified_project_partition(tmp_path):
    from keiltool.gui.workbench_model import build_flash_read_request

    facts = SimpleNamespace(
        flash_origin=0x08005800,
        flash_size=150 * 1024,
        flash_range_complete=False,
    )

    with pytest.raises(ValueError, match="complete physical Flash"):
        build_flash_read_request(facts, tmp_path / "board-flash.bin")


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


def test_one_click_vofa_uses_dedicated_rtt_channel_and_ports(tmp_path, monkeypatch):
    import tkinter as tk

    import keiltool.gui.app as app
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.settings import SettingsStore

    executable = tmp_path / "vofa+.exe"
    executable.write_bytes(b"MZ")
    root = tk.Tk()
    root.withdraw()
    gui = KeilToolGui(root, settings_store=SettingsStore(tmp_path / "settings.json"))
    bridges = []
    sessions = []
    workers = []
    launches = []
    configurations = []

    class FakeBridge:
        def __init__(
            self,
            host,
            port,
            *,
            raw_output,
            reverse_output,
            expected_float_count,
            reverse_sink,
        ):
            self.host = host
            self.port = port
            self.raw_output = raw_output
            self.reverse_output = reverse_output
            self.expected_float_count = expected_float_count
            self.reverse_sink = reverse_sink
            self.started = False
            self.stats = SimpleNamespace(
                frames_received=0,
                frames_forwarded=0,
                frames_dropped=0,
                invalid_frames=0,
                clients_connected=0,
                active_clients=0,
                last_error="",
            )
            bridges.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    class FakeSession:
        def __init__(self, config, request, log_path, **kwargs):
            self.config = config
            self.request = request
            self.log_path = log_path
            self.kwargs = kwargs
            self.command = ["openocd", "rtt"]
            self.sent = []
            sessions.append(self)

        def start(self):
            pass

        def send_bytes(self, data):
            payload = bytes(data)
            self.sent.append(payload)
            return len(payload)

    facts = SimpleNamespace(
        device="GD32F303CC",
        ram_origin=0x20000000,
        ram_size=0x10000,
    )
    config = SimpleNamespace(
        target_cfg="target/stm32f3x.cfg",
        interface_cfg="interface/stlink.cfg",
    )
    gui.logs_dir_var.set(str(tmp_path / "logs"))
    gui.vofa_path_var.set(str(executable))
    gui.vofa_listen_var.set("127.0.0.1:1347")
    monkeypatch.setattr(gui, "_obtain_fresh_snapshot", lambda: SimpleNamespace(facts=facts))
    monkeypatch.setattr(gui, "_build_openocd_config", lambda _snapshot: config)
    monkeypatch.setattr(app, "VofaTcpBridge", FakeBridge)
    monkeypatch.setattr(app, "RttSession", FakeSession)
    monkeypatch.setattr(
        app,
        "prepare_installed_vofa_connection",
        lambda executable, host, port: configurations.append((executable, host, port))
        or SimpleNamespace(configured=True, changed=True, config_path=tmp_path / "vofa.json"),
    )
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda command, **kwargs: launches.append((command, kwargs)) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        gui,
        "_start_worker",
        lambda kind, action, owner=None: workers.append((kind, action, owner)),
    )

    try:
        gui._start_vofa_rtt()

        assert len(sessions) == 1
        assert sessions[0].request.channel == 1
        assert sessions[0].request.port == 19022
        assert sessions[0].request.expected_channel_name == "Scope"
        assert sessions[0].kwargs["parse_records"] is False
        assert bridges[0].host == "127.0.0.1"
        assert bridges[0].port == 1347
        assert bridges[0].raw_output.name == "rtt-justfloat.bin"
        assert bridges[0].reverse_output.name == "vofa-to-mcu.bin"
        assert bridges[0].expected_float_count == 15
        reverse_payload = b"\x00\x80\xffcommand"
        assert bridges[0].reverse_sink(reverse_payload) == len(reverse_payload)
        assert sessions[0].sent == [reverse_payload]
        assert bridges[0].started
        guide = sessions[0].log_path.parent / "scope-channels.txt"
        assert guide.is_file()
        assert "I0  = acc_g.x" in guide.read_text(encoding="utf-8")
        assert "I14 = euler_9dof_deg.yaw" in gui.output._openocd_text.get("1.0", "end")
        assert gui.vofa_verify_scope_name_var.get() is True
        assert "Scope" in gui.controls.vofa_verify_scope_check.cget("text")
        assert launches[0][0] == [str(executable.resolve())]
        assert configurations == [(executable.resolve(), "127.0.0.1", 1347)]
        assert "127.0.0.1:1347" in gui.vofa_connection_hint_var.get()
        assert "JustFloat" in gui.vofa_connection_hint_var.get()
        assert "双向" in gui.vofa_connection_hint_var.get()
        assert workers[0][0] == "rtt-start-settled"
        assert workers[0][2] is sessions[0]
    finally:
        if gui._vofa_bridge is not None:
            gui._vofa_bridge.stop()
        root.destroy()


def test_gui_applies_theme_and_filters_structured_rtt_records(tmp_path, monkeypatch):
    import tkinter as tk

    from keiltool.core.openocd_backend import ConnectionResult
    from keiltool.core.rtt import RttEvent
    from keiltool.core.rtt_log import RttLevel
    from keiltool.gui.app import KeilToolGui
    from keiltool.gui.operation_feedback import OperationFeedback, ProgressMode
    from keiltool.gui.rtt_display import RttDisplayBuffer
    from keiltool.gui.settings import SettingsStore
    from keiltool.gui.state import SessionState
    from keiltool.gui.theme import PALETTE

    root = tk.Tk()
    root.withdraw()
    gui = KeilToolGui(root, settings_store=SettingsStore(tmp_path / "settings.json"))
    try:
        assert gui.rtt_display_level_var.get() == "VERBOSE"
        assert gui.controls.vofa_start_button.cget("text") == "VOFA+ 曲线"
        assert tuple(gui.output.rtt_level_combo.cget("values")) == (
            "VERBOSE",
            "DEBUG",
            "INFO",
            "WARN",
            "ERROR",
            "ASSERT",
        )
        assert root.cget("background") == PALETTE["background"]
        assert gui.operation_status.winfo_reqheight() >= 96
        feedback = OperationFeedback()
        feedback.begin("检查连接", "OpenOCD 执行中", started_at=10.0)
        feedback.set_stage("OpenOCD 执行中", ProgressMode.INDETERMINATE)
        gui.operation_status.update(feedback, now=12.0)
        assert gui.operation_status.state_var.get() == "执行中"
        assert gui.operation_status.stage_var.get() == "OpenOCD 执行中"
        assert gui.operation_status.elapsed_var.get() == "00:00:02"
        assert str(gui.operation_status.progress.cget("mode")) == "indeterminate"

        feedback.fail("无法连接目标", detail="init mode failed", returncode=1, finished_at=13.0)
        gui.operation_status.update(feedback, now=20.0)
        assert gui.operation_status.state_var.get() == "失败"
        assert gui.operation_status.summary_var.get() == "无法连接目标"
        assert str(gui.operation_status.copy_button.cget("state")) == "normal"

        gui.output.select_openocd()
        assert gui.output.notebook.index("current") == 1

        info_dialogs = []
        error_dialogs = []
        monkeypatch.setattr(
            "keiltool.gui.app.messagebox.showinfo",
            lambda *args, **kwargs: info_dialogs.append((args, kwargs)),
        )
        monkeypatch.setattr(
            "keiltool.gui.app.messagebox.showerror",
            lambda *args, **kwargs: error_dialogs.append((args, kwargs)),
        )
        gui._begin_feedback("检查连接", "准备配置")
        gui.gate.begin(SessionState.CONNECT)
        gui._finish_connection(
            ConnectionResult(
                success=True,
                returncode=0,
                command=["openocd"],
                stdout="connected\n",
                stderr="",
                stdout_log=tmp_path / "connect.out.log",
                stderr_log=tmp_path / "connect.err.log",
                findings=[],
                outcome="succeeded",
            )
        )
        assert gui.operation_feedback.state.value == "succeeded"
        assert gui.operation_feedback.progress_value == 100
        assert info_dialogs == []

        gui.output.notebook.select(0)
        gui._begin_feedback("检查连接", "准备配置")
        gui.gate.begin(SessionState.CONNECT)
        gui._finish_connection(
            ConnectionResult(
                success=False,
                returncode=1,
                command=["openocd"],
                stdout="",
                stderr="init mode failed\n",
                stdout_log=tmp_path / "connect-fail.out.log",
                stderr_log=tmp_path / "connect-fail.err.log",
                findings=[],
                outcome="failed",
            )
        )
        assert gui.operation_feedback.state.value == "failed"
        assert gui.operation_feedback.returncode == 1
        assert gui.output.notebook.index("current") == 1
        assert error_dialogs == []
        assert gui.controls.flash_read_button.cget("text") == "读取完整 Flash"
        assert gui.output._rtt_text.tag_cget("ERROR", "foreground") == PALETTE["error"]
        label = next(
            value
            for value in gui.controls.device_combo.cget("values")
            if value.startswith("GD32F303CC ")
        )
        gui.device_choice_var.set(label)
        gui._select_catalog_device()
        assert gui._current_settings().device_name == "GD32F303CC"
        assert "官方目录" in gui.device_source_var.get()

        project_device = gui._catalog.lookup_any_vendor("GD32F303CC")
        assert project_device is not None
        gui.device_source_mode_var.set("project")
        gui.project_var.set("D:/firmware/app.uvprojx")
        gui.target_var.set("Dragon_debug")
        gui.firmware_var.set("D:/firmware/project.hex")
        gui._facts = SimpleNamespace(
            device="GD32F303CC",
            ram_origin=None,
            ram_size=None,
            ready=False,
            openocd_executable="",
            target_cfg="",
        )
        gui._refresh_controls()
        assert str(gui.controls.device_combo.cget("state")) == "disabled"

        other_label = next(
            value
            for value in gui.controls.device_combo.cget("values")
            if value.startswith("GD32F303ZK ")
        )
        gui.device_choice_var.set(other_label)
        gui._select_catalog_device()
        assert gui.device_choice_var.get() == gui._device_label(project_device)
        assert "Keil 工程" in gui.device_source_var.get()

        gui.device_source_mode_var.set("device")
        gui._change_device_source()
        assert gui.project_var.get() == "D:/firmware/app.uvprojx"
        assert gui.target_var.get() == ""
        assert gui.firmware_var.get() == ""
        assert gui._visible_fact_inputs().project == ""
        assert str(gui.controls.target_combo.cget("state")) == "disabled"
        assert str(gui.controls.device_combo.cget("state")) == "normal"

        gui.device_choice_var.set(other_label)
        gui._select_catalog_device()
        independent_inputs = gui._visible_fact_inputs()
        assert independent_inputs.project == ""
        assert independent_inputs.target == ""
        assert independent_inputs.device_name == "GD32F303ZK"
        gui.firmware_var.set("D:/firmware/device.bin")

        loaded_projects = []
        monkeypatch.setattr(
            gui,
            "_load_project",
            lambda path, restored=False: loaded_projects.append(path),
        )
        gui.device_source_mode_var.set("project")
        gui._change_device_source()
        assert gui.target_var.get() == "Dragon_debug"
        assert gui.firmware_var.get() == "D:/firmware/project.hex"
        assert gui._visible_fact_inputs().project == "D:/firmware/app.uvprojx"
        assert loaded_projects == [Path("D:/firmware/app.uvprojx")]
        saved = gui._current_settings()
        assert saved.device_source_mode == "project"
        assert saved.project_firmware == "D:/firmware/project.hex"
        assert saved.device_firmware == "D:/firmware/device.bin"
        assert saved.device_name == "GD32F303ZK"
        gui.vofa_path_var.set("D:/tools/VOFA+/vofa+.exe")
        gui.vofa_listen_var.set("127.0.0.1:1347")
        saved = gui._current_settings()
        assert saved.vofa_path == "D:/tools/VOFA+/vofa+.exe"
        assert saved.vofa_listen == "127.0.0.1:1347"

        gui.output.clear_openocd()
        gui.output.append_openocd("alpha\nbeta\n")
        view = gui.output.openocd_view
        view.text.tag_add("sel", "1.0", "1.5")
        assert view.copy_selected() == "alpha"
        assert view.copy_all() == "alpha\nbeta\n"
        assert tuple(view.menu.entrycget(index, "label") for index in range(3)) == (
            "复制",
            "全选",
            "复制全部",
        )

        gui._handle_rtt_event(RttEvent("data", text="I/ready\n", level=RttLevel.INFO, terminal=0))
        gui._handle_rtt_event(RttEvent("data", text="D/loop\n", level=RttLevel.DEBUG, terminal=1))
        gui.rtt_display_level_var.set("INFO")
        gui._on_rtt_level_changed()

        assert gui.output._rtt_text.get("1.0", "end-1c") == "I/ready\n"
        assert gui.rtt_visible_counts_var.get() == "1 可见 / 2 缓存"

        forwarded = []
        gui._vofa_bridge = SimpleNamespace(
            feed=forwarded.append,
            stats=SimpleNamespace(
                frames_received=1,
                frames_forwarded=1,
                frames_dropped=0,
                invalid_frames=0,
                clients_connected=1,
                active_clients=1,
                last_error="",
            ),
        )
        gui._handle_rtt_event(RttEvent("raw", data=b"\x00\x00\x80?\x00\x00\x80\x7f"))
        assert forwarded == [b"\x00\x00\x80?\x00\x00\x80\x7f"]
        assert "1 帧" in gui.counts_var.get()
        gui._vofa_bridge = None

        gui._rtt_display = RttDisplayBuffer(max_records=2)
        gui._clear_rtt_display()
        for text in ("I/one\n", "I/two\n", "I/three\n"):
            gui._handle_rtt_event(
                RttEvent("data", text=text, level=RttLevel.INFO, terminal=0)
            )

        assert gui.output._rtt_text.get("1.0", "end-1c") == "I/two\nI/three\n"
        assert gui.rtt_visible_counts_var.get() == "2 可见 / 2 缓存"

        gui._begin_feedback("RTT 日志采集", "扫描 RTT 控制块")
        gui.gate.begin(SessionState.RTT_SCAN)
        gui._handle_rtt_event(RttEvent("connected", message="RTT connected"))
        assert gui.operation_feedback.state.value == "running"
        assert gui.operation_feedback.stage == "正在采集 RTT 日志"
        gui._handle_rtt_event(RttEvent("data", text="I/live\n", level=RttLevel.INFO, terminal=0))
        assert "字节" in gui.operation_feedback.summary
        assert "行" in gui.operation_feedback.summary
        gui.gate.finish()

        stopped_sessions = []
        session = SimpleNamespace()
        gui._rtt_session = session
        gui._rtt_lifecycle.begin_start(session)
        gui._rtt_lifecycle.start_settled(session)
        gui.gate.begin(SessionState.RTT)
        gui._begin_feedback("RTT 日志采集", "正在采集 RTT 日志")
        gui._rtt_bytes = 128
        gui._rtt_lines = 4
        monkeypatch.setattr(gui, "_dispatch_rtt_stop", stopped_sessions.append)
        gui._stop_rtt()
        assert stopped_sessions == [session]
        assert gui.operation_feedback.state.value == "stopping"
        gui._handle_rtt_event(RttEvent("stopped", message="clean", outcome="clean"))
        assert gui.operation_feedback.state.value == "succeeded"
        assert "128 字节 / 4 行" in gui.operation_feedback.summary

        incomplete_session = SimpleNamespace()
        gui._rtt_session = incomplete_session
        gui._rtt_lifecycle.begin_start(incomplete_session)
        gui._rtt_lifecycle.start_settled(incomplete_session)
        gui.gate.begin(SessionState.RTT)
        gui._begin_feedback("RTT 日志采集", "正在采集 RTT 日志")
        gui._handle_rtt_event(
            RttEvent("stopped", message="cleanup incomplete", outcome="incomplete")
        )
        assert gui.operation_feedback.state.value == "incomplete"
        assert error_dialogs == []
        gui._handle_rtt_event(RttEvent("stopped", message="clean", outcome="clean"))

        failed_session = SimpleNamespace()
        gui._rtt_session = failed_session
        gui._rtt_lifecycle.begin_start(failed_session)
        gui.gate.begin(SessionState.RTT_SCAN)
        gui._begin_feedback("RTT 日志采集", "扫描 RTT 控制块")
        gui._handle_worker_error(
            "rtt-start-settled",
            RuntimeError("RTT startup worker failed"),
            failed_session,
        )
        assert gui.operation_feedback.state.value == "failed"
        assert "RTT startup worker failed" in gui.operation_feedback.detail
        gui._handle_rtt_event(
            RttEvent("stopped", message="startup failed", outcome="startup_failed")
        )
        assert gui.operation_feedback.state.value == "failed"
        assert error_dialogs == []

        firmware = tmp_path / "external.bin"
        firmware.write_bytes(b"version-1")
        gui.device_source_mode_var.set("device")
        gui.firmware_var.set(str(firmware))
        gui._current_firmware_freshness().accept(firmware)
        firmware.write_bytes(b"version-2-longer")
        reload_answers = []
        monkeypatch.setattr(
            "keiltool.gui.app.messagebox.askyesno",
            lambda title, message, **_kwargs: reload_answers.append((title, message)) or False,
        )

        assert gui._check_firmware_external_change() is False
        assert gui._current_firmware_freshness().stale
        assert len(reload_answers) == 1
        assert "SHA-256" in reload_answers[0][1]
        assert gui._check_firmware_external_change() is False
        assert len(reload_answers) == 1

        gui._current_firmware_freshness().accept(firmware)
        firmware.write_bytes(b"version-3")
        monkeypatch.setattr(
            "keiltool.gui.app.messagebox.askyesno",
            lambda *_args, **_kwargs: True,
        )
        assert gui._check_firmware_external_change() is True
        assert not gui._current_firmware_freshness().stale

        read_output = tmp_path / "complete-flash.bin"
        read_snapshot = SimpleNamespace(
            facts=SimpleNamespace(
                device="GD32F303CC",
                flash_origin=0x08000000,
                flash_size=0x40000,
                flash_range_complete=True,
            ),
            target=None,
        )
        read_config = SimpleNamespace(interface_cfg="interface/stlink.cfg", target_cfg="target/stm32f3x.cfg")
        dispatched = []
        monkeypatch.setattr(gui, "_obtain_fresh_snapshot", lambda: read_snapshot)
        monkeypatch.setattr(gui, "_build_openocd_config", lambda _snapshot: read_config)
        monkeypatch.setattr(gui, "_log_dir", lambda: tmp_path)
        monkeypatch.setattr(
            "keiltool.gui.app.filedialog.asksaveasfilename",
            lambda **_kwargs: str(read_output),
        )
        monkeypatch.setattr(
            gui,
            "_begin_one_shot",
            lambda state, operation: dispatched.append(("begin", state, operation)),
        )
        monkeypatch.setattr(
            gui,
            "_start_worker",
            lambda kind, action, *, owner=None: dispatched.append((kind, action, owner)),
        )

        gui._read_flash()

        assert dispatched[0][1] is SessionState.FLASH_READ
        assert dispatched[0][2]._background is True
        assert dispatched[1][0] == "flash-read-result"
        assert gui.operation_feedback.task == "读取完整 Flash"
        assert gui.operation_feedback.state.value == "running"
        assert gui.operation_feedback.stage == "OpenOCD 执行中"
        assert gui.operation_feedback.log_dir is not None

        error_dialogs.clear()
        monkeypatch.setattr(
            gui,
            "_obtain_fresh_snapshot",
            lambda: (_ for _ in ()).throw(ValueError("缺少目标芯片配置")),
        )
        gui._check_connection()
        assert gui.operation_feedback.state.value == "failed"
        assert gui.operation_feedback.summary == "无法检查连接"
        assert "缺少目标芯片配置" in gui.operation_feedback.detail
        assert error_dialogs == []
    finally:
        if not gui._destroyed:
            gui._on_close()
