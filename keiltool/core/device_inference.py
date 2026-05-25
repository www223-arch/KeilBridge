from __future__ import annotations

import re

from .project_model import MemoryRegion


def infer_vendor(device: str) -> str:
    """从 Keil Device 名称推导厂商。

    这是设备数据库未命中时的兜底逻辑，不能替代正式数据库。
    """

    normalized = device.upper()
    if normalized.startswith("STM32"):
        return "st"
    if normalized.startswith("GD32"):
        return "gd"
    return ""


def infer_family(device: str) -> str:
    """从 Device 前缀推导系列名，例如 STM32G431 -> stm32g4。"""

    normalized = device.upper()
    for prefix in ("STM32", "GD32"):
        if normalized.startswith(prefix) and len(normalized) >= len(prefix) + 2:
            return f"{prefix.lower()}{normalized[len(prefix)].lower()}{normalized[len(prefix) + 1]}"
    return ""


def infer_core(cpu_text: str, device: str) -> str:
    """推导 Cortex 内核。

    优先读取 Keil Cpu 字段里的 CPUTYPE；如果工程没有写入，再根据系列粗略兜底。
    """

    match = re.search(r'CPUTYPE\("([^"]+)"\)', cpu_text)
    if match:
        return match.group(1).lower()

    family = infer_family(device)
    if family in {"stm32f1", "gd32f1"}:
        return "cortex-m3"
    if family in {"stm32f3", "stm32f4", "stm32g4", "stm32l4", "gd32f3"}:
        return "cortex-m4"
    if family in {"stm32h7"}:
        return "cortex-m7"
    return ""


def infer_fpu(cpu_text: str, core: str) -> tuple[str, str]:
    """推导 FPU 和 float ABI。

    Keil 的 FPU2 这类字段不是 GCC 参数，所以这里转换成 GCC 能理解的
    `-mfpu` 和 `-mfloat-abi` 信息。
    """

    if "FPU" in cpu_text.upper():
        if core == "cortex-m7":
            return "fpv5-d16", "hard"
        if core == "cortex-m4":
            return "fpv4-sp-d16", "hard"
    return "", "soft"


def _format_length(byte_count: int) -> str:
    if byte_count % 1024 == 0:
        return f"{byte_count // 1024}K"
    return str(byte_count)


def parse_memory_regions(cpu_text: str) -> list[MemoryRegion]:
    """从 Keil Cpu 字段解析 IROM/IRAM。

    例如 `IROM(0x8000000-0x801FFFF)` 会被转成 FLASH 128K。
    """

    regions: list[MemoryRegion] = []
    for name, start_hex, end_hex in re.findall(r"(IROM\d*|IRAM\d*)\(0x([0-9A-Fa-f]+)-0x([0-9A-Fa-f]+)\)", cpu_text):
        start = int(start_hex, 16)
        end = int(end_hex, 16)
        if end < start:
            continue
        length = end - start + 1
        region_name = "FLASH" if name.startswith("IROM") else "RAM"
        regions.append(
            MemoryRegion(
                name=region_name,
                origin=f"0x{start:08X}",
                length=_format_length(length),
            )
        )
    return regions
