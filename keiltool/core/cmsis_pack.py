from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from .device_catalog import CatalogDevice, CatalogMemory, CatalogSource


@dataclass(slots=True)
class _InheritedFacts:
    family: str = ""
    sub_family: str = ""
    processor: dict[str, str] = field(default_factory=dict)
    memory: dict[str, CatalogMemory] = field(default_factory=dict)
    algorithms: dict[str, str] = field(default_factory=dict)

    def child(self) -> _InheritedFacts:
        return _InheritedFacts(
            family=self.family,
            sub_family=self.sub_family,
            processor=dict(self.processor),
            memory=dict(self.memory),
            algorithms=dict(self.algorithms),
        )


def parse_pdsc(path: str | Path, *, source_kind: str = "embedded") -> tuple[CatalogDevice, ...]:
    source_path = Path(path)
    data = source_path.read_bytes()
    return parse_pdsc_bytes(
        data,
        location=str(source_path),
        source_kind=source_kind,
    )


def parse_pdsc_bytes(
    data: bytes,
    *,
    location: str,
    source_kind: str = "embedded",
) -> tuple[CatalogDevice, ...]:
    root = ET.fromstring(data)
    vendor = _text(root, "vendor") or _vendor_name(root)
    pack = _text(root, "name")
    release = next(_children(_child(root, "releases"), "release"), None)
    version = release.attrib.get("version", "") if release is not None else ""
    source = CatalogSource(
        kind=source_kind,
        vendor=vendor,
        pack=pack,
        pack_version=version,
        location=location,
        digest=hashlib.sha256(data).hexdigest(),
    )

    devices_root = _child(root, "devices")
    if devices_root is None:
        return ()

    devices: list[CatalogDevice] = []
    for family in _children(devices_root, "family"):
        facts = _InheritedFacts(family=family.attrib.get("Dfamily", ""))
        _apply_node(facts, family)
        _walk_children(family, facts, vendor, source, devices)
    return tuple(devices)


def _walk_children(
    parent: ET.Element,
    inherited: _InheritedFacts,
    vendor: str,
    source: CatalogSource,
    output: list[CatalogDevice],
) -> None:
    for node in list(parent):
        kind = _local_name(node.tag)
        if kind not in {"subFamily", "device", "variant"}:
            continue
        facts = inherited.child()
        if kind == "subFamily":
            facts.sub_family = node.attrib.get("DsubFamily", facts.sub_family)
        _apply_node(facts, node)
        name = node.attrib.get("Dname") or node.attrib.get("Dvariant")
        if name:
            output.append(_build_device(name, vendor, facts, source))
        _walk_children(node, facts, vendor, source, output)


def _apply_node(facts: _InheritedFacts, node: ET.Element) -> None:
    processor = _child(node, "processor")
    if processor is not None:
        facts.processor.update(processor.attrib)
    for memory in _children(node, "memory"):
        parsed = _parse_memory(memory)
        facts.memory[parsed.name.upper()] = parsed
    for algorithm in _children(node, "algorithm"):
        name = algorithm.attrib.get("name", "").strip()
        if name:
            facts.algorithms[name.upper()] = name


def _parse_memory(node: ET.Element) -> CatalogMemory:
    name = node.attrib.get("name") or node.attrib.get("id") or "MEMORY"
    access = node.attrib.get("access", "")
    if not access:
        upper = name.upper()
        access = "rwx" if "RAM" in upper else "rx" if "ROM" in upper else ""
    return CatalogMemory(
        name=name,
        start=_number(node.attrib.get("start", "0")),
        size=_number(node.attrib.get("size", "0")),
        access=access,
        default=_boolean(node.attrib.get("default")),
        startup=_boolean(node.attrib.get("startup")),
    )


def _build_device(
    name: str,
    vendor: str,
    facts: _InheritedFacts,
    source: CatalogSource,
) -> CatalogDevice:
    processor = facts.processor
    return CatalogDevice(
        vendor=vendor,
        device=name,
        family=facts.family,
        sub_family=facts.sub_family,
        core=processor.get("Dcore", ""),
        fpu=_normalize_fpu(processor.get("Dfpu", "")),
        endian=processor.get("Dendian", ""),
        memory=tuple(facts.memory.values()),
        flash_algorithms=tuple(facts.algorithms.values()),
        openocd_target="",
        openocd_status="",
        source=source,
    )


def _normalize_fpu(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"", "0", "NO_FPU"}:
        return ""
    if normalized == "1":
        return "FPU"
    return normalized


def _number(value: str) -> int:
    return int(value.strip(), 0)


def _boolean(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true"}


def _text(parent: ET.Element, name: str) -> str:
    node = _child(parent, name)
    return (node.text or "").strip() if node is not None else ""


def _vendor_name(root: ET.Element) -> str:
    devices = _child(root, "devices")
    family = next(_children(devices, "family"), None)
    value = family.attrib.get("Dvendor", "") if family is not None else ""
    return value.split(":", 1)[0]


def _child(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((item for item in list(parent) if _local_name(item.tag) == name), None)


def _children(parent: ET.Element | None, name: str):
    if parent is None:
        return iter(())
    return (item for item in list(parent) if _local_name(item.tag) == name)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


__all__ = ["parse_pdsc", "parse_pdsc_bytes"]
