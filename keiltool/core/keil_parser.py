from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .device_database import lookup_device
from .device_override import apply_device_override
from .device_inference import infer_core, infer_family, infer_fpu, infer_vendor, parse_memory_regions
from .keil_option_parser import parse_flash_algorithm, parse_uvoptx_debug_options
from .path_resolver import infer_project_root, normalize_path, resolve_keil_path
from .project_classifier import classify_project
from .project_model import KeilFile, KeilProjectModel, KeilTargetModel
from .scatter import discover_scatter_files

SOURCE_SUFFIXES = {".c", ".cpp", ".cxx", ".cc", ".s", ".S", ".asm"}
LIB_SUFFIXES = {".lib", ".a"}
STARTUP_RE = re.compile(r"(^|[/\\])startup_[^/\\]+\.(s|S|asm)$", re.IGNORECASE)


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _split_defines(value: str) -> list[str]:
    items: list[str] = []
    for item in re.split(r"[,;\s]+", value):
        item = item.strip()
        if item:
            items.append(item)
    return items


def _file_kind(path: str) -> str:
    suffix = Path(path).suffix
    if suffix in LIB_SUFFIXES:
        return "library"
    if STARTUP_RE.search(path):
        return "startup"
    if suffix.lower() == ".c":
        return "c"
    if suffix.lower() in {".cpp", ".cxx", ".cc"}:
        return "cpp"
    if suffix.lower() in {".s", ".asm"}:
        return "asm"
    return "other"


def _target_option_text(target: ET.Element, tag: str) -> str:
    values = [_text(elem) for elem in target.findall(f".//{tag}")]
    values = [value for value in values if value]
    return values[-1] if values else ""


def _compiler_option_text(target: ET.Element, tag: str) -> str:
    """读取当前 target 的 C/C++ 编译器选项。

    Keil 的同名字段会同时出现在 C 编译器 `Cads`、汇编器 `Aads` 以及单文件覆盖配置里。
    例如 `IncludePath` 在 CubeMX 工程中常见为：Cads 里是完整 C include，Aads 里只有
    `Core/Inc`。如果简单取最后一个同名字段，就会把完整 include 覆盖成汇编 include，
    进而导致 `stm32f4xx_hal.h`、`FreeRTOS.h` 等头文件找不到。
    """

    compiler_value = _text(target.find(f"./TargetOption/TargetArmAds/Cads/VariousControls/{tag}"))
    if compiler_value:
        return compiler_value
    return _target_option_text(target, tag)


def _parse_files(target: ET.Element, base_dir: Path, project_root: Path) -> tuple[list[KeilFile], list[str], list[str]]:
    """解析 Keil 文件分组。

    Keil 的 FileType 并不总是可靠，跨版本也可能变化。因此这里以路径后缀和
    startup 命名规则为主，保留 group 名称用于后续诊断和 CMake source_group。
    """

    sources: list[KeilFile] = []
    libraries: list[str] = []
    startup_files: list[str] = []

    for group in target.findall(".//Group"):
        group_name = _text(group.find("GroupName"))
        for file_elem in group.findall(".//File"):
            raw_path = _text(file_elem.find("FilePath"))
            if not raw_path:
                continue
            kind = _file_kind(raw_path)
            resolved = resolve_keil_path(base_dir, raw_path, project_root)
            suffix = Path(raw_path).suffix

            if suffix in SOURCE_SUFFIXES:
                sources.append(KeilFile(path=resolved, kind=kind, group=group_name))
            elif suffix in LIB_SUFFIXES:
                libraries.append(resolved)

            if kind == "startup":
                startup_files.append(resolved)

    return sources, libraries, startup_files


def parse_uvprojx(uvprojx_path: str | Path) -> KeilProjectModel:
    """解析 `.uvprojx` 并返回工具内部模型。

    这个函数只读 Keil 工程，不做任何写入，保证 0 侵入。路径统一解析成绝对路径，
    是为了后续生成的 CMake 可以放在任意外部目录里运行。
    """

    project_path = Path(uvprojx_path).resolve()
    base_dir = project_path.parent
    tree = ET.parse(project_path)
    root = tree.getroot()

    project_root = infer_project_root(project_path)
    model = KeilProjectModel(
        project_file=normalize_path(str(project_path)),
        keil_project_dir=normalize_path(str(base_dir)),
        inferred_project_root=normalize_path(str(project_root)),
    )

    for target in root.findall(".//Target"):
        target_name = _text(target.find("TargetName"))
        if not target_name:
            continue

        cpu = _target_option_text(target, "Cpu")
        device = _target_option_text(target, "Device")
        flash_driver = _target_option_text(target, "FlashDriverDll")
        define_text = _compiler_option_text(target, "Define")
        include_text = _compiler_option_text(target, "IncludePath")
        scatter_text = _target_option_text(target, "ScatterFile")
        c99_mode = _target_option_text(target, "C99Mode")
        optimization = _target_option_text(target, "Optimization")
        if not optimization:
            optimization = _target_option_text(target, "OptimizationLevel")

        sources, libraries, startup_files = _parse_files(target, base_dir, project_root)

        # 设备数据库是长期维护 STM/GD 全系列的基础；Keil Cpu 字段只作为兜底。
        device_info = lookup_device(device)
        vendor = device_info.vendor or infer_vendor(device)
        family = device_info.family or infer_family(device)
        core = infer_core(cpu, device) or device_info.core
        inferred_fpu, inferred_float_abi = infer_fpu(cpu, core)
        # Keil 的 Cpu 字段来自当前 target，通常比 seed 设备库更贴近实际工程配置。
        # 如果 Cpu 明确写了 FPU，而设备库条目还没有完善 FPU 信息，则优先采用 Cpu 推导结果。
        fpu = inferred_fpu or device_info.fpu
        float_abi = inferred_float_abi if inferred_fpu else (device_info.float_abi or inferred_float_abi)
        memory = parse_memory_regions(cpu) or device_info.memory

        scatter_file = resolve_keil_path(base_dir, scatter_text, project_root) if scatter_text else ""
        scatter_candidates = [] if scatter_file else discover_scatter_files(base_dir, target_name)

        includes = [
            resolve_keil_path(base_dir, item, project_root)
            for item in _split_semicolon(include_text)
        ]
        features = classify_project(str(project_root), sources, includes, _split_defines(define_text))
        debug_options = parse_uvoptx_debug_options(project_path.with_suffix(".uvoptx"), target_name)
        flash_algorithm = debug_options.flash_algorithm or parse_flash_algorithm(flash_driver)

        target_model = KeilTargetModel(
            name=target_name,
            device=device,
            vendor=vendor,
            family=family,
            core=core,
            fpu=fpu,
            float_abi=float_abi,
            cpu=cpu,
            memory=memory,
            sources=sources,
            includes=includes,
            defines=_split_defines(define_text),
            libraries=libraries,
            startup_files=startup_files,
            scatter_file=scatter_file,
            scatter_candidates=scatter_candidates,
            debug_probe=debug_options.probe,
            keil_debug_dll=debug_options.debug_dll,
            flash_algorithm=flash_algorithm,
            device_info=device_info,
            features=features,
            c_standard="c99" if c99_mode == "1" else "c11",
            optimization=optimization,
        )
        apply_device_override(target_model, project_root)
        model.targets.append(target_model)

    return model
