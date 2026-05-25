from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class KeilFile:
    path: str
    kind: str
    group: str = ""


@dataclass(slots=True)
class MemoryRegion:
    """统一描述芯片存储区，后续 linker generator 只消费这个抽象。"""

    name: str
    origin: str
    length: str


@dataclass(slots=True)
class DeviceInfo:
    """设备数据库条目。

    Keil 的 Cpu 字段有时能推导出内存和内核，但它不是稳定的公共接口。
    所以这里单独保留数据库命中的信息，后续可以逐步扩展到 STM/GD 全系列。
    """

    matched: bool = False
    device: str = ""
    vendor: str = ""
    family: str = ""
    core: str = ""
    fpu: str = ""
    float_abi: str = ""
    openocd_target: str = ""
    memory: list[MemoryRegion] = field(default_factory=list)


@dataclass(slots=True)
class KeilTargetModel:
    """单个 Keil Target 的归一化模型。

    Keil 一个 `.uvprojx` 里可以包含多个 Target。CMake 生成时必须先明确选中
    哪个 Target，所以这里不把多个 Target 混在一起。
    """

    name: str
    device: str = ""
    vendor: str = ""
    family: str = ""
    core: str = ""
    fpu: str = ""
    float_abi: str = ""
    cpu: str = ""
    memory: list[MemoryRegion] = field(default_factory=list)
    sources: list[KeilFile] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    startup_files: list[str] = field(default_factory=list)
    scatter_file: str = ""
    scatter_candidates: list[str] = field(default_factory=list)
    device_info: DeviceInfo = field(default_factory=DeviceInfo)
    c_standard: str = "c11"
    optimization: str = ""


@dataclass(slots=True)
class KeilProjectModel:
    """整个 Keil 工程的归一化模型。"""

    project_file: str
    keil_project_dir: str
    inferred_project_root: str
    targets: list[KeilTargetModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def project_path(self) -> Path:
        return Path(self.project_file)
