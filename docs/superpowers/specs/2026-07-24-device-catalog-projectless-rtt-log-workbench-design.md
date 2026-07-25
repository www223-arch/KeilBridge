# Device Catalog, Projectless RTT, and Log Workbench Design

Date: 2026-07-24
Status: Approved direction

## 1. Goal

Improve the existing ST-Link/OpenOCD workbench without adding a separate
"RTT-only" mode or page:

1. Make a Keil project optional for GUI connection, flash, and RTT operations.
2. Let users select a trusted device from an embedded catalog.
3. Build the embedded catalog from official CMSIS Device Family Pack metadata.
4. Let users import devices that are not included in the embedded catalog.
5. Preserve the rule that KeilTool never guesses an OpenOCD target.
6. Apply the approved light-control-surface plus dark-log-console visual style.
7. Make RTT and OpenOCD output easy to select and copy.
8. Store every hardware operation in a separate, clearly named log directory.

The CLI build/configure workflows still require a Keil project. This design
changes only the GUI hardware workbench and shared device-catalog services.

## 2. Trusted Device Facts

### 2.1 Official catalog snapshot

KeilTool will include a normalized UTF-8 JSON catalog generated from official
CMSIS-Pack/PDSC files. The generator records the source vendor, pack name, pack
version, source URL, and source digest.

The initial source manifest will cover the official GigaDevice and
STMicroelectronics DFP descriptors needed by the families already represented
by KeilTool. Additional official DFP descriptors can be added without changing
the runtime schema.

The generated catalog contains device facts such as:

- vendor and exact device name;
- family and sub-family;
- processor core, FPU, and endianness;
- inherited RAM and Flash regions;
- default Flash algorithm metadata;
- CMSIS-Pack source and version.

KeilTool bundles only normalized metadata required by the tool. It does not
execute source-pack content at runtime.

### 2.2 OpenOCD compatibility map

CMSIS-Pack does not define OpenOCD target cfg files. OpenOCD support therefore
remains a separate, explicit compatibility map:

- each mapping has a device or family key;
- each mapping names an exact `target/*.cfg`;
- each mapping records its origin and verification status;
- the selected cfg must exist in the current OpenOCD scripts directory.

A catalog device without an OpenOCD mapping remains visible, but connection,
flash, and RTT actions stay disabled. KeilTool must not derive a cfg from a
similar-looking device name.

### 2.3 User catalog

User-imported device records are normalized and stored under:

```text
%APPDATA%\KeilTool\devices\
```

Supported import formats:

- `.pdsc`: parse one official CMSIS-Pack descriptor;
- `.pack`: inspect the ZIP-compatible package and parse its PDSC descriptor;
- `.json`: parse the documented KeilTool custom-device schema.

Custom JSON may include an explicit OpenOCD target. It is marked
`user_provided`, must reference an existing cfg at operation time, and is never
represented as an officially verified mapping.

Imports are atomic. Invalid files, incomplete memory definitions, duplicate
keys, unsafe archive paths, oversized archive entries, and schema conflicts are
reported without partially changing the user catalog. A user record can
explicitly override the same vendor/device key, but the source badge must remain
visible.

## 3. Runtime Catalog Resolution

Catalog layers merge in this order:

1. embedded official snapshot;
2. globally imported official PDSC/PACK records;
3. explicit user JSON overrides.

Records use a normalized `(vendor, device)` key. Resolution returns both device
facts and provenance; consumers do not inspect raw catalog files.

When a Keil project is selected:

- the Keil Device field selects the matching catalog record automatically;
- project CPU and memory facts remain available as independent evidence;
- a mismatch between Keil facts and catalog facts blocks hardware actions and
  reports both values;
- the project device is authoritative until the project is cleared.

When no Keil project is selected:

- the user selects a device directly from the existing Device row;
- Target displays `No Keil project (device catalog)`;
- connection, existing HEX/BIN flash, and RTT use the selected catalog facts;
- build and workspace-generation behavior is unchanged.

## 4. Existing GUI Changes

No new mode, page, or navigation is introduced.

The current read-only Device row becomes a searchable combobox. The same row
adds an `Import device` command. Each selection shows a source label such as:

```text
Official CMSIS-Pack 2.5.0
Imported CMSIS-Pack 1.2.0
User configuration
```

The existing workbench remains split into controls on the left and logs on the
right. The approved visual direction is:

- pale blue-gray application background;
- white/light control surfaces with teal section headers and primary actions;
- dark blue-green RTT/OpenOCD console;
- explicit running/success/warning/error states;
- restrained EasyLogger level colors on the dark console;
- no layout replacement or new landing screen.

Both RTT and OpenOCD text areas support:

- normal mouse selection;
- `Ctrl+C`;
- a right-click menu with `Copy`, `Select all`, and `Copy all`;
- toolbar commands for `Copy selected` and `Copy all`.

Copying uses visible text. RTT level filtering still affects only GUI display;
the complete RTT log remains on disk.

## 5. Hardware Readiness

The GUI computes hardware readiness from either a verified project target or a
selected catalog device.

RTT requires:

- an exact selected device;
- a resolvable OpenOCD target cfg;
- at least one valid RAM scan region;
- a valid probe/OpenOCD configuration;
- a writable log root.

Existing HEX/BIN flash additionally requires a firmware path and, for BIN, a
base address. Project import is not required.

If multiple RAM regions are marked writable, RTT scans them in declared order.
The UI shows the exact region currently being used. A manually entered RTT
control-block address retains its current behavior and takes precedence over
automatic RAM scanning.

## 6. Log Root and Session Directories

The existing log-directory field becomes a remembered log root. Resolution
order is:

1. the directory explicitly selected by the user;
2. `<keil-project-root>\.keilbridge\logs` when a project is selected;
3. `%USERPROFILE%\Documents\KeilTool Logs` without a project.

Every connection check, flash operation, and RTT capture creates a separate
directory:

```text
YYYYMMDD-HHMMSS-fff_<device>_<task>
```

Examples:

```text
20260724-211830-125_GD32F303VE_RTT
20260724-212104-442_GD32F303VE_FLASH
20260724-212330-008_GD32F303VE_CONNECT
```

Unsafe filename characters are replaced deterministically.

Each directory contains `session.json` with machine-readable metadata. Every
human-readable log starts with a UTF-8 header containing:

- local date and time including timezone;
- task type;
- exact device and catalog source;
- project and Target when present;
- probe and OpenOCD executable;
- interface cfg and target cfg;
- command line;
- final outcome when the operation closes.

RTT session files:

```text
session.json
rtt.log
openocd.stdout.log
openocd.stderr.log
```

Connection and flash files use task-specific names:

```text
connect.stdout.log
connect.stderr.log
flash.stdout.log
flash.stderr.log
```

Creating the session directory and initial metadata must succeed before a
hardware process starts. Log failure therefore cannot leave an untracked
OpenOCD operation running.

## 7. Error Handling

- No selected project and no selected device: hardware actions remain disabled.
- Catalog entry has no OpenOCD mapping: show the exact missing fact.
- Candidate target cfg is absent from the selected scripts directory: block the
  operation.
- Project/catalog memory mismatch: block and report both definitions.
- Imported PDSC/PACK has no usable devices: reject it with a diagnostic.
- Imported custom JSON omits required RAM or target information: import the
  informational record only, but keep hardware actions disabled.
- Session directory or metadata cannot be written: abort before opening the
  probe.
- Copy selected with no selection: leave the clipboard unchanged and show a
  short status message.
- A malformed user catalog file must not prevent the GUI from loading embedded
  devices; report the file and continue with valid layers.

## 8. Testing

Tests cover:

1. PDSC family/sub-family/device/variant inheritance.
2. Processor, FPU, RAM, Flash, and algorithm normalization.
3. Safe `.pack` inspection without arbitrary extraction.
4. Custom JSON validation and explicit target handling.
5. Embedded/imported/user catalog precedence and provenance.
6. Exact-name normalization without fuzzy chip substitution.
7. OpenOCD cfg existence verification.
8. Keil project/catalog agreement and mismatch blocking.
9. Projectless connection, flash, and RTT readiness.
10. Device selection and settings persistence.
11. Log-root precedence and remembered custom directory.
12. Per-operation session directory naming and sanitization.
13. UTF-8 headers, session metadata, and outcome finalization.
14. RTT complete-log persistence despite GUI filtering.
15. Mouse/keyboard/context-menu copy behavior.
16. GUI creation and close smoke tests at 1280x800 and 1024x720.
17. Existing CLI, flash, OpenOCD cleanup, and RTT lifecycle regression tests.

## 9. Acceptance Criteria

- A user can select a supported device and capture RTT without importing a Keil
  project.
- The GUI never invents a chip, RAM range, or OpenOCD target.
- Embedded device facts are traceable to an official CMSIS-Pack version.
- Unknown devices can be imported without modifying the installation.
- Unsupported OpenOCD devices remain visibly unsupported and cannot start a
  hardware task.
- The approved light-control/dark-console visual style is applied.
- RTT and OpenOCD output can be copied.
- Every operation produces a self-describing, independently named log folder.
- Complete UTF-8 RTT logs remain independent from GUI filtering and clearing.

## 10. Authoritative References

- Keil Pack Index: <https://www.keil.com/pack/index.pidx>
- Open-CMSIS-Pack PDSC format:
  <https://open-cmsis-pack.github.io/Open-CMSIS-Pack-Spec/main/html/packFormat.html>
- Open-CMSIS-Pack device metadata and inheritance:
  <https://open-cmsis-pack.github.io/Open-CMSIS-Pack-Spec/main/html/pdsc_devices_pg.html>
- OpenOCD configuration and target scripts:
  <https://openocd.org/doc/html/Config-File-Guidelines.html>
