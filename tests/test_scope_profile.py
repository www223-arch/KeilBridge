from keiltool.core.scope_profile import BILBOPRO_IMU_SCOPE_V1, write_scope_guide


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

    assert "RTT up-channel: 1 (Scope)" in text
    assert "RTT down-channel: 1 (ScopeCmd)" in text
    assert "transparent raw bytes" in text
    assert "JustFloat: 15 x float32 little-endian + 00 00 80 7F" in text
    assert "I0  = acc_g.x" in text
    assert "I14 = euler_9dof_deg.yaw" in text
    assert "VOFA+" in text
