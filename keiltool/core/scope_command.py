from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import struct
import time
from typing import Callable, Mapping


SCOPE_COMMAND_SOF = b"\xB1\x50"
SCOPE_COMMAND_VERSION = 1
SCOPE_COMMAND_MAX_PAYLOAD = 32
SCOPE_COMMAND_HEADER_SIZE = 6
SCOPE_COMMAND_CRC_SIZE = 2
SCOPE_FIRMWARE_MAX_RATE_DPS = 6.5


class ScopeCommandType(IntEnum):
    SET_MODE = 0x01
    SET_SPEED = 0x02
    SET_PID = 0x03
    SET_ATTITUDE_QUAT = 0x04
    SET_ATTITUDE_GAIN = 0x05
    START = 0x06
    KEEPALIVE = 0x07
    STOP = 0x08
    GET_STATE = 0x09


@dataclass(frozen=True, slots=True)
class ScopeCommandFrame:
    command: ScopeCommandType | int
    seq: int
    payload: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class ScopeKeepaliveStatus:
    enabled: bool
    next_seq: int
    next_in_ms: int | None
    reason: str = ""


class ScopeKeepaliveController:
    """Schedule non-starting KEEPALIVE frames while an RTT session stays connected."""

    def __init__(
        self,
        *,
        on_send: Callable[[bytes, str], None],
        is_connected: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_send = on_send
        self._is_connected = is_connected
        self._monotonic = monotonic
        self._enabled = False
        self._ttl_ms = 0
        self._next_seq = 0
        self._next_at = 0.0
        self._reason = ""

    def start(self, *, ttl_ms: int, seq: int) -> ScopeKeepaliveStatus:
        ttl_value = _ttl({"ttl_ms": ttl_ms})
        seq_value = _u8(seq, "seq")
        if not self._is_connected():
            raise RuntimeError("RTT is not connected; automatic KEEPALIVE was not started.")
        self._enabled = True
        self._ttl_ms = ttl_value
        self._next_seq = seq_value
        self._reason = ""
        try:
            self._send_now()
        except Exception:
            self.stop("send failed")
            raise
        return self.status()

    def poll(self) -> ScopeKeepaliveStatus:
        if not self._enabled:
            return self.status()
        if not self._is_connected():
            return self.stop("RTT disconnected")
        now = self._monotonic()
        if now >= self._next_at:
            try:
                self._send_now()
            except Exception:
                self.stop("send failed")
                raise
        return self.status()

    def stop(self, reason: str = "disabled") -> ScopeKeepaliveStatus:
        self._enabled = False
        self._next_at = 0.0
        self._reason = reason
        return self.status()

    def set_next_seq(self, seq: int) -> ScopeKeepaliveStatus:
        self._next_seq = _u8(seq, "seq")
        return self.status()

    def status(self) -> ScopeKeepaliveStatus:
        next_in_ms = None
        if self._enabled:
            next_in_ms = max(0, int(round((self._next_at - self._monotonic()) * 1000)))
        return ScopeKeepaliveStatus(
            enabled=self._enabled,
            next_seq=self._next_seq,
            next_in_ms=next_in_ms,
            reason=self._reason,
        )

    def _send_now(self) -> None:
        frame = build_scope_command(
            ScopeCommandType.KEEPALIVE,
            seq=self._next_seq,
            ttl_ms=self._ttl_ms,
        )
        description = f"KEEPALIVE seq={self._next_seq} ttl_ms={self._ttl_ms}"
        self._on_send(frame, description)
        self._next_seq = (self._next_seq + 1) & 0xFF
        self._next_at = self._monotonic() + self._ttl_ms / 2000.0


def crc16_ccitt_false(data: bytes | bytearray | memoryview) -> int:
    crc = 0xFFFF
    for value in bytes(data):
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_scope_command(
    command: ScopeCommandType | int,
    *,
    seq: int,
    payload: bytes | bytearray | memoryview = b"",
) -> bytes:
    command_value = _u8(command, "command")
    seq_value = _u8(seq, "seq")
    payload_bytes = bytes(payload)
    if len(payload_bytes) > SCOPE_COMMAND_MAX_PAYLOAD:
        raise ValueError("ScopeCmd payload cannot exceed 32 bytes.")
    body = bytes(
        (*SCOPE_COMMAND_SOF, SCOPE_COMMAND_VERSION, command_value, seq_value, len(payload_bytes))
    ) + payload_bytes
    return body + struct.pack("<H", crc16_ccitt_false(body))


def decode_scope_command(data: bytes | bytearray | memoryview) -> ScopeCommandFrame:
    raw = bytes(data)
    if len(raw) < SCOPE_COMMAND_HEADER_SIZE + SCOPE_COMMAND_CRC_SIZE:
        raise ValueError("ScopeCmd frame length is shorter than 8 bytes.")
    if raw[:2] != SCOPE_COMMAND_SOF:
        raise ValueError("ScopeCmd SOF does not match B1 50.")
    if raw[2] != SCOPE_COMMAND_VERSION:
        raise ValueError(f"Unsupported ScopeCmd version: {raw[2]}.")
    payload_length = raw[5]
    if payload_length > SCOPE_COMMAND_MAX_PAYLOAD:
        raise ValueError("ScopeCmd payload length exceeds 32 bytes.")
    expected_length = SCOPE_COMMAND_HEADER_SIZE + payload_length + SCOPE_COMMAND_CRC_SIZE
    if len(raw) != expected_length:
        raise ValueError(
            f"ScopeCmd frame length mismatch: expected {expected_length}, received {len(raw)}."
        )
    expected_crc = crc16_ccitt_false(raw[:-2])
    actual_crc = struct.unpack("<H", raw[-2:])[0]
    if actual_crc != expected_crc:
        raise ValueError(
            f"ScopeCmd CRC mismatch: expected 0x{expected_crc:04X}, received 0x{actual_crc:04X}."
        )
    command_value = raw[3]
    try:
        command: ScopeCommandType | int = ScopeCommandType(command_value)
    except ValueError:
        command = command_value
    return ScopeCommandFrame(command=command, seq=raw[4], payload=raw[6:-2], raw=raw)


def build_scope_command(
    command: ScopeCommandType | int,
    *,
    seq: int,
    **values: object,
) -> bytes:
    try:
        command_type = ScopeCommandType(command)
    except ValueError as exc:
        raise ValueError(f"Unsupported ScopeCmd command: {int(command):#04x}.") from exc

    payload: bytes
    if command_type is ScopeCommandType.SET_MODE:
        payload = struct.pack(
            "<BB",
            _choice(values, "axis", {1, 2}),
            _choice(values, "mode", {0, 1, 2}),
        )
    elif command_type is ScopeCommandType.SET_SPEED:
        payload = struct.pack(
            "<Bf",
            _choice(values, "axis", {1, 2}),
            _firmware_speed(values, "target_dps"),
        )
    elif command_type is ScopeCommandType.SET_PID:
        payload = struct.pack(
            "<Bffff",
            _choice(values, "axis", {1, 2}),
            _finite(values, "kp"),
            _finite(values, "ki"),
            _finite(values, "kd"),
            _finite(values, "output_limit_dps"),
        )
    elif command_type is ScopeCommandType.SET_ATTITUDE_QUAT:
        payload = struct.pack(
            "<ffff",
            _finite(values, "w"),
            _finite(values, "x"),
            _finite(values, "y"),
            _finite(values, "z"),
        )
    elif command_type is ScopeCommandType.SET_ATTITUDE_GAIN:
        payload = struct.pack(
            "<fff",
            _finite(values, "kp"),
            _finite(values, "kd"),
            _firmware_positive_rate(values, "max_rate_dps"),
        )
    elif command_type is ScopeCommandType.START:
        payload = struct.pack(
            "<BH",
            _choice(values, "axis_mask", {1, 2, 3}),
            _ttl(values),
        )
    elif command_type is ScopeCommandType.KEEPALIVE:
        payload = struct.pack("<H", _ttl(values))
    elif command_type is ScopeCommandType.STOP:
        payload = struct.pack("<B", _choice(values, "axis_mask", {1, 2, 3}))
    else:
        payload = b""
    return encode_scope_command(command_type, seq=seq, payload=payload)


def _u8(value: object, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if not 0 <= result <= 0xFF:
        raise ValueError(f"{field} must be between 0 and 255.")
    return result


def _choice(values: Mapping[str, object], field: str, allowed: set[int]) -> int:
    value = _u8(values.get(field), field)
    if value not in allowed:
        options = ", ".join(str(item) for item in sorted(allowed))
        raise ValueError(f"{field} must be one of: {options}.")
    return value


def _finite(values: Mapping[str, object], field: str) -> float:
    try:
        value = float(values.get(field))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite float.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite float.")
    return value


def _ttl(values: Mapping[str, object]) -> int:
    try:
        ttl_ms = int(values.get("ttl_ms"))
    except (TypeError, ValueError) as exc:
        raise ValueError("ttl_ms must be an integer between 1 and 30000.") from exc
    if not 1 <= ttl_ms <= 30_000:
        raise ValueError("ttl_ms must be between 1 and 30000.")
    return ttl_ms


def _firmware_speed(values: Mapping[str, object], field: str) -> float:
    value = _finite(values, field)
    if not -SCOPE_FIRMWARE_MAX_RATE_DPS <= value <= SCOPE_FIRMWARE_MAX_RATE_DPS:
        raise ValueError(
            f"{field} must be within the firmware range "
            f"-{SCOPE_FIRMWARE_MAX_RATE_DPS}..+{SCOPE_FIRMWARE_MAX_RATE_DPS} deg/s."
        )
    return value


def _firmware_positive_rate(values: Mapping[str, object], field: str) -> float:
    value = _finite(values, field)
    if not 0.0 < value <= SCOPE_FIRMWARE_MAX_RATE_DPS:
        raise ValueError(
            f"{field} must be within the firmware range (0, {SCOPE_FIRMWARE_MAX_RATE_DPS}] deg/s."
        )
    return value


__all__ = [
    "SCOPE_COMMAND_CRC_SIZE",
    "SCOPE_COMMAND_HEADER_SIZE",
    "SCOPE_COMMAND_MAX_PAYLOAD",
    "SCOPE_COMMAND_SOF",
    "SCOPE_COMMAND_VERSION",
    "SCOPE_FIRMWARE_MAX_RATE_DPS",
    "ScopeCommandFrame",
    "ScopeKeepaliveController",
    "ScopeKeepaliveStatus",
    "ScopeCommandType",
    "build_scope_command",
    "crc16_ccitt_false",
    "decode_scope_command",
    "encode_scope_command",
]
