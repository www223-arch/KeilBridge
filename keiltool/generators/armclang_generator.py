from __future__ import annotations

from pathlib import Path

from keiltool.core.project_model import KeilTargetModel, MemoryRegion


def generate_armclang_toolchain(target: KeilTargetModel) -> str:
    """生成 ArmClang CMake toolchain 文件。

    这一层只描述“如何找到 armclang/armlink/armasm/fromelf”，不把用户机器上的绝对路径
    写死进 CMakeLists。换电脑时优先设置 `ARMCLANG_ROOT`，也可以把 Keil ARMCLANG/bin
    加到 PATH。这样 generated 工作区可以复制或重新生成，路径污染最小。
    """

    processor = target.core or "cortex-m4"
    return f"""set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR {processor})
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
cmake_policy(SET CMP0123 NEW)

if(DEFINED ENV{{ARMCLANG_ROOT}})
  file(TO_CMAKE_PATH "$ENV{{ARMCLANG_ROOT}}" ARMCLANG_ROOT)
  if(EXISTS "${{ARMCLANG_ROOT}}/bin/armclang.exe")
    set(ARMCLANG_BIN "${{ARMCLANG_ROOT}}/bin")
  else()
    set(ARMCLANG_BIN "${{ARMCLANG_ROOT}}")
  endif()
  set(TOOLCHAIN_SUFFIX ".exe")
else()
  set(ARMCLANG_BIN "")
  set(TOOLCHAIN_SUFFIX "")
endif()

if(ARMCLANG_BIN)
  if(EXISTS "${{ARMCLANG_BIN}}/armclang_kb.exe")
    set(ARMCLANG_COMPILER "${{ARMCLANG_BIN}}/armclang_kb.exe")
  else()
    set(ARMCLANG_COMPILER "${{ARMCLANG_BIN}}/armclang${{TOOLCHAIN_SUFFIX}}")
  endif()
  set(CMAKE_C_COMPILER "${{ARMCLANG_COMPILER}}" CACHE FILEPATH "C compiler" FORCE)
  set(CMAKE_CXX_COMPILER "${{ARMCLANG_COMPILER}}" CACHE FILEPATH "CXX compiler" FORCE)
  set(CMAKE_ASM_COMPILER "${{ARMCLANG_BIN}}/armasm${{TOOLCHAIN_SUFFIX}}" CACHE FILEPATH "ASM compiler" FORCE)
  set(CMAKE_LINKER "${{ARMCLANG_BIN}}/armlink${{TOOLCHAIN_SUFFIX}}" CACHE FILEPATH "linker" FORCE)
  set(CMAKE_OBJCOPY "${{ARMCLANG_BIN}}/fromelf${{TOOLCHAIN_SUFFIX}}" CACHE FILEPATH "fromelf" FORCE)
else()
  set(CMAKE_C_COMPILER "armclang" CACHE FILEPATH "C compiler" FORCE)
  set(CMAKE_CXX_COMPILER "armclang" CACHE FILEPATH "CXX compiler" FORCE)
  set(CMAKE_ASM_COMPILER "armasm" CACHE FILEPATH "ASM compiler" FORCE)
  set(CMAKE_LINKER "armlink" CACHE FILEPATH "linker" FORCE)
  set(CMAKE_OBJCOPY "fromelf" CACHE FILEPATH "fromelf" FORCE)
endif()

set(CMAKE_EXECUTABLE_SUFFIX_C ".axf")
set(CMAKE_EXECUTABLE_SUFFIX_CXX ".axf")
set(CMAKE_EXECUTABLE_SUFFIX_ASM ".axf")

set(CMAKE_C_LINK_EXECUTABLE "<CMAKE_LINKER> <LINK_FLAGS> <OBJECTS> <LINK_LIBRARIES> --output <TARGET>")
set(CMAKE_CXX_LINK_EXECUTABLE "<CMAKE_LINKER> <LINK_FLAGS> <OBJECTS> <LINK_LIBRARIES> --output <TARGET>")
"""


def generate_armclang_cmakelists(target: KeilTargetModel, scatter_file: Path) -> str:
    """生成 ArmClang/ArmLink 试验性 CMakeLists。

    ArmClang 路线的第一目标是“尽量贴近 Keil 原语义”，因此这里复用 Keil 源文件列表、
    include、define、startup 和 scatter，而不是生成 GNU ld 或 GCC startup。它仍然是
    零侵入式：所有文件只引用原工程路径，不修改 `.uvprojx/.sct/.c/.h`。
    """

    project_name = _sanitize_name(target.name)
    sources = _cmake_list(_source_list(target))
    includes = _cmake_list(target.includes)
    defines = _cmake_list(target.defines)
    libraries = _cmake_list(target.libraries)
    c_flags = _armclang_c_flags(target)
    linker_flags = _armlink_flags(target, scatter_file)

    return f"""cmake_minimum_required(VERSION 3.20)
cmake_policy(SET CMP0123 NEW)

set(CMAKE_TOOLCHAIN_FILE "${{CMAKE_CURRENT_LIST_DIR}}/cmake/armclang.cmake" CACHE FILEPATH "Toolchain")

project({project_name}_armclang C CXX ASM)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(TARGET_NAME "{project_name}")
set(SCATTER_FILE "{_cmake_path(scatter_file)}")

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
{c_flags}
)

target_link_options(${{TARGET_NAME}} PRIVATE
{linker_flags}
)

target_link_libraries(${{TARGET_NAME}} PRIVATE
{libraries}
)

add_custom_command(TARGET ${{TARGET_NAME}} POST_BUILD
  COMMAND ${{CMAKE_OBJCOPY}} --i32 --output ${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.hex $<TARGET_FILE:${{TARGET_NAME}}>
  COMMAND ${{CMAKE_OBJCOPY}} --bin --output ${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.bin $<TARGET_FILE:${{TARGET_NAME}}>
  COMMAND ${{CMAKE_OBJCOPY}} --text -z --output ${{CMAKE_BINARY_DIR}}/${{TARGET_NAME}}.size.txt $<TARGET_FILE:${{TARGET_NAME}}>
  COMMENT "Generating HEX/BIN and ArmClang size report"
)
"""


def generate_armclang_presets() -> str:
    return """{
  "version": 3,
  "configurePresets": [
    {
      "name": "armclang-debug",
      "displayName": "ArmClang Debug",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/../../build/armclang-debug",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug"
      }
    }
  ],
  "buildPresets": [
    {
      "name": "armclang-debug",
      "configurePreset": "armclang-debug"
    }
  ]
}
"""


def generate_armclang_scatter_from_memory(target: KeilTargetModel, memory: list[MemoryRegion]) -> str:
    """在 Keil target 没显式配置 scatter 时，生成一个最小 ArmLink scatter。

    这只是兜底模板，复杂工程仍应优先使用原 `.sct`。生成文件放在 `.keilbridge` 内，
    不改变 Keil 工程。
    """

    flash = _first_region(memory, "FLASH")
    ram = _first_region(memory, "RAM")
    if not flash or not ram:
        raise ValueError("ArmClang scatter generation requires FLASH and RAM memory regions.")
    return f"""LR_IROM1 {flash.origin} {flash.length}  {{
  ER_IROM1 {flash.origin} {flash.length}  {{
    *.o (RESET, +First)
    *(InRoot$$Sections)
    .ANY (+RO)
  }}
  RW_IRAM1 {ram.origin} {ram.length}  {{
    .ANY (+RW +ZI)
  }}
}}
"""


def _source_list(target: KeilTargetModel) -> list[str]:
    sources: list[str] = []
    has_project_freertos_port = _has_project_freertos_port(target)
    for source in target.sources:
        if has_project_freertos_port and _is_freertos_rvds_port(source.path):
            continue
        sources.append(source.path)
    return sources


def _is_freertos_rvds_port(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        "/Freertos/portable/RVDS/ARM_CM4F" in normalized
        or "/FreeRTOS/portable/RVDS/ARM_CM4F" in normalized
        or "/FreeRTOS/Source/portable/RVDS/ARM_CM4F" in normalized
    )


def _has_project_freertos_port(target: KeilTargetModel) -> bool:
    for source in target.sources:
        normalized = source.path.replace("\\", "/")
        if normalized.endswith("/Middlewares/FreeRTOS_port/port.c"):
            return True
    return False


def _armclang_c_flags(target: KeilTargetModel) -> str:
    armasm_cpu = _armasm_cpu(target)
    flags = [
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:--target=arm-arm-none-eabi>"',
        f'  "$<$<COMPILE_LANGUAGE:C,CXX>:-mcpu={target.core or "cortex-m4"}>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-mthumb>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-ffunction-sections>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-fdata-sections>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-fshort-wchar>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-fshort-enums>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-fno-unwind-tables>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-fno-asynchronous-unwind-tables>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-g>"',
        '  "$<$<COMPILE_LANGUAGE:C,CXX>:-O0>"',
        '  "$<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions>"',
        '  "$<$<COMPILE_LANGUAGE:CXX>:-std=c++14>"',
        f'  "$<$<COMPILE_LANGUAGE:ASM>:--cpu={armasm_cpu}>"',
    ]
    if target.fpu:
        flags.append(f'  "$<$<COMPILE_LANGUAGE:C,CXX>:-mfpu={target.fpu}>"')
    if target.float_abi:
        flags.append(f'  "$<$<COMPILE_LANGUAGE:C,CXX>:-mfloat-abi={target.float_abi}>"')
    return "\n".join(flags)


def _armasm_cpu(target: KeilTargetModel) -> str:
    """把 Cortex-M 内核模型映射成 Keil ARMASM 可接受的 --cpu 名称。"""

    core = (target.core or "cortex-m4").lower()
    mapping = {
        "cortex-m0": "Cortex-M0",
        "cortex-m0plus": "Cortex-M0plus",
        "cortex-m3": "Cortex-M3",
        "cortex-m4": "Cortex-M4",
        "cortex-m7": "Cortex-M7",
        "cortex-m23": "Cortex-M23",
        "cortex-m33": "Cortex-M33",
    }
    cpu = mapping.get(core, "Cortex-M4")
    if target.fpu and core in {"cortex-m4", "cortex-m7", "cortex-m33"}:
        return f"{cpu}.fp"
    return cpu


def _armlink_flags(target: KeilTargetModel, scatter_file: Path) -> str:
    return "\n".join(
        [
            f'  "--scatter={_cmake_path(scatter_file)}"',
            '  "--map"',
            '  "--info=sizes,totals,unused,veneers"',
            '  "--entry=Reset_Handler"',
        ]
    )


def _first_region(memory: list[MemoryRegion], name: str) -> MemoryRegion | None:
    for region in memory:
        if region.name.upper() == name:
            return region
    return None


def _cmake_list(items: list[str | Path]) -> str:
    return "\n".join(f'  "{_cmake_path(item)}"' for item in items)


def _cmake_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
