# ST-Link Flash and RTT GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tkinter desktop GUI that uses ST-Link/OpenOCD to flash existing HEX/BIN packages and independently capture RTT logs without resetting the MCU.

**Architecture:** Extract OpenOCD command construction and flash execution from the CLI into a shared core backend. Add a long-running RTT session service, small persisted-settings and session-state units, then keep Tkinter responsible only for validation, task dispatch, and rendering queued events.

**Tech Stack:** Python 3.10+, standard-library Tkinter, `subprocess`, `socket`, `threading`, UTF-8 JSON/log files, pytest.

## Global Constraints

- The only probe/backend in this feature is ST-Link through OpenOCD over SWD.
- The GUI must add no third-party runtime dependency.
- Flash accepts existing `.hex` and `.bin` files only; it does not build or merge firmware.
- BIN defaults to `0x08000000`; HEX uses embedded addresses.
- OpenOCD target resolution must fail closed when no verified target cfg or explicit override exists.
- Flash and RTT are independent user actions but mutually exclusive probe sessions.
- Starting RTT never resets the MCU and exposes no reset option.
- RTT output is displayed live and automatically saved as UTF-8.
- All source files and persisted text use UTF-8.

---

## File Structure

- `keiltool/core/openocd_backend.py`: immutable OpenOCD/flash request and result types, validation, command construction, one-shot flash execution.
- `keiltool/core/rtt.py`: RTT command construction and lifecycle for OpenOCD, TCP reception, log writing, and graceful stop.
- `keiltool/gui/settings.py`: versioned `%APPDATA%\KeilTool\gui-settings.json` persistence.
- `keiltool/gui/state.py`: legal GUI task states and probe-session mutual exclusion.
- `keiltool/gui/project_config.py`: parse a Keil project/Target into GUI-ready device, memory, OpenOCD, and log-directory facts.
- `keiltool/gui/app.py`: Tkinter widgets, validation, background workers, queue dispatch, dialogs, and shutdown.
- `keiltool/gui/__init__.py`: exported `launch_gui()` entry point.
- `keiltool/cli.py`: add `k2c gui`; migrate `cmd_flash` to the shared flash backend.
- `tests/test_openocd_backend.py`: flash/config unit tests.
- `tests/test_gui_settings.py`: settings and corruption fallback tests.
- `tests/test_gui_state.py`: state transition tests.
- `tests/test_rtt.py`: fake OpenOCD and TCP RTT tests.
- `tests/test_gui_project_config.py`: Keil facts, override, and fail-closed tests.
- `tests/test_gui_smoke.py`: headless-safe parser/import smoke tests.
- `docs/01_KeilBridge_用户使用手册.md`: GUI startup and workflow.
- `docs/03_KeilBridge_FAQ.md`: ST-Link ownership, RTT scanning, and error guidance.

---

### Task 1: Shared OpenOCD Flash Backend

**Files:**
- Create: `keiltool/core/openocd_backend.py`
- Create: `tests/test_openocd_backend.py`
- Modify: `keiltool/cli.py`

**Interfaces:**
- Consumes: `classify_openocd_log()`, `find_openocd()`, `find_openocd_scripts()`.
- Produces: `OpenOcdConfig`, `ConnectionResult`, `FlashRequest`, `FlashResult`, `parse_address()`, `build_connection_command()`, `run_connection_check()`, `build_flash_command()`, `run_flash()`.

- [ ] **Step 1: Write failing command-construction tests**

```python
def test_build_hex_flash_command_uses_embedded_addresses(tmp_path):
    request = FlashRequest(tmp_path / "full.hex")
    command = build_flash_command(CONFIG, request)
    assert command[-2:] == ["-c", f"program {(tmp_path / 'full.hex').as_posix()} verify reset exit"]


def test_build_bin_flash_command_includes_base_address(tmp_path):
    request = FlashRequest(tmp_path / "full.bin", base_address=0x08004000)
    command = build_flash_command(CONFIG, request)
    assert command[-1].endswith("full.bin 0x08004000 verify reset exit")


def test_connection_check_does_not_reset_or_halt():
    command = build_connection_command(CONFIG)
    joined = " ".join(command).lower()
    assert "init" in joined
    assert "shutdown" in joined
    assert "reset" not in joined
    assert "halt" not in joined
```

- [ ] **Step 2: Run the focused tests and verify import failure**

Run: `python -m pytest tests/test_openocd_backend.py -q`  
Expected: FAIL because `keiltool.core.openocd_backend` does not exist.

- [ ] **Step 3: Implement request types, validation, and command construction**

```python
@dataclass(frozen=True, slots=True)
class OpenOcdConfig:
    executable: Path
    scripts_dir: Path | None
    interface_cfg: str
    target_cfg: str


@dataclass(frozen=True, slots=True)
class FlashRequest:
    firmware: Path
    base_address: int = 0x08000000


def build_flash_command(config: OpenOcdConfig, request: FlashRequest) -> list[str]:
    command = config.base_command()
    suffix = request.firmware.suffix.lower()
    if suffix == ".hex":
        program = f"program {request.firmware.resolve().as_posix()} verify reset exit"
    elif suffix == ".bin":
        program = (
            f"program {request.firmware.resolve().as_posix()} "
            f"0x{request.base_address:08X} verify reset exit"
        )
    else:
        raise ValueError("Firmware must be a .hex or .bin file.")
    return [*command, "-c", program]
```

- [ ] **Step 4: Implement read-only connection checking**

`build_connection_command()` appends `-c init -c targets -c shutdown`, without `reset`, `halt`, or memory writes. `run_connection_check()` captures stdout/stderr, succeeds only on return code 0 plus target/core evidence, and returns `ConnectionResult` with command preview and log paths.

- [ ] **Step 5: Add result parsing and a fake-runner test**

```python
def test_run_flash_requires_program_and_verify_markers(tmp_path):
    runner = FakeRunner(returncode=0, stdout="Programming Finished\nVerified OK\n", stderr="")
    result = run_flash(CONFIG, FlashRequest(tmp_path / "full.hex"), tmp_path, runner=runner)
    assert result.success is True
    assert result.stdout_log.exists()
```

Implement `FlashResult(success, returncode, command, stdout, stderr, stdout_log, stderr_log, findings)` and require return code 0 plus case-insensitive program/verify success markers.

- [ ] **Step 6: Migrate `cmd_flash` to `run_flash`**

Replace direct `subprocess.run()` and duplicated log writes in `cmd_flash` with one `OpenOcdConfig` and `FlashRequest`, preserving existing CLI defaults and printed diagnostics.

- [ ] **Step 7: Run regression tests**

Run: `python -m pytest tests/test_openocd_backend.py tests/test_flash_doctor.py -q`  
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```text
git add keiltool/core/openocd_backend.py keiltool/cli.py tests/test_openocd_backend.py
git commit -m "refactor: share OpenOCD flash backend"
```

---

### Task 2: GUI Settings, Session State, and Project Facts

**Files:**
- Create: `keiltool/gui/__init__.py`
- Create: `keiltool/gui/settings.py`
- Create: `keiltool/gui/state.py`
- Create: `keiltool/gui/project_config.py`
- Create: `tests/test_gui_settings.py`
- Create: `tests/test_gui_state.py`
- Create: `tests/test_gui_project_config.py`

**Interfaces:**
- Consumes: `parse_uvprojx()`, `resolve_openocd_target()`, `find_openocd()`, `find_openocd_scripts()`.
- Produces: `GuiSettings`, `SettingsStore`, `SessionState`, `TaskGate`, `ProjectTargetFacts`, `load_project_targets()`, `resolve_target_facts()`.

- [ ] **Step 1: Write settings round-trip and damaged-file tests**

```python
def test_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "gui-settings.json")
    settings = GuiSettings(project="D:/fw/motor.uvprojx", bin_address="0x08004000")
    store.save(settings)
    assert store.load() == settings


def test_damaged_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "gui-settings.json"
    path.write_text("{broken", encoding="utf-8")
    assert SettingsStore(path).load() == GuiSettings()
```

- [ ] **Step 2: Implement versioned atomic settings storage**

Use a `GuiSettings` dataclass with string fields for paths/addresses, integer RTT channel/port/timeout fields, `to_dict()`, and tolerant `from_dict()`. Write a sibling `.tmp` file and finish with `Path.replace()`.

- [ ] **Step 3: Write state mutual-exclusion tests**

```python
def test_rtt_blocks_flash_until_stopped():
    gate = TaskGate()
    gate.begin(SessionState.RTT)
    with pytest.raises(BusySessionError):
        gate.begin(SessionState.FLASH)
    gate.finish()
    gate.begin(SessionState.FLASH)
    assert gate.state is SessionState.FLASH
```

- [ ] **Step 4: Implement explicit session states**

```python
class SessionState(Enum):
    IDLE = "idle"
    CONNECT = "connect"
    FLASH = "flash"
    RTT_SCAN = "rtt_scan"
    RTT = "rtt"
    STOPPING = "stopping"
    FAILED = "failed"
```

`TaskGate.begin()` accepts work only from `IDLE` or `FAILED`; `finish()` returns to `IDLE`; no widget property is used as the source of truth.

- [ ] **Step 5: Write project-facts tests**

Test a fixture Keil project with two Targets, verified family mapping, explicit target override, missing RAM, and an unavailable cfg. Assert unavailable targets return `ready=False` and a non-empty reason.

- [ ] **Step 6: Implement project/Target resolution**

`ProjectTargetFacts` contains target name, Device, Flash/RAM summaries, main RAM origin/size as integers, OpenOCD executable/scripts/interface/target cfg, resolution status/reason, default log directory, and `ready`.

Explicit override accepts either an absolute cfg path or a scripts-relative `target/name.cfg`. Automatic resolution must call `resolve_openocd_target(target, scripts_dir)` and fail closed.

- [ ] **Step 7: Run focused tests and commit**

Run: `python -m pytest tests/test_gui_settings.py tests/test_gui_state.py tests/test_gui_project_config.py -q`  
Expected: all tests PASS.

```text
git add keiltool/gui tests/test_gui_settings.py tests/test_gui_state.py tests/test_gui_project_config.py
git commit -m "feat: add GUI settings and target facts"
```

---

### Task 3: OpenOCD RTT Session Service

**Files:**
- Create: `keiltool/core/rtt.py`
- Create: `tests/test_rtt.py`

**Interfaces:**
- Consumes: `OpenOcdConfig` from Task 1.
- Produces: `RttRequest`, `RttEvent`, `RttSession`, `build_rtt_command()`.

- [ ] **Step 1: Write automatic and manual RTT command tests**

```python
def test_auto_scan_uses_full_ram_range():
    request = RttRequest(scan_address=0x20000000, scan_size=0x10000, port=19021)
    command = build_rtt_command(CONFIG, request)
    joined = " ".join(command)
    assert 'rtt setup 0x20000000 0x10000 "SEGGER RTT"' in joined
    assert "reset" not in joined.lower()


def test_manual_address_uses_0x100_search_window():
    request = RttRequest(scan_address=0x20006CAC, scan_size=0x100, port=19021)
    assert "rtt setup 0x20006CAC 0x100" in " ".join(build_rtt_command(CONFIG, request))
```

- [ ] **Step 2: Implement RTT command construction without reset**

Build:

```text
openocd [-s scripts] -f interface/stlink.cfg -f <target>
  -c init
  -c rtt setup <address> <size> "SEGGER RTT"
  -c rtt start
  -c rtt server start <port> <channel>
```

Do not include `reset`, `halt`, `resume`, or `shutdown`.

- [ ] **Step 3: Write a TCP fragmentation/UTF-8 test**

Start a local fake RTT server that sends `电机启动\n`. Split the UTF-8 byte sequence across socket writes, run `RttSession`, and assert the emitted text and saved UTF-8 file both equal the original string.

- [ ] **Step 4: Implement `RttSession`**

Inject `popen_factory`, `socket_factory`, monotonic clock, and sleep function for tests. Start stdout/stderr reader threads, detect the OpenOCD control-block-found marker, retry TCP connect until timeout, decode with `codecs.getincrementaldecoder("utf-8")(errors="replace")`, and emit structured queue events.

- [ ] **Step 5: Add timeout, unexpected-exit, and stop tests**

Verify:

- no control block before timeout emits `error`;
- OpenOCD exiting before TCP connection emits `error`;
- `stop()` closes socket/log, calls `terminate()`, then `kill()` only after timeout;
- all worker threads finish.

- [ ] **Step 6: Run and commit**

Run: `python -m pytest tests/test_rtt.py -q`  
Expected: all tests PASS.

```text
git add keiltool/core/rtt.py tests/test_rtt.py
git commit -m "feat: add OpenOCD RTT session service"
```

---

### Task 4: Tkinter Workbench

**Files:**
- Create: `keiltool/gui/app.py`
- Create: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: `SettingsStore`, `TaskGate`, project facts, `run_flash()`, `RttSession`.
- Produces: `KeilToolGui`, `launch_gui()`.

- [ ] **Step 1: Write import/parser smoke tests**

```python
def test_gui_module_imports_without_creating_a_root_window():
    module = importlib.import_module("keiltool.gui.app")
    assert callable(module.launch_gui)


def test_cli_parser_accepts_gui():
    args = build_parser().parse_args(["gui"])
    assert args.command == "gui"
```

- [ ] **Step 2: Build the left configuration pane**

Use `ttk.LabelFrame`, `ttk.Entry`, `ttk.Combobox`, file/directory dialogs, a compact read-only device summary, primary “烧录并校验” and independent RTT start/stop controls. Place OpenOCD/scripts/target override/port fields in a collapsible advanced frame.

- [ ] **Step 3: Build the right output pane**

Use `ttk.Notebook` with RTT and OpenOCD tabs. Use fixed-width `tk.Text` widgets with scrollbars, status line, elapsed time, line count, clear action, and “打开日志目录”.

- [ ] **Step 4: Wire validation and state-driven control enablement**

Project/Target changes recompute facts. HEX disables BIN address. `TaskGate` is authoritative: flash/connect disable RTT and editing; RTT disables flash/connect and editing; Stop remains enabled only during RTT.

- [ ] **Step 5: Wire background work and queued events**

Use daemon worker threads only as wrappers around core services. Poll a `queue.Queue` with `root.after(50, ...)`; update Tk widgets only on the Tk thread. A failed flash displays Doctor findings and log paths. A successful flash requires `FlashResult.success`.

- [ ] **Step 6: Implement clean shutdown**

On `WM_DELETE_WINDOW`, ask before stopping an active task, stop RTT gracefully, wait with periodic `after()` checks, save settings, then destroy the root. Never leave OpenOCD running.

- [ ] **Step 7: Run smoke and full tests**

Run: `python -m pytest tests/test_gui_smoke.py -q`  
Expected: PASS without opening a window.

Run: `python -m pytest -q`  
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```text
git add keiltool/gui/app.py keiltool/gui/__init__.py tests/test_gui_smoke.py
git commit -m "feat: add ST-Link flash and RTT GUI"
```

---

### Task 5: CLI Entry, Documentation, and End-to-End Verification

**Files:**
- Modify: `keiltool/cli.py`
- Modify: `README.md`
- Modify: `docs/01_KeilBridge_用户使用手册.md`
- Modify: `docs/03_KeilBridge_FAQ.md`

**Interfaces:**
- Consumes: `launch_gui()` from Task 4.
- Produces: public `k2c gui` workflow and operator documentation.

- [ ] **Step 1: Add the CLI entry**

```python
def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import launch_gui
    launch_gui()
    return 0
```

Register a `gui` subparser with no required project argument so remembered settings can restore the previous project.

- [ ] **Step 2: Document the workflow**

Add exact startup, HEX/BIN behavior, no-reset RTT behavior, target override rules, log locations, and the fact that flash is blocked while RTT owns ST-Link.

- [ ] **Step 3: Run automated verification**

Run:

```text
python -m pytest -q
python -m keiltool.cli --help
python -m keiltool.cli gui --help
```

Expected: all tests PASS; both help commands return 0 and list `gui`.

- [ ] **Step 4: Run GUI visual smoke verification**

Start `python -m keiltool.cli gui`, verify the two-pane layout at 1280x800 and 1024x720, load a multi-Target Keil project, close and reopen, and confirm settings restoration without automatic hardware access.

- [ ] **Step 5: Run real ST-Link acceptance**

With an explicitly selected test image and connected target:

1. “检查连接” succeeds without reset.
2. HEX programming reports `Programming Finished` and `Verified OK`.
3. BIN programming uses the displayed base address and reports the same evidence.
4. RTT discovers `SEGGER RTT` without reset and records at least 60 seconds.
5. Flash controls stay disabled during RTT.
6. Stop and window close leave no `openocd.exe`.

Record exact firmware paths, file timestamps/sizes, probe/core evidence, OpenOCD version, verify lines, RTT log path, and process-cleanup result.

- [ ] **Step 6: Commit**

```text
git add keiltool/cli.py README.md docs/01_KeilBridge_用户使用手册.md docs/03_KeilBridge_FAQ.md
git commit -m "docs: add GUI flash and RTT workflow"
```

- [ ] **Step 7: Final branch verification**

Run:

```text
git status --short
python -m pytest -q
git log --oneline --decorate -8
```

Expected: clean worktree, all tests PASS, feature commits visible on `codex/gui-stlink-openocd-rtt`.
