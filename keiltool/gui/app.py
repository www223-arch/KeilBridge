from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, cast

from keiltool.core.openocd_backend import (
    ConnectionResult,
    FlashResult,
    OpenOcdConfig,
    run_connection_check,
    run_flash,
)
from keiltool.core.rtt import RttEvent, RttSession
from keiltool.gui.project_config import (
    ProjectTargetFacts,
    load_project_targets,
)
from keiltool.gui.settings import GuiSettings, SettingsStore
from keiltool.gui.state import BusySessionError, SessionState, TaskGate
from keiltool.gui.widgets import ConfigurationPane, OutputNotebook
from keiltool.gui.workbench_controller import (
    FactInputs,
    FreshnessController,
    LifecycleAction,
    RttLifecycleController,
    RttPhase,
    SaveFailureAction,
    VerifiedSnapshot,
    resolve_verified_snapshot,
    save_failure_action,
)
from keiltool.gui.workbench_model import (
    RttLogPaths,
    TargetFactsDisplay,
    build_flash_request,
    build_rtt_log_paths,
    build_rtt_request,
    int_or_default,
    is_firmware_ready,
    is_target_ready,
    target_facts_display,
)


_BUSY_STATES = frozenset(
    {
        SessionState.CONNECT,
        SessionState.FLASH,
        SessionState.RTT_SCAN,
        SessionState.RTT,
        SessionState.STOPPING,
    }
)

_STATE_TEXT = {
    SessionState.IDLE: "空闲",
    SessionState.CONNECT: "检查连接",
    SessionState.FLASH: "烧录中",
    SessionState.RTT_SCAN: "RTT 扫描中",
    SessionState.RTT: "RTT 采集中",
    SessionState.STOPPING: "停止中",
    SessionState.FAILED: "失败",
}


@dataclass(frozen=True, slots=True)
class _UiEvent:
    kind: str
    value: object = None


class KeilToolGui:
    """Tkinter workbench for independent ST-Link flash and RTT operations."""

    def __init__(self, root: tk.Tk, *, settings_store: SettingsStore | None = None) -> None:
        self.root = root
        self.settings_store = settings_store or SettingsStore()
        self.gate = TaskGate()
        self._freshness = FreshnessController()
        self._rtt_lifecycle = RttLifecycleController()
        self._events: queue.Queue[_UiEvent] = queue.Queue()
        self._facts: ProjectTargetFacts | None = None
        self._rtt_session: RttSession | None = None
        self._rtt_log_paths: RttLogPaths | None = None
        self._rtt_started_at: float | None = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self._closing = False
        self._destroyed = False

        settings = self.settings_store.load()
        self._create_variables(settings)
        self._configure_window()
        self._build_layout()
        self._bind_updates()
        self._refresh_controls()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._poll_events)
        if settings.project:
            self.root.after_idle(lambda: self._load_project(Path(settings.project), restored=True))

    def _create_variables(self, settings: GuiSettings) -> None:
        self.project_var = tk.StringVar(value=settings.project)
        self.target_var = tk.StringVar(value=settings.target)
        self.device_var = tk.StringVar(value="—")
        self.flash_summary_var = tk.StringVar(value="—")
        self.ram_summary_var = tk.StringVar(value="—")
        self.target_cfg_var = tk.StringVar(value="—")
        self.resolution_var = tk.StringVar(value="请选择 Keil 工程")
        self.firmware_var = tk.StringVar(value=settings.firmware)
        self.bin_address_var = tk.StringVar(value=settings.bin_address)
        self.rtt_manual_var = tk.BooleanVar(value=bool(settings.rtt_address))
        self.rtt_address_var = tk.StringVar(value=settings.rtt_address)
        self.rtt_channel_var = tk.StringVar(value=str(settings.rtt_channel))
        self.logs_dir_var = tk.StringVar(value=settings.logs_dir)
        self.openocd_var = tk.StringVar(value=settings.openocd_path)
        self.scripts_var = tk.StringVar(value=settings.scripts_dir)
        self.target_override_var = tk.StringVar(value=settings.target_override)
        self.rtt_port_var = tk.StringVar(value=str(settings.rtt_port))
        self.rtt_timeout_var = tk.StringVar(value=str(settings.rtt_timeout_ms))
        self.status_var = tk.StringVar(value=_STATE_TEXT[SessionState.IDLE])
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.counts_var = tk.StringVar(value="0 字节 / 0 行")

    def _configure_window(self) -> None:
        self.root.title("KeilTool ST-Link 工作台")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 720)
        self.root.columnconfigure(0, minsize=420, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_layout(self) -> None:
        left = ttk.Frame(self.root, padding=(10, 10, 8, 8))
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root, padding=(0, 10, 10, 8))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.controls = ConfigurationPane(left, self)
        self.controls.grid(row=0, column=0, sticky="nsew")

        self.output = OutputNotebook(
            right,
            elapsed_var=self.elapsed_var,
            counts_var=self.counts_var,
            open_logs_dir=self._open_logs_dir,
        )
        self.output.grid(row=0, column=0, sticky="nsew")

        status = ttk.Frame(self.root, padding=(10, 4, 10, 6))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Separator(status).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(status, text="状态").grid(row=1, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var).grid(row=1, column=1, sticky="w", padx=(10, 0))
        status.columnconfigure(1, weight=1)

    def _bind_updates(self) -> None:
        controls = self.controls
        controls.project_button.configure(command=self._choose_project)
        controls.firmware_button.configure(command=self._choose_firmware)
        controls.logs_button.configure(command=self._choose_logs_dir)
        controls.openocd_button.configure(command=self._choose_openocd)
        controls.scripts_button.configure(command=self._choose_scripts_dir)
        controls.override_button.configure(command=self._choose_target_override)
        controls.connect_button.configure(command=self._check_connection)
        controls.flash_button.configure(command=self._flash)
        controls.rtt_start_button.configure(command=self._start_rtt)
        controls.rtt_stop_button.configure(command=self._stop_rtt)
        controls.auto_radio.configure(command=self._refresh_controls)
        controls.manual_radio.configure(command=self._refresh_controls)
        controls.target_combo.bind("<<ComboboxSelected>>", lambda _event: self._resolve_selected_target())
        self.firmware_var.trace_add("write", lambda *_args: self._refresh_controls())
        for variable in (
            self.project_var,
            self.target_var,
            self.openocd_var,
            self.scripts_var,
            self.target_override_var,
        ):
            variable.trace_add("write", self._on_fact_input_changed)
        controls.project_entry.bind("<FocusOut>", lambda _event: self._load_project(Path(self.project_var.get().strip())))
        controls.project_entry.bind("<Return>", lambda _event: self._load_project(Path(self.project_var.get().strip())))
        for entry in (controls.openocd_entry, controls.scripts_entry, controls.override_entry):
            entry.bind("<FocusOut>", lambda _event: self._resolve_selected_target())
            entry.bind("<Return>", lambda _event: self._resolve_selected_target())

    def _visible_fact_inputs(self) -> FactInputs:
        return FactInputs(
            project=self.project_var.get().strip(),
            target=self.target_var.get().strip(),
            openocd=self.openocd_var.get().strip(),
            scripts=self.scripts_var.get().strip(),
            target_override=self.target_override_var.get().strip(),
        )

    def _on_fact_input_changed(self, *_args: object) -> None:
        if self._freshness.observe(self._visible_fact_inputs()):
            self._facts = None
            self._clear_facts("配置已更改，请重新解析")
            self._refresh_controls()

    def _choose_project(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 Keil 工程",
            filetypes=[("Keil 工程", "*.uvprojx"), ("所有文件", "*.*")],
        )
        if path:
            self.project_var.set(path)
            self._load_project(Path(path))

    def _choose_firmware(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择固件",
            filetypes=[("固件", "*.hex *.bin"), ("HEX", "*.hex"), ("BIN", "*.bin")],
        )
        if path:
            self.firmware_var.set(path)

    def _choose_logs_dir(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="选择日志目录")
        if path:
            self.logs_dir_var.set(path)

    def _choose_openocd(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 OpenOCD",
            filetypes=[("OpenOCD", "openocd.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if path:
            self.openocd_var.set(path)
            self._resolve_selected_target()

    def _choose_scripts_dir(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="选择 OpenOCD scripts 目录")
        if path:
            self.scripts_var.set(path)
            self._resolve_selected_target()

    def _choose_target_override(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 OpenOCD target cfg",
            filetypes=[("OpenOCD 配置", "*.cfg"), ("所有文件", "*.*")],
        )
        if path:
            self.target_override_var.set(path)
            self._resolve_selected_target()

    def _load_project(self, path: Path, *, restored: bool = False) -> None:
        if self._hardware_busy():
            self._show_busy()
            return
        try:
            loaded = load_project_targets(path)
        except Exception as exc:
            self._facts = None
            self.controls.target_combo.configure(values=())
            self._clear_facts(f"工程读取失败: {exc}")
            self._append_openocd(f"[工程] {path}\n读取失败: {exc}\n\n")
            if not restored:
                messagebox.showerror("工程读取失败", str(exc), parent=self.root)
            self._refresh_controls()
            return

        names = tuple(target.name for target in loaded.targets)
        self.controls.target_combo.configure(values=names)
        requested = self.target_var.get()
        self.target_var.set(requested if requested in names else (names[0] if names else ""))
        if not names:
            self._facts = None
            self._clear_facts("工程中没有可用 Target")
            self._refresh_controls()
            return
        self._resolve_selected_target()

    def _resolve_selected_target(self) -> None:
        if self._hardware_busy():
            return
        try:
            self._obtain_fresh_snapshot()
        except Exception as exc:
            self._facts = None
            self._freshness.observe(self._visible_fact_inputs())
            self._clear_facts(f"Target 解析失败: {exc}")
            self._refresh_controls()
            return
        self._refresh_controls()

    def _obtain_fresh_snapshot(self) -> VerifiedSnapshot:
        visible = self._visible_fact_inputs()
        self._freshness.observe(visible)
        snapshot = resolve_verified_snapshot(visible)
        facts = cast(ProjectTargetFacts, snapshot.facts)
        if not visible.openocd and facts.openocd_executable:
            self.openocd_var.set(facts.openocd_executable)
        if not visible.scripts and facts.openocd_scripts:
            self.scripts_var.set(facts.openocd_scripts)

        current = self._visible_fact_inputs()
        snapshot = VerifiedSnapshot(
            key=current,
            loaded_project=snapshot.loaded_project,
            target=snapshot.target,
            facts=facts,
        )
        self._freshness.observe(current)
        self._freshness.accept(snapshot)
        self._facts = facts
        self._apply_facts_display(target_facts_display(facts))
        if not self.logs_dir_var.get().strip():
            self.logs_dir_var.set(facts.default_log_dir)
        return snapshot

    def _clear_facts(self, reason: str) -> None:
        self._apply_facts_display(target_facts_display(None, empty_reason=reason))

    def _apply_facts_display(self, display: TargetFactsDisplay) -> None:
        self.device_var.set(display.device)
        self.flash_summary_var.set(display.flash)
        self.ram_summary_var.set(display.ram)
        self.target_cfg_var.set(display.target_cfg)
        self.resolution_var.set(display.resolution)

    @staticmethod
    def _build_openocd_config(snapshot: VerifiedSnapshot) -> OpenOcdConfig:
        facts = cast(ProjectTargetFacts, snapshot.facts)
        if not is_target_ready(facts):
            reason = facts.resolution_reason if facts else "请先选择并解析 Keil Target。"
            raise ValueError(reason)
        return OpenOcdConfig(
            executable=Path(facts.openocd_executable),
            scripts_dir=Path(facts.openocd_scripts) if facts.openocd_scripts else None,
            interface_cfg=facts.interface_cfg,
            target_cfg=facts.target_cfg,
        )

    def _log_dir(self) -> Path:
        value = self.logs_dir_var.get().strip()
        if not value and self._facts:
            value = self._facts.default_log_dir
            self.logs_dir_var.set(value)
        if not value:
            raise ValueError("请选择日志目录。")
        return Path(value).expanduser()

    def _check_connection(self) -> None:
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            log_dir = self._log_dir()
            target = snapshot.target
            self.gate.begin(SessionState.CONNECT)
        except BusySessionError:
            self._show_busy()
            return
        except Exception as exc:
            messagebox.showerror("无法检查连接", str(exc), parent=self.root)
            return
        self._set_status()
        self._refresh_controls()
        self._start_worker(
            "connection-result",
            lambda: run_connection_check(config, log_dir, target=target),
        )

    def _flash(self) -> None:
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            request = build_flash_request(self.firmware_var.get().strip(), self.bin_address_var.get().strip())
            log_dir = self._log_dir()
            target = snapshot.target
        except Exception as exc:
            messagebox.showerror("无法烧录", str(exc), parent=self.root)
            return

        facts = cast(ProjectTargetFacts, snapshot.facts)
        address_line = (
            f"\nBIN 地址: 0x{request.base_address:08X}"
            if request.firmware.suffix.lower() == ".bin"
            else ""
        )
        size = request.firmware.stat().st_size
        confirmed = messagebox.askokcancel(
            "确认烧录",
            (
                f"Device: {facts.device if facts else '—'}\n"
                f"Target cfg: {config.target_cfg}\n"
                f"固件: {request.firmware.resolve()}\n"
                f"大小: {size:,} 字节"
                f"{address_line}\n\n"
                "将执行烧录、校验和复位。"
            ),
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.gate.begin(SessionState.FLASH)
        except BusySessionError:
            self._show_busy()
            return
        self._set_status()
        self._refresh_controls()
        self._start_worker(
            "flash-result",
            lambda: run_flash(config, request, log_dir, target=target),
        )

    def _start_rtt(self) -> None:
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            facts = cast(ProjectTargetFacts, snapshot.facts)
            request = build_rtt_request(
                manual=self.rtt_manual_var.get(),
                address=self.rtt_address_var.get().strip(),
                ram_origin=facts.ram_origin,
                ram_size=facts.ram_size,
                port=self.rtt_port_var.get().strip(),
                channel=self.rtt_channel_var.get().strip(),
            )
            timeout_ms = int(self.rtt_timeout_var.get().strip())
            if timeout_ms <= 0:
                raise ValueError("RTT 扫描超时必须大于 0。")
            log_dir = self._log_dir()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            log_paths = build_rtt_log_paths(log_dir, self.target_var.get() or "target", stamp)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_paths.stdout.write_text("", encoding="utf-8", newline="\n")
            log_paths.stderr.write_text("", encoding="utf-8", newline="\n")
            session = RttSession(
                config,
                request,
                log_paths.channel,
                connect_timeout=timeout_ms / 1000.0,
            )
            self.gate.begin(SessionState.RTT_SCAN)
            try:
                self._rtt_lifecycle.begin_start(session)
            except Exception:
                self.gate.finish()
                raise
        except BusySessionError:
            self._show_busy()
            return
        except Exception as exc:
            messagebox.showerror("无法启动 RTT", str(exc), parent=self.root)
            return

        self._rtt_session = session
        self._rtt_log_paths = log_paths
        self._rtt_started_at = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self.elapsed_var.set("00:00:00")
        self.counts_var.set("0 字节 / 0 行")
        self._append_openocd(
            "[RTT]\n"
            f"命令: {subprocess.list2cmdline(session.command)}\n"
            f"RTT 日志: {log_paths.channel}\n"
            f"OpenOCD stdout: {log_paths.stdout}\n"
            f"OpenOCD stderr: {log_paths.stderr}\n"
        )
        self._set_status()
        self._refresh_controls()
        self._start_worker("rtt-start-settled", session.start, owner=session)

    def _stop_rtt(self) -> None:
        session = self._rtt_session
        if session is None:
            return
        action = self._rtt_lifecycle.request_stop()
        if action is LifecycleAction.STOP_SESSION:
            self._dispatch_rtt_stop(session)
        elif self._rtt_lifecycle.phase is RttPhase.STOP_PENDING:
            self.status_var.set("RTT 启动完成后停止")
            self._refresh_controls()

    def _dispatch_rtt_stop(self, session: RttSession) -> None:
        if session is not self._rtt_session:
            return
        if self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT}:
            self.gate.begin_stopping()
        self._set_status()
        self._refresh_controls()
        self._start_worker("rtt-stop-settled", session.stop, owner=session)

    def _start_worker(
        self,
        success_kind: str,
        action: Callable[[], object],
        *,
        owner: object | None = None,
    ) -> None:
        def run() -> None:
            try:
                value = action()
            except BaseException as exc:
                self._events.put(_UiEvent("worker-error", (success_kind, exc, owner)))
            else:
                self._events.put(_UiEvent(success_kind, (owner, value) if owner is not None else value))

        threading.Thread(target=run, name=f"keiltool-gui-{success_kind}", daemon=True).start()

    def _poll_events(self) -> None:
        if self._destroyed:
            return
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            self._handle_ui_event(event)
        session = self._rtt_session
        if session is not None:
            while True:
                try:
                    event = session.events.get_nowait()
                except queue.Empty:
                    break
                self._handle_rtt_event(event)
        self._update_elapsed()
        if not self._destroyed:
            self.root.after(50, self._poll_events)

    def _handle_ui_event(self, event: _UiEvent) -> None:
        if event.kind == "connection-result":
            self._finish_connection(event.value)
        elif event.kind == "flash-result":
            self._finish_flash(event.value)
        elif event.kind == "worker-error":
            operation, error, owner = event.value
            self._handle_worker_error(operation, error, owner)
        elif event.kind == "rtt-start-settled":
            session, _value = event.value
            action = self._rtt_lifecycle.start_settled(session)
            if action is LifecycleAction.STOP_SESSION:
                self._dispatch_rtt_stop(cast(RttSession, session))
            self._finish_close_if_ready()
        elif event.kind == "rtt-stop-settled":
            self._finish_close_if_ready()

    def _finish_connection(self, value: object) -> None:
        if not isinstance(value, ConnectionResult):
            self._handle_worker_error("connection-result", RuntimeError("连接检查返回了无效结果。"), None)
            return
        self._render_openocd_result("连接检查", value)
        if value.success:
            self.gate.finish()
            self.status_var.set("连接检查成功")
            if not self._closing:
                messagebox.showinfo("连接检查", "已确认 ST-Link 和目标内核连接。", parent=self.root)
        else:
            self.gate.fail()
            self.status_var.set("连接检查失败")
            if not self._closing:
                messagebox.showerror("连接检查失败", self._result_error_summary(value), parent=self.root)
        self._refresh_controls()
        self._finish_close_if_ready()

    def _finish_flash(self, value: object) -> None:
        if not isinstance(value, FlashResult):
            self._handle_worker_error("flash-result", RuntimeError("烧录返回了无效结果。"), None)
            return
        self._render_openocd_result("烧录并校验", value)
        if value.success:
            self.gate.finish()
            self.status_var.set("烧录并校验成功")
            if not self._closing:
                messagebox.showinfo("烧录完成", "固件烧录和校验均已成功。", parent=self.root)
        else:
            self.gate.fail()
            self.status_var.set("烧录或校验失败")
            if not self._closing:
                messagebox.showerror("烧录失败", self._result_error_summary(value), parent=self.root)
        self._refresh_controls()
        self._finish_close_if_ready()

    def _handle_worker_error(self, operation: object, error: object, owner: object | None) -> None:
        message = str(error)
        self._append_openocd(f"\n[后台任务失败] {operation}: {message}\n")
        if str(operation).startswith("rtt") and owner is not None:
            operation_name = "start" if operation == "rtt-start-settled" else "stop"
            action = self._rtt_lifecycle.worker_failed(owner, operation_name)
            if action is LifecycleAction.STOP_SESSION:
                self._dispatch_rtt_stop(cast(RttSession, owner))
        else:
            self.gate.fail()
        self.status_var.set(f"失败: {message}")
        self._refresh_controls()
        if not self._closing:
            messagebox.showerror("任务失败", message, parent=self.root)
        self._finish_close_if_ready()

    def _handle_rtt_event(self, event: RttEvent) -> None:
        if event.kind == "openocd":
            self._append_openocd(event.text)
            self._persist_rtt_openocd_event(event)
        elif event.kind == "data":
            self.output.append_rtt(event.text)
            self._rtt_bytes += len(event.text.encode("utf-8", errors="replace"))
            self._rtt_lines += event.text.count("\n")
            self.counts_var.set(f"{self._rtt_bytes:,} 字节 / {self._rtt_lines:,} 行")
        elif event.kind == "connected":
            if self.gate.state is SessionState.RTT_SCAN:
                self.gate.finish()
                self.gate.begin(SessionState.RTT)
            self._rtt_started_at = time.monotonic()
            self.status_var.set("RTT 采集中")
            self._append_openocd(f"{event.message}\n")
            self._refresh_controls()
        elif event.kind in {"error", "eof"}:
            self._append_openocd(f"[RTT] {event.message}\n")
            self.status_var.set(f"RTT 异常: {event.message}")
            self.root.after_idle(self._stop_rtt)
        elif event.kind == "stopped":
            session = self._rtt_session
            if session is None:
                return
            self._append_openocd(f"[RTT] {event.message} ({event.outcome})\n\n")
            action = self._rtt_lifecycle.terminal(session, event.outcome)
            if self._rtt_lifecycle.phase is RttPhase.INCOMPLETE:
                if self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT}:
                    self.gate.begin_stopping()
                self.status_var.set("RTT 清理不完整，请点击“停止采集”重试")
                messagebox.showerror(
                    "RTT 清理不完整",
                    "OpenOCD 或 RTT 工作线程尚未完全退出。硬件操作和关闭已阻止，请点击“停止采集”重试清理。",
                    parent=self.root,
                )
            elif action is LifecycleAction.RELEASE_SESSION:
                if event.outcome == "startup_failed":
                    self.gate.fail()
                    self.status_var.set("RTT 启动失败")
                else:
                    self.gate.finish()
                    self.status_var.set("RTT 已停止")
                self._rtt_session = None
                self._rtt_log_paths = None
            else:
                return
            self._rtt_started_at = None
            self._refresh_controls()
            self._finish_close_if_ready()

    def _persist_rtt_openocd_event(self, event: RttEvent) -> None:
        paths = self._rtt_log_paths
        if paths is None or not event.text:
            return
        path = paths.stdout if event.stream == "stdout" else paths.stderr
        try:
            with path.open("a", encoding="utf-8", newline="\n") as log_file:
                log_file.write(event.text)
        except OSError as exc:
            self.status_var.set(f"OpenOCD 日志写入失败: {exc}")

    def _render_openocd_result(self, title: str, result: ConnectionResult | FlashResult) -> None:
        command = subprocess.list2cmdline(result.command)
        self._append_openocd(
            f"\n[{title}]\n"
            f"命令: {command}\n"
            f"退出码: {result.returncode}\n"
            f"stdout 日志: {result.stdout_log}\n"
            f"stderr 日志: {result.stderr_log}\n"
            "----- stdout -----\n"
            f"{result.stdout}"
            f"{'' if result.stdout.endswith(chr(10)) or not result.stdout else chr(10)}"
            "----- stderr -----\n"
            f"{result.stderr}"
            f"{'' if result.stderr.endswith(chr(10)) or not result.stderr else chr(10)}"
        )
        if result.findings:
            self._append_openocd("----- Doctor -----\n")
            for finding in result.findings:
                self._append_openocd(
                    f"[{finding.severity}] {finding.code}: {finding.title}\n"
                    f"{finding.message}\n"
                )
        self._append_openocd("\n")

    @staticmethod
    def _result_error_summary(result: ConnectionResult | FlashResult) -> str:
        findings = "\n".join(
            f"• {finding.title}: {finding.message}" for finding in result.findings
        )
        detail = findings or f"OpenOCD 退出码: {result.returncode}"
        return (
            f"{detail}\n\n"
            f"stdout: {result.stdout_log}\n"
            f"stderr: {result.stderr_log}"
        )

    def _refresh_controls(self) -> None:
        busy = self._hardware_busy()
        controls = self.controls
        for widget, idle_state in controls.editable_widgets:
            state = "disabled" if busy else idle_state
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

        firmware_is_hex = Path(self.firmware_var.get().strip()).suffix.lower() == ".hex"
        controls.bin_address_entry.configure(state="disabled" if busy or firmware_is_hex else "normal")
        controls.rtt_address_entry.configure(
            state="normal" if not busy and self.rtt_manual_var.get() else "disabled"
        )

        ready = self._freshness.is_current(self._visible_fact_inputs()) and is_target_ready(self._facts)
        idle = not busy
        controls.connect_button.configure(state="normal" if idle and ready else "disabled")
        controls.flash_button.configure(
            state="normal" if idle and ready and is_firmware_ready(self.firmware_var.get().strip()) else "disabled"
        )
        auto_rtt_ready = bool(self._facts and self._facts.ram_origin is not None and self._facts.ram_size)
        rtt_fields_ready = self.rtt_manual_var.get() or auto_rtt_ready
        controls.rtt_start_button.configure(
            state="normal" if idle and ready and rtt_fields_ready else "disabled"
        )
        controls.rtt_stop_button.configure(
            state=(
                "normal"
                if self._rtt_lifecycle.phase in {RttPhase.STARTING, RttPhase.RUNNING, RttPhase.INCOMPLETE}
                else "disabled"
            )
        )

    def _hardware_busy(self) -> bool:
        return self.gate.state in _BUSY_STATES or self._rtt_lifecycle.owns_session

    def _set_status(self) -> None:
        self.status_var.set(_STATE_TEXT[self.gate.state])

    def _show_busy(self) -> None:
        messagebox.showwarning(
            "ST-Link 正忙",
            f"当前任务: {_STATE_TEXT[self.gate.state]}。请等待当前任务结束。",
            parent=self.root,
        )

    def _update_elapsed(self) -> None:
        if self._rtt_started_at is None:
            return
        elapsed = max(0, int(time.monotonic() - self._rtt_started_at))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _append_openocd(self, text: str) -> None:
        self.output.append_openocd(text)

    def _open_logs_dir(self) -> None:
        try:
            path = self._log_dir()
            path.mkdir(parents=True, exist_ok=True)
            if os.name != "nt" or not hasattr(os, "startfile"):
                raise OSError("当前平台不支持通过资源管理器打开目录。")
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("无法打开日志目录", str(exc), parent=self.root)

    def _on_close(self) -> None:
        if self._closing:
            if self._rtt_lifecycle.phase is RttPhase.INCOMPLETE:
                self._stop_rtt()
            return
        if self._hardware_busy():
            confirmed = messagebox.askyesno(
                "关闭 KeilTool",
                "当前有硬件任务正在运行。停止或等待任务完成后关闭？",
                parent=self.root,
            )
            if not confirmed:
                return
            self._closing = True
            self.status_var.set("正在安全关闭")
            self._refresh_controls()
            action = self._rtt_lifecycle.request_close()
            if action is LifecycleAction.STOP_SESSION and self._rtt_session is not None:
                self._dispatch_rtt_stop(self._rtt_session)
            return
        self._closing = True
        self._rtt_lifecycle.request_close()
        self._finish_close_if_ready()

    def _finish_close_if_ready(self) -> None:
        if self._closing and self.gate.state not in _BUSY_STATES and self._rtt_lifecycle.can_destroy:
            self._destroy()

    def _destroy(self) -> None:
        if self._destroyed:
            return
        if self._hardware_busy() or not self._rtt_lifecycle.can_destroy:
            self.status_var.set("仍有硬件资源未释放，无法关闭")
            return
        while True:
            try:
                self.settings_store.save(self._current_settings())
                break
            except OSError as exc:
                answer = messagebox.askyesnocancel(
                    "设置保存失败",
                    (
                        f"无法保存 GUI 设置:\n{exc}\n\n"
                        "选择“是”重试，选择“否”放弃保存并关闭，选择“取消”返回工作台。"
                    ),
                    parent=self.root,
                )
                decision = save_failure_action(answer)
                if decision is SaveFailureAction.RETRY:
                    continue
                if decision is SaveFailureAction.STAY_OPEN:
                    self._closing = False
                    self._rtt_lifecycle.cancel_close()
                    self.status_var.set("设置未保存，已取消关闭")
                    self._refresh_controls()
                    return
                break
        self._destroyed = True
        self.root.destroy()

    def _current_settings(self) -> GuiSettings:
        return GuiSettings(
            project=self.project_var.get().strip(),
            target=self.target_var.get().strip(),
            firmware=self.firmware_var.get().strip(),
            bin_address=self.bin_address_var.get().strip(),
            openocd_path=self.openocd_var.get().strip(),
            scripts_dir=self.scripts_var.get().strip(),
            target_override=self.target_override_var.get().strip(),
            rtt_address=self.rtt_address_var.get().strip() if self.rtt_manual_var.get() else "",
            rtt_channel=int_or_default(self.rtt_channel_var.get(), 0),
            rtt_port=int_or_default(self.rtt_port_var.get(), 19021),
            rtt_timeout_ms=int_or_default(self.rtt_timeout_var.get(), 5000),
            logs_dir=self.logs_dir_var.get().strip(),
        )


def launch_gui() -> None:
    root = tk.Tk()
    KeilToolGui(root)
    root.mainloop()


__all__ = [
    "KeilToolGui",
    "launch_gui",
]
