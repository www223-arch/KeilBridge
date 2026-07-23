from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable


@dataclass(frozen=True, slots=True)
class FactInputs:
    project: str
    target: str
    openocd: str
    scripts: str
    target_override: str


@dataclass(frozen=True, slots=True)
class VerifiedSnapshot:
    key: FactInputs
    loaded_project: object
    target: object
    facts: object


class SnapshotKeyMismatch(RuntimeError):
    pass


class FreshnessController:
    def __init__(self) -> None:
        self._visible: FactInputs | None = None
        self._snapshot: VerifiedSnapshot | None = None

    @property
    def snapshot(self) -> VerifiedSnapshot | None:
        return self._snapshot

    def observe(self, visible: FactInputs) -> bool:
        changed = visible != self._visible
        self._visible = visible
        if changed:
            self._snapshot = None
        return changed

    def accept(self, snapshot: VerifiedSnapshot) -> None:
        if snapshot.key != self._visible:
            raise SnapshotKeyMismatch("Verified snapshot does not match the current visible fact inputs.")
        self._snapshot = snapshot

    def is_current(self, visible: FactInputs) -> bool:
        return bool(
            self._snapshot is not None
            and self._visible == visible
            and self._snapshot.key == visible
        )


def resolve_verified_snapshot(
    inputs: FactInputs,
    *,
    load_targets: Callable[[str], object] | None = None,
    resolve_facts: Callable[..., object] | None = None,
) -> VerifiedSnapshot:
    if not inputs.project:
        raise ValueError("请选择 Keil 工程。")
    if not inputs.target:
        raise ValueError("请选择 Target。")
    if load_targets is None:
        from keiltool.gui.project_config import load_project_targets

        load_targets = load_project_targets
    if resolve_facts is None:
        from keiltool.gui.project_config import resolve_target_facts

        resolve_facts = resolve_target_facts

    loaded = load_targets(inputs.project)
    targets = tuple(getattr(loaded, "targets"))
    target = next((candidate for candidate in targets if getattr(candidate, "name", "") == inputs.target), None)
    if target is None:
        raise ValueError(f"Keil 工程中不存在 Target: {inputs.target}")
    facts = resolve_facts(
        target,
        getattr(loaded, "project_root"),
        openocd_path=inputs.openocd,
        scripts_dir=inputs.scripts,
        target_override=inputs.target_override,
    )
    return VerifiedSnapshot(inputs, loaded, target, facts)


class RttPhase(Enum):
    IDLE = auto()
    STARTING = auto()
    STOP_PENDING = auto()
    RUNNING = auto()
    STOPPING = auto()
    INCOMPLETE = auto()


class LifecycleAction(Enum):
    NONE = auto()
    STOP_SESSION = auto()
    RELEASE_SESSION = auto()


_COMPLETE_OUTCOMES = frozenset({"clean", "forced", "startup_failed"})


class RttLifecycleController:
    def __init__(self) -> None:
        self.phase = RttPhase.IDLE
        self._owner: object | None = None
        self.close_requested = False
        self.accepted_terminals = 0

    @property
    def owns_session(self) -> bool:
        return self._owner is not None

    @property
    def owner(self) -> object | None:
        return self._owner

    @property
    def can_destroy(self) -> bool:
        return self.close_requested and self.phase is RttPhase.IDLE and self._owner is None

    def begin_start(self, session: object) -> None:
        if self._owner is not None or self.phase is not RttPhase.IDLE:
            raise RuntimeError("An RTT session is already owned.")
        self._owner = session
        self.phase = RttPhase.STARTING

    def request_stop(self) -> LifecycleAction:
        if self._owner is None:
            return LifecycleAction.NONE
        if self.phase is RttPhase.STARTING:
            self.phase = RttPhase.STOP_PENDING
            return LifecycleAction.NONE
        if self.phase in {RttPhase.RUNNING, RttPhase.INCOMPLETE}:
            self.phase = RttPhase.STOPPING
            return LifecycleAction.STOP_SESSION
        return LifecycleAction.NONE

    def request_close(self) -> LifecycleAction:
        self.close_requested = True
        return self.request_stop()

    def cancel_close(self) -> None:
        self.close_requested = False

    def start_settled(self, session: object) -> LifecycleAction:
        if session is not self._owner:
            return LifecycleAction.NONE
        if self.phase is RttPhase.STARTING:
            self.phase = RttPhase.RUNNING
            return LifecycleAction.NONE
        if self.phase is RttPhase.STOP_PENDING:
            self.phase = RttPhase.STOPPING
            return LifecycleAction.STOP_SESSION
        return LifecycleAction.NONE

    def worker_failed(self, session: object, operation: str) -> LifecycleAction:
        if session is not self._owner:
            return LifecycleAction.NONE
        if operation == "start" and self.phase in {
            RttPhase.STARTING,
            RttPhase.STOP_PENDING,
            RttPhase.RUNNING,
        }:
            self.phase = RttPhase.STOPPING
            return LifecycleAction.STOP_SESSION
        return LifecycleAction.NONE

    def terminal(self, session: object, outcome: str) -> LifecycleAction:
        if session is not self._owner:
            return LifecycleAction.NONE
        self.accepted_terminals += 1
        if outcome == "incomplete":
            self.phase = RttPhase.INCOMPLETE
            return LifecycleAction.NONE
        if outcome in _COMPLETE_OUTCOMES:
            self.phase = RttPhase.IDLE
            self._owner = None
            return LifecycleAction.RELEASE_SESSION
        self.phase = RttPhase.INCOMPLETE
        return LifecycleAction.NONE


class SaveFailureAction(Enum):
    RETRY = auto()
    CLOSE_WITHOUT_SAVING = auto()
    STAY_OPEN = auto()


def save_failure_action(answer: bool | None) -> SaveFailureAction:
    if answer is True:
        return SaveFailureAction.RETRY
    if answer is False:
        return SaveFailureAction.CLOSE_WITHOUT_SAVING
    return SaveFailureAction.STAY_OPEN


__all__ = [
    "FactInputs",
    "FreshnessController",
    "LifecycleAction",
    "RttLifecycleController",
    "RttPhase",
    "SaveFailureAction",
    "SnapshotKeyMismatch",
    "VerifiedSnapshot",
    "resolve_verified_snapshot",
    "save_failure_action",
]
