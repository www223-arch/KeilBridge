from keiltool.core.scope_profile import (
    BILBOPRO_IMU_LOOP_SCOPE_V2,
    BILBOPRO_IMU_SCOPE_V1,
    get_scope_profile,
    write_scope_guide,
)


def test_bilbopro_imu_scope_v1_has_stable_15_channel_contract():
    profile = BILBOPRO_IMU_SCOPE_V1

    assert profile.profile_id == "bilbopro-imu-scope-v1"
    assert profile.expected_float_count == 15
    assert profile.rtt_down_channel_name == "ScopeCmd"
    assert profile.channels == (
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
    )


def test_scope_guide_contains_vofa_mapping_and_first_use_steps(tmp_path):
    path = write_scope_guide(tmp_path / "scope-channels.txt", BILBOPRO_IMU_SCOPE_V1)
    text = path.read_text(encoding="utf-8")

    assert "RTT text up-channel: 0" in text
    assert "never forwarded to VOFA+" in text
    assert "RTT up-channel: 1 (Scope)" in text
    assert "RTT down-channel: 1 (ScopeCmd)" in text
    assert "transparent raw bytes" in text
    assert "JustFloat: 15 x float32 little-endian + 00 00 80 7F" in text
    assert "I0  = acc_g.x" in text
    assert "I14 = euler_9dof_deg.yaw" in text
    assert "VOFA+" in text
    assert "ScopeCmd control frame v1" not in text


def test_bilbopro_loop_scope_v2_extends_v1_without_changing_existing_indices():
    profile = BILBOPRO_IMU_LOOP_SCOPE_V2

    assert profile.profile_id == "bilbopro-imu-loop-scope-v2"
    assert profile.rtt_channel == 2
    assert profile.rtt_channel_name == "LoopScope"
    assert profile.rtt_port == 19023
    assert profile.vofa_port == 1348
    assert profile.rtt_down_channel == 1
    assert profile.rtt_down_port == 19022
    assert profile.rtt_down_channel_name == "ScopeCmd"
    assert profile.telemetry_hz == 100
    assert profile.expected_float_count == 40
    assert profile.channels[:15] == BILBOPRO_IMU_SCOPE_V1.channels
    assert profile.channels[15:] == (
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
    )
    assert get_scope_profile(profile.profile_id) is profile


def test_loop_scope_guide_records_transport_and_control_contract(tmp_path):
    path = write_scope_guide(
        tmp_path / "loop-scope-v2.txt",
        BILBOPRO_IMU_LOOP_SCOPE_V2,
    )
    text = path.read_text(encoding="utf-8")

    assert "RTT up-channel: 2 (LoopScope), OpenOCD TCP 19023" in text
    assert "RTT down-channel: 1 (ScopeCmd), OpenOCD TCP 19022" in text
    assert "VOFA+ TCP: 127.0.0.1:1348" in text
    assert "Telemetry rate: 100 Hz" in text
    assert "JustFloat: 40 x float32" in text
    assert "I39 = control.last_cmd_result_status_bitmask" in text
    assert "SOF B1 50" in text
    assert "crc16_ccitt_false" in text
    assert "TTL maximum: 30000 ms" in text
