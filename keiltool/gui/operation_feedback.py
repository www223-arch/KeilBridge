from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import time


class OperationVisualState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPING = "stopping"
    INCOMPLETE = "incomplete"


class ProgressMode(Enum):
    NONE = "none"
    DETERMINATE = "determinate"
    INDETERMINATE = "indeterminate"


@dataclass(slots=True)
class OperationFeedback:
    task: str = "当前任务"
    state: OperationVisualState = OperationVisualState.IDLE
    stage: str = "等待操作"
    summary: str = ""
    detail: str = ""
    artifact: Path | None = None
    log_dir: Path | None = None
    returncode: int | None = None
    progress_mode: ProgressMode = ProgressMode.NONE
    progress_value: int = 0
    started_at: float | None = None
    finished_at: float | None = None

    def reset(self) -> None:
        self.task = "当前任务"
        self.state = OperationVisualState.IDLE
        self.stage = "等待操作"
        self.summary = ""
        self.detail = ""
        self.artifact = None
        self.log_dir = None
        self.returncode = None
        self.progress_mode = ProgressMode.NONE
        self.progress_value = 0
        self.started_at = None
        self.finished_at = None

    def begin(self, task: str, stage: str, *, started_at: float | None = None) -> None:
        self.task = task
        self.state = OperationVisualState.RUNNING
        self.stage = stage
        self.summary = ""
        self.detail = ""
        self.artifact = None
        self.log_dir = None
        self.returncode = None
        self.progress_mode = ProgressMode.DETERMINATE
        self.progress_value = 10
        self.started_at = time.monotonic() if started_at is None else started_at
        self.finished_at = None

    def set_stage(
        self,
        stage: str,
        mode: ProgressMode,
        value: int | None = None,
    ) -> None:
        self.stage = stage
        self.progress_mode = mode
        if value is not None:
            self.progress_value = max(0, min(100, value))

    def succeed(
        self,
        summary: str,
        *,
        artifact: Path | None = None,
        log_dir: Path | None = None,
        finished_at: float | None = None,
    ) -> None:
        self.state = OperationVisualState.SUCCEEDED
        self.stage = "已完成"
        self.summary = summary
        self.detail = ""
        self.artifact = artifact
        self.log_dir = log_dir
        self.returncode = 0
        self.progress_mode = ProgressMode.DETERMINATE
        self.progress_value = 100
        self.finished_at = time.monotonic() if finished_at is None else finished_at

    def fail(
        self,
        summary: str,
        *,
        detail: str = "",
        log_dir: Path | None = None,
        returncode: int | None = None,
        finished_at: float | None = None,
    ) -> None:
        self.state = OperationVisualState.FAILED
        self.stage = "执行失败"
        self.summary = summary
        self.detail = detail
        self.log_dir = log_dir
        self.returncode = returncode
        self.progress_mode = ProgressMode.DETERMINATE
        self.finished_at = time.monotonic() if finished_at is None else finished_at

    def stopping(self, stage: str) -> None:
        self.state = OperationVisualState.STOPPING
        self.stage = stage
        self.progress_mode = ProgressMode.INDETERMINATE

    def incomplete(
        self,
        summary: str,
        detail: str = "",
        *,
        finished_at: float | None = None,
    ) -> None:
        self.state = OperationVisualState.INCOMPLETE
        self.stage = "清理不完整"
        self.summary = summary
        self.detail = detail
        self.progress_mode = ProgressMode.DETERMINATE
        self.finished_at = time.monotonic() if finished_at is None else finished_at

    def elapsed(self, now: float | None = None) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at
        if end is None:
            end = time.monotonic() if now is None else now
        return max(0.0, end - self.started_at)

    @property
    def copyable_error(self) -> str:
        lines = [self.summary]
        if self.returncode is not None:
            lines.append(f"OpenOCD 返回码: {self.returncode}")
        if self.detail:
            lines.append(self.detail)
        return "\n".join(line for line in lines if line)


__all__ = ["OperationFeedback", "OperationVisualState", "ProgressMode"]
