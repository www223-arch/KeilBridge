from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Protocol

from keiltool.core.rtt_log import RttLogRecord
from keiltool.gui.operation_feedback import (
    OperationFeedback,
    OperationVisualState,
    ProgressMode,
)
from keiltool.gui.rtt_display import RTT_LEVEL_NAMES
from keiltool.gui.theme import configure_log_text


def path_row(
    parent: ttk.Frame,
    row: int,
    label: str,
    variable: tk.StringVar,
    command: Callable[[], None] | None = None,
) -> tuple[ttk.Entry, ttk.Button]:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
    entry = ttk.Entry(parent, textvariable=variable)
    entry.grid(row=row, column=1, sticky="ew", pady=3)
    button = ttk.Button(parent, text="选择", width=6)
    if command is not None:
        button.configure(command=command)
    button.grid(row=row, column=2, sticky="e", padx=(6, 0), pady=3)
    return entry, button


def readonly_row(parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
    entry = ttk.Entry(parent, textvariable=variable, state="readonly")
    entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)


class WorkbenchVariables(Protocol):
    project_var: tk.StringVar
    target_var: tk.StringVar
    device_var: tk.StringVar
    device_choice_var: tk.StringVar
    device_source_var: tk.StringVar
    device_source_mode_var: tk.StringVar
    flash_summary_var: tk.StringVar
    ram_summary_var: tk.StringVar
    target_cfg_var: tk.StringVar
    resolution_var: tk.StringVar
    firmware_var: tk.StringVar
    bin_address_var: tk.StringVar
    flash_read_format_var: tk.StringVar
    probe_choice_var: tk.StringVar
    probe_status_var: tk.StringVar
    rtt_manual_var: tk.BooleanVar
    rtt_address_var: tk.StringVar
    rtt_channel_var: tk.StringVar
    logs_dir_var: tk.StringVar
    openocd_var: tk.StringVar
    scripts_var: tk.StringVar
    target_override_var: tk.StringVar
    rtt_port_var: tk.StringVar
    rtt_timeout_var: tk.StringVar
    vofa_path_var: tk.StringVar
    vofa_listen_var: tk.StringVar
    vofa_up_channel_var: tk.StringVar
    vofa_up_port_var: tk.StringVar
    vofa_up_name_var: tk.StringVar
    vofa_down_channel_var: tk.StringVar
    vofa_down_port_var: tk.StringVar
    vofa_down_name_var: tk.StringVar
    vofa_expected_float_count_var: tk.StringVar
    vofa_connection_hint_var: tk.StringVar
    collector_device_status_var: tk.StringVar


class OperationStatusPane(ttk.Frame):
    _STATE_PRESENTATION = {
        OperationVisualState.IDLE: ("空闲", "Idle"),
        OperationVisualState.RUNNING: ("执行中", "Running"),
        OperationVisualState.SUCCEEDED: ("完成", "Succeeded"),
        OperationVisualState.FAILED: ("失败", "Failed"),
        OperationVisualState.STOPPING: ("停止中", "Stopping"),
        OperationVisualState.INCOMPLETE: ("清理不完整", "Incomplete"),
    }

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, height=112, padding=(10, 7), style="Operation.TFrame")
        self.grid_propagate(False)
        self.columnconfigure(1, weight=1)
        self.task_var = tk.StringVar(value="当前任务")
        self.state_var = tk.StringVar(value="空闲")
        self.stage_var = tk.StringVar(value="等待操作")
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.summary_var = tk.StringVar(value="")
        self._active_progress: tuple[ProgressMode, str] | None = None

        ttk.Label(self, textvariable=self.task_var, style="OperationTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.state_label = ttk.Label(
            self,
            textvariable=self.state_var,
            style="OperationIdle.TLabel",
        )
        self.state_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(self, textvariable=self.elapsed_var, style="Operation.TLabel").grid(
            row=0, column=2, sticky="e"
        )
        ttk.Label(self, textvariable=self.stage_var, style="Operation.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(5, 2)
        )
        self.progress = ttk.Progressbar(
            self,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="OperationIdle.Horizontal.TProgressbar",
        )
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")
        footer = ttk.Frame(self, style="Operation.TFrame")
        footer.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            textvariable=self.summary_var,
            width=1,
            style="Operation.TLabel",
        ).grid(row=0, column=0, sticky="ew")
        self.copy_button = ttk.Button(footer, text="复制错误", state="disabled")
        self.copy_button.grid(row=0, column=1, padx=(6, 0))
        self.logs_button = ttk.Button(footer, text="打开日志", state="disabled")
        self.logs_button.grid(row=0, column=2, padx=(6, 0))

    def set_copy_command(self, callback: Callable[[], None]) -> None:
        self.copy_button.configure(command=callback)

    def set_open_logs_command(self, callback: Callable[[], None]) -> None:
        self.logs_button.configure(command=callback)

    def update(self, feedback: OperationFeedback, *, now: float | None = None) -> None:
        state_text, style_name = self._STATE_PRESENTATION[feedback.state]
        self.task_var.set(feedback.task)
        self.state_var.set(state_text)
        self.stage_var.set(feedback.stage)
        self.elapsed_var.set(_format_elapsed(feedback.elapsed(now)))
        self.summary_var.set(feedback.summary)
        self.state_label.configure(style=f"Operation{style_name}.TLabel")
        self.progress.configure(style=f"Operation{style_name}.Horizontal.TProgressbar")
        active = (feedback.progress_mode, style_name)
        if active != self._active_progress:
            self.progress.stop()
            if feedback.progress_mode is ProgressMode.INDETERMINATE:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
            else:
                self.progress.configure(mode="determinate")
            self._active_progress = active
        if feedback.progress_mode is not ProgressMode.INDETERMINATE:
            self.progress.configure(value=feedback.progress_value)
        self.copy_button.configure(state="normal" if feedback.copyable_error else "disabled")
        self.logs_button.configure(state="normal" if feedback.log_dir else "disabled")


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class AdvancedSettingsDialog(tk.Toplevel):
    """Scrollable RTT/OpenOCD settings kept outside the fixed-height main pane."""

    def __init__(self, parent: tk.Misc, variables: WorkbenchVariables) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("RTT 高级设置")
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.minsize(540, 400)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        viewport = ttk.Frame(self)
        viewport.grid(row=0, column=0, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(
            viewport,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.content = ttk.Frame(self.canvas, padding=14)
        self.content.columnconfigure(1, weight=1)
        self._content_window = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )
        self.content.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_content_width)
        self._build_fields(variables)

        footer = ttk.Frame(self)
        footer.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 12))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="关闭", command=self.close).grid(row=0, column=1)

    def _build_fields(self, variables: WorkbenchVariables) -> None:
        self.openocd_entry, self.openocd_button = path_row(
            self.content,
            0,
            "OpenOCD",
            variables.openocd_var,
        )
        self.scripts_entry, self.scripts_button = path_row(
            self.content,
            1,
            "scripts",
            variables.scripts_var,
        )
        self.override_entry, self.override_button = path_row(
            self.content,
            2,
            "target override",
            variables.target_override_var,
        )
        ttk.Label(self.content, text="文字 RTT 端口").grid(
            row=3, column=0, sticky="w", pady=3
        )
        self.port_entry = ttk.Entry(
            self.content,
            textvariable=variables.rtt_port_var,
            width=12,
        )
        self.port_entry.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(self.content, text="扫描超时(ms)").grid(
            row=4, column=0, sticky="w", pady=3
        )
        self.timeout_entry = ttk.Entry(
            self.content,
            textvariable=variables.rtt_timeout_var,
            width=12,
        )
        self.timeout_entry.grid(row=4, column=1, sticky="w", pady=3)
        self.vofa_entry, self.vofa_button = path_row(
            self.content,
            5,
            "VOFA+",
            variables.vofa_path_var,
        )
        ttk.Label(self.content, text="VOFA 监听").grid(
            row=6, column=0, sticky="w", pady=3
        )
        self.vofa_listen_entry = ttk.Entry(
            self.content,
            textvariable=variables.vofa_listen_var,
            width=20,
        )
        self.vofa_listen_entry.grid(row=6, column=1, sticky="w", pady=3)
        self.vofa_up_channel_entry, self.vofa_up_port_entry = _channel_port_row(
            self.content,
            7,
            "曲线 Up / 端口",
            variables.vofa_up_channel_var,
            variables.vofa_up_port_var,
        )
        ttk.Label(self.content, text="曲线 Up 名称").grid(
            row=8, column=0, sticky="w", pady=3
        )
        self.vofa_up_name_entry = ttk.Entry(
            self.content,
            textvariable=variables.vofa_up_name_var,
            width=20,
        )
        self.vofa_up_name_entry.grid(row=8, column=1, sticky="w", pady=3)
        self.vofa_down_channel_entry, self.vofa_down_port_entry = _channel_port_row(
            self.content,
            9,
            "反向 Down / 端口",
            variables.vofa_down_channel_var,
            variables.vofa_down_port_var,
        )
        ttk.Label(self.content, text="反向 Down 名称").grid(
            row=10, column=0, sticky="w", pady=3
        )
        self.vofa_down_name_entry = ttk.Entry(
            self.content,
            textvariable=variables.vofa_down_name_var,
            width=20,
        )
        self.vofa_down_name_entry.grid(row=10, column=1, sticky="w", pady=3)
        ttk.Label(self.content, text="固定浮点数 N").grid(
            row=11, column=0, sticky="w", pady=3
        )
        self.vofa_expected_float_count_entry = ttk.Entry(
            self.content,
            textvariable=variables.vofa_expected_float_count_var,
            width=12,
        )
        self.vofa_expected_float_count_entry.grid(row=11, column=1, sticky="w", pady=3)
        ttk.Label(self.content, text="0 = 不校验", style="Muted.TLabel").grid(
            row=11, column=2, sticky="w", pady=3
        )
        self.vofa_guide_button = ttk.Button(
            self.content,
            text="打开 RTT/VOFA 会话说明",
        )
        self.vofa_guide_button.grid(row=12, column=1, sticky="w", pady=3)

    def open(self) -> None:
        screen_height = max(480, self.winfo_screenheight())
        height = min(720, screen_height - 120)
        width = min(680, max(540, self.winfo_screenwidth() - 120))
        owner = self.master.winfo_toplevel()
        owner.update_idletasks()
        x = max(0, owner.winfo_rootx() + (owner.winfo_width() - width) // 2)
        y = max(0, owner.winfo_rooty() + (owner.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.update_idletasks()
        self.canvas.yview_moveto(0.0)
        self.port_entry.focus_set()

    def close(self) -> None:
        self.withdraw()

    def ensure_visible(self, widget: tk.Widget) -> None:
        self.update_idletasks()
        region = self.canvas.bbox("all")
        if region is None or region[3] <= region[1]:
            return
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        visible_height = self.canvas.winfo_height()
        total_height = region[3] - region[1]
        if top < visible_top:
            self.canvas.yview_moveto(max(0.0, top / total_height))
        elif bottom > visible_top + visible_height:
            offset = max(0, bottom - visible_height)
            self.canvas.yview_moveto(min(1.0, offset / total_height))

    def _sync_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_content_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._content_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"


def _channel_port_row(
    parent: ttk.Frame,
    row: int,
    label: str,
    channel_var: tk.StringVar,
    port_var: tk.StringVar,
) -> tuple[ttk.Entry, ttk.Entry]:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
    values = ttk.Frame(parent)
    values.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
    channel = ttk.Entry(values, textvariable=channel_var, width=6)
    channel.grid(row=0, column=0, sticky="w")
    port = ttk.Entry(values, textvariable=port_var, width=10)
    port.grid(row=0, column=1, sticky="w", padx=(8, 0))
    return channel, port


class ConfigurationPane(ttk.Frame):
    """Stable left-side project, flash, RTT, and advanced controls."""

    def __init__(self, parent: ttk.Frame, variables: WorkbenchVariables) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.editable_widgets: list[tuple[tk.Widget, str]] = []
        background = ttk.Style(self).lookup("Background.TFrame", "background")
        self.canvas = tk.Canvas(
            self,
            background=background,
            borderwidth=0,
            highlightthickness=0,
            width=420,
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = ttk.Frame(self.canvas, style="Background.TFrame")
        self.content.columnconfigure(0, weight=1)
        self._content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_content_width)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._build_project_section(self.content, variables)
        self._build_rtt_section(self.content, variables)
        self._build_advanced_section(self.content, variables)

    def _build_project_section(self, parent: ttk.Frame, variables: WorkbenchVariables) -> None:
        section = ttk.LabelFrame(parent, text="工程与烧录", padding=6)
        section.grid(row=0, column=0, sticky="ew")
        section.columnconfigure(1, weight=1)
        self.project_section = section

        self.project_entry, self.project_button = path_row(
            section,
            0,
            "Keil 工程",
            variables.project_var,
        )
        ttk.Label(section, text="Target").grid(row=1, column=0, sticky="w", pady=3)
        self.target_combo = ttk.Combobox(
            section,
            textvariable=variables.target_var,
            state="readonly",
            width=34,
        )
        self.target_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(section, text="使用的 ST-Link").grid(row=2, column=0, sticky="w", pady=3)
        probe_row = ttk.Frame(section)
        probe_row.grid(row=2, column=1, columnspan=2, sticky="ew", pady=3)
        probe_row.columnconfigure(0, weight=1)
        self.probe_combo = ttk.Combobox(
            probe_row,
            textvariable=variables.probe_choice_var,
            state="readonly",
            width=22,
        )
        self.probe_combo.grid(row=0, column=0, sticky="ew")
        self.probe_refresh_button = ttk.Button(probe_row, text="刷新", width=5)
        self.probe_refresh_button.grid(row=0, column=1, padx=(5, 0))
        self.probe_rename_button = ttk.Button(probe_row, text="命名", width=5)
        self.probe_rename_button.grid(row=0, column=2, padx=(5, 0))
        self.probe_driver_button = ttk.Button(probe_row, text="安装驱动", width=8)
        self.collector_device_status = ttk.Label(
            section,
            textvariable=variables.collector_device_status_var,
            style="Accent.TLabel",
        )
        ttk.Label(
            probe_row,
            textvariable=variables.probe_status_var,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        ttk.Label(section, text="配置来源").grid(row=3, column=0, sticky="w", pady=3)
        source_modes = ttk.Frame(section)
        source_modes.grid(row=3, column=1, columnspan=2, sticky="w", pady=3)
        self.project_source_radio = ttk.Radiobutton(
            source_modes,
            text="Keil 工程",
            variable=variables.device_source_mode_var,
            value="project",
        )
        self.project_source_radio.grid(row=0, column=0, sticky="w")
        self.device_source_radio = ttk.Radiobutton(
            source_modes,
            text="独立 Device",
            variable=variables.device_source_mode_var,
            value="device",
        )
        self.device_source_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.device_label = ttk.Label(section, text="Device")
        self.device_label.grid(row=4, column=0, sticky="w", pady=3)
        self.device_combo = ttk.Combobox(
            section,
            textvariable=variables.device_choice_var,
            state="normal",
            width=34,
        )
        self.device_combo.grid(row=4, column=1, sticky="ew", pady=3)
        self.device_import_button = ttk.Button(section, text="导入", width=6)
        self.device_import_button.grid(row=4, column=2, sticky="e", padx=(6, 0), pady=3)
        readonly_row(section, 5, "来源", variables.device_source_var)
        readonly_row(section, 6, "Flash", variables.flash_summary_var)
        readonly_row(section, 7, "RAM", variables.ram_summary_var)
        readonly_row(section, 8, "Target cfg", variables.target_cfg_var)
        readonly_row(section, 9, "解析", variables.resolution_var)

        self.firmware_entry, self.firmware_button = path_row(
            section,
            10,
            "固件",
            variables.firmware_var,
        )
        ttk.Label(section, text="BIN 地址").grid(row=11, column=0, sticky="w", pady=3)
        self.bin_address_entry = ttk.Entry(section, textvariable=variables.bin_address_var, width=34)
        self.bin_address_entry.grid(row=11, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(section, text="Flash 读取格式").grid(row=12, column=0, sticky="w", pady=3)
        read_formats = ttk.Frame(section)
        read_formats.grid(row=12, column=1, columnspan=2, sticky="w", pady=3)
        self.flash_read_bin_radio = ttk.Radiobutton(
            read_formats,
            text="BIN",
            variable=variables.flash_read_format_var,
            value="bin",
        )
        self.flash_read_bin_radio.grid(row=0, column=0, sticky="w")
        self.flash_read_hex_radio = ttk.Radiobutton(
            read_formats,
            text="HEX",
            variable=variables.flash_read_format_var,
            value="hex",
        )
        self.flash_read_hex_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        actions = ttk.Frame(section)
        actions.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        self.connect_button = ttk.Button(actions, text="检查连接")
        self.connect_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.flash_read_button = ttk.Button(actions, text="读取完整 Flash")
        self.flash_read_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.flash_button = ttk.Button(actions, text="烧录并校验", style="Primary.TButton")
        self.flash_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))

        self._remember_editable(
            self.project_entry,
            self.project_button,
            self.firmware_entry,
            self.firmware_button,
        )
        self.editable_widgets.append((self.target_combo, "readonly"))
        self.editable_widgets.append((self.project_source_radio, "normal"))
        self.editable_widgets.append((self.device_source_radio, "normal"))
        self.editable_widgets.append((self.device_combo, "normal"))
        self.editable_widgets.append((self.device_import_button, "normal"))
        self.editable_widgets.append((self.bin_address_entry, "normal"))
        self.editable_widgets.append((self.flash_read_bin_radio, "normal"))
        self.editable_widgets.append((self.flash_read_hex_radio, "normal"))
        self.editable_widgets.append((self.probe_combo, "readonly"))
        self.editable_widgets.append((self.probe_refresh_button, "normal"))
        self.editable_widgets.append((self.probe_rename_button, "normal"))

    def _build_rtt_section(self, parent: ttk.Frame, variables: WorkbenchVariables) -> None:
        section = ttk.LabelFrame(parent, text="RTT 采集", padding=6)
        section.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        section.columnconfigure(1, weight=1)
        self.rtt_section = section

        ttk.Label(section, text="扫描").grid(row=0, column=0, sticky="w", pady=3)
        modes = ttk.Frame(section)
        modes.grid(row=0, column=1, columnspan=2, sticky="w")
        self.auto_radio = ttk.Radiobutton(
            modes,
            text="自动 RAM",
            variable=variables.rtt_manual_var,
            value=False,
        )
        self.auto_radio.grid(row=0, column=0, sticky="w")
        self.manual_radio = ttk.Radiobutton(
            modes,
            text="手动地址",
            variable=variables.rtt_manual_var,
            value=True,
        )
        self.manual_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(section, text="控制块地址").grid(row=1, column=0, sticky="w", pady=3)
        self.rtt_address_entry = ttk.Entry(section, textvariable=variables.rtt_address_var)
        self.rtt_address_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(section, text="文字 Up 通道").grid(row=2, column=0, sticky="w", pady=3)
        self.channel_spin = ttk.Spinbox(
            section,
            from_=0,
            to=255,
            textvariable=variables.rtt_channel_var,
            width=8,
        )
        self.channel_spin.grid(row=2, column=1, sticky="w", pady=3)

        self.logs_entry, self.logs_button = path_row(
            section,
            3,
            "日志目录",
            variables.logs_dir_var,
        )

        actions = ttk.Frame(section)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        self.rtt_actions = actions
        self.rtt_start_button = ttk.Button(actions, text="开始采集", style="Primary.TButton")
        self.rtt_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.vofa_start_button = ttk.Button(actions, text="VOFA+ 曲线")
        self.vofa_start_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.rtt_stop_button = ttk.Button(actions, text="停止采集")
        self.rtt_stop_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))

        vofa_hint = ttk.Frame(section)
        vofa_hint.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        vofa_hint.columnconfigure(0, weight=1)
        ttk.Label(
            vofa_hint,
            textvariable=variables.vofa_connection_hint_var,
            style="Accent.TLabel",
            wraplength=270,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self.copy_vofa_connection_button = ttk.Button(
            vofa_hint,
            text="复制连接参数",
        )
        self.copy_vofa_connection_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self._remember_editable(
            self.auto_radio,
            self.manual_radio,
            self.rtt_address_entry,
            self.channel_spin,
            self.logs_entry,
            self.logs_button,
        )

    def _build_advanced_section(self, parent: ttk.Frame, variables: WorkbenchVariables) -> None:
        self.advanced_button = ttk.Button(
            parent,
            text="高级设置...",
        )
        self.advanced_button.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.advanced_dialog = AdvancedSettingsDialog(self, variables)
        self.advanced_button.configure(command=self.advanced_dialog.open)
        for name in (
            "openocd_entry",
            "openocd_button",
            "scripts_entry",
            "scripts_button",
            "override_entry",
            "override_button",
            "port_entry",
            "timeout_entry",
            "vofa_entry",
            "vofa_button",
            "vofa_listen_entry",
            "vofa_up_channel_entry",
            "vofa_up_port_entry",
            "vofa_up_name_entry",
            "vofa_down_channel_entry",
            "vofa_down_port_entry",
            "vofa_down_name_entry",
            "vofa_expected_float_count_entry",
            "vofa_guide_button",
        ):
            setattr(self, name, getattr(self.advanced_dialog, name))

        self._remember_editable(
            self.openocd_entry,
            self.openocd_button,
            self.scripts_entry,
            self.scripts_button,
            self.override_entry,
            self.override_button,
            self.port_entry,
            self.timeout_entry,
            self.vofa_entry,
            self.vofa_button,
            self.vofa_listen_entry,
            self.vofa_up_channel_entry,
            self.vofa_up_port_entry,
            self.vofa_up_name_entry,
            self.vofa_down_channel_entry,
            self.vofa_down_port_entry,
            self.vofa_down_name_entry,
            self.vofa_expected_float_count_entry,
            self.vofa_guide_button,
        )
        self.editable_widgets.append((self.advanced_button, "normal"))

    def enable_rtt_collector_layout(self) -> None:
        self.project_section.configure(text="采集设备")
        for row in (0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13):
            for widget in self.project_section.grid_slaves(row=row):
                widget.grid_remove()

        for widget in self.project_section.grid_slaves(row=4):
            widget.grid_configure(row=0)
        self.device_import_button.grid_remove()
        self.device_combo.grid_configure(columnspan=2)
        for widget in self.project_section.grid_slaves(row=2):
            widget.grid_configure(row=1)
        self.collector_device_status.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.probe_rename_button.grid_remove()
        self.probe_driver_button.grid(row=0, column=2, padx=(5, 0))

        for row in (0, 1, 2, 5):
            for widget in self.rtt_section.grid_slaves(row=row):
                widget.grid_remove()
        self.vofa_start_button.grid_remove()
        self.rtt_start_button.grid_configure(row=0, column=0, padx=(0, 3))
        self.rtt_stop_button.grid_configure(row=0, column=1, padx=(3, 0))
        self.rtt_actions.columnconfigure(2, weight=0)
        self.advanced_button.grid_remove()

    def ensure_visible(self, widget: tk.Widget) -> None:
        self.update_idletasks()
        region = self.canvas.bbox("all")
        if region is None or region[3] <= region[1]:
            return
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        visible_height = self.canvas.winfo_height()
        total_height = region[3] - region[1]
        if top < visible_top:
            self.canvas.yview_moveto(max(0.0, top / total_height))
        elif bottom > visible_top + visible_height:
            self.canvas.yview_moveto(min(1.0, (bottom - visible_height) / total_height))

    def _sync_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_content_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._content_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _remember_editable(self, *widgets: tk.Widget) -> None:
        self.editable_widgets.extend((widget, "normal") for widget in widgets)


class OutputNotebook(ttk.Frame):
    """Reusable live RTT and OpenOCD output surface."""

    def __init__(
        self,
        parent: ttk.Frame,
        *,
        elapsed_var: tk.StringVar,
        counts_var: tk.StringVar,
        rtt_level_var: tk.StringVar,
        rtt_visible_counts_var: tk.StringVar,
        on_level_changed: Callable[[], None],
        on_clear_rtt: Callable[[], None],
        open_logs_dir: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="Console.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self, style="Console.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        rtt_tab = ttk.Frame(self.notebook, padding=8, style="Console.TFrame")
        openocd_tab = ttk.Frame(self.notebook, padding=8, style="Console.TFrame")
        self.notebook.add(rtt_tab, text="RTT 日志")
        self.notebook.add(openocd_tab, text="OpenOCD 输出")
        self._openocd_tab = openocd_tab

        rtt_tab.columnconfigure(0, weight=1)
        rtt_tab.rowconfigure(2, weight=1)
        rtt_toolbar = ttk.Frame(rtt_tab, style="Console.TFrame")
        rtt_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(rtt_toolbar, textvariable=elapsed_var, width=10, style="Console.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(rtt_toolbar, textvariable=counts_var, width=22, style="Console.TLabel").grid(row=0, column=1, sticky="w")
        rtt_toolbar.columnconfigure(2, weight=1)
        ttk.Button(rtt_toolbar, text="复制全部", command=lambda: self.rtt_view.copy_all()).grid(
            row=0,
            column=3,
            padx=(6, 0),
        )
        ttk.Button(rtt_toolbar, text="清空显示", command=on_clear_rtt).grid(
            row=0,
            column=4,
            padx=(6, 0),
        )
        ttk.Button(rtt_toolbar, text="打开日志目录", command=open_logs_dir).grid(
            row=0,
            column=5,
            padx=(6, 0),
        )

        filter_bar = ttk.Frame(rtt_tab, style="Console.TFrame")
        filter_bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(filter_bar, text="显示等级", style="Console.TLabel").grid(row=0, column=0, sticky="w")
        self.rtt_level_combo = ttk.Combobox(
            filter_bar,
            textvariable=rtt_level_var,
            values=RTT_LEVEL_NAMES,
            state="readonly",
            width=10,
        )
        self.rtt_level_combo.grid(row=0, column=1, sticky="w", padx=(6, 12))
        self.rtt_level_combo.bind("<<ComboboxSelected>>", lambda _event: on_level_changed())
        ttk.Label(
            filter_bar,
            textvariable=rtt_visible_counts_var,
            style="Console.TLabel",
        ).grid(row=0, column=2, sticky="w")
        filter_bar.columnconfigure(3, weight=1)
        self.rtt_view = LogTextView(rtt_tab, row=2, rtt=True)
        self._rtt_text = self.rtt_view.text

        openocd_tab.columnconfigure(0, weight=1)
        openocd_tab.rowconfigure(1, weight=1)
        openocd_toolbar = ttk.Frame(openocd_tab, style="Console.TFrame")
        openocd_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        openocd_toolbar.columnconfigure(0, weight=1)
        ttk.Button(openocd_toolbar, text="复制全部", command=lambda: self.openocd_view.copy_all()).grid(
            row=0,
            column=1,
        )
        ttk.Button(openocd_toolbar, text="清空输出", command=self.clear_openocd).grid(
            row=0,
            column=2,
            padx=(6, 0),
        )
        ttk.Button(openocd_toolbar, text="打开日志目录", command=open_logs_dir).grid(
            row=0,
            column=3,
            padx=(6, 0),
        )
        self.openocd_view = LogTextView(openocd_tab, row=1)
        self._openocd_text = self.openocd_view.text

    def select_openocd(self) -> None:
        self.notebook.select(self._openocd_tab)

    def append_rtt(self, text: str) -> None:
        _append_text(self._rtt_text, text)

    def append_rtt_record(self, record: RttLogRecord) -> None:
        _append_text(self._rtt_text, record.text, tag=record.level.name)

    def render_rtt_records(self, records: tuple[RttLogRecord, ...]) -> None:
        self._rtt_text.configure(state="normal")
        self._rtt_text.delete("1.0", "end")
        for record in records:
            self._rtt_text.insert("end", record.text, record.level.name)
        self._rtt_text.see("end")
        self._rtt_text.configure(state="disabled")

    def remove_first_rtt_record(self, record: RttLogRecord) -> None:
        self._rtt_text.configure(state="normal")
        self._rtt_text.delete("1.0", f"1.0 + {len(record.text)} chars")
        self._rtt_text.configure(state="disabled")

    def append_openocd(self, text: str) -> None:
        _append_text(self._openocd_text, text)

    def clear_rtt(self) -> None:
        _clear_text(self._rtt_text)

    def clear_openocd(self) -> None:
        _clear_text(self._openocd_text)


class LogTextView:
    def __init__(self, parent: ttk.Frame, *, row: int, rtt: bool = False) -> None:
        self.frame = ttk.Frame(parent, style="Console.TFrame")
        self.frame.grid(row=row, column=0, sticky="nsew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)
        self.text = tk.Text(
            self.frame,
            wrap="none",
            width=1,
            height=1,
            font=("Consolas", 10),
            undo=False,
            state="disabled",
            borderwidth=0,
            relief="flat",
        )
        configure_log_text(self.text, rtt=rtt)
        yscroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        xscroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        self.menu = tk.Menu(self.text, tearoff=False)
        self.menu.add_command(label="复制", command=self.copy_selected)
        self.menu.add_command(label="全选", command=self.select_all)
        self.menu.add_command(label="复制全部", command=self.copy_all)
        self.text.bind("<Button-3>", self._show_menu)
        self.text.bind("<Control-c>", lambda _event: self.copy_selected())
        self.text.bind("<Control-a>", lambda _event: self.select_all())

    def copy_selected(self) -> str:
        try:
            value = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""
        self._copy(value)
        return value

    def copy_all(self) -> str:
        value = self.text.get("1.0", "end-1c")
        self._copy(value)
        return value

    def select_all(self) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _copy(self, value: str) -> None:
        self.text.clipboard_clear()
        self.text.clipboard_append(value)

    def _show_menu(self, event: tk.Event) -> str:
        self.menu.tk_popup(event.x_root, event.y_root)
        return "break"


def _append_text(widget: tk.Text, text: str, *, tag: str | None = None) -> None:
    if not text:
        return
    widget.configure(state="normal")
    widget.insert("end", text, tag)
    widget.see("end")
    widget.configure(state="disabled")


def _clear_text(widget: tk.Text) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.configure(state="disabled")


__all__ = [
    "ConfigurationPane",
    "LogTextView",
    "OutputNotebook",
    "WorkbenchVariables",
    "path_row",
    "readonly_row",
]
