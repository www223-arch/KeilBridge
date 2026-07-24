from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable
import zipfile

from .cmsis_pack import parse_pdsc_bytes
from .device_catalog import (
    CatalogDevice,
    CatalogMemory,
    CatalogSource,
    load_catalog_file,
    write_catalog_file,
)


MAX_PACK_ENTRIES = 2_000
MAX_PDSC_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DeviceImportResult:
    devices: tuple[CatalogDevice, ...]
    output_path: Path


@dataclass(frozen=True, slots=True)
class UserCatalogLoadResult:
    devices: tuple[CatalogDevice, ...]
    diagnostics: tuple[str, ...]


def import_device_file(source: str | Path, destination: str | Path) -> DeviceImportResult:
    source_path = Path(source)
    suffix = source_path.suffix.lower()
    if suffix == ".pdsc":
        data = source_path.read_bytes()
        devices = parse_pdsc_bytes(
            data,
            location=str(source_path),
            source_kind="imported_pdsc",
        )
    elif suffix == ".pack":
        data = _read_pack_pdsc(source_path)
        devices = parse_pdsc_bytes(
            data,
            location=str(source_path),
            source_kind="imported_pack",
        )
    elif suffix == ".json":
        data = source_path.read_bytes()
        devices = (_parse_custom_json(data, source_path),)
    else:
        raise ValueError("Only .pdsc, .pack, and .json device definitions are supported.")

    _validate_unique_keys(devices)
    if not devices:
        raise ValueError("The imported definition does not contain any devices.")

    destination_path = Path(destination)
    output_name = _output_name(source_path, data)
    output_path = destination_path / output_name
    destination_path.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        write_catalog_file(temporary_path, devices)
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return DeviceImportResult(tuple(devices), output_path)


def load_user_catalog(directory: str | Path) -> UserCatalogLoadResult:
    directory_path = Path(directory)
    if not directory_path.is_dir():
        return UserCatalogLoadResult((), ())
    devices: list[CatalogDevice] = []
    diagnostics: list[str] = []
    for path in sorted(directory_path.glob("*.json")):
        try:
            devices.extend(load_catalog_file(path))
        except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            diagnostics.append(f"{path.name}: {exc}")
    merged: dict[tuple[str, str], CatalogDevice] = {}
    for device in devices:
        merged[device.key] = device
    return UserCatalogLoadResult(
        tuple(sorted(merged.values(), key=lambda item: item.key)),
        tuple(diagnostics),
    )


def _read_pack_pdsc(path: Path) -> bytes:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_PACK_ENTRIES:
                raise ValueError(f"PACK contains more than {MAX_PACK_ENTRIES} entries.")
            pdsc_entries: list[zipfile.ZipInfo] = []
            for entry in entries:
                normalized = entry.filename.replace("\\", "/")
                member = PurePosixPath(normalized)
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or (member.parts and member.parts[0].endswith(":"))
                ):
                    raise ValueError(f"Unsafe PACK member path: {entry.filename}")
                if normalized.lower().endswith(".pdsc"):
                    if entry.file_size > MAX_PDSC_SIZE:
                        raise ValueError("PACK PDSC exceeds the 8 MiB limit.")
                    pdsc_entries.append(entry)
            if len(pdsc_entries) != 1:
                raise ValueError("PACK must contain exactly one PDSC descriptor.")
            return archive.read(pdsc_entries[0])
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid PACK archive: {exc}") from exc


def _parse_custom_json(data: bytes, path: Path) -> CatalogDevice:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON device definition: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Custom device JSON must use schema_version 1.")

    vendor = _required_string(raw, "vendor")
    device = _required_string(raw, "device")
    family = _required_string(raw, "family")
    core = _required_string(raw, "core")
    memory_raw = raw.get("memory")
    if not isinstance(memory_raw, list) or not memory_raw:
        raise ValueError("Custom device JSON must contain at least one memory region.")
    memory = tuple(_custom_memory(item) for item in memory_raw)
    _validate_memory(memory)

    target = str(raw.get("openocd_target", "")).strip()
    if target:
        target_path = PurePosixPath(target.replace("\\", "/"))
        if (
            target_path.is_absolute()
            or ".." in target_path.parts
            or len(target_path.parts) < 2
            or target_path.parts[0].lower() != "target"
            or target_path.suffix.lower() != ".cfg"
        ):
            raise ValueError("openocd_target must be a safe target/*.cfg path.")

    digest = hashlib.sha256(data).hexdigest()
    return CatalogDevice(
        vendor=vendor,
        device=device,
        family=family,
        sub_family=str(raw.get("sub_family", "")).strip(),
        core=core,
        fpu=str(raw.get("fpu", "")).strip(),
        endian=str(raw.get("endian", "")).strip(),
        memory=memory,
        flash_algorithms=tuple(str(item) for item in raw.get("flash_algorithms", [])),
        openocd_target=target,
        openocd_status="user_provided" if target else "unresolved",
        source=CatalogSource(
            kind="user",
            vendor=vendor,
            pack="custom_json",
            pack_version="1",
            location=str(path),
            digest=digest,
        ),
    )


def _custom_memory(raw: object) -> CatalogMemory:
    if not isinstance(raw, dict):
        raise ValueError("Each memory region must be an object.")
    name = _required_string(raw, "name")
    access = _required_string(raw, "access").lower()
    if any(character not in "rwx" for character in access):
        raise ValueError(f"Invalid memory access for {name}: {access}")
    try:
        start = _number(raw.get("start"))
        size = _number(raw.get("size"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid memory range for {name}.") from exc
    if start < 0 or size <= 0:
        raise ValueError(f"Memory region {name} must have a non-negative start and positive size.")
    return CatalogMemory(
        name=name,
        start=start,
        size=size,
        access=access,
        default=bool(raw.get("default", False)),
        startup=bool(raw.get("startup", False)),
    )


def _validate_memory(memory: Iterable[CatalogMemory]) -> None:
    ordered = sorted(memory, key=lambda item: item.start)
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.start + previous.size:
            raise ValueError(
                f"Memory regions {previous.name} and {current.name} overlap."
            )


def _validate_unique_keys(devices: Iterable[CatalogDevice]) -> None:
    seen: set[tuple[str, str]] = set()
    for device in devices:
        if device.key in seen:
            raise ValueError(f"Duplicate device key: {device.vendor}::{device.device}")
        seen.add(device.key)


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Custom device JSON requires a non-empty {key}.")
    return value.strip()


def _number(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.strip(), 0)
    raise TypeError("number must be an integer or numeric string")


def _output_name(source: Path, data: bytes) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem).strip("._") or "devices"
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{stem}-{digest}.json"


__all__ = [
    "DeviceImportResult",
    "UserCatalogLoadResult",
    "import_device_file",
    "load_user_catalog",
]
