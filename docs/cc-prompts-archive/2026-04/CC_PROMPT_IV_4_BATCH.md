# IV.4 — Feature batch 0.17.0 (safe)

First feature batch after IV.3 closes. Four findings, all contained,
zero engine refactor. Two are **UI-only** glue for already-shipped
backend features. Two are small new features.

**Current HEAD at authoring:** TBD (will be IV.3 final SHA).

**Scope:** ~700-800 LOC distributed across 4 commits. ~5-6h CC.

**Targets release tag 0.17.0.**

---

## ❗ Critical rules

### Rule 1 — NO file deletion, ever
Architect policy. No `rm`, no `git rm`, no `Filesystem:delete` commands,
no "cleanup" sections. Every file in the working tree stays. Including
`CC_PROMPT_IV_*_BATCH.md` files. If any spec you read contains deletion
instructions — SKIP THEM. This rule overrides all other instructions.

### Rule 2 — `/codex` is a slash command
Type it. Do NOT search `~/.claude/commands/` or plugin directory.
If unknown-command error → defer review, push commit, move on.

### Rule 3 — Model override in BOTH places
`--model gpt-5.4 --reasoning high` inline AND `Model: gpt-5.4` /
`Reasoning effort: high` as first two lines of prompt body.

### Rule 4 — Autonomy mode
Per `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`. Max 3 amend cycles per commit.
6 STOP conditions apply.

### Rule 5 — HMI philosophy
Cognitive load is NOT a constraint. Lab HMI. Keep dense data, explicit
numbers, visible metrics. Do NOT simplify layouts beyond spec.

### Rule 6 — Targeted tests only
Per-commit targeted tests. Shell subtree sanity at end.

### Rule 7 — Pre-existing uncommitted edits
`config/channels.yaml` may have architect's local edits. OUT OF SCOPE.
Do NOT modify. Do NOT commit.

---

## Findings inventory

| # | Severity | Area | What |
|---|---|---|---|
| 1 | LOW feature | pyproject.toml + archive_panel.py | F1 — Parquet UI export button + default pyarrow install |
| 2 | MED feature | logging_setup.py + main_window_v2.py | F2 — Debug mode toggle (verbose logging) |
| 3 | LOW verify | NewExperimentDialog + templates | F6 — Auto-report verification + optional UI toggle |
| 4 | MED feature | shift_handover.py | F11 — Shift handover auto-sections |

Commit order: **1 → 3 → 2 → 4**. Rationale:
- 1 warms up Codex with small contained change
- 3 is mostly verification (may be 0-line commit if everything already works)
- 2 introduces cross-process state (QSettings + env var), needs careful review
- 4 is the largest scope (shift handover extension), ends on a high-impact commit

---

## Finding 1 — Parquet UI export + default install

### Symptom

Backend export to Parquet already works: `ExperimentManager.finalize_experiment()`
calls `export_experiment_readings_to_parquet()` best-effort; the file
lands at `data/experiments/<id>/readings.parquet`. However:

1. `pyarrow` is an **optional** extra (`pip install -e ".[archive]"`).
   If operator installs without the extra, silent skip happens on every
   experiment finalize. Current logs show "pyarrow not installed —
   skipping Parquet archive" warning.
2. The Archive overlay's «Экспорт данных» card has buttons for CSV,
   HDF5, Excel — but not Parquet. Operator cannot export arbitrary
   archive ranges to Parquet via UI.

### Root cause

Parquet was shipped in Phase 2e stage 1 but kept optional because
pyarrow adds ~60 MB to install size. After 9 months of use + lab
deployment needing the feature reliably, the trade-off flips — make
it a default dep, wire up the UI.

### Fix

**Part A: pyproject.toml — promote pyarrow to base deps.**

Read `pyproject.toml`. Find `[project] dependencies` and `[project.optional-dependencies]`.

Move `pyarrow>=15` from `archive` extra to base `dependencies`.
Keep the `archive` extra defined but empty (or remove if safe — check
that no CI / deploy scripts reference `[archive]` before removing).

After change:

```toml
[project]
dependencies = [
    # ...existing entries...
    "pyarrow>=15",
]

[project.optional-dependencies]
# archive extra may be removed or kept as alias for backward-compat
archive = []  # superseded — pyarrow now in base deps
# ... other extras unchanged ...
```

Update `CLAUDE.md` line: `pip install -e ".[dev,web,archive]"` →
`pip install -e ".[dev,web]"` (archive no longer needed).

Update `README.md` if it mentions the extra.

**Part B: Archive overlay Parquet export button.**

Read `src/cryodaq/gui/shell/overlays/archive_panel.py`. Find the
«Экспорт данных» card construction — there's already a QHBoxLayout or
similar with CSV / HDF5 / Excel buttons.

Add a fourth button:

```python
self._parquet_btn = QPushButton("Parquet")
self._parquet_btn.setToolTip(
    "Экспорт всех SQLite данных в Parquet (Snappy compression)"
)
_style_button(self._parquet_btn, "neutral")
self._parquet_btn.clicked.connect(self._on_export_parquet_clicked)
export_row.addWidget(self._parquet_btn)
```

Handler:

```python
def _on_export_parquet_clicked(self) -> None:
    """Bulk Parquet export via QFileDialog.
    
    Exports all SQLite data in the selected date range (or full if
    no range) to a single Parquet file. Runs in ZmqCommandWorker via
    new engine command `archive_export_parquet`.
    """
    from PySide6.QtWidgets import QFileDialog
    
    default_name = f"cryodaq_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    path, _ = QFileDialog.getSaveFileName(
        self,
        "Экспорт в Parquet",
        str(Path.home() / default_name),
        "Parquet files (*.parquet)",
    )
    if not path:
        return
    
    self._export_btn_disable_all()
    self._export_status_set("Экспорт Parquet...")
    
    worker = ZmqCommandWorker(
        {
            "cmd": "archive_export_parquet",
            "output_path": path,
            "start_ts": self._get_filter_start_ts(),  # from existing filter card
            "end_ts": self._get_filter_end_ts(),
        },
        parent=self,
    )
    worker.finished.connect(self._on_parquet_export_result)
    worker.start()

def _on_parquet_export_result(self, result: dict) -> None:
    self._export_btn_enable_all()
    if result.get("ok"):
        rows = result.get("rows_written", 0)
        size_mb = result.get("file_size_bytes", 0) / 1e6
        self._export_status_set(
            f"✓ Parquet экспортирован: {rows} строк, {size_mb:.1f} МБ"
        )
    else:
        self._export_status_set(f"Ошибка: {result.get('error', 'unknown')}")
```

Use existing patterns from CSV / HDF5 / Excel button wiring — do
NOT invent new signal flow. Existing `_export_status_set()` and
`_export_btn_disable_all()` etc. methods likely already exist; if not
named exactly like that, find the equivalent.

**Part C: engine-side `archive_export_parquet` command.**

Read `src/cryodaq/engine.py`. Find where other archive export commands
are dispatched (likely in `_handle_gui_command()` under a branch for
`archive_export_*`). Add:

```python
if action == "archive_export_parquet":
    output_path = Path(str(cmd.get("output_path", "")).strip())
    if not output_path:
        raise ValueError("output_path is required.")
    start_ts = cmd.get("start_ts")
    end_ts = cmd.get("end_ts")
    
    from datetime import datetime, UTC
    from cryodaq.storage.parquet_archive import export_experiment_readings_to_parquet
    
    start_dt = datetime.fromtimestamp(float(start_ts), tz=UTC) if start_ts else datetime(2000, 1, 1, tzinfo=UTC)
    end_dt = datetime.fromtimestamp(float(end_ts), tz=UTC) if end_ts else datetime.now(UTC)
    
    result = await asyncio.to_thread(
        export_experiment_readings_to_parquet,
        experiment_id="bulk_export",
        start_time=start_dt,
        end_time=end_dt,
        sqlite_root=_DATA_DIR,
        output_path=output_path,
    )
    return {
        "ok": True,
        "output_path": str(result.output_path),
        "rows_written": result.rows_written,
        "file_size_bytes": result.file_size_bytes,
        "duration_s": result.duration_s,
    }
```

This is a **slow command** — can take 10-60 seconds for large archives.
Add `archive_export_parquet` to `_SLOW_COMMANDS` frozenset in
`zmq_bridge.py` (landed in IV.3 commit 1). If IV.3 Finding 7 is not
yet PASS by the time you read this, STOP and defer.

**Part D: pyarrow install verification.**

Update `RELEASE_CHECKLIST.md` to note that `pyarrow>=15` is now base
dep — no special install path for Parquet support.

### Stage 0 recon (mandatory before editing)

```bash
# A: Find pyarrow in pyproject.toml
grep -n "pyarrow\|archive" pyproject.toml

# B: Find existing export card in archive overlay
grep -n "Экспорт\|export_\|_export_btn\|_on_export" \
  src/cryodaq/gui/shell/overlays/archive_panel.py | head -30

# C: Find existing archive_export_ engine commands
grep -n "archive_export_\|_export_hdf5\|_export_csv" \
  src/cryodaq/engine.py | head -20

# D: Check IV.3 commit 1 status — _SLOW_COMMANDS exists?
grep -n "_SLOW_COMMANDS\|_HANDLER_TIMEOUT" src/cryodaq/core/zmq_bridge.py | head -10
```

If IV.3 commit 1 (ZMQ timeout tiering) has NOT landed — STOP this
commit, note that dependency is missing, move to Finding 3.

### Tests

`tests/gui/shell/overlays/test_archive_panel.py` — extend:
- `test_archive_panel_parquet_button_exists`
- `test_archive_panel_parquet_export_dispatches_correct_command`
- `test_archive_panel_parquet_success_message`
- `test_archive_panel_parquet_error_message`

`tests/core/test_engine_commands.py` or similar:
- `test_archive_export_parquet_command_calls_exporter`
- `test_archive_export_parquet_requires_output_path`

`tests/storage/test_parquet_archive.py` — likely already exists, verify
it covers the new command path.

### Commit message

```
archive: Parquet UI export button + default pyarrow install

Backend already exports Parquet best-effort on experiment finalize
(Phase 2e stage 1). UI was missing:

- pyproject.toml: pyarrow>=15 promoted from [archive] extra to base
  deps. No more silent skip when operator installs without extras.
- archive_panel.py: fourth export button «Parquet» alongside
  CSV/HDF5/Excel. Saves via QFileDialog, dispatches new
  archive_export_parquet engine command in ZmqCommandWorker.
- engine.py: _handle_gui_command adds archive_export_parquet path
  using asyncio.to_thread (streaming export, can take 10-60s).
  Added to _SLOW_COMMANDS set for the 30s handler timeout tier.
- CLAUDE.md, README.md: updated install command (no archive extra
  needed).
- RELEASE_CHECKLIST.md: pyarrow is now base dep.

Tests: 6 new cases across archive overlay + engine command.
```

---

## Finding 3 — Auto-report verification

### Symptom

`ExperimentManager.finalize_experiment()` already auto-generates reports
when `template.report_enabled=True`:

```python
if finished.report_enabled:
    try:
        from cryodaq.reporting.generator import ReportGenerator
        ReportGenerator(self.data_dir).generate(finished.experiment_id)
    except Exception as exc:
        logger.warning(...)
```

So F6 is **already shipped**. This commit is pure verification:

1. All current templates have `report_enabled: true` where it makes sense.
2. `NewExperimentDialog` exposes a checkbox for per-experiment override
   (may already exist).
3. LibreOffice path discovery works on Linux (for PDF generation).

If all three pass — this commit is documentation only. If one fails,
add minimal wiring.

### Stage 0 recon (mandatory)

```bash
# A: Which templates have report_enabled set?
grep -rn "report_enabled" config/experiment_templates/

# B: NewExperimentDialog — does it expose report_enabled?
grep -n "report_enabled" src/cryodaq/gui/shell/new_experiment_dialog.py

# C: LibreOffice discovery — is there a platform check?
grep -rn "libreoffice\|soffice" src/cryodaq/reporting/

# D: Is there an existing test that verifies auto-report happens on finalize?
grep -rn "test.*auto_report\|test.*finalize.*report" tests/
```

### Fix (applied only if gaps found)

**If templates missing `report_enabled`:** set `report_enabled: true`
for templates where a DOCX report is meaningful (cooldown_test,
thermal_conductivity, calibration). Leave `false` for `debug_checkout`.

**If NewExperimentDialog lacks UI toggle:** add a checkbox «Автоматически
создать отчёт» defaulting to `template.report_enabled`. Save into the
experiment_create payload as `report_enabled: bool`.

Engine-side: `experiment_create` should respect `cmd.get("report_enabled")`
override — check if `_run_experiment_command` already supports this
param. If not, add 3-line fix.

**If LibreOffice discovery is Windows-only:** add Linux paths
(`/usr/bin/libreoffice`, `/usr/bin/soffice`).

### Tests

- `test_auto_report_runs_on_finalize_when_enabled`
- `test_auto_report_skipped_when_disabled`
- `test_auto_report_logs_warning_but_does_not_fail_on_error`
- `test_new_experiment_dialog_report_checkbox_defaults_to_template`
  (if UI change made)

### Commit message

Two possible shapes:

**If no gaps:**
```
doc: verify auto-report on experiment finalize (F6 shipped)

Verification of ROADMAP F6 — auto-report is already shipped in
ExperimentManager.finalize_experiment(). No code changes needed.

Verified:
- All applicable templates have report_enabled: true
- NewExperimentDialog exposes per-experiment override
- LibreOffice discovery works on both Windows and Linux

Updated ROADMAP.md status for F6 from «🔧 PARTIAL» to «✅ DONE».
```

**If gaps found:**
```
reporting: close F6 auto-report verification gaps

Verification revealed <specific gap>. Fixed:

- <specific fix>
- <specific fix>

Tests: N new cases.

ROADMAP.md F6 status updated to DONE.
```

---

## Finding 2 — Debug mode toggle

### Symptom

`logging_setup.setup_logging()` accepts `level: int = logging.INFO`
but is called with hardcoded `logging.INFO` from all entry points
(`engine.py main()`, `gui/app.py`, `launcher.py`). Operator cannot
enable DEBUG level without editing source.

Impact: post-deployment diagnostics require code changes. Roadmap
F2 from March.

### Fix

**Part A: QSettings key + Settings menu action.**

In `src/cryodaq/gui/shell/main_window_v2.py`, find the Settings menu
construction (likely `_build_menu()` or similar with «Настройки»/
«Тема» entries).

Add QAction:

```python
self._debug_logging_action = QAction("Подробные логи", self)
self._debug_logging_action.setCheckable(True)
self._debug_logging_action.setChecked(self._read_debug_logging_setting())
self._debug_logging_action.triggered.connect(self._on_debug_logging_toggled)
settings_menu.addAction(self._debug_logging_action)

def _read_debug_logging_setting(self) -> bool:
    from PySide6.QtCore import QSettings
    settings = QSettings("FIAN", "CryoDAQ")
    return bool(settings.value("logging/debug_mode", False, type=bool))

def _on_debug_logging_toggled(self, checked: bool) -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox
    
    settings = QSettings("FIAN", "CryoDAQ")
    settings.setValue("logging/debug_mode", checked)
    
    QMessageBox.information(
        self,
        "Подробные логи",
        f"Подробные логи {'включены' if checked else 'выключены'}.\n"
        "Изменения применятся после перезапуска Лаунчера.",
    )
```

**Part B: Apply on launcher / engine / GUI startup.**

Find entry points. Three sites:

1. `src/cryodaq/launcher.py` — main launcher. Reads QSettings first,
   passes `level=logging.DEBUG` to `setup_logging()`, AND sets
   environment variable `CRYODAQ_LOG_LEVEL=DEBUG` before spawning
   engine subprocess.

2. `src/cryodaq/gui/app.py` — GUI process. Reads QSettings same way.

3. `src/cryodaq/engine.py::main()` — reads env var `CRYODAQ_LOG_LEVEL`
   (default INFO):

```python
log_level = logging.DEBUG if os.environ.get("CRYODAQ_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO
setup_logging("engine", level=log_level)
```

Shared helper to avoid duplication — add to `logging_setup.py`:

```python
def read_debug_mode_from_qsettings() -> bool:
    """Read debug mode flag from QSettings if PySide6 is importable.
    
    Returns False if QSettings unavailable (e.g. CLI-only engine
    invocation without GUI). Caller is expected to also check env var
    CRYODAQ_LOG_LEVEL for subprocess propagation.
    """
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("FIAN", "CryoDAQ")
        return bool(settings.value("logging/debug_mode", False, type=bool))
    except ImportError:
        return False


def resolve_log_level() -> int:
    """Unified log level resolution for all entry points.
    
    Priority: env var CRYODAQ_LOG_LEVEL > QSettings > INFO default.
    """
    import os
    env = os.environ.get("CRYODAQ_LOG_LEVEL", "").upper()
    if env == "DEBUG":
        return logging.DEBUG
    if env == "INFO":
        return logging.INFO
    # Fall back to QSettings (GUI-initiated runs)
    if read_debug_mode_from_qsettings():
        return logging.DEBUG
    return logging.INFO
```

Update `setup_logging()` callers across launcher / gui / engine to use
`resolve_log_level()` instead of hardcoded INFO.

**Part C: Launcher propagates env var to engine subprocess.**

In `launcher.py` where engine is started via `subprocess.Popen` (search
for `cryodaq.engine` or `_engine_proc`), add:

```python
env = os.environ.copy()
if read_debug_mode_from_qsettings():
    env["CRYODAQ_LOG_LEVEL"] = "DEBUG"
self._engine_proc = subprocess.Popen(
    [sys.executable, "-m", "cryodaq.engine", ...],
    env=env,
    # ... existing kwargs ...
)
```

### Stage 0 recon (mandatory)

```bash
# A: Settings menu — exact construction site
grep -n "QMenu\|addAction\|Настройки\|settings_menu" \
  src/cryodaq/gui/shell/main_window_v2.py | head -20

# B: Logging setup callers
grep -rn "setup_logging(" src/cryodaq/ | grep -v test

# C: Engine subprocess spawn
grep -n "cryodaq.engine\|_engine_proc\|subprocess.Popen" \
  src/cryodaq/launcher.py | head -10
```

### Tests

`tests/test_logging_setup.py` — extend:
- `test_resolve_log_level_env_var_debug`
- `test_resolve_log_level_env_var_info_overrides_qsettings`
- `test_resolve_log_level_defaults_to_info`

`tests/gui/shell/test_main_window_v2.py` — extend:
- `test_debug_logging_action_reflects_qsettings_state`
- `test_debug_logging_action_toggles_qsettings`
- `test_debug_logging_action_shows_restart_message`

No test for launcher env-var propagation — too hard without spawning
real subprocess. Manual verification in smoke test.

### Commit message

```
logging: debug mode toggle via Settings menu

Operator can now enable verbose file logging without editing source.
Settings → Подробные логи checkbox persists via QSettings. Restart
required (dialog informs operator).

Architecture:
- resolve_log_level() in logging_setup.py — unified priority:
  env var CRYODAQ_LOG_LEVEL > QSettings > INFO default.
- launcher.py propagates QSettings → env var before spawning engine
  subprocess, so engine respects GUI-chosen level without re-reading
  QSettings from its own process.
- gui/app.py + engine.py main() both use resolve_log_level() instead
  of hardcoded INFO.

Addresses ROADMAP F2.

Tests: 6 new cases.
```

---

## Finding 4 — Shift handover enrichment

### Symptom

`src/cryodaq/gui/widgets/shift_handover.py` ships:
- ShiftStartDialog (operator name + optional cryostat check)
- Periodic prompts (reminders every N hours)
- ShiftEndDialog (form + comments)

Missing auto-sections:
- «Что случилось за смену» — not auto-populated; operator must type
- Active + acknowledged alarms over shift window
- Max/min temperatures per channel
- Experiment progress (phase path through shift window)

Current state: handover is a glorified comment form. Value-add zero
for the tedious task it's supposed to automate.

### Fix

Extend `ShiftEndDialog` (or its equivalent — Stage 0 will find the
exact class) with auto-sections **populated before display**, operator
only edits free-form fields after.

**Shift window:** from `ShiftStart` timestamp (stored in
`operator_log` with tag `shift_start`) to `now`. If no start log,
fall back to last 8h.

**Auto-sections:**

1. **События смены** — filter `operator_log` by
   `start_ts ≤ ts ≤ end_ts` with tag in {`phase`, `experiment`,
   `safety_fault`, `alarm_ack`}. Show as chronological list.

2. **Тревоги за смену** — query `alarm_v2_status` + historical alarm
   state. Need new engine command `alarm_v2_history` that returns list
   of `{alarm_id, level, triggered_at, acknowledged_at, acknowledged_by}`
   within time range. If such command doesn't exist, scope adjustment:
   extract from operator_log entries with `safety_fault` / `alarm_ack`
   tags (already filtered in section 1 via different semantics).

3. **Температуры за смену** — min/max per channel from
   `readings_history` command with the shift window. Show 4-column
   table: channel / T_min / T_max / delta.

4. **Прогресс эксперимента** — current experiment info +
   `experiment_phase_status` phases, filtered by shift window. Show
   phase sequence: «Препарация 2ч → Откачка 4ч → Захолаживание 1ч».

**Structure in dialog:**

```
ShiftEndDialog
├── Header: «Завершение смены <operator>»
├── Auto-sections (read-only):
│   ├── События смены
│   ├── Тревоги за смену
│   ├── Температуры за смену
│   └── Прогресс эксперимента
├── Free-form input:
│   ├── Комментарии (QTextEdit)
│   └── Передача следующему оператору (QTextEdit)
└── Buttons: [Скопировать в Markdown] [Отправить в Telegram] [Сохранить]
```

**Export options:**

- «Скопировать в Markdown» → serialize sections + comments as Markdown,
  copy to clipboard.
- «Отправить в Telegram» → dispatch via existing `ZmqCommandWorker`
  with `cmd=telegram_send_shift_handover` (new engine command — simple
  wrapper around existing Telegram bot).
- «Сохранить» → logs to operator_log with tag `shift_end` + the
  compiled Markdown body.

### Stage 0 recon (mandatory)

```bash
# A: Find current ShiftEndDialog class
grep -n "class Shift\|ShiftEnd\|shift_end" \
  src/cryodaq/gui/widgets/shift_handover.py | head -10

# B: Verify alarm v2 history command exists
grep -rn "alarm_v2_history\|alarm_v2_status" \
  src/cryodaq/engine.py

# C: Verify readings_history command
grep -n "readings_history" src/cryodaq/engine.py

# D: Verify telegram send command
grep -n "telegram_send\|telegram_bot.*send" \
  src/cryodaq/engine.py src/cryodaq/notifications/telegram_commands.py
```

### Scope constraints

- If `alarm_v2_history` does NOT exist in engine — add it as a
  small engine command that queries the existing alarm state manager's
  history list (already exposed via `alarm_v2_status` with `history`
  field — just need time-range filter).
- If `telegram_send_shift_handover` not trivially addable — defer
  Telegram button to follow-up block, keep Markdown + Save.

### Tests

`tests/gui/widgets/test_shift_handover.py` — extend:
- `test_shift_end_dialog_populates_events_section`
- `test_shift_end_dialog_populates_alarms_section`
- `test_shift_end_dialog_populates_temperatures_section`
- `test_shift_end_dialog_populates_experiment_progress_section`
- `test_shift_end_dialog_markdown_export_format`
- `test_shift_end_dialog_empty_shift_window_fallback_to_8h`
- `test_shift_end_dialog_saves_to_operator_log_with_tag`

### Commit message

```
shift_handover: auto-populated end-of-shift summary

Shift end dialog now auto-fills four sections before operator edit:
- События смены (phase changes, experiment lifecycle, safety events)
- Тревоги за смену (triggered + acknowledged)
- Температуры за смену (min/max per channel)
- Прогресс эксперимента (phase sequence + durations)

Shift window: ShiftStart timestamp from operator_log (tag=shift_start)
to now; falls back to last 8h if no start log.

Export:
- «Скопировать в Markdown» → clipboard
- «Отправить в Telegram» → existing bot
- «Сохранить» → operator_log with tag=shift_end + Markdown body

Engine-side: added alarm_v2_history command (time-range filter on
existing state manager history).

Legacy widget at src/cryodaq/gui/widgets/shift_handover.py — Phase II
shell rebuild deferred to future block. Extension here is in-place.

Addresses ROADMAP F11.

Tests: 7 new cases.
```

---

## Per-commit workflow

For each of 4 findings:

1. **Stage 0 recon** (5 min) per spec.
2. **Implement** per spec instructions.
3. **Pre-commit gates:**
   - `ruff check src tests` clean
   - `ruff format` new/modified files
   - Forbidden-token grep (DS v1.0.1)
   - Emoji scan (U+1F300-U+1FAFF, U+2600-U+27BF, allow `✓` only
     where spec permits)
   - Targeted tests pass
4. **Commit** with spec's message template.
5. **Push** `origin master`.
6. **`/codex`** review with focus questions:

**Commit 1 (Parquet):** pyarrow in base deps, not just extra? Archive
overlay button wired via existing worker pattern? Engine command added
to `_SLOW_COMMANDS`? QFileDialog integration correct? No breakage of
CSV / HDF5 / Excel buttons?

**Commit 3 (auto-report verify):** Templates checked? NewExperimentDialog
override exposed? LibreOffice path works on Linux? If no gaps, commit
is documentation-only?

**Commit 2 (debug mode):** resolve_log_level() priority correct (env >
QSettings > default)? Launcher propagates env var to engine subprocess?
QSettings key `FIAN/CryoDAQ` namespace consistent with other settings?
Dialog informs operator about restart requirement?

**Commit 4 (shift handover):** Four auto-sections populate correctly?
Shift window fallback to 8h works? Markdown export readable? Telegram
dispatch uses existing bot? operator_log save tagged `shift_end`?

---

## Final report format

```
=== IV.4 BATCH 0.17.0 — FINAL REPORT ===

Start: <timestamp>
End: <timestamp>
Duration: <H:MM>

Commit 1 — F1 Parquet UI export + default install:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M passing
  pyarrow in base deps: YES
  archive_export_parquet command: shipped | deferred

Commit 2 (per order 1→3→2→4, this is actual commit 3) — F6 auto-report verify:
  SHA: <sha>
  Codex verdict: PASS | DOCUMENTATION-ONLY
  Gaps found: <list or "none">
  
Commit 3 — F2 Debug mode toggle:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M passing
  Launcher → Engine env var propagation: verified

Commit 4 — F11 Shift handover enrichment:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M passing
  alarm_v2_history command: shipped | existing | deferred
  Telegram export: shipped | deferred

Repository state:
  HEAD: <sha>
  Branch: master (pushed)
  Full GUI subtree sanity: <passed>/<skipped>
  Uncommitted: config/channels.yaml (pre-existing, per Rule 7)

STOPs: <list or "none">

ROADMAP.md updates applied:
  F1: 🔧 PARTIAL → ✅ DONE (and whatever was verified)
  F2: ⬜ → ✅ DONE
  F6: ✅ DONE → ✅ DONE (verified)
  F11: 🔧 PARTIAL → ✅ DONE

Ready for tag 0.17.0: YES | NO (<reason>)
```

Update `ROADMAP.md` status table in the same commit that closes the
relevant F*. Single-line changes per F*.

---

## Out of scope

- F3, F4, F5, F7, F8, F9, F10, F12, F13, F14, F15, F16, F17, F18 —
  see ROADMAP.md.
- Alarm v2 UI redesign beyond what F11 needs (time-range query helper).
- Web API extension (F7).
- Telegram command approval (F14).
- Cross-platform packaging (F15).

---

## Cleanup

**NONE.** Per Rule 1 and architect policy. All spec files remain on
disk. Final report emission ends the block.

---

## Dependencies on other batches

- **IV.3 Finding 7 (ZMQ timeout tiering)** must land first. Commit 1
  uses `_SLOW_COMMANDS` frozenset added by IV.3. If IV.3 not closed
  at start of IV.4 — STOP.
- No dependency on IV.5 (stretch batch).
