from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from keiltool import cli
from keiltool.core.hardware_context import MemoryRange


def _context(tmp_path: Path):
    return SimpleNamespace(
        source="device",
        device="GD32F303CC",
        target_name="GD32F303CC",
        target=SimpleNamespace(name="GD32F303CC"),
        config=SimpleNamespace(
            executable=tmp_path / "openocd.exe",
            scripts_dir=tmp_path / "scripts",
            interface_cfg="interface/stlink.cfg",
            target_cfg="target/stm32f3x.cfg",
        ),
        flash=MemoryRange(0x08000000, 0x40000),
        ram=MemoryRange(0x20000000, 0x10000),
        logs_dir=tmp_path / "logs",
        workspace_root=tmp_path,
    )


def test_hardware_parsers_require_exactly_one_target_source():
    parser = cli.build_parser()

    project = parser.parse_args(["connect", "--project", "app.uvprojx"])
    device = parser.parse_args(["connect", "--device", "GD32F303CC"])

    assert project.project == Path("app.uvprojx")
    assert not project.device
    assert device.device == "GD32F303CC"
    assert device.project is None
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["connect"])
    with pytest.raises(SystemExit) as conflicting:
        parser.parse_args(
            ["connect", "--project", "app.uvprojx", "--device", "GD32F303CC"]
        )
    assert missing.value.code == 2
    assert conflicting.value.code == 2


def test_connect_json_has_stable_machine_contract(tmp_path, monkeypatch, capsys):
    context = _context(tmp_path)
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: context)

    def fake_connect(_config, _log_dir, **kwargs):
        return SimpleNamespace(
            success=True,
            returncode=0,
            outcome="succeeded",
            command=["openocd", "-f", "target/stm32f3x.cfg"],
            stdout="connected\n",
            stderr="",
            stdout_log=kwargs["stdout_log_path"],
            stderr_log=kwargs["stderr_log_path"],
            findings=[],
        )

    monkeypatch.setattr(cli, "run_connection_check", fake_connect)
    args = cli.build_parser().parse_args(
        [
            "connect",
            "--device",
            "GD32F303CC",
            "--logs-dir",
            str(tmp_path / "logs"),
            "--output-format",
            "json",
        ]
    )

    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "keiltool.hardware.v1"
    assert payload["command"] == "connect"
    assert payload["success"] is True
    assert payload["device"] == "GD32F303CC"
    assert payload["openocd"]["target_cfg"] == "target/stm32f3x.cfg"


def test_flash_read_cli_reads_exact_context_range_and_reports_artifact(
    tmp_path, monkeypatch, capsys
):
    context = _context(tmp_path)
    output = tmp_path / "flash.bin"
    captured = {}
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: context)

    def fake_read(_config, request, _log_dir, **kwargs):
        captured["request"] = request
        output.write_bytes(b"flash")
        return SimpleNamespace(
            success=True,
            returncode=0,
            outcome="succeeded",
            command=["openocd", "-c", "dump_image"],
            stdout="",
            stderr="",
            stdout_log=kwargs["stdout_log_path"],
            stderr_log=kwargs["stderr_log_path"],
            findings=[],
            output=output,
            address=request.address,
            requested_size=request.size,
            actual_size=request.size,
            sha256="abc123",
        )

    monkeypatch.setattr(cli, "run_flash_read", fake_read)
    args = cli.build_parser().parse_args(
        [
            "flash-read",
            "--device",
            "GD32F303CC",
            "--output",
            str(output),
            "--logs-dir",
            str(tmp_path / "logs"),
            "--output-format",
            "json",
        ]
    )

    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert captured["request"].address == 0x08000000
    assert captured["request"].size == 0x40000
    assert payload["artifact"]["path"] == str(output.resolve())
    assert payload["artifact"]["sha256"] == "abc123"
    assert payload["artifact"]["size"] == 0x40000


def test_device_flash_requires_explicit_firmware(tmp_path, monkeypatch):
    context = _context(tmp_path)
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: context)
    args = cli.build_parser().parse_args(["flash", "--device", "GD32F303CC"])

    with pytest.raises(SystemExit, match="--firmware"):
        args.func(args)
