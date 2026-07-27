from __future__ import annotations

from pathlib import Path

from keiltool.gui.operation_feedback import (
    OperationFeedback,
    OperationVisualState,
    ProgressMode,
)


def test_operation_feedback_tracks_running_stage_and_elapsed_time():
    feedback = OperationFeedback()

    feedback.begin("读取完整 Flash", "准备配置", started_at=10.0)
    feedback.set_stage("OpenOCD 执行中", ProgressMode.INDETERMINATE)

    assert feedback.state is OperationVisualState.RUNNING
    assert feedback.task == "读取完整 Flash"
    assert feedback.stage == "OpenOCD 执行中"
    assert feedback.progress_mode is ProgressMode.INDETERMINATE
    assert feedback.elapsed(13.25) == 3.25


def test_operation_feedback_success_finishes_at_100_and_keeps_artifact():
    feedback = OperationFeedback()
    feedback.begin("读取完整 Flash", "准备配置", started_at=10.0)

    feedback.succeed(
        "已读取 524,288 字节",
        artifact=Path("D:/logs/full.bin"),
        log_dir=Path("D:/logs/session"),
        finished_at=12.0,
    )

    assert feedback.state is OperationVisualState.SUCCEEDED
    assert feedback.progress_mode is ProgressMode.DETERMINATE
    assert feedback.progress_value == 100
    assert feedback.elapsed(20.0) == 2.0
    assert feedback.artifact == Path("D:/logs/full.bin")
    assert feedback.log_dir == Path("D:/logs/session")


def test_operation_feedback_failure_retains_copyable_evidence():
    feedback = OperationFeedback()
    feedback.begin("检查连接", "OpenOCD 执行中", started_at=10.0)

    feedback.fail(
        "无法连接目标",
        detail="Error: init mode failed",
        log_dir=Path("D:/logs/connect"),
        returncode=1,
        finished_at=11.0,
    )

    assert feedback.state is OperationVisualState.FAILED
    assert feedback.summary == "无法连接目标"
    assert feedback.detail == "Error: init mode failed"
    assert feedback.returncode == 1
    assert feedback.copyable_error == "无法连接目标\nOpenOCD 返回码: 1\nError: init mode failed"


def test_operation_feedback_stopping_and_incomplete_are_explicit():
    feedback = OperationFeedback()
    feedback.begin("RTT", "正在采集", started_at=10.0)

    feedback.stopping("正在停止")
    assert feedback.state is OperationVisualState.STOPPING
    assert feedback.progress_mode is ProgressMode.INDETERMINATE

    feedback.incomplete("清理不完整", "OpenOCD 尚未退出", finished_at=15.0)
    assert feedback.state is OperationVisualState.INCOMPLETE
    assert feedback.summary == "清理不完整"
    assert feedback.detail == "OpenOCD 尚未退出"


def test_operation_feedback_reset_returns_stable_idle_state():
    feedback = OperationFeedback()
    feedback.begin("烧录并校验", "准备配置", started_at=1.0)
    feedback.reset()

    assert feedback.state is OperationVisualState.IDLE
    assert feedback.task == "当前任务"
    assert feedback.stage == "等待操作"
    assert feedback.progress_mode is ProgressMode.NONE
