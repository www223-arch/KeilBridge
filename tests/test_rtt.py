from __future__ import annotations

from pathlib import Path
import queue
import socket
import threading
import time

from keiltool.core.openocd_backend import OpenOcdConfig
from keiltool.core.rtt import RttRequest, RttSession, build_rtt_command


CONFIG = OpenOcdConfig(
    executable=Path("C:/tools/openocd.exe"),
    scripts_dir=Path("C:/tools/scripts"),
    interface_cfg="interface/stlink.cfg",
    target_cfg="target/stm32f3x.cfg",
)


def test_auto_scan_uses_full_ram_range():
    request = RttRequest(scan_address=0x20000000, scan_size=0x10000, port=19021)

    command = build_rtt_command(CONFIG, request)
    joined = " ".join(command)

    assert 'rtt setup 0x20000000 0x10000 "SEGGER RTT"' in joined
    assert "reset" not in joined.lower()
    assert "halt" not in joined.lower()
    assert "resume" not in joined.lower()
    assert "shutdown" not in joined.lower()


def test_manual_address_uses_0x100_search_window():
    request = RttRequest(scan_address=0x20006CAC, scan_size=0x100, port=19021)

    assert "rtt setup 0x20006CAC 0x100" in " ".join(build_rtt_command(CONFIG, request))


class FakeProcess:
    def __init__(self, stdout_lines: tuple[str, ...] = (), stderr_lines: tuple[str, ...] = (), returncode: int | None = None):
        self.stdout = _LineStream(stdout_lines)
        self.stderr = _LineStream(stderr_lines)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise TimeoutError("process is still running")
        return self.returncode


class _LineStream:
    def __init__(self, lines: tuple[str, ...]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


def _start_rtt_server(payload: bytes) -> tuple[int, threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(payload[:2])
                time.sleep(0.01)
                connection.sendall(payload[2:])
        finally:
            listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    return port, thread


def _collect_text(session: RttSession, timeout: float = 1.0) -> str:
    deadline = time.monotonic() + timeout
    chunks: list[str] = []
    while time.monotonic() < deadline:
        try:
            event = session.events.get(timeout=0.02)
        except queue.Empty:
            continue
        if event.kind == "data":
            chunks.append(event.text)
        if event.kind == "eof":
            return "".join(chunks)
        if event.kind == "error":
            raise AssertionError(event.message)
    raise AssertionError("RTT server data was not received before timeout")


def _next_event(session: RttSession, kind: str, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = session.events.get(timeout=0.02)
        except queue.Empty:
            continue
        if event.kind == kind:
            return event
    raise AssertionError(f"RTT event {kind!r} was not emitted before timeout")


def test_session_decodes_fragmented_utf8_and_writes_log(tmp_path):
    expected = "电机启动\n"
    port, server = _start_rtt_server(expected.encode("utf-8"))
    process = FakeProcess(stdout_lines=("Info : rtt: Found control block at 0x20000000\n",))
    log_path = tmp_path / "rtt.log"
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000, port=port),
        log_path,
        popen_factory=lambda *args, **kwargs: process,
        connect_timeout=0.5,
    )

    session.start()
    text = _collect_text(session)
    server.join(timeout=1)
    session.stop()

    assert text == expected
    assert log_path.read_text(encoding="utf-8") == expected
    assert not server.is_alive()
    assert session.wait(timeout=1)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration


def test_session_reports_error_when_control_block_is_not_found_before_timeout(tmp_path):
    clock = FakeClock()
    process = FakeProcess()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        connect_timeout=0.1,
        retry_interval=0.05,
    )

    session.start()
    event = _next_event(session, "error")
    session.stop()

    assert "control block" in event.message.lower()
    assert session.wait(timeout=1)


def test_session_reports_error_when_openocd_exits_before_tcp_connection(tmp_path):
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))

    def failed_connect(*args, **kwargs):
        process.returncode = 1
        raise OSError("connection refused")

    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=failed_connect,
        connect_timeout=0.5,
    )

    session.start()
    event = _next_event(session, "error")
    session.stop()

    assert "before the rtt tcp connection" in event.message.lower()
    assert session.wait(timeout=1)


class BlockingSocket:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.timeout: float | None | str = "not-configured"

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def recv(self, size: int) -> bytes:
        self.closed.wait(timeout=1)
        raise OSError("socket closed")

    def close(self) -> None:
        self.closed.set()


class StubbornProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True


def test_stop_closes_resources_then_terminates_and_kills_after_timeout(tmp_path):
    clock = FakeClock()
    process = StubbornProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connection = BlockingSocket()
    log_path = tmp_path / "rtt.log"
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        log_path,
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=lambda *args, **kwargs: connection,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        stop_timeout=0.1,
        retry_interval=0.05,
    )

    session.start()
    _next_event(session, "connected")

    assert connection.timeout is None

    session.stop()

    assert connection.closed.is_set()
    assert process.terminated is True
    assert process.killed is True
    assert clock.value >= 0.1
    assert log_path.exists()
    assert session.wait(timeout=1)
