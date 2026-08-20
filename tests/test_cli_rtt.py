from __future__ import annotations

import json
from pathlib import Path
import queue
from types import SimpleNamespace

import pytest

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
        self.sent: list[bytes] = []
        self.kwargs = kwargs
        FakeRttSession.last = self

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def wait(self, timeout=None):
        return True

    def send_bytes(self, data, *, channel=None):
        payload = bytes(data)
        self.sent.append((channel, payload))
        return len(payload)


def _run(tmp_path, monkeypatch, output_format: str, *extra_args: str):
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
            *extra_args,
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


def test_rtt_raw_output_file_preserves_bytes_across_receive_boundaries(
    tmp_path,
    monkeypatch,
    capsysbinary,
):
    chunks = (
        b"\x00\x80",
        b"\xff\x10\x00",
        b"\x80\xff\x00tail",
    )
    FakeRttSession.event_list = (
        RttEvent("connected", message="connected"),
        *(RttEvent("raw", data=chunk) for chunk in chunks),
        RttEvent("eof", message="RTT TCP connection closed by peer"),
    )
    output = tmp_path / "foc-sweep.bin"

    assert (
        _run(
            tmp_path,
            monkeypatch,
            "raw",
            "--output",
            str(output),
            "--channel",
            "1",
            "--port",
            "19022",
        )
        == 0
    )

    capture = capsysbinary.readouterr()
    expected = b"".join(chunks)
    assert cli._RTT_RAW_FILE_BUFFER_SIZE >= 1024 * 1024
    assert capture.out == b""
    assert output.read_bytes() == expected
    assert FakeRttSession.last.request.channel == 1
    assert FakeRttSession.last.request.port == 19022
    assert FakeRttSession.last.kwargs["parse_records"] is False
    assert f"received_bytes={len(expected)}".encode() in capture.err
    assert f"file_bytes={len(expected)}".encode() in capture.err
    assert b"disconnect=RTT TCP connection closed by peer" in capture.err


def test_rtt_raw_output_reports_receive_error_and_preserves_received_bytes(
    tmp_path,
    monkeypatch,
    capsysbinary,
):
    payload = b"\x00\x80\xffpartial"
    FakeRttSession.event_list = (
        RttEvent("connected", message="connected"),
        RttEvent("raw", data=payload),
        RttEvent("error", message="RTT TCP receive failed: connection reset"),
    )
    output = tmp_path / "partial.bin"

    assert _run(tmp_path, monkeypatch, "raw", "--output", str(output)) == 1

    capture = capsysbinary.readouterr()
    assert output.read_bytes() == payload
    assert f"received_bytes={len(payload)}".encode() in capture.err
    assert f"file_bytes={len(payload)}".encode() in capture.err
    assert b"error=RTT TCP receive failed: connection reset" in capture.err


def test_rtt_output_requires_raw_format(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="--output requires --format raw"):
        _run(
            tmp_path,
            monkeypatch,
            "text",
            "--output",
            str(tmp_path / "not-raw.bin"),
        )


def test_rtt_raw_sink_closes_file_when_final_flush_fails(tmp_path):
    class FlushFailingStream:
        closed = False

        def flush(self):
            raise OSError("disk flush failed")

        def close(self):
            self.closed = True

    stream = FlushFailingStream()
    sink = cli._RttRawSink(tmp_path / "capture.bin")
    sink._stream = stream

    with pytest.raises(OSError, match="disk flush failed"):
        sink.close()

    assert stream.closed


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


def test_rtt_parser_exposes_vofa_bridge_options():
    args = cli.build_parser().parse_args(
        [
            "rtt",
            "--device",
            "GD32F303CC",
            "--vofa-listen",
            "127.0.0.1:1347",
            "--vofa-executable",
            "D:/tools/vofa+.exe",
        ]
    )

    assert args.vofa_listen == "127.0.0.1:1347"
    assert args.vofa_executable == Path("D:/tools/vofa+.exe")
    assert args.no_verify_channel_name is False
    assert args.text_port == 19021


def test_rtt_does_not_start_vofa_bridge_before_hardware_validation(monkeypatch):
    started = []

    class FakeBridge:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            started.append(True)

    monkeypatch.setattr(cli, "VofaTcpBridge", FakeBridge)
    monkeypatch.setattr(
        cli,
        "resolve_hardware_context",
        lambda _selection: (_ for _ in ()).throw(SystemExit("invalid target")),
    )
    args = cli.build_parser().parse_args(
        [
            "rtt",
            "--device",
            "UNKNOWN",
            "--format",
            "raw",
            "--vofa-listen",
            "127.0.0.1:1347",
        ]
    )

    with pytest.raises(SystemExit, match="invalid target"):
        args.func(args)

    assert started == []


def test_rtt_vofa_bridge_receives_raw_events(tmp_path, monkeypatch, capsysbinary):
    payload = b"\x00\x00\x80?\x00\x00\x80\x7f"
    FakeRttSession.event_list = (
        RttEvent("connected", message="text connected", channel=0),
        RttEvent("connected", message="scope connected", channel=1),
        RttEvent("raw", data=b"I/boot ready\n", channel=0),
        RttEvent("data", text="I/boot ready\n", level=RttLevel.INFO, terminal=0, channel=0),
        RttEvent("raw", data=payload, channel=1),
        RttEvent("eof", message="closed", channel=1),
    )

    class FakeBridge:
        last = None

        def __init__(self, host, port, **kwargs):
            self.listen_address = (host, port)
            self.kwargs = kwargs
            self.payloads = []
            self.started = False
            self.stopped = False
            self.stats = SimpleNamespace(
                frames_received=1,
                frames_forwarded=1,
                frames_dropped=0,
                invalid_frames=0,
                clients_connected=1,
                last_error="",
            )
            FakeBridge.last = self

        def start(self):
            self.started = True

        def feed(self, data):
            self.payloads.append(data)

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(cli, "VofaTcpBridge", FakeBridge)
    output = tmp_path / "capture.bin"

    assert (
        _run(
            tmp_path,
            monkeypatch,
            "raw",
            "--output",
            str(output),
            "--vofa-listen",
            "127.0.0.1:1347",
        )
        == 0
    )

    capture = capsysbinary.readouterr()
    assert FakeBridge.last.started
    assert FakeBridge.last.stopped
    assert FakeBridge.last.payloads == [payload]
    assert FakeBridge.last.kwargs["expected_float_count"] == 15
    reverse_payload = b"\x00\x80\xffcommand"
    assert FakeBridge.last.kwargs["reverse_sink"](reverse_payload) == len(reverse_payload)
    assert FakeRttSession.last.sent == [(1, reverse_payload)]
    assert FakeRttSession.last.request.expected_channel_name == "Scope"
    assert FakeRttSession.last.kwargs["parse_records"] is False
    assert FakeRttSession.last.request.port == 19022
    assert FakeRttSession.last.request.additional_channels[0].channel == 0
    assert FakeRttSession.last.request.additional_channels[0].port == 19021
    assert FakeRttSession.last.request.additional_channels[0].parse_records is True
    assert output.read_bytes() == payload
    assert b"frames_forwarded=1" in capture.err
    assert FakeRttSession.last.stopped
    guides = tuple((tmp_path / "logs").glob("*/scope-channels.txt"))
    assert len(guides) == 1
    assert "I14 = euler_9dof_deg.yaw" in guides[0].read_text(encoding="utf-8")


def test_rtt_vofa_allows_explicitly_disabling_channel_name_verification(
    tmp_path,
    monkeypatch,
    capsysbinary,
):
    FakeRttSession.event_list = (
        RttEvent("connected", message="connected"),
        RttEvent("eof", message="closed"),
    )

    assert (
        _run(
            tmp_path,
            monkeypatch,
            "raw",
            "--output",
            str(tmp_path / "capture.bin"),
            "--vofa-listen",
            "127.0.0.1:1347",
            "--no-verify-channel-name",
        )
        == 0
    )

    capsysbinary.readouterr()
    assert FakeRttSession.last.request.expected_channel_name is None


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
