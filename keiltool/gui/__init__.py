"""GUI support types for the ST-Link/OpenOCD workflow."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import KeilToolGui

__all__ = ["KeilToolGui", "launch_gui"]


def __getattr__(name: str):
    if name in __all__:
        from .app import KeilToolGui, launch_gui

        return {"KeilToolGui": KeilToolGui, "launch_gui": launch_gui}[name]
    raise AttributeError(name)
