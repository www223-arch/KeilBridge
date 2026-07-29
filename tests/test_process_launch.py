from __future__ import annotations

import subprocess

from keiltool.core.process_launch import background_process_kwargs


def test_windows_background_process_uses_no_window_flag():
    assert background_process_kwargs("win32") == {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    }


def test_non_windows_background_process_adds_no_platform_flags():
    assert background_process_kwargs("linux") == {}
