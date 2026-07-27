from __future__ import annotations

from enum import Enum
from threading import RLock


class SessionState(Enum):
    IDLE = "idle"
    CONNECT = "connect"
    FLASH = "flash"
    FLASH_READ = "flash_read"
    RTT_SCAN = "rtt_scan"
    RTT = "rtt"
    STOPPING = "stopping"
    FAILED = "failed"


class BusySessionError(RuntimeError):
    """Raised when another operation already owns the ST-Link session."""


class TaskGate:
    _WORK_STATES = frozenset(
        {
            SessionState.CONNECT,
            SessionState.FLASH,
            SessionState.FLASH_READ,
            SessionState.RTT_SCAN,
            SessionState.RTT,
        }
    )

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = SessionState.IDLE

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._state

    def begin(self, state: SessionState) -> None:
        if state not in self._WORK_STATES:
            raise ValueError("TaskGate.begin() requires a work state.")
        with self._lock:
            if self._state not in {SessionState.IDLE, SessionState.FAILED}:
                raise BusySessionError(f"ST-Link is busy with {self._state.value}.")
            self._state = state

    def begin_stopping(self) -> None:
        with self._lock:
            if self._state not in self._WORK_STATES:
                raise BusySessionError(f"Cannot stop session in {self._state.value} state.")
            self._state = SessionState.STOPPING

    def finish(self) -> None:
        with self._lock:
            self._state = SessionState.IDLE

    def fail(self) -> None:
        with self._lock:
            self._state = SessionState.FAILED
