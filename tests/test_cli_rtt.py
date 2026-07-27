from __future__ import annotations

import json
from pathlib import Path
import queue
from types import SimpleNamespace

from keiltool import cli
from keiltool.core.hardware_context import MemoryRange
from keiltool.core.rtt import RttEvent
from keiltool.core.rtt_log import RttLevel


def _context(tmp_path: Path):
    return SimpleNamespace(
        source="device",
        device="GD32F303CC",
        target_name="GD32F303CC",
        target=SimpleNamespace(name="GD32F303CC"),
        config=SimpleNamespace(target_cfg="target/stm32f3x.cfg"),
        flash=MemoryRange(0x08000000, 0x40000),
        ram=MemoryRange(0x20000000, 0x10000),
        logs_dir=tmp_path / "logs",
        workspace_root=tmp_path,
    )


class FakeRttSession:
    event_list: tuple[RttEvent, ...] = ()
    last = None

    def __init__(self, config, request, log_path, **kwargs):
        self.config = config
        self.request = request
        self.log_path = log_path
        self.events = queue.Queue()
        for event in self.event_list:
            self.events.put(event)
        self.started = False
        self.stopped = False
        FakeRttSession.last = self

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def wait(self, timeout=None):
        return True


def _run(tmp_path, monkeypatch, output_format: str):
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: _context(tmp_path))
    monkeypatch.setattr(cli, "RttSession", FakeRttSession)
    args = cli.build_parser().parse_args(
        [
            "rtt",
            "--device",
            "GD32F303CC",
            "--logs-dir",
            str(tmp_path / "logs"),
            "--format",
            output_format,
        ]
    )
    return args.func(args)


def test_rtt_text_and_jsonl_formats_use_structured_records(tmp_path, monkeypatch, capsys):
    FakeRttSession.event_list = (
        RttEvent("connected", message="connected"),
        RttEvent("raw", data=b"I/ready\n"),
        RttEvent("data", text="I/ready\n", level=RttLevel.INFO, terminal=0),
        RttEvent("eof", message="closed"),
    )

    assert _run(tmp_path, monkeypatch, "text") == 0
    text_capture = capsys.readouterr()
    assert text_capture.out == "I/ready\n"
    assert "RTT log:" in text_capture.err
    assert FakeRttSession.last.request.scan_address == 0x20000000
    assert FakeRttSession.last.request.scan_size == 0x10000
    assert FakeRttSession.last.stopped

    assert _run(tmp_path, monkeypatch, "jsonl") == 0
    json_capture = capsys.readouterr()
    record = json.loads(json_capture.out)
    assert record == {
        "schema": "keiltool.rtt.v1",
        "type": "data",
        "level": "INFO",
        "terminal": 0,
        "text": "I/ready\n",
    }


def test_rtt_raw_writes_original_bytes(tmp_path, monkeypatch, capsysbinary):
    payload = b"\xff0\x80binary\n"
    FakeRttSession.event_list = (
        RttEvent("connected", message="connected"),
        RttEvent("raw", data=payload),
        RttEvent("data", text="replacement\n", level=RttLevel.INFO, terminal=0),
        RttEvent("eof", message="closed"),
    )

    assert _run(tmp_path, monkeypatch, "raw") == 0

    assert capsysbinary.readouterr().out == payload


def test_rtt_duration_stops_a_connected_session(tmp_path, monkeypatch):
    FakeRttSession.event_list = (RttEvent("connected", message="connected"),)
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: _context(tmp_path))
    monkeypatch.setattr(cli, "RttSession", FakeRttSession)
    args = cli.build_parser().parse_args(
        [
            "rtt",
            "--device",
            "GD32F303CC",
            "--logs-dir",
            str(tmp_path / "logs"),
            "--duration",
            "0.01",
        ]
    )

    assert args.func(args) == 0
    assert FakeRttSession.last.stopped


class InterruptingEvents:
    def get(self, timeout=None):
        raise KeyboardInterrupt

    def get_nowait(self):
        raise queue.Empty


class InterruptingSession(FakeRttSession):
    def __init__(self, config, request, log_path, **kwargs):
        super().__init__(config, request, log_path, **kwargs)
        self.events = InterruptingEvents()


def test_rtt_ctrl_c_stops_session_and_returns_130(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "resolve_hardware_context", lambda _selection: _context(tmp_path))
    monkeypatch.setattr(cli, "RttSession", InterruptingSession)
    args = cli.build_parser().parse_args(
        ["rtt", "--device", "GD32F303CC", "--logs-dir", str(tmp_path / "logs")]
    )

    assert args.func(args) == 130
    assert FakeRttSession.last.stopped
