from __future__ import annotations

import hashlib
from pathlib import Path

from keiltool.core.project_model import KeilTargetModel


def generate_source_overlays(target: KeilTargetModel, generated_dir: Path) -> dict[str, str]:
    """生成只用于外部 GCC 构建的源码覆盖副本。

    覆盖层只处理少量可以机械判断、机械修复的兼容污点。它不改用户原始源码，
    也不试图“猜业务逻辑”。如果源码错误无法用稳定规则修复，应继续让 GCC 报错。
    返回值是 `原始绝对路径 -> 覆盖副本绝对路径`，CMake 生成层据此重定向 source list。
    """

    overlay_dir = generated_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    overlays: dict[str, str] = {}
    report_lines = [
        "# KeilBridge Source Overlay Report",
        "",
        "This directory contains generated source copies used only by the external GCC build.",
        "Original project files are not modified.",
        "",
    ]

    for source in target.sources:
        original = Path(source.path)
        if not original.is_file():
            continue
        if original.name.lower() == "drv_memory.cpp":
            overlay = _try_generate_drv_memory_overlay(original, overlay_dir)
            if overlay:
                overlays[_path_key(str(original))] = str(overlay)
                report_lines.extend(
                    [
                        f"- `{original}`",
                        f"  -> `{overlay}`",
                        "  reason: rewrite invalid `std::malloc/std::free` definitions to global `malloc/free` for GCC.",
                        "",
                    ]
                )

    if overlays:
        (overlay_dir / "overlay_report.md").write_text("\n".join(report_lines), encoding="utf-8", newline="\n")
    else:
        report = overlay_dir / "overlay_report.md"
        if report.exists():
            report.unlink()

    return overlays


def _try_generate_drv_memory_overlay(original: Path, overlay_dir: Path) -> Path | None:
    """为 SRML `drv_memory.cpp` 生成 GCC 兼容副本。

    该文件在部分 Keil/ARMCC 工程中会写成 `void* std::malloc(...)` 和
    `void std::free(...)`。GCC/libstdc++ 不允许在命名空间外这样定义 `std`
    内的函数。这个修复只去掉 `std::` 限定，让用户原有的 FreeRTOS heap 接管逻辑
    保持不变。
    """

    data = original.read_bytes()
    fixed = data.replace(b"void* std::malloc(size_t size)", b"void* malloc(size_t size)")
    fixed = fixed.replace(b"void std::free(void* ptr)", b"void free(void* ptr)")
    if fixed == data:
        return None

    digest = hashlib.sha1(str(original).replace("\\", "/").lower().encode("utf-8")).hexdigest()[:12]
    overlay = overlay_dir / digest / original.name
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_bytes(fixed)
    return overlay


def _path_key(path: str) -> str:
    return path.replace("\\", "/").lower()
