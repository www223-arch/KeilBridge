from __future__ import annotations

import json
from pathlib import Path

from .project_model import DeviceInfo, MemoryRegion


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "devices"


def _load_device_files() -> dict[str, dict]:
    """加载内置设备数据库。

    这里先用 JSON 而不是 YAML，是为了 MVP 阶段不引入第三方依赖。
    后续如果设备库变复杂，可以再迁移到 YAML 或 pack 解析。
    """

    devices: dict[str, dict] = {}
    for file_path in DATA_DIR.glob("*.json"):
        with file_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        devices.update(payload)
    return devices


def _normalize_device_name(device: str) -> str:
    """把 Keil Device 字符串规整成用于查表的 key。

    Keil 里常见的封装后缀、大小写、大小容量标记可能略有不同。
    当前先做大小写统一；后续再增加别名表和模糊匹配。
    """

    return device.strip().upper()


def lookup_device(device: str) -> DeviceInfo:
    """按 Keil device 名称查找设备数据库。"""

    normalized = _normalize_device_name(device)
    devices = _load_device_files()
    raw = devices.get(normalized)
    if raw is None:
        return DeviceInfo(matched=False, device=device)

    memory = [
        MemoryRegion(
            name=item["name"],
            origin=item["origin"],
            length=item["length"],
        )
        for item in raw.get("memory", [])
    ]

    return DeviceInfo(
        matched=True,
        device=normalized,
        vendor=raw.get("vendor", ""),
        family=raw.get("family", ""),
        core=raw.get("core", ""),
        fpu=raw.get("fpu", ""),
        float_abi=raw.get("float_abi", ""),
        openocd_target=raw.get("openocd_target", ""),
        memory=memory,
    )

