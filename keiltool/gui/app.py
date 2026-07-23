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
from typing import Callable

from keiltool.core.openocd_backend import (
    ConnectionResult,
    FlashRequest,
    FlashResult,
    OpenOcdConfig,
    parse_address,
    run_connection_check,
    run_flash,
)
from keiltool.core.rtt import RttEvent, RttRequest, RttSession
from keiltool.gui.project_config import (
    LoadedProjectTargets,
    ProjectTargetFacts,
    load_project_targets,
    resolve_target_facts,
)
from keiltool.gui.settings import GuiSettings, SettingsStore
from keiltool.gui.state import BusySessionError, SessionState, TaskGate


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


@dataclass(frozen=True, slots=True)
class RttLogPaths:
    channel: Path
    stdout: Path
    stderr: Path


def build_flash_request(firmware: str | Path, bin_address: str) -> FlashRequest:
    """Validate GUI firmware fields and return the shared backend request."""

    path = Path(firmware).expanduser()
    if path.suffix.lower() not in {".hex", ".bin"}:
        raise ValueError("Firmware must be a .hex or .bin file.")
    if not path.is_file():
        raise ValueError(f"Firmware file does not exist: {path}")
    if path.suffix.lower() == ".hex":
        return FlashRequest(path)
    return FlashRequest(path, base_address=parse_address(bin_address))


def build_rtt_request(
    *,
    manual: bool,
    address: str,
    ram_origin: int | None,
    ram_size: int | None,
    port: str | int,
    channel: str | int,
) -> RttRequest:
    """Validate GUI RTT fields and return the shared RTT request."""

    try:
        parsed_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("RTT port must be an integer.") from exc
    try:
        parsed_channel = int(channel)
    except (TypeError, ValueError) as exc:
        raise ValueError("RTT channel must be an integer.") from exc

    if manual:
        scan_address = parse_address(address)
        scan_size = 0x100
    else:
        if ram_origin is None or ram_size is None or ram_size <= 0:
            raise ValueError("Keil Target does not provide a usable RAM range for automatic RTT scanning.")
        scan_address = ram_origin
        scan_size = ram_size
    return RttRequest(
        scan_address=scan_address,
        scan_size=scan_size,
        port=parsed_port,
        channel=parsed_channel,
    )


def build_rtt_log_paths(log_dir: str | Path, target_name: str, stamp: str) -> RttLogPaths:
    directory = Path(log_dir)
    target = _safe_filename(target_name)
    return RttLogPaths(
        channel=directory / f"rtt_{target}_{stamp}.log",
        stdout=directory / f"rtt_openocd_{target}_{stamp}.out.log",
        stderr=directory / f"rtt_openocd_{target}_{stamp}.err.log",
    )


class KeilToolGui:
    """Tkinter workbench for independent ST-Link flash and RTT operations."""

    def __init__(self, root: tk.Tk, *, settings_store: SettingsStore | None = None) -> None:
        self.root = root
        self.settings_store = settings_store or SettingsStore()
        self.gate = TaskGate()
        self._events: queue.Queue[_UiEvent] = queue.Queue()
        self._loaded_project: LoadedProjectTargets | None = None
        self._facts: ProjectTargetFacts | None = None
        self._rtt_session: RttSession | None = None
        self._rtt_log_paths: RttLogPaths | None = None
        self._rtt_started_at: float | None = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self._closing = False
        self._destroyed = False
        self._stop_requested = False
        self._advanced_visible = False
        self._editable_widgets: list[tuple[tk.Widget, str]] = []

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
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root, padding=(0, 10, 10, 8))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_project_section(left)
        self._build_rtt_section(left)
        self._build_advanced_section(left)
        left.rowconfigure(3, weight=1)

        self._build_output_notebook(right)

        status = ttk.Frame(self.root, padding=(10, 4, 10, 6))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Separator(status).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(status, text="状态").grid(row=1, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var).grid(row=1, column=1, sticky="w", padx=(10, 0))
        status.columnconfigure(1, weight=1)

    def _build_project_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="工程与烧录", padding=8)
        section.grid(row=0, column=0, sticky="ew")
        section.columnconfigure(1, weight=1)

        self.project_entry, project_button = self._path_row(
            section,
            0,
            "Keil 工程",
            self.project_var,
            self._choose_project,
        )
        ttk.Label(section, text="Target").grid(row=1, column=0, sticky="w", pady=3)
        self.target_combo = ttk.Combobox(
            section,
            textvariable=self.target_var,
            state="readonly",
            width=34,
        )
        self.target_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)

        self._readonly_row(section, 2, "Device", self.device_var)
        self._readonly_row(section, 3, "Flash", self.flash_summary_var)
        self._readonly_row(section, 4, "RAM", self.ram_summary_var)
        self._readonly_row(section, 5, "Target cfg", self.target_cfg_var)
        self._readonly_row(section, 6, "解析", self.resolution_var)

        self.firmware_entry, firmware_button = self._path_row(
            section,
            7,
            "固件",
            self.firmware_var,
            self._choose_firmware,
        )
        ttk.Label(section, text="BIN 地址").grid(row=8, column=0, sticky="w", pady=3)
        self.bin_address_entry = ttk.Entry(section, textvariable=self.bin_address_var, width=34)
        self.bin_address_entry.grid(row=8, column=1, columnspan=2, sticky="ew", pady=3)

        actions = ttk.Frame(section)
        actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        actions.columnconfigure((0, 1), weight=1)
        self.connect_button = ttk.Button(actions, text="检查连接", command=self._check_connection)
        self.connect_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.flash_button = ttk.Button(
            actions,
            text="烧录并校验",
            style="Primary.TButton",
            command=self._flash,
        )
        self.flash_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._remember_editable(self.project_entry, project_button, self.firmware_entry, firmware_button)
        self._editable_widgets.append((self.target_combo, "readonly"))
        self._editable_widgets.append((self.bin_address_entry, "normal"))

    def _build_rtt_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="RTT 采集", padding=8)
        section.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="扫描").grid(row=0, column=0, sticky="w", pady=3)
        modes = ttk.Frame(section)
        modes.grid(row=0, column=1, columnspan=2, sticky="w")
        self.auto_radio = ttk.Radiobutton(
            modes,
            text="自动 RAM",
            variable=self.rtt_manual_var,
            value=False,
            command=self._refresh_controls,
        )
        self.auto_radio.grid(row=0, column=0, sticky="w")
        self.manual_radio = ttk.Radiobutton(
            modes,
            text="手动地址",
            variable=self.rtt_manual_var,
            value=True,
            command=self._refresh_controls,
        )
        self.manual_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(section, text="控制块地址").grid(row=1, column=0, sticky="w", pady=3)
        self.rtt_address_entry = ttk.Entry(section, textvariable=self.rtt_address_var)
        self.rtt_address_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(section, text="通道").grid(row=2, column=0, sticky="w", pady=3)
        self.channel_spin = ttk.Spinbox(
            section,
            from_=0,
            to=255,
            textvariable=self.rtt_channel_var,
            width=8,
        )
        self.channel_spin.grid(row=2, column=1, sticky="w", pady=3)

        self.logs_entry, logs_button = self._path_row(
            section,
            3,
            "日志目录",
            self.logs_dir_var,
            self._choose_logs_dir,
        )

        actions = ttk.Frame(section)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        actions.columnconfigure((0, 1), weight=1)
        self.rtt_start_button = ttk.Button(
            actions,
            text="开始采集",
            style="Primary.TButton",
            command=self._start_rtt,
        )
        self.rtt_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.rtt_stop_button = ttk.Button(actions, text="停止采集", command=self._stop_rtt)
        self.rtt_stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._remember_editable(
            self.auto_radio,
            self.manual_radio,
            self.rtt_address_entry,
            self.channel_spin,
            self.logs_entry,
            logs_button,
        )

    def _build_advanced_section(self, parent: ttk.Frame) -> None:
        self.advanced_button = ttk.Button(
            parent,
            text="▶ 高级设置",
            command=self._toggle_advanced,
        )
        self.advanced_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self.advanced_frame = ttk.Frame(parent, padding=(8, 5, 8, 0))
        self.advanced_frame.columnconfigure(1, weight=1)
        self.openocd_entry, openocd_button = self._path_row(
            self.advanced_frame,
            0,
            "OpenOCD",
            self.openocd_var,
            self._choose_openocd,
        )
        self.scripts_entry, scripts_button = self._path_row(
            self.advanced_frame,
            1,
            "scripts",
            self.scripts_var,
            self._choose_scripts_dir,
        )
        self.override_entry, override_button = self._path_row(
            self.advanced_frame,
            2,
            "target override",
            self.target_override_var,
            self._choose_target_override,
        )
        ttk.Label(self.advanced_frame, text="RTT 端口").grid(row=3, column=0, sticky="w", pady=3)
        self.port_entry = ttk.Entry(self.advanced_frame, textvariable=self.rtt_port_var, width=12)
        self.port_entry.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(self.advanced_frame, text="扫描超时(ms)").grid(row=4, column=0, sticky="w", pady=3)
        self.timeout_entry = ttk.Entry(self.advanced_frame, textvariable=self.rtt_timeout_var, width=12)
        self.timeout_entry.grid(row=4, column=1, sticky="w", pady=3)

        self._remember_editable(
            self.openocd_entry,
            openocd_button,
            self.scripts_entry,
            scripts_button,
            self.override_entry,
            override_button,
            self.port_entry,
            self.timeout_entry,
        )
        self._editable_widgets.append((self.advanced_button, "normal"))

    def _build_output_notebook(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")

        rtt_tab = ttk.Frame(notebook, padding=8)
        openocd_tab = ttk.Frame(notebook, padding=8)
        notebook.add(rtt_tab, text="RTT 日志")
        notebook.add(openocd_tab, text="OpenOCD 输出")

        rtt_tab.columnconfigure(0, weight=1)
        rtt_tab.rowconfigure(1, weight=1)
        rtt_toolbar = ttk.Frame(rtt_tab)
        rtt_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(rtt_toolbar, textvariable=self.elapsed_var, width=10).grid(row=0, column=0, sticky="w")
        ttk.Label(rtt_toolbar, textvariable=self.counts_var, width=22).grid(row=0, column=1, sticky="w")
        rtt_toolbar.columnconfigure(2, weight=1)
        ttk.Button(rtt_toolbar, text="清空显示", command=self._clear_rtt_display).grid(
            row=0,
            column=3,
            padx=(6, 0),
        )
        ttk.Button(rtt_toolbar, text="打开日志目录", command=self._open_logs_dir).grid(
            row=0,
            column=4,
            padx=(6, 0),
        )
        self.rtt_text = self._text_with_scrollbar(rtt_tab, row=1)

        openocd_tab.columnconfigure(0, weight=1)
        openocd_tab.rowconfigure(1, weight=1)
        openocd_toolbar = ttk.Frame(openocd_tab)
        openocd_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        openocd_toolbar.columnconfigure(0, weight=1)
        ttk.Button(openocd_toolbar, text="清空输出", command=self._clear_openocd_display).grid(
            row=0,
            column=1,
        )
        ttk.Button(openocd_toolbar, text="打开日志目录", command=self._open_logs_dir).grid(
            row=0,
            column=2,
            padx=(6, 0),
        )
        self.openocd_text = self._text_with_scrollbar(openocd_tab, row=1)

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> tuple[ttk.Entry, ttk.Button]:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        button = ttk.Button(parent, text="选择", command=command, width=6)
        button.grid(row=row, column=2, sticky="e", padx=(6, 0), pady=3)
        return entry, button

    @staticmethod
    def _readonly_row(parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=variable, state="readonly")
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)

    @staticmethod
    def _text_with_scrollbar(parent: ttk.Frame, *, row: int) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(
            frame,
            wrap="none",
            width=1,
            height=1,
            font=("Consolas", 10),
            undo=False,
            state="disabled",
            borderwidth=1,
            relief="solid",
        )
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        return text

    def _remember_editable(self, *widgets: tk.Widget) -> None:
        self._editable_widgets.extend((widget, "normal") for widget in widgets)

    def _bind_updates(self) -> None:
        self.target_combo.bind("<<ComboboxSelected>>", lambda _event: self._resolve_selected_target())
        self.firmware_var.trace_add("write", lambda *_args: self._refresh_controls())
        for entry in (self.openocd_entry, self.scripts_entry, self.override_entry):
            entry.bind("<FocusOut>", lambda _event: self._resolve_selected_target())
            entry.bind("<Return>", lambda _event: self._resolve_selected_target())

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_frame.grid(row=3, column=0, sticky="ew")
            self.advanced_button.configure(text="▼ 高级设置")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="▶ 高级设置")

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
        if self.gate.state in _BUSY_STATES:
            self._show_busy()
            return
        try:
            loaded = load_project_targets(path)
        except Exception as exc:
            self._loaded_project = None
            self._facts = None
            self.target_combo.configure(values=())
            self._clear_facts(f"工程读取失败: {exc}")
            self._append_openocd(f"[工程] {path}\n读取失败: {exc}\n\n")
            if not restored:
                messagebox.showerror("工程读取失败", str(exc), parent=self.root)
            self._refresh_controls()
            return

        self._loaded_project = loaded
        names = tuple(target.name for target in loaded.targets)
        self.target_combo.configure(values=names)
        requested = self.target_var.get()
        self.target_var.set(requested if requested in names else (names[0] if names else ""))
        if not names:
            self._facts = None
            self._clear_facts("工程中没有可用 Target")
            self._refresh_controls()
            return
        self._resolve_selected_target()

    def _resolve_selected_target(self) -> None:
        loaded = self._loaded_project
        if loaded is None or self.gate.state in _BUSY_STATES:
            return
        target = self._selected_target()
        if target is None:
            self._facts = None
            self._clear_facts("请选择 Target")
            self._refresh_controls()
            return
        try:
            facts = resolve_target_facts(
                target,
                loaded.project_root,
                openocd_path=self.openocd_var.get().strip(),
                scripts_dir=self.scripts_var.get().strip(),
                target_override=self.target_override_var.get().strip(),
            )
        except Exception as exc:
            self._facts = None
            self._clear_facts(f"Target 解析失败: {exc}")
            self._refresh_controls()
            return

        self._facts = facts
        self.device_var.set(facts.device or "—")
        self.flash_summary_var.set(facts.flash_summary or "—")
        self.ram_summary_var.set(facts.ram_summary or "—")
        self.target_cfg_var.set(facts.target_cfg or "—")
        self.resolution_var.set(facts.resolution_reason or facts.resolution_status)
        if not self.openocd_var.get().strip() and facts.openocd_executable:
            self.openocd_var.set(facts.openocd_executable)
        if not self.scripts_var.get().strip() and facts.openocd_scripts:
            self.scripts_var.set(facts.openocd_scripts)
        if not self.logs_dir_var.get().strip():
            self.logs_dir_var.set(facts.default_log_dir)
        self._refresh_controls()

    def _selected_target(self):
        loaded = self._loaded_project
        if loaded is None:
            return None
        selected = self.target_var.get()
        return next((target for target in loaded.targets if target.name == selected), None)

    def _clear_facts(self, reason: str) -> None:
        self.device_var.set("—")
        self.flash_summary_var.set("—")
        self.ram_summary_var.set("—")
        self.target_cfg_var.set("—")
        self.resolution_var.set(reason)

    def _facts_are_ready(self) -> bool:
        facts = self._facts
        return bool(facts and facts.ready and facts.openocd_executable and facts.target_cfg)

    def _firmware_is_ready(self) -> bool:
        path = Path(self.firmware_var.get().strip())
        return path.suffix.lower() in {".hex", ".bin"} and path.is_file()

    def _build_openocd_config(self) -> OpenOcdConfig:
        facts = self._facts
        if not self._facts_are_ready() or facts is None:
            reason = facts.resolution_reason if facts else "请先选择并解析 Keil Target。"
            raise ValueError(reason)
        scripts_text = self.scripts_var.get().strip()
        return OpenOcdConfig(
            executable=Path(facts.openocd_executable),
            scripts_dir=Path(scripts_text) if scripts_text else None,
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
            config = self._build_openocd_config()
            log_dir = self._log_dir()
            target = self._selected_target()
            self.gate.begin(SessionState.CONNECT)
        except BusySessionError:
            self._show_busy()
            return
        except (OSError, ValueError) as exc:
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
            config = self._build_openocd_config()
            request = build_flash_request(self.firmware_var.get().strip(), self.bin_address_var.get().strip())
            log_dir = self._log_dir()
            target = self._selected_target()
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法烧录", str(exc), parent=self.root)
            return

        facts = self._facts
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
            config = self._build_openocd_config()
            facts = self._facts
            request = build_rtt_request(
                manual=self.rtt_manual_var.get(),
                address=self.rtt_address_var.get().strip(),
                ram_origin=facts.ram_origin if facts else None,
                ram_size=facts.ram_size if facts else None,
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
        except BusySessionError:
            self._show_busy()
            return
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法启动 RTT", str(exc), parent=self.root)
            return

        self._rtt_session = session
        self._rtt_log_paths = log_paths
        self._rtt_started_at = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self._stop_requested = False
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
        self._start_worker("rtt-started", session.start)

    def _stop_rtt(self) -> None:
        session = self._rtt_session
        if session is None or self.gate.state not in {SessionState.RTT_SCAN, SessionState.RTT}:
            return
        try:
            self.gate.begin_stopping()
        except BusySessionError:
            return
        self._stop_requested = True
        self._set_status()
        self._refresh_controls()
        self._start_worker("rtt-stop-returned", session.stop)

    def _start_worker(self, success_kind: str, action: Callable[[], object]) -> None:
        def run() -> None:
            try:
                value = action()
            except BaseException as exc:
                self._events.put(_UiEvent("worker-error", (success_kind, exc)))
            else:
                self._events.put(_UiEvent(success_kind, value))

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
            operation, error = event.value
            self._handle_worker_error(operation, error)
        elif event.kind in {"rtt-started", "rtt-stop-returned"}:
            self._finish_close_if_ready()

    def _finish_connection(self, value: object) -> None:
        if not isinstance(value, ConnectionResult):
            self._handle_worker_error("connection-result", RuntimeError("连接检查返回了无效结果。"))
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
            self._handle_worker_error("flash-result", RuntimeError("烧录返回了无效结果。"))
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

    def _handle_worker_error(self, operation: object, error: object) -> None:
        message = str(error)
        self._append_openocd(f"\n[后台任务失败] {operation}: {message}\n")
        if str(operation).startswith("rtt"):
            if self._rtt_session is not None and self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT}:
                self._stop_rtt()
            elif self.gate.state is SessionState.STOPPING:
                self.gate.fail()
                self._rtt_session = None
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
            self._append_text(self.rtt_text, event.text)
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
            if self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT}:
                self._stop_rtt()
        elif event.kind == "stopped":
            self._append_openocd(f"[RTT] {event.message} ({event.outcome})\n\n")
            if event.outcome == "incomplete":
                self.gate.fail()
                self.status_var.set("RTT 清理不完整")
            elif event.outcome == "startup_failed":
                self.gate.fail()
                self.status_var.set("RTT 启动失败")
            else:
                self.gate.finish()
                self.status_var.set("RTT 已停止")
            self._rtt_session = None
            self._rtt_started_at = None
            self._stop_requested = False
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
        busy = self.gate.state in _BUSY_STATES
        for widget, idle_state in self._editable_widgets:
            state = "disabled" if busy else idle_state
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

        firmware_is_hex = Path(self.firmware_var.get().strip()).suffix.lower() == ".hex"
        self.bin_address_entry.configure(state="disabled" if busy or firmware_is_hex else "normal")
        self.rtt_address_entry.configure(
            state="normal" if not busy and self.rtt_manual_var.get() else "disabled"
        )

        ready = self._facts_are_ready()
        idle = not busy
        self.connect_button.configure(state="normal" if idle and ready else "disabled")
        self.flash_button.configure(
            state="normal" if idle and ready and self._firmware_is_ready() else "disabled"
        )
        auto_rtt_ready = bool(self._facts and self._facts.ram_origin is not None and self._facts.ram_size)
        rtt_fields_ready = self.rtt_manual_var.get() or auto_rtt_ready
        self.rtt_start_button.configure(
            state="normal" if idle and ready and rtt_fields_ready else "disabled"
        )
        self.rtt_stop_button.configure(
            state="normal" if self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT} else "disabled"
        )

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

    def _clear_rtt_display(self) -> None:
        self._clear_text(self.rtt_text)

    def _clear_openocd_display(self) -> None:
        self._clear_text(self.openocd_text)

    def _append_openocd(self, text: str) -> None:
        self._append_text(self.openocd_text, text)

    @staticmethod
    def _append_text(widget: tk.Text, text: str) -> None:
        if not text:
            return
        widget.configure(state="normal")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    @staticmethod
    def _clear_text(widget: tk.Text) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

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
            return
        if self.gate.state in _BUSY_STATES:
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
            if self.gate.state in {SessionState.RTT_SCAN, SessionState.RTT}:
                self._stop_rtt()
            return
        self._closing = True
        self._destroy()

    def _finish_close_if_ready(self) -> None:
        if self._closing and self.gate.state not in _BUSY_STATES and self._rtt_session is None:
            self._destroy()

    def _destroy(self) -> None:
        if self._destroyed:
            return
        try:
            self.settings_store.save(self._current_settings())
        except OSError as exc:
            if not self._closing:
                messagebox.showerror("设置保存失败", str(exc), parent=self.root)
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
            rtt_channel=_int_or_default(self.rtt_channel_var.get(), 0),
            rtt_port=_int_or_default(self.rtt_port_var.get(), 19021),
            rtt_timeout_ms=_int_or_default(self.rtt_timeout_var.get(), 5000),
            logs_dir=self.logs_dir_var.get().strip(),
        )


def _int_or_default(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _safe_filename(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    return cleaned.strip("._") or "target"


def launch_gui() -> None:
    root = tk.Tk()
    KeilToolGui(root)
    root.mainloop()


__all__ = [
    "KeilToolGui",
    "RttLogPaths",
    "build_flash_request",
    "build_rtt_log_paths",
    "build_rtt_request",
    "launch_gui",
]
