import pytest

from keiltool.core.rtt_vofa import VofaRttConfig, write_vofa_session_guide


def test_default_vofa_rtt_config_is_generic_and_does_not_force_frame_length():
    config = VofaRttConfig()
    primary, additional = config.channel_configs()

    assert config.expected_float_count is None
    assert primary.channel == 1
    assert primary.port == 19022
    assert primary.expected_channel_name is None
    assert primary.expected_down_channel_name is None
    assert [(item.channel, item.port, item.parse_records) for item in additional] == [
        (0, 19021, True)
    ]


def test_vofa_rtt_config_supports_distinct_user_selected_down_channel():
    config = VofaRttConfig(
        text_up_channel=3,
        text_port=19100,
        curve_up_channel=4,
        curve_port=19101,
        down_channel=5,
        down_port=19102,
        curve_up_name="Plot",
        down_name="Commands",
        expected_float_count=8,
    )
    primary, additional = config.channel_configs()

    assert primary.expected_channel_name == "Plot"
    assert {(item.channel, item.port) for item in additional} == {
        (3, 19100),
        (5, 19102),
    }
    down = next(item for item in additional if item.channel == 5)
    assert down.expected_down_channel_name == "Commands"


@pytest.mark.parametrize(
    "values, message",
    [
        ({"text_up_channel": 1, "curve_up_channel": 1}, "must be different"),
        ({"curve_port": 19021, "down_port": 19021}, "Different RTT channels"),
        ({"down_channel": 2, "down_port": 19022}, "Different RTT channels"),
        ({"curve_up_name": "曲线"}, "must be ASCII"),
        ({"expected_float_count": 0}, "must be positive"),
    ],
)
def test_vofa_rtt_config_rejects_ambiguous_transport(values, message):
    with pytest.raises(ValueError, match=message):
        VofaRttConfig(**values)


def test_vofa_session_guide_describes_transport_without_business_protocol(tmp_path):
    config = VofaRttConfig(
        curve_up_name="Plot",
        down_name="Commands",
        expected_float_count=6,
    )
    path = write_vofa_session_guide(
        tmp_path / "rtt-vofa-session.txt",
        config,
        "127.0.0.1:1347",
    )
    text = path.read_text(encoding="utf-8")

    assert "Text log: RTT Up0" in text
    assert "VOFA curve: RTT Up1" in text
    assert "Reverse data" in text
    assert "RTT Down1" in text
    assert "Plot" in text
    assert "Commands" in text
    assert "JustFloat values per frame: 6" in text
    assert "does not add framing or interpret commands" in text
    assert "BilboPro" not in text
