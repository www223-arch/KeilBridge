from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .device_database import lookup_device
from .device_inference import infer_core, infer_family, infer_fpu, infer_vendor, parse_memory_regions
from .path_resolver import infer_project_root, normalize_path, resolve_keil_path
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


def _parse_files(target: ET.Element, base_dir: Path) -> tuple[list[KeilFile], list[str], list[str]]:
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
            resolved = resolve_keil_path(base_dir, raw_path)
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

    model = KeilProjectModel(
        project_file=normalize_path(str(project_path)),
        keil_project_dir=normalize_path(str(base_dir)),
        inferred_project_root=normalize_path(str(infer_project_root(project_path))),
    )

    for target in root.findall(".//Target"):
        target_name = _text(target.find("TargetName"))
        if not target_name:
            continue

        cpu = _target_option_text(target, "Cpu")
        device = _target_option_text(target, "Device")
        define_text = _target_option_text(target, "Define")
        include_text = _target_option_text(target, "IncludePath")
        scatter_text = _target_option_text(target, "ScatterFile")
        c99_mode = _target_option_text(target, "C99Mode")
        optimization = _target_option_text(target, "Optimization")
        if not optimization:
            optimization = _target_option_text(target, "OptimizationLevel")

        sources, libraries, startup_files = _parse_files(target, base_dir)

        # 设备数据库是长期维护 STM/GD 全系列的基础；Keil Cpu 字段只作为兜底。
        device_info = lookup_device(device)
        vendor = device_info.vendor or infer_vendor(device)
        family = device_info.family or infer_family(device)
        core = device_info.core or infer_core(cpu, device)
        inferred_fpu, inferred_float_abi = infer_fpu(cpu, core)
        fpu = device_info.fpu or inferred_fpu
        float_abi = device_info.float_abi or inferred_float_abi
        memory = device_info.memory or parse_memory_regions(cpu)

        scatter_file = resolve_keil_path(base_dir, scatter_text) if scatter_text else ""
        scatter_candidates = [] if scatter_file else discover_scatter_files(base_dir, target_name)

        includes = [
            resolve_keil_path(base_dir, item)
            for item in _split_semicolon(include_text)
        ]

        model.targets.append(
            KeilTargetModel(
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
                device_info=device_info,
                c_standard="c99" if c99_mode == "1" else "c11",
                optimization=optimization,
            )
        )

    return model
