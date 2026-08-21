from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .rtt import RttChannelConfig


@dataclass(frozen=True, slots=True)
class VofaRttConfig:
    """User-selected RTT channels for simultaneous text, scope, and downlink I/O."""

    text_up_channel: int = 0
    text_port: int = 19021
    curve_up_channel: int = 1
    curve_port: int = 19022
    down_channel: int = 1
    down_port: int = 19022
    curve_up_name: str | None = None
    down_name: str | None = None
    expected_float_count: int | None = None

    def __post_init__(self) -> None:
        for label, channel in (
            ("Text RTT up-channel", self.text_up_channel),
            ("Curve RTT up-channel", self.curve_up_channel),
            ("RTT down-channel", self.down_channel),
        ):
            if not 0 <= channel <= 255:
                raise ValueError(f"{label} must be between 0 and 255.")
        for label, port in (
            ("Text RTT port", self.text_port),
            ("Curve RTT port", self.curve_port),
            ("RTT down port", self.down_port),
        ):
            if not 1 <= port <= 65535:
                raise ValueError(f"{label} must be between 1 and 65535.")
        if self.text_up_channel == self.curve_up_channel:
            raise ValueError("Text and curve RTT up-channels must be different.")
        channel_ports: dict[int, int] = {}
        for channel, port in (
            (self.text_up_channel, self.text_port),
            (self.curve_up_channel, self.curve_port),
            (self.down_channel, self.down_port),
        ):
            previous = channel_ports.setdefault(channel, port)
            if previous != port:
                raise ValueError("The same RTT channel must use the same OpenOCD TCP port.")
        port_channels: dict[int, int] = {}
        for channel, port in channel_ports.items():
            previous = port_channels.setdefault(port, channel)
            if previous != channel:
                raise ValueError("Different RTT channels must use different OpenOCD TCP ports.")
        _validate_optional_ascii_name("Curve RTT up-channel name", self.curve_up_name)
        _validate_optional_ascii_name("RTT down-channel name", self.down_name)
        if self.expected_float_count is not None and self.expected_float_count <= 0:
            raise ValueError("Expected JustFloat count must be positive when provided.")

    def channel_configs(self) -> tuple[RttChannelConfig, tuple[RttChannelConfig, ...]]:
        configs: dict[int, RttChannelConfig] = {
            self.curve_up_channel: RttChannelConfig(
                port=self.curve_port,
                channel=self.curve_up_channel,
                expected_channel_name=self.curve_up_name,
                expected_down_channel_name=(
                    self.down_name if self.down_channel == self.curve_up_channel else None
                ),
            ),
            self.text_up_channel: RttChannelConfig(
                port=self.text_port,
                channel=self.text_up_channel,
                expected_down_channel_name=(
                    self.down_name if self.down_channel == self.text_up_channel else None
                ),
                parse_records=True,
            ),
        }
        if self.down_channel not in configs:
            configs[self.down_channel] = RttChannelConfig(
                port=self.down_port,
                channel=self.down_channel,
                expected_down_channel_name=self.down_name,
            )
        primary = configs.pop(self.curve_up_channel)
        return primary, tuple(configs.values())


def render_vofa_session_guide(config: VofaRttConfig, listen: str) -> str:
    float_count = (
        str(config.expected_float_count)
        if config.expected_float_count is not None
        else "variable (no KeilTool length check)"
    )
    return (
        "KeilTool generic RTT / VOFA+ session\n"
        "===================================\n"
        f"Text log: RTT Up{config.text_up_channel} -> OpenOCD TCP {config.text_port}\n"
        f"VOFA curve: RTT Up{config.curve_up_channel} -> OpenOCD TCP {config.curve_port} "
        f"-> KeilTool TCP {listen}\n"
        f"Reverse data: KeilTool TCP {listen} -> RTT Down{config.down_channel} "
        f"through OpenOCD TCP {config.down_port}\n"
        f"Expected up name: {config.curve_up_name or '(not checked)'}\n"
        f"Expected down name: {config.down_name or '(not checked)'}\n"
        f"JustFloat values per frame: {float_count}\n"
        "\n"
        "Transport contract\n"
        "------------------\n"
        "- Text and curve data are isolated by RTT up-channel.\n"
        "- Curve frames use VOFA+ JustFloat: float32 little-endian values followed by "
        "00 00 80 7F.\n"
        "- Reverse TCP bytes are written to the selected RTT down-channel unchanged.\n"
        "- KeilTool does not add framing or interpret commands, CRC, ACK, or business fields.\n"
    )


def write_vofa_session_guide(
    path: str | Path,
    config: VofaRttConfig,
    listen: str,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_vofa_session_guide(config, listen),
        encoding="utf-8",
        newline="\n",
    )
    return output


def _validate_optional_ascii_name(label: str, value: str | None) -> None:
    if value is None:
        return
    if not value:
        raise ValueError(f"{label} must not be empty when provided.")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be ASCII.") from exc


__all__ = [
    "VofaRttConfig",
    "render_vofa_session_guide",
    "write_vofa_session_guide",
]
