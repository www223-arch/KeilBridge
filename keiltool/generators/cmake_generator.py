from __future__ import annotations

from pathlib import Path

from keiltool.core.diagnostics import ARMCC_ONLY_DEFINES
from keiltool.core.project_model import KeilTargetModel


def generate_toolchain() -> str:
    """生成 GCC ARM Embedded toolchain 文件。

    支持两种方式：优先读取 `ARM_GCC_ROOT`，否则从 PATH 里找 `arm-none-eabi-*`。
    这样工具本身不绑定具体安装路径。
    """

    return """set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

if(DEFINED ENV{ARM_GCC_ROOT})
  file(TO_CMAKE_PATH "$ENV{ARM_GCC_ROOT}" ARM_GCC_ROOT)
  set(TOOLCHAIN_PREFIX "${ARM_GCC_ROOT}/bin/arm-none-eabi-")
  set(TOOLCHAIN_SUFFIX ".exe")
else()
  set(TOOLCHAIN_PREFIX "arm-none-eabi-")
  set(TOOLCHAIN_SUFFIX "")
endif()

set(CMAKE_C_COMPILER "${TOOLCHAIN_PREFIX}gcc${TOOLCHAIN_SUFFIX}" CACHE FILEPATH "C compiler" FORCE)
set(CMAKE_CXX_COMPILER "${TOOLCHAIN_PREFIX}g++${TOOLCHAIN_SUFFIX}" CACHE FILEPATH "CXX compiler" FORCE)
set(CMAKE_ASM_COMPILER "${TOOLCHAIN_PREFIX}gcc${TOOLCHAIN_SUFFIX}" CACHE FILEPATH "ASM compiler" FORCE)
set(CMAKE_OBJCOPY "${TOOLCHAIN_PREFIX}objcopy${TOOLCHAIN_SUFFIX}" CACHE FILEPATH "objcopy" FORCE)
set(CMAKE_SIZE "${TOOLCHAIN_PREFIX}size${TOOLCHAIN_SUFFIX}" CACHE FILEPATH "size" FORCE)

set(CMAKE_EXECUTABLE_SUFFIX_C ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_CXX ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_ASM ".elf")
"""


def generate_cmakelists(target: KeilTargetModel, generated_dir: Path, source_overlays: dict[str, str] | None = None) -> str:
    """生成外部 CMakeLists。

    这里引用原工程绝对路径，但不写入原工程；KeilBridge 生成的 startup/linker/support
    都放在 `.keilbridge/generated` 内。
    """

    project_name = _sanitize_name(target.name)
    sources = _source_list(target, generated_dir, source_overlays or {})
    includes = _cmake_list(_include_list(target))
    defines = _cmake_list([item for item in target.defines if item not in ARMCC_ONLY_DEFINES])
    compile_flags = _compile_flags(target)

    return f"""cmake_minimum_required(VERSION 3.20)

set(CMAKE_TOOLCHAIN_FILE "${{CMAKE_CURRENT_LIST_DIR}}/cmake/arm-none-eabi-gcc.cmake" CACHE FILEPATH "Toolchain")

project({project_name} C CXX ASM)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)

set(TARGET_NAME "{project_name}")
set(LINKER_SCRIPT "${{CMAKE_CURRENT_LIST_DIR}}/linker/{project_name}.ld")

set(SOURCES
{sources}
)

add_executable(${{TARGET_NAME}} ${{SOURCES}})

target_include_directories(${{TARGET_NAME}} PRIVATE
{includes}
)

target_compile_definitions(${{TARGET_NAME}} PRIVATE
{defines}
)

target_compile_options(${{TARGET_NAME}} PRIVATE
{compile_flags}
  -ffunction-sections
  -fdata-sections
  -fno-common
  -Wall
  -Wextra
  -Wno-unused-parameter
  -Wno-missing-field-initializers
  # Keil/ArmClang 老工程里常有一些 G++ 默认视为错误、但迁移期可以降级为
  # warning 的 C++ 写法，例如成员变量名和 typedef 同名。这里仅对 C++ 源启用
  # -fpermissive，不影响 C 源，也不修改用户源码。
  $<$<COMPILE_LANGUAGE:CXX>:-fpermissive>
  -g3
  -Og
)

target_link_options(${{TARGET_NAME}} PRIVATE
{compile_flags}
  -T${{LINKER_SCRIPT}}
  -Wl,-Map=${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.map
  -Wl,--gc-sections
  -Wl,--print-memory-usage
  --specs=nano.specs
  --specs=nosys.specs
)

target_link_libraries(${{TARGET_NAME}} PRIVATE m c gcc nosys)

add_custom_command(TARGET ${{TARGET_NAME}} POST_BUILD
  COMMAND ${{CMAKE_OBJCOPY}} -O ihex $<TARGET_FILE:${{TARGET_NAME}}> ${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.hex
  COMMAND ${{CMAKE_OBJCOPY}} -O binary $<TARGET_FILE:${{TARGET_NAME}}> ${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.bin
  COMMAND ${{CMAKE_SIZE}} $<TARGET_FILE:${{TARGET_NAME}}>
  COMMENT "Generating HEX/BIN and printing size"
)
"""


def generate_presets() -> str:
    """生成 CMakePresets，默认使用 Ninja。"""

    return """{
  "version": 3,
  "configurePresets": [
    {
      "name": "gcc-debug",
      "displayName": "GCC Debug",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/../build/gcc-debug",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug"
      }
    }
  ],
  "buildPresets": [
    {
      "name": "gcc-debug",
      "configurePreset": "gcc-debug"
    }
  ]
}
"""


def _source_list(target: KeilTargetModel, generated_dir: Path, source_overlays: dict[str, str]) -> str:
    original_sources: list[str] = []
    for source in target.sources:
        if source.kind == "startup":
            continue
        adapted = _adapt_source_path(source_overlays.get(_path_key(source.path), source.path), target)
        if adapted:
            original_sources.append(adapted)
    generated_sources = [
        generated_dir / "startup" / f"{_sanitize_name(target.name)}_startup.S",
        generated_dir / "support" / "syscalls.c",
    ]
    if needs_arm_math_compat(target):
        generated_sources.append(generated_dir / "support" / "arm_math_compat.c")
    return _cmake_list([*original_sources, *(str(path) for path in generated_sources)])


def _include_list(target: KeilTargetModel) -> list[str]:
    """生成 GCC 构建使用的 include 列表。

    Keil 工程如果使用 FreeRTOS，常见情况是 target 里选了 RVDS/ARMCC port。
    GCC 构建时不能直接消费 RVDS 的 `portmacro.h`，所以生成层只在外部 CMake 中
    把 include 路径映射到 FreeRTOS 自带 GCC port；原 Keil 工程保持不变。
    """

    includes: list[str] = []
    for item in target.includes:
        includes.append(_adapt_include_path(item))

    # 如果源文件里出现了 RVDS port.c，但 Keil include path 没写 GCC port，
    # 这里补充一次 GCC port 目录，避免 portable.h 继续拾取 RVDS 的 portmacro.h。
    for source in target.sources:
        gcc_port = _freertos_gcc_port_from_path(source.path)
        if gcc_port and gcc_port not in includes:
            includes.append(gcc_port)

    return _dedupe(includes)


def _adapt_source_path(path: str, target: KeilTargetModel) -> str | None:
    """把已知的编译器专用源码映射为 GCC 等价实现。"""

    if not _is_freertos_rvds_port(path):
        return path

    gcc_port = _freertos_gcc_port_from_path(path)
    if gcc_port and Path(gcc_port, "port.c").is_file():
        return gcc_port + "/port.c"

    # CubeMX/团队 BSP 有时单独提供 `Middlewares/FreeRTOS_port/port.c`，
    # 同时 Keil 源列表里仍保留 ARMCC/RVDS port。GCC 构建应使用项目自带
    # GCC port，并跳过 RVDS port，避免编译 ARMCC 内联汇编。
    if _has_project_freertos_port(target):
        return None

    return gcc_port + "/port.c" if gcc_port else path


def _adapt_include_path(path: str) -> str:
    """把已知的编译器专用 include 路径映射为 GCC 等价路径。"""

    if _is_freertos_rvds_port(path):
        return _freertos_gcc_port_from_path(path)
    return path


def _is_freertos_rvds_port(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        "/Freertos/portable/RVDS/ARM_CM4F" in normalized
        or "/FreeRTOS/portable/RVDS/ARM_CM4F" in normalized
        or "/FreeRTOS/Source/portable/RVDS/ARM_CM4F" in normalized
    )


def _freertos_gcc_port_from_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    for marker in (
        "/Freertos/portable/RVDS/ARM_CM4F",
        "/FreeRTOS/portable/RVDS/ARM_CM4F",
        "/FreeRTOS/Source/portable/RVDS/ARM_CM4F",
    ):
        if marker in normalized:
            return normalized.split(marker, 1)[0] + marker.replace("/RVDS/", "/GCC/")
    return ""


def _has_project_freertos_port(target: KeilTargetModel) -> bool:
    for source in target.sources:
        normalized = source.path.replace("\\", "/")
        if normalized.endswith("/Middlewares/FreeRTOS_port/port.c"):
            return True
    return False


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def needs_arm_math_compat(target: KeilTargetModel) -> bool:
    """判断是否需要 CMSIS-DSP 兼容源。

    早期样例工程使用了 Keil/ARMCC 的 `arm_cortexM4lf_math.lib`，外部 GCC 构建需要
    一个兼容入口。GD32 这个验证工程没有 CMSIS-DSP，若无条件加入反而会因为缺少
    `arm_math.h` 失败，所以这里按 define/library/source 证据启用。
    """

    if any(item.startswith("ARM_MATH_") for item in target.defines):
        return True
    if any("arm_cortex" in item.replace("\\", "/").lower() and item.lower().endswith(".lib") for item in target.libraries):
        return True
    return any("arm_math.h" in item.replace("\\", "/").lower() for item in target.includes)


def _compile_flags(target: KeilTargetModel) -> str:
    flags = [
        f"  -mcpu={target.core or 'cortex-m4'}",
        "  -mthumb",
    ]
    if target.fpu:
        flags.append(f"  -mfpu={target.fpu}")
    if target.float_abi:
        flags.append(f"  -mfloat-abi={target.float_abi}")
    return "\n".join(flags)


def _cmake_list(items: list[str]) -> str:
    return "\n".join(f'  "{_cmake_path(item)}"' for item in items)


def _cmake_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _path_key(path: str) -> str:
    return path.replace("\\", "/").lower()


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
