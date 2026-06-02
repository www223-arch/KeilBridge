from __future__ import annotations

import json
from dataclasses import asdict
import os
from pathlib import Path

from keiltool.core.diagnostics import diagnose_target
from keiltool.core.project_model import KeilTargetModel
from keiltool.core.scatter import generate_gnu_ld, parse_scatter_memory
from keiltool.core.tool_finder import find_arm_gcc_root, find_cmake, find_ninja, find_openocd, find_openocd_scripts
from keiltool.generators.cmake_generator import generate_cmakelists, generate_presets, generate_toolchain, needs_arm_math_compat
from keiltool.generators.debug_generator import (
    generate_code_workspace,
    generate_launch_json,
    generate_openocd_config,
    generate_tasks_json,
    generate_vscode_settings,
)
from keiltool.generators.overlay_generator import generate_source_overlays
from keiltool.generators.startup_generator import generate_gcc_startup
from keiltool.generators.support_generator import generate_arm_math_compat, generate_syscalls


def configure_workspace(workspace_root: Path, target: KeilTargetModel, probe: str = "stlink") -> Path:
    """生成 KeilBridge 工作区。

    默认 `workspace_root` 是目标 Keil 工程根目录，因此每个工程都有自己的
    `.keilbridge/`，多个工程来回编译不会互相覆盖。这里仍然不修改 Keil 工程文件，
    只新增一个可删除、可再生成的工具工作目录。
    """

    generated_dir = workspace_root / ".keilbridge" / "generated"
    build_dir = workspace_root / ".keilbridge" / "build" / "gcc-debug"
    (generated_dir / "cmake").mkdir(parents=True, exist_ok=True)
    (generated_dir / "linker").mkdir(parents=True, exist_ok=True)
    (generated_dir / "startup").mkdir(parents=True, exist_ok=True)
    (generated_dir / "support").mkdir(parents=True, exist_ok=True)
    (generated_dir / ".vscode").mkdir(parents=True, exist_ok=True)
    (generated_dir / "reports").mkdir(parents=True, exist_ok=True)
    (generated_dir / "openocd").mkdir(parents=True, exist_ok=True)
    (generated_dir / "overlays").mkdir(parents=True, exist_ok=True)

    project_name = _sanitize_name(target.name)
    memory = _linker_memory(target)
    diagnostics = diagnose_target(target)
    openocd = find_openocd()
    openocd_scripts = find_openocd_scripts(openocd)
    openocd_config = f"openocd/{project_name}_{probe}.cfg"
    source_root = _source_view_root(target, workspace_root)
    cmake = find_cmake()
    ninja = find_ninja()
    arm_gcc_root = find_arm_gcc_root()
    source_overlays = generate_source_overlays(target, generated_dir)

    _write(generated_dir / "cmake" / "arm-none-eabi-gcc.cmake", generate_toolchain())
    _write(generated_dir / "linker" / f"{project_name}.ld", generate_gnu_ld(memory))
    _write(generated_dir / "startup" / f"{project_name}_startup.S", generate_gcc_startup(target))
    if needs_arm_math_compat(target):
        _write(generated_dir / "support" / "arm_math_compat.c", generate_arm_math_compat())
    else:
        _remove_if_exists(generated_dir / "support" / "arm_math_compat.c")
    _write(generated_dir / "support" / "syscalls.c", generate_syscalls())
    _write(generated_dir / "CMakeLists.txt", generate_cmakelists(target, generated_dir, source_overlays))
    _write(generated_dir / "CMakePresets.json", generate_presets())
    _write(generated_dir / "openocd" / f"{project_name}_{probe}.cfg", generate_openocd_config(target, probe, openocd_scripts))
    _write(
        generated_dir / ".vscode" / "launch.json",
        generate_launch_json(target, probe, openocd_path=openocd, openocd_scripts=openocd_scripts, openocd_config=openocd_config),
    )
    _write(generated_dir / ".vscode" / "tasks.json", generate_tasks_json(cmake, ninja, generated_dir, build_dir, arm_gcc_root))
    _write(generated_dir / ".vscode" / "settings.json", generate_vscode_settings())
    _write(
        workspace_root / ".keilbridge" / f"KeilBridge_{project_name}.code-workspace",
        generate_code_workspace(
            target=target,
            source_root=source_root,
            generated_dir=generated_dir,
            build_dir=build_dir,
            openocd_path=openocd,
            openocd_scripts=openocd_scripts,
            openocd_config=generated_dir / openocd_config,
            cmake=cmake,
            ninja=ninja,
            arm_gcc_root=arm_gcc_root,
            probe=probe,
        ),
    )
    _write_json(generated_dir / "reports" / "project_ir.json", _report_payload(target, diagnostics))
    _write(generated_dir / "reports" / "conversion_report.md", _report_markdown(target, diagnostics, probe))

    return generated_dir


def _linker_memory(target: KeilTargetModel):
    # 只有 Keil target 明确配置了 ScatterFile 时才把它视为事实源。
    # 有些工程的 output 目录会残留多个 `.sct`，可能来自其他 target 或旧构建。
    # 如果盲用这些候选文件，链接脚本会生成错误 RAM 大小，栈顶越界后启动时进入
    # BusFault/HardFault。未显式配置 scatter 时，优先使用当前 target 的 Cpu/device memory。
    if target.scatter_file:
        return parse_scatter_memory(target.scatter_file)
    return target.memory


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def _source_view_root(target: KeilTargetModel, fallback: Path) -> Path:
    """推导 VS Code 应展示的完整源码根。

    Keil 的 `.uvprojx` 经常放在 `MDK-ARM`、`Keil5_project` 这类子目录里，但源码分布在
    更高层的 Firmware、Drivers、Freertos、User、USP 等目录。调试工作区必须展示这些真实
    源码目录，否则用户只能看到生成层或局部工程目录，断点体验会很差。
    """

    paths: list[str] = []
    for source in target.sources:
        source_path = Path(source.path)
        if source_path.is_absolute():
            paths.append(str(source_path.parent))
    for include in target.includes:
        include_path = Path(include)
        if include_path.is_absolute():
            paths.append(str(include_path))
    if not paths:
        return fallback
    try:
        return Path(os.path.commonpath(paths))
    except ValueError:
        return fallback


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


def _report_payload(target: KeilTargetModel, diagnostics) -> dict:
    """输出可机器读取的工程 IR。

    这个文件不是给 CMake 直接消费的，而是给后续 adapter、测试用例和用户排障使用。
    参考迁移工具的工程化经验，解析结果必须先沉淀成中间模型，避免 generator 直接绑定
    Keil XML 的偶然结构。
    """

    return {
        "schema": "keilbridge.project_ir.v1",
        "target": asdict(target),
        "diagnostics": [asdict(item) for item in diagnostics],
    }


def _report_markdown(target: KeilTargetModel, diagnostics, probe: str) -> str:
    """输出面向用户的转换报告。

    报告只描述事实、风险和下一步验证方式，不承诺自动修复用户源码。
    对 GD32、CubeMX、RTOS 这类容易误判的场景，报告会明确当前边界。
    """

    lines = [
        "# KeilBridge Conversion Report",
        "",
        "## Target",
        "",
        f"- Name: `{target.name}`",
        f"- Device: `{target.device or 'unknown'}`",
        f"- Vendor/family: `{target.vendor or 'unknown'}/{target.family or 'unknown'}`",
        f"- Core: `{target.core or 'unknown'}`",
        f"- FPU/float ABI: `{target.fpu or 'none'}/{target.float_abi or 'unknown'}`",
        f"- Probe profile: `{probe}`",
        f"- OpenOCD target: `{target.device_info.openocd_target or 'not configured'}`",
        "",
        "## Project Shape",
        "",
        f"- Framework: `{target.features.framework}`",
        f"- Generated by: `{target.features.generated_by or 'unknown'}`",
        f"- RTOS: `{', '.join(target.features.rtos) if target.features.rtos else 'none detected'}`",
        f"- Middleware: `{', '.join(target.features.middleware) if target.features.middleware else 'none detected'}`",
        "",
        "## Diagnostics",
        "",
    ]

    if diagnostics:
        for item in diagnostics:
            lines.append(f"- `{item.level}` `{item.code}`: {item.message}")
            if item.detail:
                lines.append(f"  {item.detail}")
    else:
        lines.append("- No diagnostics.")

    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- KeilBridge does not modify user source files.",
            "- KeilBridge does not modify `.uvprojx`, `.uvoptx`, or CubeMX `.ioc` files.",
            "- If user source code has GCC errors, the build should fail and show the compiler diagnostics.",
            "- CubeMX projects are reused as-is; KeilBridge does not regenerate CubeMX code.",
            "- RTOS projects may need compiler-port mapping before they are considered fully supported.",
        ]
    )
    return "\n".join(lines) + "\n"
