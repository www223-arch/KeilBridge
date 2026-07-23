from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path
import queue
import socket
import subprocess
import threading
import time
from typing import Callable, Protocol, TextIO

from .openocd_backend import OpenOcdConfig


@dataclass(frozen=True, slots=True)
class RttRequest:
    scan_address: int
    scan_size: int
    port: int = 19021
    channel: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.scan_address <= 0xFFFFFFFF:
            raise ValueError("RTT scan address must fit in 32 bits.")
        if self.scan_size <= 0:
            raise ValueError("RTT scan size must be positive.")
        if not 1 <= self.port <= 65535:
            raise ValueError("RTT port must be between 1 and 65535.")
        if self.channel < 0:
            raise ValueError("RTT channel must be non-negative.")


def build_rtt_command(config: OpenOcdConfig, request: RttRequest) -> list[str]:
    """Build a non-invasive OpenOCD RTT command for ST-Link over SWD."""

    return [
        *config.base_command(),
        "-c",
        "init",
        "-c",
        f'rtt setup 0x{request.scan_address:08X} 0x{request.scan_size:X} "SEGGER RTT"',
        "-c",
        "rtt start",
        "-c",
        f"rtt server start {request.port} {request.channel}",
    ]


@dataclass(frozen=True, slots=True)
class RttEvent:
    kind: str
    text: str = ""
    message: str = ""
    stream: str = ""
    outcome: str = ""


class RttProcess(Protocol):
    stdout: TextIO | None
    stderr: TextIO | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


PopenFactory = Callable[..., RttProcess]
SocketFactory = Callable[..., socket.socket]
LogFactory = Callable[[Path], TextIO]


def _open_rtt_log(path: Path) -> TextIO:
    return path.open("w", encoding="utf-8", newline="")


class RttSession:
    """Own an OpenOCD RTT server and persist its live channel output."""

    def __init__(
        self,
        config: OpenOcdConfig,
        request: RttRequest,
        log_path: Path,
        *,
        popen_factory: PopenFactory = subprocess.Popen,
        socket_factory: SocketFactory = socket.create_connection,
        log_factory: LogFactory = _open_rtt_log,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        connect_timeout: float = 10.0,
        stop_timeout: float = 2.0,
        retry_interval: float = 0.05,
        host: str = "127.0.0.1",
    ) -> None:
        if connect_timeout <= 0:
            raise ValueError("RTT connect timeout must be positive.")
        if stop_timeout < 0:
            raise ValueError("RTT stop timeout must be non-negative.")
        if retry_interval <= 0:
            raise ValueError("RTT retry interval must be positive.")
        self.command = build_rtt_command(config, request)
        self.events: queue.Queue[RttEvent] = queue.Queue()
        self.log_path = Path(log_path)
        self._popen_factory = popen_factory
        self._socket_factory = socket_factory
        self._log_factory = log_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._connect_timeout = connect_timeout
        self._stop_timeout = stop_timeout
        self._retry_interval = retry_interval
        self._host = host
        self._port = request.port
        self._lock = threading.RLock()
        self._lifecycle = threading.Condition(threading.RLock())
        self._stop_requested = threading.Event()
        self._control_block_found = threading.Event()
        self._process: RttProcess | None = None
        self._socket: socket.socket | None = None
        self._log_file: TextIO | None = None
        self._workers: list[threading.Thread] = []
        self._state = "new"
        self._cleanup_emitted = False

    def start(self) -> None:
        """Start OpenOCD and return while background workers establish RTT."""

        with self._lifecycle:
            if self._state == "stopped":
                raise RuntimeError("RTT session has been stopped and cannot be started.")
            if self._state != "new":
                raise RuntimeError("RTT session has already been started.")
            self._state = "running"
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._finish_startup_failure(f"Unable to create RTT log directory: {exc}")
                return
            try:
                self._log_file = self._log_factory(self.log_path)
            except OSError as exc:
                self._finish_startup_failure(f"Unable to open RTT log: {exc}")
                return
            try:
                self._process = self._popen_factory(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                self._finish_startup_failure(f"Unable to start OpenOCD: {exc}")
                return

            if self._process.stdout is not None:
                self._start_worker("rtt-openocd-stdout", self._read_openocd_stream, self._process.stdout, "stdout")
            if self._process.stderr is not None:
                self._start_worker("rtt-openocd-stderr", self._read_openocd_stream, self._process.stderr, "stderr")
            self._start_worker("rtt-connect", self._wait_for_control_block)

    def stop(self) -> None:
        """Close RTT resources and give OpenOCD a bounded graceful shutdown."""

        with self._lifecycle:
            if self._state == "stopped":
                return
            if self._state == "stopping":
                while self._state == "stopping":
                    self._lifecycle.wait()
                return
            self._state = "stopping"

        self._stop_requested.set()
        forced = False
        joined = False
        incomplete = False
        try:
            try:
                self._close_socket()
            except Exception as exc:
                incomplete = True
                self._emit("error", message=f"RTT socket cleanup failed: {exc}")
            if not self._close_log():
                incomplete = True
            process = self._process
            try:
                if process is not None and self._process_running(process):
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    if not self._wait_for_process_exit(process):
                        forced = True
                        try:
                            process.kill()
                        except OSError:
                            pass
                        finally:
                            if not self._reap_process(process):
                                incomplete = True
            except Exception as exc:
                incomplete = True
                self._emit("error", message=f"OpenOCD process cleanup failed: {exc}")
            joined = self._join_workers(timeout=self._stop_timeout)
            if not joined:
                incomplete = True
                self._emit("error", message="RTT worker threads did not finish during cleanup.")
        finally:
            outcome = "incomplete" if incomplete else "forced" if forced else "clean"
            self._emit_terminal(outcome)
            with self._lifecycle:
                self._state = "stopped"
                self._lifecycle.notify_all()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for started worker threads to finish, returning whether they did."""

        return self._join_workers(timeout)

    def _wait_for_control_block(self) -> None:
        deadline = self._monotonic() + self._connect_timeout
        while not self._stop_requested.is_set():
            if self._control_block_found.is_set():
                self._connect_rtt_server(deadline)
                return
            if self._process_exited():
                self._emit("error", message="OpenOCD exited before the RTT control block was found.")
                return
            if self._monotonic() >= deadline:
                self._emit("error", message="Timed out waiting for the OpenOCD RTT control block.")
                return
            self._sleep(self._retry_interval)

    def _connect_rtt_server(self, deadline: float) -> None:
        while not self._stop_requested.is_set():
            if self._process_exited():
                self._emit("error", message="OpenOCD exited before the RTT TCP connection was established.")
                return
            try:
                connection = self._socket_factory((self._host, self._port), timeout=self._retry_interval)
            except OSError:
                if self._monotonic() >= deadline:
                    self._emit("error", message="Timed out connecting to the OpenOCD RTT TCP server.")
                    return
                self._sleep(self._retry_interval)
                continue
            connection.settimeout(None)
            with self._lock:
                if self._stop_requested.is_set():
                    connection.close()
                    return
                self._socket = connection
            self._emit("connected", message=f"Connected to RTT channel on {self._host}:{self._port}.")
            self._start_worker("rtt-tcp", self._read_rtt_socket, connection)
            return

    def _read_openocd_stream(self, stream: TextIO, stream_name: str) -> None:
        while not self._stop_requested.is_set():
            line = stream.readline()
            if not line:
                return
            self._emit("openocd", text=line, stream=stream_name)
            normalized = line.casefold()
            if "rtt" in normalized and "control block" in normalized and "found" in normalized:
                self._control_block_found.set()

    def _read_rtt_socket(self, connection: socket.socket) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while not self._stop_requested.is_set():
                data = connection.recv(4096)
                if not data:
                    self._write_decoded(decoder.decode(b"", final=True))
                    self._emit("eof", message="RTT TCP connection closed.")
                    return
                self._write_decoded(decoder.decode(data, final=False))
        except OSError as exc:
            if not self._stop_requested.is_set():
                self._emit("error", message=f"RTT TCP receive failed: {exc}")
        finally:
            self._close_socket(connection)

    def _write_decoded(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            if self._log_file is not None:
                try:
                    self._log_file.write(text)
                    self._log_file.flush()
                except Exception as exc:
                    self._emit("error", message=f"RTT log write failed: {exc}")
        self._emit("data", text=text)

    def _process_exited(self) -> bool:
        process = self._process
        return process is None or not self._process_running(process)

    @staticmethod
    def _process_running(process: RttProcess) -> bool:
        try:
            return process.poll() is None
        except OSError:
            return False

    def _wait_for_process_exit(self, process: RttProcess) -> bool:
        deadline = self._monotonic() + self._stop_timeout
        while self._process_running(process) and self._monotonic() < deadline:
            self._sleep(min(self._retry_interval, max(0.0, deadline - self._monotonic())))
        return not self._process_running(process)

    def _reap_process(self, process: RttProcess) -> bool:
        try:
            process.wait(timeout=self._stop_timeout)
        except (OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
            self._emit("error", message=f"OpenOCD could not be reaped after forced kill: {exc}")
            return False
        return True

    def _start_worker(self, name: str, target: Callable[..., None], *args: object) -> None:
        worker = threading.Thread(name=name, target=target, args=args, daemon=True)
        with self._lock:
            self._workers.append(worker)
        worker.start()

    def _join_workers(self, timeout: float | None) -> bool:
        deadline = None if timeout is None else self._monotonic() + timeout
        current = threading.current_thread()
        with self._lock:
            workers = tuple(self._workers)
        for worker in workers:
            if worker is current:
                continue
            remaining = None if deadline is None else max(0.0, deadline - self._monotonic())
            worker.join(remaining)
        return all(not worker.is_alive() or worker is current for worker in workers)

    def _close_socket(self, expected: socket.socket | None = None) -> None:
        with self._lock:
            connection = self._socket
            if connection is None or (expected is not None and connection is not expected):
                return
            self._socket = None
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass

    def _close_log(self) -> bool:
        with self._lock:
            log_file = self._log_file
            self._log_file = None
        if log_file is None:
            return True
        closed = True
        try:
            log_file.flush()
        except Exception as exc:
            closed = False
            self._emit("error", message=f"RTT log flush during cleanup failed: {exc}")
        try:
            log_file.close()
        except Exception as exc:
            closed = False
            self._emit("error", message=f"RTT log close during cleanup failed: {exc}")
        return closed

    def _finish_startup_failure(self, message: str) -> None:
        self._emit("error", message=message)
        outcome = "startup_failed" if self._close_log() else "incomplete"
        self._emit_terminal(outcome)
        self._state = "stopped"
        self._lifecycle.notify_all()

    def _emit_terminal(self, outcome: str) -> None:
        with self._lifecycle:
            if self._cleanup_emitted:
                return
            self._cleanup_emitted = True
        if outcome == "clean":
            message = "RTT session stopped cleanly."
        elif outcome == "forced":
            message = "RTT session was forcefully terminated."
        elif outcome == "startup_failed":
            message = "RTT session startup failed."
        else:
            message = "RTT session cleanup is incomplete."
        self._emit("stopped", message=message, outcome=outcome)

    def _emit(self, kind: str, *, text: str = "", message: str = "", stream: str = "", outcome: str = "") -> None:
        self.events.put(RttEvent(kind=kind, text=text, message=message, stream=stream, outcome=outcome))
