from __future__ import annotations

from pathlib import Path
import queue
import socket
import subprocess
import threading
import time

import pytest

from keiltool.core.openocd_backend import OpenOcdConfig
from keiltool.core.rtt import RttRequest, RttSession, build_rtt_command
from keiltool.core.rtt_log import RttLevel


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
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
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


def _drain_events(session: RttSession):
    events = []
    while True:
        try:
            events.append(session.events.get_nowait())
        except queue.Empty:
            return events


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


def test_session_emits_structured_levels_and_persists_all_text(tmp_path):
    payload = (
        b"\xff0\x1b[36;22mI/ready\x1b[0m\n"
        b"\xff1D/control loop\n"
        b"\xff2V/sample\n"
    )
    port, server = _start_rtt_server(payload)
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
    events = []
    while True:
        event = session.events.get(timeout=1)
        events.append(event)
        if event.kind == "eof":
            break
        if event.kind == "error":
            raise AssertionError(event.message)
    server.join(timeout=1)
    session.stop()

    data = [event for event in events if event.kind == "data"]
    raw = b"".join(event.data for event in events if event.kind == "raw")
    assert [(event.level, event.terminal, event.text) for event in data] == [
        (RttLevel.INFO, 0, "I/ready\n"),
        (RttLevel.DEBUG, 1, "D/control loop\n"),
        (RttLevel.VERBOSE, 2, "V/sample\n"),
    ]
    assert raw == payload
    assert log_path.read_text(encoding="utf-8") == "I/ready\nD/control loop\nV/sample\n"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.calls = 0

    def monotonic(self) -> float:
        self.calls += 1
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

    def shutdown(self, how: int) -> None:
        self.closed.set()

    def close(self) -> None:
        self.closed.set()


class StubbornProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True


class BlockingTerminateProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.terminate_calls = 0
        self.terminate_entered = threading.Event()
        self.release_terminate = threading.Event()

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.terminate_entered.set()
        self.release_terminate.wait(timeout=1)
        self.returncode = 0


class ExitRaceProcess(FakeProcess):
    def poll(self) -> int | None:
        if self.terminated:
            raise ProcessLookupError("process exited")
        return None

    def terminate(self) -> None:
        self.terminated = True
        raise ProcessLookupError("process exited during terminate")


class KillRaceProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        raise OSError("process exited during kill")


class UnreapedKillProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("openocd", timeout)


class RecordingSocket:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self.operations: list[str] = []
        self.recv_entered = threading.Event()
        self.recv_returned = threading.Event()

    def settimeout(self, value: float | None) -> None:
        self._connection.settimeout(value)

    def recv(self, size: int) -> bytes:
        self.recv_entered.set()
        try:
            return self._connection.recv(size)
        finally:
            self.recv_returned.set()

    def shutdown(self, how: int) -> None:
        self.operations.append("shutdown")
        self._connection.shutdown(how)

    def close(self) -> None:
        self.operations.append("close")
        self._connection.close()


def _start_idle_rtt_server() -> tuple[int, threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                try:
                    connection.recv(1)
                except OSError:
                    pass
        finally:
            listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    return port, thread


def test_stop_shuts_down_real_blocking_socket_and_joins_worker(tmp_path):
    port, server = _start_idle_rtt_server()
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connections: list[RecordingSocket] = []

    def connect(address, timeout):
        connection = RecordingSocket(socket.create_connection(address, timeout=timeout))
        connections.append(connection)
        return connection

    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000, port=port),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=connect,
        stop_timeout=0.2,
    )

    session.start()
    _next_event(session, "connected")
    assert connections[0].recv_entered.wait(timeout=1)
    session.stop()
    server.join(timeout=1)

    assert connections[0].operations[:2] == ["shutdown", "close"]
    assert connections[0].recv_returned.is_set()
    assert not server.is_alive()
    assert session.wait(timeout=0.2)


def test_concurrent_stop_calls_terminate_the_process_once(tmp_path):
    process = BlockingTerminateProcess()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        stop_timeout=0.2,
    )
    session.start()

    first = threading.Thread(target=session.stop)
    second = threading.Thread(target=session.stop)
    first.start()
    assert process.terminate_entered.wait(timeout=1)
    second.start()
    time.sleep(0.05)
    process.release_terminate.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert process.terminate_calls == 1
    assert not first.is_alive()
    assert not second.is_alive()


def test_stop_before_start_prevents_openocd_launch(tmp_path):
    launches: list[object] = []
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: launches.append(args),
    )

    session.stop()

    with pytest.raises(RuntimeError, match="stopped"):
        session.start()

    assert launches == []


def test_stop_handles_process_exit_race_and_emits_one_clean_event(tmp_path):
    process = ExitRaceProcess()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
    )
    session.start()

    session.stop()
    session.stop()

    stopped = [event for event in _drain_events(session) if event.kind == "stopped"]
    assert process.terminated is True
    assert len(stopped) == 1
    assert stopped[0].outcome == "clean"


def test_stop_reaps_process_after_forced_kill_even_when_kill_races(tmp_path):
    clock = FakeClock()
    process = KillRaceProcess()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        stop_timeout=0.1,
        retry_interval=0.05,
    )
    session.start()

    session.stop()

    stopped = [event for event in _drain_events(session) if event.kind == "stopped"]
    assert process.killed is True
    assert process.wait_calls == 1
    assert len(stopped) == 1
    assert stopped[0].outcome == "forced"


class UnresponsiveSocket:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.recv_entered = threading.Event()

    def settimeout(self, value: float | None) -> None:
        pass

    def recv(self, size: int) -> bytes:
        self.recv_entered.set()
        self.release.wait(timeout=1)
        return b""

    def shutdown(self, how: int) -> None:
        pass

    def close(self) -> None:
        pass


class ObservedCondition(threading.Condition):
    def __init__(self) -> None:
        super().__init__(threading.RLock())
        self.wait_entered = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_entered.set()
        return super().wait(timeout)


class FirstTerminalBlockingQueue(queue.Queue):
    def __init__(self) -> None:
        super().__init__()
        self.first_terminal_published = threading.Event()
        self.second_terminal_published = threading.Event()
        self.release_first_publisher = threading.Event()
        self._terminal_count = 0

    def put(self, item, block: bool = True, timeout: float | None = None) -> None:
        super().put(item, block=block, timeout=timeout)
        if getattr(item, "kind", "") != "stopped":
            return
        self._terminal_count += 1
        if self._terminal_count == 1:
            self.first_terminal_published.set()
            self.release_first_publisher.wait(timeout=1)
        else:
            self.second_terminal_published.set()


def test_stop_reports_join_failure_and_emits_one_cleanup_event(tmp_path):
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connection = UnresponsiveSocket()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=lambda *args, **kwargs: connection,
        stop_timeout=0.01,
    )
    session.start()
    _next_event(session, "connected")
    assert connection.recv_entered.wait(timeout=1)

    session.stop()
    events = _drain_events(session)
    connection.release.set()

    assert any(event.kind == "error" and "worker" in event.message.lower() for event in events)
    stopped = [event for event in events if event.kind == "stopped"]
    assert len(stopped) == 1
    assert stopped[0].outcome == "incomplete"
    assert session.wait(timeout=1)


def test_incomplete_cleanup_can_be_retried_until_complete(tmp_path):
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connection = UnresponsiveSocket()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=lambda *args, **kwargs: connection,
        stop_timeout=0.01,
    )
    session.start()
    _next_event(session, "connected")
    assert connection.recv_entered.wait(timeout=1)

    session.stop()
    first = [event for event in _drain_events(session) if event.kind == "stopped"]
    connection.release.set()
    assert session.wait(timeout=1)
    session.stop()
    second = [event for event in _drain_events(session) if event.kind == "stopped"]

    assert [event.outcome for event in first] == ["incomplete"]
    assert [event.outcome for event in second] == ["clean"]


def test_incomplete_cleanup_can_be_retried_from_terminal_event_consumer(tmp_path):
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connection = UnresponsiveSocket()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=lambda *args, **kwargs: connection,
        stop_timeout=0.01,
    )
    lifecycle = ObservedCondition()
    events = FirstTerminalBlockingQueue()
    session._lifecycle = lifecycle
    session.events = events
    session.start()
    _next_event(session, "connected")
    assert connection.recv_entered.wait(timeout=1)

    outcomes: list[str] = []
    retry_started = threading.Event()

    def retry_on_incomplete() -> None:
        try:
            while len(outcomes) < 2:
                event = session.events.get(timeout=1)
                if event.kind != "stopped":
                    continue
                outcomes.append(event.outcome)
                if event.outcome == "incomplete":
                    connection.release.set()
                    retry_started.set()
                    session.stop()
        except queue.Empty:
            pass

    consumer = threading.Thread(target=retry_on_incomplete)
    consumer.start()
    initial_stop = threading.Thread(target=session.stop)
    initial_stop.start()
    assert events.first_terminal_published.wait(timeout=1)
    assert retry_started.wait(timeout=1)
    deadline = time.monotonic() + 1
    while (
        not lifecycle.wait_entered.is_set()
        and not events.second_terminal_published.is_set()
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)
    events.release_first_publisher.set()
    initial_stop.join(timeout=2)
    consumer.join(timeout=2)
    connection.release.set()

    assert not initial_stop.is_alive()
    assert not consumer.is_alive()
    assert outcomes == ["incomplete", "clean"]


def test_stop_reports_unreaped_forced_kill_as_incomplete(tmp_path):
    clock = FakeClock()
    process = UnreapedKillProcess()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        stop_timeout=0.1,
        retry_interval=0.05,
    )
    session.start()

    session.stop()

    events = _drain_events(session)
    stopped = [event for event in events if event.kind == "stopped"]
    assert process.killed is True
    assert process.wait_calls == 1
    assert any(event.kind == "error" and "reap" in event.message.lower() for event in events)
    assert len(stopped) == 1
    assert stopped[0].outcome == "incomplete"


class FailingLog:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        raise OSError("log close failed")


class FlakyCloseLog(FailingLog):
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1:
            raise OSError("log close failed")


class BlockingFinalWriteLog:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.closed = False
        self.write_after_close = False
        self.writer_entered = threading.Event()
        self.release_writer = threading.Event()

    def write(self, text: str) -> int:
        self.writer_entered.set()
        self.release_writer.wait(timeout=1)
        if self.closed:
            self.write_after_close = True
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class CloseFailingRecordingLog:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        raise OSError("log close failed")


def test_stop_retains_log_until_final_data_writer_quiesces_and_retry_closes_it(tmp_path):
    log = BlockingFinalWriteLog()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        stop_timeout=0.01,
    )
    session._state = "running"
    session._log_file = log
    session._start_worker("rtt-final-writer", session._write_decoded, "final chunk\n")
    assert log.writer_entered.wait(timeout=1)
    stopper = threading.Thread(target=session.stop)
    stopper.start()
    stopper.join(timeout=0.5)

    first_events = _drain_events(session)
    first_stopped = [event for event in first_events if event.kind == "stopped"]
    assert not stopper.is_alive()
    assert [event.outcome for event in first_stopped] == ["incomplete"]
    assert session._log_file is log
    assert log.closed is False

    log.release_writer.set()
    assert session.wait(timeout=1)
    session.stop()
    second_events = _drain_events(session)
    data_events = [event.text for event in first_events + second_events if event.kind == "data"]
    second_stopped = [event for event in second_events if event.kind == "stopped"]

    assert data_events == ["final chunk\n"]
    assert log.writes == data_events
    assert [event.outcome for event in second_stopped] == ["clean"]
    assert log.closed is True
    assert log.write_after_close is False


def test_close_log_failure_does_not_republish_detached_handle(tmp_path):
    log = CloseFailingRecordingLog()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
    )
    session._log_file = log

    assert session._close_log() is False
    session._write_decoded("after-close-failure")

    assert session._log_file is None
    assert log.writes == []


def test_start_reports_log_directory_failure_without_launching_openocd(tmp_path):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    launches: list[object] = []
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        blocked_parent / "rtt.log",
        popen_factory=lambda *args, **kwargs: launches.append(args),
    )

    session.start()

    events = _drain_events(session)
    stopped = [event for event in events if event.kind == "stopped"]
    assert launches == []
    assert any(event.kind == "error" and "directory" in event.message.lower() for event in events)
    assert len(stopped) == 1
    assert stopped[0].outcome == "startup_failed"
    session.stop()
    assert _drain_events(session) == []
    with pytest.raises(RuntimeError, match="stopped"):
        session.start()


def test_start_reports_log_open_failure_without_launching_openocd(tmp_path):
    launches: list[object] = []

    def fail_to_open(path: Path):
        raise OSError("log open failed")

    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: launches.append(args),
        log_factory=fail_to_open,
    )

    session.start()

    events = _drain_events(session)
    stopped = [event for event in events if event.kind == "stopped"]
    assert launches == []
    assert any(event.kind == "error" and "open" in event.message.lower() for event in events)
    assert len(stopped) == 1
    assert stopped[0].outcome == "startup_failed"
    session.stop()
    assert _drain_events(session) == []


def test_start_reports_one_incomplete_terminal_per_cleanup_attempt(tmp_path):
    log = FailingLog()
    launches: list[object] = []

    def fail_to_launch(*args, **kwargs):
        launches.append(args)
        raise OSError("OpenOCD launch failed")

    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=fail_to_launch,
        log_factory=lambda path: log,
    )

    session.start()

    events = _drain_events(session)
    stopped = [event for event in events if event.kind == "stopped"]
    assert len(launches) == 1
    assert any(event.kind == "error" and "openocd" in event.message.lower() for event in events)
    assert any(event.kind == "error" and "log close" in event.message.lower() for event in events)
    assert len(stopped) == 1
    assert stopped[0].outcome == "incomplete"
    session.stop()
    retry_events = _drain_events(session)
    retry_stopped = [event for event in retry_events if event.kind == "stopped"]
    assert not any(event.kind == "error" and "log close" in event.message.lower() for event in retry_events)
    assert [event.outcome for event in retry_stopped] == ["clean"]


def test_incomplete_startup_cleanup_retry_does_not_reuse_failed_log_handle(tmp_path):
    log = FlakyCloseLog()

    def fail_to_launch(*args, **kwargs):
        raise OSError("OpenOCD launch failed")

    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=fail_to_launch,
        log_factory=lambda path: log,
    )

    session.start()
    first = [event for event in _drain_events(session) if event.kind == "stopped"]
    session.stop()
    second = [event for event in _drain_events(session) if event.kind == "stopped"]

    assert [event.outcome for event in first] == ["incomplete"]
    assert [event.outcome for event in second] == ["clean"]
    assert log.close_calls == 1


def test_stop_reports_log_close_error_and_continues_cleanup(tmp_path):
    process = FakeProcess(stdout_lines=("rtt: Found control block at 0x20000000\n",))
    connection = BlockingSocket()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        popen_factory=lambda *args, **kwargs: process,
        socket_factory=lambda *args, **kwargs: connection,
        log_factory=lambda path: FailingLog(),
    )
    session.start()
    _next_event(session, "connected")

    session.stop()

    events = _drain_events(session)
    stopped = [event for event in events if event.kind == "stopped"]
    assert connection.closed.is_set()
    assert process.terminated is True
    assert any(event.kind == "error" and "log" in event.message.lower() for event in events)
    assert len(stopped) == 1
    assert stopped[0].outcome == "incomplete"
    assert session.wait(timeout=1)


def test_wait_uses_injected_monotonic_clock(tmp_path):
    clock = FakeClock()
    session = RttSession(
        CONFIG,
        RttRequest(scan_address=0x20000000, scan_size=0x10000),
        tmp_path / "rtt.log",
        monotonic=clock.monotonic,
    )

    assert session.wait(timeout=0)
    assert clock.calls >= 1


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
