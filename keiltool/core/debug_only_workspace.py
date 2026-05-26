from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from keiltool.core.diagnostics import diagnose_target
from keiltool.core.project_model import KeilTargetModel
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts
from keiltool.generators.debug_generator import generate_debug_configuration, generate_openocd_config


def configure_debug_only_workspace(
    workspace_root: Path,
    target: KeilTargetModel,
    probe: str = "stlink",
    executable: str | None = None,
    keil_project_dir: str | Path | None = None,
) -> Path:
    """生成只调试已有 AXF/ELF 的工作区。

    Debug-only 不负责构建，也不要求 CMake 能编译用户工程。它只复用 Keil 或其他链路
    已经生成的调试符号文件，然后生成 VS Code/Cortex-Debug/OpenOCD 配置，用于断点、
    单步、变量、寄存器和 Fault 现场采集。
    """

    project_name = _sanitize_name(target.name)
    generated_dir = workspace_root / ".keilbridge" / "generated" / "debug-only"
    report_dir = workspace_root / ".keilbridge" / "generated" / "reports"
    for directory in [generated_dir / "openocd", generated_dir / ".vscode", report_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    resolved_executable = _resolve_executable(workspace_root, target, executable, keil_project_dir)
    openocd = find_openocd()
    openocd_scripts = find_openocd_scripts(openocd)
    openocd_config = generated_dir / "openocd" / f"{project_name}_{probe}.cfg"
    source_root = _source_view_root(target, workspace_root)

    _write(openocd_config, generate_openocd_config(target, probe))
    _write(generated_dir / ".vscode" / "launch.json", _launch_json(target, probe, resolved_executable, generated_dir, openocd, openocd_scripts, openocd_config))
    _write(
        workspace_root / ".keilbridge" / f"KeilBridge_{project_name}_debug.code-workspace",
        _code_workspace(target, source_root, generated_dir, resolved_executable, openocd, openocd_scripts, openocd_config, probe),
    )
    _write_json(
        report_dir / "debug_only_workspace.json",
        {
            "schema": "keilbridge.debug_only_workspace.v1",
            "target": asdict(target),
            "executable": str(resolved_executable),
            "generated_dir": str(generated_dir),
            "diagnostics": [asdict(item) for item in diagnose_target(target)],
        },
    )
    _write(report_dir / "debug_only_workspace.md", _report_markdown(target, resolved_executable, generated_dir))
    return generated_dir


def _resolve_executable(workspace_root: Path, target: KeilTargetModel, executable: str | None, keil_project_dir: str | Path | None) -> Path:
    if executable:
        path = Path(executable)
        if not path.is_absolute():
            path = workspace_root / path
        if not path.exists():
            raise FileNotFoundError(f"Debug executable not found: {path}")
        return path.resolve()

    keil_dir = Path(keil_project_dir) if keil_project_dir else workspace_root / "MDK-ARM"
    candidates = [
        workspace_root / "MDK-ARM" / target.name / f"{target.name}.axf",
        keil_dir / target.name / f"{target.name}.axf",
        workspace_root / "MDK-ARM" / target.name / f"{target.name}.elf",
        keil_dir / target.name / f"{target.name}.elf",
    ]
    existing = [item for item in candidates if item.exists()]
    if existing:
        return existing[0].resolve()

    found = sorted(
        [*workspace_root.rglob("*.axf"), *workspace_root.rglob("*.elf")],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for item in found:
        if ".keilbridge" not in item.parts:
            return item.resolve()
    raise FileNotFoundError("No Keil AXF/ELF found. Pass --elf with the Keil build output path.")


def _launch_json(
    target: KeilTargetModel,
    probe: str,
    executable: Path,
    generated_dir: Path,
    openocd: str,
    scripts: str,
    cfg: Path,
) -> str:
    configuration = _debug_launch_configuration(
        target=target,
        probe=probe,
        executable=executable,
        cwd=generated_dir,
        openocd_path=openocd,
        openocd_scripts=scripts,
        openocd_config=cfg,
    )
    return json.dumps({"version": "0.2.0", "configurations": configuration}, ensure_ascii=False, indent=2) + "\n"


def _code_workspace(
    target: KeilTargetModel,
    source_root: Path,
    generated_dir: Path,
    executable: Path,
    openocd: str,
    scripts: str,
    cfg: Path,
    probe: str,
) -> str:
    configurations = _debug_launch_configuration(
        target=target,
        probe=probe,
        executable=executable,
        cwd=generated_dir,
        openocd_path=openocd,
        openocd_scripts=scripts,
        openocd_config=cfg,
    )
    payload = {
        "folders": [
            {"name": "Original Source", "path": _json_path(str(source_root))},
            {"name": "KeilBridge Debug-only Generated", "path": _json_path(str(generated_dir))},
        ],
        "settings": {
            "cmake.configureOnOpen": False,
            "C_Cpp.errorSquiggles": "enabled",
        },
        "launch": {"version": "0.2.0", "configurations": configurations},
        "tasks": {"version": "2.0.0", "tasks": []},
        "extensions": {"recommendations": ["marus25.cortex-debug", "ms-vscode.cpptools"]},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _debug_launch_configuration(
    target: KeilTargetModel,
    probe: str,
    executable: Path,
    cwd: Path,
    openocd_path: str,
    openocd_scripts: str,
    openocd_config: Path,
) -> list[dict]:
    """生成 Debug-only 的两种调试入口：附加现场、复位暂停。

    两者都不触发构建，也不下载固件；`attach` 适合保留当前运行现场，`launch` 适合
    重新复位后从入口附近开始排查。
    """

    reset_halt = generate_debug_configuration(
        target=target,
        probe=probe,
        executable=executable,
        cwd=cwd,
        openocd_path=openocd_path,
        openocd_scripts=openocd_scripts,
        openocd_config=openocd_config,
        pre_launch_task="",
    )
    reset_halt.pop("preLaunchTask", None)
    reset_halt["name"] = f"KeilBridge Debug-only Reset/Halt ({probe})"
    reset_halt["loadFiles"] = []

    attach = dict(reset_halt)
    attach["name"] = f"KeilBridge Debug-only Attach ({probe})"
    attach["request"] = "attach"
    attach.pop("runToEntryPoint", None)
    attach["postAttachCommands"] = []
    return [attach, reset_halt]


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


def _report_markdown(target: KeilTargetModel, executable: Path, generated_dir: Path) -> str:
    return "\n".join(
        [
            "# KeilBridge Debug-only Workspace Report",
            "",
            f"- Target: `{target.name}`",
            f"- Device: `{target.device or 'unknown'}`",
            f"- Executable: `{executable}`",
            f"- Generated dir: `{generated_dir}`",
            "",
            "## Boundary",
            "",
            "- Debug-only does not build user firmware.",
            "- Debug-only uses an existing AXF/ELF for symbols and OpenOCD/Cortex-Debug for live debugging.",
            "- Source files and Keil project files are not modified.",
        ]
    ) + "\n"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _json_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
