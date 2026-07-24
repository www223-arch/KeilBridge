from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from keiltool.core.rtt_log import RttLevel


PALETTE = {
    "background": "#F3F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#E9EEF2",
    "border": "#D7DEE5",
    "text": "#202A33",
    "muted": "#657481",
    "primary": "#087F8C",
    "primary_active": "#066B75",
    "selection": "#CDE8EB",
    "success": "#15803D",
    "warning": "#B36B00",
    "error": "#B42318",
    "assert": "#8B2C83",
    "info": "#087F8C",
    "debug": "#15803D",
    "verbose": "#315A8C",
}

RTT_LEVEL_COLORS = {
    RttLevel.ASSERT: PALETTE["assert"],
    RttLevel.ERROR: PALETTE["error"],
    RttLevel.WARN: PALETTE["warning"],
    RttLevel.INFO: PALETTE["info"],
    RttLevel.DEBUG: PALETTE["debug"],
    RttLevel.VERBOSE: PALETTE["verbose"],
}


def configure_theme(root: tk.Tk) -> ttk.Style:
    root.configure(background=PALETTE["background"])
    root.option_add("*Font", ("Microsoft YaHei UI", 9))
    root.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", 9))

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        ".",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=("Microsoft YaHei UI", 9),
    )
    style.configure("TFrame", background=PALETTE["surface"])
    style.configure("Surface.TFrame", background=PALETTE["surface"])
    style.configure("Background.TFrame", background=PALETTE["background"])
    style.configure("TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure("Muted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"])
    style.configure("TRadiobutton", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.map("TRadiobutton", background=[("active", PALETTE["surface"])])
    style.configure(
        "TLabelframe",
        background=PALETTE["surface"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=("Microsoft YaHei UI", 9, "bold"),
    )
    style.configure(
        "TButton",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
        padding=(10, 5),
    )
    style.map(
        "TButton",
        background=[("active", PALETTE["surface_alt"]), ("disabled", PALETTE["background"])],
        foreground=[("disabled", PALETTE["muted"])],
    )
    style.configure(
        "Primary.TButton",
        background=PALETTE["primary"],
        foreground="#FFFFFF",
        bordercolor=PALETTE["primary"],
        lightcolor=PALETTE["primary"],
        darkcolor=PALETTE["primary"],
        font=("Microsoft YaHei UI", 9, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[
            ("pressed", PALETTE["primary_active"]),
            ("active", PALETTE["primary_active"]),
            ("disabled", PALETTE["border"]),
        ],
        foreground=[("disabled", PALETTE["muted"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
        padding=4,
    )
    style.configure(
        "TCombobox",
        fieldbackground=PALETTE["surface"],
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        arrowcolor=PALETTE["muted"],
        bordercolor=PALETTE["border"],
        padding=3,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PALETTE["surface"])],
        selectbackground=[("readonly", PALETTE["surface"])],
        selectforeground=[("readonly", PALETTE["text"])],
    )
    style.configure("TNotebook", background=PALETTE["background"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=PALETTE["surface_alt"],
        foreground=PALETTE["muted"],
        padding=(14, 7),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PALETTE["surface"])],
        foreground=[("selected", PALETTE["primary"])],
    )
    style.configure("Status.TFrame", background=PALETTE["surface"])
    style.configure("Status.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure(
        "Horizontal.TSeparator",
        background=PALETTE["border"],
    )
    return style


def configure_log_text(widget: tk.Text, *, rtt: bool = False) -> None:
    widget.configure(
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        insertbackground=PALETTE["text"],
        selectbackground=PALETTE["selection"],
        selectforeground=PALETTE["text"],
        highlightbackground=PALETTE["border"],
        highlightcolor=PALETTE["primary"],
        highlightthickness=1,
        borderwidth=0,
        padx=10,
        pady=8,
    )
    if rtt:
        for level, color in RTT_LEVEL_COLORS.items():
            widget.tag_configure(level.name, foreground=color)


__all__ = ["PALETTE", "RTT_LEVEL_COLORS", "configure_log_text", "configure_theme"]
