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

from keiltool.core.device_catalog import CatalogDevice, DeviceCatalog, load_embedded_catalog
from keiltool.core.device_import import import_device_file, load_user_catalog
from keiltool.core.openocd_backend import (
    ConnectionResult,
    FlashReadResult,
    FlashResult,
    OpenOcdCleanupResult,
    OpenOcdConfig,
    OpenOcdOperation,
    run_connection_check,
    run_flash,
    run_flash_read,
)
from keiltool.core.rtt import RttEvent, RttSession
from keiltool.core.rtt_log import RttLevel, RttLogRecord
from keiltool.core.process_launch import background_process_kwargs
from keiltool.core.session_logs import SessionLogContext, create_session_logs
from keiltool.core.vofa_bridge import (
    VofaTcpBridge,
    discover_vofa_executable,
    parse_listen_address,
)
from keiltool.gui.project_config import (
    ProjectTargetFacts,
    clear_project_device_catalog_cache,
    load_project_targets,
)
from keiltool.gui.firmware_freshness import FirmwareChange, FirmwareFingerprint, FirmwareFreshness
from keiltool.gui.operation_feedback import (
    OperationFeedback,
    OperationVisualState,
    ProgressMode,
)
from keiltool.gui.rtt_display import RttDisplayBuffer, build_rtt_view, parse_rtt_level
from keiltool.gui.settings import (
    GuiSettings,
    SettingsDiagnostic,
    SettingsStore,
    default_devices_path,
)
from keiltool.gui.state import BusySessionError, SessionState, TaskGate
from keiltool.gui.theme import configure_theme
from keiltool.gui.widgets import ConfigurationPane, OperationStatusPane, OutputNotebook
from keiltool.gui.workbench_controller import (
    BoundedEventPoller,
    FactInputs,
    FreshnessController,
    LifecycleAction,
    OneShotLifecycleController,
    OneShotPhase,
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
    build_flash_read_request,
    build_flash_request,
    build_rtt_request,
    int_or_default,
    is_firmware_ready,
    is_target_ready,
    safe_filename,
    target_facts_display,
)


_BUSY_STATES = frozenset(
    {
        SessionState.CONNECT,
        SessionState.FLASH,
        SessionState.FLASH_READ,
        SessionState.RTT_SCAN,
        SessionState.RTT,
        SessionState.STOPPING,
    }
)

_PROJECT_SOURCE = "project"
_DEVICE_SOURCE = "device"

_STATE_TEXT = {
    SessionState.IDLE: "空闲",
    SessionState.CONNECT: "检查连接",
    SessionState.FLASH: "烧录中",
    SessionState.FLASH_READ: "读取 Flash 中",
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
        self.operation_feedback = OperationFeedback()
        self._firmware_freshness = {
            _PROJECT_SOURCE: FirmwareFreshness(),
            _DEVICE_SOURCE: FirmwareFreshness(),
        }
        self._window_inactive = False
        self._firmware_focus_check_pending = False
        self._one_shot_lifecycle = OneShotLifecycleController()
        self._rtt_lifecycle = RttLifecycleController()
        self._event_poller = BoundedEventPoller()
        self._events: queue.Queue[_UiEvent] = queue.Queue()
        self._facts: ProjectTargetFacts | None = None
        self._rtt_session: RttSession | None = None
        self._rtt_log_paths: RttLogPaths | None = None
        self._rtt_log_context: SessionLogContext | None = None
        self._rtt_started_at: float | None = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self._rtt_error_message = ""
        self._vofa_bridge: VofaTcpBridge | None = None
        self._vofa_process: subprocess.Popen | None = None
        self._last_operation_feedback_refresh = 0.0
        self._rtt_display = RttDisplayBuffer(max_records=20_000)
        self._one_shot_cleanup_log: Path | None = None
        self._operation_logs: dict[object, SessionLogContext] = {}
        self._closing = False
        self._destroyed = False

        settings_result = self.settings_store.load_result()
        settings = settings_result.settings
        self._catalog_diagnostics: tuple[str, ...] = ()
        self._catalog = DeviceCatalog()
        self._device_by_label: dict[str, CatalogDevice] = {}
        self._reload_device_catalog()
        self._create_variables(settings)
        self._configure_window()
        self._build_layout()
        if settings_result.diagnostic is not None:
            self._render_settings_diagnostic(settings_result.diagnostic)
        for diagnostic in self._catalog_diagnostics:
            self._append_openocd(f"[设备目录] {diagnostic}\n")
        self._bind_updates()
        self._refresh_controls()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<FocusOut>", self._on_window_focus_out, add="+")
        self.root.bind("<FocusIn>", self._on_window_focus_in, add="+")
        self.root.after(50, self._poll_events)
        self.root.after_idle(self._initialize_firmware_baseline)
        if settings.project and self.device_source_mode_var.get() == _PROJECT_SOURCE:
            self.root.after_idle(lambda: self._load_project(Path(settings.project), restored=True))
        elif settings.device_vendor and settings.device_name:
            self.root.after_idle(self._resolve_selected_target)

    def _reload_device_catalog(self) -> None:
        clear_project_device_catalog_cache()
        embedded = load_embedded_catalog()
        user = load_user_catalog(default_devices_path())
        self._catalog = DeviceCatalog(embedded=embedded.devices, user=user.devices)
        self._catalog_diagnostics = user.diagnostics
        self._device_by_label = {
            self._device_label(device): device
            for device in self._catalog.devices
        }

    @staticmethod
    def _device_label(device: CatalogDevice) -> str:
        return f"{device.device}  [{device.vendor}]"

    @staticmethod
    def _device_source_text(device: CatalogDevice | None) -> str:
        if device is None:
            return "未选择"
        source = device.source
        kind = {
            "embedded": "内置官方目录",
            "imported_pdsc": "用户 PDSC",
            "imported_pack": "用户 PACK",
            "user": "用户 JSON",
        }.get(source.kind, source.kind or "未知来源")
        version = f" {source.pack_version}" if source.pack_version else ""
        return f"{kind} · {source.pack}{version}"

    def _create_variables(self, settings: GuiSettings) -> None:
        selected = self._catalog.lookup(settings.device_vendor, settings.device_name)
        source_mode = (
            settings.device_source_mode
            if settings.project or settings.device_source_mode == _DEVICE_SOURCE
            else _DEVICE_SOURCE
        )
        self._project_target = settings.target
        self._project_firmware = settings.project_firmware or (
            settings.firmware if source_mode == _PROJECT_SOURCE else ""
        )
        self._device_firmware = settings.device_firmware or (
            settings.firmware if source_mode == _DEVICE_SOURCE else ""
        )
        self._independent_device = selected
        self.project_var = tk.StringVar(value=settings.project)
        self.target_var = tk.StringVar(
            value=settings.target if source_mode == _PROJECT_SOURCE else ""
        )
        self.device_source_mode_var = tk.StringVar(value=source_mode)
        self.device_var = tk.StringVar(value=selected.device if selected else "—")
        self.device_choice_var = tk.StringVar(value=self._device_label(selected) if selected else "")
        source_prefix = "独立 Device" if source_mode == _DEVICE_SOURCE else "Keil 工程"
        self.device_source_var = tk.StringVar(
            value=f"{source_prefix} · {self._device_source_text(selected)}"
        )
        self.flash_summary_var = tk.StringVar(value="—")
        self.ram_summary_var = tk.StringVar(value="—")
        self.target_cfg_var = tk.StringVar(value="—")
        self.resolution_var = tk.StringVar(value="请选择 Keil 工程")
        self.firmware_var = tk.StringVar(
            value=self._project_firmware
            if source_mode == _PROJECT_SOURCE
            else self._device_firmware
        )
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
        self.vofa_path_var = tk.StringVar(value=settings.vofa_path)
        self.vofa_listen_var = tk.StringVar(value=settings.vofa_listen)
        self.status_var = tk.StringVar(value=_STATE_TEXT[SessionState.IDLE])
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.counts_var = tk.StringVar(value="0 字节 / 0 行")
        self.rtt_display_level_var = tk.StringVar(value=settings.rtt_display_level)
        self.rtt_visible_counts_var = tk.StringVar(value="0 可见 / 0 缓存")

    def _configure_window(self) -> None:
        self.root.title("KeilTool ST-Link 工作台")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 720)
        self.root.columnconfigure(0, minsize=420, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        configure_theme(self.root)

    def _build_layout(self) -> None:
        left = ttk.Frame(self.root, padding=(10, 6, 8, 4), style="Background.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root, padding=(0, 6, 10, 4), style="Background.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.controls = ConfigurationPane(left, self)
        self.controls.grid(row=0, column=0, sticky="nsew")
        self.controls.device_combo.configure(values=tuple(self._device_by_label))

        self.operation_status = OperationStatusPane(right)
        self.operation_status.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.operation_status.set_copy_command(self._copy_operation_error)
        self.operation_status.set_open_logs_command(self._open_operation_log_dir)
        self.operation_status.update(self.operation_feedback)

        self.output = OutputNotebook(
            right,
            elapsed_var=self.elapsed_var,
            counts_var=self.counts_var,
            rtt_level_var=self.rtt_display_level_var,
            rtt_visible_counts_var=self.rtt_visible_counts_var,
            on_level_changed=self._on_rtt_level_changed,
            on_clear_rtt=self._clear_rtt_display,
            open_logs_dir=self._open_logs_dir,
        )
        self.output.grid(row=1, column=0, sticky="nsew")

        status = ttk.Frame(self.root, padding=(10, 2, 10, 3), style="Status.TFrame")
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Separator(status).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 3))
        ttk.Label(status, text="状态", style="Status.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").grid(
            row=1,
            column=1,
            sticky="w",
            padx=(10, 0),
        )
        status.columnconfigure(1, weight=1)

    def _bind_updates(self) -> None:
        controls = self.controls
        controls.project_button.configure(command=self._choose_project)
        controls.device_import_button.configure(command=self._import_device)
        controls.firmware_button.configure(command=self._choose_firmware)
        controls.logs_button.configure(command=self._choose_logs_dir)
        controls.openocd_button.configure(command=self._choose_openocd)
        controls.scripts_button.configure(command=self._choose_scripts_dir)
        controls.override_button.configure(command=self._choose_target_override)
        controls.connect_button.configure(command=self._check_connection)
        controls.flash_read_button.configure(command=self._read_flash)
        controls.flash_button.configure(command=self._flash)
        controls.rtt_start_button.configure(command=self._start_rtt)
        controls.vofa_start_button.configure(command=self._start_vofa_rtt)
        controls.rtt_stop_button.configure(command=self._stop_rtt)
        controls.vofa_button.configure(command=self._choose_vofa)
        controls.auto_radio.configure(command=self._refresh_controls)
        controls.manual_radio.configure(command=self._refresh_controls)
        controls.project_source_radio.configure(command=self._change_device_source)
        controls.device_source_radio.configure(command=self._change_device_source)
        controls.target_combo.bind("<<ComboboxSelected>>", lambda _event: self._select_project_target())
        controls.device_combo.bind("<<ComboboxSelected>>", lambda _event: self._select_catalog_device())
        controls.device_combo.bind("<KeyRelease>", self._filter_device_choices)
        controls.device_combo.bind("<Return>", lambda _event: self._select_catalog_device())
        self.firmware_var.trace_add("write", lambda *_args: self._refresh_controls())
        controls.firmware_entry.bind("<FocusOut>", self._accept_typed_firmware)
        controls.firmware_entry.bind("<Return>", self._accept_typed_firmware)
        for variable in (
            self.project_var,
            self.target_var,
            self.openocd_var,
            self.scripts_var,
            self.target_override_var,
            self.device_choice_var,
        ):
            variable.trace_add("write", self._on_fact_input_changed)
        controls.project_entry.bind("<FocusOut>", lambda _event: self._load_project(Path(self.project_var.get().strip())))
        controls.project_entry.bind("<Return>", lambda _event: self._load_project(Path(self.project_var.get().strip())))
        for entry in (controls.openocd_entry, controls.scripts_entry, controls.override_entry):
            entry.bind("<FocusOut>", lambda _event: self._resolve_selected_target())
            entry.bind("<Return>", lambda _event: self._resolve_selected_target())

    def _selected_catalog_device(self) -> CatalogDevice | None:
        value = self.device_choice_var.get().strip()
        selected = self._device_by_label.get(value)
        if selected is not None:
            return selected
        return self._catalog.lookup_any_vendor(value)

    def _filter_device_choices(self, _event: tk.Event | None = None) -> None:
        if self.device_source_mode_var.get() == _PROJECT_SOURCE:
            return
        query = self.device_choice_var.get().strip().lower()
        values = tuple(
            label
            for label in self._device_by_label
            if not query or query in label.lower()
        )
        self.controls.device_combo.configure(values=values[:300])

    def _select_catalog_device(self) -> None:
        if self.device_source_mode_var.get() == _PROJECT_SOURCE:
            self._sync_project_device_selection()
            return
        if self._hardware_busy():
            return
        device = self._selected_catalog_device()
        if device is None:
            self.device_source_var.set("未找到精确型号")
            self._facts = None
            self._clear_facts("请选择设备目录中的精确型号")
            self._refresh_controls()
            return
        previous = self._independent_device
        if previous is not None and (
            previous.vendor != device.vendor or previous.device != device.device
        ):
            self._device_firmware = ""
            self._firmware_freshness[_DEVICE_SOURCE].clear()
            self.firmware_var.set("")
        self._independent_device = device
        self.device_choice_var.set(self._device_label(device))
        self.device_source_var.set(f"独立 Device · {self._device_source_text(device)}")
        self.controls.device_combo.configure(values=tuple(self._device_by_label))
        self._resolve_selected_target()

    def _sync_project_device_selection(self) -> None:
        if self.device_source_mode_var.get() != _PROJECT_SOURCE:
            return
        facts = self._facts
        if facts is None:
            self.device_choice_var.set("")
            self.device_source_var.set("Keil 工程 · 等待解析 Target 设备")
            return
        catalog_device = self._catalog.lookup_any_vendor(facts.device)
        if catalog_device is not None:
            self.device_choice_var.set(self._device_label(catalog_device))
            self.device_source_var.set(
                f"Keil 工程 · {self._device_source_text(catalog_device)}"
            )
        else:
            self.device_choice_var.set(facts.device)
            self.device_source_var.set(
                f"Keil 工程 · {facts.device} · 直接使用工程信息（设备目录未收录）"
            )

    def _change_device_source(self) -> None:
        if self._hardware_busy():
            return
        mode = self.device_source_mode_var.get()
        if mode == _PROJECT_SOURCE:
            project = self.project_var.get().strip()
            if not project:
                self.device_source_mode_var.set(_DEVICE_SOURCE)
                self._refresh_controls()
                return
            self._remember_device_context()
            self.target_var.set(self._project_target)
            self.firmware_var.set(self._project_firmware)
            self._facts = None
            self._clear_facts("正在重新解析 Keil 工程 Target")
            self._load_project(Path(project))
            return

        self._remember_project_context()
        self.target_var.set("")
        self.controls.target_combo.configure(values=())
        self.firmware_var.set(self._device_firmware)
        self._facts = None
        if self._independent_device is not None:
            self.device_choice_var.set(self._device_label(self._independent_device))
            self.device_source_var.set(
                f"独立 Device · {self._device_source_text(self._independent_device)}"
            )
            self._resolve_selected_target()
        else:
            self.device_choice_var.set("")
            self.device_source_var.set("独立 Device · 未选择")
            self._clear_facts("请选择设备目录中的精确型号")
            self._freshness.observe(self._visible_fact_inputs())
            self._refresh_controls()

    def _remember_project_context(self) -> None:
        self._project_target = self.target_var.get().strip()
        self._project_firmware = self.firmware_var.get().strip()

    def _remember_device_context(self) -> None:
        selected = self._selected_catalog_device()
        if selected is not None:
            self._independent_device = selected
        self._device_firmware = self.firmware_var.get().strip()

    def _select_project_target(self) -> None:
        if self.device_source_mode_var.get() == _PROJECT_SOURCE:
            self._project_target = self.target_var.get().strip()
        self._resolve_selected_target()

    def _import_device(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入设备定义",
            filetypes=[
                ("设备定义", "*.pdsc *.pack *.json"),
                ("CMSIS-Pack", "*.pack"),
                ("PDSC", "*.pdsc"),
                ("JSON", "*.json"),
            ],
        )
        if not path:
            return
        self._begin_feedback("导入设备定义", "解析设备文件")
        try:
            result = import_device_file(path, default_devices_path())
            self._reload_device_catalog()
            self.controls.device_combo.configure(values=tuple(self._device_by_label))
            selected = self._catalog.lookup(
                result.devices[0].vendor,
                result.devices[0].device,
            )
            if selected is None:
                raise ValueError("导入成功，但刷新目录后找不到设备。")
            if self.device_source_mode_var.get() == _DEVICE_SOURCE:
                self._independent_device = selected
                self.device_choice_var.set(self._device_label(selected))
                self.device_source_var.set(
                    f"独立 Device · {self._device_source_text(selected)}"
                )
                self._resolve_selected_target()
            self._append_openocd(
                f"[设备目录] 已导入 {len(result.devices)} 个型号: {result.output_path}\n"
            )
            self._complete_feedback(
                f"已导入 {len(result.devices)} 个设备型号",
                artifact=result.output_path,
            )
        except Exception as exc:
            self._fail_feedback("设备导入失败", str(exc))

    def _visible_fact_inputs(self) -> FactInputs:
        project_mode = self.device_source_mode_var.get() == _PROJECT_SOURCE
        selected = None if project_mode else self._selected_catalog_device()
        return FactInputs(
            project=self.project_var.get().strip() if project_mode else "",
            target=self.target_var.get().strip() if project_mode else "",
            openocd=self.openocd_var.get().strip(),
            scripts=self.scripts_var.get().strip(),
            target_override=self.target_override_var.get().strip(),
            device_vendor=selected.vendor if selected else "",
            device_name=selected.device if selected else "",
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
            if path != self.project_var.get().strip():
                if self.device_source_mode_var.get() == _DEVICE_SOURCE:
                    self._remember_device_context()
                self._project_target = ""
                self._project_firmware = ""
                self._firmware_freshness[_PROJECT_SOURCE].clear()
                self.target_var.set("")
                self.firmware_var.set("")
            self.project_var.set(path)
            self.device_source_mode_var.set(_PROJECT_SOURCE)
            self._load_project(Path(path))

    def _choose_firmware(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择固件",
            filetypes=[("固件", "*.hex *.bin"), ("HEX", "*.hex"), ("BIN", "*.bin")],
        )
        if path:
            self.firmware_var.set(path)
            self._current_firmware_freshness().accept(path)
            if self.device_source_mode_var.get() == _PROJECT_SOURCE:
                self._project_firmware = path
            else:
                self._device_firmware = path
            self.status_var.set("已载入固件文件")
            self._refresh_controls()

    def _current_firmware_freshness(self) -> FirmwareFreshness:
        return self._firmware_freshness[self.device_source_mode_var.get()]

    def _initialize_firmware_baseline(self) -> None:
        path = self.firmware_var.get().strip()
        if not path:
            return
        try:
            self._current_firmware_freshness().accept(path)
        except OSError:
            pass
        self._refresh_controls()

    def _accept_typed_firmware(self, _event: tk.Event | None = None) -> None:
        path = self.firmware_var.get().strip()
        if not path:
            self._current_firmware_freshness().clear()
            self._refresh_controls()
            return
        try:
            self._current_firmware_freshness().accept(path)
        except OSError as exc:
            self.status_var.set(f"固件文件不可用: {exc}")
        else:
            if self.device_source_mode_var.get() == _PROJECT_SOURCE:
                self._project_firmware = path
            else:
                self._device_firmware = path
            self.status_var.set("已载入固件文件")
        self._refresh_controls()

    def _on_window_focus_out(self, _event: tk.Event | None = None) -> None:
        self.root.after_idle(self._mark_window_inactive_if_needed)

    def _mark_window_inactive_if_needed(self) -> None:
        if not self._destroyed and self.root.focus_displayof() is None:
            self._window_inactive = True

    def _on_window_focus_in(self, _event: tk.Event | None = None) -> None:
        if not self._window_inactive or self._firmware_focus_check_pending:
            return
        self._window_inactive = False
        self._firmware_focus_check_pending = True
        self.root.after_idle(self._check_firmware_after_focus)

    def _check_firmware_after_focus(self) -> None:
        self._firmware_focus_check_pending = False
        if not self._destroyed and not self._hardware_busy():
            self._check_firmware_external_change()

    def _check_firmware_external_change(self) -> bool:
        path = self.firmware_var.get().strip()
        if not path:
            return True
        freshness = self._current_firmware_freshness()
        change = freshness.observe(path)
        if change is None:
            self._refresh_controls()
            return not freshness.stale
        if change.current is None:
            self.status_var.set("固件文件已丢失或不可读取，烧录已禁用")
            self._append_openocd(f"[固件检查] 文件不可用: {path}\n{change.error}\n\n")
            self._refresh_controls()
            return False

        reload_file = messagebox.askyesno(
            "固件文件已更新",
            self._firmware_change_message(change),
            parent=self.root,
        )
        if reload_file:
            freshness.accept_pending()
            self.status_var.set("已重新载入更新后的固件")
            self._append_openocd(f"[固件检查] 已接受外部更新: {change.current.path}\n")
            self._refresh_controls()
            return True

        self.status_var.set("固件已变化但未重新载入，烧录已禁用；重新选择固件可载入")
        self._append_openocd(f"[固件检查] 外部更新未载入，已禁用烧录: {change.current.path}\n")
        self._refresh_controls()
        return False

    @staticmethod
    def _firmware_change_message(change: FirmwareChange) -> str:
        previous = KeilToolGui._format_firmware_fingerprint("上次载入", change.previous)
        current = KeilToolGui._format_firmware_fingerprint("磁盘当前", change.current)
        return (
            "检测到固件文件被外部程序修改。是否重新载入当前磁盘版本？\n\n"
            f"{previous}\n\n{current}\n\n"
            "选择“否”后将禁用烧录，直到重新选择该固件。"
        )

    @staticmethod
    def _format_firmware_fingerprint(label: str, value: FirmwareFingerprint | None) -> str:
        if value is None:
            return f"{label}: 无"
        modified = datetime.fromtimestamp(value.modified_ns / 1_000_000_000).astimezone()
        return (
            f"{label}:\n"
            f"路径: {value.path}\n"
            f"大小: {value.size:,} 字节\n"
            f"修改时间: {modified.isoformat(timespec='seconds')}\n"
            f"SHA-256: {value.sha256}"
        )

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

    def _choose_vofa(self) -> Path | None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 VOFA+ 可执行文件",
            filetypes=[("VOFA+", "vofa+.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if not path:
            return None
        executable = Path(path)
        self.vofa_path_var.set(str(executable))
        return executable

    def _obtain_vofa_executable(self) -> Path:
        executable = discover_vofa_executable(self.vofa_path_var.get().strip())
        if executable is None:
            executable = self._choose_vofa()
        if executable is None:
            raise ValueError(
                "未找到可用的 VOFA+。当前桌面快捷方式已经失效，请安装 VOFA+ 后选择 vofa+.exe。"
            )
        self.vofa_path_var.set(str(executable))
        return executable

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
        if not self.project_var.get().strip():
            if self.device_source_mode_var.get() == _PROJECT_SOURCE:
                self._remember_project_context()
            self.device_source_mode_var.set(_DEVICE_SOURCE)
            self.controls.target_combo.configure(values=())
            self.target_var.set("")
            self.firmware_var.set(self._device_firmware)
            selected = self._independent_device
            if selected is not None:
                self.device_choice_var.set(self._device_label(selected))
            self.device_source_var.set(
                f"独立 Device · {self._device_source_text(selected)}"
            )
            if selected is None:
                self._facts = None
                self._clear_facts("请选择设备型号")
                self._refresh_controls()
            else:
                self._resolve_selected_target()
            return
        if self.device_source_mode_var.get() != _PROJECT_SOURCE:
            self._remember_device_context()
            self.device_source_mode_var.set(_PROJECT_SOURCE)
            self.target_var.set(self._project_target)
            self.firmware_var.set(self._project_firmware)
        self._begin_feedback("读取 Keil 工程", "解析工程 Target")
        try:
            loaded = load_project_targets(path)
        except Exception as exc:
            self._facts = None
            self.controls.target_combo.configure(values=())
            self._clear_facts(f"工程读取失败: {exc}")
            self._append_openocd(f"[工程] {path}\n读取失败: {exc}\n\n")
            self._fail_feedback("工程读取失败", str(exc))
            self._refresh_controls()
            return

        names = tuple(target.name for target in loaded.targets)
        self.controls.target_combo.configure(values=names)
        requested = self.target_var.get()
        self.target_var.set(requested if requested in names else (names[0] if names else ""))
        self._project_target = self.target_var.get().strip()
        if not names:
            self._facts = None
            self._clear_facts("工程中没有可用 Target")
            self._fail_feedback("工程中没有可用 Target", str(path))
            self._refresh_controls()
            return
        self._resolve_selected_target()
        if self._facts is None:
            self._fail_feedback("工程 Target 解析失败", self.resolution_var.get())
        else:
            self._complete_feedback(f"已载入 Target: {self.target_var.get()}")

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
        if current.project:
            self._sync_project_device_selection()
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
        if self._hardware_busy():
            self._show_busy()
            return
        self._begin_feedback("检查连接", "准备 OpenOCD 配置")
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            log_dir = self._log_dir()
            target = snapshot.target
            facts = cast(ProjectTargetFacts, snapshot.facts)
            log_context = create_session_logs(
                log_dir,
                device=facts.device,
                task="CONNECT",
                metadata={
                    "probe": "ST-Link",
                    "target_cfg": config.target_cfg,
                    "interface_cfg": config.interface_cfg,
                },
            )
            operation = OpenOcdOperation(timeout=30.0, background=True)
            try:
                self._begin_one_shot(SessionState.CONNECT, operation)
            except Exception:
                log_context.finalize("not_started")
                raise
            self._operation_logs[operation] = log_context
        except BusySessionError:
            self._show_busy()
            return
        except Exception as exc:
            self._fail_feedback("无法检查连接", str(exc))
            return
        self.operation_feedback.log_dir = log_context.directory
        self._set_feedback_stage("OpenOCD 执行中", ProgressMode.INDETERMINATE)
        self._set_status()
        self._refresh_controls()
        self._start_worker(
            "connection-result",
            lambda: run_connection_check(
                config,
                log_context.directory,
                operation=operation,
                target=target if hasattr(target, "name") else None,
                target_name=str(getattr(target, "name", "")),
                stdout_log_path=log_context.stdout_log,
                stderr_log_path=log_context.stderr_log,
            ),
            owner=operation,
        )

    def _read_flash(self) -> None:
        if self._hardware_busy():
            self._show_busy()
            return
        self._begin_feedback("读取完整 Flash", "准备读取参数")
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            facts = cast(ProjectTargetFacts, snapshot.facts)
            if not facts.flash_range_complete:
                raise ValueError(
                    "当前来源没有确认整颗芯片的物理 Flash 范围，无法执行完整读取。"
                )
            log_dir = self._log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            output = filedialog.asksaveasfilename(
                parent=self.root,
                title="保存完整 Flash 镜像",
                initialdir=str(log_dir),
                initialfile=(
                    f"{safe_filename(facts.device)}_flash_"
                    f"0x{facts.flash_origin:08X}_{facts.flash_size}.bin"
                ),
                defaultextension=".bin",
                filetypes=[("BIN 镜像", "*.bin"), ("所有文件", "*.*")],
            )
            if not output:
                self.operation_feedback.reset()
                self._refresh_operation_feedback()
                return
            request = build_flash_read_request(facts, output)
            target = snapshot.target
            log_context = create_session_logs(
                log_dir,
                device=facts.device,
                task="FLASH_READ",
                metadata={
                    "probe": "ST-Link",
                    "target_cfg": config.target_cfg,
                    "interface_cfg": config.interface_cfg,
                    "output": str(request.output.expanduser().resolve()),
                    "address": f"0x{request.address:08X}",
                    "size": request.size,
                },
            )
            operation = OpenOcdOperation(timeout=300.0, background=True)
            try:
                self._begin_one_shot(SessionState.FLASH_READ, operation)
            except Exception:
                log_context.finalize("not_started")
                raise
            self._operation_logs[operation] = log_context
        except BusySessionError:
            self._show_busy()
            return
        except Exception as exc:
            self._fail_feedback("无法读取 Flash", str(exc))
            return

        self.operation_feedback.log_dir = log_context.directory
        self._set_feedback_stage("OpenOCD 执行中", ProgressMode.INDETERMINATE)
        self._set_status()
        self._refresh_controls()
        self._start_worker(
            "flash-read-result",
            lambda: run_flash_read(
                config,
                request,
                log_context.directory,
                operation=operation,
                target=target if hasattr(target, "name") else None,
                target_name=str(getattr(target, "name", "")),
                stdout_log_path=log_context.stdout_log,
                stderr_log_path=log_context.stderr_log,
            ),
            owner=operation,
        )

    def _flash(self) -> None:
        if self._hardware_busy():
            self._show_busy()
            return
        try:
            if not self._check_firmware_external_change():
                return
            self._begin_feedback("烧录并校验", "准备固件与目标配置")
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            request = build_flash_request(self.firmware_var.get().strip(), self.bin_address_var.get().strip())
            log_dir = self._log_dir()
            target = snapshot.target
        except Exception as exc:
            self._fail_feedback("无法烧录", str(exc))
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
            self.operation_feedback.reset()
            self._refresh_operation_feedback()
            return
        try:
            log_context = create_session_logs(
                log_dir,
                device=facts.device,
                task="FLASH",
                metadata={
                    "probe": "ST-Link",
                    "target_cfg": config.target_cfg,
                    "interface_cfg": config.interface_cfg,
                    "firmware": str(request.firmware.resolve()),
                    "base_address": request.base_address,
                },
            )
            operation = OpenOcdOperation(timeout=300.0, background=True)
            try:
                self._begin_one_shot(SessionState.FLASH, operation)
            except Exception:
                log_context.finalize("not_started")
                raise
            self._operation_logs[operation] = log_context
        except BusySessionError:
            self._show_busy()
            return
        except Exception as exc:
            self._fail_feedback("无法创建烧录日志", str(exc))
            return
        self.operation_feedback.log_dir = log_context.directory
        self._set_feedback_stage("OpenOCD 执行中", ProgressMode.INDETERMINATE)
        self._set_status()
        self._refresh_controls()
        self._start_worker(
            "flash-result",
            lambda: run_flash(
                config,
                request,
                log_context.directory,
                operation=operation,
                target=target if hasattr(target, "name") else None,
                target_name=str(getattr(target, "name", "")),
                stdout_log_path=log_context.stdout_log,
                stderr_log_path=log_context.stderr_log,
            ),
            owner=operation,
        )

    def _start_vofa_rtt(self) -> None:
        self._start_rtt(vofa=True)

    def _start_rtt(self, *, vofa: bool = False) -> None:
        if self._hardware_busy():
            self._show_busy()
            return
        task_name = "RTT → VOFA+" if vofa else "RTT 日志采集"
        self._begin_feedback(task_name, "准备 RTT 配置")
        bridge: VofaTcpBridge | None = None
        vofa_process: subprocess.Popen | None = None
        log_context: SessionLogContext | None = None
        try:
            snapshot = self._obtain_fresh_snapshot()
            config = self._build_openocd_config(snapshot)
            facts = cast(ProjectTargetFacts, snapshot.facts)
            vofa_executable: Path | None = None
            vofa_host = ""
            vofa_port = 0
            if vofa:
                vofa_executable = self._obtain_vofa_executable()
                vofa_host, vofa_port = parse_listen_address(self.vofa_listen_var.get())
            request = build_rtt_request(
                manual=self.rtt_manual_var.get(),
                address=self.rtt_address_var.get().strip(),
                ram_origin=facts.ram_origin,
                ram_size=facts.ram_size,
                port="19022" if vofa else self.rtt_port_var.get().strip(),
                channel="1" if vofa else self.rtt_channel_var.get().strip(),
            )
            timeout_ms = int(self.rtt_timeout_var.get().strip())
            if timeout_ms <= 0:
                raise ValueError("RTT 扫描超时必须大于 0。")
            log_dir = self._log_dir()
            log_context = create_session_logs(
                log_dir,
                device=facts.device,
                task="RTT_VOFA" if vofa else "RTT",
                metadata={
                    "probe": "ST-Link",
                    "target_cfg": config.target_cfg,
                    "interface_cfg": config.interface_cfg,
                    "scan_address": f"0x{request.scan_address:08X}",
                    "scan_size": request.scan_size,
                    "channel": request.channel,
                    "port": request.port,
                    "mode": "vofa_justfloat" if vofa else "text",
                    "vofa_listen": self.vofa_listen_var.get().strip() if vofa else "",
                },
            )
            log_paths = RttLogPaths(
                channel=log_context.primary_log,
                stdout=log_context.stdout_log,
                stderr=log_context.stderr_log,
            )
            session = RttSession(
                config,
                request,
                log_paths.channel,
                connect_timeout=timeout_ms / 1000.0,
                background=True,
                parse_records=not vofa,
            )
            if vofa:
                raw_output = log_context.directory / "rtt-justfloat.bin"
                bridge = VofaTcpBridge(
                    vofa_host,
                    vofa_port,
                    raw_output=raw_output,
                )
                bridge.start()
                vofa_process = subprocess.Popen(
                    [str(vofa_executable)],
                    cwd=vofa_executable.parent,
                    **background_process_kwargs(),
                )
            self.gate.begin(SessionState.RTT_SCAN)
            try:
                self._rtt_lifecycle.begin_start(session)
            except Exception:
                self.gate.finish()
                raise
        except BusySessionError:
            if bridge is not None:
                bridge.stop()
            if log_context is not None:
                log_context.finalize("not_started")
            self._show_busy()
            return
        except Exception as exc:
            if bridge is not None:
                bridge.stop()
            if log_context is not None:
                try:
                    log_context.finalize("not_started")
                except OSError:
                    pass
            self._fail_feedback(f"无法启动 {task_name}", str(exc))
            return

        self._rtt_session = session
        self._rtt_log_paths = log_paths
        self._rtt_log_context = log_context
        self._vofa_bridge = bridge
        self._vofa_process = vofa_process
        self._rtt_started_at = None
        self._rtt_bytes = 0
        self._rtt_lines = 0
        self._rtt_error_message = ""
        self.operation_feedback.log_dir = log_context.directory
        self._set_feedback_stage("扫描 RTT 控制块", ProgressMode.INDETERMINATE)
        self.elapsed_var.set("00:00:00")
        self.counts_var.set("0 字节 / 0 帧 / 等待 VOFA+" if vofa else "0 字节 / 0 行")
        self._append_openocd(
            "[RTT]\n"
            f"命令: {subprocess.list2cmdline(session.command)}\n"
            f"RTT 日志: {log_paths.channel}\n"
            f"OpenOCD stdout: {log_paths.stdout}\n"
            f"OpenOCD stderr: {log_paths.stderr}\n"
            + (
                f"VOFA+ TCP: {self.vofa_listen_var.get().strip()} (JustFloat)\n"
                f"RTT 原始数据: {log_context.directory / 'rtt-justfloat.bin'}\n"
                if vofa
                else ""
            )
        )
        self._set_status()
        self._refresh_controls()
        self._start_worker("rtt-start-settled", session.start, owner=session)

    def _stop_rtt(self) -> None:
        session = self._rtt_session
        if session is None:
            return
        action = self._rtt_lifecycle.request_stop()
        self.operation_feedback.stopping("正在停止 RTT 并清理 OpenOCD")
        self._refresh_operation_feedback()
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

    def _begin_one_shot(self, state: SessionState, operation: OpenOcdOperation) -> None:
        self.gate.begin(state)
        try:
            self._one_shot_lifecycle.begin(operation)
        except Exception:
            self.gate.finish()
            raise

    def _poll_events(self) -> None:
        if self._destroyed:
            return
        session = self._rtt_session
        batch = self._event_poller.drain(
            self._events,
            session.events if session is not None else None,
        )
        for item in batch.items:
            if item.source == "ui":
                self._handle_ui_event(cast(_UiEvent, item.event))
            else:
                self._handle_rtt_event(cast(RttEvent, item.event))
        self._update_elapsed()
        feedback = getattr(self, "operation_feedback", None)
        now = time.monotonic()
        refresh_due = now - getattr(self, "_last_operation_feedback_refresh", 0.0) >= 0.1
        if (
            feedback is not None
            and feedback.state in {OperationVisualState.RUNNING, OperationVisualState.STOPPING}
            and refresh_due
        ):
            self._refresh_operation_feedback()
            self._last_operation_feedback_refresh = now
        if not self._destroyed:
            self.root.after(0 if batch.backlog else 50, self._poll_events)

    def _handle_ui_event(self, event: _UiEvent) -> None:
        if event.kind == "connection-result":
            operation, value = event.value
            self._settle_one_shot_result(operation, value, self._finish_connection)
        elif event.kind == "flash-result":
            operation, value = event.value
            self._settle_one_shot_result(operation, value, self._finish_flash)
        elif event.kind == "flash-read-result":
            operation, value = event.value
            self._settle_one_shot_result(operation, value, self._finish_flash_read)
        elif event.kind == "one-shot-cleanup-settled":
            operation, value = event.value
            self._finish_one_shot_cleanup(operation, value)
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

    def _settle_one_shot_result(
        self,
        operation: object,
        value: object,
        finish: Callable[[object], None],
    ) -> None:
        if not self._one_shot_lifecycle.owns(operation):
            return
        outcome = str(getattr(value, "outcome", "failed"))
        self._one_shot_lifecycle.result_settled(operation, outcome)
        if outcome != "incomplete":
            self._finalize_operation_log(operation, outcome)
        finish(value)
        if outcome == "incomplete" and self._one_shot_lifecycle.owns(operation):
            log_path = getattr(value, "stderr_log", None)
            self._one_shot_cleanup_log = log_path if isinstance(log_path, Path) else None
            self._dispatch_one_shot_cleanup(cast(OpenOcdOperation, operation))

    def _dispatch_one_shot_cleanup(self, operation: OpenOcdOperation) -> None:
        if not self._one_shot_lifecycle.begin_cleanup(operation):
            return
        self.status_var.set("正在重试清理 OpenOCD 进程")
        self.operation_feedback.stopping("正在清理 OpenOCD 进程")
        self._refresh_operation_feedback()
        self._refresh_controls()
        self._start_worker(
            "one-shot-cleanup-settled",
            operation.retry_cleanup,
            owner=operation,
        )

    def _finish_one_shot_cleanup(self, operation: object, value: object) -> None:
        if not self._one_shot_lifecycle.owns(operation):
            return
        if not isinstance(value, OpenOcdCleanupResult):
            self._one_shot_lifecycle.cleanup_settled(operation, complete=False)
            self._handle_worker_error(
                "one-shot-cleanup-settled",
                RuntimeError("OpenOCD 清理返回了无效结果。"),
                operation,
            )
            return
        self._append_openocd(f"\n[OpenOCD 清理] {value.message}\n")
        if self._one_shot_cleanup_log is not None:
            try:
                with self._one_shot_cleanup_log.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(f"\n[KeilTool] {value.message}\n")
            except OSError as exc:
                self._append_openocd(f"[OpenOCD 清理日志写入失败] {exc}\n")
        released = self._one_shot_lifecycle.cleanup_settled(operation, complete=value.complete)
        if released:
            self._finalize_operation_log(operation, "incomplete_cleaned")
            self._one_shot_cleanup_log = None
            self.status_var.set("OpenOCD 进程已确认退出")
            self._fail_feedback(
                self.operation_feedback.summary or "操作未完成，但 OpenOCD 进程已退出",
                self.operation_feedback.detail,
                log_dir=self.operation_feedback.log_dir,
                returncode=self.operation_feedback.returncode,
            )
        else:
            self.status_var.set("OpenOCD 清理仍不完整；再次关闭窗口可重试")
            self.operation_feedback.incomplete(
                "OpenOCD 进程尚未确认退出",
                "硬件操作和窗口关闭已阻止；关闭窗口可再次重试清理。",
            )
            self._refresh_operation_feedback()
        self._refresh_controls()
        self._finish_close_if_ready()

    def _finish_connection(self, value: object) -> None:
        if not isinstance(value, ConnectionResult):
            self._handle_worker_error("connection-result", RuntimeError("连接检查返回了无效结果。"), None)
            return
        self._set_feedback_stage("分析连接结果", ProgressMode.DETERMINATE, 90)
        self._render_openocd_result("连接检查", value)
        if value.success:
            self.gate.finish()
            self.status_var.set("连接检查成功")
            self._complete_feedback(
                "已确认 ST-Link 与目标内核连接",
                log_dir=value.stdout_log.parent,
            )
        else:
            self.gate.fail()
            self.status_var.set("连接检查失败")
            self._fail_feedback(
                "连接检查失败",
                self._result_error_summary(value),
                log_dir=value.stdout_log.parent,
                returncode=value.returncode,
            )
        self._refresh_controls()
        self._finish_close_if_ready()

    def _finish_flash(self, value: object) -> None:
        if not isinstance(value, FlashResult):
            self._handle_worker_error("flash-result", RuntimeError("烧录返回了无效结果。"), None)
            return
        self._set_feedback_stage("分析烧录与校验结果", ProgressMode.DETERMINATE, 90)
        self._render_openocd_result("烧录并校验", value)
        if value.success:
            self.gate.finish()
            self.status_var.set("烧录并校验成功")
            self._complete_feedback(
                "固件写入与校验均已通过",
                log_dir=value.stdout_log.parent,
            )
        else:
            self.gate.fail()
            self.status_var.set("烧录或校验失败")
            self._fail_feedback(
                "烧录或校验失败",
                self._result_error_summary(value),
                log_dir=value.stdout_log.parent,
                returncode=value.returncode,
            )
        self._refresh_controls()
        self._finish_close_if_ready()

    def _finish_flash_read(self, value: object) -> None:
        if not isinstance(value, FlashReadResult):
            self._handle_worker_error(
                "flash-read-result",
                RuntimeError("Flash 读取返回了无效结果。"),
                None,
            )
            return
        self._set_feedback_stage("校验镜像大小与摘要", ProgressMode.DETERMINATE, 90)
        self._render_openocd_result("读取完整 Flash", value)
        self._append_openocd(
            "----- Flash 镜像 -----\n"
            f"起始地址: 0x{value.address:08X}\n"
            f"请求大小: {value.requested_size:,} 字节\n"
            f"实际大小: {value.actual_size:,} 字节\n"
            f"输出文件: {value.output}\n"
            f"SHA-256: {value.sha256 or '未生成'}\n\n"
        )
        if value.success:
            self.gate.finish()
            self.status_var.set("完整 Flash 读取成功")
            self._complete_feedback(
                f"已读取并校验 {value.actual_size:,} 字节，SHA-256: {value.sha256}",
                artifact=value.output,
                log_dir=value.stdout_log.parent,
            )
        else:
            self.gate.fail()
            self.status_var.set("Flash 读取失败")
            self._fail_feedback(
                "完整 Flash 读取失败",
                self._result_error_summary(value),
                log_dir=value.stdout_log.parent,
                returncode=value.returncode,
            )
        self._refresh_controls()
        self._finish_close_if_ready()

    def _handle_worker_error(self, operation: object, error: object, owner: object | None) -> None:
        message = str(error)
        retry_operation: OpenOcdOperation | None = None
        self._append_openocd(f"\n[后台任务失败] {operation}: {message}\n")
        if operation == "one-shot-cleanup-settled" and owner is not None:
            self._one_shot_lifecycle.cleanup_settled(owner, complete=False)
        elif owner is not None and self._one_shot_lifecycle.owns(owner):
            cleanup_pending = isinstance(owner, OpenOcdOperation) and owner.cleanup_pending
            self._one_shot_lifecycle.worker_failed(owner, cleanup_pending=cleanup_pending)
            if cleanup_pending:
                retry_operation = cast(OpenOcdOperation, owner)
            else:
                self._finalize_operation_log(owner, "worker_error")
            self.gate.fail()
        elif str(operation).startswith("rtt") and owner is not None:
            self._rtt_error_message = message
            operation_name = "start" if operation == "rtt-start-settled" else "stop"
            action = self._rtt_lifecycle.worker_failed(owner, operation_name)
            if action is LifecycleAction.STOP_SESSION:
                self._dispatch_rtt_stop(cast(RttSession, owner))
        else:
            self.gate.fail()
        self.status_var.set(f"失败: {message}")
        log_dir = self.operation_feedback.log_dir
        self._fail_feedback("后台任务失败", message, log_dir=log_dir)
        self._refresh_controls()
        if retry_operation is not None:
            self._dispatch_one_shot_cleanup(retry_operation)
        self._finish_close_if_ready()

    def _handle_rtt_event(self, event: RttEvent) -> None:
        if event.kind == "openocd":
            self._append_openocd(event.text)
            self._persist_rtt_openocd_event(event)
        elif event.kind == "raw" and self._vofa_bridge is not None:
            try:
                self._vofa_bridge.feed(event.data)
            except OSError as exc:
                self._rtt_error_message = f"RTT 原始数据写入失败: {exc}"
                self._fail_feedback(
                    "VOFA+ 数据保存失败",
                    self._rtt_error_message,
                    log_dir=self.operation_feedback.log_dir,
                )
                self.root.after_idle(self._stop_rtt)
                return
            self._rtt_bytes += len(event.data)
            self._update_vofa_summary()
        elif event.kind == "data":
            level = event.level if event.level is not None else RttLevel.INFO
            terminal = event.terminal if event.terminal is not None else 0
            threshold = parse_rtt_level(self.rtt_display_level_var.get())
            chunks = event.text.splitlines(keepends=True) or ([event.text] if event.text else [])
            for text in chunks:
                record = RttLogRecord(level=level, text=text, terminal=terminal)
                evicted = self._rtt_display.append(record)
                if evicted is not None and evicted.level <= threshold:
                    self.output.remove_first_rtt_record(evicted)
                if record.level <= threshold:
                    self.output.append_rtt_record(record)
            self._update_rtt_visible_counts()
            self._rtt_bytes += len(event.text.encode("utf-8", errors="replace"))
            self._rtt_lines += event.text.count("\n")
            self.counts_var.set(f"{self._rtt_bytes:,} 字节 / {self._rtt_lines:,} 行")
            if (
                self.operation_feedback.task == "RTT 日志采集"
                and self.operation_feedback.state is OperationVisualState.RUNNING
            ):
                self.operation_feedback.summary = self.counts_var.get()
        elif event.kind == "connected":
            if self.gate.state is SessionState.RTT_SCAN:
                self.gate.finish()
                self.gate.begin(SessionState.RTT)
            self._rtt_started_at = time.monotonic()
            if self._vofa_bridge is not None:
                self.status_var.set("RTT → VOFA+ 运行中")
                self._set_feedback_stage("正在转发 JustFloat 曲线", ProgressMode.INDETERMINATE)
                self._update_vofa_summary()
            else:
                self.status_var.set("RTT 采集中")
                self._set_feedback_stage("正在采集 RTT 日志", ProgressMode.INDETERMINATE)
            self._append_openocd(f"{event.message}\n")
            self._refresh_controls()
        elif event.kind in {"error", "eof"}:
            self._append_openocd(f"[RTT] {event.message}\n")
            self.status_var.set(f"RTT 异常: {event.message}")
            self._rtt_error_message = event.message
            self._fail_feedback(
                "RTT 采集异常",
                event.message,
                log_dir=self.operation_feedback.log_dir,
            )
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
                self.operation_feedback.incomplete(
                    "RTT 清理不完整",
                    "OpenOCD 或 RTT 工作线程尚未完全退出；请点击“停止采集”重试清理。",
                )
                self._refresh_operation_feedback()
            elif action is LifecycleAction.RELEASE_SESSION:
                vofa_stats = None
                if self._vofa_bridge is not None:
                    bridge = self._vofa_bridge
                    bridge.stop()
                    vofa_stats = bridge.stats
                    self._vofa_bridge = None
                    self._vofa_process = None
                if event.outcome == "startup_failed":
                    self.gate.fail()
                    self.status_var.set("RTT 启动失败")
                    self._fail_feedback(
                        "RTT 启动失败",
                        self._rtt_error_message or event.message,
                        log_dir=self.operation_feedback.log_dir,
                    )
                elif self._rtt_error_message:
                    self.gate.fail()
                    self.status_var.set("RTT 因异常停止")
                    self._fail_feedback(
                        "RTT 采集异常并已停止",
                        self._rtt_error_message,
                        log_dir=self.operation_feedback.log_dir,
                    )
                else:
                    self.gate.finish()
                    self.status_var.set("RTT 已停止")
                    summary = (
                        f"RTT → VOFA+ 已停止，共接收 {self._rtt_bytes:,} 字节，"
                        f"转发 {vofa_stats.frames_forwarded:,} 帧，"
                        f"丢弃 {vofa_stats.frames_dropped:,} 帧，"
                        f"无效 {vofa_stats.invalid_frames:,} 帧"
                        if vofa_stats is not None
                        else f"RTT 已停止，共采集 {self._rtt_bytes:,} 字节 / {self._rtt_lines:,} 行"
                    )
                    self._complete_feedback(
                        summary,
                        log_dir=self.operation_feedback.log_dir,
                    )
                if self._rtt_log_context is not None:
                    try:
                        self._rtt_log_context.finalize(event.outcome)
                    except OSError as exc:
                        self._append_openocd(f"[RTT 日志结束信息写入失败] {exc}\n")
                self._rtt_session = None
                self._rtt_log_paths = None
                self._rtt_log_context = None
            else:
                return
            self._rtt_started_at = None
            self._refresh_controls()
            self._finish_close_if_ready()

    def _update_vofa_summary(self) -> None:
        bridge = self._vofa_bridge
        if bridge is None:
            return
        stats = bridge.stats
        client = "VOFA+ 已连接" if stats.active_clients else "等待 VOFA+"
        summary = (
            f"{self._rtt_bytes:,} 字节 / {stats.frames_forwarded:,} 帧 / {client}"
        )
        if stats.frames_dropped or stats.invalid_frames:
            summary += (
                f" / 丢弃 {stats.frames_dropped:,} / 无效 {stats.invalid_frames:,}"
            )
        self.counts_var.set(summary)
        if (
            self.operation_feedback.task == "RTT → VOFA+"
            and self.operation_feedback.state is OperationVisualState.RUNNING
        ):
            self.operation_feedback.summary = summary

    def _on_rtt_level_changed(self) -> None:
        view = build_rtt_view(self._rtt_display, self.rtt_display_level_var.get())
        self.output.render_rtt_records(view.records)
        self.rtt_visible_counts_var.set(view.label)

    def _update_rtt_visible_counts(self) -> None:
        view = build_rtt_view(self._rtt_display, self.rtt_display_level_var.get())
        self.rtt_visible_counts_var.set(view.label)

    def _clear_rtt_display(self) -> None:
        self._rtt_display.clear()
        self.output.clear_rtt()
        self._update_rtt_visible_counts()

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

    def _finalize_operation_log(self, owner: object, outcome: str) -> None:
        context = self._operation_logs.pop(owner, None)
        if context is None:
            return
        try:
            context.finalize(outcome)
        except OSError as exc:
            self._append_openocd(f"[日志结束信息写入失败] {exc}\n")

    def _render_openocd_result(
        self,
        title: str,
        result: ConnectionResult | FlashResult | FlashReadResult,
    ) -> None:
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
    def _result_error_summary(
        result: ConnectionResult | FlashResult | FlashReadResult,
    ) -> str:
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
        project_mode = self.device_source_mode_var.get() == _PROJECT_SOURCE
        controls.device_label.configure(
            text="Device（来自工程）" if project_mode else "Device"
        )
        controls.project_source_radio.configure(
            state=(
                "disabled"
                if busy or not self.project_var.get().strip()
                else "normal"
            )
        )
        controls.device_source_radio.configure(state="disabled" if busy else "normal")
        controls.target_combo.configure(
            state="readonly" if not busy and project_mode else "disabled"
        )
        controls.device_combo.configure(
            state="disabled" if busy or project_mode else "normal"
        )
        controls.bin_address_entry.configure(state="disabled" if busy or firmware_is_hex else "normal")
        controls.rtt_address_entry.configure(
            state="normal" if not busy and self.rtt_manual_var.get() else "disabled"
        )

        ready = self._freshness.is_current(self._visible_fact_inputs()) and is_target_ready(self._facts)
        idle = not busy
        controls.connect_button.configure(state="normal" if idle and ready else "disabled")
        flash_read_ready = bool(
            self._facts
            and getattr(self._facts, "flash_range_complete", False)
            and getattr(self._facts, "flash_origin", None) is not None
            and getattr(self._facts, "flash_size", None)
        )
        controls.flash_read_button.configure(
            state="normal" if idle and ready and flash_read_ready else "disabled"
        )
        controls.flash_button.configure(
            state=(
                "normal"
                if idle
                and ready
                and is_firmware_ready(self.firmware_var.get().strip())
                and self._current_firmware_freshness().accepts_path(
                    self.firmware_var.get().strip()
                )
                else "disabled"
            )
        )
        auto_rtt_ready = bool(self._facts and self._facts.ram_origin is not None and self._facts.ram_size)
        rtt_fields_ready = self.rtt_manual_var.get() or auto_rtt_ready
        controls.rtt_start_button.configure(
            state="normal" if idle and ready and rtt_fields_ready else "disabled"
        )
        controls.vofa_start_button.configure(
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
        return (
            self.gate.state in _BUSY_STATES
            or self._one_shot_lifecycle.owns_operation
            or self._rtt_lifecycle.owns_session
        )

    def _set_status(self) -> None:
        self.status_var.set(_STATE_TEXT[self.gate.state])

    def _show_busy(self) -> None:
        self.status_var.set(f"当前任务仍在执行: {_STATE_TEXT[self.gate.state]}")

    def _update_elapsed(self) -> None:
        if self._rtt_started_at is None:
            return
        elapsed = max(0, int(time.monotonic() - self._rtt_started_at))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self._update_vofa_summary()

    def _append_openocd(self, text: str) -> None:
        self.output.append_openocd(text)

    def _refresh_operation_feedback(self) -> None:
        self.operation_status.update(self.operation_feedback)

    def _begin_feedback(self, task: str, stage: str) -> None:
        self.operation_feedback.begin(task, stage)
        self._refresh_operation_feedback()

    def _set_feedback_stage(
        self,
        stage: str,
        mode: ProgressMode,
        value: int | None = None,
    ) -> None:
        self.operation_feedback.set_stage(stage, mode, value)
        self._refresh_operation_feedback()

    def _complete_feedback(
        self,
        summary: str,
        *,
        artifact: Path | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.operation_feedback.succeed(
            summary,
            artifact=artifact,
            log_dir=log_dir or self.operation_feedback.log_dir,
        )
        self._refresh_operation_feedback()

    def _fail_feedback(
        self,
        summary: str,
        detail: str = "",
        *,
        log_dir: Path | None = None,
        returncode: int | None = None,
    ) -> None:
        self.operation_feedback.fail(
            summary,
            detail=detail,
            log_dir=log_dir or self.operation_feedback.log_dir,
            returncode=returncode,
        )
        self.output.select_openocd()
        self._refresh_operation_feedback()

    def _copy_operation_error(self) -> None:
        text = self.operation_feedback.copyable_error
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("错误详情已复制")

    def _open_operation_log_dir(self) -> None:
        path = self.operation_feedback.log_dir
        if path is None:
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name != "nt" or not hasattr(os, "startfile"):
                raise OSError("当前平台不支持通过资源管理器打开目录。")
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            self.status_var.set(f"无法打开任务日志目录: {exc}")

    def _render_settings_diagnostic(self, diagnostic: SettingsDiagnostic) -> None:
        self._append_openocd(
            f"[Settings warning] {diagnostic.code}: {diagnostic.message}\n\n"
        )

    def _open_logs_dir(self) -> None:
        try:
            path = self._log_dir()
            path.mkdir(parents=True, exist_ok=True)
            if os.name != "nt" or not hasattr(os, "startfile"):
                raise OSError("当前平台不支持通过资源管理器打开目录。")
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            self._fail_feedback("无法打开日志目录", str(exc))

    def _on_close(self) -> None:
        if self._closing:
            if self._one_shot_lifecycle.phase is OneShotPhase.INCOMPLETE:
                operation = self._one_shot_lifecycle.owner
                if isinstance(operation, OpenOcdOperation):
                    self._dispatch_one_shot_cleanup(operation)
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
            self._one_shot_lifecycle.request_close()
            if self._one_shot_lifecycle.phase is OneShotPhase.INCOMPLETE:
                operation = self._one_shot_lifecycle.owner
                if isinstance(operation, OpenOcdOperation):
                    self._dispatch_one_shot_cleanup(operation)
            action = self._rtt_lifecycle.request_close()
            if action is LifecycleAction.STOP_SESSION and self._rtt_session is not None:
                self._dispatch_rtt_stop(self._rtt_session)
            return
        self._closing = True
        self._one_shot_lifecycle.request_close()
        self._rtt_lifecycle.request_close()
        self._finish_close_if_ready()

    def _finish_close_if_ready(self) -> None:
        if (
            self._closing
            and self.gate.state not in _BUSY_STATES
            and self._one_shot_lifecycle.can_destroy
            and self._rtt_lifecycle.can_destroy
        ):
            self._destroy()

    def _destroy(self) -> None:
        if self._destroyed:
            return
        if (
            self._hardware_busy()
            or not self._one_shot_lifecycle.can_destroy
            or not self._rtt_lifecycle.can_destroy
        ):
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
                    self._one_shot_lifecycle.cancel_close()
                    self._rtt_lifecycle.cancel_close()
                    self.status_var.set("设置未保存，已取消关闭")
                    self._refresh_controls()
                    return
                break
        self._destroyed = True
        self.root.destroy()

    def _current_settings(self) -> GuiSettings:
        mode = self.device_source_mode_var.get()
        if mode == _PROJECT_SOURCE:
            self._remember_project_context()
        else:
            self._remember_device_context()
        selected = self._independent_device
        return GuiSettings(
            project=self.project_var.get().strip(),
            target=self._project_target,
            firmware=self.firmware_var.get().strip(),
            bin_address=self.bin_address_var.get().strip(),
            openocd_path=self.openocd_var.get().strip(),
            scripts_dir=self.scripts_var.get().strip(),
            target_override=self.target_override_var.get().strip(),
            rtt_address=self.rtt_address_var.get().strip() if self.rtt_manual_var.get() else "",
            rtt_channel=int_or_default(self.rtt_channel_var.get(), 0),
            rtt_port=int_or_default(self.rtt_port_var.get(), 19021),
            rtt_timeout_ms=int_or_default(self.rtt_timeout_var.get(), 5000),
            rtt_display_level=self.rtt_display_level_var.get(),
            logs_dir=self.logs_dir_var.get().strip(),
            device_vendor=selected.vendor if selected else "",
            device_name=selected.device if selected else "",
            device_source_mode=mode,
            project_firmware=self._project_firmware,
            device_firmware=self._device_firmware,
            vofa_path=self.vofa_path_var.get().strip(),
            vofa_listen=self.vofa_listen_var.get().strip() or "127.0.0.1:1347",
        )


def launch_gui() -> None:
    root = tk.Tk()
    KeilToolGui(root)
    root.mainloop()


__all__ = [
    "KeilToolGui",
    "launch_gui",
]
