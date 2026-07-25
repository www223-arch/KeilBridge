# Task 4 Report: Tkinter Workbench

Date: 2026-07-23

## Status

Implemented and verified. Task 4 does not add or test the `k2c gui` parser entry; that remains owned by Task 5.

## Implementation

- Added `KeilToolGui` and `launch_gui()` with a fixed-width left configuration pane, resizable right output notebook, and bottom operational status.
- Added project/Target selection, read-only Device/Flash/RAM/target facts, HEX/BIN firmware validation, BIN address enablement, connection checking, and confirmed flash plus verify.
- Added independent RTT auto/manual scan configuration, channel/log controls, start/stop, elapsed time, UTF-8 byte/line counters, display clearing, and log-directory opening.
- Added a collapsed advanced section for OpenOCD, scripts, target override, RTT port, and timeout.
- Delegated all connection, flash, and RTT command/process behavior to `openocd_backend` and `RttSession`; the GUI contains no OpenOCD command construction.
- Added daemon wrappers and queue polling through `root.after(50, ...)`; background workers never update Tk widgets directly.
- Made `TaskGate` authoritative for probe ownership and disabled editing/conflicting actions while work is active.
- Added clean close behavior that waits for one-shot work or stops RTT through `RttSession.stop()` before saving settings and destroying Tk.
- Persisted RTT channel output through `RttSession` and RTT OpenOCD stdout/stderr as separate UTF-8 evidence logs.
- Restored saved fields and project facts without automatically connecting, flashing, or starting RTT.
- Split the initial workbench implementation along coherent ownership boundaries after controller review:
  - `workbench_model.py` owns Tk-free validation, request creation, readiness checks, deterministic log paths, and facts-to-display mapping.
  - `widgets.py` owns the complete left configuration surface, reusable field rows, and the RTT/OpenOCD output notebook.
  - `app.py` retains window/control orchestration, TaskGate transitions, worker dispatch, queued event handling, dialogs, and shutdown.
- Changed package-level GUI exports to lazy loading so importing `workbench_model` does not import Tkinter.

## Files

- `keiltool/gui/app.py`: window/control orchestration, event routing, task state, and shutdown lifecycle.
- `keiltool/gui/workbench_model.py`: pure/headless validation and display-ready model helpers.
- `keiltool/gui/widgets.py`: focused Tk configuration and output surfaces.
- `keiltool/gui/__init__.py`: lazily exports `KeilToolGui` and `launch_gui`.
- `tests/test_gui_smoke.py`: headless-safe import and pure request/path validation.
- `.superpowers/sdd/task-4-report.md`: this report.

## TDD Evidence

### RED

1. Initial focused run: `python -m pytest tests/test_gui_smoke.py -q`
   - Result: `8 failed`
   - Expected cause: `ModuleNotFoundError: No module named 'keiltool.gui.app'`.
2. RTT evidence-path follow-up: `python -m pytest tests/test_gui_smoke.py -q`
   - Result: `1 failed, 8 passed`
   - Expected cause: `ImportError` for the not-yet-implemented `build_rtt_log_paths`.
3. Controller-authorized module extraction: `python -m pytest tests/test_gui_smoke.py -q`
   - Result: `10 failed, 1 passed`
   - Expected cause: `ModuleNotFoundError` for the not-yet-created `keiltool.gui.workbench_model`.

### GREEN

- Focused: `python -m pytest tests/test_gui_smoke.py -q`
  - Result: `11 passed in 0.18s`.
- Full: `python -m pytest -q`
  - Result: `78 passed in 1.76s`.

## Additional Verification

- `python -m py_compile keiltool/gui/app.py keiltool/gui/widgets.py keiltool/gui/workbench_model.py tests/test_gui_smoke.py`: passed.
- `git diff --check`: passed.
- Forbidden-pattern scan found no direct `subprocess.run`, `subprocess.Popen`, `shell=True`, OpenOCD command fragments, reset command, or CLI parser additions in Task 4.
- A real withdrawn Tk root constructed at the default `1280x800`.
- At `1024x720`, the left pane measured 420 px and the right output pane 604 px; requested content size was 868x617.
- A clean interpreter imported `workbench_model` with `tkinter` absent from `sys.modules`.
- File sizes after extraction: `app.py` 774 lines, `workbench_model.py` 134 lines, and `widgets.py` 349 lines.

## Self-Review

- Confirmed HEX ignores the BIN address and BIN uses shared `parse_address()`.
- Confirmed unresolved target facts keep hardware actions disabled.
- Confirmed RTT scan/collection blocks connect and flash, while Stop remains available until stopping begins.
- Confirmed flash success is based only on `FlashResult.success`; failure output includes Doctor findings and log paths.
- Confirmed RTT startup does not request a reset and all commands originate in the core service.
- Confirmed close does not destroy the root while connection/flash is active and invokes bounded RTT cleanup before destruction.
- Confirmed settings restoration performs no hardware action.
- Confirmed all new source/test/report files are UTF-8.
- Confirmed the extracted modules follow behavior/ownership boundaries rather than arbitrary line slices; no task behavior changed.

## Concerns

- No physical ST-Link, target board, or live OpenOCD RTT session was available, so real-hardware acceptance remains for Task 5/final integration.
- `ruff` is not installed in the environment; syntax, whitespace, focused tests, full tests, and targeted static scans were used instead.

## Review Fixes: Freshness And Lifecycle

### Implementation

- Added `workbench_controller.py` as a Tk-free decision layer:
  - `FactInputs`, frozen `VerifiedSnapshot`, and `FreshnessController` key every verified result to all visible fact-driving values.
  - `resolve_verified_snapshot()` always reloads the project and resolves facts using the current project, Target, OpenOCD executable, scripts directory, and target override.
  - `RttLifecycleController` serializes start/stop, queues Stop during start, retains one session owner until a complete terminal event, and blocks close after incomplete cleanup.
  - `save_failure_action()` maps the three settings-save dialog choices to retry, explicit close without saving, or stay open.
- Traced project, Target, OpenOCD, scripts, and target override variables. Every edit immediately invalidates facts and disables hardware actions.
- Changed connect, flash, and RTT start to synchronously obtain a new verified snapshot immediately before acquiring `TaskGate`; `OpenOcdConfig` and Doctor target data come only from that snapshot.
- Added session-token context to RTT worker events so stale or out-of-order worker completions cannot reacquire or discard a released session.
- Queued an immediate Stop/close while RTT start is unsettled, dispatching cleanup only after `session.start()` settles.
- Retained `RttSession`, TaskGate ownership, and the live window after `incomplete`; Stop remains enabled as an explicit cleanup retry.
- Made incomplete `RttSession.stop()` attempts retryable. Log handles are retained when close fails, and each cleanup attempt emits exactly one terminal result.
- Reworked close-time settings persistence to always report failure and offer Retry, Close Without Saving, or Cancel Close before root destruction.

### Files

- Added `keiltool/gui/workbench_controller.py`.
- Modified `keiltool/gui/app.py`.
- Modified `keiltool/core/rtt.py`.
- Added `tests/test_gui_workbench_controller.py`.
- Modified `tests/test_rtt.py`.

### TDD Evidence

#### RED

1. Controller and cleanup retry tests:
   - Command: `python -m pytest tests/test_gui_workbench_controller.py tests/test_rtt.py -q`
   - Result: `11 failed, 18 passed`.
   - Expected causes: missing `workbench_controller` and no second terminal event after retrying incomplete cleanup.
2. Synchronous verifier test:
   - Command: `python -m pytest tests/test_gui_workbench_controller.py -q`
   - Result: `1 failed, 10 passed`.
   - Expected cause: missing `resolve_verified_snapshot`.
3. Incomplete startup cleanup retry:
   - Command: `python -m pytest tests/test_rtt.py::test_incomplete_startup_cleanup_can_be_retried_until_complete -q`
   - Result: `1 failed`.
   - Expected cause: startup cleanup marked the session permanently stopped and discarded the failed log handle.

#### GREEN

- Focused:
  - Command: `python -m pytest tests/test_gui_workbench_controller.py tests/test_gui_smoke.py tests/test_rtt.py tests/test_gui_state.py -q`
  - Result: `45 passed in 0.56s`.
- Full:
  - Command: `python -m pytest -q`
  - Result: `91 passed in 1.80s`.
- Compilation and whitespace:
  - `python -m py_compile keiltool/core/rtt.py keiltool/gui/app.py keiltool/gui/workbench_controller.py tests/test_gui_workbench_controller.py tests/test_rtt.py`: passed.
  - `git diff --check`: passed.

### Self-Review

- Confirmed every fact-driving field invalidates readiness through a Tk variable trace.
- Confirmed explicit refresh and all three hardware actions reload the project and resolve a snapshot from current visible values.
- Confirmed `OpenOcdConfig` uses the verified snapshot executable, scripts directory, interface, and target cfg without mixing cached/UI generations.
- Confirmed immediate Start→Stop and close-during-start produce a pending stop and never call `stop()` before `start()` settles.
- Confirmed worker errors retain session ownership until exactly one terminal event is accepted.
- Confirmed stale/out-of-order worker and duplicate terminal events cannot release or reacquire another session.
- Confirmed `incomplete` blocks editing, hardware reuse, settings save, and root destruction while exposing Stop as cleanup retry.
- Confirmed only complete terminal outcomes release session ownership; startup cleanup failures can also be retried when resource closure is incomplete.
- Confirmed settings-save errors are shown before destruction and every dialog choice has an explicit outcome.
- Confirmed no CLI files or OpenOCD command-building logic changed.
- Runtime probe: verified action state `normal → disabled → normal` across fact edit and refresh, with snapshot key equal to visible values.

### Remaining Concern

- Physical ST-Link/OpenOCD behavior is still not exercised in this environment; automated fake-process/socket coverage and real Tk construction passed.

## Re-review Fixes: RTT Cleanup Concurrency

Date: 2026-07-24

This section supersedes the earlier statement that a log handle is retained after
close failure. A handle is now detached before cleanup and is never published
back to writers, even when flush or close fails.

### Implementation

- Made cleanup state transition, terminal-event reservation, and condition
  notification one atomic lifecycle operation before publishing `stopped`.
- Ensured a cleanup retry invoked directly by the consumer of
  `stopped(incomplete)` observes `cleanup_incomplete`, performs another bounded
  cleanup attempt, and emits its own terminal event.
- Changed log cleanup to set `_log_file = None` while holding the session lock,
  then perform best-effort flush and close on the detached local handle outside
  the lock.
- Kept flush/close failures visible as error events and an `incomplete` outcome
  without exposing the failed handle to later writers or retry attempts.
- Updated prior startup-cleanup tests to assert that a detached failed handle is
  not closed a second time; a later retry can complete once no owned resources
  remain.

### Files

- `keiltool/core/rtt.py`: atomic cleanup finalization and log ownership transfer.
- `tests/test_rtt.py`: immediate-consumer retry, barrier-controlled close/write
  overlap, failed-close detachment, and updated retry ownership expectations.
- `.superpowers/sdd/task-4-report.md`: re-review evidence and self-review.

### TDD Evidence

#### RED

- Command: `python -m pytest -q tests/test_rtt.py -k "terminal_event_consumer or overlapping_writer or republish_detached"`
- Result: `3 failed, 20 deselected in 2.57s`.
- Observed failures:
  - The terminal-event consumer received only `incomplete`; its immediate retry
    was swallowed while the first stop still reported `stopping`.
  - The overlapping writer reached the still-published log handle during close.
  - A close failure left `_log_file` pointing at the unsafe handle.

#### GREEN

- New regression cases:
  - Command: `python -m pytest -q tests/test_rtt.py -k "terminal_event_consumer or overlapping_writer or republish_detached"`
  - Result: `3 passed, 20 deselected in 0.18s`.
- Complete RTT module:
  - Command: `python -m pytest -q tests/test_rtt.py`
  - Result: `23 passed in 0.73s`.
- Focused RTT/controller/GUI:
  - Command: `python -m pytest -q tests/test_rtt.py tests/test_gui_workbench_controller.py tests/test_gui_smoke.py tests/test_gui_state.py tests/test_gui_project_config.py tests/test_gui_settings.py`
  - Result: `59 passed in 1.60s`.
- Full:
  - Command: `python -m pytest -q`
  - Result: `94 passed in 1.91s`.

### Self-Review

- Confirmed terminal state and event ownership are established under
  `_lifecycle` before an event consumer can observe `stopped`.
- Confirmed an immediate retry cannot enter the old `stopping` wait path and
  cannot be lost behind the first cleanup attempt.
- Confirmed a writer already holding `_lock` completes before detachment, while
  every writer after detachment skips the old handle.
- Confirmed flush and close execute without `_lock`, so cleanup does not hold the
  writer synchronization lock during external I/O.
- Confirmed close failure reports an error and incomplete terminal outcome, but
  neither writers nor retries can use the detached handle.
- Confirmed freshness, GUI lifecycle/controller tests, and all prior core tests
  remain green; no CLI or OpenOCD command construction changed.

### Remaining Concern

- Physical RTT hardware was unavailable. The concurrency behavior is covered
  with deterministic condition, queue, socket, and log barriers.
