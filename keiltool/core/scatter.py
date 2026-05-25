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

    MVP 先覆盖 CubeMX/MDK 常见的 LR_IROM1、RW_IRAM1 和 RW_CCM 结构。
    RW_CCM 不能简单丢弃：很多 Keil 老工程会用 `__attribute__((section(".CCM")))`
    放置已初始化的查表、外设实例表或运行态状态。如果 GNU ld/startup 不处理 `.CCM`，
    程序可能能编译烧录，却在运行时因为变量未初始化进入 Error_Handler。
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
            # Keil scatter 中常见 `RW_CCM 0x10000000 ... { *(.CCM) }`。
            # 这不是普通 SRAM，而是 STM32F4 的 CCMRAM。保留独立区域，后续 linker
            # 会把 `.CCM` 输入段放进去并由 startup 复制初始化数据。
            region_name = "CCMRAM" if "CCM" in name.upper() else "RAM"
        else:
            continue

        # FLASH 同时可能出现 LR_IROM1 和 ER_IROM1，保留第一个避免重复。
        # RAM/CCMRAM 需要分别保留，不能因为已有 RAM 就丢弃 CCMRAM。
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
    ccmram = _find_region(memory, "CCMRAM")
    if flash is None or ram is None:
        raise ValueError("GNU ld generation requires both FLASH and RAM regions.")

    ccm_memory = ""
    if ccmram is not None:
        ccm_memory = f"  CCMRAM (xrw) : ORIGIN = {ccmram.origin}, LENGTH = {ccmram.length}\n"

    if ccmram is not None:
        ccm_section = """  _siccm = LOADADDR(.ccmram);

  .ccmram :
  {
    . = ALIGN(4);
    _sccm = .;
    *(.CCM)
    *(.CCM*)
    . = ALIGN(4);
    _eccm = .;
  } >CCMRAM AT> FLASH

"""
    else:
        # startup 模板会统一尝试复制 CCM 段。没有 CCMRAM 的工程把符号定义为空范围，
        # 这样同一个启动模板可复用，避免 generator 根据每个芯片拼装不同汇编。
        ccm_section = """  _siccm = _sidata;
  _sccm = _edata;
  _eccm = _edata;

"""

    return f"""ENTRY(Reset_Handler)

MEMORY
{{
  FLASH (rx)  : ORIGIN = {flash.origin}, LENGTH = {flash.length}
  RAM   (xrw) : ORIGIN = {ram.origin}, LENGTH = {ram.length}
{ccm_memory.rstrip()}
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

  .ARM.extab :
  {{
    *(.ARM.extab* .gnu.linkonce.armextab.*)
  }} >FLASH

  .ARM.exidx :
  {{
    __exidx_start = .;
    *(.ARM.exidx* .gnu.linkonce.armexidx.*)
    __exidx_end = .;
  }} >FLASH

  /* C++ 全局对象构造/析构表。
     Reset_Handler 会调用 __libc_init_array()，但这个函数依赖下面这些符号遍历
     构造函数表。如果 linker script 漏掉 .init_array，带虚函数或默认成员初始化的
     全局 C++ 对象只会被 BSS 清零，运行到虚函数调用时就可能跳到 0x00000000、
     0x20020000 等非法地址并进入 HardFault。 */

  .preinit_array (READONLY) :
  {{
    . = ALIGN(4);
    PROVIDE_HIDDEN(__preinit_array_start = .);
    KEEP(*(.preinit_array*))
    PROVIDE_HIDDEN(__preinit_array_end = .);
    . = ALIGN(4);
  }} >FLASH

  .init_array (READONLY) :
  {{
    . = ALIGN(4);
    PROVIDE_HIDDEN(__init_array_start = .);
    KEEP(*(SORT(.init_array.*)))
    KEEP(*(.init_array*))
    PROVIDE_HIDDEN(__init_array_end = .);
    . = ALIGN(4);
  }} >FLASH

  .fini_array (READONLY) :
  {{
    . = ALIGN(4);
    PROVIDE_HIDDEN(__fini_array_start = .);
    KEEP(*(SORT(.fini_array.*)))
    KEEP(*(.fini_array*))
    PROVIDE_HIDDEN(__fini_array_end = .);
    . = ALIGN(4);
  }} >FLASH

  .ctors (READONLY) :
  {{
    . = ALIGN(4);
    KEEP(*crtbegin.o(.ctors))
    KEEP(*crtbegin?.o(.ctors))
    KEEP(*(EXCLUDE_FILE(*crtend?.o *crtend.o) .ctors))
    KEEP(*(SORT(.ctors.*)))
    KEEP(*(.ctors))
    . = ALIGN(4);
  }} >FLASH

  .dtors (READONLY) :
  {{
    . = ALIGN(4);
    KEEP(*crtbegin.o(.dtors))
    KEEP(*crtbegin?.o(.dtors))
    KEEP(*(EXCLUDE_FILE(*crtend?.o *crtend.o) .dtors))
    KEEP(*(SORT(.dtors.*)))
    KEEP(*(.dtors))
    . = ALIGN(4);
  }} >FLASH

  _sidata = LOADADDR(.data);

  .data :
  {{
    . = ALIGN(4);
    _sdata = .;
    *(.data)
    *(.data*)
    /* KeilBridge 兼容 SRML/用户代码里常见的 `__SRAM` 宏。
       如果不把 `.SRAM` 显式收进 `.data`，GNU ld 会生成 orphan section，
       startup 复制范围就可能漏掉这类已初始化 SRAM 对象。 */
    *(.SRAM)
    *(.SRAM*)
    . = ALIGN(4);
    _edata = .;
  }} >RAM AT> FLASH

{ccm_section.rstrip()}

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
