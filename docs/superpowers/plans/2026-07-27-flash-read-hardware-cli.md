# Flash Read And Hardware CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complete user-Flash readback, safe external firmware reload detection, and connect/flash/RTT CLI workflows.

**Architecture:** A shared hardware-context resolver converts either a Keil project target or exact catalog Device into verified facts and OpenOCD configuration. Core operations own OpenOCD commands, evidence, files, and cleanup; GUI and CLI remain thin consumers. Firmware freshness is represented independently from widget state so a changed file cannot be flashed without explicit acceptance.

**Tech Stack:** Python 3.11+, argparse, Tkinter/ttk, OpenOCD, pytest.

## Global Constraints

- Flash read never resets the target and restores its original running state.
- RTT never resets, halts, or resumes the target.
- Hardware target resolution fails closed when facts or cfg files are unverified.
- Existing project-based `k2c flash` invocations remain valid.
- All text and JSON files use UTF-8.

---

### Task 1: Structured Flash Facts And Shared Hardware Context

**Files:**
- Create: `keiltool/core/hardware_context.py`
- Modify: `keiltool/gui/project_config.py`
- Test: `tests/test_hardware_context.py`
- Test: `tests/test_gui_project_config.py`

**Interfaces:**
- Produces: `MemoryRange`, `HardwareContext`, `HardwareSelection`, and `resolve_hardware_context(selection)`.
- Produces: `ProjectTargetFacts.flash_origin` and `flash_size` for GUI compatibility.

- [ ] Write failing tests for exact project/device selection, ambiguity, primary Flash/RAM ranges, verified cfg, and unresolved failure.
- [ ] Run focused tests and verify failures are caused by missing interfaces.
- [ ] Implement the resolver by reusing catalog, project parser, and verified cfg rules.
- [ ] Adapt GUI project facts without changing existing displayed summaries.
- [ ] Run focused tests and verify they pass.

### Task 2: Core Complete Flash Readback

**Files:**
- Modify: `keiltool/core/openocd_backend.py`
- Test: `tests/test_openocd_backend.py`

**Interfaces:**
- Produces: `FlashReadRequest`, `FlashReadResult`, `build_flash_read_command()`, and `run_flash_read()`.

- [ ] Write failing command tests for quoted output paths, initial-state capture, halt, `dump_image`, conditional resume, shutdown, and no reset command.
- [ ] Write failing result tests for exact byte count, SHA-256, partial output, OpenOCD failure, timeout, and cancellation cleanup.
- [ ] Implement command construction and read result validation through `OpenOcdOperation`.
- [ ] Run backend tests and verify they pass.

### Task 3: Firmware External-Change Gate

**Files:**
- Create: `keiltool/gui/firmware_freshness.py`
- Modify: `keiltool/gui/app.py`
- Test: `tests/test_firmware_freshness.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Produces: `FirmwareFingerprint`, `FirmwareFreshness`, `observe(path)`, `accept(path)`, and `is_current(path)`.

- [ ] Write failing tests for SHA-256 fingerprints, same-path changes, missing files, accept, decline/stale state, and reselection.
- [ ] Implement the independent freshness model.
- [ ] Bind a debounced root focus-return check and prompt with old/new evidence.
- [ ] Add a final freshness check before flash dispatch and disable flash while stale.
- [ ] Run focused tests and verify they pass.

### Task 4: GUI Flash Read Action

**Files:**
- Modify: `keiltool/gui/state.py`
- Modify: `keiltool/gui/widgets.py`
- Modify: `keiltool/gui/workbench_model.py`
- Modify: `keiltool/gui/app.py`
- Test: `tests/test_gui_state.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: `FlashReadRequest` and `run_flash_read()`.
- Produces: separate `读取完整 Flash` button and `SessionState.FLASH_READ` lifecycle.

- [ ] Write failing state/readiness tests and a GUI dispatch/result test.
- [ ] Add the stable three-command action layout and save-file selection.
- [ ] Dispatch through the existing exclusive one-shot gate and session logs.
- [ ] Render origin, size, output path, SHA-256, and evidence logs.
- [ ] Run GUI tests and verify they pass.

### Task 5: Connect, Flash Write, And Flash Read CLI

**Files:**
- Modify: `keiltool/cli.py`
- Create: `keiltool/core/cli_output.py`
- Test: `tests/test_cli_hardware.py`
- Modify: `tests/test_cli_flash.py`

**Interfaces:**
- Produces: `k2c connect`, `k2c flash-read`, and extended `k2c flash` selectors.

- [ ] Write failing parser tests for mutually exclusive project/device selection and legacy flash compatibility.
- [ ] Write failing command tests for text/JSON success and failure output with stable exit codes.
- [ ] Implement common hardware arguments, context resolution, session logs, and rendering.
- [ ] Run CLI hardware tests and verify they pass.

### Task 6: RTT Raw Events And CLI

**Files:**
- Modify: `keiltool/core/rtt.py`
- Modify: `keiltool/cli.py`
- Test: `tests/test_rtt.py`
- Create: `tests/test_cli_rtt.py`

**Interfaces:**
- Produces: raw byte `RttEvent` data and `k2c rtt --format text|jsonl|raw`.

- [ ] Write failing RTT tests proving original recv bytes are emitted without changing decoded GUI records.
- [ ] Write failing CLI tests for text, versioned JSONL, raw output, duration stop, Ctrl+C exit 130, and bounded cleanup.
- [ ] Add raw events to `RttSession` and preserve existing text logging/parser behavior.
- [ ] Implement CLI streaming with payload on stdout and diagnostics on stderr.
- [ ] Run RTT and CLI tests and verify they pass.

### Task 7: Documentation, Full Verification, And Runtime Smoke

**Files:**
- Modify: `docs/01_KeilBridge_用户使用手册.md`
- Modify: `docs/03_KeilBridge_FAQ.md`
- Modify: `docs/superpowers/plans/2026-07-27-flash-read-hardware-cli.md`

**Interfaces:**
- Documents final commands, safety behavior, output schemas, and reload semantics.

- [ ] Run `python -m pytest -q` and require the complete suite to pass.
- [ ] Run CLI `--help` and parser smoke commands.
- [ ] Launch the GUI, verify layout and firmware reload prompt without performing a write.
- [ ] If ST-Link connects read-only, perform one Flash readback and verify exact size/SHA-256; otherwise record the hardware blocker without claiming a hardware pass.
- [ ] Update every checklist item and commit the implementation.
