from __future__ import annotations

import re
from pathlib import Path

from .path_resolver import normalize_path
from .project_model import MemoryRegion


SCATTER_REGION_RE = re.compile(
    r"(?P<name>LR_\w+|ER_\w+|RW_\w+)\s+"
    r"(?P<origin>0x[0-9A-Fa-f]+)\s+"
    r"(?P<size>0x[0-9A-Fa-f]+|[0-9]+)"
)


def discover_scatter_files(keil_project_dir: Path, target_name: str) -> list[str]:
    """在 Keil 工程目录里寻找可能的 scatter 文件。

    很多 Keil 工程的 `<ScatterFile>` 为空，但构建后会在输出目录生成 `.sct`。
    这是典型的“Keil 能构建但 uvprojx 不完整描述”的情况，所以工具要主动发现。
    """

    candidates = sorted(keil_project_dir.rglob("*.sct"))
    if not candidates:
        return []

    # 优先返回文件名或父目录包含 target 名称的候选，这样多 target 工程更稳定。
    normalized_target = target_name.lower()
    preferred = [
        path
        for path in candidates
        if normalized_target in path.stem.lower() or normalized_target in path.parent.name.lower()
    ]
    ordered = preferred + [path for path in candidates if path not in preferred]
    return [normalize_path(str(path.resolve())) for path in ordered]


def parse_scatter_memory(scatter_file: str | Path) -> list[MemoryRegion]:
    """从常见 Keil scatter 文件中提取 FLASH/RAM 区域。

    MVP 先覆盖 CubeMX/MDK 常见的 LR_IROM1 和 RW_IRAM1 结构。
    更复杂的多 bank、多 RAM、外部 Flash 后续由 adapter 或 override 接管。
    """

    text = Path(scatter_file).read_text(encoding="utf-8", errors="ignore")
    regions: list[MemoryRegion] = []
    for match in SCATTER_REGION_RE.finditer(text):
        name = match.group("name")
        origin = int(match.group("origin"), 16)
        size_raw = match.group("size")
        size = int(size_raw, 16) if size_raw.lower().startswith("0x") else int(size_raw)
        if name.startswith("LR_") or name.startswith("ER_"):
            region_name = "FLASH"
        elif name.startswith("RW_"):
            region_name = "RAM"
        else:
            continue

        # 同类区域可能同时出现 LR_IROM1 和 ER_IROM1，保留第一个避免重复。
        if any(region.name == region_name for region in regions):
            continue
        regions.append(MemoryRegion(name=region_name, origin=f"0x{origin:08X}", length=_format_size(size)))
    return regions


def generate_gnu_ld(memory: list[MemoryRegion]) -> str:
    """根据归一化内存模型生成最小 GNU ld 脚本。

    这里生成的是后续 CMake 链接的基础模板。它不会修改原 `.sct`，只在
    `.keiltool/generated/linker/` 之类目录中产生派生文件。
    """

    flash = _find_region(memory, "FLASH")
    ram = _find_region(memory, "RAM")
    if flash is None or ram is None:
        raise ValueError("GNU ld generation requires both FLASH and RAM regions.")

    return f"""ENTRY(Reset_Handler)

MEMORY
{{
  FLASH (rx)  : ORIGIN = {flash.origin}, LENGTH = {flash.length}
  RAM   (xrw) : ORIGIN = {ram.origin}, LENGTH = {ram.length}
}}

_Min_Heap_Size = 0x200;
_Min_Stack_Size = 0x400;
_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{{
  .isr_vector :
  {{
    . = ALIGN(4);
    KEEP(*(.isr_vector))
    . = ALIGN(4);
  }} >FLASH

  .text :
  {{
    . = ALIGN(4);
    *(.text)
    *(.text*)
    *(.rodata)
    *(.rodata*)
    KEEP(*(.init))
    KEEP(*(.fini))
    . = ALIGN(4);
    _etext = .;
  }} >FLASH

  _sidata = LOADADDR(.data);

  .data :
  {{
    . = ALIGN(4);
    _sdata = .;
    *(.data)
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  }} >RAM AT> FLASH

  .bss :
  {{
    . = ALIGN(4);
    _sbss = .;
    *(.bss)
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  }} >RAM

  ._user_heap_stack :
  {{
    . = ALIGN(8);
    PROVIDE(end = .);
    PROVIDE(_end = .);
    . = . + _Min_Heap_Size;
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  }} >RAM
}}
"""


def _find_region(memory: list[MemoryRegion], name: str) -> MemoryRegion | None:
    for region in memory:
        if region.name == name:
            return region
    return None


def _format_size(byte_count: int) -> str:
    if byte_count % 1024 == 0:
        return f"{byte_count // 1024}K"
    return str(byte_count)
