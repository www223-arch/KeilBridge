from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from keiltool.core.keil_parser import parse_uvprojx
from keiltool.core.openocd_target_resolver import resolve_openocd_target
from keiltool.core.project_model import KeilTargetModel, MemoryRegion
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts


INTERFACE_CFG = "interface/stlink.cfg"
_PROJECT_ROOTS: dict[int, Path] = {}


@dataclass(frozen=True, slots=True)
class ProjectTargetFacts:
    target_name: str
    device: str
    flash_summary: str
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


def load_project_targets(project_path: str | Path) -> list[KeilTargetModel]:
    """Parse a Keil project and return its selectable Target models."""

    project = parse_uvprojx(project_path)
    root = Path(project.inferred_project_root)
    _PROJECT_ROOTS.clear()
    for target in project.targets:
        _PROJECT_ROOTS[id(target)] = root
    return project.targets


def resolve_target_facts(
    target: KeilTargetModel,
    *,
    openocd_path: str | Path = "",
    scripts_dir: str | Path = "",
    target_override: str | Path = "",
    project_root: str | Path | None = None,
) -> ProjectTargetFacts:
    """Resolve GUI facts while refusing every unverified OpenOCD target cfg."""

    executable = str(openocd_path) if openocd_path else find_openocd()
    scripts = str(scripts_dir) if scripts_dir else find_openocd_scripts(executable)
    target_cfg, status, reason = _resolve_target_cfg(target, scripts, target_override)
    flash_regions = _regions_named(target.memory, "FLASH")
    ram_regions = _regions_named(target.memory, "RAM")
    main_ram = ram_regions[0] if ram_regions else None
    return ProjectTargetFacts(
        target_name=target.name,
        device=target.device,
        flash_summary=_summary(flash_regions),
        ram_summary=_summary(ram_regions),
        ram_origin=_integer_value(main_ram.origin) if main_ram else None,
        ram_size=_size_value(main_ram.length) if main_ram else None,
        openocd_executable=executable,
        openocd_scripts=scripts,
        interface_cfg=INTERFACE_CFG,
        target_cfg=target_cfg,
        resolution_status=status,
        resolution_reason=reason,
        default_log_dir=str((Path(project_root) if project_root is not None else target_model_root(target)) / ".keilbridge" / "logs"),
        ready=status.endswith("_verified") and bool(target_cfg),
    )


def target_model_root(target: KeilTargetModel) -> Path:
    """Return the project root registered while parsing a selectable Target."""

    return _PROJECT_ROOTS.get(id(target), Path.cwd())


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


def _regions_named(regions: list[MemoryRegion], name: str) -> list[MemoryRegion]:
    return [region for region in regions if region.name.upper() == name]


def _summary(regions: list[MemoryRegion]) -> str:
    return ", ".join(f"{region.name}: {region.origin} ({region.length})" for region in regions)


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
