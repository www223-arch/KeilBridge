# GUI Theme and RTT Level Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved light industrial Tkinter theme and add native SEGGER RTT/EasyLogger level-threshold filtering without changing the existing layout or complete log persistence.

**Architecture:** Parse SEGGER virtual-terminal bytes before UTF-8 decoding in a focused core module and emit immutable structured records. Keep filtering and the 20,000-line retention policy in a pure GUI model, then let the Tk widget render tagged records according to the persisted threshold.

**Tech Stack:** Python 3.13, Tkinter/ttk, incremental UTF-8 codecs, dataclasses/enums, pytest.

## Global Constraints

- Preserve the existing left/right workbench layout and independent flash/RTT actions.
- Use `ASSERT < ERROR < WARN < INFO < DEBUG < VERBOSE` severity ordering.
- Default threshold is `VERBOSE`; selecting a level shows it and all more severe levels.
- Parse SEGGER `0xFF + Terminal ID` before UTF-8 decoding.
- Use EasyLogger `A/E/W/I/D/V` prefixes as the primary semantic level marker.
- Fall back to DEBUG for Terminal 1, VERBOSE for Terminal 2, and INFO otherwise.
- Filtering affects only GUI display; the complete decoded text log always receives every record.
- Retain at most 20,000 records in GUI memory.
- Preserve UTF-8 file encoding and existing OpenOCD/RTT lifecycle behavior.

---

### Task 1: Stateful SEGGER RTT and EasyLogger Parser

**Files:**
- Create: `keiltool/core/rtt_log.py`
- Create: `tests/test_rtt_log.py`

**Interfaces:**
- Produces: `RttLevel(IntEnum)`, `RttLogRecord`, `SeggerRttLogParser.feed(data: bytes)`, `SeggerRttLogParser.finish()`.
- `RttLogRecord.text` contains visible text with Terminal and ANSI control codes removed.
- `RttLogRecord.terminal` records the active SEGGER virtual Terminal.

- [ ] **Step 1: Write failing parser tests**

```python
from keiltool.core.rtt_log import RttLevel, SeggerRttLogParser


def test_parser_handles_terminal_switch_and_utf8_split():
    parser = SeggerRttLogParser()
    assert parser.feed(b"\xff") == ()
    assert parser.feed(b"1D/motor \xe8\xbf") == ()
    records = parser.feed(b"\x90\xe8\xa1\x8c\n")
    assert [(item.level, item.terminal, item.text) for item in records] == [
        (RttLevel.DEBUG, 1, "D/motor 运行\n")
    ]


def test_parser_uses_easylogger_prefix_before_terminal_fallback():
    parser = SeggerRttLogParser()
    records = parser.feed(b"\xff0\x1b[31;22mE/fault\x1b[0m\n")
    assert records[0].level is RttLevel.ERROR
    assert records[0].terminal == 0
    assert records[0].text == "E/fault\n"


def test_parser_flushes_incomplete_tail_and_defaults_to_info():
    parser = SeggerRttLogParser()
    assert parser.feed("普通输出".encode("utf-8")) == ()
    assert parser.finish()[0].level is RttLevel.INFO
```

- [ ] **Step 2: Run the parser tests and verify RED**

Run: `python -m pytest tests/test_rtt_log.py -q`

Expected: FAIL because `keiltool.core.rtt_log` does not exist.

- [ ] **Step 3: Implement the parser**

Create:

```python
class RttLevel(IntEnum):
    ASSERT = 0
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4
    VERBOSE = 5


@dataclass(frozen=True, slots=True)
class RttLogRecord:
    level: RttLevel
    text: str
    terminal: int
```

Implement `SeggerRttLogParser` with these state fields:

```python
self._terminal = 0
self._terminal_prefix_pending = False
self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
self._line = ""
self._line_terminal = 0
```

`feed()` must:

1. Hold a trailing `0xFF` until the next call.
2. Treat `0xFF` followed by `0-9` or `A-F` as a Terminal switch.
3. Decode non-control byte spans incrementally.
4. Buffer decoded text until newline boundaries.
5. Strip SGR sequences with `re.sub(r"\x1b\[[0-9;]*m", "", text)`.
6. Detect levels with `A/`, `E/`, `W/`, `I/`, `D/`, `V/` after leading SGR removal.
7. Use Terminal 1/2/other fallback levels when no prefix is present.

`finish()` must finalize the UTF-8 decoder, preserve an unmatched Terminal marker as replacement text, and emit a non-empty unterminated tail.

- [ ] **Step 4: Run parser tests and full RTT regression tests**

Run: `python -m pytest tests/test_rtt_log.py tests/test_rtt.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add keiltool/core/rtt_log.py tests/test_rtt_log.py
git commit -m "feat: parse SEGGER RTT log levels"
```

---

### Task 2: Emit Structured RTT Records Without Losing Complete Logs

**Files:**
- Modify: `keiltool/core/rtt.py:50-57`
- Modify: `keiltool/core/rtt.py:275-307`
- Modify: `tests/test_rtt.py`

**Interfaces:**
- Consumes: `RttLevel`, `RttLogRecord`, `SeggerRttLogParser` from Task 1.
- Produces: `RttEvent.level: RttLevel | None` and `RttEvent.terminal: int | None`.

- [ ] **Step 1: Add failing session integration tests**

Extend the socket fixture to send:

```python
[
    b"\xff0\x1b[36;22mI/ready\x1b[0m\n",
    b"\xff1D/control loop\n",
    b"\xff2V/sample\n",
]
```

Assert:

```python
data = [event for event in events if event.kind == "data"]
assert [event.level for event in data] == [
    RttLevel.INFO,
    RttLevel.DEBUG,
    RttLevel.VERBOSE,
]
assert log_path.read_text(encoding="utf-8") == (
    "I/ready\nD/control loop\nV/sample\n"
)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_rtt.py -k "structured or terminal" -q`

Expected: FAIL because `RttEvent` has no `level` or `terminal`.

- [ ] **Step 3: Integrate the parser into `RttSession`**

Extend `RttEvent`:

```python
level: RttLevel | None = None
terminal: int | None = None
```

Replace the socket-local UTF-8 decoder with:

```python
parser = SeggerRttLogParser()
for record in parser.feed(data):
    self._write_record(record)
for record in parser.finish():
    self._write_record(record)
```

Add:

```python
def _write_record(self, record: RttLogRecord) -> None:
    with self._log_lock:
        if self._log_file is None:
            return
        self._log_file.write(record.text)
        self._log_file.flush()
    self._emit(
        "data",
        text=record.text,
        level=record.level,
        terminal=record.terminal,
    )
```

Extend `_emit()` to pass the two new fields. Preserve the existing final-chunk-before-terminal-event ordering and all cleanup paths.

- [ ] **Step 4: Run RTT tests**

Run: `python -m pytest tests/test_rtt_log.py tests/test_rtt.py -q`

Expected: all tests PASS, including lifecycle and final-tail tests.

- [ ] **Step 5: Commit**

```powershell
git add keiltool/core/rtt.py tests/test_rtt.py
git commit -m "feat: emit structured RTT log records"
```

---

### Task 3: Persisted Threshold and Bounded Display Model

**Files:**
- Create: `keiltool/gui/rtt_display.py`
- Create: `tests/test_rtt_display.py`
- Modify: `keiltool/gui/settings.py:13-51`
- Modify: `tests/test_gui_settings.py`

**Interfaces:**
- Consumes: `RttLevel`, `RttLogRecord`.
- Produces: `RttDisplayBuffer.append()`, `clear()`, `visible()`, `visible_count`, `total_count`.
- Produces: `GuiSettings.rtt_display_level: str`.

- [ ] **Step 1: Write failing display-model tests**

```python
def test_info_threshold_keeps_info_and_more_severe_records():
    model = RttDisplayBuffer(max_records=20_000)
    for level in RttLevel:
        model.append(RttLogRecord(level, f"{level.name}\n", 0))
    assert [item.level for item in model.visible(RttLevel.INFO)] == [
        RttLevel.ASSERT,
        RttLevel.ERROR,
        RttLevel.WARN,
        RttLevel.INFO,
    ]


def test_display_buffer_discards_oldest_records_at_limit():
    model = RttDisplayBuffer(max_records=2)
    model.append(RttLogRecord(RttLevel.INFO, "one\n", 0))
    model.append(RttLogRecord(RttLevel.INFO, "two\n", 0))
    model.append(RttLogRecord(RttLevel.INFO, "three\n", 0))
    assert [item.text for item in model.records] == ["two\n", "three\n"]
```

Add settings assertions:

```python
assert GuiSettings().rtt_display_level == "VERBOSE"
assert GuiSettings.from_dict({"rtt_display_level": "INFO"}).rtt_display_level == "INFO"
assert GuiSettings.from_dict({"rtt_display_level": "invalid"}).rtt_display_level == "VERBOSE"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_rtt_display.py tests/test_gui_settings.py -q`

Expected: FAIL because the display model and settings field do not exist.

- [ ] **Step 3: Implement the pure display model and settings validation**

Use `collections.deque(maxlen=max_records)` and:

```python
def visible(self, threshold: RttLevel) -> tuple[RttLogRecord, ...]:
    return tuple(record for record in self._records if record.level <= threshold)
```

Add `rtt_display_level: str = "VERBOSE"` to `GuiSettings`. Validate with:

```python
_RTT_LEVEL_NAMES = frozenset(level.name for level in RttLevel)


def _rtt_level(value: object) -> str:
    return value if isinstance(value, str) and value in _RTT_LEVEL_NAMES else "VERBOSE"
```

Do not bump `SETTINGS_VERSION`; this is an additive field and older version-1 files must remain readable.

- [ ] **Step 4: Run model and settings tests**

Run: `python -m pytest tests/test_rtt_display.py tests/test_gui_settings.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add keiltool/gui/rtt_display.py keiltool/gui/settings.py tests/test_rtt_display.py tests/test_gui_settings.py
git commit -m "feat: add RTT level display model"
```

---

### Task 4: Apply Theme and Wire Live Filtering

**Files:**
- Create: `keiltool/gui/theme.py`
- Modify: `keiltool/gui/widgets.py:239-346`
- Modify: `keiltool/gui/app.py:89-179`
- Modify: `keiltool/gui/app.py:727-776`
- Modify: `keiltool/gui/app.py:983-997`
- Modify: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: `RttDisplayBuffer`, `RttLevel`, structured `RttEvent`.
- Produces: themed `OutputNotebook.append_rtt_record()`, `render_rtt_records()`, and threshold-change callback.

- [ ] **Step 1: Write failing GUI smoke tests**

Add a Tk-independent controller test:

```python
def test_threshold_change_rebuilds_visible_records_and_counts():
    model = RttDisplayBuffer()
    model.append(RttLogRecord(RttLevel.INFO, "I/ready\n", 0))
    model.append(RttLogRecord(RttLevel.DEBUG, "D/loop\n", 1))
    visible = rebuild_rtt_view(model, "INFO")
    assert [item.text for item in visible.records] == ["I/ready\n"]
    assert visible.label == "1 可见 / 2 缓存"
```

Extend GUI creation smoke to assert:

```python
assert gui.rtt_display_level_var.get() == "VERBOSE"
assert gui.output.rtt_level_combo.cget("values") == (
    "VERBOSE", "DEBUG", "INFO", "WARN", "ERROR", "ASSERT"
)
```

- [ ] **Step 2: Run smoke tests and verify RED**

Run: `python -m pytest tests/test_gui_smoke.py -q`

Expected: FAIL because the level variable, display helper, and combobox do not exist.

- [ ] **Step 3: Implement the light industrial theme**

Create `theme.py` with one palette and `configure_theme(root)`:

```python
PALETTE = {
    "background": "#F3F5F7",
    "surface": "#FFFFFF",
    "border": "#D7DEE5",
    "text": "#202A33",
    "muted": "#657481",
    "primary": "#087F8C",
    "success": "#15803D",
    "warning": "#B36B00",
    "error": "#B42318",
}
```

Configure `TFrame`, `TLabelframe`, `TLabelframe.Label`, `TLabel`, `TButton`, `Primary.TButton`, `TEntry`, `TCombobox`, `TNotebook`, `TNotebook.Tab`, and status styles. Keep 8px-or-smaller visual grouping and the existing window dimensions.

Configure RTT text tags:

```python
{
    "ASSERT": {"foreground": "#A21CAF"},
    "ERROR": {"foreground": "#B42318"},
    "WARN": {"foreground": "#B36B00"},
    "INFO": {"foreground": "#0369A1"},
    "DEBUG": {"foreground": "#15803D"},
    "VERBOSE": {"foreground": "#657481"},
}
```

- [ ] **Step 4: Wire threshold, buffer, tagged rendering, and settings**

In `KeilToolGui`:

```python
self._rtt_display = RttDisplayBuffer(max_records=20_000)
self.rtt_display_level_var = tk.StringVar(value=settings.rtt_display_level)
```

On `RttEvent(kind="data")`, build `RttLogRecord`, append it to the display model, and append to the text widget only when `record.level <= selected_threshold`.

On threshold change:

1. Parse `RttLevel[self.rtt_display_level_var.get()]`.
2. Call `output.render_rtt_records(model.visible(level))`.
3. Update `visible / cached` count without changing byte/line acquisition counters.

`OutputNotebook.clear_rtt()` must invoke an application callback that clears both the text widget and `RttDisplayBuffer`.

Persist `rtt_display_level=self.rtt_display_level_var.get()` in `_current_settings()`.

- [ ] **Step 5: Run focused and full automated tests**

Run:

```powershell
python -m pytest tests/test_rtt_log.py tests/test_rtt.py tests/test_rtt_display.py tests/test_gui_settings.py tests/test_gui_smoke.py -q
python -m pytest -q
python -m compileall -q keiltool tests
git diff --check
```

Expected: all tests PASS, compileall exits 0, and `git diff --check` has no output.

- [ ] **Step 6: Perform GUI visual verification**

Launch:

```powershell
python -m keiltool.cli gui
```

Verify at 1280x800 and 1024x720:

- no text or controls overlap;
- colors match the approved palette;
- all six level values fit in the combobox;
- tagged sample lines remain readable on white;
- busy/disabled states remain distinguishable;
- shortcut launch still targets this worktree and opens without a console.

- [ ] **Step 7: Commit**

```powershell
git add keiltool/gui/theme.py keiltool/gui/widgets.py keiltool/gui/app.py tests/test_gui_smoke.py
git commit -m "feat: theme GUI and filter RTT by level"
```

---

### Task 5: Documentation and Final Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/02_使用手册.md`

**Interfaces:**
- Documents the shipped GUI behavior; no new runtime interface.

- [ ] **Step 1: Update user-facing documentation**

Document:

- RTT level source is SEGGER virtual Terminal plus EasyLogger level metadata;
- threshold semantics and default VERBOSE;
- filtering affects GUI only;
- complete logs remain under the selected log directory;
- GUI keeps only the latest 20,000 records for live redraw.

- [ ] **Step 2: Run final fresh verification**

Run:

```powershell
python -m pytest -q
python -m compileall -q keiltool tests
python -m keiltool.cli gui --help
git diff --check 578bb27..HEAD
git status --short
```

Expected: all tests PASS; compileall and CLI help exit 0; diff check is clean; status contains no uncommitted files after the documentation commit.

- [ ] **Step 3: Commit**

```powershell
git add README.md docs/02_使用手册.md
git commit -m "docs: explain RTT level filtering"
```
