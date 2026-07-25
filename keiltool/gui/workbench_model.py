from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from keiltool.core.openocd_backend import FlashRequest, parse_address
from keiltool.core.rtt import RttRequest
from keiltool.gui.project_config import ProjectTargetFacts


@dataclass(frozen=True, slots=True)
class RttLogPaths:
    channel: Path
    stdout: Path
    stderr: Path


@dataclass(frozen=True, slots=True)
class TargetFactsDisplay:
    device: str
    flash: str
    ram: str
    target_cfg: str
    resolution: str


def build_flash_request(firmware: str | Path, bin_address: str) -> FlashRequest:
    """Validate workbench firmware fields and return the shared backend request."""

    path = Path(firmware).expanduser()
    if path.suffix.lower() not in {".hex", ".bin"}:
        raise ValueError("Firmware must be a .hex or .bin file.")
    if not path.is_file():
        raise ValueError(f"Firmware file does not exist: {path}")
    if path.suffix.lower() == ".hex":
        return FlashRequest(path)
    return FlashRequest(path, base_address=parse_address(bin_address))


def build_rtt_request(
    *,
    manual: bool,
    address: str,
    ram_origin: int | None,
    ram_size: int | None,
    port: str | int,
    channel: str | int,
) -> RttRequest:
    """Validate workbench RTT fields and return the shared RTT request."""

    try:
        parsed_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("RTT port must be an integer.") from exc
    try:
        parsed_channel = int(channel)
    except (TypeError, ValueError) as exc:
        raise ValueError("RTT channel must be an integer.") from exc

    if manual:
        scan_address = parse_address(address)
        scan_size = 0x100
    else:
        if ram_origin is None or ram_size is None or ram_size <= 0:
            raise ValueError("Keil Target does not provide a usable RAM range for automatic RTT scanning.")
        scan_address = ram_origin
        scan_size = ram_size
    return RttRequest(
        scan_address=scan_address,
        scan_size=scan_size,
        port=parsed_port,
        channel=parsed_channel,
    )


def build_rtt_log_paths(log_dir: str | Path, target_name: str, stamp: str) -> RttLogPaths:
    directory = Path(log_dir)
    target = safe_filename(target_name)
    return RttLogPaths(
        channel=directory / f"rtt_{target}_{stamp}.log",
        stdout=directory / f"rtt_openocd_{target}_{stamp}.out.log",
        stderr=directory / f"rtt_openocd_{target}_{stamp}.err.log",
    )


def target_facts_display(
    facts: ProjectTargetFacts | None,
    *,
    empty_reason: str = "请选择 Keil 工程",
) -> TargetFactsDisplay:
    if facts is None:
        return TargetFactsDisplay("—", "—", "—", "—", empty_reason)
    return TargetFactsDisplay(
        device=facts.device or "—",
        flash=facts.flash_summary or "—",
        ram=facts.ram_summary or "—",
        target_cfg=facts.target_cfg or "—",
        resolution=facts.resolution_reason or facts.resolution_status,
    )


def is_target_ready(facts: ProjectTargetFacts | None) -> bool:
    return bool(facts and facts.ready and facts.openocd_executable and facts.target_cfg)


def is_firmware_ready(firmware: str | Path) -> bool:
    path = Path(firmware)
    return path.suffix.lower() in {".hex", ".bin"} and path.is_file()


def int_or_default(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def safe_filename(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    return cleaned.strip("._") or "target"


__all__ = [
    "RttLogPaths",
    "TargetFactsDisplay",
    "build_flash_request",
    "build_rtt_log_paths",
    "build_rtt_request",
    "int_or_default",
    "is_firmware_ready",
    "is_target_ready",
    "safe_filename",
    "target_facts_display",
]
