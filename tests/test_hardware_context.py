from pathlib import Path

import pytest


def test_hardware_selection_requires_exactly_one_source():
    from keiltool.core.hardware_context import HardwareSelection

    with pytest.raises(ValueError, match="exactly one"):
        HardwareSelection()
    with pytest.raises(ValueError, match="exactly one"):
        HardwareSelection(project=Path("app.uvprojx"), device="GD32F303VE")


def test_hardware_selection_accepts_project_or_device():
    from keiltool.core.hardware_context import HardwareSelection

    project = HardwareSelection(project=Path("app.uvprojx"), target="Debug")
    device = HardwareSelection(device="GD32F303VE", vendor="GigaDevice")

    assert project.source == "project"
    assert device.source == "device"
