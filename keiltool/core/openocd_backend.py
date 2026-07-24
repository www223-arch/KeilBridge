from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
import threading
import time
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


class OpenOcdProcess(Protocol):
    returncode: int | None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenOcdConfig:
    executable: Path
    scripts_dir: Path | None
    interface_cfg: str | None
    target_cfg: str

    def __post_init__(self) -> None:
        if not self.target_cfg.strip():
            raise ValueError("An OpenOCD target cfg is required.")

    def base_command(self) -> list[str]:
        command = [self.executable.as_posix()]
        if self.scripts_dir:
            command.extend(["-s", self.scripts_dir.resolve().as_posix()])
        if self.interface_cfg:
            command.extend(["-f", self.interface_cfg])
        command.extend(["-f", self.target_cfg])
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
    outcome: str = "failed"


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
    outcome: str = "failed"


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    outcome: str


class OpenOcdOperation:
    """Run one OpenOCD command with bounded timeout and cancellation."""

    def __init__(
        self,
        *,
        timeout: float = 300.0,
        terminate_timeout: float = 2.0,
        kill_timeout: float = 2.0,
        poll_interval: float = 0.05,
        popen_factory=subprocess.Popen,
        monotonic=time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("OpenOCD operation timeout must be positive.")
        if terminate_timeout < 0 or kill_timeout < 0:
            raise ValueError("OpenOCD cleanup timeouts must be non-negative.")
        if poll_interval <= 0:
            raise ValueError("OpenOCD poll interval must be positive.")
        self._timeout = timeout
        self._terminate_timeout = terminate_timeout
        self._kill_timeout = kill_timeout
        self._poll_interval = poll_interval
        self._popen_factory = popen_factory
        self._monotonic = monotonic
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: OpenOcdProcess | None = None
        self._terminate_requested = False

    def cancel(self) -> None:
        self._cancelled.set()
        self._request_terminate()

    def execute(self, command: list[str], cwd: Path | None) -> _ExecutionResult:
        command_preview = subprocess.list2cmdline(command)
        if self._cancelled.is_set():
            return _ExecutionResult(
                -1,
                "",
                _evidence(command_preview, "OpenOCD operation was cancelled before launch."),
                "cancelled",
            )
        try:
            process = self._popen_factory(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return _ExecutionResult(
                -1,
                "",
                _evidence(command_preview, f"Unable to launch OpenOCD: {exc}"),
                "launch_failed",
            )

        with self._lock:
            self._process = process
        if self._cancelled.is_set():
            self._request_terminate()

        deadline = self._monotonic() + self._timeout
        stdout = ""
        stderr = ""
        while True:
            if self._cancelled.is_set():
                return self._stop_process(process, command_preview, stdout, stderr, "cancelled")
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return self._stop_process(process, command_preview, stdout, stderr, "timed_out")
            try:
                stdout, stderr = process.communicate(timeout=min(self._poll_interval, remaining))
            except subprocess.TimeoutExpired as exc:
                stdout = _timeout_text(exc.output, stdout)
                stderr = _timeout_text(exc.stderr, stderr)
                continue
            return _ExecutionResult(
                process.returncode if process.returncode is not None else 0,
                stdout or "",
                stderr or "",
                "completed",
            )

    def _stop_process(
        self,
        process: OpenOcdProcess,
        command_preview: str,
        stdout: str,
        stderr: str,
        outcome: str,
    ) -> _ExecutionResult:
        self._request_terminate()
        message = "OpenOCD operation was cancelled." if outcome == "cancelled" else "OpenOCD operation timed out."
        try:
            final_stdout, final_stderr = process.communicate(timeout=self._terminate_timeout)
            stdout = final_stdout or stdout
            stderr = final_stderr or stderr
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_text(exc.output, stdout)
            stderr = _timeout_text(exc.stderr, stderr)
            try:
                process.kill()
            except OSError as kill_error:
                message += f" Kill failed: {kill_error}"
            else:
                message += " OpenOCD was killed after the terminate timeout."
            try:
                final_stdout, final_stderr = process.communicate(timeout=self._kill_timeout)
                stdout = final_stdout or stdout
                stderr = final_stderr or stderr
            except subprocess.TimeoutExpired as kill_timeout:
                stdout = _timeout_text(kill_timeout.output, stdout)
                stderr = _timeout_text(kill_timeout.stderr, stderr)
                message += " OpenOCD did not report exit before the kill timeout."
        stderr = _append_text(stderr, _evidence(command_preview, message))
        return _ExecutionResult(
            process.returncode if process.returncode is not None else -1,
            stdout,
            stderr,
            outcome,
        )

    def _request_terminate(self) -> None:
        with self._lock:
            process = self._process
            if process is None or self._terminate_requested:
                return
            self._terminate_requested = True
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass


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
    if suffix in {".hex", ".elf", ".axf"}:
        program = f"program {firmware} verify reset exit"
    elif suffix == ".bin":
        base_address = parse_address(request.base_address)
        program = f"program {firmware} 0x{base_address:08X} verify reset exit"
    else:
        raise ValueError("Firmware must be a .hex, .bin, .elf, or .axf file.")
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
    runner: OpenOcdRunner | None = None,
    operation: OpenOcdOperation | None = None,
    cwd: Path | None = None,
    target: KeilTargetModel | None = None,
    target_name: str = "",
) -> ConnectionResult:
    command = build_connection_command(config)
    completed, stdout_log, stderr_log = _run_with_logs(
        command,
        log_dir,
        "connection",
        runner,
        operation or OpenOcdOperation(timeout=30.0),
        cwd,
        target_name,
    )
    findings = _classify(completed.stdout, completed.stderr, config.executable, target)
    success = (
        completed.outcome == "completed"
        and completed.returncode == 0
        and _has_connection_evidence(completed.stdout + "\n" + completed.stderr)
    )
    if completed.outcome != "completed":
        findings.append(_operation_finding(completed.outcome, "connection"))
    elif not success and completed.returncode == 0:
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
        outcome="succeeded" if success else completed.outcome if completed.outcome != "completed" else "failed",
    )


def run_flash(
    config: OpenOcdConfig,
    request: FlashRequest,
    log_dir: Path,
    *,
    runner: OpenOcdRunner | None = None,
    operation: OpenOcdOperation | None = None,
    cwd: Path | None = None,
    target: KeilTargetModel | None = None,
    target_name: str = "",
) -> FlashResult:
    if not request.firmware.is_file():
        raise ValueError(f"Firmware file does not exist: {request.firmware}")
    command = build_flash_command(config, request)
    completed, stdout_log, stderr_log = _run_with_logs(
        command,
        log_dir,
        "flash",
        runner,
        operation or OpenOcdOperation(),
        cwd,
        target_name,
    )
    findings = _classify(completed.stdout, completed.stderr, config.executable, target)
    success = (
        completed.outcome == "completed"
        and completed.returncode == 0
        and _has_flash_success_markers(completed.stdout + "\n" + completed.stderr)
    )
    if completed.outcome != "completed":
        findings.append(_operation_finding(completed.outcome, "flash"))
    elif not success and completed.returncode == 0:
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
        outcome="succeeded" if success else completed.outcome if completed.outcome != "completed" else "failed",
    )


def _run_with_logs(
    command: list[str],
    log_dir: Path,
    name: str,
    runner: OpenOcdRunner | None,
    operation: OpenOcdOperation,
    cwd: Path | None,
    target_name: str,
) -> tuple[_ExecutionResult, Path, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target_component = f"_{_safe_log_component(target_name)}" if target_name else ""
    stdout_log = log_dir / f"{name}{target_component}_{stamp}.out.log"
    stderr_log = log_dir / f"{name}{target_component}_{stamp}.err.log"
    if runner is None:
        completed = operation.execute(command, cwd)
    else:
        try:
            runner_result = runner(command, cwd=cwd, text=True, capture_output=True)
            completed = _ExecutionResult(
                runner_result.returncode,
                runner_result.stdout,
                runner_result.stderr,
                "completed",
            )
        except OSError as exc:
            completed = _ExecutionResult(
                -1,
                "",
                _evidence(subprocess.list2cmdline(command), f"Unable to launch OpenOCD: {exc}"),
                "launch_failed",
            )
    stdout_log.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_log.write_text(completed.stderr, encoding="utf-8", newline="\n")
    return completed, stdout_log, stderr_log


def _operation_finding(outcome: str, operation: str) -> DoctorFinding:
    titles = {
        "cancelled": "OpenOCD operation was cancelled",
        "timed_out": "OpenOCD operation timed out",
        "launch_failed": "OpenOCD could not be launched",
    }
    return DoctorFinding(
        stage="flash",
        severity="fail",
        code=f"OPENOCD_{operation.upper()}_{outcome.upper()}",
        title=titles.get(outcome, "OpenOCD operation failed"),
        message=f"The OpenOCD {operation} operation ended with outcome: {outcome}.",
    )


def _safe_log_component(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    return cleaned.strip("._") or "target"


def _timeout_text(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _append_text(existing: str, extra: str) -> str:
    if not existing:
        return extra
    return existing + ("" if existing.endswith("\n") else "\n") + extra


def _evidence(command_preview: str, message: str) -> str:
    return f"[KeilTool] Command: {command_preview}\n[KeilTool] {message}\n"


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
