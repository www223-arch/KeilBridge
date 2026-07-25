# ST-Link Flash/RTT GUI Final Fix Report

Base reviewed: `0a686cc17a868b6f43e7eb8314f0cac240a7e80c`

Date: 2026-07-24

## Status

All Important and Minor findings in `final-review-findings.md` were implemented with regression coverage. No real hardware operation was performed.

## Finding Implementations

### 1. Preserve the existing `flash` CLI contract

- Restored optional `--elf` and the generated ELF default under `.keilbridge/build/gcc-debug`.
- Restored the generated per-probe OpenOCD cfg path and legacy probe selection for ELF/AXF.
- Kept `--firmware` and `--base-address` as additive HEX/BIN options.
- Extended the shared backend to accept ELF/AXF without weakening the GUI's ST-Link-only request validation.
- Added parser and execution regressions for the pre-branch command forms.

Files:

- `keiltool/cli.py`
- `keiltool/core/openocd_backend.py`
- `tests/test_cli_flash_compat.py`
- `tests/test_openocd_backend.py`

### 2. Bound and cancel one-shot OpenOCD operations

- Added `OpenOcdOperation`, using `Popen.communicate()` with bounded polling.
- Cancellation and timeout terminate first, wait for a bounded interval, then kill only after that interval.
- Launch failure, timeout, and cancellation return `ConnectionResult`/`FlashResult` with explicit outcomes, command data, Doctor findings, and UTF-8 evidence logs.
- Added `OneShotLifecycleController`; the GUI owns the active handle until its worker result is consumed.
- Window close cancels the active handle and waits through existing event polling before destroying Tk.

Files:

- `keiltool/core/openocd_backend.py`
- `keiltool/gui/workbench_controller.py`
- `keiltool/gui/app.py`
- `tests/test_openocd_backend.py`
- `tests/test_gui_workbench_controller.py`

### 3. Preserve the final RTT data chunk

- Split socket, log, and worker locks so a blocked log writer cannot block bounded cleanup.
- Stop now closes the socket and terminates/reaps OpenOCD before joining workers.
- The RTT log is closed only after every receive/stream worker quiesces.
- An unjoined worker produces `incomplete` and leaves the log attached for cleanup retry.
- Data events are emitted only after the same text has been written and flushed to the UTF-8 log.
- The incremental decoder is finalized during socket cleanup.
- Replaced the prior late-write-drop expectation with an overlap/retry regression.

Files:

- `keiltool/core/rtt.py`
- `tests/test_rtt.py`

### 4. Bound Tk event polling

- Added `BoundedEventPoller` with a 200-event and 10 ms callback budget.
- UI and RTT queues are drained fairly within the batch.
- Adjacent RTT `data` events are coalesced.
- Backlog schedules `after(0)` continuation; an empty batch returns to the normal 50 ms interval.
- Added a 5,000-event producer test showing an unrelated queued Tk callback runs before continuation.

Files:

- `keiltool/gui/workbench_controller.py`
- `keiltool/gui/app.py`
- `tests/test_gui_workbench_controller.py`
- `tests/test_gui_smoke.py`

### 5. Settings fallback diagnostics

- Added typed `SettingsLoadResult` and `SettingsDiagnostic`.
- A missing file returns defaults without a diagnostic.
- Corrupt UTF-8/JSON, unreadable files, and incompatible versions return distinct diagnostics.
- The GUI renders the diagnostic in OpenOCD output only after output widgets are built.
- Kept `SettingsStore.load()` compatibility by delegating to `load_result()`.

Files:

- `keiltool/gui/settings.py`
- `keiltool/gui/app.py`
- `tests/test_gui_settings.py`

### 6. Evidence filenames

- Connection and flash stems now include a sanitized Target name.
- The existing `%f` microsecond timestamp remains in both stdout and stderr names.

Files:

- `keiltool/core/openocd_backend.py`
- `tests/test_openocd_backend.py`

### 7. Readiness and launch diagnostics

- Hardware readiness now checks the OpenOCD executable, scripts directory, ST-Link interface cfg, and resolved target cfg.
- `ProjectTargetFacts.ready` remains false until every path and the verified target resolution are valid.
- Reasons are appended to the existing target-resolution diagnostic instead of replacing its status.
- One-shot launch failures are structured results with command preview and deterministic UTF-8 log paths.

Files:

- `keiltool/gui/project_config.py`
- `keiltool/core/openocd_backend.py`
- `tests/test_gui_project_config.py`
- `tests/test_openocd_backend.py`

## RED/GREEN Evidence

### Cycle 1: CLI compatibility and one-shot lifecycle

RED command:

```text
python -m pytest tests/test_cli_flash_compat.py tests/test_openocd_backend.py tests/test_gui_workbench_controller.py -q
```

RED output:

```text
FFF..F..........FFF...........F                                          [100%]
FAILED tests/test_cli_flash_compat.py::test_flash_parser_preserves_legacy_generated_elf_and_explicit_elf_contract
FAILED tests/test_cli_flash_compat.py::test_flash_parser_keeps_hex_and_bin_support_additive
FAILED tests/test_cli_flash_compat.py::test_cmd_flash_without_firmware_uses_generated_elf_and_probe_config
FAILED tests/test_openocd_backend.py::test_build_elf_flash_command_preserves_legacy_program_contract
FAILED tests/test_openocd_backend.py::test_cancellable_operation_terminates_then_kills_and_returns_utf8_evidence
FAILED tests/test_openocd_backend.py::test_one_shot_timeout_returns_structured_failure_and_logs
FAILED tests/test_openocd_backend.py::test_launch_failure_returns_structured_result_with_command_and_logs
FAILED tests/test_gui_workbench_controller.py::test_window_close_cancels_active_one_shot_and_waits_for_completion
8 failed, 23 passed in 0.75s
```

GREEN command:

```text
python -m pytest tests/test_cli_flash_compat.py tests/test_openocd_backend.py tests/test_gui_workbench_controller.py -q
```

GREEN output:

```text
...............................                                          [100%]
31 passed in 0.32s
```

### Cycle 2: RTT final chunk and bounded Tk polling

RED command:

```text
python -m pytest tests/test_rtt.py::test_stop_retains_log_until_final_data_writer_quiesces_and_retry_closes_it tests/test_gui_workbench_controller.py::test_bounded_event_poller_aggregates_adjacent_rtt_data_and_reports_backlog tests/test_gui_smoke.py::test_high_rate_rtt_poll_yields_to_unrelated_tk_callback -q
```

RED output:

```text
FFF                                                                      [100%]
FAILED tests/test_rtt.py::test_stop_retains_log_until_final_data_writer_quiesces_and_retry_closes_it
FAILED tests/test_gui_workbench_controller.py::test_bounded_event_poller_aggregates_adjacent_rtt_data_and_reports_backlog
FAILED tests/test_gui_smoke.py::test_high_rate_rtt_poll_yields_to_unrelated_tk_callback
3 failed in 1.18s
```

GREEN command:

```text
python -m pytest tests/test_rtt.py tests/test_gui_workbench_controller.py tests/test_gui_smoke.py -q
```

GREEN output:

```text
..................................................                       [100%]
50 passed in 0.71s
```

### Cycle 3: settings, evidence names, and readiness

RED command:

```text
python -m pytest tests/test_gui_settings.py tests/test_openocd_backend.py::test_connection_and_flash_evidence_stems_include_sanitized_target_and_microseconds tests/test_gui_project_config.py::test_hardware_readiness_validates_executable_scripts_interface_and_target_cfg -q
```

RED output:

```text
....FFFFFFF                                                              [100%]
FAILED tests/test_gui_settings.py::test_missing_settings_is_normal_and_has_no_diagnostic
FAILED tests/test_gui_settings.py::test_corrupt_settings_returns_a_diagnostic
FAILED tests/test_gui_settings.py::test_unreadable_settings_returns_a_diagnostic
FAILED tests/test_gui_settings.py::test_incompatible_settings_returns_a_diagnostic
FAILED tests/test_gui_settings.py::test_settings_diagnostic_renders_in_openocd_output
FAILED tests/test_openocd_backend.py::test_connection_and_flash_evidence_stems_include_sanitized_target_and_microseconds
FAILED tests/test_gui_project_config.py::test_hardware_readiness_validates_executable_scripts_interface_and_target_cfg
7 failed, 4 passed in 0.67s
```

GREEN command:

```text
python -m pytest tests/test_gui_settings.py tests/test_openocd_backend.py::test_connection_and_flash_evidence_stems_include_sanitized_target_and_microseconds tests/test_gui_project_config.py::test_hardware_readiness_validates_executable_scripts_interface_and_target_cfg -q
```

GREEN output:

```text
...........                                                              [100%]
11 passed in 0.34s
```

## Focused and Full Verification

Focused command:

```text
python -m pytest tests/test_cli_flash_compat.py tests/test_openocd_backend.py tests/test_rtt.py tests/test_gui_settings.py tests/test_gui_project_config.py tests/test_gui_workbench_controller.py tests/test_gui_smoke.py -q
```

Focused output:

```text
........................................................................ [ 82%]
...............                                                          [100%]
87 passed in 1.64s
```

Full command:

```text
python -m pytest -q
```

Full output:

```text
........................................................................ [ 63%]
.........................................                                [100%]
113 passed in 2.04s
```

Additional checks:

```text
git diff --check
python -m compileall -q keiltool
python -m keiltool.cli flash --help
```

All returned exit code 0. Flash help lists optional `--elf` and `--firmware`, with no firmware requirement.

## Self-Review

- Compared the CLI path against `git show 578bb27:keiltool/cli.py`; generated ELF default, explicit ELF, generated probe cfg, and probe selection are restored.
- GUI HEX/BIN validation still accepts only `.hex`/`.bin`; legacy ELF/AXF support exists only in the shared backend/CLI route.
- Automatic target resolution still fails closed; readiness now adds path validation.
- RTT command construction remains free of `reset`, `halt`, `resume`, and `shutdown`.
- Flash Tcl word quoting is unchanged.
- TaskGate, RTT lifecycle ownership, and stale snapshot guarantees remain intact.
- No dependency was added and no real flash command was executed.
- `git diff --check` and Python compilation are clean.

## Concerns

- Real ST-Link/OpenOCD behavior was intentionally not exercised. Process termination, timeout, log ordering, and Tk scheduling are verified with fakes and local threads.
- No interactive GUI visual smoke was run during this fix wave; the headless GUI/controller suite covers state and polling behavior.
