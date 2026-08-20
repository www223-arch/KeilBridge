from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScopeProfile:
    profile_id: str
    title: str
    rtt_channel: int
    rtt_channel_name: str
    rtt_down_channel_name: str
    channels: tuple[str, ...]

    @property
    def expected_float_count(self) -> int:
        return len(self.channels)


BILBOPRO_IMU_SCOPE_V1 = ScopeProfile(
    profile_id="bilbopro-imu-scope-v1",
    title="BilboPro IMU Scope v1",
    rtt_channel=1,
    rtt_channel_name="Scope",
    rtt_down_channel_name="ScopeCmd",
    channels=(
        "acc_g.x",
        "acc_g.y",
        "acc_g.z",
        "gyro_dps.x",
        "gyro_dps.y",
        "gyro_dps.z",
        "mag_uT.x",
        "mag_uT.y",
        "mag_uT.z",
        "euler_6dof_deg.roll",
        "euler_6dof_deg.pitch",
        "euler_6dof_deg.yaw",
        "euler_9dof_deg.roll",
        "euler_9dof_deg.pitch",
        "euler_9dof_deg.yaw",
    ),
)


def render_scope_guide(profile: ScopeProfile) -> str:
    mapping = "\n".join(
        f"I{index:<2} = {name}" for index, name in enumerate(profile.channels)
    )
    return (
        f"{profile.title}\n"
        f"Profile ID: {profile.profile_id}\n"
        "RTT text up-channel: 0 (KeilTool log only; never forwarded to VOFA+)\n"
        f"RTT up-channel: {profile.rtt_channel} ({profile.rtt_channel_name})\n"
        f"RTT down-channel: {profile.rtt_channel} ({profile.rtt_down_channel_name})\n"
        "VOFA+ -> MCU: transparent raw bytes; KeilTool adds no encoding, delimiter, or framing.\n"
        f"JustFloat: {profile.expected_float_count} x float32 little-endian + 00 00 80 7F\n"
        "\n"
        "VOFA+ channel mapping\n"
        "---------------------\n"
        f"{mapping}\n"
        "\n"
        "VOFA+ first use\n"
        "---------------\n"
        "1. KeilTool auto-fills TCP Client 127.0.0.1:1347 and JustFloat for VOFA+ 1.3.\n"
        "2. In the newly opened VOFA+ window, click the connection button.\n"
        "3. Add or rename curves using the I0-I14 mapping above.\n"
        "4. Use the VOFA+ send area in text or HEX mode to write RTT down-channel 1.\n"
        "5. Keep this profile fixed for the complete capture session.\n"
    )


def write_scope_guide(path: str | Path, profile: ScopeProfile) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_scope_guide(profile), encoding="utf-8", newline="\n")
    return output


__all__ = [
    "BILBOPRO_IMU_SCOPE_V1",
    "ScopeProfile",
    "render_scope_guide",
    "write_scope_guide",
]
