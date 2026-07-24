from __future__ import annotations

import codecs
from dataclasses import dataclass
from enum import IntEnum
import re


class RttLevel(IntEnum):
    ASSERT = 0
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4
    VERBOSE = 5


@dataclass(frozen=True, slots=True)
class RttLogRecord:
    level: RttLevel
    text: str
    terminal: int


_TERMINAL_IDS = {
    **{ord(str(value)): value for value in range(10)},
    **{ord(character): value for value, character in enumerate("ABCDEF", start=10)},
}
_ANSI_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_PREFIX_LEVELS = {
    "A/": RttLevel.ASSERT,
    "E/": RttLevel.ERROR,
    "W/": RttLevel.WARN,
    "I/": RttLevel.INFO,
    "D/": RttLevel.DEBUG,
    "V/": RttLevel.VERBOSE,
}
_FOREGROUND_LEVELS = {
    35: RttLevel.ASSERT,
    31: RttLevel.ERROR,
    33: RttLevel.WARN,
    36: RttLevel.INFO,
    32: RttLevel.DEBUG,
    34: RttLevel.VERBOSE,
}


class SeggerRttLogParser:
    """Parse SEGGER virtual terminals and EasyLogger text into complete records."""

    def __init__(self) -> None:
        self._terminal = 0
        self._terminal_prefix_pending = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._line = ""
        self._line_terminal = 0
        self._finished = False

    def feed(self, data: bytes) -> tuple[RttLogRecord, ...]:
        if self._finished:
            raise RuntimeError("RTT log parser has already finished.")
        records: list[RttLogRecord] = []
        span = bytearray()

        def flush_span() -> None:
            if not span:
                return
            text = self._decoder.decode(bytes(span), final=False)
            span.clear()
            records.extend(self._accept_text(text))

        for byte in data:
            if self._terminal_prefix_pending:
                terminal = _TERMINAL_IDS.get(byte)
                self._terminal_prefix_pending = False
                if terminal is not None:
                    self._terminal = terminal
                else:
                    span.extend((0xFF, byte))
                continue
            if byte == 0xFF:
                flush_span()
                self._terminal_prefix_pending = True
                continue
            span.append(byte)

        flush_span()
        return tuple(records)

    def finish(self) -> tuple[RttLogRecord, ...]:
        if self._finished:
            return ()
        self._finished = True
        records: list[RttLogRecord] = []
        if self._terminal_prefix_pending:
            self._terminal_prefix_pending = False
            records.extend(self._accept_text(self._decoder.decode(b"\xff", final=False)))
        records.extend(self._accept_text(self._decoder.decode(b"", final=True)))
        if self._line:
            records.append(self._build_record(self._line, self._line_terminal))
            self._line = ""
        return tuple(records)

    def _accept_text(self, text: str) -> list[RttLogRecord]:
        records: list[RttLogRecord] = []
        for character in text:
            if not self._line:
                self._line_terminal = self._terminal
            self._line += character
            if character == "\n":
                records.append(self._build_record(self._line, self._line_terminal))
                self._line = ""
        return records

    @staticmethod
    def _build_record(text: str, terminal: int) -> RttLogRecord:
        clean_text = _ANSI_SGR.sub("", text)
        probe = clean_text.lstrip()
        level = next(
            (candidate for prefix, candidate in _PREFIX_LEVELS.items() if probe.startswith(prefix)),
            None,
        )
        if level is None:
            level = _level_from_ansi(text)
        if level is None:
            level = _terminal_level(terminal)
        return RttLogRecord(level=level, text=clean_text, terminal=terminal)


def _level_from_ansi(text: str) -> RttLevel | None:
    for match in _ANSI_SGR.finditer(text):
        for value in match.group(1).split(";"):
            if value.isdigit() and int(value) in _FOREGROUND_LEVELS:
                return _FOREGROUND_LEVELS[int(value)]
    return None


def _terminal_level(terminal: int) -> RttLevel:
    if terminal == 1:
        return RttLevel.DEBUG
    if terminal == 2:
        return RttLevel.VERBOSE
    return RttLevel.INFO


__all__ = ["RttLevel", "RttLogRecord", "SeggerRttLogParser"]
