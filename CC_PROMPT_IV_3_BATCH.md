# IV.3 — UX + tooling batch hotfix

Batch of 6 commits from Vladimir's runtime smoke review after
IV.2 close. Mix of UX polish, icon set migration, mock data
tooling, and DS rule enforcement upgrade.

**Current HEAD at authoring:** `df43081` (IV.2 closed).

**Scope:** ~1400 LOC distributed across 7 commits + 3 new tools.
~6-7h CC.

---

## ❗ Critical rules

### Rule 1 — NO file deletion, EVER
Architect policy. Claude never deletes files in this repo — not
manually, not via CC, not via codex, not in any "Stage Cleanup"
section. All spec files stay on disk. If you see any `rm` or
`git rm` or `Filesystem:delete` — **SKIP IT**. This overrides
anything else in any spec.

### Rule 2 — `/codex` is a slash command
Just type it. Do NOT search filesystem. If unknown-command
error → defer review, push commit, move on.

### Rule 3 — Model override in BOTH places
`--model gpt-5.4 --reasoning high` inline AND `Model: gpt-5.4` /
`Reasoning effort: high` as first two lines of prompt body.

### Rule 4 — Autonomy mode
Per `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`. Max 3 amend cycles per
commit. 6 STOP conditions apply.

### Rule 5 — HMI philosophy
Cognitive load is NOT a constraint. Keep dense data, explicit
numbers, visible metrics. Do NOT simplify beyond spec.

### Rule 6 — Targeted tests only
Per-commit targeted tests. Shell subtree sanity at end.

---

## Findings inventory

| # | Severity | Area | What |
|---|---|---|---|
| 1 | LOW UX | conductivity_panel.py | Replace awkward «Стабильность: выберите датчики» with muted «Прогноз» header placeholder |
| 2 | MED UX | alarm_panel.py | Unified centered empty state when both v1 + v2 tables are empty |
| 3 | LOW UX | operator_log_panel.py | Halve message input initial height; keep expanding behavior |
| 4 | MED refactor | tool_rail.py + icons/ | Migrate from Lucide SVG files to qtawesome + Phosphor Icons |
| 5 | HIGH tooling | tools/mock_scenario.py + force_phase.py + replay_session.py | Mock data tooling for analytics verification |
| 6 | MED DS quality | DS rule CI filter | Replace regex-based grep with AST-based scan for RULE-COPY-009 |
| 7 | **HIGH** | zmq_bridge.py + engine.py + experiment_overlay.py | Fix finalize/abort 2s handler timeout that cascades into full REP deadlock |

Commit order: **7 → 1 → 2 → 3 → 4 → 5 → 6**. Rationale:
finding 7 is HIGH severity (experiment lifecycle completely
broken for long-running finalize/abort) and should land first
so subsequent commits are tested against a working engine.
Then small UX fixes (quick Codex PASS warmup); icon migration;
tools; AST scan.

---

## Finding 1 — Conductivity stability header placeholder

### Symptom

Before any sensor pair is selected, the stability row renders
«Стабильность: выберите датчики · P = 0 Вт» — awkward imperative
mixed with data readout; over-explains for wasted column space.

### Fix

When no pair is selected: render a single muted «Прогноз»
header-style label (same font weight as other section titles in
this overlay, e.g. «Цепочка датчиков»), centered vertically in
the row slot previously occupied by the stability line. No
imperative text — the existing empty-state below the header
(«Здесь появится прогноз теплопроводности. Выберите пары
датчиков...» from IV.2 A.1) already gives the instructive
guidance.

When pair IS selected: restore the full stability readout (no
change to that branch).

### File

`src/cryodaq/gui/shell/overlays/conductivity_panel.py`

### Implementation

Find the stability row construction site (header strip above the
prediction table). Replace current `QLabel("Стабильность: ...")`
content-swap logic with a `QStackedWidget`:

- Index 0: muted «Прогноз» QLabel, aligned `Qt.AlignCenter`,
  font = label font (same as other section titles), color =
  `theme.MUTED_FOREGROUND`.
- Index 1: existing dual-label row (stability chip + P readout).

Swap index on pair select / deselect via
`QStackedWidget.setCurrentIndex(0 or 1)`.

Match the vertical height of existing row so layout doesn't
jump when switching states.

### Tests

`tests/gui/shell/overlays/test_conductivity_panel.py` — extend:
- `test_stability_header_shows_prognosis_label_without_pair`
- `test_stability_header_shows_readout_with_pair`
- `test_stability_header_returns_to_prognosis_on_deselect`

### Commit message

```
conductivity: replace stability imperative with Прогноз placeholder

Before pair select, the stability row read «Стабильность: выберите
датчики · P = 0 Вт» — awkward imperative mixed with a 0-valued
readout. Replace with a single muted «Прогноз» header label,
swapped via QStackedWidget. Full stability readout preserved for
the selected state.

Phase III.A empty-state convention: header text only, imperative
guidance lives in the body empty state (IV.2 A.1).

Tests: 3 new placeholder-state cases.
```

---

## Finding 2 — Alarm panel unified empty state

### Symptom

Alarm overlay shows two cards with titles «Пороговые тревоги» /
«Фазо-зависимые тревоги». Each card renders an empty table when
no alarms are active — combined with the «Нет активных алармов»
caption only under the second card, the layout reads as broken
dead space.

### Fix

When **both** v1 and v2 alarm lists are empty: hide both cards
entirely, render a single centered empty state across the full
overlay body:

```
          ⬤ (optional subtle icon)
    Нет активных тревог.
    Система отслеживает все каналы автоматически.
```

(Icon optional — can be omitted; plain text acceptable.)

When **at least one** list has entries: restore the current
two-card layout. Each card with zero entries in this state uses
a short inline empty hint («Нет пороговых тревог» / «Нет
фазо-зависимых тревог»). The large centered empty state is ONLY
shown when both are empty.

### File

`src/cryodaq/gui/shell/overlays/alarm_panel.py`

### Implementation

Wrap the two cards + stretch filler in a `QStackedWidget`:

- Index 0: unified empty state (new QWidget with centered QLabel).
- Index 1: existing two-card layout.

Toggle logic in refresh handlers (on v1 reading, on v2 poll
result):

```python
def _update_stack_state(self) -> None:
    both_empty = (
        self.get_active_v1_count() == 0
        and self.get_active_v2_count() == 0
    )
    target = 0 if both_empty else 1
    if self._body_stack.currentIndex() != target:
        self._body_stack.setCurrentIndex(target)
```

Call `_update_stack_state()` after every count change (v1
dispatch, v2 poll result, ACK reply).

Per-card inline empty hint: already exists or add a tiny
«Нет пороговых тревог» label inside each card's table area
when count=0 AND stack is on index 1 (one side has data, the
other doesn't).

### Tests

`tests/gui/shell/overlays/test_alarm_panel.py` — extend:
- `test_alarm_panel_shows_unified_empty_state_when_both_empty`
- `test_alarm_panel_shows_cards_when_only_v1_has_data`
- `test_alarm_panel_shows_cards_when_only_v2_has_data`
- `test_alarm_panel_returns_to_unified_empty_when_all_clear`
- `test_alarm_panel_inline_empty_hint_in_zero_card_when_other_has_data`

### Commit message

```
alarm_panel: unified centered empty state when both tables empty

Previously the overlay rendered two cards with their own empty
tables side-by-side, reading as broken dead space. Wrap the body
in a QStackedWidget: index 0 = unified centered «Нет активных
тревог» message; index 1 = existing two-card layout. Toggle based
on combined v1 + v2 active count.

Per-card inline «Нет <...> тревог» hint shown only when the
other card has data (asymmetric state).

Tests: 5 new empty-state transition cases.
```

---

## Finding 3 — Operator log composer height halved

### Symptom

Operator log overlay: message input `QPlainTextEdit` consumes
~1/3 of the visible area by default. Timeline below is cramped.

### Fix

Reduce initial height of `self._message_edit` from 80 to 40 px.
Keep `sizePolicy.Expanding` / `addWidget(..., stretch=1)` so
operator can still drag the vertical splitter if they want more
space — but default layout gives most of the screen to the
timeline.

### File

`src/cryodaq/gui/shell/overlays/operator_log_panel.py`

### Implementation

Single-line change:

```python
# Before:
self._message_edit.setMinimumHeight(80)

# After:
self._message_edit.setMinimumHeight(40)
```

Keep everything else: `setMaximumBlockCount(2000)`, placeholder,
styling, `addWidget(self._message_edit, stretch=1)`.

### Tests

`tests/gui/shell/overlays/test_operator_log_panel.py` — extend:
- `test_composer_message_edit_minimum_height_is_40`
- `test_composer_message_edit_remains_expandable` — verify
  sizePolicy.Expanding still in place (regression guard)

### Commit message

```
operator_log: halve composer default height

Composer message input was claiming ~1/3 of the overlay by
default; timeline below was cramped. Reduce minimum height from
80 to 40 px. Expanding sizePolicy preserved — operator can still
drag the splitter if they need more composition space.

Tests: 2 new layout assertions.
```

---

## Finding 4 — Icon migration to Phosphor via qtawesome

### Symptom

Current ToolRail uses Lucide SVG files (10 icons under
`src/cryodaq/gui/resources/icons/`) with a custom `_colored_icon`
helper that substitutes `stroke="currentColor"` at load time.
Vladimir wants Phosphor — same structural style, more coverage,
and access via qtawesome means runtime font-based rendering
without having to ship SVG files.

### Dependency change

Add `qtawesome>=1.4` to `pyproject.toml` runtime dependencies.
Already installed in Vladimir's venv (`qtawesome-1.4.2`,
`qtpy-2.4.3`). Do NOT remove the existing SVG files — keep as
fallback; migration is additive.

### File changes

- `pyproject.toml` — add `qtawesome>=1.4` to `[project] dependencies`.
- `src/cryodaq/gui/shell/tool_rail.py` — replace icon loading
  mechanism.
- `src/cryodaq/gui/resources/icons/` — LEAVE AS-IS (do NOT
  delete any SVG file; keep as reference/fallback).

### Implementation

In `tool_rail.py`:

```python
import qtawesome as qta

# Canonical icon names. All Phosphor regular weight, standard
# stroke width. Map Vladimir-approved from architect memory:
_ICONS: dict[str, str] = {
    "home":            "ph.house",
    "new_experiment":  "ph.plus-circle",
    "experiment":      "ph.flask",
    "source":          "ph.lightning",
    "analytics":       "ph.chart-line-up",
    "conductivity":    "ph.thermometer-simple",
    "alarms":          "ph.bell-simple",
    "log":             "ph.note-pencil",
    "instruments":     "ph.cpu",
    "more":            "ph.dots-three",
}


@lru_cache(maxsize=128)
def _phosphor_icon(name: str, color: str, size: int) -> QIcon:
    """Render a Phosphor icon at the specified color + pixel size.
    
    Cached by (name, color, size) tuple — calling with new colors
    (theme switch) produces a fresh icon; repeated calls for the
    same color return the cached instance.
    """
    return qta.icon(name, color=color)
```

Replace `_colored_icon(svg_path_str, color, size)` usage in
`ToolRailButton._paint_or_set_icon` with `_phosphor_icon(name, color, size)`.

The qtawesome `qta.icon()` already supports QSize in
`QIcon.pixmap(QSize)` calls — Qt scales appropriately. No need
for custom QSvgRenderer.

**Theme awareness:** qtawesome icon cache must be invalidated
on theme switch. The `_phosphor_icon` lru_cache is keyed on color,
so new theme = new color = new cache entry. Old cache entries
accumulate but stay under 128 via lru eviction. Acceptable.

**Fallback to SVG:** keep existing `_colored_icon` helper as
dead code for one iteration — may be useful for custom icons
not in Phosphor later. DO NOT DELETE the function or the SVG
files. Mark them as "unused for now, retained for fallback"
in a docstring comment.

### Tests

`tests/gui/shell/test_tool_rail.py` — extend:
- `test_tool_rail_uses_phosphor_icon_names` — import qtawesome,
  verify icons dict maps slot names to `ph.*` strings.
- `test_tool_rail_icon_color_follows_theme_foreground` — render
  icon, verify it calls qta with `theme.FOREGROUND` as color.
- `test_tool_rail_icon_uncached_on_different_color` — calling
  twice with different colors produces different cache entries.
- Preserve existing test: SVG path existence tests should either
  be removed (if purely about SVG loading) or updated to
  reflect the new qtawesome-first flow.

Minimum: 3 new cases, keep existing coverage for non-icon
behavior (shortcuts, active state, etc.).

### Commit message

```
tool_rail: migrate to Phosphor icons via qtawesome

Replace Lucide SVG file loading with qtawesome + Phosphor icon
font (ph.* namespace). Runtime-colored, theme-aware, 1200+ icons
available vs. 10 SVG files previously.

SVG files and _colored_icon helper retained for fallback — not
deleted, marked as reserve.

Icon mapping (architect-approved):
  home → ph.house                    (Дашборд)
  new_experiment → ph.plus-circle    (Новый экспт)
  experiment → ph.flask              (Эксперимент)
  source → ph.lightning              (Keithley)
  analytics → ph.chart-line-up       (Аналитика)
  conductivity → ph.thermometer-simple (Теплопров.)
  alarms → ph.bell-simple            (Тревоги)
  log → ph.note-pencil               (Журнал)
  instruments → ph.cpu               (Приборы)
  more → ph.dots-three               (Ещё)

Dependency: qtawesome>=1.4 added to pyproject.toml. Already in
Vladimir's venv.

Tests: 3 new + preserved.
```

---

## Finding 5 — Mock data tooling for analytics verification

### Symptom

No way to exercise Analytics phase-aware layouts in isolation or
with plausible data. Architect wants to validate III.C rebuild
visually.

### Scope

Three standalone tools in `tools/` (next to `theme_previewer.py`):

**5A. `tools/mock_scenario.py` — scenario publisher.**

Publishes synthetic `Reading` objects to ZMQ PUB port 5555
following named scenarios. Replaces or augments whatever the
current `cryodaq.engine --mock` publishes.

```
python -m tools.mock_scenario --scenario vacuum --duration 60
python -m tools.mock_scenario --scenario cooldown --duration 600
python -m tools.mock_scenario --scenario measurement --duration 300
python -m tools.mock_scenario --scenario cooldown_with_prediction \
    --ci-level 67
```

Scenarios:
- `vacuum` — pressure decay from 1e-3 to 1e-7 mbar exponential over
  duration; temperatures stable at 290 K.
- `cooldown` — temperatures decay 290 → 4 K following a
  tanh-smoothed curve; pressure stable at 1e-6.
- `measurement` — R_thermal around 1.5e-3 K/W with 5% noise;
  temperatures stable at 4 K; Keithley power stable at 0.5 W.
- `warmup` — mirror of cooldown, 4 → 290 K.
- `cooldown_with_prediction` — same as cooldown but also publishes
  `analytics/cooldown_prediction` readings with central + lower_ci
  + upper_ci values.

**Decoupling:** runs as a standalone process. Does NOT need the
engine running. Publishes direct to port 5555 (if engine running,
will compete — document «stop engine first»). GUI connects to
5555 and will pick up the synthetic data.

Output: `--dry-run` mode prints first 10 readings without binding
port; `--verbose` logs all publishes.

**5B. `tools/force_phase.py` — phase advancement CLI.**

Pushes phase transitions via engine REQ port 5556:

```
python -m tools.force_phase preparation
python -m tools.force_phase vacuum
python -m tools.force_phase cooldown
python -m tools.force_phase measurement
python -m tools.force_phase warmup
python -m tools.force_phase disassembly
```

Requires engine running (uses existing engine command channel).
Dispatches `{"cmd": "experiment_advance_phase", "target": "<name>"}`
via ZMQ REQ socket.

This is distinct from 5A — 5A publishes fake readings, 5B
actually pokes the engine's real state machine. Combined, they
let architect see phase-aware AnalyticsView swap layouts while
synthetic data streams.

**5C. `tools/replay_session.py` — SQLite session replay.**

Reads readings from an existing SQLite database file, publishes
them to port 5555 with accelerated timebase:

```
python -m tools.replay_session --db data/data_2026-04-17.db --speed 10
python -m tools.replay_session --db data/data_2026-04-17.db \
    --speed 100 --channels T1,T2,pressure
python -m tools.replay_session --db data/data_2026-04-17.db \
    --start-offset 3600 --duration 1800
```

Flags:
- `--db <path>` — required, path to SQLite file (read-only).
- `--speed <multiplier>` — playback rate (default 10).
- `--channels <comma-list>` — filter to specific channels (optional).
- `--start-offset <seconds>` — skip first N seconds of recorded session.
- `--duration <seconds>` — replay only first N seconds of session.
- `--loop` — restart from beginning after reaching end.

Reads `readings` table (or equivalent — confirm schema in Stage 0).
Preserves original channel names, metadata, and relative timing.
Dispatches via ZMQ PUB port 5555.

### Files (new)

- `tools/mock_scenario.py`
- `tools/force_phase.py`
- `tools/replay_session.py`
- `tests/tools/test_mock_scenario.py`
- `tests/tools/test_force_phase.py`
- `tests/tools/test_replay_session.py`

### Stage 0 recon

Before implementation:
- Read `src/cryodaq/drivers/base.py` for `Reading` dataclass shape.
- Read `src/cryodaq/engine.py` — grep for current mock-mode
  publisher logic (if exists). Use same ZMQ topic format.
- Read `src/cryodaq/core/database.py` or similar for SQLite
  readings table schema.
- Read `src/cryodaq/core/experiment.py` for phase names
  (`preparation` / `vacuum` / `cooldown` / `measurement` /
  `warmup` / `disassembly` are canonical — verify).

### Implementation notes

- All three tools share a common ZMQ publisher helper — factor
  into `tools/_zmq_helpers.py` if DRY makes sense.
- Each tool has `__main__` entry point (runnable via
  `python -m tools.<name>`).
- `argparse` for CLI, NOT click or typer (project baseline).
- Russian help strings — consistent with operator-facing tooling
  convention.
- Rich `--help` output with example invocations.

### Tests

Per tool — minimum coverage:

**mock_scenario.py:**
- Scenario generators produce expected value ranges.
- `vacuum` scenario: first pressure >= 1e-3, last <= 1e-7.
- `cooldown`: first T == 290, last T in [3.9, 4.1].
- `cooldown_with_prediction`: publishes both `temperature/T*`
  and `analytics/cooldown_prediction` channels.
- CLI parsing: `--scenario`, `--duration`, `--dry-run`.

**force_phase.py:**
- Valid phase names accepted; invalid rejected.
- Dispatches correct cmd shape.
- Handles engine timeout gracefully (returns non-zero exit).

**replay_session.py:**
- Reads SQLite schema correctly.
- `--speed 10` replays 10× faster (verify timing of publishes).
- `--channels` filter applied.
- `--loop` restarts from beginning.

### Commit message

```
tools: mock_scenario, force_phase, replay_session for analytics QA

Three CLI tools for exercising analytics phase-aware layouts:

- tools/mock_scenario.py — publishes synthetic readings following
  named scenarios (vacuum, cooldown, measurement, warmup,
  cooldown_with_prediction). Direct ZMQ PUB to port 5555, works
  without engine.
- tools/force_phase.py — pokes engine state machine via REQ port
  5556 to force phase transitions. Lets operator verify layout
  swaps in phase-aware views (III.C).
- tools/replay_session.py — replays an existing SQLite database
  with accelerated timebase. Useful for exercising analytics
  against real historical data.

Combined, they give architect a full test harness for analytics
verification without waiting for real lab cycles.

Tests: ~25 cases across 3 test files.
```

---

## Finding 6 — AST-based DS rule scan (replaces regex)

### Symptom

IV.2 B.3 landed regex-based CI grep for RULE-COPY-009 (no
internal versioning in UI) but Codex flagged a residual gap:
snake_case identifier literals like `"keithley_v3"` or
`"lakeshore_legacy"` in operator-facing surfaces (QComboBox
items, setText calls) would evade the `_IDENTIFIER_LIKE` filter.

### Fix

Replace the regex-based CI grep with an AST-based scanner that
walks Python source trees and inspects string literals passed to
known operator-facing Qt methods:

- `QLabel.setText()`
- `QLineEdit.setPlaceholderText()`
- `QAbstractButton.setText()` (QPushButton, QToolButton,
  QRadioButton, QCheckBox)
- `QComboBox.addItem()`, `addItems()`
- `QTableWidgetItem.setText()`, constructor arg
- `QHeaderView.setLabels()` / `setHorizontalHeaderLabels()`
- `QAction.setText()`
- `QMenu.setTitle()`, `addAction()`
- `setToolTip()`, `setWindowTitle()`, `setStatusTip()`, `setWhatsThis()`

### Implementation

New file: `tests/design_system/test_no_internal_versioning_ast.py`

```python
"""AST-based enforcement of RULE-COPY-009 (no internal versioning
in operator-facing text).

Walks all Python files under src/cryodaq/gui/ and flags any string
literal passed to a known operator-facing Qt method if the string
matches forbidden patterns (v1/v2/legacy/etc.).

More precise than grep: catches cases where the forbidden word
appears inside setText() args regardless of quoting style, f-string
interpolation, or .format() placeholders. Does NOT flag internal
variable names, imports, docstrings, or comments.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_GUI_ROOT = Path(__file__).parent.parent.parent / "src" / "cryodaq" / "gui"

# Methods that emit strings to operator-visible UI surfaces.
# Module-qualified methods tracked via attribute access patterns.
_OPERATOR_FACING_METHODS: set[str] = {
    "setText",
    "setPlaceholderText",
    "setToolTip",
    "setWindowTitle",
    "setStatusTip",
    "setWhatsThis",
    "setTitle",
    "addItem",
    "addItems",
    "setLabels",
    "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels",
}

# Forbidden patterns in operator text. Case-insensitive match.
_FORBIDDEN_PATTERN = re.compile(
    r'\b(v[0-9]+|legacy|deprecated|experimental|beta|alpha|'
    r'новая версия|старая версия|устар[а-я]*)\b',
    re.IGNORECASE,
)


class _OperatorTextVisitor(ast.NodeVisitor):
    """Collect string literals passed to operator-facing methods."""
    
    def __init__(self, path: Path):
        self._path = path
        self.violations: list[tuple[int, str, str]] = []  # (line, method, snippet)
    
    def visit_Call(self, node: ast.Call) -> None:
        method_name = self._extract_method_name(node.func)
        if method_name in _OPERATOR_FACING_METHODS:
            for arg in node.args:
                self._check_arg(node, method_name, arg)
            for kw in node.keywords:
                self._check_arg(node, method_name, kw.value)
        self.generic_visit(node)
    
    def _extract_method_name(self, func_node: ast.expr) -> str | None:
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None
    
    def _check_arg(self, call_node: ast.Call, method: str,
                   arg: ast.expr) -> None:
        text = self._extract_string(arg)
        if text is None:
            return
        if _FORBIDDEN_PATTERN.search(text):
            snippet = text[:60] + ("..." if len(text) > 60 else "")
            self.violations.append((call_node.lineno, method, snippet))
    
    def _extract_string(self, node: ast.expr) -> str | None:
        """Extract string from Constant, JoinedStr (f-string), or
        BinOp + concatenation."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            # f-string: collect all str constant parts
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                # Don't recurse into FormattedValue expressions
            return "".join(parts) if parts else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._extract_string(node.left) or ""
            right = self._extract_string(node.right) or ""
            combined = left + right
            return combined if combined else None
        return None


def _collect_violations(path: Path) -> list[tuple[Path, int, str, str]]:
    violations: list[tuple[Path, int, str, str]] = []
    for py_file in path.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        visitor = _OperatorTextVisitor(py_file)
        visitor.visit(tree)
        for line, method, snippet in visitor.violations:
            violations.append((py_file, line, method, snippet))
    return violations


def test_no_internal_versioning_in_operator_text():
    """RULE-COPY-009: operator-facing text MUST NOT contain
    internal versioning vocabulary (v1/v2/legacy/deprecated/etc.).
    
    AST-based scan is more precise than grep — catches violations
    in setText() / addItem() args regardless of string quoting,
    f-strings, concatenation, or identifier-like shape.
    """
    violations = _collect_violations(_GUI_ROOT)
    if violations:
        report = "\n".join(
            f"  {path.relative_to(_GUI_ROOT.parent.parent.parent)}:"
            f"{line} — {method}(): {snippet!r}"
            for path, line, method, snippet in violations
        )
        pytest.fail(
            f"\nRULE-COPY-009 violations — internal versioning "
            f"in operator text:\n{report}"
        )
```

### Migration plan

1. Write the new AST-based test (above).
2. Verify it passes on current HEAD (IV.2 closed, tree should
   be clean).
3. In the same commit, replace or deprecate the existing regex
   grep test. If the old test is still useful for non-AST cases
   (e.g. markdown / YAML files), keep it; otherwise remove.
4. Update `docs/design-system/rules/content-voice-rules.md` —
   RULE-COPY-009 text should reference the AST test as primary
   enforcement.

### Stage 0

- Locate current regex-based test: `tests/design_system/test_*.py`,
  grep for `_IDENTIFIER_LIKE` or `RULE-COPY-009`.
- Decide: replace in-place or add new test + remove old?
  Recommend ADD new, mark old as deprecated or remove it if
  clearly superseded.

### Tests

Self-test the AST visitor:

- `test_ast_detects_v1_in_setText`
- `test_ast_detects_v2_in_addItem`
- `test_ast_detects_legacy_in_placeholder`
- `test_ast_does_not_flag_docstrings`
- `test_ast_does_not_flag_variable_names`
- `test_ast_handles_fstrings`
- `test_ast_handles_string_concatenation`

Plus the main test that scans the real `src/cryodaq/gui/` tree —
should pass (no violations on current HEAD).

### Commit message

```
ds: AST-based scanner for RULE-COPY-009 enforcement

Replace regex-based grep filter (IV.2 B.3 STOP residual) with
AST walker. Visits every ast.Call node, extracts method name,
and checks string literal args against forbidden-versioning
pattern if method is operator-facing (setText, addItem,
setPlaceholderText, etc.).

More precise than grep:
- Catches violations regardless of string quoting style
- Handles f-strings, concatenation, multi-line strings
- Does NOT flag docstrings, variable names, imports, comments
- Close Codex-flagged residual gap (identifier-like literals)

Extends tests/design_system/ with ast-based test + 7 self-check
unit cases for the visitor itself.

Supersedes IV.2 B.3 regex filter — retained as legacy until
test_no_internal_versioning_ast stabilizes.
```

---

## Finding 7 — Experiment finalize/abort 2s timeout + REP wedge (HIGH)

### Symptom

From Vladimir's smoke session (runtime log):

```
23:48:41 WARNING experiment_overlay │ finalize/abort failed: handler timeout (2s)
23:48:56 WARNING experiment_overlay │ finalize/abort failed: handler timeout (2s)
23:49:05 WARNING zmq_client       │ REP timeout on safety_status (EAGAIN)
23:49:08 WARNING zmq_client       │ REP timeout on alarm_v2_status (EAGAIN)
[…cascade of all REP commands timing out…]
```

Clicking «Завершить эксперимент» or «Прервать» makes the
command handler in engine time out at 2s. Because the handler
did NOT complete in time, the engine-side `experiment_finalize`
still runs to completion internally (SQLite writes + report
generation can take 3-10s), but by then the REQ/REP exchange is
lost. Worse, the cascading REP timeouts after that indicate
REP socket gets into an inconsistent state and all subsequent
commands also time out.

This is the **second manifestation** of the same architectural
fragility that caused the theme-switch bug (IV.1 commit 1):
any REQ timeout without a matching reply leaves REP wedged.

### Root cause

`cryodaq.core.zmq_bridge.ZMQCommandServer._run_handler()` enforces
a hardcoded 2.0s envelope on every command. Fast commands
(status queries) never hit it. Slow commands (finalize with
report generation, abort with data flush, experiment_create
with template instantiation) routinely exceed 2s and get
cancelled.

The comment in `engine.py` even admits this:

```python
# REP is still protected by the outer 2.0s handler
# timeout envelope in ZMQCommandServer._run_handler(); this
# inner 1.5s wrapper only gives faster client feedback and
# frees the REP loop earlier.
```

Two bugs interact:

**Bug A: 2s is wrong for finalize/abort/create.**
`experiment_finalize` triggers SQLite writes, operator log entry,
and report generation in `ExperimentManager.finalize_experiment()`.
Report generation alone (DOCX + PDF with matplotlib charts) is
easily 3-8s.

**Bug B: REP wedge after timeout.**
When handler times out, the engine sends no reply. ZMQ REP state
machine expects exactly one `send()` per `recv()`. Without the
send, the next REQ gets queued; when the slow handler EVENTUALLY
sends, it is out of order. With `REQ_CORRELATE=1` + `REQ_RELAXED=1`
on the REQ side, subprocess recovers. But the engine-side REP
socket has no equivalent safety valve — it stays in "expecting
send" state and rejects all subsequent REQs.

### Fix

Two-layer fix. Apply both.

**Layer 1: increase handler timeout envelope to 30s (per-command
tiered, not flat).**

In `src/cryodaq/core/zmq_bridge.py::ZMQCommandServer`:

```python
# Before: flat _HANDLER_TIMEOUT_S = 2.0

# After: per-command tiered.
# Status queries must stay fast; long-running state transitions
# get 30s to complete finalize + report generation.
_HANDLER_TIMEOUT_FAST_S = 2.0  # status, polls, lookups
_HANDLER_TIMEOUT_SLOW_S = 30.0  # finalize, abort, create, import

_SLOW_COMMANDS = frozenset({
    "experiment_finalize",
    "experiment_stop",
    "experiment_abort",
    "experiment_create",
    "experiment_start",
    "experiment_create_retroactive",
    "experiment_generate_report",
    "calibration_curve_import",
    "calibration_curve_export",
    "calibration_v2_fit",
    "calibration_v2_extract",
})


def _timeout_for(cmd: dict) -> float:
    action = cmd.get("cmd", "") if isinstance(cmd, dict) else ""
    return _HANDLER_TIMEOUT_SLOW_S if action in _SLOW_COMMANDS else _HANDLER_TIMEOUT_FAST_S
```

Apply this in `_run_handler()` / `_dispatch()` where the timeout
is currently looked up. Architect's Stage 0 reading of
`zmq_bridge.py` will confirm exact method name.

**Corresponding client-side adjustments:**

- `cryodaq.gui.zmq_client.ZmqBridge._CMD_REPLY_TIMEOUT_S` —
  bump from 5.0 to 35.0 (greater than server 30s ceiling so
  client always waits for server's own cap).
- `cryodaq.core.zmq_subprocess.cmd_forward_loop` REQ RCVTIMEO /
  SNDTIMEO — bump from 3000 to 35000 for consistency.

These are blunt constants, not per-command. Client waits as
long as the server's own ceiling; REP wedge protection below
is the real fix.

**Layer 2: REP wedge protection.**

Even with a 30s ceiling, a truly stuck handler (bug, deadlock,
watchdog-killed worker) still leaves REP wedged. Protect REP
the same way IV.1 protected the theme-switch path: **always
send a reply, even on timeout.**

In `ZMQCommandServer._run_handler()`:

```python
async def _run_handler(self, cmd: dict) -> dict:
    timeout = _timeout_for(cmd)
    try:
        return await asyncio.wait_for(self._handler(cmd), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            "Handler for %r timed out after %.1fs; "
            "sending error reply to unwedge REP.",
            cmd.get("cmd"),
            timeout,
        )
        return {
            "ok": False,
            "error": f"Handler timeout ({timeout:g}s); operation may still be running.",
            "_handler_timeout": True,
        }
    except Exception as exc:
        logger.exception("Handler error for %r", cmd.get("cmd"))
        return {"ok": False, "error": str(exc)}
```

The key insight: return the error reply via `return`, so the
caller (the REP loop in the server) sends it over the socket.
REP state machine gets its expected send(), is ready for next
recv(), no wedge.

This is a **structural fix**, not a bandaid. Even if some
future handler takes 5 minutes, REP still responds to pings
because the timeout + reply path is guaranteed.

**Optional Layer 3: background task for slow handlers.**

For truly long operations (report generation that can hit 10-30s),
consider making them fire-and-forget tasks with status polling:

- `experiment_finalize` returns `{ok: True, task_id: "…"}` immediately
- Client polls `{cmd: "task_status", id: "…"}` for progress

**Out of scope for IV.3.** This is the "correct" architecture
but a larger refactor. Document as residual / future work.
IV.3 Finding 7 does Layer 1 + Layer 2 only.

### Files

- `src/cryodaq/core/zmq_bridge.py` — main fix (timeout tiering + unwedge)
- `src/cryodaq/gui/zmq_client.py` — client timeout bump
- `src/cryodaq/core/zmq_subprocess.py` — subprocess REQ timeout bump
- `tests/core/test_zmq_bridge.py` — new coverage

### Stage 0 recon (mandatory)

Before writing code:

```bash
# Find current _run_handler + timeout constant
grep -n "_HANDLER_TIMEOUT\|_run_handler\|asyncio.wait_for" src/cryodaq/core/zmq_bridge.py

# Confirm REQ timeouts in subprocess
grep -n "RCVTIMEO\|SNDTIMEO" src/cryodaq/core/zmq_subprocess.py

# Confirm client future timeout  
grep -n "_CMD_REPLY_TIMEOUT_S\|future.result" src/cryodaq/gui/zmq_client.py
```

### Tests

`tests/core/test_zmq_bridge.py` — add:

- `test_handler_timeout_returns_error_reply_not_silence` —
  mock handler that sleeps 5s, verify server returns reply
  dict (ok=False, _handler_timeout=True) rather than letting
  REP hang.
- `test_handler_timeout_fast_command_uses_2s` — verify
  `cmd=safety_status` uses 2s timeout.
- `test_handler_timeout_slow_command_uses_30s` — verify
  `cmd=experiment_finalize` uses 30s timeout.
- `test_handler_after_timeout_next_request_works` — send
  slow cmd that times out, then send fast cmd, verify it
  gets a reply (REP not wedged).
- `test_handler_exception_returns_error_reply` — handler
  raises, verify server still sends reply.

`tests/gui/test_zmq_client.py` — add or update:

- `test_client_waits_beyond_fast_timeout_for_slow_commands` —
  not needed since client is agnostic to server timeout, but
  verify `_CMD_REPLY_TIMEOUT_S == 35.0` is applied (simple constant check).

### Commit message

```
zmq_bridge: tier handler timeout + always reply to prevent REP wedge

The 2s flat handler timeout in ZMQCommandServer was wrong for
stateful commands: experiment_finalize / experiment_abort /
experiment_create / calibration_curve_import etc. routinely
exceed 2s. When they time out, server sends no reply. ZMQ REP
state machine requires send() per recv(), so the next REQ gets
wedged. Cascade: all subsequent commands time out.

Two-layer fix:

1. Tiered timeout. Fast commands (status queries) keep 2s.
   Slow commands (stateful transitions) get 30s. _SLOW_COMMANDS
   enumerates the known-slow set.

2. REP wedge protection. _run_handler now ALWAYS returns a
   dict, even on timeout or exception. The server's send()
   happens unconditionally, REP stays unstuck, subsequent
   commands continue to work.

Client-side (gui/zmq_client) _CMD_REPLY_TIMEOUT_S bumped
from 5.0 to 35.0 — greater than server's 30s ceiling so the
client always waits for the server's own cap. Subprocess
REQ RCVTIMEO/SNDTIMEO bumped from 3s to 35s for consistency.

Residual: very long operations (report generation > 30s) still
would time out. Future follow-up: background-task pattern with
polling task_status. Out of scope for IV.3.

Tests: 5 new cases in test_zmq_bridge covering timeout reply,
fast/slow tiers, and non-wedge-after-timeout.

Closes: experiment finalize/abort deadlock from architect's
smoke session 2026-04-19 23:48.
```

---

## Per-commit workflow

For each of 7 findings in order (7 first):

1. Stage 0 recon (5 min).
2. Implement per spec.
3. Pre-commit gates:
   - `ruff check src tests` clean
   - `ruff format` new/modified files
   - Forbidden-token grep (DS v1.0.1)
   - Emoji scan
   - Targeted tests pass
4. Commit with spec's message template.
5. Push `origin master`.
6. `/codex` review with focus questions:

**Commit 7 (zmq timeout + REP unwedge):** _SLOW_COMMANDS list
complete (all experiment_* lifecycle + calibration import/export/
fit)? `_run_handler` ALWAYS returns dict (try/except/finally
covers all paths)? Client _CMD_REPLY_TIMEOUT_S bumped to 35?
Subprocess REQ RCVTIMEO/SNDTIMEO bumped? 5 new tests cover
reply-on-timeout, fast/slow tiers, and post-timeout command
works? No risk of silent swallow of exceptions?

**Commit 1 (conductivity Прогноз):** QStackedWidget swap
logic correct? Muted «Прогноз» font matches section title
weight? State transitions (select → deselect → select) covered?

**Commit 2 (alarm empty):** QStackedWidget transitions cover
4 state combinations (both empty, v1 only, v2 only, both have
data)? Inline per-card empty hints only show when other has
data? Centered message styled correctly (MUTED_FOREGROUND,
no hardcoded colors)?

**Commit 3 (operator log height):** 40px value applied?
sizePolicy.Expanding preserved? No regression in composer
disabled/enabled behavior?

**Commit 4 (Phosphor icons):** All 10 ToolRail slots mapped?
pyproject.toml has qtawesome>=1.4? lru_cache key includes
color (theme-switch correctness)? Old SVG files and
_colored_icon helper NOT deleted (fallback preserved)? Icon
size matches existing 24px?

**Commit 5 (mock tools):** 3 tools in `tools/`? argparse (not
click)? Each runnable as `python -m tools.<name>`? Russian
help strings? Scenarios produce expected value ranges?
force_phase uses correct REQ port 5556? replay_session reads
SQLite schema correctly?

**Commit 6 (AST scan):** AST visitor handles Constant, JoinedStr,
BinOp (concatenation)? 7 unit tests for visitor pass? Full scan
on src/cryodaq/gui/ passes on current HEAD (no false positives)?
Docs updated to reference AST test as primary RULE-COPY-009
enforcement?

---

## Final report format

```
=== IV.3 BATCH UX + TOOLING — FINAL REPORT ===

Start: <timestamp>
End: <timestamp>
Duration: <H:MM>

Commit 1 — conductivity Прогноз placeholder:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M targeted passing

Commit 2 — alarm unified empty state:
  [same]

Commit 3 — operator log composer height:
  [same]

Commit 4 — ToolRail Phosphor migration:
  [same]

Commit 5 — mock tooling (mock_scenario + force_phase + replay_session):
  [same]

Commit 6 — AST-based RULE-COPY-009 scanner:
  [same]

Repository state:
  HEAD: <sha>
  Branch: master (pushed)
  GUI subtree sanity: <passed>/<skipped>
  Tools subtree: <passed>/<skipped>
  Modified-but-uncommitted: <list or "config/channels.yaml only,
    pre-existing">
  
STOPs: <list or "none">

Spec files (retained per architect policy):
  - CC_PROMPT_IV_3_BATCH.md (this spec)
  - CC_PROMPT_IV_2_ORCHESTRATOR.md (reference)
  
No files deleted.

Next action items for architect:
  <residual risks, deferred items>
```

---

## Out of scope

- Engine-side changes.
- Analytics placeholder widget data wiring (separate block).
- Lazy-open snapshot replay for AnalyticsView (separate block).
- Dashboard pressure autorange (closed in IV.1).
- Full alarm v1/v2 card redesign (beyond empty-state fix).
- Custom Phosphor icon subset (full library available via qta).
- IV.2 deferred findings that were already closed.

---

## Cleanup

**NONE.** No files deleted. Architect has sole authority.
Final report emission ends the block.
