from __future__ import annotations

import json
from pathlib import Path

from .project_model import KeilTargetModel, MemoryRegion


def apply_device_override(target: KeilTargetModel, project_root: str | Path) -> None:
    override_path = Path(project_root) / ".keilbridge" / "device_override.json"
    if not override_path.exists():
        return
    payload = json.loads(override_path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if isinstance(targets, dict):
        payload = targets.get(target.name, {})

    if payload.get("openocd_target"):
        target.device_info.openocd_target = str(payload["openocd_target"])
    if payload.get("probe"):
        target.debug_probe = str(payload["probe"])
    if payload.get("flash_algorithm"):
        target.flash_algorithm = str(payload["flash_algorithm"])
    if isinstance(payload.get("memory"), list):
        target.memory = [
            MemoryRegion(
                name=str(item["name"]),
                origin=str(item["origin"]),
                length=str(item["length"]),
            )
            for item in payload["memory"]
            if all(key in item for key in ("name", "origin", "length"))
        ]
