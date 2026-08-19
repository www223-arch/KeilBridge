from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from keiltool.core.rtt_log import RttLevel


PALETTE = {
    "background": "#DCE5E9",
    "surface": "#F9FBFC",
    "surface_alt": "#DFEAEC",
    "border": "#B8C8CE",
    "text": "#17313B",
    "muted": "#5B6F77",
    "primary": "#087F8C",
    "primary_active": "#066B75",
    "selection": "#245766",
    "console": "#0B1C23",
    "console_chrome": "#102730",
    "console_border": "#17313B",
    "console_text": "#DFECEF",
    "success": "#5FD28A",
    "warning": "#F4C15D",
    "error": "#FF7770",
    "assert": "#F29BEA",
    "info": "#67D5E0",
    "debug": "#72D99B",
    "verbose": "#9ABEF4",
    "success_surface": "#E5F6EC",
    "error_surface": "#FCE9E8",
    "warning_surface": "#FFF4D9",
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
    style.configure("Console.TFrame", background=PALETTE["console_chrome"])
    style.configure("Console.TLabel", background=PALETTE["console_chrome"], foreground=PALETTE["console_text"])
    style.configure("Surface.TFrame", background=PALETTE["surface"])
    style.configure("Background.TFrame", background=PALETTE["background"])
    style.configure("TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure("Muted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"])
    style.configure(
        "Accent.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["primary"],
        font=("Microsoft YaHei UI", 9, "bold"),
    )
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
    style.configure("Console.TNotebook", background=PALETTE["console_chrome"], borderwidth=0)
    style.configure(
        "Console.TNotebook.Tab",
        background=PALETTE["console_border"],
        foreground="#AFC4CA",
        padding=(14, 7),
    )
    style.map(
        "Console.TNotebook.Tab",
        background=[("selected", PALETTE["console_chrome"])],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure("Status.TFrame", background=PALETTE["surface"])
    style.configure("Status.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure("Operation.TFrame", background=PALETTE["surface_alt"])
    style.configure("Operation.TLabel", background=PALETTE["surface_alt"], foreground=PALETTE["text"])
    style.configure(
        "OperationTitle.TLabel",
        background=PALETTE["surface_alt"],
        foreground=PALETTE["text"],
        font=("Microsoft YaHei UI", 10, "bold"),
    )
    for name, foreground, background in (
        ("Idle", PALETTE["muted"], PALETTE["surface"]),
        ("Running", PALETTE["primary"], PALETTE["surface_alt"]),
        ("Succeeded", "#17683A", PALETTE["success_surface"]),
        ("Failed", "#A52D28", PALETTE["error_surface"]),
        ("Stopping", "#7A5710", PALETTE["warning_surface"]),
        ("Incomplete", "#A52D28", PALETTE["warning_surface"]),
    ):
        style.configure(
            f"Operation{name}.TLabel",
            background=background,
            foreground=foreground,
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(7, 2),
        )
    for name, color in (
        ("Running", PALETTE["primary"]),
        ("Succeeded", "#2C9B59"),
        ("Failed", "#D94B45"),
        ("Stopping", "#C38A1F"),
        ("Incomplete", "#D94B45"),
        ("Idle", PALETTE["border"]),
    ):
        style.configure(
            f"Operation{name}.Horizontal.TProgressbar",
            background=color,
            troughcolor=PALETTE["surface"],
            bordercolor=PALETTE["border"],
            lightcolor=color,
            darkcolor=color,
        )
    style.configure(
        "Horizontal.TSeparator",
        background=PALETTE["border"],
    )
    return style


def configure_log_text(widget: tk.Text, *, rtt: bool = False) -> None:
    widget.configure(
        background=PALETTE["console"],
        foreground=PALETTE["console_text"],
        insertbackground=PALETTE["console_text"],
        selectbackground=PALETTE["selection"],
        selectforeground="#FFFFFF",
        highlightbackground=PALETTE["console_border"],
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
