from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FirmwareFingerprint:
    path: Path
    size: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FirmwareChange:
    previous: FirmwareFingerprint | None
    current: FirmwareFingerprint | None
    error: str = ""


class FirmwareFreshness:
    def __init__(self) -> None:
        self._accepted: FirmwareFingerprint | None = None
        self._pending: FirmwareFingerprint | None = None
        self._pending_key: tuple[object, ...] | None = None
        self._stale = False

    @property
    def stale(self) -> bool:
        return self._stale

    @property
    def accepted(self) -> FirmwareFingerprint | None:
        return self._accepted

    def accepts_path(self, path: str | Path) -> bool:
        if self._stale or self._accepted is None:
            return False
        return Path(path).expanduser().resolve() == self._accepted.path

    def clear(self) -> None:
        self._accepted = None
        self._pending = None
        self._pending_key = None
        self._stale = False

    def accept(self, path: str | Path) -> FirmwareFingerprint:
        fingerprint = fingerprint_firmware(path)
        self._accepted = fingerprint
        self._pending = None
        self._pending_key = None
        self._stale = False
        return fingerprint

    def observe(self, path: str | Path) -> FirmwareChange | None:
        candidate, error = _try_fingerprint(path)
        if self._accepted is None:
            if candidate is not None:
                self._accepted = candidate
                self._stale = False
                return None
            key = (str(Path(path)), error)
        elif candidate == self._accepted:
            self._pending = None
            self._pending_key = None
            self._stale = False
            return None
        else:
            key = (
                candidate.path if candidate else str(Path(path)),
                candidate.size if candidate else None,
                candidate.modified_ns if candidate else None,
                candidate.sha256 if candidate else None,
                error,
            )

        self._stale = True
        self._pending = candidate
        if key == self._pending_key:
            return None
        self._pending_key = key
        return FirmwareChange(self._accepted, candidate, error)

    def accept_pending(self) -> FirmwareFingerprint:
        if self._pending is None:
            raise ValueError("There is no readable pending firmware version to accept.")
        self._accepted = self._pending
        self._pending = None
        self._pending_key = None
        self._stale = False
        return self._accepted

    def is_current(self, path: str | Path) -> bool:
        if self._stale or self._accepted is None:
            return False
        current, _error = _try_fingerprint(path)
        return current == self._accepted


def fingerprint_firmware(path: str | Path) -> FirmwareFingerprint:
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return FirmwareFingerprint(
        path=resolved,
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def _try_fingerprint(path: str | Path) -> tuple[FirmwareFingerprint | None, str]:
    try:
        return fingerprint_firmware(path), ""
    except OSError as exc:
        return None, str(exc)


__all__ = [
    "FirmwareChange",
    "FirmwareFingerprint",
    "FirmwareFreshness",
    "fingerprint_firmware",
]
