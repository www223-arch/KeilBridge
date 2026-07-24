from __future__ import annotations

from keiltool.core.rtt_log import RttLevel, RttLogRecord


def test_info_threshold_keeps_info_and_more_severe_records():
    from keiltool.gui.rtt_display import RttDisplayBuffer

    model = RttDisplayBuffer(max_records=20_000)
    for level in RttLevel:
        model.append(RttLogRecord(level, f"{level.name}\n", 0))

    assert [item.level for item in model.visible(RttLevel.INFO)] == [
        RttLevel.ASSERT,
        RttLevel.ERROR,
        RttLevel.WARN,
        RttLevel.INFO,
    ]
    assert model.visible_count(RttLevel.INFO) == 4
    assert model.total_count == 6


def test_verbose_threshold_keeps_every_level():
    from keiltool.gui.rtt_display import RttDisplayBuffer

    model = RttDisplayBuffer()
    for level in RttLevel:
        model.append(RttLogRecord(level, f"{level.name}\n", 0))

    assert model.visible(RttLevel.VERBOSE) == model.records


def test_display_buffer_discards_oldest_records_at_limit():
    from keiltool.gui.rtt_display import RttDisplayBuffer

    model = RttDisplayBuffer(max_records=2)
    assert model.append(RttLogRecord(RttLevel.INFO, "one\n", 0)) is None
    model.append(RttLogRecord(RttLevel.INFO, "two\n", 0))
    evicted = model.append(RttLogRecord(RttLevel.INFO, "three\n", 0))

    assert [item.text for item in model.records] == ["two\n", "three\n"]
    assert evicted == RttLogRecord(RttLevel.INFO, "one\n", 0)


def test_display_buffer_clear_removes_only_cached_records():
    from keiltool.gui.rtt_display import RttDisplayBuffer

    model = RttDisplayBuffer()
    model.append(RttLogRecord(RttLevel.INFO, "one\n", 0))

    model.clear()

    assert model.records == ()
    assert model.total_count == 0


def test_parse_rtt_level_falls_back_to_verbose():
    from keiltool.gui.rtt_display import parse_rtt_level

    assert parse_rtt_level("WARN") is RttLevel.WARN
    assert parse_rtt_level("invalid") is RttLevel.VERBOSE


def test_build_rtt_view_filters_records_and_formats_counts():
    from keiltool.gui.rtt_display import RttDisplayBuffer, build_rtt_view

    model = RttDisplayBuffer()
    model.append(RttLogRecord(RttLevel.INFO, "I/ready\n", 0))
    model.append(RttLogRecord(RttLevel.DEBUG, "D/loop\n", 1))

    view = build_rtt_view(model, "INFO")

    assert [item.text for item in view.records] == ["I/ready\n"]
    assert view.label == "1 可见 / 2 缓存"
