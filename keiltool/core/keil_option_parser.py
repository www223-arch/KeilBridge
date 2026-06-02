from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class KeilDebugOptions:
    probe: str = ""
    debug_dll: str = ""
    flash_algorithm: str = ""


def parse_uvoptx_debug_options(uvoptx_path: str | Path, target_name: str) -> KeilDebugOptions:
    path = Path(uvoptx_path)
    if not path.exists():
        return KeilDebugOptions()
    root = ET.parse(path).getroot()
    for target in root.findall(".//Target"):
        if _text(target.find("TargetName")) != target_name:
            continue
        debug_dll = _text(target.find(".//DebugOpt/pMon"))
        registry_text = " ".join(_text(item) for item in target.findall(".//TargetDriverDllRegistry//Name"))
        return KeilDebugOptions(
            probe=_probe_from_debug_dll(debug_dll),
            debug_dll=debug_dll,
            flash_algorithm=_flash_algorithm_from_registry(registry_text),
        )
    return KeilDebugOptions()


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _probe_from_debug_dll(debug_dll: str) -> str:
    normalized = debug_dll.replace("\\", "/").lower()
    if "stlink" in normalized or "st-link" in normalized:
        return "stlink"
    if "cmsis" in normalized or "dap" in normalized:
        return "cmsis-dap"
    if "jlink" in normalized or "j-link" in normalized:
        return "jlink"
    return ""


def _flash_algorithm_from_registry(text: str) -> str:
    matches = re.findall(r"([^\\/$()\s]+\.FLM)", text, flags=re.IGNORECASE)
    return matches[-1] if matches else ""
