from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from keiltool.core.rtt_log import RttLevel, RttLogRecord


RTT_LEVEL_NAMES = tuple(level.name for level in reversed(tuple(RttLevel)))


@dataclass(frozen=True, slots=True)
class RttViewState:
    records: tuple[RttLogRecord, ...]
    label: str


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

    def append(self, record: RttLogRecord) -> RttLogRecord | None:
        evicted = self._records[0] if len(self._records) == self._records.maxlen else None
        self._records.append(record)
        return evicted

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


def build_rtt_view(buffer: RttDisplayBuffer, level_name: object) -> RttViewState:
    records = buffer.visible(parse_rtt_level(level_name))
    return RttViewState(
        records=records,
        label=f"{len(records):,} 可见 / {buffer.total_count:,} 缓存",
    )


__all__ = [
    "RTT_LEVEL_NAMES",
    "RttDisplayBuffer",
    "RttViewState",
    "build_rtt_view",
    "parse_rtt_level",
]
