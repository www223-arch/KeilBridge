from __future__ import annotations


def test_parser_handles_terminal_switch_and_utf8_split():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    assert parser.feed(b"\xff") == ()
    assert parser.feed(b"1D/motor \xe8\xbf") == ()
    records = parser.feed(b"\x90\xe8\xa1\x8c\n")

    assert [(item.level, item.terminal, item.text) for item in records] == [
        (RttLevel.DEBUG, 1, "D/motor 运行\n")
    ]


def test_parser_uses_easylogger_prefix_before_terminal_fallback():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    records = parser.feed(b"\xff0\x1b[31;22mE/fault\x1b[0m\n")

    assert records[0].level is RttLevel.ERROR
    assert records[0].terminal == 0
    assert records[0].text == "E/fault\n"


def test_parser_uses_terminal_fallback_without_easylogger_prefix():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    records = parser.feed(b"\xff1loop details\n\xff2sample details\n")

    assert [(item.level, item.terminal) for item in records] == [
        (RttLevel.DEBUG, 1),
        (RttLevel.VERBOSE, 2),
    ]


def test_parser_handles_ansi_sequence_split_across_chunks():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    assert parser.feed(b"\x1b[33;") == ()
    records = parser.feed(b"22mW/slow\x1b[0m\n")

    assert records[0].level is RttLevel.WARN
    assert records[0].text == "W/slow\n"


def test_parser_flushes_incomplete_tail_and_defaults_to_info():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    assert parser.feed("普通输出".encode("utf-8")) == ()
    records = parser.finish()

    assert records[0].level is RttLevel.INFO
    assert records[0].text == "普通输出"


def test_parser_preserves_unmatched_terminal_marker_as_replacement_text():
    from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser

    parser = SeggerRttLogParser()

    assert parser.feed(b"I/ready\xff") == ()
    records = parser.finish()

    assert records[0].level is RttLevel.INFO
    assert records[0].text == "I/ready\ufffd"


def test_parser_rejects_feed_after_finish():
    import pytest

    from keiltool.core.rtt_log import SeggerRttLogParser

    parser = SeggerRttLogParser()
    parser.finish()

    with pytest.raises(RuntimeError, match="finished"):
        parser.feed(b"late")
