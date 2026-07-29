from __future__ import annotations

import subprocess
import sys


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def background_process_kwargs(platform: str | None = None) -> dict[str, int]:
    current = platform or sys.platform
    if current == "win32":
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


__all__ = ["background_process_kwargs"]
