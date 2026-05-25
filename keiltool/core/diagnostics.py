from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .project_model import KeilTargetModel

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

    if not target.memory:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="memory_unknown",
                message="No memory regions could be inferred from the Keil target.",
                detail="A device database entry or explicit override will be required before linker generation.",
            )
        )

    return diagnostics
