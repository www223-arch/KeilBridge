from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import queue
import socket
import threading
from typing import BinaryIO, Iterable


JUSTFLOAT_TAIL = b"\x00\x00\x80\x7f"
_RAW_FILE_BUFFER_SIZE = 1024 * 1024


@dataclass(slots=True)
class JustFloatDecoderStats:
    frames: int = 0
    payload_bytes: int = 0
    invalid_frames: int = 0
    discarded_bytes: int = 0


class JustFloatFrameDecoder:
    """Incrementally split VOFA+ JustFloat frames without decoding their values."""

    def __init__(self, *, max_frame_bytes: int = 1024 * 1024) -> None:
        if max_frame_bytes < 8:
            raise ValueError("JustFloat maximum frame size must be at least 8 bytes.")
        self._max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self.stats = JustFloatDecoderStats()

    def feed(self, data: bytes) -> tuple[bytes, ...]:
        if not data:
            return ()
        self._buffer.extend(data)
        frames: list[bytes] = []
        while True:
            marker = self._buffer.find(JUSTFLOAT_TAIL)
            if marker < 0:
                self._trim_unterminated_buffer()
                break
            frame_size = marker + len(JUSTFLOAT_TAIL)
            frame = bytes(self._buffer[:frame_size])
            del self._buffer[:frame_size]
            payload_size = marker
            if payload_size == 0 or payload_size % 4 != 0 or frame_size > self._max_frame_bytes:
                self.stats.invalid_frames += 1
                self.stats.discarded_bytes += frame_size
                continue
            self.stats.frames += 1
            self.stats.payload_bytes += payload_size
            frames.append(frame)
        return tuple(frames)

    def _trim_unterminated_buffer(self) -> None:
        if len(self._buffer) <= self._max_frame_bytes:
            return
        keep = len(JUSTFLOAT_TAIL) - 1
        discarded = len(self._buffer) - keep
        del self._buffer[:discarded]
        self.stats.invalid_frames += 1
        self.stats.discarded_bytes += discarded


@dataclass(slots=True)
class VofaBridgeStats:
    raw_bytes: int = 0
    frames_received: int = 0
    frames_forwarded: int = 0
    bytes_forwarded: int = 0
    frames_dropped: int = 0
    invalid_frames: int = 0
    clients_connected: int = 0
    active_clients: int = 0
    disconnects: int = 0
    last_error: str = ""


class VofaTcpBridge:
    """Forward complete JustFloat frames to one non-blocking local TCP consumer."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1347,
        *,
        raw_output: Path | None = None,
        queued_frames: int = 2048,
    ) -> None:
        if not 0 <= port <= 65535:
            raise ValueError("VOFA TCP port must be between 0 and 65535.")
        if queued_frames <= 0:
            raise ValueError("VOFA queued frame count must be positive.")
        self._host = host
        self._port = port
        self._raw_output = Path(raw_output) if raw_output is not None else None
        self._decoder = JustFloatFrameDecoder()
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=queued_frames)
        self._stats = VofaBridgeStats()
        self._stats_lock = threading.Lock()
        self._raw_lock = threading.Lock()
        self._raw_stream: BinaryIO | None = None
        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._listen_address: tuple[str, int] | None = None

    @property
    def listen_address(self) -> tuple[str, int]:
        if self._listen_address is None:
            raise RuntimeError("VOFA bridge has not been started.")
        return self._listen_address

    @property
    def stats(self) -> VofaBridgeStats:
        with self._stats_lock:
            snapshot = replace(self._stats)
        snapshot.invalid_frames = self._decoder.stats.invalid_frames
        return snapshot

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("VOFA bridge is already running.")
        if self._raw_output is not None:
            self._raw_output.parent.mkdir(parents=True, exist_ok=True)
            self._raw_stream = self._raw_output.open("wb", buffering=_RAW_FILE_BUFFER_SIZE)
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._host, self._port))
            listener.listen(1)
            listener.settimeout(0.1)
        except Exception:
            self._close_raw_stream()
            raise
        self._listener = listener
        address = listener.getsockname()
        self._listen_address = (str(address[0]), int(address[1]))
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="keiltool-vofa-bridge",
            daemon=True,
        )
        self._thread.start()

    def feed(self, data: bytes) -> None:
        if not data:
            return
        if self._thread is None:
            raise RuntimeError("VOFA bridge is not running.")
        self._write_raw(data)
        with self._stats_lock:
            self._stats.raw_bytes += len(data)
        for frame in self._decoder.feed(data):
            with self._stats_lock:
                self._stats.frames_received += 1
            self._enqueue_latest(frame)

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        self._stop_requested.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        self._close_client(count_disconnect=False)
        try:
            self._close_raw_stream()
        except OSError as exc:
            with self._stats_lock:
                self._stats.last_error = str(exc)
        self._thread = None
        self._listener = None

    def _write_raw(self, data: bytes) -> None:
        with self._raw_lock:
            if self._raw_stream is not None:
                written = self._raw_stream.write(data)
                if written != len(data):
                    raise OSError(
                        f"Short RTT raw write: expected {len(data)} bytes, wrote {written}."
                    )

    def _enqueue_latest(self, frame: bytes) -> None:
        try:
            self._frames.put_nowait(frame)
            return
        except queue.Full:
            pass
        try:
            self._frames.get_nowait()
        except queue.Empty:
            pass
        else:
            with self._stats_lock:
                self._stats.frames_dropped += 1
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            with self._stats_lock:
                self._stats.frames_dropped += 1

    def _serve(self) -> None:
        while not self._stop_requested.is_set():
            if self._client is None:
                self._accept_client()
                continue
            try:
                frame = self._frames.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._client.sendall(frame)
            except OSError as exc:
                with self._stats_lock:
                    self._stats.frames_dropped += 1
                    self._stats.last_error = str(exc)
                self._close_client()
                continue
            with self._stats_lock:
                self._stats.frames_forwarded += 1
                self._stats.bytes_forwarded += len(frame)

    def _accept_client(self) -> None:
        listener = self._listener
        if listener is None:
            return
        try:
            client, _address = listener.accept()
        except socket.timeout:
            return
        except OSError as exc:
            if not self._stop_requested.is_set():
                with self._stats_lock:
                    self._stats.last_error = str(exc)
            return
        client.settimeout(0.5)
        self._client = client
        with self._stats_lock:
            self._stats.clients_connected += 1
            self._stats.active_clients = 1

    def _close_client(self, *, count_disconnect: bool = True) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.close()
        except OSError:
            pass
        with self._stats_lock:
            self._stats.active_clients = 0
            if count_disconnect:
                self._stats.disconnects += 1

    def _close_raw_stream(self) -> None:
        with self._raw_lock:
            stream = self._raw_stream
            self._raw_stream = None
            if stream is None:
                return
            try:
                stream.flush()
            finally:
                stream.close()


def parse_listen_address(value: str) -> tuple[str, int]:
    host, separator, port_text = value.strip().rpartition(":")
    if not separator or not host or not port_text:
        raise ValueError("VOFA listen address must use HOST:PORT format.")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("VOFA TCP port must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("VOFA TCP port must be between 1 and 65535.")
    return host, port


def default_vofa_candidates() -> tuple[Path, ...]:
    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    return (
        local_appdata / "Programs" / "VOFA+" / "vofa+.exe",
        local_appdata / "VOFA+" / "vofa+.exe",
        program_files / "VOFA+" / "vofa+.exe",
        program_files_x86 / "VOFA+" / "vofa+.exe",
        Path("C:/stm32/vofa+/x64/vofa+.exe"),
    )


def discover_vofa_executable(
    preferred: str | Path | None = None,
    *,
    candidates: Iterable[Path] | None = None,
) -> Path | None:
    choices: list[Path] = []
    if preferred:
        choices.append(Path(preferred).expanduser())
    environment_path = os.environ.get("VOFA_PATH")
    if environment_path:
        choices.append(Path(environment_path).expanduser())
    choices.extend(default_vofa_candidates() if candidates is None else candidates)
    for candidate in choices:
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            return candidate.resolve()
    return None


__all__ = [
    "JUSTFLOAT_TAIL",
    "JustFloatDecoderStats",
    "JustFloatFrameDecoder",
    "VofaBridgeStats",
    "VofaTcpBridge",
    "default_vofa_candidates",
    "discover_vofa_executable",
    "parse_listen_address",
]
