from __future__ import annotations

from pathlib import Path

from .path_resolver import normalize_path
from .project_model import KeilFile, ProjectFeatures


def classify_project(project_root: str, sources: list[KeilFile], includes: list[str], defines: list[str]) -> ProjectFeatures:
    """识别工程形态。

    这里只做保守识别：通过目录、文件名、宏和 include 路径判断工程使用了哪些
    框架或中间件。识别结果用于报告和后续 adapter，不会自动改用户源码。
    """

    root = Path(project_root)
    evidence: list[str] = []
    rtos: list[str] = []
    middleware: list[str] = []
    framework = "unknown"
    generated_by = ""

    source_paths = [source.path.lower().replace("\\", "/") for source in sources]
    include_paths = [item.lower().replace("\\", "/") for item in includes]
    defines_set = set(defines)

    ioc_files = list(root.glob("*.ioc"))
    if ioc_files:
        generated_by = "stm32cubemx"
        evidence.extend(normalize_path(str(path)) for path in ioc_files)

    if any("stm32" in path and "hal_driver" in path for path in [*source_paths, *include_paths]) or "USE_HAL_DRIVER" in defines_set:
        framework = "stm32_hal"
        evidence.append("STM32 HAL driver path or USE_HAL_DRIVER define")
    elif any("stm32" in path and ("stdperiph" in path or "standard_peripheral" in path) for path in [*source_paths, *include_paths]):
        framework = "stm32_stdperiph"
        evidence.append("STM32 standard peripheral path")
    elif any("gd32" in path and ("standard_peripheral" in path or "stdperiph" in path or "firmware" in path) for path in [*source_paths, *include_paths]):
        framework = "gd32_stdperiph"
        evidence.append("GD32 standard peripheral path")
    elif any("/gd32" in path or "\\gd32" in path for path in [*source_paths, *include_paths]):
        framework = "gd32_baremetal_or_vendor_lib"
        evidence.append("GD32 source/include path")

    if _contains_any(source_paths, include_paths, ["freertos", "freertosconfig.h"]):
        rtos.append("freertos")
        evidence.append("FreeRTOS path or FreeRTOSConfig.h")
    if _contains_any(source_paths, include_paths, ["rt-thread", "rtthread", "rtconfig.h"]):
        rtos.append("rt-thread")
        evidence.append("RT-Thread path or rtconfig.h")
    if _contains_any(source_paths, include_paths, ["threadx", "tx_api.h"]):
        rtos.append("threadx")
        evidence.append("ThreadX path or tx_api.h")
    if _contains_any(source_paths, include_paths, ["ucos", "os_cfg.h"]):
        rtos.append("ucos")
        evidence.append("uC/OS path or os_cfg.h")

    for name, tokens in {
        "lwip": ["lwip"],
        "fatfs": ["fatfs", "ff.c", "ff.h"],
        "usb": ["usb_device", "usb_host", "usbd_", "usbh_"],
        "cmsis_dsp": ["arm_math.h", "cmsis/dsp", "dsp_lib"],
        "segger_rtt": ["segger_rtt"],
    }.items():
        if _contains_any(source_paths, include_paths, tokens):
            middleware.append(name)

    return ProjectFeatures(
        framework=framework,
        generated_by=generated_by,
        rtos=sorted(set(rtos)),
        middleware=sorted(set(middleware)),
        evidence=evidence,
    )


def _contains_any(source_paths: list[str], include_paths: list[str], tokens: list[str]) -> bool:
    haystack = [*source_paths, *include_paths]
    return any(token in item for item in haystack for token in tokens)
