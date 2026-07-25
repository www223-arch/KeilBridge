from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import strftime
import shutil
import subprocess

from .path_resolver import infer_project_root


UVISION_CANDIDATES = [
    Path(r"C:\Keil_v5\UV4\UV4.exe"),
    Path(r"D:\Keil_v5\UV4\UV4.exe"),
    Path(r"C:\Keil\UV4\UV4.exe"),
    Path(r"D:\Keil\UV4\UV4.exe"),
    Path(r"C:\Program Files\Keil_v5\UV4\UV4.exe"),
    Path(r"C:\Program Files (x86)\Keil_v5\UV4\UV4.exe"),
]


@dataclass(slots=True)
class KeilCliResult:
    command: list[str]
    returncode: int
    log_path: str
    mode: str = "uvision"


def find_uvision(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for name in ("UV4.exe", "UV4.com", "UVISION.exe", "UVISION.com"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in UVISION_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return "UV4.exe"


def run_keil_cli(
    project: Path,
    target: str | None,
    action: str,
    uvision: str | None = None,
    workspace_root: Path | None = None,
) -> KeilCliResult:
    uv = find_uvision(uvision)
    if action in {"build", "rebuild"} and not _uvision_available(uv):
        batch = find_keil_batch(project, target)
        if batch:
            return run_keil_batch(batch, project, target, action, workspace_root)
    if not _uvision_available(uv):
        raise FileNotFoundError(
            "Keil uVision CLI was not found. Pass --uvision path\\to\\UV4.exe, "
            "add UV4.exe to PATH, or use a project-generated BAT file for build/rebuild."
        )
    command = build_keil_command(uv, project, target, action, _log_path(project, target, action, workspace_root))
    completed = subprocess.run(command, cwd=project.resolve().parent)
    log_path = command[-1][2:]
    returncode = completed.returncode or (1 if _log_has_keil_errors(Path(log_path)) else 0)
    return KeilCliResult(command=command, returncode=returncode, log_path=log_path)


def find_keil_batch(project: Path, target: str | None) -> Path | None:
    project_dir = project.resolve().parent
    candidates: list[Path] = []
    if target:
        candidates.append(project_dir / f"{target}.BAT")
        candidates.append(project_dir / f"{target}.bat")
    candidates.extend(sorted(project_dir.glob("*.BAT")))
    candidates.extend(sorted(project_dir.glob("*.bat")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_keil_batch(batch: Path, project: Path, target: str | None, action: str, workspace_root: Path | None) -> KeilCliResult:
    log_path = _log_path(project, target, action, workspace_root)
    runnable_batch = prepare_keil_batch(batch, project, workspace_root)
    command = ["cmd.exe", "/c", str(runnable_batch.resolve())]
    with log_path.open("w", encoding="utf-8", errors="replace", newline="\n") as log:
        completed = subprocess.run(command, cwd=batch.parent, stdout=log, stderr=subprocess.STDOUT)
    returncode = completed.returncode or (1 if _log_has_keil_errors(log_path) else 0)
    return KeilCliResult(command=command, returncode=returncode, log_path=str(log_path), mode="batch")


def prepare_keil_batch(batch: Path, project: Path, workspace_root: Path | None) -> Path:
    text = batch.read_text(encoding="utf-8", errors="replace")
    replacement = _find_armcc_bin()
    patched = text
    if replacement:
        patched = _replace_missing_armcc_paths(text, replacement)
    if patched == text:
        return batch
    root = workspace_root or infer_project_root(project)
    generated = root / ".keilbridge" / "generated" / "keil-batch"
    generated.mkdir(parents=True, exist_ok=True)
    patched_batch = generated / batch.name
    patched_batch.write_text(patched, encoding="utf-8", newline="\n")
    return patched_batch


def build_keil_command(uvision: str, project: Path, target: str | None, action: str, log_path: Path) -> list[str]:
    command_switch = {
        "build": "-b",
        "rebuild": "-r",
        "download": "-f",
    }[action]
    command = [uvision, command_switch, str(project.resolve())]
    if target:
        command.append(f"-t{target}")
    command.append(f"-o{log_path.resolve()}")
    return command


def _uvision_available(uvision: str) -> bool:
    path = Path(uvision)
    if path.exists():
        return True
    return shutil.which(uvision) is not None


def _find_armcc_bin() -> Path | None:
    for candidate in [
        Path(r"C:\Keil_v5\ARM\ARMCC\Bin"),
        Path(r"D:\Keil_v5\ARM\ARMCC\Bin"),
        Path(r"C:\Keil5\ARM\ARMCC\bin"),
        Path(r"D:\Keil5\ARM\ARMCC\bin"),
    ]:
        if (candidate / "armcc.exe").exists():
            return candidate
    found = shutil.which("armcc.exe")
    if found:
        return Path(found).parent
    return None


def _replace_missing_armcc_paths(text: str, replacement: Path) -> str:
    result = text
    for marker in [r"C:\Keil_v5\ARM\ARMCC\Bin", r"D:\Keil_v5\ARM\ARMCC\Bin", r"C:\Keil5\ARM\ARMCC\bin", r"D:\Keil5\ARM\ARMCC\bin"]:
        if marker in result and not Path(marker).exists():
            result = result.replace(marker, str(replacement))
    return result


def _log_has_keil_errors(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    text = log_path.read_text(encoding="utf-8", errors="replace").lower()
    error_tokens = [
        "fatal error",
        "error:",
        " error ",
        "could not open via file",
        "target not created",
    ]
    return any(token in text for token in error_tokens)


def _log_path(project: Path, target: str | None, action: str, workspace_root: Path | None) -> Path:
    root = workspace_root or infer_project_root(project)
    logs_dir = root / ".keilbridge" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    safe_target = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (target or "default"))
    return logs_dir / f"keil_{action}_{safe_target}_{strftime('%Y%m%d-%H%M%S')}.log"
