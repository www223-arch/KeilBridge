from __future__ import annotations

from collections import deque

from keiltool.core.rtt_log import RttLevel, RttLogRecord


RTT_LEVEL_NAMES = tuple(level.name for level in reversed(tuple(RttLevel)))


class RttDisplayBuffer:
    def __init__(self, max_records: int = 20_000) -> None:
        if max_records <= 0:
            raise ValueError("RTT display record limit must be positive.")
        self._records: deque[RttLogRecord] = deque(maxlen=max_records)

    @property
    def records(self) -> tuple[RttLogRecord, ...]:
        return tuple(self._records)

    @property
    def total_count(self) -> int:
        return len(self._records)

    def append(self, record: RttLogRecord) -> None:
        self._records.append(record)

    def clear(self) -> None:
        self._records.clear()

    def visible(self, threshold: RttLevel) -> tuple[RttLogRecord, ...]:
        return tuple(record for record in self._records if record.level <= threshold)

    def visible_count(self, threshold: RttLevel) -> int:
        return sum(record.level <= threshold for record in self._records)


def parse_rtt_level(value: object) -> RttLevel:
    if isinstance(value, str):
        try:
            return RttLevel[value]
        except KeyError:
            pass
    return RttLevel.VERBOSE


__all__ = ["RTT_LEVEL_NAMES", "RttDisplayBuffer", "parse_rtt_level"]
