from __future__ import annotations

import re
from pathlib import Path

from keiltool.core.project_model import KeilTargetModel


DCD_RE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?DCD\s+([A-Za-z_][A-Za-z0-9_]*|0)\b")


def extract_vector_entries(startup_file: str | Path) -> list[str]:
    """从 Keil ARMASM startup 里抽取向量表。

    这一步不是把 ARMASM 逐行翻译成 GNU ASM，而是只复用最稳定的信息：
    中断向量表顺序。Reset 流程、数据段搬运和 BSS 清零由 KeilBridge 自己的
    GCC 模板生成，这样跨 Keil 版本更稳。
    """

    entries: list[str] = []
    for line in Path(startup_file).read_text(encoding="utf-8", errors="ignore").splitlines():
        match = DCD_RE.match(line)
        if match:
            entries.append(match.group(1))
    return entries


def generate_gcc_startup(target: KeilTargetModel) -> str:
    """生成 GCC 可编译的 startup `.S`。

    当前策略：从 Keil startup 抽取向量表，生成标准 GNU as 语法启动代码。
    后续 STM/GD 全系列可以把这部分替换为厂商 adapter 模板。
    """

    if not target.startup_files:
        raise ValueError("No startup file found in Keil target.")

    entries = extract_vector_entries(target.startup_files[0])
    if not entries or entries[0] == "0":
        raise ValueError("Could not extract a valid vector table from Keil startup.")

    # Keil startup 的第一个向量是 `__initial_sp`，但在 GCC 链接脚本里栈顶统一叫
    # `_estack`。无论 ARMASM 原文件怎么命名，外部 GCC 启动文件的第 0 项都必须是
    # RAM 栈顶；否则 CPU 会把 MSP 设成错误地址，启动后很快进入 MemManage/HardFault。
    entries[0] = "_estack"
    vector_symbols = [entry for entry in entries if entry != "0"]
    handler_symbols = [entry for entry in vector_symbols if entry not in {"_estack", "__initial_sp", "Reset_Handler"}]

    weak_handlers = "\n".join(
        f"def_irq_handler {symbol}" for symbol in dict.fromkeys(handler_symbols)
    )
    vector_lines = "\n".join(
        f"  .word {entry}" if entry != "0" else "  .word 0" for entry in entries
    )

    return f""".syntax unified
.cpu {target.core or "cortex-m4"}
{_fpu_directive(target)}
.thumb

.global g_pfnVectors
.global Reset_Handler

.section .text.Reset_Handler
.weak Reset_Handler
.type Reset_Handler, %function
Reset_Handler:
  ldr r0, =_estack
  mov sp, r0

  ldr r0, =_sdata
  ldr r1, =_edata
  ldr r2, =_sidata
  movs r3, #0
CopyData:
  adds r4, r0, r3
  cmp r4, r1
  bcc CopyDataWord
  b ZeroBss
CopyDataWord:
  ldr r5, [r2, r3]
  str r5, [r4]
  adds r3, r3, #4
  b CopyData

ZeroBss:
  ldr r0, =_sbss
  ldr r1, =_ebss
  movs r2, #0
ZeroBssLoop:
  cmp r0, r1
  bcc ZeroBssWord
  b CallInit
ZeroBssWord:
  str r2, [r0]
  adds r0, r0, #4
  b ZeroBssLoop

CallInit:
  bl SystemInit
  bl __libc_init_array
  bl main
LoopForever:
  b LoopForever
.size Reset_Handler, .-Reset_Handler

.section .text.Default_Handler,"ax",%progbits
Default_Handler:
Infinite_Loop:
  b Infinite_Loop
.size Default_Handler, .-Default_Handler

.macro def_irq_handler handler_name
  .weak \\handler_name
  .set \\handler_name, Default_Handler
.endm

{weak_handlers}

.section .isr_vector,"a",%progbits
.type g_pfnVectors, %object
g_pfnVectors:
{vector_lines}
.size g_pfnVectors, .-g_pfnVectors
"""


def _fpu_directive(target: KeilTargetModel) -> str:
    if target.fpu:
        return f".fpu {target.fpu}"
    return ""
