# Device Catalog, Projectless RTT, and Log Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the existing GUI select an officially sourced device and run connection, flash, or RTT without a Keil project, while adding user imports, per-operation log folders, output copying, and the approved light-control/dark-console theme.

**Architecture:** Add a shared normalized catalog layer that parses CMSIS-Pack metadata and merges embedded and user records with explicit provenance. Feed either Keil target facts or a manually selected catalog record into the existing GUI hardware-fact model, then centralize session-directory creation so all OpenOCD and RTT operations receive self-describing paths before touching hardware.

**Tech Stack:** Python 3.10+, standard-library `json`, `zipfile`, `xml.etree.ElementTree`, `tkinter/ttk`, pytest, OpenOCD, CMSIS-Pack/PDSC XML.

## Global Constraints

- Do not add a separate RTT-only mode, page, or navigation path.
- A Keil project remains required by CLI build/configure workflows, but is optional for GUI hardware operations.
- Never infer an OpenOCD cfg from a similar-looking device name.
- Every selected target cfg must exist in the active OpenOCD scripts directory.
- Runtime code must remain dependency-free outside the Python standard library.
- All authored text and metadata files use UTF-8.
- GUI filtering and clearing never modify the complete RTT file.
- Each hardware action creates `YYYYMMDD-HHMMSS-fff_<device>_<task>`.
- Preserve the existing no-reset RTT behavior and probe-ownership cleanup rules.

---

### Task 1: Normalized Device Catalog and CMSIS-Pack Parser

**Files:**
- Create: `keiltool/core/device_catalog.py`
- Create: `keiltool/core/cmsis_pack.py`
- Create: `keiltool/data/device_catalog/catalog.json`
- Create: `tools/build_device_catalog.py`
- Create: `tools/device_catalog_sources.json`
- Modify: `keiltool/core/device_database.py`
- Test: `tests/test_cmsis_pack.py`
- Test: `tests/test_device_catalog.py`

**Interfaces:**
- Produces: `CatalogDevice`, `CatalogMemory`, `CatalogSource`, `DeviceCatalog`.
- Produces: `parse_pdsc(path: Path) -> tuple[CatalogDevice, ...]`.
- Produces: `load_embedded_catalog() -> DeviceCatalog`.
- Preserves: `lookup_device(device: str) -> DeviceInfo`.

- [ ] **Step 1: Write failing PDSC inheritance tests**

Create a temporary PDSC containing family processor metadata, sub-family RAM,
device Flash, and one variant. Assert inherited facts:

```python
devices = parse_pdsc(pdsc_path)
device = next(item for item in devices if item.device == "GD32F303VE")
assert device.vendor == "GigaDevice"
assert device.family == "GD32F30x"
assert device.core == "Cortex-M4"
assert [(m.name, m.start, m.size) for m in device.memory] == [
    ("SRAM", 0x20000000, 0x10000),
    ("Flash", 0x08000000, 0x40000),
]
assert device.source.pack_version == "2.5.0"
```

- [ ] **Step 2: Run parser tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_cmsis_pack.py -q
```

Expected: import failure for `keiltool.core.cmsis_pack`.

- [ ] **Step 3: Implement immutable catalog records and PDSC parsing**

Define:

```python
@dataclass(frozen=True, slots=True)
class CatalogMemory:
    name: str
    start: int
    size: int
    access: str
    default: bool
    startup: bool

@dataclass(frozen=True, slots=True)
class CatalogSource:
    kind: str
    vendor: str
    pack: str
    pack_version: str
    location: str
    digest: str

@dataclass(frozen=True, slots=True)
class CatalogDevice:
    vendor: str
    device: str
    family: str
    sub_family: str
    core: str
    fpu: str
    endian: str
    memory: tuple[CatalogMemory, ...]
    flash_algorithms: tuple[str, ...]
    openocd_target: str
    openocd_status: str
    source: CatalogSource
```

Implement hierarchical inheritance by copying family properties into
sub-family, device, and variant nodes before applying child overrides. Accept
hexadecimal and decimal CMSIS numeric attributes with `int(value, 0)`.

- [ ] **Step 4: Add catalog merge and exact lookup tests**

Assert case-normalized exact lookup, no fuzzy substitution, provenance, and
explicit user precedence:

```python
catalog = DeviceCatalog((embedded,), (imported,), (user_override,))
assert catalog.lookup("GigaDevice", "gd32f303ve") == user_override
assert catalog.lookup_any_vendor("GD32F303V") is None
```

- [ ] **Step 5: Implement catalog loading and compatibility adapter**

Load `keiltool/data/device_catalog/catalog.json`, normalize keys as
`VENDOR::DEVICE`, and adapt the selected record to the existing `DeviceInfo`.
Keep `device_database.lookup_device()` as a compatibility wrapper so CLI code
does not change in this task.

- [ ] **Step 6: Build the official snapshot**

`tools/device_catalog_sources.json` lists official PDSC source paths/URLs and
their expected SHA-256 values. `tools/build_device_catalog.py` parses every
source, applies only explicit existing OpenOCD compatibility mappings, sorts
records by vendor/device, and writes deterministic UTF-8 JSON.

Use the official GigaDevice and STMicroelectronics PDSC descriptors available
from the Keil Pack index. Do not include `.flm`, source code, or pack binaries in
the repository.

- [ ] **Step 7: Run tests and deterministic generation check**

Run:

```powershell
python -m pytest tests/test_cmsis_pack.py tests/test_device_catalog.py tests/test_keil_parser.py -q
python tools/build_device_catalog.py --check
```

Expected: all pass and generated catalog matches the committed snapshot.

- [ ] **Step 8: Commit**

```powershell
git add keiltool/core/device_catalog.py keiltool/core/cmsis_pack.py keiltool/core/device_database.py keiltool/data/device_catalog/catalog.json tools/build_device_catalog.py tools/device_catalog_sources.json tests/test_cmsis_pack.py tests/test_device_catalog.py
git commit -m "feat: add official CMSIS device catalog"
```

### Task 2: Safe User Device Imports

**Files:**
- Create: `keiltool/core/device_import.py`
- Modify: `keiltool/core/device_catalog.py`
- Modify: `keiltool/gui/settings.py`
- Test: `tests/test_device_import.py`
- Test: `tests/test_gui_settings.py`

**Interfaces:**
- Consumes: `parse_pdsc`, `CatalogDevice`, `DeviceCatalog`.
- Produces: `DeviceImportResult`.
- Produces: `import_device_file(source: Path, destination: Path) -> DeviceImportResult`.
- Produces: `load_user_catalog(directory: Path) -> tuple[CatalogDevice, ...]`.

- [ ] **Step 1: Write failing PDSC, PACK, and JSON import tests**

Tests create:

- a direct `.pdsc`;
- a `.pack` ZIP containing exactly one root-level PDSC;
- a valid custom JSON record with explicit `target/stm32f3x.cfg`;
- a ZIP containing `../escape.pdsc`;
- malformed JSON and duplicate device keys.

Assert valid imports write one normalized JSON atomically and invalid imports
leave the destination unchanged.

- [ ] **Step 2: Run import tests and confirm RED**

```powershell
python -m pytest tests/test_device_import.py -q
```

Expected: import failure for `keiltool.core.device_import`.

- [ ] **Step 3: Implement bounded PACK inspection**

Use `zipfile.ZipFile` without extracting files. Reject:

- absolute or parent-traversal names;
- more than 2,000 entries;
- PDSC entries larger than 8 MiB;
- archives with zero or multiple package descriptors.

Parse PDSC bytes with `ElementTree.fromstring`, normalize records, then write a
temporary JSON sibling and finish with `Path.replace()`.

- [ ] **Step 4: Implement custom JSON validation**

Require:

```json
{
  "schema_version": 1,
  "vendor": "GigaDevice",
  "device": "GD32F303VE",
  "family": "GD32F30x",
  "core": "Cortex-M4",
  "memory": [
    {"name": "Flash", "start": "0x08000000", "size": "0x40000", "access": "rx"},
    {"name": "SRAM", "start": "0x20000000", "size": "0x10000", "access": "rwx"}
  ],
  "openocd_target": "target/stm32f3x.cfg"
}
```

Missing target information creates an informational record with disabled
hardware readiness. Invalid or overlapping memory regions reject the import.

- [ ] **Step 5: Add settings paths and diagnostics**

Add a helper for `%APPDATA%\KeilTool\devices` and preserve the current settings
version compatibility. Catalog-load diagnostics identify malformed files but
return all valid embedded/user records.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_device_import.py tests/test_device_catalog.py tests/test_gui_settings.py -q
git add keiltool/core/device_import.py keiltool/core/device_catalog.py keiltool/gui/settings.py tests/test_device_import.py tests/test_gui_settings.py
git commit -m "feat: import user device definitions"
```

### Task 3: Projectless Hardware Facts and Readiness

**Files:**
- Modify: `keiltool/gui/project_config.py`
- Modify: `keiltool/gui/workbench_model.py`
- Modify: `keiltool/gui/workbench_controller.py`
- Modify: `keiltool/gui/settings.py`
- Test: `tests/test_gui_project_config.py`
- Test: `tests/test_gui_workbench_model.py`
- Test: `tests/test_gui_workbench_controller.py`

**Interfaces:**
- Consumes: `CatalogDevice`.
- Produces: `facts_from_catalog_device(...) -> ProjectTargetFacts`.
- Produces: `resolve_workbench_facts(project_target, catalog_device, ...)`.

- [ ] **Step 1: Write failing projectless-facts tests**

Assert a catalog device with verified RAM and target creates ready facts without
a project:

```python
facts = facts_from_catalog_device(device, openocd, scripts)
assert facts.project_path == ""
assert facts.device == "GD32F303VE"
assert facts.ram_origin == 0x20000000
assert facts.ram_size == 0x10000
assert facts.target_cfg.endswith("target/stm32f3x.cfg")
assert facts.ready
```

Also assert missing cfg, no writable RAM, and user target missing from scripts
all produce exact blocking diagnostics.

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_gui_project_config.py tests/test_gui_workbench_model.py -q
```

- [ ] **Step 3: Implement catalog-backed fact resolution**

Factor current OpenOCD executable/scripts discovery into a helper shared by
project and catalog sources. Convert writable catalog memories into RTT scan
regions and select the first default writable SRAM region.

Never call `infer_family()` or `FAMILY_TARGET_MAP` for a manually imported
device unless the embedded compatibility table contains an explicit exact
family mapping.

- [ ] **Step 4: Add project/catalog mismatch validation**

When a project is loaded, compare exact device name and normalized memory
regions with the matching catalog entry. A mismatch returns `ready=False` and a
diagnostic that names both sources and values.

- [ ] **Step 5: Persist manual device selection**

Add `device_vendor` and `device_name` to `GuiSettings`. Invalid or removed
selections fall back to no selected device rather than a fuzzy match.

- [ ] **Step 6: Run focused regression tests and commit**

```powershell
python -m pytest tests/test_gui_project_config.py tests/test_gui_workbench_model.py tests/test_gui_workbench_controller.py tests/test_gui_settings.py -q
git add keiltool/gui/project_config.py keiltool/gui/workbench_model.py keiltool/gui/workbench_controller.py keiltool/gui/settings.py tests/test_gui_project_config.py tests/test_gui_workbench_model.py tests/test_gui_workbench_controller.py tests/test_gui_settings.py
git commit -m "feat: resolve GUI hardware facts without a project"
```

### Task 4: Per-Operation Session Logging

**Files:**
- Create: `keiltool/core/session_logs.py`
- Modify: `keiltool/core/openocd_backend.py`
- Modify: `keiltool/core/rtt.py`
- Modify: `keiltool/gui/workbench_model.py`
- Modify: `keiltool/gui/app.py`
- Test: `tests/test_session_logs.py`
- Test: `tests/test_openocd_backend.py`
- Test: `tests/test_rtt.py`

**Interfaces:**
- Produces: `SessionLogContext`.
- Produces: `create_session_logs(root, device, task, metadata, now=None)`.
- Produces paths for RTT, OpenOCD stdout/stderr, and `session.json`.
- Produces: `finalize(outcome: str, ended_at: datetime) -> None`.

- [ ] **Step 1: Write failing directory/header tests**

Freeze time and assert:

```python
context = create_session_logs(
    root,
    device="GD32F303VE",
    task="RTT",
    metadata={"probe": "ST-Link", "target_cfg": "target/stm32f3x.cfg"},
    now=fixed_time,
)
assert context.directory.name == "20260724-211830-125_GD32F303VE_RTT"
assert context.rtt_log.name == "rtt.log"
assert "Task    : RTT" in context.rtt_log.read_text(encoding="utf-8")
assert json.loads(context.metadata_log.read_text(encoding="utf-8"))["device"] == "GD32F303VE"
```

Add sanitization and write-failure tests.

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -m pytest tests/test_session_logs.py -q
```

- [ ] **Step 3: Implement session creation and finalization**

Create the directory atomically enough to detect collisions by retrying with a
numeric suffix. Write local ISO-8601 timestamps with timezone. Write initial
headers before returning paths. `finalize()` atomically updates `session.json`
with outcome/end/duration and appends an outcome footer to text logs.

- [ ] **Step 4: Route all GUI operations through session contexts**

Replace flat filename construction for CONNECT, FLASH, and RTT. Abort before
creating `OpenOcdOperation` or `RttSession` if session creation fails.

Keep core backend APIs accepting explicit paths so CLI behavior remains
compatible.

- [ ] **Step 5: Verify complete RTT persistence**

Extend the socket test to emit INFO and DEBUG records while the GUI threshold is
INFO. Assert `rtt.log` contains both and the GUI displays only INFO.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_session_logs.py tests/test_openocd_backend.py tests/test_rtt.py tests/test_gui_smoke.py -q
git add keiltool/core/session_logs.py keiltool/core/openocd_backend.py keiltool/core/rtt.py keiltool/gui/workbench_model.py keiltool/gui/app.py tests/test_session_logs.py tests/test_openocd_backend.py tests/test_rtt.py tests/test_gui_smoke.py
git commit -m "feat: create self-describing operation log folders"
```

### Task 5: Device Selector, Output Copying, and Approved Theme

**Files:**
- Modify: `keiltool/gui/widgets.py`
- Modify: `keiltool/gui/theme.py`
- Modify: `keiltool/gui/app.py`
- Modify: `keiltool/gui/rtt_display.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_rtt_display.py`

**Interfaces:**
- Consumes: catalog APIs and projectless facts.
- Produces: searchable Device combobox, import command, source label.
- Produces: reusable `LogTextView` copy/select/context-menu behavior.

- [ ] **Step 1: Write failing GUI behavior tests**

Create a Tk root and assert:

- Device is a readonly searchable combobox populated from the catalog.
- Selecting a device without a project resolves ready facts.
- Loading a project selects and locks its exact device.
- Import invokes the import service and refreshes combobox values.
- `copy_selected()` places only the selected span on the clipboard.
- `copy_all()` copies visible text.
- right-click menu exposes Copy, Select all, and Copy all.
- custom log root remains editable without a project.

- [ ] **Step 2: Run GUI tests and confirm RED**

```powershell
python -m pytest tests/test_gui_smoke.py -q
```

- [ ] **Step 3: Refine widget boundaries**

Keep `ConfigurationPane` and `OutputNotebook`, but extract a focused
`LogTextView` helper responsible for Text creation, tags, keyboard bindings,
context menu, and clipboard operations. Do not move hardware lifecycle code out
of `KeilToolGui` in this task.

- [ ] **Step 4: Implement Device selection and import**

Change the existing Device row to a combobox plus import button. Project load
sets the exact selection and disables manual selection; clearing the project
restores manual selection. Selection changes recompute facts and control
readiness without opening hardware.

- [ ] **Step 5: Apply approved A-v2 palette**

Use:

```text
background       #DCE5E9
control surface  #F9FBFC
section header   #DFEAEC
primary          #087F8C
console          #0B1C23
console chrome   #102730 / #17313B
console text     #DFECEF
```

Keep existing EasyLogger level colors adjusted for the dark console. Add clear
running and source labels without changing the left/right layout.

- [ ] **Step 6: Verify 1024x720 and 1280x800**

Instantiate the GUI at both sizes, populate the longest expected Chinese labels,
and assert every toolbar child remains within its parent. Capture screenshots
for manual inspection, then keep screenshots outside git.

- [ ] **Step 7: Run tests and commit**

```powershell
python -m pytest tests/test_gui_smoke.py tests/test_rtt_display.py tests/test_gui_settings.py -q
git add keiltool/gui/widgets.py keiltool/gui/theme.py keiltool/gui/app.py keiltool/gui/rtt_display.py tests/test_gui_smoke.py tests/test_rtt_display.py
git commit -m "feat: select devices and improve log workbench"
```

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/01_KeilBridge_用户使用手册.md`
- Modify: `docs/03_KeilBridge_FAQ.md`
- Modify: `docs/superpowers/plans/2026-07-24-device-catalog-projectless-rtt-log-workbench.md`

**Interfaces:**
- Documents the shipped behavior; no new runtime interface.

- [ ] **Step 1: Update user documentation**

Document:

- projectless device selection;
- official and user catalog provenance;
- PDSC/PACK/custom JSON import;
- unsupported target blocking;
- custom remembered log root;
- per-operation directory and file names;
- copy-selected/copy-all behavior;
- unchanged no-reset RTT and complete-log guarantees.

- [ ] **Step 2: Run complete verification**

```powershell
python -m pytest -q
python -m compileall -q keiltool
python -m keiltool.cli --help
git diff --check
```

Expected: all tests pass, compileall and CLI return zero, and diff-check emits
no output.

- [ ] **Step 3: Run read-only GUI acceptance**

Launch from the existing desktop shortcut and verify:

- no hardware action occurs at startup;
- catalog devices load without a project;
- project selection still restores Target facts;
- log root can be changed and remembered;
- output text can be copied;
- closing the idle GUI leaves no OpenOCD process.

Do not run flash or RTT hardware acceptance unless the user confirms the actual
probe and target are connected.

- [ ] **Step 4: Commit**

```powershell
git add README.md docs/01_KeilBridge_用户使用手册.md docs/03_KeilBridge_FAQ.md docs/superpowers/plans/2026-07-24-device-catalog-projectless-rtt-log-workbench.md
git commit -m "docs: explain device catalog and session logs"
```
