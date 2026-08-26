# RTT / VOFA Automatic Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start RTT text logging and VOFA curves without asking users to enter RTT channel numbers, OpenOCD TCP ports, VOFA listener ports, or a fixed float count.

**Architecture:** Keep KeilTool transport-generic. A short initial OpenOCD RTT session reads the MCU-provided RTT channel directory. The tool selects Up0 as text when available, offers non-text Up channels by their firmware-provided ASCII names, pairs a Down channel automatically, and assigns unique local OpenOCD ports. The MCU remains the owner of channel names and curve framing; KeilTool remains a raw transport bridge.

**Tech Stack:** Python 3.13, Tkinter, OpenOCD RTT/TCL, pytest.

## Global Constraints

- Do not hard-code BilboPro, IMU, `Scope`, `LoopScope`, command bytes, or a float count.
- Preserve manual advanced settings as an expert override only.
- Never start a second OpenOCD/ST-Link session after discovery; extend the same session through its TCL endpoint.
- Keep text and curve byte streams isolated by their RTT Up channels.

### Task 1: Parse the RTT directory

**Files:**
- Modify: `keiltool/core/rtt.py`
- Test: `tests/test_rtt.py`

- [ ] Add a failing fixture containing OpenOCD `Up-channels:` and `Down-channels:` output.
- [ ] Parse each `{direction, index, ASCII name, size, flags}` record into an immutable `RttChannelInfo`.
- [ ] Verify fragmented stdout lines, missing Down channels, and non-ASCII/unnamed records.
- [ ] Commit the parser and focused tests.

### Task 2: Derive a generic transport plan

**Files:**
- Create: `keiltool/core/rtt_auto_config.py`
- Test: `tests/test_rtt_auto_config.py`

- [ ] Write failing tests for: Up0 text + one curve + matching Down; multiple non-text Up channels; no curve candidate; and occupied default ports.
- [ ] Implement `choose_rtt_auto_config(directory, reserved_ports)` returning a text channel, selectable curve candidates, Down channel, and distinct ports beginning at 19021.
- [ ] Select the first non-text Up only as the initial default; expose all candidates by their firmware names.
- [ ] Keep `expected_float_count=None` by default.
- [ ] Commit the planner and tests.

### Task 3: Use one OpenOCD session for discovery and streaming

**Files:**
- Modify: `keiltool/core/rtt.py`
- Test: `tests/test_rtt.py`

- [ ] Write a failing fake-TCL test proving channel servers start only after the directory is parsed.
- [ ] Add an internal Tcl client that sends `rtt server start <port> <channel>` to the existing OpenOCD Tcl endpoint.
- [ ] Start text, selected curve, and Down servers exactly once with assigned ports; retain existing stop/cleanup ownership.
- [ ] Verify OpenOCD process count remains one and every socket is closed on stop.
- [ ] Commit the session change and tests.

### Task 4: Replace manual-first GUI flow

**Files:**
- Modify: `keiltool/gui/app.py`
- Modify: `keiltool/gui/widgets.py`
- Modify: `keiltool/gui/settings.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_gui_settings.py`

- [ ] Write a failing GUI test: a legacy invalid configuration launches auto-discovery rather than showing a port-topology error.
- [ ] Make “VOFA 曲线” use automatic discovery by default and display a readable selected channel name after discovery.
- [ ] Retain the advanced dialog only for explicit “手动覆盖” mode; fixed N is optional and defaults to zero/no validation.
- [ ] Persist only valid explicit overrides; migrate invalid old settings to automatic mode.
- [ ] Verify VOFA launch receives the automatically assigned listener address.
- [ ] Commit GUI behavior and tests.

### Task 5: Verify and hand off

- [ ] Run `py -m pytest -q`.
- [ ] Run `git diff --check`.
- [ ] Start no hardware session during automated tests.
- [ ] Document the one-click operation: select project, click “VOFA 曲线”, choose a discovered curve only if more than one is present.
