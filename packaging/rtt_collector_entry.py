from __future__ import annotations

from multiprocessing import freeze_support
from pathlib import Path
import tempfile
import tkinter as tk
import sys

from keiltool.core.device_catalog import load_embedded_catalog
from keiltool.core.stlink_probe import (
    StLinkDiscovery,
    discover_stlink_probes_nonintrusive,
)
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts
from keiltool.gui.app import KeilToolGui, launch_rtt_collector
from keiltool.gui.settings import SettingsStore


def portable_self_test() -> int:
    openocd = find_openocd()
    scripts = find_openocd_scripts(openocd)
    if not Path(openocd).is_file() or not Path(scripts).is_dir():
        return 2
    if not load_embedded_catalog().devices:
        return 3

    with tempfile.TemporaryDirectory(prefix="keiltool-rtt-collector-") as temporary:
        root = tk.Tk()
        root.withdraw()
        try:
            KeilToolGui(
                root,
                settings_store=SettingsStore(Path(temporary) / "settings.json"),
                probe_discovery=lambda _openocd: StLinkDiscovery(()),
                mode="rtt_collector",
            )
            root.update()
        finally:
            root.destroy()
    return 0


def main() -> int:
    freeze_support()
    if "--portable-self-test" in sys.argv[1:]:
        return portable_self_test()
    launch_rtt_collector(probe_discovery=discover_stlink_probes_nonintrusive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
