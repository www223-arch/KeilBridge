from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from keiltool.core.scope_command import (
    ScopeCommandType,
    ScopeKeepaliveController,
    build_scope_command,
)


@dataclass(frozen=True, slots=True)
class _Field:
    key: str
    label: str
    default: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CommandForm:
    command: ScopeCommandType
    label: str
    fields: tuple[_Field, ...]
    requires_confirmation: bool = False


_AXIS = _Field("axis", "轴", "1", ("1 - Yaw/Rotate", "2 - Pitch"))
_AXIS_MASK = _Field(
    "axis_mask",
    "轴掩码",
    "3",
    ("1 - Yaw/Rotate", "2 - Pitch", "3 - Yaw + Pitch"),
)
_FORMS = (
    _CommandForm(
        ScopeCommandType.SET_MODE,
        "SET_MODE - 设置控制模式",
        (
            _AXIS,
            _Field(
                "mode",
                "模式",
                "1",
                ("0 - Open speed", "1 - Closed speed", "2 - Quaternion attitude"),
            ),
        ),
    ),
    _CommandForm(
        ScopeCommandType.SET_SPEED,
        "SET_SPEED - 设置目标速度",
        (_AXIS, _Field("target_dps", "目标速度 (deg/s，-6.5..+6.5)", "0")),
    ),
    _CommandForm(
        ScopeCommandType.SET_PID,
        "SET_PID - 设置速度环 PID",
        (
            _AXIS,
            _Field("kp", "Kp", "0"),
            _Field("ki", "Ki", "0"),
            _Field("kd", "Kd", "0"),
            _Field("output_limit_dps", "输出限幅 (deg/s)", "0"),
        ),
    ),
    _CommandForm(
        ScopeCommandType.SET_ATTITUDE_QUAT,
        "SET_ATTITUDE_QUAT - 设置目标四元数",
        (
            _Field("w", "W", "1"),
            _Field("x", "X", "0"),
            _Field("y", "Y", "0"),
            _Field("z", "Z", "0"),
        ),
    ),
    _CommandForm(
        ScopeCommandType.SET_ATTITUDE_GAIN,
        "SET_ATTITUDE_GAIN - 设置姿态外环增益",
        (
            _Field("kp", "Kp", "0"),
            _Field("kd", "Kd", "0"),
            _Field("max_rate_dps", "最大速率 (deg/s，0 < 值 <= 6.5)", "1"),
        ),
    ),
    _CommandForm(
        ScopeCommandType.START,
        "START - 显式启动",
        (_AXIS_MASK, _Field("ttl_ms", "安全 TTL (ms，1..30000)", "1000")),
        requires_confirmation=True,
    ),
    _CommandForm(
        ScopeCommandType.KEEPALIVE,
        "KEEPALIVE - 刷新已启动轴 TTL",
        (_Field("ttl_ms", "安全 TTL (ms，1..30000)", "1000"),),
    ),
    _CommandForm(
        ScopeCommandType.STOP,
        "STOP - 停止指定轴",
        (_AXIS_MASK,),
    ),
    _CommandForm(ScopeCommandType.GET_STATE, "GET_STATE - 查询状态", ()),
)
_FORM_BY_LABEL = {form.label: form for form in _FORMS}


class ScopeCommandDialog(tk.Toplevel):
    """Build and send BilboPro ScopeCmd v1 frames without manual CRC work."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_send: Callable[[bytes, str], None],
        is_connected: Callable[[], bool],
        profile_text: str,
        connection_text: str,
        initial_seq: int = 0,
    ) -> None:
        super().__init__(parent)
        self._on_send = on_send
        self._is_connected = is_connected
        self._connected_text = connection_text
        self._field_vars: dict[str, tk.StringVar] = {}
        self._ui_after_id: str | None = None
        self.title("BilboPro 控制命令")
        self.geometry("620x620")
        self.minsize(560, 560)
        self.transient(parent.winfo_toplevel())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.command_var = tk.StringVar(value=_FORMS[-1].label)
        self.seq_var = tk.StringVar(value=str(initial_seq & 0xFF))
        self.preview_var = tk.StringVar()
        self.validation_var = tk.StringVar()
        self.profile_var = tk.StringVar(value=profile_text)
        self.connection_var = tk.StringVar(value=connection_text)
        self.auto_keepalive_var = tk.BooleanVar(value=False)
        self.auto_ttl_var = tk.StringVar(value="1000")
        self.keepalive_status_var = tk.StringVar(value="自动 KEEPALIVE 已关闭")
        self._keepalive = ScopeKeepaliveController(
            on_send=self._on_send,
            is_connected=self._is_connected,
        )

        header = ttk.Frame(self, padding=(14, 12, 14, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(
            header,
            textvariable=self.profile_var,
            style="Accent.TLabel",
            wraplength=500,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            header,
            textvariable=self.connection_var,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 10))
        ttk.Label(header, text="命令").grid(row=2, column=0, sticky="w")
        self.command_combo = ttk.Combobox(
            header,
            textvariable=self.command_var,
            values=tuple(form.label for form in _FORMS),
            state="readonly",
        )
        self.command_combo.grid(row=2, column=1, sticky="ew", padx=(10, 0))
        ttk.Label(header, text="序号").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.seq_spin = ttk.Spinbox(
            header,
            from_=0,
            to=255,
            textvariable=self.seq_var,
            width=8,
        )
        self.seq_spin.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        self.fields = ttk.Frame(self, padding=(14, 8))
        self.fields.grid(row=1, column=0, sticky="nsew")
        self.fields.columnconfigure(1, weight=1)

        keepalive = ttk.Frame(self, padding=(14, 4, 14, 8))
        keepalive.grid(row=2, column=0, sticky="ew")
        keepalive.columnconfigure(3, weight=1)
        self.auto_keepalive_check = ttk.Checkbutton(
            keepalive,
            text="自动 KEEPALIVE（默认关闭）",
            variable=self.auto_keepalive_var,
            command=self._toggle_auto_keepalive,
        )
        self.auto_keepalive_check.grid(row=0, column=0, sticky="w")
        ttk.Label(keepalive, text="TTL (ms)").grid(row=0, column=1, padx=(14, 5))
        self.auto_ttl_spin = ttk.Spinbox(
            keepalive,
            from_=1,
            to=30000,
            textvariable=self.auto_ttl_var,
            width=8,
        )
        self.auto_ttl_spin.grid(row=0, column=2, sticky="w")
        ttk.Label(
            keepalive,
            textvariable=self.keepalive_status_var,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))

        footer = ttk.Frame(self, padding=(14, 8, 14, 14))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            text="完整帧 HEX（含 CRC16-CCITT-FALSE，little-endian）",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.preview_entry = ttk.Entry(
            footer,
            textvariable=self.preview_var,
            state="readonly",
        )
        self.preview_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(footer, text="复制 HEX", command=self._copy_hex).grid(
            row=1,
            column=1,
            padx=(8, 0),
            pady=(5, 0),
        )
        ttk.Label(
            footer,
            textvariable=self.validation_var,
            style="Muted.TLabel",
            wraplength=500,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(7, 0))

        actions = ttk.Frame(footer)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="关闭", command=self.destroy).grid(row=0, column=0)
        self.send_button = ttk.Button(
            actions,
            text="发送到 RTT Down1",
            style="Primary.TButton",
            command=self._send,
        )
        self.send_button.grid(row=0, column=1, padx=(8, 0))

        self.command_combo.bind("<<ComboboxSelected>>", self._render_form)
        self.seq_var.trace_add("write", self._refresh_preview)
        self._render_form()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._schedule_ui_tick()

    def _selected_form(self) -> _CommandForm:
        return _FORM_BY_LABEL[self.command_var.get()]

    def _render_form(self, _event: tk.Event | None = None) -> None:
        for child in self.fields.winfo_children():
            child.destroy()
        self._field_vars.clear()
        form = self._selected_form()
        if not form.fields:
            ttk.Label(
                self.fields,
                text="该命令没有 payload。发送后请通过 LoopScope I38/I39 确认 ACK。",
                style="Muted.TLabel",
                wraplength=500,
            ).grid(row=0, column=0, columnspan=2, sticky="w")
        for row, field in enumerate(form.fields):
            ttk.Label(self.fields, text=field.label).grid(
                row=row,
                column=0,
                sticky="w",
                pady=4,
            )
            variable = tk.StringVar(value=field.default)
            self._field_vars[field.key] = variable
            variable.trace_add("write", self._refresh_preview)
            if field.choices:
                widget = ttk.Combobox(
                    self.fields,
                    textvariable=variable,
                    values=field.choices,
                    state="readonly",
                )
                variable.set(next(item for item in field.choices if item.startswith(field.default)))
            else:
                widget = ttk.Entry(self.fields, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=4)
        self._refresh_preview()

    def _values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for key, variable in self._field_vars.items():
            text = variable.get().strip()
            values[key] = text.split(" ", 1)[0] if key in {"axis", "axis_mask", "mode"} else text
        return values

    def _build_frame(self) -> tuple[bytes, str]:
        form = self._selected_form()
        frame = build_scope_command(
            form.command,
            seq=int(self.seq_var.get().strip()),
            **self._values(),
        )
        return frame, f"{form.command.name} seq={int(self.seq_var.get().strip())}"

    def _refresh_preview(self, *_args: object) -> None:
        try:
            frame, _description = self._build_frame()
        except (TypeError, ValueError) as exc:
            self.preview_var.set("")
            self.validation_var.set(f"参数待完善：{exc}")
            self.send_button.configure(state="disabled")
            return
        self.preview_var.set(frame.hex(" ").upper())
        self.validation_var.set(
            f"帧长 {len(frame)} 字节；发送成功不等于 MCU 已执行，请核对 I38/I39。"
        )
        self.send_button.configure(state="normal" if self._is_connected() else "disabled")

    def _toggle_auto_keepalive(self) -> None:
        if not self.auto_keepalive_var.get():
            self._keepalive.stop()
            self.auto_ttl_spin.configure(state="normal")
            self.keepalive_status_var.set("自动 KEEPALIVE 已关闭")
            return
        try:
            status = self._keepalive.start(
                ttl_ms=int(self.auto_ttl_var.get().strip()),
                seq=int(self.seq_var.get().strip()),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.auto_keepalive_var.set(False)
            self.keepalive_status_var.set(f"自动 KEEPALIVE 未启动：{exc}")
            messagebox.showerror("自动 KEEPALIVE 未启动", str(exc), parent=self)
            return
        self.seq_var.set(str(status.next_seq))
        self.auto_ttl_spin.configure(state="disabled")
        self._show_keepalive_status(status.next_in_ms)

    def _schedule_ui_tick(self) -> None:
        self._ui_after_id = self.after(100, self._ui_tick)

    def _ui_tick(self) -> None:
        self._ui_after_id = None
        connected = self._is_connected()
        self.connection_var.set(
            self._connected_text if connected else "RTT 已断开 · 命令发送与自动 KEEPALIVE 已停止"
        )
        if self.preview_var.get():
            self.send_button.configure(state="normal" if connected else "disabled")
        if self.auto_keepalive_var.get():
            try:
                status = self._keepalive.poll()
            except (OSError, RuntimeError, ValueError) as exc:
                self.auto_keepalive_var.set(False)
                self.auto_ttl_spin.configure(state="normal")
                self.keepalive_status_var.set(f"自动 KEEPALIVE 已停止：{exc}")
            else:
                self.seq_var.set(str(status.next_seq))
                if status.enabled:
                    self._show_keepalive_status(status.next_in_ms)
                else:
                    self.auto_keepalive_var.set(False)
                    self.auto_ttl_spin.configure(state="normal")
                    reason = "RTT 已断开" if status.reason == "RTT disconnected" else status.reason
                    self.keepalive_status_var.set(f"自动 KEEPALIVE 已停止：{reason}")
        self._schedule_ui_tick()

    def _show_keepalive_status(self, next_in_ms: int | None) -> None:
        remaining = 0 if next_in_ms is None else next_in_ms
        self.keepalive_status_var.set(
            f"自动续租运行中 · 下次续租 {remaining / 1000.0:.1f} s · "
            f"TTL {self.auto_ttl_var.get().strip()} ms"
        )

    def _copy_hex(self) -> None:
        text = self.preview_var.get()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _send(self) -> None:
        try:
            frame, description = self._build_frame()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("控制命令参数无效", str(exc), parent=self)
            return
        form = self._selected_form()
        if form.requires_confirmation and not messagebox.askokcancel(
            "确认显式启动",
            "START 会启动所选轴，并由 TTL/KEEPALIVE 约束运行时间。\n\n"
            f"即将发送：{description}\n"
            f"{self.preview_var.get()}\n\n"
            "确认目标安全后再继续。",
            parent=self,
        ):
            return
        try:
            self._on_send(frame, description)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("控制命令发送失败", str(exc), parent=self)
            return
        next_seq = (int(self.seq_var.get()) + 1) & 0xFF
        self.seq_var.set(str(next_seq))
        if self.auto_keepalive_var.get():
            self._keepalive.set_next_seq(next_seq)

    def destroy(self) -> None:
        self._keepalive.stop("dialog closed")
        after_id = self._ui_after_id
        self._ui_after_id = None
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        super().destroy()


__all__ = ["ScopeCommandDialog"]
