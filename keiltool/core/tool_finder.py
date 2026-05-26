from __future__ import annotations

import os
import shutil
from pathlib import Path


VS_CMAKE = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe")
VS_NINJA = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe")
OPENOCD_CANDIDATES = [
    Path(r"C:\OpenOCD\bin\openocd.exe"),
    Path(r"C:\Program Files\OpenOCD\bin\openocd.exe"),
    Path(r"C:\Program Files (x86)\OpenOCD\bin\openocd.exe"),
    Path(r"D:\ESP32\Esp_idf\Espressif\tools\openocd-esp32\v0.12.0-esp32-20250422\openocd-esp32\bin\openocd.exe"),
]
ARM_GCC_ROOTS = [
    Path(r"C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\14.2 rel1"),
    Path(r"C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\12.2 mpacbti-rel1"),
    Path(r"C:\Program Files\Arm GNU Toolchain arm-none-eabi\14.2 rel1"),
    Path(r"C:\Program Files\Arm GNU Toolchain arm-none-eabi\12.2 mpacbti-rel1"),
]
ARMCLANG_ROOTS = [
    Path(r"C:\Keil_v5\ARM\ARMCLANG"),
    Path(r"C:\Keil_v5\ARM\ARMCLANG\bin"),
    Path(r"D:\Keil5\ARM\ARMCLANG"),
    Path(r"D:\Keil5\ARM\ARMCLANG\bin"),
    Path(r"D:\Keil_v5\ARM\ARMCLANG"),
    Path(r"D:\Keil_v5\ARM\ARMCLANG\bin"),
    Path(r"C:\Program Files\Arm\Development Studio 2024.1\bin"),
    Path(r"C:\Program Files\Arm\Development Studio 2023.1\bin"),
]


def find_cmake(explicit: str | None = None) -> str:
    """寻找 CMake。

    Windows 上 VS 会自带 CMake，但通常没进 PATH。这里优先尊重用户显式传入，
    其次查 PATH，最后查 VS 常见路径。
    """

    return _find_executable(explicit, "cmake", [VS_CMAKE])


def find_ninja(explicit: str | None = None) -> str:
    """寻找 Ninja，规则同 CMake。"""

    return _find_executable(explicit, "ninja", [VS_NINJA])


def find_arm_gcc_root(explicit: str | None = None) -> str:
    """寻找 Arm GNU Toolchain 根目录。

    生成的 toolchain 文件读取 `ARM_GCC_ROOT`，所以 build 命令只需要把这个环境
    变量临时补进去，不污染用户系统环境。
    """

    if explicit:
        return explicit
    if os.environ.get("ARM_GCC_ROOT"):
        return os.environ["ARM_GCC_ROOT"]
    if shutil.which("arm-none-eabi-gcc"):
        return ""
    for root in ARM_GCC_ROOTS:
        if (root / "bin" / "arm-none-eabi-gcc.exe").exists():
            return str(root)
    return ""


def find_armclang_tools(explicit_root: str | None = None) -> dict[str, str]:
    """查找 ArmClang/ArmLink 工具链。

    ArmClang 后端和 GCC 后端的技术边界不同：它更适合承接 Keil/AC6 工程里的
    scatter、ARMCC/ArmClang 库和 ARMASM 启动文件。因此这里不只找 `armclang.exe`，
    还同时检查 `armlink.exe`、`armasm.exe`、`fromelf.exe`。Backend Doctor 会根据
    这些结果告诉用户“适合用 ArmClang”和“本机是否已经具备 ArmClang 环境”是两回事。
    """

    root = _normalize_tool_root(explicit_root)
    candidates = [root] if root else [*ARMCLANG_ROOTS]
    tools = {
        "armclang": _find_first_tool_in_roots(["armclang_kb.exe", "armclang.exe"], candidates),
        "armlink": _find_tool_in_roots("armlink.exe", candidates),
        "armasm": _find_tool_in_roots("armasm.exe", candidates),
        "fromelf": _find_tool_in_roots("fromelf.exe", candidates),
    }
    return tools


def armclang_environment(explicit_root: str | None = None) -> dict[str, str]:
    """生成命令行调用 ArmClang 所需的环境变量。

    Keil IDE 会在内部补齐 license/product/toolkit 环境；直接从 CMake 或 PowerShell
    调 `armclang/armlink/fromelf` 时，这些变量经常缺失。这里按 Keil 安装目录推导，
    让外部构建尽量复用和 Keil 相同的授权配置。
    """

    tools = find_armclang_tools(explicit_root)
    armclang = tools.get("armclang", "")
    if not armclang:
        return {}
    bin_dir = Path(armclang).parent
    arm_dir = bin_dir.parent.parent
    keil_root = arm_dir.parent
    env: dict[str, str] = {
        "ARMCLANG_ROOT": str(bin_dir.parent),
        "PATH_PREFIX": os.pathsep.join([str(bin_dir), str(arm_dir / "BIN")]),
    }
    product_path = arm_dir / "sw" / "mappings"
    if product_path.exists():
        env["ARM_PRODUCT_PATH"] = str(product_path)
    tool_variant = _read_tool_variant(keil_root / "TOOLS.INI")
    if tool_variant:
        env["ARM_TOOL_VARIANT"] = tool_variant
    return env


def find_openocd(explicit: str | None = None) -> str:
    """寻找 OpenOCD。

    调试服务可能来自独立 OpenOCD、xPack OpenOCD、STM32CubeIDE 或用户自定义路径。
    MVP 先查显式参数、PATH 和常见独立安装路径。
    """

    return _find_executable(explicit, "openocd", OPENOCD_CANDIDATES)


def find_openocd_scripts(openocd_path: str) -> str:
    """根据 openocd.exe 位置推导 scripts 目录。

    Cortex-Debug 的 `searchDir` 和命令行 OpenOCD 的 `-s` 都需要这个目录。
    独立 OpenOCD、xPack 和 ESP-IDF 打包版目录层级略有差异，所以从 exe 位置向上查找
    `share/openocd/scripts`，找不到时返回空字符串，让 OpenOCD 使用自身默认搜索路径。
    """

    exe = Path(openocd_path)
    if not exe.exists():
        return ""
    for parent in [exe.parent, *exe.parents]:
        candidate = parent / "share" / "openocd" / "scripts"
        if candidate.exists():
            return str(candidate)
    return ""


def _find_executable(explicit: str | None, name: str, candidates: list[Path]) -> str:
    if explicit:
        return explicit
    found = shutil.which(name)
    if found:
        return found
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return name


def _normalize_tool_root(explicit_root: str | None) -> Path | None:
    if not explicit_root:
        env_root = os.environ.get("ARMCLANG_ROOT") or os.environ.get("ARM_TOOLCHAIN_ROOT")
        if not env_root:
            return None
        explicit_root = env_root
    root = Path(explicit_root)
    if root.name.lower() == "bin":
        return root
    return root / "bin"


def _find_tool_in_roots(tool: str, roots: list[Path]) -> str:
    found = shutil.which(tool)
    if found:
        return found
    for root in roots:
        if not root:
            continue
        candidate = root / tool
        if candidate.exists():
            return str(candidate)
    return ""


def _find_first_tool_in_roots(tools: list[str], roots: list[Path]) -> str:
    for tool in tools:
        found = _find_tool_in_roots(tool, roots)
        if found:
            return found
    return ""


def _read_tool_variant(tools_ini: Path) -> str:
    if not tools_ini.exists():
        return ""
    try:
        for line in tools_ini.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().upper().startswith("TOOL_VARIANT="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        return ""
    return ""
