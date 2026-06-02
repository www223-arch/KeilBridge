from __future__ import annotations

import json
from dataclasses import asdict
import os
from pathlib import Path

from keiltool.core.diagnostics import diagnose_target
from keiltool.core.project_model import KeilTargetModel
from keiltool.core.scatter import parse_scatter_memory
from keiltool.core.tool_finder import armclang_environment, find_armclang_tools, find_cmake, find_ninja, find_openocd, find_openocd_scripts
from keiltool.generators.armclang_generator import (
    generate_armclang_cmakelists,
    generate_armclang_presets,
    generate_armclang_scatter_from_memory,
    generate_armclang_toolchain,
)
from keiltool.generators.debug_generator import generate_debug_configuration, generate_openocd_config


def configure_armclang_workspace(
    workspace_root: Path,
    target: KeilTargetModel,
    probe: str = "stlink",
    armclang_root: str | None = None,
) -> Path:
    """生成 ArmClang 后端工作区。

    当前 ArmClang 后端是“可生成、可审查、待实机验证”的阶段：它会独立放在
    `.keilbridge/generated/armclang`，构建目录是 `.keilbridge/build/armclang-debug`。
    这样不会覆盖已经跑通的 GCC 产物，也方便后续把两个后端的 map/size/ELF 做对比。
    """

    project_name = _sanitize_name(target.name)
    generated_dir = workspace_root / ".keilbridge" / "generated" / "armclang"
    build_dir = workspace_root / ".keilbridge" / "build" / "armclang-debug"
    report_dir = workspace_root / ".keilbridge" / "generated" / "reports"
    for directory in [
        generated_dir / "cmake",
        generated_dir / "scatter",
        generated_dir / "openocd",
        generated_dir / ".vscode",
        report_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    scatter_file, scatter_note = _resolve_scatter(target, generated_dir)
    tools = find_armclang_tools(armclang_root)
    openocd = find_openocd()
    openocd_scripts = find_openocd_scripts(openocd)
    openocd_config = generated_dir / "openocd" / f"{project_name}_{probe}.cfg"
    cmake = find_cmake()
    ninja = find_ninja()

    _write(generated_dir / "cmake" / "armclang.cmake", generate_armclang_toolchain(target))
    _write(generated_dir / "CMakeLists.txt", generate_armclang_cmakelists(target, scatter_file))
    _write(generated_dir / "CMakePresets.json", generate_armclang_presets())
    _write(openocd_config, generate_openocd_config(target, probe, openocd_scripts))
    _write(generated_dir / ".vscode" / "launch.json", _launch_json(target, probe, build_dir, openocd, openocd_scripts, openocd_config))
    _write(generated_dir / ".vscode" / "tasks.json", _tasks_json(cmake, ninja, generated_dir, build_dir, armclang_root))
    _write_json(
        report_dir / "armclang_workspace.json",
        {
            "schema": "keilbridge.armclang_workspace.v1",
            "target": asdict(target),
            "tools": tools,
            "scatter": str(scatter_file),
            "scatter_note": scatter_note,
            "generated_dir": str(generated_dir),
            "build_dir": str(build_dir),
            "diagnostics": [asdict(item) for item in diagnose_target(target)],
        },
    )
    _write(report_dir / "armclang_workspace.md", _report_markdown(target, tools, scatter_file, scatter_note, generated_dir, build_dir))
    _write(
        workspace_root / ".keilbridge" / f"KeilBridge_{project_name}_armclang.code-workspace",
        _code_workspace(target, workspace_root, generated_dir, build_dir, openocd, openocd_scripts, openocd_config, cmake, ninja, armclang_root, probe),
    )
    return generated_dir


def _resolve_scatter(target: KeilTargetModel, generated_dir: Path) -> tuple[Path, str]:
    if target.scatter_file:
        return Path(target.scatter_file), "Using ScatterFile configured in selected Keil target."
    if target.scatter_candidates:
        candidate = Path(target.scatter_candidates[0])
        try:
            parse_scatter_memory(str(candidate))
            return candidate, "Using first discovered scatter candidate because selected Keil target has no explicit ScatterFile."
        except Exception:
            pass
    generated = generated_dir / "scatter" / f"{_sanitize_name(target.name)}.sct"
    _write(generated, generate_armclang_scatter_from_memory(target, target.memory))
    return generated, "Generated minimal scatter from target Cpu/device memory."


def _launch_json(target: KeilTargetModel, probe: str, build_dir: Path, openocd: str, scripts: str, cfg: Path) -> str:
    configuration = generate_debug_configuration(
        target=target,
        probe=probe,
        executable=build_dir / f"{_sanitize_name(target.name)}.axf",
        cwd=build_dir.parent.parent / "generated" / "armclang",
        openocd_path=openocd,
        openocd_scripts=scripts,
        openocd_config=cfg,
        pre_launch_task="KeilBridge ArmClang: build",
    )
    return json.dumps({"version": "0.2.0", "configurations": [configuration]}, ensure_ascii=False, indent=2) + "\n"


def _tasks_json(cmake: str, ninja: str, generated_dir: Path, build_dir: Path, armclang_root: str | None) -> str:
    env = _task_env(armclang_root)
    return json.dumps(
        {
            "version": "2.0.0",
            "tasks": [
                _configure_task(cmake, ninja, generated_dir, build_dir, env),
                {
                    "label": "KeilBridge ArmClang: build",
                    "type": "process",
                    "command": _json_path(cmake),
                    "args": ["--build", _json_path(str(build_dir))],
                    "dependsOn": "KeilBridge ArmClang: configure",
                    "options": {"env": env},
                    "problemMatcher": "$gcc",
                },
            ],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _configure_task(cmake: str, ninja: str, generated_dir: Path, build_dir: Path, env: dict[str, str]) -> dict:
    task = {
        "label": "KeilBridge ArmClang: configure",
        "type": "process",
        "command": _json_path(cmake),
        "args": [
            "-S",
            _json_path(str(generated_dir)),
            "-B",
            _json_path(str(build_dir)),
            "-G",
            "Ninja",
            f"-DCMAKE_MAKE_PROGRAM={_json_path(ninja)}",
        ],
        "problemMatcher": [],
    }
    if env:
        task["options"] = {"env": env}
    return task


def _task_env(armclang_root: str | None) -> dict[str, str]:
    """为 VS Code task 补齐 Keil/ArmClang 运行环境，避免只在 CLI 中能构建。"""

    env = armclang_environment(armclang_root)
    task_env: dict[str, str] = {}
    for key, value in env.items():
        if key == "PATH_PREFIX":
            task_env["PATH"] = _json_path(value) + ";${env:PATH}"
        else:
            task_env[key] = _json_path(value)
    return task_env


def _code_workspace(
    target: KeilTargetModel,
    workspace_root: Path,
    generated_dir: Path,
    build_dir: Path,
    openocd: str,
    scripts: str,
    cfg: Path,
    cmake: str,
    ninja: str,
    armclang_root: str | None,
    probe: str,
) -> str:
    configuration = generate_debug_configuration(
        target=target,
        probe=probe,
        executable=build_dir / f"{_sanitize_name(target.name)}.axf",
        cwd=generated_dir,
        openocd_path=openocd,
        openocd_scripts=scripts,
        openocd_config=cfg,
        pre_launch_task="KeilBridge ArmClang: build",
    )
    payload = {
        "folders": [
            {"name": "Original Source", "path": _json_path(str(_source_view_root(target, workspace_root)))},
            {"name": "KeilBridge ArmClang Generated", "path": _json_path(str(generated_dir))},
        ],
        "settings": {
            "cmake.configureOnOpen": False,
            "cmake.useCMakePresets": "always",
            "C_Cpp.default.compileCommands": _json_path(str(build_dir / "compile_commands.json")),
            "C_Cpp.errorSquiggles": "enabled",
        },
        "launch": {"version": "0.2.0", "configurations": [configuration]},
        "tasks": json.loads(_tasks_json(cmake, ninja, generated_dir, build_dir, armclang_root))["tasks"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _source_view_root(target: KeilTargetModel, fallback: Path) -> Path:
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


def _report_markdown(target: KeilTargetModel, tools: dict[str, str], scatter: Path, scatter_note: str, generated_dir: Path, build_dir: Path) -> str:
    missing = [name for name, path in tools.items() if not path]
    lines = [
        "# KeilBridge ArmClang Workspace Report",
        "",
        f"- Target: `{target.name}`",
        f"- Device: `{target.device or 'unknown'}`",
        f"- Generated dir: `{generated_dir}`",
        f"- Build dir: `{build_dir}`",
        f"- Scatter: `{scatter}`",
        f"- Scatter strategy: {scatter_note}",
        "",
        "## Toolchain",
        "",
    ]
    for name, path in tools.items():
        lines.append(f"- `{name}`: `{path or 'not found'}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This workspace is generated outside the Keil project and does not modify user files.",
            "- ArmClang backend is intended to preserve Keil/ArmLink semantics first, then improve portability.",
            "- If tools are missing, set `ARMCLANG_ROOT` to Keil `ARMCLANG` or `ARMCLANG\\bin` before building.",
        ]
    )
    if missing:
        lines.extend(["", "## Missing Tools", "", f"- {', '.join(missing)}"])
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _json_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
