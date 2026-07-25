# Device Source Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Keil project facts and independent catalog Device facts mutually exclusive, persistent GUI modes.

**Architecture:** `GuiSettings` persists the selected mode and the firmware path for each mode. `KeilToolGui` owns the transition between modes, clears active stale state, and feeds only the active source into `FactInputs`. `ConfigurationPane` exposes the two modes as radio controls.

**Tech Stack:** Python 3.11+, Tkinter/ttk, pytest.

## Global Constraints

- A hardware action receives facts from exactly one active source.
- Entering Independent Device mode clears active Target and project firmware.
- Returning to Keil project mode restores and re-resolves the saved project Target.
- Existing version-1 settings remain readable.

---

### Task 1: Persist Source-Specific Settings

**Files:**
- Modify: `keiltool/gui/settings.py`
- Test: `tests/test_gui_settings.py`

**Interfaces:**
- Produces: `GuiSettings.device_source_mode`, `project_firmware`, and `device_firmware`.

- [ ] Write tests showing old settings infer a safe source mode and new fields round-trip.
- [ ] Run `pytest tests/test_gui_settings.py -v` and observe the missing-field failure.
- [ ] Add backward-compatible parsing and serialization for the three fields.
- [ ] Run `pytest tests/test_gui_settings.py -v` and verify it passes.

### Task 2: Add Exclusive Mode Transitions

**Files:**
- Modify: `keiltool/gui/widgets.py`
- Modify: `keiltool/gui/app.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: the new `GuiSettings` fields.
- Produces: `_change_device_source()` and mode-aware `_visible_fact_inputs()`.

- [ ] Write a GUI test that loads project state, switches to Independent Device, and asserts Target, firmware, and project fact inputs are empty.
- [ ] Extend the test to select a catalog Device and assert only catalog identifiers enter `FactInputs`.
- [ ] Extend the test to switch back and assert the project Target and firmware are restored.
- [ ] Run the focused test and observe failure because the source controls and transition do not exist.
- [ ] Add the source radio controls and mode state.
- [ ] Implement transitions, source-specific context memory, fact invalidation, and control states.
- [ ] Run the focused test and verify it passes.

### Task 3: Verify And Launch The Correct Worktree

**Files:**
- Modify: desktop shortcut `KeilTool ST-Link 工作台.lnk`

**Interfaces:**
- Consumes: the completed GUI branch.
- Produces: a shortcut whose working directory is the current worktree.

- [ ] Run `pytest -q` and require the complete suite to pass.
- [ ] Update the shortcut working directory to the current worktree.
- [ ] Close stale GUI processes, launch through the shortcut command, and inspect its process command line and working code location.
- [ ] Commit the implementation and tests.
