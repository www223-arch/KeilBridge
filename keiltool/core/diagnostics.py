from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .openocd_target_resolver import resolve_openocd_target
from .project_model import KeilTargetModel
from .scatter import parse_scatter_memory

ARMCC_ONLY_DEFINES = {"__CC_ARM", "__ARMCC_VERSION", "ARMCOMPILER"}


@dataclass(slots=True)
class Diagnostic:
    level: str
    code: str
    message: str
    detail: str = ""


def diagnose_target(target: KeilTargetModel) -> list[Diagnostic]:
    """生成面向 GCC/CMake 适配的诊断。

    诊断层的职责是提前暴露风险，并给 generator/adapter 提供处理依据。
    它不会修改原工程，也不会静默吞掉不兼容问题。
    """

    diagnostics: list[Diagnostic] = []

    for define in target.defines:
        if define in ARMCC_ONLY_DEFINES:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="armcc_define",
                    message=f"Keil/ARMCC-only define detected: {define}",
                    detail="This define should be filtered from GCC builds to avoid selecting the wrong compiler branch.",
                )
            )

    for library in target.libraries:
        if Path(library).suffix.lower() == ".lib":
            diagnostics.append(
                Diagnostic(
                    level="error",
                    code="armcc_library",
                    message=f"ARMCC-style static library detected: {library}",
                    detail="GCC cannot be assumed to link this library. Configure a GCC-compatible replacement or build the library from source.",
                )
            )

    for startup in target.startup_files:
        if Path(startup).suffix.lower() in {".s", ".asm"}:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="startup_may_be_armasm",
                    message=f"Startup file may use Keil ARMASM syntax: {startup}",
                    detail="KeilTool should resolve a GCC startup file or generate one from a device template.",
                )
            )

    if not target.scatter_file:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="scatter_missing",
                message="No explicit ScatterFile found in the selected Keil target.",
                detail="Keil may be using a generated scatter file. KeilTool should infer memory from Cpu metadata or discover generated .sct files.",
            )
        )
        diagnostics.extend(_diagnose_scatter_candidates(target))

    if not target.memory:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="memory_unknown",
                message="No memory regions could be inferred from the Keil target.",
                detail="A device database entry or explicit override will be required before linker generation.",
            )
        )

    openocd_target = resolve_openocd_target(target)
    if target.vendor == "gd" and openocd_target.target_cfg:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="gd32_openocd_needs_board_validation",
                message=f"GD32 OpenOCD target selected: {openocd_target.target_cfg}",
                detail="Some GD32 parts can be debugged through OpenOCD compatibility targets, but flash/debug behavior must be verified with the actual chip and probe.",
            )
        )

    if target.vendor == "gd" and not openocd_target.target_cfg:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="gd32_openocd_unverified",
                message="GD32 device matched, but no verified OpenOCD target is configured.",
                detail="GD32 debug support should be verified with the actual board/probe. J-Link may be a better first validation path for some GD32 devices.",
            )
        )

    if target.features.generated_by == "stm32cubemx":
        diagnostics.append(
            Diagnostic(
                level="info",
                code="cubemx_detected",
                message="STM32CubeMX project shape detected.",
                detail="KeilBridge reuses CubeMX-generated Core/Drivers/Middlewares files and does not regenerate CubeMX code.",
            )
        )

    if target.features.rtos:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="rtos_detected",
                message=f"RTOS detected: {', '.join(target.features.rtos)}",
                detail="RTOS projects may require compiler-specific port mapping, such as RVDS to GCC FreeRTOS portable layer.",
            )
        )

    if any("freertos/portable/rvds/arm_cm4f" in source.path.replace("\\", "/").lower() for source in target.sources):
        diagnostics.append(
            Diagnostic(
                level="info",
                code="freertos_rvds_port_mapped",
                message="FreeRTOS RVDS/ARMCC Cortex-M4F port detected.",
                detail="Generated GCC CMake output maps this external build to the FreeRTOS GCC/ARM_CM4F port without modifying the Keil project.",
            )
        )

    return diagnostics


def _diagnose_scatter_candidates(target: KeilTargetModel) -> list[Diagnostic]:
    """检查自动发现的 scatter 候选是否和当前 target 内存一致。

    Keil output 目录里可能残留其他 target 的 `.sct`，比如 GD32F303CB 当前 CPU 字段是
    32K RAM，但某个 output `.sct` 写了 48K RAM。KeilBridge 不能盲用这种候选，否则
    GCC 链接脚本会把 `_estack` 放到不存在的 RAM，启动后 HardFault。
    """

    diagnostics: list[Diagnostic] = []
    if not target.scatter_candidates or not target.memory:
        return diagnostics

    expected = _memory_signature(target.memory)
    for candidate in target.scatter_candidates:
        try:
            actual = _memory_signature(parse_scatter_memory(candidate))
        except Exception:
            continue
        if actual and actual != expected:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="scatter_candidate_memory_mismatch",
                    message=f"Discovered scatter candidate does not match target memory: {candidate}",
                    detail=f"Target memory is {expected}; scatter candidate memory is {actual}. KeilBridge will prefer target Cpu/device memory unless ScatterFile is explicitly configured.",
                )
            )
    return diagnostics


def _memory_signature(memory) -> str:
    return ", ".join(f"{item.name}:{item.origin}+{item.length}" for item in memory)
