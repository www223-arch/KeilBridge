from __future__ import annotations

from multiprocessing import freeze_support
from pathlib import Path
import sys

from keiltool.core.device_catalog import load_embedded_catalog
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts
from keiltool.gui.app import launch_gui


def portable_self_test() -> int:
    openocd = find_openocd()
    scripts = find_openocd_scripts(openocd)
    if not Path(openocd).is_file() or not Path(scripts).is_dir():
        return 2
    if not load_embedded_catalog().devices:
        return 3
    return 0


def main() -> int:
    freeze_support()
    if "--portable-self-test" in sys.argv[1:]:
        return portable_self_test()
    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
