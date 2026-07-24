from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
import queue
import time
from typing import Callable, Protocol


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


class CancellableOperation(Protocol):
    def cancel(self) -> None: ...


class OneShotPhase(Enum):
    IDLE = auto()
    RUNNING = auto()
    INCOMPLETE = auto()
    CLEANING = auto()


class OneShotLifecycleController:
    def __init__(self) -> None:
        self._owner: CancellableOperation | None = None
        self.close_requested = False
        self.phase = OneShotPhase.IDLE

    @property
    def owns_operation(self) -> bool:
        return self._owner is not None

    @property
    def owner(self) -> CancellableOperation | None:
        return self._owner

    @property
    def can_destroy(self) -> bool:
        return self.close_requested and self._owner is None

    def owns(self, operation: object) -> bool:
        return operation is self._owner

    def begin(self, operation: CancellableOperation) -> None:
        if self._owner is not None:
            raise RuntimeError("A one-shot OpenOCD operation is already owned.")
        self._owner = operation
        self.phase = OneShotPhase.RUNNING

    def result_settled(self, operation: object, outcome: str) -> bool:
        if operation is not self._owner:
            return False
        if outcome == "incomplete":
            self.phase = OneShotPhase.INCOMPLETE
            return False
        self.phase = OneShotPhase.IDLE
        self._owner = None
        return True

    def begin_cleanup(self, operation: object) -> bool:
        if operation is not self._owner or self.phase is not OneShotPhase.INCOMPLETE:
            return False
        self.phase = OneShotPhase.CLEANING
        return True

    def cleanup_settled(self, operation: object, *, complete: bool) -> bool:
        if operation is not self._owner or self.phase is not OneShotPhase.CLEANING:
            return False
        if not complete:
            self.phase = OneShotPhase.INCOMPLETE
            return False
        self.phase = OneShotPhase.IDLE
        self._owner = None
        return True

    def worker_failed(self, operation: object, *, cleanup_pending: bool) -> bool:
        return self.result_settled(
            operation,
            "incomplete" if cleanup_pending else "worker_error",
        )

    def request_close(self) -> None:
        self.close_requested = True
        if self._owner is not None and self.phase is OneShotPhase.RUNNING:
            self._owner.cancel()

    def cancel_close(self) -> None:
        self.close_requested = False


@dataclass(frozen=True, slots=True)
class PolledEvent:
    source: str
    event: object


@dataclass(frozen=True, slots=True)
class EventPollBatch:
    items: tuple[PolledEvent, ...]
    raw_count: int
    backlog: bool


class EventQueue(Protocol):
    def get_nowait(self) -> object: ...

    def empty(self) -> bool: ...


class BoundedEventPoller:
    def __init__(
        self,
        *,
        max_events: int = 200,
        time_budget: float = 0.01,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_events <= 0:
            raise ValueError("Event poll count must be positive.")
        if time_budget <= 0:
            raise ValueError("Event poll time budget must be positive.")
        self._max_events = max_events
        self._time_budget = time_budget
        self._monotonic = monotonic

    def drain(
        self,
        ui_events: EventQueue,
        rtt_events: EventQueue | None,
    ) -> EventPollBatch:
        started = self._monotonic()
        items: list[PolledEvent] = []
        raw_count = 0
        queues = (("ui", ui_events), ("rtt", rtt_events))
        while raw_count < self._max_events:
            if raw_count and self._monotonic() - started >= self._time_budget:
                break
            pulled = False
            for source, event_queue in queues:
                if event_queue is None or raw_count >= self._max_events:
                    continue
                if raw_count and self._monotonic() - started >= self._time_budget:
                    break
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    continue
                raw_count += 1
                pulled = True
                self._append(items, source, event)
            if not pulled:
                break
        backlog = not ui_events.empty() or bool(rtt_events is not None and not rtt_events.empty())
        return EventPollBatch(tuple(items), raw_count, backlog)

    @staticmethod
    def _append(items: list[PolledEvent], source: str, event: object) -> None:
        if (
            source == "rtt"
            and getattr(event, "kind", "") == "data"
            and items
            and items[-1].source == "rtt"
            and getattr(items[-1].event, "kind", "") == "data"
        ):
            previous = items[-1]
            merged = replace(
                previous.event,
                text=str(getattr(previous.event, "text", "")) + str(getattr(event, "text", "")),
            )
            items[-1] = PolledEvent(source, merged)
            return
        items.append(PolledEvent(source, event))


__all__ = [
    "BoundedEventPoller",
    "EventPollBatch",
    "FactInputs",
    "FreshnessController",
    "LifecycleAction",
    "OneShotLifecycleController",
    "PolledEvent",
    "RttLifecycleController",
    "RttPhase",
    "SaveFailureAction",
    "SnapshotKeyMismatch",
    "VerifiedSnapshot",
    "resolve_verified_snapshot",
    "save_failure_action",
]
