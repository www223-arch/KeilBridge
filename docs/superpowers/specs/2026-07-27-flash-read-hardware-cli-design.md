# Flash Read And Hardware CLI Design

## Scope

Add complete user-Flash readback to the GUI and expose the existing ST-Link/
OpenOCD hardware workflows through a stable CLI. Plotting and J-Scope decoding
are explicitly out of scope.

The supported operations are:

- read-only target connection check;
- write and verify HEX/BIN firmware;
- read the complete resolved user-Flash region into a binary image;
- capture SEGGER RTT without reset.

## Command Surface

The existing `k2c flash` command remains the write command for backward
compatibility. The new commands are:

```text
k2c connect [target selection] [tool options] [--json]
k2c flash-read [target selection] [tool options] [--output FILE] [--json]
k2c rtt [target selection] [tool options] [--format text|jsonl|raw]
```

Every hardware command accepts exactly one target source:

```text
--project APP.uvprojx [--target Debug]
--device GD32F303VE [--vendor GigaDevice]
```

Common tool options are `--openocd`, `--scripts`, `--target-cfg`, and
`--logs-dir`. Device selection is exact. An ambiguous device name requires
`--vendor`; an unresolved OpenOCD target fails closed unless `--target-cfg`
points to a verified cfg.

`k2c flash` is extended to accept the same target selection and tool options.
Its existing project-based invocation remains valid.

## Flash Readback

The resolved hardware facts expose a structured primary user-Flash origin and
size. The read operation covers that entire range. It does not include option
bytes, OTP, system ROM, or external memories unless they are explicitly the
resolved primary Flash region.

OpenOCD records the target's initial run state, halts it for a consistent
read, executes `dump_image`, and resumes it only if it was running before the
operation. It never resets the target. Failure to determine Flash origin or
size disables the GUI action and makes the CLI fail before opening the probe.

The result is accepted only when OpenOCD exits successfully, the output file
exists, and its exact size equals the requested Flash size. The result reports
origin, requested size, actual size, SHA-256, OpenOCD command, stdout/stderr
logs, and session metadata. A partial file is retained as evidence but the
operation returns failure.

The GUI adds a separate `读取完整 Flash` command. It asks for the destination
file, runs through the existing exclusive hardware task gate, and never
depends on the firmware input field.

## External Firmware Reload

The GUI fingerprints the selected HEX/BIN file. When the application regains
focus after the file changed externally, it asks whether to reload and accept
the new firmware version. Accepting refreshes the fingerprint and keeps flash
write available. Declining marks the firmware stale and disables flash write;
the application cannot claim to preserve old bytes because firmware is read
from the selected path at operation time. Reselecting the file or accepting a
later prompt clears the stale state.

Flash write performs the same fingerprint check immediately before opening
the probe, closing the race between the focus notification and the destructive
operation. A missing or unreadable firmware file is stale and cannot be
flashed. The prompt reports the old and new size, modification time, and
SHA-256 where available.

## RTT CLI

`k2c rtt` reuses `RttSession` and does not reset, halt, or resume the target.
Automatic scanning uses the resolved RAM region; `--address` selects a manual
control-block address. Other options are `--channel`, `--port`, `--timeout`,
`--duration`, and `--output`.

Formats:

- `text`: decoded RTT/EasyLogger text to stdout;
- `jsonl`: one versioned event per line for AI and third-party consumers;
- `raw`: original RTT channel bytes, written to stdout or `--output`.

OpenOCD diagnostics go to stderr. Session logs always retain decoded RTT,
OpenOCD stdout/stderr, metadata, and raw bytes. Ctrl+C requests bounded cleanup
and cannot leave an owned OpenOCD process silently running.

## Machine Contract

Text commands return `0` on proven success, `1` on hardware/operation failure,
and argparse uses `2` for invalid invocation. `--json` emits one JSON object to
stdout; all human diagnostics move to stderr.

JSONL RTT events use schema `keiltool.rtt.v1` and include `event`, timestamp,
device, channel, and event-specific fields. A final `stopped` event records the
cleanup outcome. Ctrl+C returns `130` after cleanup.

## Architecture

A core hardware-target resolver owns project/catalog selection and produces
one verified context consumed by GUI and CLI. OpenOCD connection, flash write,
flash read, and RTT remain core operations. CLI handlers only translate
arguments, stream events, and render results; they do not build OpenOCD command
strings independently.

## Verification

Tests cover target-source exclusivity, backward-compatible `flash` parsing,
Flash range resolution, read command quoting, halt/resume behavior, exact-size
and SHA-256 validation, cancellation cleanup, GUI readiness, CLI text/JSON,
RTT text/JSONL/raw streaming, Ctrl+C cleanup, and process-orphan prevention.
Firmware tests cover focus-return change detection, accept/decline behavior,
missing files, and the final pre-flash race check.

Hardware smoke testing uses a read-only connection first. Flash readback is
then compared by byte count and SHA-256; no write or reset is performed by the
read test.
