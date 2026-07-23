from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    with pytest.raises(ValueError, match=".hex or .bin"):
        build_flash_command(CONFIG, FlashRequest(tmp_path / "firmware.elf"))


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


def test_run_connection_check_requires_target_and_core_evidence(tmp_path):
    runner = FakeRunner(returncode=0, stdout="TargetName Type Endian TapName State\nstm32.cpu Cortex-M4\n", stderr="")

    result = run_connection_check(CONFIG, tmp_path, runner=runner)

    assert result.success is True
    assert result.stdout_log.exists()


def test_run_connection_check_rejects_a_clean_exit_without_target_evidence(tmp_path):
    runner = FakeRunner(returncode=0, stdout="OpenOCD ready\n", stderr="")

    result = run_connection_check(CONFIG, tmp_path, runner=runner)

    assert result.success is False
