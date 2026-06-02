from __future__ import annotations

import json
from pathlib import Path

from keiltool.core.openocd_target_resolver import resolve_openocd_target
from keiltool.core.project_model import KeilTargetModel


def generate_launch_json(
    target: KeilTargetModel,
    probe: str = "stlink",
    openocd_path: str = "",
    openocd_scripts: str = "",
    openocd_config: str = "",
) -> str:
    """生成 VS Code Cortex-Debug 配置。

    OpenOCD 的 interface 由 probe profile 决定，target cfg 来自设备数据库。
    """

    configuration = generate_debug_configuration(
        target=target,
        probe=probe,
        executable=Path(f"${{workspaceFolder}}/../build/gcc-debug/{target.name}.elf"),
        cwd=Path("${workspaceFolder}"),
        openocd_path=openocd_path,
        openocd_scripts=openocd_scripts,
        openocd_config=openocd_config,
        pre_launch_task="KeilBridge: build",
    )
    return json.dumps({"version": "0.2.0", "configurations": [configuration]}, ensure_ascii=False, indent=2) + "\n"


def generate_vscode_settings() -> str:
    """生成 VS Code C/C++ 智能提示配置。

    真正的 includePath 不应该手写一份易漂移的列表，而应该读取 CMake/Ninja 生成的
    `compile_commands.json`。这样 KeilBridge 后续适配 RTOS port、GCC flags 或 include
    目录时，IntelliSense 会跟着真实构建命令走。
    """

    return json.dumps(
        {
            "cmake.configureOnOpen": False,
            "cmake.useCMakePresets": "always",
            "C_Cpp.default.compileCommands": "${workspaceFolder}/../build/gcc-debug/compile_commands.json",
            "C_Cpp.errorSquiggles": "enabled",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def generate_code_workspace(
    target: KeilTargetModel,
    source_root: Path,
    generated_dir: Path,
    build_dir: Path,
    openocd_path: str,
    openocd_scripts: str,
    openocd_config: Path,
    cmake: str,
    ninja: str,
    arm_gcc_root: str,
    probe: str,
) -> str:
    """生成推荐打开的 VS Code 工作区。

    用户调试时需要同时看到原工程源码和 KeilBridge 生成层。只打开 `generated` 目录虽然能启动
    调试，但文件树里看不到原始源码，断点体验会很差；多根工作区可以在不移动目录结构的前提下
    把两边放到同一个 VS Code 视图里。
    """

    configuration = generate_debug_configuration(
        target=target,
        probe=probe,
        executable=build_dir / f"{target.name}.elf",
        cwd=generated_dir,
        openocd_path=openocd_path,
        openocd_scripts=openocd_scripts,
        openocd_config=openocd_config,
        pre_launch_task="KeilBridge: build",
    )
    payload = {
        "folders": [
            {"name": "Original Source", "path": _json_path(str(source_root))},
            {"name": "KeilBridge Generated", "path": _json_path(str(generated_dir))},
        ],
        "settings": {
            "cmake.configureOnOpen": False,
            "cmake.useCMakePresets": "always",
            "C_Cpp.default.compileCommands": _json_path(str(build_dir / "compile_commands.json")),
            "C_Cpp.errorSquiggles": "enabled",
        },
        "launch": {
            "version": "0.2.0",
            "configurations": [configuration],
        },
        "tasks": {
            "version": "2.0.0",
            "tasks": [
                _configure_task(cmake, ninja, generated_dir, build_dir, arm_gcc_root),
                _build_task(cmake, build_dir),
            ],
        },
        "extensions": {
            "recommendations": [
                "ms-vscode.cmake-tools",
                "marus25.cortex-debug",
                "ms-vscode.cpptools",
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def generate_debug_configuration(
    target: KeilTargetModel,
    probe: str,
    executable: Path,
    cwd: Path,
    openocd_path: str,
    openocd_scripts: str,
    openocd_config: str | Path,
    pre_launch_task: str,
) -> dict:
    """生成 Cortex-Debug 配置对象。

    VS Code 多根工作区里 `${workspaceFolder}` 容易解析到用户当前选中的根目录。调试配置
    使用绝对路径可以避开这个坑，确保 GDB server、ELF 和 OpenOCD cfg 都指向同一套
    `.keilbridge` 产物。
    """

    interface = {
        "stlink": "interface/stlink.cfg",
        "cmsis-dap": "interface/cmsis-dap.cfg",
        "daplink": "interface/cmsis-dap.cfg",
    }.get(probe, "interface/stlink.cfg")
    if openocd_config:
        config_files = [_json_path(str(openocd_config))]
    else:
        target_resolution = resolve_openocd_target(target, openocd_scripts)
        if not target_resolution.target_cfg:
            raise ValueError(f"OpenOCD target could not be resolved: {target_resolution.reason}")
        config_files = [interface, target_resolution.target_cfg]
    configuration = {
        "name": f"KeilBridge OpenOCD ({probe})",
        "type": "cortex-debug",
        "request": "launch",
        "servertype": "openocd",
        "cwd": _json_path(str(cwd)),
        "executable": _json_path(str(executable)),
        "loadFiles": [],
        "device": target.device,
        "configFiles": config_files,
        "runToEntryPoint": "main",
        "preLaunchTask": pre_launch_task,
        "showDevDebugOutput": "raw",
    }
    if openocd_path:
        configuration["serverpath"] = _json_path(openocd_path)
    if openocd_scripts:
        configuration["searchDir"] = [_json_path(openocd_scripts)]
    return configuration


def generate_openocd_config(target: KeilTargetModel, probe: str = "stlink", openocd_scripts: str = "") -> str:
    """生成单文件 OpenOCD 配置。

    对 GD32F303 这类 OpenOCD 没有官方专用 target 的芯片，实测可先复用 STM32F3 flash
    algorithm。配置文件放在 `.keilbridge/generated/openocd`，VS Code 和 CLI 都引用它，
    这样验证过的命令不会散落在用户手工配置里。
    """

    interface = {
        "stlink": "interface/stlink.cfg",
        "cmsis-dap": "interface/cmsis-dap.cfg",
        "daplink": "interface/cmsis-dap.cfg",
    }.get(probe, "interface/stlink.cfg")
    target_resolution = resolve_openocd_target(target, openocd_scripts)
    target_cfg = target_resolution.target_cfg
    adapter_speed = "1000" if probe in {"cmsis-dap", "daplink"} else "4000"
    chip_name = (target.device or target.name).lower()
    flash_size = _flash_size_hex(target)
    workarea = "0x4000"

    transport = "dapdirect_swd" if probe == "stlink" else "swd"

    return f"""source [find {interface}]
transport select {transport}
adapter speed {adapter_speed}

set CHIPNAME {chip_name}
set FLASH_SIZE {flash_size}
set WORKAREASIZE {workarea}

{_openocd_target_source_line(target_cfg, target_resolution.reason)}
"""


def generate_tasks_json(cmake: str, ninja: str, generated_dir: Path, build_dir: Path, arm_gcc_root: str) -> str:
    """生成 VS Code 构建任务。

    不能依赖 VS Code 任务环境里的 PATH。很多 Windows 机器上命令行能找到 CMake，
    但 VS Code task 的 PowerShell 找不到 `cmake.exe`，于是调试前反复弹
    “preLaunchTask 已终止”。这里和 `.code-workspace` 使用同一套绝对路径任务。
    """

    payload = {
        "version": "2.0.0",
        "tasks": [
            _configure_task(cmake, ninja, generated_dir, build_dir, arm_gcc_root),
            _build_task(cmake, build_dir),
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _configure_task(cmake: str, ninja: str, generated_dir: Path, build_dir: Path, arm_gcc_root: str) -> dict:
    task = {
        "label": "KeilBridge: configure",
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
    if arm_gcc_root:
        task["options"] = {"env": {"ARM_GCC_ROOT": _json_path(arm_gcc_root)}}
    return task


def _build_task(cmake: str, build_dir: Path) -> dict:
    return {
        "label": "KeilBridge: build",
        "type": "process",
        "command": _json_path(cmake),
        "args": ["--build", _json_path(str(build_dir))],
        "dependsOn": "KeilBridge: configure",
        "problemMatcher": "$gcc",
    }


def _flash_size_hex(target: KeilTargetModel) -> str:
    for region in target.memory:
        if region.name.upper() == "FLASH":
            return _length_to_hex(region.length)
    return "0x20000"


def _length_to_hex(length: str) -> str:
    text = length.strip().upper()
    if text.endswith("K"):
        return hex(int(text[:-1]) * 1024)
    if text.endswith("M"):
        return hex(int(text[:-1]) * 1024 * 1024)
    return hex(int(text, 0))


def _openocd_target_source_line(target_cfg: str, reason: str) -> str:
    if target_cfg:
        return f"source [find {target_cfg}]"
    return f"# KeilBridge OpenOCD target unresolved: {reason}"


def _json_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")
