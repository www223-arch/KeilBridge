from __future__ import annotations

from pathlib import Path
import socket
import time

from keiltool.core.vofa_bridge import (
    JUSTFLOAT_TAIL,
    JustFloatFrameDecoder,
    VofaTcpBridge,
    discover_vofa_executable,
    parse_listen_address,
)


def _frame(*values: bytes) -> bytes:
    return b"".join(values) + JUSTFLOAT_TAIL


def test_justfloat_decoder_preserves_frames_across_arbitrary_chunks():
    first = _frame(b"\x00\x00\x80?", b"\x00\x00\x00@")
    second = _frame(b"\x00\x00@@")
    decoder = JustFloatFrameDecoder()

    assert decoder.feed(first[:3]) == ()
    assert decoder.feed(first[3:-2]) == ()
    assert decoder.feed(first[-2:] + second[:5]) == (first,)
    assert decoder.feed(second[5:]) == (second,)
    assert decoder.stats.frames == 2
    assert decoder.stats.payload_bytes == 12


def test_justfloat_decoder_rejects_non_float_aligned_frame_and_resynchronizes():
    invalid = b"abc" + JUSTFLOAT_TAIL
    valid = _frame(b"\x00\x00\x80?")
    decoder = JustFloatFrameDecoder()

    assert decoder.feed(invalid + valid) == (valid,)
    assert decoder.stats.invalid_frames == 1
    assert decoder.stats.frames == 1


def test_vofa_bridge_forwards_complete_frames_to_tcp_client(tmp_path):
    bridge = VofaTcpBridge("127.0.0.1", 0, raw_output=tmp_path / "capture.bin")
    bridge.start()
    client = socket.create_connection(bridge.listen_address, timeout=2)
    client.settimeout(2)
    first = _frame(b"\x00\x00\x80?")
    second = _frame(b"\x00\x00\x00@")

    try:
        bridge.feed(first[:3])
        bridge.feed(first[3:] + second)
        received = b""
        deadline = time.monotonic() + 2
        while len(received) < len(first + second) and time.monotonic() < deadline:
            received += client.recv(4096)
    finally:
        client.close()
        bridge.stop()

    assert received == first + second
    assert (tmp_path / "capture.bin").read_bytes() == first + second
    assert bridge.stats.frames_forwarded == 2
    assert bridge.stats.bytes_forwarded == len(first + second)
    assert bridge.stats.clients_connected == 1


def test_parse_listen_address_accepts_host_port_and_rejects_invalid_port():
    assert parse_listen_address("127.0.0.1:1347") == ("127.0.0.1", 1347)

    try:
        parse_listen_address("127.0.0.1:70000")
    except ValueError as exc:
        assert "port" in str(exc).lower()
    else:
        raise AssertionError("invalid port was accepted")


def test_discover_vofa_prefers_remembered_executable(tmp_path):
    executable = tmp_path / "vofa+.exe"
    executable.write_bytes(b"MZ")

    assert discover_vofa_executable(str(executable), candidates=()) == executable


def test_discover_vofa_ignores_missing_remembered_path(tmp_path):
    executable = tmp_path / "portable" / "vofa+.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"MZ")

    assert discover_vofa_executable(
        str(tmp_path / "old" / "vofa+.exe"),
        candidates=(executable,),
    ) == executable


def test_vofa_bridge_stop_records_flush_failure_without_breaking_cleanup():
    class FlushFailingStream:
        closed = False

        def flush(self):
            raise OSError("disk full")

        def close(self):
            self.closed = True

    bridge = VofaTcpBridge()
    stream = FlushFailingStream()
    bridge._raw_stream = stream

    bridge.stop()

    assert stream.closed
    assert "disk full" in bridge.stats.last_error
