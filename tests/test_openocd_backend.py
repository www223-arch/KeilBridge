from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import threading

import pytest

from keiltool.core.openocd_backend import (
    FlashRequest,
    OpenOcdConfig,
    build_connection_command,
    build_flash_command,
    parse_address,
    run_connection_check,
    run_flash,
)


CONFIG = OpenOcdConfig(
    executable=Path("openocd"),
    scripts_dir=None,
    interface_cfg="interface/stlink.cfg",
    target_cfg="target/stm32f3x.cfg",
)


@dataclass
class FakeCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


class FakeRunner:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.completed = FakeCompletedProcess(returncode, stdout, stderr)
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, command: list[str], *, cwd: Path | None, text: bool, capture_output: bool) -> FakeCompletedProcess:
        self.calls.append((command, cwd))
        return self.completed


def test_build_hex_flash_command_uses_embedded_addresses(tmp_path):
    request = FlashRequest(tmp_path / "full.hex")

    command = build_flash_command(CONFIG, request)

    assert command[-2:] == ["-c", f"program {(tmp_path / 'full.hex').as_posix()} verify reset exit"]


def test_build_bin_flash_command_includes_base_address(tmp_path):
    request = FlashRequest(tmp_path / "full.bin", base_address=0x08004000)

    command = build_flash_command(CONFIG, request)

    assert command[-1].endswith("full.bin 0x08004000 verify reset exit")


def test_build_elf_flash_command_preserves_legacy_program_contract(tmp_path):
    request = FlashRequest(tmp_path / "motor.elf")

    command = build_flash_command(CONFIG, request)

    assert command[-1].endswith("motor.elf verify reset exit")


def test_build_flash_command_quotes_tcl_metacharacters_in_firmware_path(tmp_path):
    firmware = tmp_path / "firmware {release};$[slot one].hex"
    request = FlashRequest(firmware)

    command = build_flash_command(CONFIG, request)

    path = firmware.resolve().as_posix()
    assert command[-1] == f'program "{path.replace("$", "\\$").replace("[", "\\[").replace("]", "\\]")}" verify reset exit'


def test_connection_check_does_not_reset_or_halt():
    command = build_connection_command(CONFIG)

    joined = " ".join(command).lower()
    assert "init" in joined
    assert "shutdown" in joined
    assert "reset" not in joined
    assert "halt" not in joined


def test_parse_address_accepts_decimal_and_hexadecimal_values():
    assert parse_address("0x08004000") == 0x08004000
    assert parse_address("134217728") == 0x08000000
    assert parse_address(0x08008000) == 0x08008000


def test_parse_address_rejects_negative_and_invalid_values():
    with pytest.raises(ValueError, match="non-negative"):
        parse_address("-1")
    with pytest.raises(ValueError, match="valid integer"):
        parse_address("not-an-address")


def test_build_flash_command_rejects_non_firmware_extensions(tmp_path):
    with pytest.raises(ValueError, match=r"\.hex.*\.bin.*\.elf.*\.axf"):
        build_flash_command(CONFIG, FlashRequest(tmp_path / "firmware.txt"))


def test_run_flash_requires_program_and_verify_markers(tmp_path):
    firmware = tmp_path / "full.hex"
    firmware.write_text(":00000001FF\n", encoding="utf-8")
    runner = FakeRunner(returncode=0, stdout="Programming Finished\nVerified OK\n", stderr="")

    result = run_flash(CONFIG, FlashRequest(firmware), tmp_path, runner=runner)

    assert result.success is True
    assert result.stdout_log.exists()
    assert result.stdout_log.read_text(encoding="utf-8") == "Programming Finished\nVerified OK\n"


def test_run_flash_fails_when_verify_evidence_is_missing(tmp_path):
    firmware = tmp_path / "full.hex"
    firmware.write_text(":00000001FF\n", encoding="utf-8")
    runner = FakeRunner(returncode=0, stdout="Programming Finished\n", stderr="")

    result = run_flash(CONFIG, FlashRequest(firmware), tmp_path, runner=runner)

    assert result.success is False
    assert result.returncode == 0


def test_run_flash_uses_unique_log_paths_within_the_same_second(tmp_path):
    firmware = tmp_path / "full.hex"
    firmware.write_text(":00000001FF\n", encoding="utf-8")
    runner = FakeRunner(returncode=0, stdout="Programming Finished\nVerified OK\n", stderr="")

    first = run_flash(CONFIG, FlashRequest(firmware), tmp_path, runner=runner)
    second = run_flash(CONFIG, FlashRequest(firmware), tmp_path, runner=runner)

    assert first.stdout_log != second.stdout_log
    assert first.stderr_log != second.stderr_log
    assert first.stdout_log.exists()
    assert second.stdout_log.exists()


def test_run_connection_check_requires_target_and_core_evidence(tmp_path):
    runner = FakeRunner(returncode=0, stdout="TargetName Type Endian TapName State\nstm32.cpu Cortex-M4\n", stderr="")

    result = run_connection_check(CONFIG, tmp_path, runner=runner)

    assert result.success is True
    assert result.stdout_log.exists()


def test_run_connection_check_rejects_a_clean_exit_without_target_evidence(tmp_path):
    runner = FakeRunner(returncode=0, stdout="OpenOCD ready\n", stderr="")

    result = run_connection_check(CONFIG, tmp_path, runner=runner)

    assert result.success is False


def test_connection_and_flash_evidence_stems_include_sanitized_target_and_microseconds(tmp_path):
    firmware = tmp_path / "full.hex"
    firmware.write_text(":00000001FF\n", encoding="ascii")
    connection_runner = FakeRunner(
        returncode=0,
        stdout="TargetName Type Endian TapName State\nstm32.cpu Cortex-M4\n",
        stderr="",
    )
    flash_runner = FakeRunner(
        returncode=0,
        stdout="Programming Finished\nVerified OK\n",
        stderr="",
    )

    connection = run_connection_check(
        CONFIG,
        tmp_path,
        runner=connection_runner,
        target_name="Motor Target",
    )
    flash = run_flash(
        CONFIG,
        FlashRequest(firmware),
        tmp_path,
        runner=flash_runner,
        target_name="Motor Target",
    )

    assert re.fullmatch(r"connection_Motor_Target_\d{8}-\d{6}-\d{6}\.out\.log", connection.stdout_log.name)
    assert re.fullmatch(r"flash_Motor_Target_\d{8}-\d{6}-\d{6}\.err\.log", flash.stderr_log.name)


class HungProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.communicate_entered = threading.Event()
        self.terminated = False
        self.killed = False
        self.command = []

    def communicate(self, timeout=None):
        self.communicate_entered.set()
        if self.killed:
            return ("鐩爣杩炴帴涓?\n", "OpenOCD killed\n")
        raise subprocess.TimeoutExpired(
            self.command,
            timeout,
            output="鐩爣杩炴帴涓?\n",
            stderr="",
        )

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9

    def poll(self):
        return self.returncode


class KillFailingProcess(HungProcess):
    def communicate(self, timeout=None):
        self.communicate_entered.set()
        if self.returncode is not None:
            return ("", "OpenOCD exited after cleanup retry\n")
        raise subprocess.TimeoutExpired(self.command, timeout, output="", stderr="")

    def kill(self):
        self.killed = True
        raise OSError("access denied")


class UnreapedKilledProcess(HungProcess):
    def communicate(self, timeout=None):
        self.communicate_entered.set()
        if self.returncode is not None:
            return ("", "OpenOCD exit reaped\n")
        raise subprocess.TimeoutExpired(self.command, timeout, output="", stderr="")

    def kill(self):
        self.killed = True


@pytest.mark.parametrize("process_type", [KillFailingProcess, UnreapedKilledProcess])
def test_incomplete_one_shot_cleanup_retains_process_until_retry_confirms_exit(tmp_path, process_type):
    from keiltool.core.openocd_backend import OpenOcdOperation

    process = process_type()
    operation = OpenOcdOperation(
        timeout=0.01,
        terminate_timeout=0.01,
        kill_timeout=0.01,
        poll_interval=0.001,
        popen_factory=lambda command, **kwargs: process,
    )

    result = run_connection_check(CONFIG, tmp_path, operation=operation)

    assert result.outcome == "incomplete"
    assert operation.cleanup_pending is True

    process.returncode = -9
    cleanup = operation.retry_cleanup()

    assert cleanup.complete is True
    assert operation.cleanup_pending is False


def test_cancellable_operation_terminates_then_kills_and_returns_utf8_evidence(tmp_path):
    from keiltool.core.openocd_backend import OpenOcdOperation

    process = HungProcess()

    def popen(command, **kwargs):
        process.command = command
        return process

    operation = OpenOcdOperation(
        timeout=5.0,
        terminate_timeout=0.01,
        kill_timeout=0.01,
        poll_interval=0.001,
        popen_factory=popen,
    )
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            run_connection_check(
                CONFIG,
                tmp_path,
                operation=operation,
                target_name="Debug Target",
            )
        )
    )
    worker.start()
    assert process.communicate_entered.wait(timeout=1)

    operation.cancel()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert process.terminated is True
    assert process.killed is True
    assert results[0].outcome == "cancelled"
    assert "鐩爣杩炴帴涓?" in results[0].stdout_log.read_text(encoding="utf-8")


def test_one_shot_timeout_returns_structured_failure_and_logs(tmp_path):
    from keiltool.core.openocd_backend import OpenOcdOperation

    process = HungProcess()
    operation = OpenOcdOperation(
        timeout=0.01,
        terminate_timeout=0.01,
        kill_timeout=0.01,
        poll_interval=0.001,
        popen_factory=lambda command, **kwargs: process,
    )

    result = run_connection_check(
        CONFIG,
        tmp_path,
        operation=operation,
        target_name="Motor Target",
    )

    assert result.success is False
    assert result.outcome == "timed_out"
    assert process.terminated is True
    assert process.killed is True
    assert "timed out" in result.stderr_log.read_text(encoding="utf-8").lower()


def test_launch_failure_returns_structured_result_with_command_and_logs(tmp_path):
    from keiltool.core.openocd_backend import OpenOcdOperation

    def fail_to_launch(command, **kwargs):
        raise OSError("鏃犳硶鍚姩 OpenOCD")

    firmware = tmp_path / "full.hex"
    firmware.write_text(":00000001FF\n", encoding="ascii")
    operation = OpenOcdOperation(popen_factory=fail_to_launch)

    result = run_flash(
        CONFIG,
        FlashRequest(firmware),
        tmp_path,
        operation=operation,
        target_name="Motor Target",
    )

    assert result.success is False
    assert result.outcome == "launch_failed"
    assert result.command == build_flash_command(CONFIG, FlashRequest(firmware))
    evidence = result.stderr_log.read_text(encoding="utf-8")
    assert "鏃犳硶鍚姩 OpenOCD" in evidence
    assert "Command:" in evidence
