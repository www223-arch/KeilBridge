from __future__ import annotations

from pathlib import Path
import os
import re


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def resolve_keil_path(base_dir: Path, raw_path: str, project_root: Path | None = None) -> str:
    """解析 Keil 工程路径。

    Keil 工程里常见 `$PROJ_DIR$`、`%USERPROFILE%` 这类路径变量。
    这里先做保守展开；如果变量未知，保留原文本并按相对路径处理，后续由诊断报告提示。
    """

    normalized = normalize_path(_expand_keil_vars(raw_path.strip(), base_dir, project_root))
    path = Path(normalized)
    if path.is_absolute():
        return normalize_path(str(path))
    return normalize_path(str((base_dir / path).resolve()))


def infer_project_root(uvprojx_path: Path) -> Path:
    parent = uvprojx_path.resolve().parent
    if parent.name.upper() in {"MDK-ARM", "MDK_ARM", "ARM", "KEIL", "KEIL5"}:
        return parent.parent
    return parent


def _expand_keil_vars(path: str, base_dir: Path, project_root: Path | None) -> str:
    expanded = path
    expanded = expanded.replace("$PROJ_DIR$", normalize_path(str(base_dir)))
    expanded = expanded.replace("$(PROJ_DIR)", normalize_path(str(base_dir)))
    if project_root is not None:
        expanded = expanded.replace("$PROJECT_ROOT$", normalize_path(str(project_root)))
        expanded = expanded.replace("$(PROJECT_ROOT)", normalize_path(str(project_root)))

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    expanded = re.sub(r"%([^%]+)%", repl, expanded)
    return os.path.expandvars(expanded)
