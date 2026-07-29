from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .project_model import KeilTargetModel


FAMILY_TARGET_MAP = {
    "stm32f1": "target/stm32f1x.cfg",
    "stm32f3": "target/stm32f3x.cfg",
    "stm32f4": "target/stm32f4x.cfg",
    "stm32g4": "target/stm32g4x.cfg",
    "stm32l4": "target/stm32l4x.cfg",
    "stm32h7": "target/stm32h7x.cfg",
    "gd32f1": "target/stm32f1x.cfg",
    "gd32f3": "target/stm32f3x.cfg",
    "gd32f4": "target/stm32f4x.cfg",
    "gd32e2": "target/gd32e23x.cfg",
}


@dataclass(slots=True)
class OpenOcdTargetResolution:
    target_cfg: str
    status: str
    reason: str


def resolve_openocd_target(target: KeilTargetModel, openocd_scripts: str | Path = "") -> OpenOcdTargetResolution:
    """Resolve the OpenOCD target cfg from Keil facts plus compatibility rules."""

    explicit = target.device_info.openocd_target
    if explicit:
        return _with_script_check(
            explicit,
            openocd_scripts,
            "device_database",
            "OpenOCD target came from the device database.",
        )

    mapped = FAMILY_TARGET_MAP.get((target.family or "").lower())
    if mapped:
        return _with_script_check(
            mapped,
            openocd_scripts,
            "family_mapping",
            f"OpenOCD target inferred from family `{target.family}`.",
        )

    return OpenOcdTargetResolution(
        target_cfg="",
        status="unresolved",
        reason="No device database target or family mapping is available.",
    )


def _with_script_check(target_cfg: str, openocd_scripts: str | Path, source_status: str, reason: str) -> OpenOcdTargetResolution:
    if not openocd_scripts:
        return OpenOcdTargetResolution(target_cfg=target_cfg, status=f"{source_status}_unverified", reason=reason)
    scripts = Path(openocd_scripts)
    if not scripts.exists():
        return OpenOcdTargetResolution(
            target_cfg=target_cfg,
            status=f"{source_status}_scripts_missing",
            reason=f"{reason} OpenOCD scripts directory was not found: {scripts}",
        )
    if (scripts / target_cfg).is_file():
        return OpenOcdTargetResolution(
            target_cfg=target_cfg,
            status=f"{source_status}_verified",
            reason=f"{reason} Verified in OpenOCD scripts.",
        )
    return OpenOcdTargetResolution(
        target_cfg="",
        status="unresolved",
        reason=f"{reason} Candidate `{target_cfg}` does not exist under `{scripts}`.",
    )
