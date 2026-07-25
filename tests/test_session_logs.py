from __future__ import annotations

from datetime import datetime
import json

from keiltool.core.session_logs import create_session_logs


def test_creates_timestamped_device_task_directory_and_headers(tmp_path):
    now = datetime.fromisoformat("2026-07-24T21:18:30.125000+08:00")

    context = create_session_logs(
        tmp_path,
        device="GD32F303VE",
        task="RTT",
        metadata={"probe": "ST-Link", "target_cfg": "target/stm32f3x.cfg"},
        now=now,
    )

    assert context.directory.name == "20260724-211830-125_GD32F303VE_RTT"
    assert context.primary_log.name == "rtt.log"
    assert context.stdout_log.name == "openocd.stdout.log"
    assert context.stderr_log.name == "openocd.stderr.log"
    assert context.metadata_log.name == "session.json"
    assert "Task    : RTT" in context.primary_log.read_text(encoding="utf-8")
    metadata = json.loads(context.metadata_log.read_text(encoding="utf-8"))
    assert metadata["device"] == "GD32F303VE"
    assert metadata["probe"] == "ST-Link"
    assert metadata["started_at"] == now.isoformat()


def test_sanitizes_names_retries_collision_and_finalizes_atomically(tmp_path):
    now = datetime.fromisoformat("2026-07-24T21:18:30.125000+08:00")
    first = create_session_logs(tmp_path, device="GD32/F303 VE", task="连接 检查", now=now)
    second = create_session_logs(tmp_path, device="GD32/F303 VE", task="连接 检查", now=now)

    assert first.directory.name == "20260724-211830-125_GD32_F303_VE_连接_检查"
    assert second.directory.name.endswith("_2")

    ended = datetime.fromisoformat("2026-07-24T21:18:32.625000+08:00")
    first.finalize("succeeded", ended_at=ended)
    metadata = json.loads(first.metadata_log.read_text(encoding="utf-8"))

    assert metadata["outcome"] == "succeeded"
    assert metadata["ended_at"] == ended.isoformat()
    assert metadata["duration_seconds"] == 2.5
    assert "Outcome : succeeded" in first.primary_log.read_text(encoding="utf-8")


def test_failed_root_creation_does_not_create_partial_session(tmp_path):
    root = tmp_path / "not-a-directory"
    root.write_text("file", encoding="utf-8")

    try:
        create_session_logs(root, device="GD32F303VE", task="RTT")
    except OSError:
        pass
    else:
        raise AssertionError("Expected session log creation to fail.")

    assert list(tmp_path.iterdir()) == [root]
