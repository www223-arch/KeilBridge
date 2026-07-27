from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import shutil

from keiltool.core.device_catalog import (
    CatalogDevice,
    CatalogMemory,
    DeviceCatalog,
    load_embedded_catalog,
)
from keiltool.core.device_import import load_user_catalog
from keiltool.core.keil_parser import parse_uvprojx
from keiltool.core.openocd_target_resolver import resolve_openocd_target
from keiltool.core.project_model import KeilTargetModel, MemoryRegion
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts


INTERFACE_CFG = "interface/stlink.cfg"


@dataclass(frozen=True, slots=True)
class LoadedProjectTargets:
    project_root: Path
    targets: tuple[KeilTargetModel, ...]


@dataclass(frozen=True, slots=True)
class ProjectTargetFacts:
    target_name: str
    device: str
    flash_summary: str
    flash_origin: int | None
    flash_size: int | None
    flash_range_complete: bool
    flash_range_source: str
    ram_summary: str
    ram_origin: int | None
    ram_size: int | None
    openocd_executable: str
    openocd_scripts: str
    interface_cfg: str
    target_cfg: str
    resolution_status: str
    resolution_reason: str
    default_log_dir: str
    ready: bool

    @property
    def scripts_dir(self) -> str:
        return self.openocd_scripts

    @property
    def main_ram_origin(self) -> int | None:
        return self.ram_origin

    @property
    def main_ram_size(self) -> int | None:
        return self.ram_size


def load_project_targets(project_path: str | Path) -> LoadedProjectTargets:
    """Parse a Keil project and retain its root with its selectable Targets."""

    project = parse_uvprojx(project_path)
    return LoadedProjectTargets(Path(project.inferred_project_root), tuple(project.targets))


def resolve_target_facts(
    target: KeilTargetModel,
    project_root: str | Path,
    *,
    openocd_path: str | Path = "",
    scripts_dir: str | Path = "",
    target_override: str | Path = "",
    catalog_device: CatalogDevice | None = None,
) -> ProjectTargetFacts:
    """Resolve GUI facts while refusing every unverified OpenOCD target cfg."""

    executable = str(openocd_path) if openocd_path else find_openocd()
    scripts = str(scripts_dir) if scripts_dir else find_openocd_scripts(executable)
    target_cfg, status, reason = _resolve_target_cfg(target, scripts, target_override)
    readiness_diagnostics = _validate_hardware_paths(executable, scripts, INTERFACE_CFG, target_cfg)
    resolution_reason = "; ".join(item for item in (reason, *readiness_diagnostics) if item)
    flash_regions = _regions_named(target.memory, "FLASH")
    ram_regions = _regions_named(target.memory, "RAM")
    project_flash = flash_regions[0] if flash_regions else None
    catalog_match = catalog_device or _lookup_target_catalog_device(target)
    catalog_flash_regions = _catalog_flash_regions(catalog_match) if catalog_match else []
    main_catalog_flash = catalog_flash_regions[0] if catalog_flash_regions else None
    main_ram = ram_regions[0] if ram_regions else None
    if main_catalog_flash is not None:
        flash_summary = f"芯片 {_catalog_summary(catalog_flash_regions)}"
        project_summary = _summary(flash_regions)
        if project_summary and (
            _integer_value(project_flash.origin) != main_catalog_flash.start
            or _size_value(project_flash.length) != main_catalog_flash.size
        ):
            flash_summary += f" | 工程 {project_summary}"
        flash_origin = main_catalog_flash.start
        flash_size = main_catalog_flash.size
        flash_range_complete = True
        flash_range_source = "device_catalog"
    else:
        flash_summary = f"工程范围（未确认整片）: {_summary(flash_regions)}"
        flash_origin = _integer_value(project_flash.origin) if project_flash else None
        flash_size = _size_value(project_flash.length) if project_flash else None
        flash_range_complete = False
        flash_range_source = "keil_irom"
    return ProjectTargetFacts(
        target_name=target.name,
        device=target.device,
        flash_summary=flash_summary,
        flash_origin=flash_origin,
        flash_size=flash_size,
        flash_range_complete=flash_range_complete,
        flash_range_source=flash_range_source,
        ram_summary=_summary(ram_regions),
        ram_origin=_integer_value(main_ram.origin) if main_ram else None,
        ram_size=_size_value(main_ram.length) if main_ram else None,
        openocd_executable=executable,
        openocd_scripts=scripts,
        interface_cfg=INTERFACE_CFG,
        target_cfg=target_cfg,
        resolution_status=status,
        resolution_reason=resolution_reason,
        default_log_dir=str(Path(project_root) / ".keilbridge" / "logs"),
        ready=status.endswith("_verified") and bool(target_cfg) and not readiness_diagnostics,
    )


def facts_from_catalog_device(
    device: CatalogDevice,
    *,
    openocd_path: str | Path = "",
    scripts_dir: str | Path = "",
    target_override: str | Path = "",
    default_log_dir: str | Path = "",
) -> ProjectTargetFacts:
    """Resolve exact catalog facts without requiring a Keil project."""

    executable = str(openocd_path) if openocd_path else find_openocd()
    scripts = str(scripts_dir) if scripts_dir else find_openocd_scripts(executable)
    override_text = str(target_override).strip()
    if override_text:
        target_cfg, status, reason = _resolve_override(override_text, scripts)
    elif device.openocd_target:
        target_cfg, override_status, reason = _resolve_override(device.openocd_target, scripts)
        status = "catalog_verified" if override_status == "override_verified" else f"catalog_{override_status}"
        reason = reason.replace(
            "OpenOCD target override",
            "Device catalog OpenOCD target mapping",
        )
    else:
        target_cfg = ""
        status = "catalog_unresolved"
        reason = (
            f"{device.device} has no explicit OpenOCD target mapping; "
            "select a verified target override to enable hardware actions."
        )

    readiness_diagnostics = _validate_hardware_paths(executable, scripts, INTERFACE_CFG, target_cfg)
    flash_regions = [
        item
        for item in device.memory
        if "x" in item.access.lower() and "w" not in item.access.lower()
    ]
    ram_regions = [item for item in device.memory if "w" in item.access.lower()]
    ordered_flash = sorted(
        flash_regions,
        key=lambda item: (not item.startup, not item.default, item.start),
    )
    ordered_ram = sorted(ram_regions, key=lambda item: (not item.default, item.start))
    main_flash = ordered_flash[0] if ordered_flash else None
    main_ram = ordered_ram[0] if ordered_ram else None
    informational = () if main_ram else ("Device catalog does not provide writable RAM for automatic RTT scanning.",)
    resolution_reason = "; ".join(
        item for item in (reason, *readiness_diagnostics, *informational) if item
    )
    return ProjectTargetFacts(
        target_name="",
        device=device.device,
        flash_summary=_catalog_summary(flash_regions),
        flash_origin=main_flash.start if main_flash else None,
        flash_size=main_flash.size if main_flash else None,
        flash_range_complete=main_flash is not None,
        flash_range_source="device_catalog" if main_flash else "unresolved",
        ram_summary=_catalog_summary(ram_regions),
        ram_origin=main_ram.start if main_ram else None,
        ram_size=main_ram.size if main_ram else None,
        openocd_executable=executable,
        openocd_scripts=scripts,
        interface_cfg=INTERFACE_CFG,
        target_cfg=target_cfg,
        resolution_status=status,
        resolution_reason=resolution_reason,
        default_log_dir=str(default_log_dir or _default_catalog_log_dir()),
        ready=status.endswith("_verified") and bool(target_cfg) and not readiness_diagnostics,
    )


def _resolve_target_cfg(target: KeilTargetModel, scripts_dir: str, override: str | Path) -> tuple[str, str, str]:
    override_text = str(override).strip()
    if override_text:
        return _resolve_override(override_text, scripts_dir)

    resolution = resolve_openocd_target(target, scripts_dir)
    if resolution.status.endswith("_verified") and resolution.target_cfg:
        return resolution.target_cfg, resolution.status, resolution.reason
    return "", resolution.status, resolution.reason


def _resolve_override(override: str, scripts_dir: str) -> tuple[str, str, str]:
    candidate = Path(override).expanduser()
    if candidate.suffix.lower() != ".cfg":
        return "", "override_invalid", "OpenOCD target override must be a .cfg file."
    if candidate.is_absolute():
        if candidate.is_file():
            return str(candidate), "override_verified", "OpenOCD target override was verified."
        return "", "override_missing", f"OpenOCD target override was not found: {candidate}"
    if not scripts_dir:
        return "", "override_unverified", "OpenOCD scripts directory is required for a relative target override."

    scripts = Path(scripts_dir)
    try:
        resolved = (scripts / candidate).resolve()
        resolved.relative_to(scripts.resolve())
    except ValueError:
        return "", "override_invalid", "Relative OpenOCD target override must remain under the scripts directory."
    if resolved.is_file():
        return candidate.as_posix(), "override_verified", "OpenOCD target override was verified."
    return "", "override_missing", f"OpenOCD target override was not found: {resolved}"


def _validate_hardware_paths(
    executable: str,
    scripts_dir: str,
    interface_cfg: str,
    target_cfg: str,
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    executable_path = Path(executable).expanduser()
    if not executable_path.is_file() and not shutil.which(executable):
        diagnostics.append(f"OpenOCD executable was not found: {executable}")

    scripts_path = Path(scripts_dir).expanduser() if scripts_dir else None
    if scripts_path is None or not scripts_path.is_dir():
        diagnostics.append(f"OpenOCD scripts directory was not found: {scripts_dir or '(empty)'}")
        return tuple(diagnostics)

    interface_path = Path(interface_cfg).expanduser()
    if not interface_path.is_absolute():
        interface_path = scripts_path / interface_path
    if not interface_path.is_file():
        diagnostics.append(f"OpenOCD interface cfg was not found: {interface_path}")

    if target_cfg:
        target_path = Path(target_cfg).expanduser()
        if not target_path.is_absolute():
            target_path = scripts_path / target_path
        if not target_path.is_file():
            diagnostics.append(f"OpenOCD target cfg was not found: {target_path}")
    else:
        diagnostics.append("OpenOCD target cfg is not resolved.")
    return tuple(diagnostics)


def _regions_named(regions: list[MemoryRegion], name: str) -> list[MemoryRegion]:
    return [region for region in regions if region.name.upper() == name]


def _summary(regions: list[MemoryRegion]) -> str:
    return ", ".join(f"{region.name}: {region.origin} ({region.length})" for region in regions)


def _catalog_summary(regions: list[CatalogMemory]) -> str:
    return ", ".join(
        f"{region.name}: 0x{region.start:08X} (0x{region.size:X})"
        for region in regions
    )


def _catalog_flash_regions(device: CatalogDevice) -> list[CatalogMemory]:
    regions = [
        item
        for item in device.memory
        if "x" in item.access.lower() and "w" not in item.access.lower()
    ]
    return sorted(
        regions,
        key=lambda item: (not item.startup, not item.default, item.start),
    )


def _lookup_target_catalog_device(target: KeilTargetModel) -> CatalogDevice | None:
    if not target.device:
        return None
    from keiltool.gui.settings import default_devices_path

    catalog = _project_device_catalog(str(default_devices_path().resolve()))
    if target.vendor:
        selected = catalog.lookup(target.vendor, target.device)
        if selected is not None:
            return selected
    return catalog.lookup_any_vendor(target.device)


@lru_cache(maxsize=4)
def _project_device_catalog(user_catalog_path: str) -> DeviceCatalog:
    embedded = load_embedded_catalog()
    user = load_user_catalog(Path(user_catalog_path))
    return DeviceCatalog(embedded=embedded.devices, user=user.devices)


def clear_project_device_catalog_cache() -> None:
    _project_device_catalog.cache_clear()


def _default_catalog_log_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base_dir = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base_dir / "KeilTool" / "logs"


def _integer_value(value: str) -> int | None:
    try:
        return int(value, 0)
    except ValueError:
        return None


def _size_value(value: str) -> int | None:
    normalized = value.strip().upper()
    multiplier = 1
    if normalized.endswith("K"):
        normalized, multiplier = normalized[:-1], 1024
    elif normalized.endswith("M"):
        normalized, multiplier = normalized[:-1], 1024 * 1024
    try:
        return int(normalized, 0) * multiplier
    except ValueError:
        return None
