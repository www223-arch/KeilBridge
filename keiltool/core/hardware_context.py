from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .device_catalog import CatalogDevice, DeviceCatalog, load_embedded_catalog
from .device_import import load_user_catalog
from .openocd_backend import OpenOcdConfig
from .project_model import KeilTargetModel, MemoryRegion


@dataclass(frozen=True, slots=True)
class MemoryRange:
    origin: int
    size: int

    def __post_init__(self) -> None:
        if not 0 <= self.origin <= 0xFFFFFFFF:
            raise ValueError("Memory origin must fit in 32 bits.")
        if self.size <= 0 or self.origin + self.size > 0x1_0000_0000:
            raise ValueError("Memory size must define a positive 32-bit range.")


@dataclass(frozen=True, slots=True)
class HardwareSelection:
    project: Path | None = None
    target: str = ""
    device: str = ""
    vendor: str = ""
    openocd: str = ""
    scripts: str = ""
    target_cfg: str = ""
    logs_dir: Path | None = None

    def __post_init__(self) -> None:
        if bool(self.project) == bool(self.device.strip()):
            raise ValueError("Hardware selection requires exactly one project or device source.")

    @property
    def source(self) -> str:
        return "project" if self.project else "device"


@dataclass(frozen=True, slots=True)
class HardwareContext:
    source: str
    device: str
    target_name: str
    target: KeilTargetModel
    config: OpenOcdConfig
    flash: MemoryRange | None
    ram: MemoryRange | None
    logs_dir: Path
    workspace_root: Path
    facts: object


def resolve_hardware_context(selection: HardwareSelection) -> HardwareContext:
    # Importing this data-only module does not initialize Tk. It remains the
    # compatibility owner of the GUI facts while CLI adoption is introduced.
    from keiltool.gui.project_config import (
        facts_from_catalog_device,
        load_project_targets,
        resolve_target_facts,
    )

    if selection.project is not None:
        loaded = load_project_targets(selection.project)
        target = _pick_target(loaded.targets, selection.target)
        facts = resolve_target_facts(
            target,
            loaded.project_root,
            openocd_path=selection.openocd,
            scripts_dir=selection.scripts,
            target_override=selection.target_cfg,
        )
        workspace_root = loaded.project_root
    else:
        catalog_device = _lookup_catalog_device(selection.vendor, selection.device)
        facts = facts_from_catalog_device(
            catalog_device,
            openocd_path=selection.openocd,
            scripts_dir=selection.scripts,
            target_override=selection.target_cfg,
            default_log_dir=selection.logs_dir or "",
        )
        target = _catalog_target(catalog_device)
        workspace_root = Path.cwd()

    if not facts.ready:
        raise ValueError(facts.resolution_reason or "Hardware target is not ready.")
    config = OpenOcdConfig(
        executable=Path(facts.openocd_executable),
        scripts_dir=Path(facts.openocd_scripts) if facts.openocd_scripts else None,
        interface_cfg=facts.interface_cfg,
        target_cfg=facts.target_cfg,
    )
    flash = (
        _range(facts.flash_origin, facts.flash_size)
        if facts.flash_range_complete
        else None
    )
    ram = _range(facts.ram_origin, facts.ram_size)
    return HardwareContext(
        source=selection.source,
        device=facts.device,
        target_name=facts.target_name,
        target=target,
        config=config,
        flash=flash,
        ram=ram,
        logs_dir=Path(selection.logs_dir or facts.default_log_dir),
        workspace_root=workspace_root,
        facts=facts,
    )


def _pick_target(targets: tuple[KeilTargetModel, ...], requested: str) -> KeilTargetModel:
    if not targets:
        raise ValueError("Keil project does not contain a target.")
    if not requested:
        return targets[0]
    target = next((item for item in targets if item.name == requested), None)
    if target is None:
        raise ValueError(f"Keil project does not contain target: {requested}")
    return target


def _lookup_catalog_device(vendor: str, device: str) -> CatalogDevice:
    from keiltool.gui.settings import default_devices_path

    embedded = load_embedded_catalog()
    user = load_user_catalog(default_devices_path())
    catalog = DeviceCatalog(embedded=embedded.devices, user=user.devices)
    selected = catalog.lookup(vendor, device) if vendor else catalog.lookup_any_vendor(device)
    if selected is None:
        qualifier = f"{vendor}::{device}" if vendor else device
        raise ValueError(f"Device catalog does not contain one exact match for: {qualifier}")
    return selected


def _catalog_target(device: CatalogDevice) -> KeilTargetModel:
    return KeilTargetModel(
        name=device.device,
        device=device.device,
        vendor=device.vendor,
        family=device.family,
        core=device.core,
        fpu=device.fpu,
        memory=[
            MemoryRegion(item.name, f"0x{item.start:08X}", f"0x{item.size:X}")
            for item in device.memory
        ],
    )


def _range(origin: int | None, size: int | None) -> MemoryRange | None:
    if origin is None or size is None or size <= 0:
        return None
    return MemoryRange(origin, size)


__all__ = [
    "HardwareContext",
    "HardwareSelection",
    "MemoryRange",
    "resolve_hardware_context",
]
