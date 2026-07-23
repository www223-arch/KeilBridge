from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
from typing import Protocol

from .doctor import DoctorFinding, classify_openocd_log
from .project_model import KeilTargetModel


class OpenOcdRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class OpenOcdConfig:
    executable: Path
    scripts_dir: Path | None
    interface_cfg: str
    target_cfg: str

    def __post_init__(self) -> None:
        if self.interface_cfg != "interface/stlink.cfg":
            raise ValueError("Only interface/stlink.cfg is supported.")
        if not self.target_cfg.strip():
            raise ValueError("An OpenOCD target cfg is required.")

    def base_command(self) -> list[str]:
        command = [self.executable.as_posix()]
        if self.scripts_dir:
            command.extend(["-s", self.scripts_dir.resolve().as_posix()])
        command.extend(["-f", self.interface_cfg, "-f", self.target_cfg])
        return command


@dataclass(frozen=True, slots=True)
class FlashRequest:
    firmware: Path
    base_address: int = 0x08000000


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    success: bool
    returncode: int
    command: list[str]
    stdout: str
    stderr: str
    stdout_log: Path
    stderr_log: Path
    findings: list[DoctorFinding]


@dataclass(frozen=True, slots=True)
class FlashResult:
    success: bool
    returncode: int
    command: list[str]
    stdout: str
    stderr: str
    stdout_log: Path
    stderr_log: Path
    findings: list[DoctorFinding]


def parse_address(value: str | int) -> int:
    if isinstance(value, bool):
        raise ValueError("Base address must be a valid integer.")
    try:
        address = value if isinstance(value, int) else int(value, 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Base address must be a valid integer.") from exc
    if address < 0:
        raise ValueError("Base address must be non-negative.")
    if address > 0xFFFFFFFF:
        raise ValueError("Base address must fit in 32 bits.")
    return address


def build_connection_command(config: OpenOcdConfig) -> list[str]:
    return [*config.base_command(), "-c", "init", "-c", "targets", "-c", "shutdown"]


def build_flash_command(config: OpenOcdConfig, request: FlashRequest) -> list[str]:
    command = config.base_command()
    suffix = request.firmware.suffix.lower()
    firmware = quote_tcl_word(request.firmware.resolve().as_posix())
    if suffix == ".hex":
        program = f"program {firmware} verify reset exit"
    elif suffix == ".bin":
        base_address = parse_address(request.base_address)
        program = f"program {firmware} 0x{base_address:08X} verify reset exit"
    else:
        raise ValueError("Firmware must be a .hex or .bin file.")
    return [*command, "-c", program]


def quote_tcl_word(value: str) -> str:
    """Return a Tcl word that preserves a literal OpenOCD argument."""

    if not any(character.isspace() or character in '\\\"$[]{};' for character in value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )
    return f'"{escaped}"'


def run_connection_check(
    config: OpenOcdConfig,
    log_dir: Path,
    *,
    runner: OpenOcdRunner = subprocess.run,
    cwd: Path | None = None,
    target: KeilTargetModel | None = None,
) -> ConnectionResult:
    command = build_connection_command(config)
    completed, stdout_log, stderr_log = _run_with_logs(command, log_dir, "connection", runner, cwd)
    findings = _classify(completed.stdout, completed.stderr, config.executable, target)
    success = completed.returncode == 0 and _has_connection_evidence(completed.stdout + "\n" + completed.stderr)
    if not success and completed.returncode == 0:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="OPENOCD_CONNECTION_EVIDENCE_MISSING",
                title="OpenOCD did not report target/core connection evidence",
                message="The connection check exited successfully, but its output did not confirm a target and Cortex core.",
            )
        )
    return ConnectionResult(
        success=success,
        returncode=completed.returncode,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        findings=findings,
    )


def run_flash(
    config: OpenOcdConfig,
    request: FlashRequest,
    log_dir: Path,
    *,
    runner: OpenOcdRunner = subprocess.run,
    cwd: Path | None = None,
    target: KeilTargetModel | None = None,
) -> FlashResult:
    if not request.firmware.is_file():
        raise ValueError(f"Firmware file does not exist: {request.firmware}")
    command = build_flash_command(config, request)
    completed, stdout_log, stderr_log = _run_with_logs(command, log_dir, "flash", runner, cwd)
    findings = _classify(completed.stdout, completed.stderr, config.executable, target)
    success = completed.returncode == 0 and _has_flash_success_markers(completed.stdout + "\n" + completed.stderr)
    if not success and completed.returncode == 0:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="OPENOCD_FLASH_SUCCESS_MARKERS_MISSING",
                title="OpenOCD did not confirm program and verify success",
                message="The flash command exited successfully, but its output lacked programming and verification success markers.",
            )
        )
    return FlashResult(
        success=success,
        returncode=completed.returncode,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        findings=findings,
    )


def _run_with_logs(
    command: list[str],
    log_dir: Path,
    name: str,
    runner: OpenOcdRunner,
    cwd: Path | None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stdout_log = log_dir / f"{name}_{stamp}.out.log"
    stderr_log = log_dir / f"{name}_{stamp}.err.log"
    completed = runner(command, cwd=cwd, text=True, capture_output=True)
    stdout_log.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_log.write_text(completed.stderr, encoding="utf-8", newline="\n")
    return completed, stdout_log, stderr_log


def _classify(
    stdout: str,
    stderr: str,
    executable: Path,
    target: KeilTargetModel | None,
) -> list[DoctorFinding]:
    return classify_openocd_log(
        stdout + "\n" + stderr,
        executable.as_posix(),
        target or KeilTargetModel(name="OpenOCD"),
        "stlink",
    )


def _has_connection_evidence(text: str) -> bool:
    lower = text.lower()
    return "target" in lower and ("cortex" in lower or "core" in lower)


def _has_flash_success_markers(text: str) -> bool:
    lower = text.lower()
    return "programming finished" in lower and "verified ok" in lower
