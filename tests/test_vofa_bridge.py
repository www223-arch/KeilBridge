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


def test_bilbopro_decoder_rejects_frames_that_are_not_15_floats():
    wrong = _frame(*(b"\x00\x00\x00\x00" for _ in range(14)))
    valid = _frame(*(b"\x00\x00\x00\x00" for _ in range(15)))
    decoder = JustFloatFrameDecoder(expected_float_count=15)

    assert decoder.feed(wrong + valid) == (valid,)
    assert decoder.stats.frame_size_mismatches == 1
    assert decoder.stats.invalid_frames == 1


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


def test_vofa_bridge_forwards_client_bytes_back_to_rtt_without_decoding(tmp_path):
    chunks: list[bytes] = []

    def reverse_sink(data: bytes) -> int:
        chunks.append(bytes(data))
        return len(data)

    bridge = VofaTcpBridge(
        "127.0.0.1",
        0,
        raw_output=tmp_path / "capture.bin",
        reverse_output=tmp_path / "vofa-to-mcu.bin",
        reverse_sink=reverse_sink,
    )
    bridge.start()
    client = socket.create_connection(bridge.listen_address, timeout=2)
    payload_parts = (b"\x00\x80", b"\xffcmd", b"\x00\r\n")

    try:
        for part in payload_parts:
            client.sendall(part)
            time.sleep(0.02)
        deadline = time.monotonic() + 2
        while bridge.stats.reverse_bytes_forwarded < sum(map(len, payload_parts)):
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        client.close()
        bridge.stop()

    assert b"".join(chunks) == b"".join(payload_parts)
    assert bridge.stats.reverse_bytes_received == len(b"".join(payload_parts))
    assert bridge.stats.reverse_bytes_forwarded == len(b"".join(payload_parts))
    assert bridge.stats.reverse_errors == 0
    assert (tmp_path / "vofa-to-mcu.bin").read_bytes() == b"".join(payload_parts)
    assert bridge.stats.clients_connected == 1


def test_vofa_bridge_operator_send_uses_same_reverse_sink_and_capture(tmp_path):
    chunks: list[bytes] = []

    def reverse_sink(data: bytes) -> int:
        chunks.append(bytes(data))
        return len(data)

    bridge = VofaTcpBridge(
        "127.0.0.1",
        0,
        reverse_output=tmp_path / "vofa-to-mcu.bin",
        reverse_sink=reverse_sink,
    )
    bridge.start()
    frame = bytes.fromhex("B1 50 01 09 2A 00 00 00")

    try:
        assert bridge.send_reverse(frame) == len(frame)
    finally:
        bridge.stop()

    assert chunks == [frame]
    assert (tmp_path / "vofa-to-mcu.bin").read_bytes() == frame
    assert bridge.stats.reverse_bytes_received == len(frame)
    assert bridge.stats.reverse_bytes_forwarded == len(frame)


def test_bilbopro_bridge_does_not_forward_wrong_float_count(tmp_path):
    bridge = VofaTcpBridge(
        "127.0.0.1",
        0,
        raw_output=tmp_path / "capture.bin",
        expected_float_count=15,
    )
    bridge.start()
    client = socket.create_connection(bridge.listen_address, timeout=2)
    client.settimeout(2)
    wrong = _frame(*(b"\x00\x00\x00\x00" for _ in range(14)))
    valid = _frame(*(b"\x00\x00\x00\x00" for _ in range(15)))

    try:
        bridge.feed(wrong[:17])
        bridge.feed(wrong[17:] + valid[:31])
        bridge.feed(valid[31:])
        received = client.recv(len(valid))
    finally:
        client.close()
        bridge.stop()

    assert received == valid
    assert (tmp_path / "capture.bin").read_bytes() == wrong + valid
    assert bridge.stats.frames_forwarded == 1
    assert bridge.stats.frame_size_mismatches == 1
    assert "expected 15" in bridge.stats.last_error


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


def test_vofa_bridge_closes_both_capture_files_when_reverse_flush_fails():
    class RecordingStream:
        def __init__(self, *, fail_flush: bool = False) -> None:
            self.fail_flush = fail_flush
            self.closed = False

        def flush(self):
            if self.fail_flush:
                raise OSError("reverse disk full")

        def close(self):
            self.closed = True

    bridge = VofaTcpBridge()
    upstream = RecordingStream()
    reverse = RecordingStream(fail_flush=True)
    bridge._raw_stream = upstream
    bridge._reverse_stream = reverse

    bridge.stop()

    assert upstream.closed
    assert reverse.closed
    assert "reverse disk full" in bridge.stats.last_error


def test_vofa_bridge_reports_reverse_sink_failure_and_disconnects_client():
    def fail(_data: bytes) -> int:
        raise OSError("RTT down-channel unavailable")

    bridge = VofaTcpBridge("127.0.0.1", 0, reverse_sink=fail)
    bridge.start()
    client = socket.create_connection(bridge.listen_address, timeout=2)

    try:
        client.sendall(b"command")
        deadline = time.monotonic() + 2
        while bridge.stats.reverse_errors == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        client.close()
        bridge.stop()

    assert bridge.stats.reverse_bytes_received == len(b"command")
    assert bridge.stats.reverse_bytes_forwarded == 0
    assert bridge.stats.reverse_errors == 1
    assert bridge.stats.active_clients == 0
    assert "down-channel unavailable" in bridge.stats.last_error
