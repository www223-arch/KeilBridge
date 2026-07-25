from __future__ import annotations

import json
from pathlib import Path

from .device_catalog import load_embedded_catalog
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
    catalog_device = load_embedded_catalog().lookup_any_vendor(normalized)
    if catalog_device is not None:
        vendor = catalog_device.vendor
        vendor_key = "gd" if "giga" in vendor.lower() else "st" if "stmicro" in vendor.lower() else vendor
        return DeviceInfo(
            matched=True,
            device=catalog_device.device,
            vendor=vendor_key,
            family=_catalog_family(catalog_device.device),
            core=catalog_device.core,
            fpu=catalog_device.fpu,
            memory=[
                MemoryRegion(
                    name=item.name,
                    origin=f"0x{item.start:08X}",
                    length=f"0x{item.size:X}",
                )
                for item in catalog_device.memory
            ],
        )

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


def _catalog_family(device: str) -> str:
    normalized = _normalize_device_name(device)
    for prefix, family in (
        ("GD32F10", "gd32f1"),
        ("GD32F30", "gd32f3"),
        ("GD32F4", "gd32f4"),
        ("STM32F1", "stm32f1"),
        ("STM32F3", "stm32f3"),
        ("STM32F4", "stm32f4"),
        ("STM32G4", "stm32g4"),
        ("STM32H7", "stm32h7"),
        ("STM32L4", "stm32l4"),
    ):
        if normalized.startswith(prefix):
            return family
    return ""
