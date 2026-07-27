from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Protocol

from keiltool.core.rtt_log import RttLogRecord
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
    rtt_manual_var: tk.BooleanVar
    rtt_address_var: tk.StringVar
    rtt_channel_var: tk.StringVar
    logs_dir_var: tk.StringVar
    openocd_var: tk.StringVar
    scripts_var: tk.StringVar
    target_override_var: tk.StringVar
    rtt_port_var: tk.StringVar
    rtt_timeout_var: tk.StringVar


class ConfigurationPane(ttk.Frame):
    """Stable left-side project, flash, RTT, and advanced controls."""

    def __init__(self, parent: ttk.Frame, variables: WorkbenchVariables) -> None:
        super().__init__(parent)
        self._advanced_visible = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.editable_widgets: list[tuple[tk.Widget, str]] = []
        self._build_project_section(variables)
        self._build_rtt_section(variables)
        self._build_advanced_section(variables)

    def _build_project_section(self, variables: WorkbenchVariables) -> None:
        section = ttk.LabelFrame(self, text="工程与烧录", padding=6)
        section.grid(row=0, column=0, sticky="ew")
        section.columnconfigure(1, weight=1)

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

        ttk.Label(section, text="配置来源").grid(row=2, column=0, sticky="w", pady=3)
        source_modes = ttk.Frame(section)
        source_modes.grid(row=2, column=1, columnspan=2, sticky="w", pady=3)
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
        self.device_label.grid(row=3, column=0, sticky="w", pady=3)
        self.device_combo = ttk.Combobox(
            section,
            textvariable=variables.device_choice_var,
            state="normal",
            width=34,
        )
        self.device_combo.grid(row=3, column=1, sticky="ew", pady=3)
        self.device_import_button = ttk.Button(section, text="导入", width=6)
        self.device_import_button.grid(row=3, column=2, sticky="e", padx=(6, 0), pady=3)
        readonly_row(section, 4, "来源", variables.device_source_var)
        readonly_row(section, 5, "Flash", variables.flash_summary_var)
        readonly_row(section, 6, "RAM", variables.ram_summary_var)
        readonly_row(section, 7, "Target cfg", variables.target_cfg_var)
        readonly_row(section, 8, "解析", variables.resolution_var)

        self.firmware_entry, self.firmware_button = path_row(
            section,
            9,
            "固件",
            variables.firmware_var,
        )
        ttk.Label(section, text="BIN 地址").grid(row=10, column=0, sticky="w", pady=3)
        self.bin_address_entry = ttk.Entry(section, textvariable=variables.bin_address_var, width=34)
        self.bin_address_entry.grid(row=10, column=1, columnspan=2, sticky="ew", pady=3)

        actions = ttk.Frame(section)
        actions.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(7, 0))
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

    def _build_rtt_section(self, variables: WorkbenchVariables) -> None:
        section = ttk.LabelFrame(self, text="RTT 采集", padding=6)
        section.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        section.columnconfigure(1, weight=1)

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

        ttk.Label(section, text="通道").grid(row=2, column=0, sticky="w", pady=3)
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
        actions.columnconfigure((0, 1), weight=1)
        self.rtt_start_button = ttk.Button(actions, text="开始采集", style="Primary.TButton")
        self.rtt_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.rtt_stop_button = ttk.Button(actions, text="停止采集")
        self.rtt_stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._remember_editable(
            self.auto_radio,
            self.manual_radio,
            self.rtt_address_entry,
            self.channel_spin,
            self.logs_entry,
            self.logs_button,
        )

    def _build_advanced_section(self, variables: WorkbenchVariables) -> None:
        self.advanced_button = ttk.Button(
            self,
            text="▶ 高级设置",
            command=self._toggle_advanced,
        )
        self.advanced_button.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        self.advanced_frame = ttk.Frame(self, padding=(8, 5, 8, 0))
        self.advanced_frame.columnconfigure(1, weight=1)
        self.openocd_entry, self.openocd_button = path_row(
            self.advanced_frame,
            0,
            "OpenOCD",
            variables.openocd_var,
        )
        self.scripts_entry, self.scripts_button = path_row(
            self.advanced_frame,
            1,
            "scripts",
            variables.scripts_var,
        )
        self.override_entry, self.override_button = path_row(
            self.advanced_frame,
            2,
            "target override",
            variables.target_override_var,
        )
        ttk.Label(self.advanced_frame, text="RTT 端口").grid(row=3, column=0, sticky="w", pady=3)
        self.port_entry = ttk.Entry(self.advanced_frame, textvariable=variables.rtt_port_var, width=12)
        self.port_entry.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(self.advanced_frame, text="扫描超时(ms)").grid(row=4, column=0, sticky="w", pady=3)
        self.timeout_entry = ttk.Entry(self.advanced_frame, textvariable=variables.rtt_timeout_var, width=12)
        self.timeout_entry.grid(row=4, column=1, sticky="w", pady=3)

        self._remember_editable(
            self.openocd_entry,
            self.openocd_button,
            self.scripts_entry,
            self.scripts_button,
            self.override_entry,
            self.override_button,
            self.port_entry,
            self.timeout_entry,
        )
        self.editable_widgets.append((self.advanced_button, "normal"))

    def _remember_editable(self, *widgets: tk.Widget) -> None:
        self.editable_widgets.extend((widget, "normal") for widget in widgets)

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_frame.grid(row=3, column=0, sticky="ew")
            self.advanced_button.configure(text="▼ 高级设置")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="▶ 高级设置")


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

        notebook = ttk.Notebook(self, style="Console.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")
        rtt_tab = ttk.Frame(notebook, padding=8, style="Console.TFrame")
        openocd_tab = ttk.Frame(notebook, padding=8, style="Console.TFrame")
        notebook.add(rtt_tab, text="RTT 日志")
        notebook.add(openocd_tab, text="OpenOCD 输出")

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
