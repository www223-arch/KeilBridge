from dataclasses import replace
from types import SimpleNamespace

import pytest


def _fact_key():
    from keiltool.gui.workbench_controller import FactInputs

    return FactInputs(
        project="D:/fw/motor.uvprojx",
        target="Debug",
        openocd="D:/tools/openocd.exe",
        scripts="D:/tools/scripts",
        target_override="target/stm32f3x.cfg",
    )


def _snapshot(key):
    from keiltool.gui.workbench_controller import VerifiedSnapshot

    return VerifiedSnapshot(
        key=key,
        loaded_project=object(),
        target=object(),
        facts=object(),
    )


def test_fact_edit_immediately_invalidates_verified_snapshot():
    from keiltool.gui.workbench_controller import FreshnessController

    controller = FreshnessController()
    original = _fact_key()
    controller.observe(original)
    controller.accept(_snapshot(original))

    controller.observe(replace(original, scripts="D:/other/scripts"))

    assert controller.snapshot is None
    assert controller.is_current(original) is False


def test_snapshot_key_mismatch_is_rejected():
    from keiltool.gui.workbench_controller import FreshnessController, SnapshotKeyMismatch

    controller = FreshnessController()
    visible = _fact_key()
    controller.observe(visible)

    with pytest.raises(SnapshotKeyMismatch, match="visible"):
        controller.accept(_snapshot(replace(visible, openocd="D:/stale/openocd.exe")))


def test_resolve_verified_snapshot_reloads_project_with_current_visible_values():
    from keiltool.gui.workbench_controller import resolve_verified_snapshot

    key = _fact_key()
    target = SimpleNamespace(name="Debug")
    loaded = SimpleNamespace(project_root="D:/fw", targets=(target,))
    facts = SimpleNamespace(ready=True)
    calls = []

    def load(project):
        calls.append(("load", str(project)))
        return loaded

    def resolve(selected, project_root, **kwargs):
        calls.append(("resolve", selected, project_root, kwargs))
        return facts

    snapshot = resolve_verified_snapshot(key, load_targets=load, resolve_facts=resolve)

    assert snapshot.key == key
    assert snapshot.loaded_project is loaded
    assert snapshot.target is target
    assert snapshot.facts is facts
    assert calls == [
        ("load", key.project),
        (
            "resolve",
            target,
            loaded.project_root,
            {
                "openocd_path": key.openocd,
                "scripts_dir": key.scripts,
                "target_override": key.target_override,
            },
        ),
    ]


def test_incomplete_cleanup_retains_ownership_and_blocks_close_until_retry_completes():
    from keiltool.gui.workbench_controller import LifecycleAction, RttLifecycleController

    session = object()
    lifecycle = RttLifecycleController()
    lifecycle.begin_start(session)
    lifecycle.start_settled(session)

    assert lifecycle.request_close() is LifecycleAction.STOP_SESSION
    assert lifecycle.terminal(session, "incomplete") is LifecycleAction.NONE
    assert lifecycle.owns_session is True
    assert lifecycle.can_destroy is False

    assert lifecycle.request_stop() is LifecycleAction.STOP_SESSION
    assert lifecycle.terminal(session, "clean") is LifecycleAction.RELEASE_SESSION
    assert lifecycle.owns_session is False
    assert lifecycle.can_destroy is True


def test_immediate_start_stop_is_serialized_until_start_settles():
    from keiltool.gui.workbench_controller import LifecycleAction, RttLifecycleController, RttPhase

    session = object()
    lifecycle = RttLifecycleController()
    lifecycle.begin_start(session)

    assert lifecycle.request_stop() is LifecycleAction.NONE
    assert lifecycle.phase is RttPhase.STOP_PENDING
    assert lifecycle.start_settled(session) is LifecycleAction.STOP_SESSION
    assert lifecycle.phase is RttPhase.STOPPING


def test_close_during_start_waits_for_start_then_cleanup_terminal():
    from keiltool.gui.workbench_controller import LifecycleAction, RttLifecycleController

    session = object()
    lifecycle = RttLifecycleController()
    lifecycle.begin_start(session)

    assert lifecycle.request_close() is LifecycleAction.NONE
    assert lifecycle.can_destroy is False
    assert lifecycle.start_settled(session) is LifecycleAction.STOP_SESSION
    assert lifecycle.terminal(session, "forced") is LifecycleAction.RELEASE_SESSION
    assert lifecycle.can_destroy is True


def test_worker_error_keeps_session_until_one_terminal_event():
    from keiltool.gui.workbench_controller import LifecycleAction, RttLifecycleController

    session = object()
    lifecycle = RttLifecycleController()
    lifecycle.begin_start(session)

    assert lifecycle.worker_failed(session, "start") is LifecycleAction.STOP_SESSION
    assert lifecycle.owns_session is True
    assert lifecycle.accepted_terminals == 0

    assert lifecycle.terminal(session, "clean") is LifecycleAction.RELEASE_SESSION
    assert lifecycle.owns_session is False
    assert lifecycle.accepted_terminals == 1


def test_out_of_order_worker_events_cannot_reacquire_released_session():
    from keiltool.gui.workbench_controller import LifecycleAction, RttLifecycleController, RttPhase

    session = object()
    lifecycle = RttLifecycleController()
    lifecycle.begin_start(session)

    assert lifecycle.terminal(session, "clean") is LifecycleAction.RELEASE_SESSION
    assert lifecycle.start_settled(session) is LifecycleAction.NONE
    assert lifecycle.worker_failed(session, "start") is LifecycleAction.NONE
    assert lifecycle.terminal(session, "clean") is LifecycleAction.NONE
    assert lifecycle.phase is RttPhase.IDLE
    assert lifecycle.accepted_terminals == 1


@pytest.mark.parametrize(
    ("answer", "expected_name"),
    [
        (True, "RETRY"),
        (False, "CLOSE_WITHOUT_SAVING"),
        (None, "STAY_OPEN"),
    ],
)
def test_save_failure_decision_is_explicit(answer, expected_name):
    from keiltool.gui.workbench_controller import save_failure_action

    assert save_failure_action(answer).name == expected_name
