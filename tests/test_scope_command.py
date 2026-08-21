from __future__ import annotations

import math
import struct

import pytest

from keiltool.core.scope_command import (
    ScopeKeepaliveController,
    ScopeCommandType,
    build_scope_command,
    crc16_ccitt_false,
    decode_scope_command,
    encode_scope_command,
)


def test_crc16_ccitt_false_matches_standard_check_value():
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_get_state_frame_uses_six_byte_header_and_eight_bytes_total():
    frame = build_scope_command(ScopeCommandType.GET_STATE, seq=0x2A)

    assert frame[:6] == bytes.fromhex("B1 50 01 09 2A 00")
    assert len(frame) == 8
    decoded = decode_scope_command(frame)
    assert decoded.command is ScopeCommandType.GET_STATE
    assert decoded.seq == 0x2A
    assert decoded.payload == b""


def test_build_scope_commands_encode_little_endian_payloads():
    speed = build_scope_command(
        ScopeCommandType.SET_SPEED,
        seq=7,
        axis=2,
        target_dps=6.5,
    )
    start = build_scope_command(
        ScopeCommandType.START,
        seq=8,
        axis_mask=3,
        ttl_ms=30_000,
    )

    assert decode_scope_command(speed).payload == bytes.fromhex("02 00 00 D0 40")
    assert decode_scope_command(start).payload == bytes.fromhex("03 30 75")


def test_all_operator_commands_build_the_contract_payload_sizes():
    cases = (
        (ScopeCommandType.SET_MODE, {"axis": 1, "mode": 2}, 2),
        (ScopeCommandType.SET_SPEED, {"axis": 1, "target_dps": -2.5}, 5),
        (
            ScopeCommandType.SET_PID,
            {"axis": 2, "kp": 1.0, "ki": 2.0, "kd": 3.0, "output_limit_dps": 4.0},
            17,
        ),
        (
            ScopeCommandType.SET_ATTITUDE_QUAT,
            {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            16,
        ),
        (
            ScopeCommandType.SET_ATTITUDE_GAIN,
            {"kp": 1.0, "kd": 2.0, "max_rate_dps": 3.0},
            12,
        ),
        (ScopeCommandType.START, {"axis_mask": 3, "ttl_ms": 1000}, 3),
        (ScopeCommandType.KEEPALIVE, {"ttl_ms": 1000}, 2),
        (ScopeCommandType.STOP, {"axis_mask": 3}, 1),
        (ScopeCommandType.GET_STATE, {}, 0),
    )

    for seq, (command, values, payload_size) in enumerate(cases):
        decoded = decode_scope_command(build_scope_command(command, seq=seq, **values))
        assert decoded.command is command
        assert decoded.seq == seq
        assert len(decoded.payload) == payload_size

    speed_payload = decode_scope_command(
        build_scope_command(ScopeCommandType.SET_SPEED, seq=1, axis=1, target_dps=-2.5)
    ).payload
    assert struct.unpack("<f", speed_payload[1:])[0] == -2.5


def test_encode_scope_command_accepts_maximum_payload_and_rejects_larger_one():
    frame = encode_scope_command(0x7F, seq=255, payload=bytes(range(32)))

    assert len(frame) == 40
    assert decode_scope_command(frame).payload == bytes(range(32))
    with pytest.raises(ValueError, match="32"):
        encode_scope_command(0x7F, seq=0, payload=bytes(33))


@pytest.mark.parametrize(
    ("command", "values", "message"),
    [
        (ScopeCommandType.SET_MODE, {"axis": 0, "mode": 1}, "axis"),
        (ScopeCommandType.SET_MODE, {"axis": 1, "mode": 3}, "mode"),
        (ScopeCommandType.START, {"axis_mask": 1, "ttl_ms": 30_001}, "ttl"),
        (ScopeCommandType.KEEPALIVE, {"ttl_ms": 0}, "ttl"),
        (
            ScopeCommandType.SET_SPEED,
            {"axis": 1, "target_dps": math.nan},
            "finite",
        ),
    ],
)
def test_build_scope_command_rejects_unsafe_or_invalid_values(command, values, message):
    with pytest.raises(ValueError, match=message):
        build_scope_command(command, seq=0, **values)


def test_decode_scope_command_rejects_corrupt_crc_and_wrong_total_length():
    frame = bytearray(build_scope_command(ScopeCommandType.STOP, seq=3, axis_mask=1))
    frame[-1] ^= 0x01

    with pytest.raises(ValueError, match="CRC"):
        decode_scope_command(frame)
    with pytest.raises(ValueError, match="length"):
        decode_scope_command(frame[:-1])


@pytest.mark.parametrize(
    "target_dps",
    (-6.51, 6.51),
)
def test_firmware_speed_limits_are_rejected_before_sending(target_dps):
    with pytest.raises(ValueError, match=r"-6\.5.*\+6\.5"):
        build_scope_command(
            ScopeCommandType.SET_SPEED,
            seq=0,
            axis=1,
            target_dps=target_dps,
        )


@pytest.mark.parametrize(
    "max_rate_dps",
    (-0.01, 0.0, 6.51),
)
def test_firmware_attitude_rate_limits_are_rejected_before_sending(max_rate_dps):
    with pytest.raises(ValueError, match=r"0.*6\.5"):
        build_scope_command(
            ScopeCommandType.SET_ATTITUDE_GAIN,
            seq=0,
            kp=1.0,
            kd=0.0,
            max_rate_dps=max_rate_dps,
        )


@pytest.mark.parametrize(
    "target_dps",
    (-6.5, -0.01, 0.0, 0.01, 6.5),
)
def test_set_speed_accepts_full_bidirectional_firmware_range(target_dps):
    frame = build_scope_command(
        ScopeCommandType.SET_SPEED,
        seq=0,
        axis=1,
        target_dps=target_dps,
    )
    assert struct.unpack("<f", decode_scope_command(frame).payload[1:])[0] == pytest.approx(
        target_dps
    )


@pytest.mark.parametrize(
    ("command", "values"),
    [
        (ScopeCommandType.SET_SPEED, {"axis": 1, "target_dps": math.nan}),
        (ScopeCommandType.SET_ATTITUDE_GAIN, {"kp": 1.0, "kd": 0.0, "max_rate_dps": math.inf}),
    ],
)
def test_firmware_rate_fields_reject_non_finite_values(command, values):
    with pytest.raises(ValueError, match="finite"):
        build_scope_command(command, seq=0, **values)


def test_auto_keepalive_sends_immediately_and_stops_when_rtt_disconnects():
    now = [100.0]
    connected = [True]
    sent: list[tuple[bytes, str]] = []
    keepalive = ScopeKeepaliveController(
        on_send=lambda frame, description: sent.append((bytes(frame), description)),
        is_connected=lambda: connected[0],
        monotonic=lambda: now[0],
    )

    status = keepalive.start(ttl_ms=1000, seq=10)

    assert status.enabled is True
    assert status.next_seq == 11
    assert status.next_in_ms == 500
    assert decode_scope_command(sent[0][0]).command is ScopeCommandType.KEEPALIVE
    assert decode_scope_command(sent[0][0]).seq == 10

    now[0] += 0.25
    assert keepalive.poll().next_in_ms == 250
    assert len(sent) == 1

    connected[0] = False
    status = keepalive.poll()
    assert status.enabled is False
    assert status.reason == "RTT disconnected"
    now[0] += 1.0
    keepalive.poll()
    assert len(sent) == 1
