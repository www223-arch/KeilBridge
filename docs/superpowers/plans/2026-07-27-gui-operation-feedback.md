# GUI Operation Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trustworthy lifecycle progress, persistent success/failure presentation, and hidden Windows OpenOCD processes to the GUI.

**Architecture:** A UI-independent latest-operation model represents state, stage, progress mode, timing, result summary, logs, and copyable errors. A fixed `OperationStatusPane` renders that model above the existing output notebook, while `KeilToolGui` updates it only at existing lifecycle boundaries. A core subprocess helper supplies Windows background launch flags to GUI-owned OpenOCD processes without changing CLI behavior.

**Tech Stack:** Python 3.11+, Tkinter/ttk, subprocess/OpenOCD, pytest.

## Global Constraints

- Never invent time-based completion percentages for OpenOCD work.
- External OpenOCD execution uses an indeterminate bar unless a reliable byte count exists.
- Normal success and operation failure do not use informational/error dialogs.
- Decision dialogs for Flash confirmation, firmware reload, safe shutdown, and settings persistence remain.
- GUI-owned OpenOCD processes use `CREATE_NO_WINDOW` on Windows; CLI behavior remains unchanged.
- Existing task ownership, cleanup blocking, session logs, and hardware safety semantics remain authoritative.
- All files remain UTF-8.

---

### Task 1: GUI Background Process Launch Policy

**Files:**
- Create: `keiltool/core/process_launch.py`
- Modify: `keiltool/core/openocd_backend.py`
- Modify: `keiltool/core/rtt.py`
- Test: `tests/test_process_launch.py`
- Test: `tests/test_openocd_backend.py`
- Test: `tests/test_rtt.py`

**Interfaces:**
- Produces: `background_process_kwargs(platform: str | None = None) -> dict[str, int]`.
- Consumes: `OpenOcdOperation(..., background: bool = False)` and `RttSession(..., background: bool = False)` opt-in from GUI callers.

- [x] Write failing tests proving Windows returns `{"creationflags": subprocess.CREATE_NO_WINDOW}`, non-Windows returns `{}`, and injected Popen factories receive the option only when `background=True`.
- [x] Run `python -m pytest tests/test_process_launch.py tests/test_openocd_backend.py tests/test_rtt.py -q` and verify failures are limited to the missing helper/constructor options.
- [x] Implement `background_process_kwargs()` and merge it into the Popen keyword arguments in `OpenOcdOperation.execute()` and `RttSession.start()` only when opted in.
- [x] Update GUI operation/session construction to pass `background=True`; leave CLI constructors at the default.
- [x] Run the focused tests and require all to pass.

### Task 2: Operation Feedback Model And Fixed Pane

**Files:**
- Create: `keiltool/gui/operation_feedback.py`
- Modify: `keiltool/gui/widgets.py`
- Modify: `keiltool/gui/theme.py`
- Test: `tests/test_operation_feedback.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Produces: `OperationVisualState`, `ProgressMode`, and mutable `OperationFeedback` methods `reset()`, `begin(task, stage, started_at)`, `set_stage(stage, mode, value)`, `succeed(summary, artifact, log_dir)`, `fail(summary, detail, log_dir, returncode)`, `stopping(stage)`, and `incomplete(summary, detail)`.
- Produces: `OperationStatusPane.update(feedback)`, `set_copy_command(callback)`, and `set_open_logs_command(callback)`.
- Produces: `OutputNotebook.select_openocd()`.

- [x] Write failing model tests for idle/running/succeeded/failed/stopping/incomplete transitions, elapsed time, copyable detail, progress mode, and completion value 100.
- [x] Run `python -m pytest tests/test_operation_feedback.py -q` and verify import/interface failures.
- [x] Implement the model without importing Tkinter.
- [x] Add a stable-height status pane with task/state, stage, elapsed time, progress bar, summary, and conditional copy/open-log actions; extend semantic theme styles without using color as the only state cue.
- [x] Place the pane above `OutputNotebook` in the right column and expose notebook tab selection.
- [x] Extend the existing single-root GUI smoke test to assert dimensions, labels, progress mode switching, and OpenOCD tab selection.
- [x] Run `python -m pytest tests/test_operation_feedback.py tests/test_gui_smoke.py -q` and require all to pass.

### Task 3: One-Shot Operation Lifecycle Integration

**Files:**
- Modify: `keiltool/gui/app.py`
- Modify: `keiltool/gui/workbench_controller.py` only if a pure transition helper is required
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_gui_workbench_controller.py`

**Interfaces:**
- Consumes: `OperationFeedback` and `OperationStatusPane` from Task 2.
- Produces: app helpers `_begin_feedback(task, stage)`, `_set_feedback_stage(stage, mode, value)`, `_complete_feedback(summary, artifact, log_dir)`, `_fail_feedback(summary, detail, log_dir, returncode)`, and `_refresh_operation_feedback()`.

- [x] Write failing integration tests showing connection, Flash read, and Flash begin in `准备配置`, enter indeterminate `OpenOCD 执行中`, then finish at 100 with summary/artifact/log path.
- [x] Write failing tests showing setup validation and worker/result failures select the OpenOCD tab, expose copyable details, and do not call `messagebox.showerror` or `messagebox.showinfo`.
- [x] Run focused GUI/controller tests and verify the expected lifecycle failures.
- [x] Instantiate the feedback model, add a 100 ms elapsed refresh while running, and update feedback at existing one-shot dispatch, result, error, and cleanup boundaries.
- [x] Replace normal connection/Flash/Flash-read success and failure dialogs with panel updates; preserve Flash confirmation and firmware reload decisions.
- [x] Ensure cleanup-incomplete state remains visible and conflicting controls remain disabled until the existing lifecycle releases ownership.
- [x] Run focused GUI/controller tests and require all to pass.

### Task 4: RTT Feedback, Documentation, And Runtime Verification

**Files:**
- Modify: `keiltool/gui/app.py`
- Modify: `docs/01_KeilBridge_用户使用手册.md`
- Modify: `docs/03_KeilBridge_FAQ.md`
- Modify: `docs/superpowers/plans/2026-07-27-gui-operation-feedback.md`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_rtt.py`

**Interfaces:**
- Consumes: existing `RttEvent` kinds and feedback helpers from Task 3.
- Produces: visible RTT stages `准备配置`, `扫描 RTT 控制块`, `正在采集`, `正在停止`, and terminal success/failure/incomplete summaries.

- [x] Write failing GUI tests for RTT scan, connected capture, live elapsed/byte/line evidence, stopping, clean stop, startup failure, and incomplete cleanup feedback.
- [x] Run RTT/GUI focused tests and verify the expected feedback failures.
- [x] Update RTT event handling and stop dispatch to drive the panel while preserving existing counters, logs, level filtering, and cleanup retry behavior.
- [x] Route remaining hardware-action setup errors into the panel; retain only the decision dialogs listed in Global Constraints.
- [x] Document the current-task panel, progress semantics, non-dialog results, error copying, log navigation, and hidden Windows OpenOCD behavior.
- [x] Run `python -m pytest -q` and `git diff --check`.
- [x] Launch `python -m keiltool.cli gui`, visually verify stable layout and validation-failure presentation, and close the test instance without accessing hardware.
- [x] Mark every checklist item complete and commit the implementation.
