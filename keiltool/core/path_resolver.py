from __future__ import annotations

from pathlib import Path


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def resolve_keil_path(base_dir: Path, raw_path: str) -> str:
    normalized = normalize_path(raw_path.strip())
    path = Path(normalized)
    if path.is_absolute():
        return normalize_path(str(path))
    return normalize_path(str((base_dir / path).resolve()))


def infer_project_root(uvprojx_path: Path) -> Path:
    parent = uvprojx_path.resolve().parent
    if parent.name.upper() in {"MDK-ARM", "MDK_ARM", "ARM", "KEIL", "KEIL5"}:
        return parent.parent
    return parent

