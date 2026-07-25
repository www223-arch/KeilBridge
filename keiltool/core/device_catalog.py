from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "device_catalog" / "catalog.json"


@dataclass(frozen=True, slots=True)
class CatalogMemory:
    name: str
    start: int
    size: int
    access: str
    default: bool = False
    startup: bool = False


@dataclass(frozen=True, slots=True)
class CatalogSource:
    kind: str
    vendor: str
    pack: str
    pack_version: str
    location: str
    digest: str


@dataclass(frozen=True, slots=True)
class CatalogDevice:
    vendor: str
    device: str
    family: str
    sub_family: str
    core: str
    fpu: str
    endian: str
    memory: tuple[CatalogMemory, ...]
    flash_algorithms: tuple[str, ...]
    openocd_target: str
    openocd_status: str
    source: CatalogSource

    @property
    def key(self) -> tuple[str, str]:
        return _key(self.vendor, self.device)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> CatalogDevice:
        if not isinstance(raw, dict):
            raise ValueError("Catalog device entry must be an object.")
        memory_raw = raw.get("memory", [])
        source_raw = raw.get("source", {})
        if not isinstance(memory_raw, list) or not isinstance(source_raw, dict):
            raise ValueError("Catalog device memory/source has an invalid type.")
        return cls(
            vendor=str(raw.get("vendor", "")),
            device=str(raw.get("device", "")),
            family=str(raw.get("family", "")),
            sub_family=str(raw.get("sub_family", "")),
            core=str(raw.get("core", "")),
            fpu=str(raw.get("fpu", "")),
            endian=str(raw.get("endian", "")),
            memory=tuple(
                CatalogMemory(
                    name=str(item["name"]),
                    start=int(item["start"]),
                    size=int(item["size"]),
                    access=str(item.get("access", "")),
                    default=bool(item.get("default", False)),
                    startup=bool(item.get("startup", False)),
                )
                for item in memory_raw
                if isinstance(item, dict)
            ),
            flash_algorithms=tuple(str(item) for item in raw.get("flash_algorithms", [])),
            openocd_target=str(raw.get("openocd_target", "")),
            openocd_status=str(raw.get("openocd_status", "")),
            source=CatalogSource(
                kind=str(source_raw.get("kind", "")),
                vendor=str(source_raw.get("vendor", "")),
                pack=str(source_raw.get("pack", "")),
                pack_version=str(source_raw.get("pack_version", "")),
                location=str(source_raw.get("location", "")),
                digest=str(source_raw.get("digest", "")),
            ),
        )


class DeviceCatalog:
    def __init__(
        self,
        embedded: Iterable[CatalogDevice] = (),
        imported: Iterable[CatalogDevice] = (),
        user: Iterable[CatalogDevice] = (),
    ) -> None:
        merged: dict[tuple[str, str], CatalogDevice] = {}
        for layer in (embedded, imported, user):
            for device in layer:
                merged[device.key] = device
        self._devices = tuple(sorted(merged.values(), key=lambda item: item.key))
        self._by_key = {item.key: item for item in self._devices}

    @property
    def devices(self) -> tuple[CatalogDevice, ...]:
        return self._devices

    def lookup(self, vendor: str, device: str) -> CatalogDevice | None:
        return self._by_key.get(_key(vendor, device))

    def lookup_any_vendor(self, device: str) -> CatalogDevice | None:
        normalized = _normalize(device)
        matches = [item for item in self._devices if _normalize(item.device) == normalized]
        return matches[0] if len(matches) == 1 else None


def load_catalog_file(path: str | Path) -> tuple[CatalogDevice, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("devices", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError("Device catalog must contain a devices list.")
    return tuple(CatalogDevice.from_dict(item) for item in entries)


def load_embedded_catalog() -> DeviceCatalog:
    if not CATALOG_PATH.is_file():
        return DeviceCatalog()
    return DeviceCatalog(embedded=load_catalog_file(CATALOG_PATH))


def write_catalog_file(path: str | Path, devices: Iterable[CatalogDevice]) -> None:
    payload = {
        "schema_version": 1,
        "devices": [
            item.to_dict()
            for item in sorted(devices, key=lambda device: device.key)
        ],
    }
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _normalize(value: str) -> str:
    return value.strip().upper()


def _key(vendor: str, device: str) -> tuple[str, str]:
    return _normalize(vendor), _normalize(device)


__all__ = [
    "CATALOG_PATH",
    "CatalogDevice",
    "CatalogMemory",
    "CatalogSource",
    "DeviceCatalog",
    "load_catalog_file",
    "load_embedded_catalog",
    "write_catalog_file",
]
