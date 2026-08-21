from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScopeProfile:
    profile_id: str
    title: str
    rtt_channel: int
    rtt_channel_name: str
    rtt_port: int
    rtt_down_channel: int
    rtt_down_channel_name: str
    rtt_down_port: int
    vofa_port: int
    telemetry_hz: int
    channels: tuple[str, ...]

    @property
    def expected_float_count(self) -> int:
        return len(self.channels)


BILBOPRO_IMU_SCOPE_V1 = ScopeProfile(
    profile_id="bilbopro-imu-scope-v1",
    title="BilboPro IMU Scope v1",
    rtt_channel=1,
    rtt_channel_name="Scope",
    rtt_port=19022,
    rtt_down_channel=1,
    rtt_down_channel_name="ScopeCmd",
    rtt_down_port=19022,
    vofa_port=1347,
    telemetry_hz=200,
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


BILBOPRO_IMU_LOOP_SCOPE_V2 = ScopeProfile(
    profile_id="bilbopro-imu-loop-scope-v2",
    title="BilboPro IMU+Loop Scope v2",
    rtt_channel=2,
    rtt_channel_name="LoopScope",
    rtt_port=19023,
    rtt_down_channel=1,
    rtt_down_channel_name="ScopeCmd",
    rtt_down_port=19022,
    vofa_port=1348,
    telemetry_hz=100,
    channels=(
        *BILBOPRO_IMU_SCOPE_V1.channels,
        "q6.w",
        "q6.x",
        "q6.y",
        "q6.z",
        "q9.w",
        "q9.x",
        "q9.y",
        "q9.z",
        "yaw.target_dps",
        "yaw.feedback_dps",
        "yaw.error_dps",
        "yaw.output_dps",
        "pitch.target_dps",
        "pitch.feedback_dps",
        "pitch.error_dps",
        "pitch.output_dps",
        "control.dt_ms",
        "imu.sample_age_ms",
        "imu.samples_dropped_total",
        "i2c.errors_total",
        "rtt.frames_dropped_total",
        "yaw.error_rms_2s_dps",
        "pitch.error_rms_2s_dps",
        "control.last_cmd_seq",
        "control.last_cmd_result_status_bitmask",
    ),
)


SCOPE_PROFILES = (
    BILBOPRO_IMU_SCOPE_V1,
    BILBOPRO_IMU_LOOP_SCOPE_V2,
)
_SCOPE_PROFILES_BY_ID = {profile.profile_id: profile for profile in SCOPE_PROFILES}


def get_scope_profile(profile_id: str) -> ScopeProfile:
    try:
        return _SCOPE_PROFILES_BY_ID[profile_id]
    except KeyError as exc:
        choices = ", ".join(_SCOPE_PROFILES_BY_ID)
        raise ValueError(f"Unknown scope profile '{profile_id}'. Available: {choices}") from exc


def render_scope_control_contract() -> str:
    return (
        "ScopeCmd control frame v1\n"
        "-------------------------\n"
        "SOF B1 50 | ver u8=1 | type u8 | seq u8 | len u8 (0..32) | "
        "payload[len] | crc16_ccitt_false u16 little-endian\n"
        "CRC coverage: SOF through payload.\n"
        "01 SET_MODE {axis:u8, mode:u8}\n"
        "02 SET_SPEED {axis:u8, target_dps:f32LE}; target_dps [-6.5,+6.5] deg/s\n"
        "03 SET_PID {axis:u8, kp:f32LE, ki:f32LE, kd:f32LE, output_limit_dps:f32LE}\n"
        "04 SET_ATTITUDE_QUAT {w:f32LE, x:f32LE, y:f32LE, z:f32LE}\n"
        "05 SET_ATTITUDE_GAIN {kp:f32LE, kd:f32LE, max_rate_dps:f32LE}; "
        "max_rate_dps (0,6.5] deg/s\n"
        "06 START {axis_mask:u8, ttl_ms:u16LE}\n"
        "07 KEEPALIVE {ttl_ms:u16LE}\n"
        "08 STOP {axis_mask:u8}\n"
        "09 GET_STATE {}\n"
        "axis: 1=yaw/rotate, 2=pitch. mode: 0=open-speed, 1=closed-speed, "
        "2=quaternion-attitude.\n"
        "START is explicit. TTL maximum: 30000 ms; expiry or missing KEEPALIVE stops motion.\n"
        "ACK: LoopScope I38 echoes seq; I39 is 0 on success or a nonzero result/status bitmask.\n"
    )


def render_scope_guide(profile: ScopeProfile) -> str:
    mapping = "\n".join(
        f"I{index:<2} = {name}" for index, name in enumerate(profile.channels)
    )
    control_contract = (
        f"\n{render_scope_control_contract()}"
        if profile.profile_id == BILBOPRO_IMU_LOOP_SCOPE_V2.profile_id
        else ""
    )
    return (
        f"{profile.title}\n"
        f"Profile ID: {profile.profile_id}\n"
        "RTT text up-channel: 0 (KeilTool log only; never forwarded to VOFA+)\n"
        f"RTT up-channel: {profile.rtt_channel} ({profile.rtt_channel_name}), "
        f"OpenOCD TCP {profile.rtt_port}\n"
        f"RTT down-channel: {profile.rtt_down_channel} ({profile.rtt_down_channel_name}), "
        f"OpenOCD TCP {profile.rtt_down_port}\n"
        f"VOFA+ TCP: 127.0.0.1:{profile.vofa_port}\n"
        f"Telemetry rate: {profile.telemetry_hz} Hz\n"
        "VOFA+ -> MCU: transparent raw bytes; KeilTool adds no encoding, delimiter, or framing.\n"
        f"JustFloat: {profile.expected_float_count} x float32 little-endian + 00 00 80 7F\n"
        "\n"
        "VOFA+ channel mapping\n"
        "---------------------\n"
        f"{mapping}\n"
        "\n"
        "VOFA+ first use\n"
        "---------------\n"
        f"1. KeilTool auto-fills TCP Client 127.0.0.1:{profile.vofa_port} "
        "and JustFloat for VOFA+ 1.3.\n"
        "2. In the newly opened VOFA+ window, click the connection button.\n"
        f"3. Add or rename curves using the I0-I{profile.expected_float_count - 1} mapping above.\n"
        f"4. Use the VOFA+ send area for transparent raw bytes, or use KeilTool's "
        f"control-command panel to build complete ScopeCmd frames for RTT down-channel "
        f"{profile.rtt_down_channel}.\n"
        "5. Keep this profile fixed for the complete capture session.\n"
        f"{control_contract}"
    )


def write_scope_guide(path: str | Path, profile: ScopeProfile) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_scope_guide(profile), encoding="utf-8", newline="\n")
    return output


__all__ = [
    "BILBOPRO_IMU_LOOP_SCOPE_V2",
    "BILBOPRO_IMU_SCOPE_V1",
    "SCOPE_PROFILES",
    "ScopeProfile",
    "get_scope_profile",
    "render_scope_control_contract",
    "render_scope_guide",
    "write_scope_guide",
]
