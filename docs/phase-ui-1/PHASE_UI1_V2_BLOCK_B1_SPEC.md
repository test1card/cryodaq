# Phase UI-1 v2 — Block B.1: DashboardView skeleton

## Context

Phase UI-1 v2 foundation (Blocks A through A.9) is **finalized**. The
shell — TopWatchBar, ToolRail, BottomStatusBar, OverlayContainer,
MainWindowV2 — works correctly. The current dashboard slot in
`OverlayContainer` is filled by the legacy `OverviewPanel` from
`src/cryodaq/gui/widgets/overview_panel.py` which Block B will replace.

**Block B is split into 7 sub-blocks** to allow visual review between
each step. This is **B.1, the first sub-block** — pure scaffold, no
content yet. After B.1 you will see a **skeleton** of the new dashboard:
five labeled placeholder zones in their final positions, with grey
borders and labels saying "[ZONE NAME — coming in B.x]". This is
intentionally not pretty — it's the structural foundation for B.2-B.7
to fill in.

**Strategy:** full replace with new directory `src/cryodaq/gui/dashboard/`.
The legacy `OverviewPanel` and its 5 dead-code child classes
(`StatusStrip`, `CompactTempCard`, `TempCardGrid`, `KeithleyStrip`,
`ExperimentStatusWidget`, `QuickLogWidget`) all live in
`overview_panel.py` and will be deleted in **B.7** as a single
`git rm` operation, after the new dashboard is fully built and verified.

## Branch and baseline

- Branch: `feat/ui-phase-1-v2` (continue from current HEAD)
- Last commit: `ui(phase-1-v2): block A.9 — orphan widget stubs + Codex finding fixes`
- Baseline tests: **840 passed, 6 skipped**

## Russian language hard rule

All operator-facing text in this spec is Russian. Placeholder zone
labels in this skeleton block are also Russian (they will be replaced
in B.2-B.7 anyway). Technical exceptions: `Engine`, `Telegram`, `SMU`,
`Keithley`, `LakeShore`, `GPIB`. Any new English string is a defect.

## Anti-pattern reminders

Apply checklist `docs/SPEC_AUTHORING_CHECKLIST.md` to all new widgets:

- **QSS selectors**: use `setObjectName("name") + "#name { ... }"`,
  never `ClassName { ... }`. Qt matches C++ class names only.
- **Child widget backgrounds**: parent owns the background; children
  must be transparent. Do not write `QWidget { background: ... }` —
  it cascades to all child QLabel / QFrame / etc and creates seams.
  Use `#parentObjectName` selector instead.
- **No `QTimer.singleShot` in `__init__`**: any timer must be a
  parented `QTimer` instance with explicit lifetime.
- **No `ZmqCommandWorker` in widget `__init__`**: B.1 has no data flow
  yet, so no workers are needed at all. Workers will appear in B.2+.
- **No `setVisible(True)` self-calls**: child widgets must not unhide
  themselves on data arrival. B.1 has no data arrival yet so this is
  not relevant, but apply when B.2+ adds data routing.

---

## Goal

Create a new `DashboardView` widget that replaces `OverviewPanel` in
the `OverlayContainer` "home" slot. The new widget contains **five
vertically stacked placeholder zones** representing the future dashboard
content:

1. **Phase-aware zone** (top, ~14% height) — placeholder for the
   PhaseAwareWidget which will show context-dependent content based on
   experiment phase. Coming in B.4-B.5.
2. **Temperature plot zone** (~38% height) — placeholder for the main
   multi-channel temperature plot with time window picker. Coming in B.2.
3. **Pressure plot zone** (~14% height) — placeholder for the compact
   log-Y pressure plot synchronized with temperature plot. Coming in B.2.
4. **Sensor grid zone** (~30% height) — placeholder for the
   DynamicSensorGrid with auto-pack visible channels. Coming in B.3.
5. **Quick log zone** (~4% height collapsed) — placeholder for the
   collapsible quick log block. Coming in B.6.

Each zone is a `QFrame` with:
- Bordered outline (1px `theme.BORDER_SUBTLE`)
- Centered Russian label `[НАЗВАНИЕ ЗОНЫ — будет в B.x]`
- Vertical layout slot inside for future content

After B.1 you launch CryoDAQ → see five labeled grey rectangles in the
dashboard area. Tool rail, watch bar, and bottom bar all still work
identically because B.1 only swaps the dashboard widget.

---

## Tasks

### Task 1 — Create new dashboard directory

Create new directory and `__init__.py`:

```
src/cryodaq/gui/dashboard/
├── __init__.py          # exports DashboardView
└── dashboard_view.py    # the new widget
```

Tests directory:

```
tests/gui/dashboard/
├── __init__.py
└── test_dashboard_view.py  # smoke tests
```

### Task 2 — Implement DashboardView

**File:** `src/cryodaq/gui/dashboard/dashboard_view.py`

#### Constructor signature

```python
class DashboardView(QWidget):
    """Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

    Currently a skeleton with five placeholder zones. Each zone will
    be filled by subsequent Block B sub-blocks:
    - Phase-aware zone: B.4-B.5
    - Temperature plot zone: B.2
    - Pressure plot zone: B.2
    - Sensor grid zone: B.3
    - Quick log zone: B.6
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._build_ui()
```

The `channel_manager` parameter mirrors how `OverviewPanel.__init__`
accepts it — needed by future sub-blocks (B.3 sensor grid). For B.1
just store it and don't use it yet.

#### Layout

Use `QVBoxLayout` as root, contentsMargins `(theme.SPACE_2,
theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)`, spacing `theme.SPACE_2`.

Five `QFrame` zones, each created via a helper method
`_make_zone(name: str, label: str) -> QFrame`. Each zone:

- `QFrame` with object name set via `setObjectName(name)` (e.g. "phaseZone")
- Stylesheet via the `#objectName` selector pattern:
  ```python
  zone.setStyleSheet(
      f"#{name} {{ "
      f"background-color: {theme.SURFACE_CARD}; "
      f"border: 1px solid {theme.BORDER_SUBTLE}; "
      f"border-radius: {theme.RADIUS_MD}px; "
      f"}}"
  )
  ```
- Inside: `QVBoxLayout` with one centered `QLabel(label)` styled
  `text.muted`, font `theme.FONT_LABEL_MD`, alignment center

Stretch factors when adding to root layout (using `addWidget(zone,
stretch=N)`):

| Zone | objectName | label text | Stretch |
|---|---|---|---|
| Phase-aware | `phaseZone` | `[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]` | 14 |
| Temperature plot | `tempPlotZone` | `[ГРАФИК ТЕМПЕРАТУР — будет в B.2]` | 38 |
| Pressure plot | `pressurePlotZone` | `[ГРАФИК ДАВЛЕНИЯ — будет в B.2]` | 14 |
| Sensor grid | `sensorGridZone` | `[ДАТЧИКИ — будет в B.3]` | 30 |
| Quick log | `quickLogZone` | `[ЖУРНАЛ — будет в B.6]` | 4 |

Stretch numbers sum to 100, matching the proportion table from
`PHASE_UI1_V2_WIREFRAME.md` section 6 (Phase 14% / Temp 38% / Pressure
14% / Sensor grid 30% / Quick log 4% collapsed).

#### `on_reading` method (stub)

`DashboardView` must accept readings via `on_reading(reading: Reading)`
because `MainWindowV2._dispatch_reading()` calls
`self._overview_panel.on_reading(reading)`. In B.1 this is a **no-op**:

```python
def on_reading(self, reading: Reading) -> None:
    """Receive reading from main window dispatcher.

    B.1: no-op stub. B.2+ wires this to plot widgets.
    """
```

This matches the OverviewPanel surface so `MainWindowV2` can swap
without other changes.

### Task 3 — Update `__init__.py`

**File:** `src/cryodaq/gui/dashboard/__init__.py`

```python
"""Phase UI-1 v2 dashboard — new home view replacing OverviewPanel."""

from cryodaq.gui.dashboard.dashboard_view import DashboardView

__all__ = ["DashboardView"]
```

### Task 4 — Wire DashboardView into MainWindowV2

**File:** `src/cryodaq/gui/shell/main_window_v2.py`

Two changes:

1. **Import:**
   ```python
   from cryodaq.gui.dashboard import DashboardView
   ```
   Keep the existing `from cryodaq.gui.widgets.overview_panel import
   OverviewPanel` import — we don't delete OverviewPanel until B.7.

2. **In `_build_ui`**, replace:
   ```python
   self._overview_panel = OverviewPanel(self._channel_mgr)
   ```
   with:
   ```python
   # Phase UI-1 v2 (B.1): new dashboard skeleton replaces legacy
   # OverviewPanel. Old class still imported above for now — removed
   # entirely in B.7 after all dashboard sub-blocks are complete.
   self._overview_panel = DashboardView(self._channel_mgr)
   ```

**Keep the attribute name `self._overview_panel`** even though it now
holds DashboardView. Many places in `_dispatch_reading` reference it
by this name. Renaming to `self._dashboard` is a separate cleanup for
B.7.

The `_dispatch_reading` method already calls
`self._overview_panel.on_reading(reading)` which now hits the no-op
stub on DashboardView. **No changes to dispatch routing needed in
B.1.**

### Task 5 — Smoke tests

**File:** `tests/gui/dashboard/test_dashboard_view.py`

Three minimal tests:

```python
"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard import DashboardView


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


def test_dashboard_view_constructs(app):
    """DashboardView instantiates without error."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    assert view is not None


def test_dashboard_view_has_five_zones(app):
    """All five placeholder zones are present as direct children with
    expected object names."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone",
                "sensorGridZone", "quickLogZone"}
    found = {child.objectName() for child in view.findChildren(
        type(view.findChild(type(view), "phaseZone").parent())
    ) if child.objectName()} if False else {
        child.objectName() for child in view.findChildren(object)
        if child.objectName() in expected
    }
    assert expected.issubset(found), f"Missing zones: {expected - found}"


def test_dashboard_view_on_reading_is_noop(app):
    """on_reading() accepts a reading without raising (B.1 stub)."""
    from cryodaq.drivers.base import ChannelStatus, Reading
    from datetime import datetime, timezone

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="Т1",
        value=4.2,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
    )
    view.on_reading(reading)  # should not raise
```

Note: the second test has a fragile findChildren idiom. Simpler version
acceptable:

```python
def test_dashboard_view_has_five_zones(app):
    mgr = ChannelManager()
    view = DashboardView(mgr)
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone",
                "sensorGridZone", "quickLogZone"}
    actual = {
        c.objectName() for c in view.findChildren(object)
        if hasattr(c, 'objectName') and c.objectName()
    }
    assert expected.issubset(actual), f"Missing: {expected - actual}"
```

Use whichever idiom works on first try. If `findChildren(object)`
doesn't enumerate properly, use `findChildren(QFrame)` instead.

---

## Out of scope

- Do NOT touch `theme.py`
- Do NOT touch `tool_rail.py`, `top_watch_bar.py`, `bottom_status_bar.py`,
  `overlay_container.py` — shell foundation is final
- Do NOT touch `overview_panel.py` — old class stays alive until B.7
- Do NOT add real plot widgets (B.2)
- Do NOT add sensor cards (B.3)
- Do NOT add phase widget logic (B.4)
- Do NOT add quick log functionality (B.6)
- Do NOT route data — `on_reading` is a no-op stub
- Do NOT introduce ZMQ workers, QTimer, animations
- Do NOT delete the legacy OverviewPanel class — B.7 does that
- Do NOT rename `self._overview_panel` attribute in MainWindowV2 —
  also B.7 cleanup

---

## Tests

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -10
```

Expected: **843 passed, 6 skipped** (840 baseline + 3 new dashboard
smoke tests).

If any **existing** test breaks, stop and report. The change should be
purely additive at the test suite level.

---

## Visual verification

Launch via launcher:
```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq
```

Expected visual result:
- Top watch bar still works (engine status, experiment, channel summary,
  alarms)
- Tool rail still works (10 icons + ⋯ menu)
- Bottom status bar still works (uptime, disk, data rate, connected, time)
- **Dashboard area** shows five vertically stacked grey/dark rectangles
  with subtle borders and centered Russian labels:
  - `[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]`
  - `[ГРАФИК ТЕМПЕРАТУР — будет в B.2]`
  - `[ГРАФИК ДАВЛЕНИЯ — будет в B.2]`
  - `[ДАТЧИКИ — будет в B.3]`
  - `[ЖУРНАЛ — будет в B.6]`
- Channel summary in watch bar still shows realistic count `N/14 норма`
  (no regression from A.9)
- All overlays (Источник мощности, Аналитика, etc) still open via tool
  rail icons because they're independent of dashboard content
- **No floating fragments**, no seams, no broken layout

**This is intentionally not pretty.** It's a structural skeleton showing
that the layout proportions are right and the wiring works. B.2-B.7
fill it in.

Also launch via standalone:
```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq-gui
```

Same check.

---

## Codex audit

After committing Task 1-5, run:

```bash
codex exec -c model="gpt-5.4" "Audit commit on feat/ui-phase-1-v2 implementing Block B.1 DashboardView skeleton against the spec at docs/phase-ui-1-v2/PHASE_UI1_V2_BLOCK_B1_SPEC.md.

Look specifically for:
- QSS selectors using Python class names instead of #objectName (Block A.7 lesson)
- QSS selectors that cascade to children causing seams (Block A.8 lesson — QWidget {} on parent affects all child QLabel)
- ZMQ worker leaks in widget __init__ methods
- QTimer.singleShot lifetime management
- Russian localization gaps in src/cryodaq/gui/dashboard/
- Embedded mode compatibility — verify that DashboardView replacement does not break MainWindowV2 reading dispatch
- Test pollution from new tests
- Any place where Task 4 wire-up missed an attribute reference in MainWindowV2

Report findings in numbered list with severity CRITICAL/HIGH/MEDIUM/LOW. Do not modify any files. Read-only audit."
```

Paste full Codex output verbatim into the CC reply. Vladimir will
triage findings and decide whether B.2 starts or B.1.1 micro-fix is
needed first.

---

## Commit and stop

```bash
git add src/cryodaq/gui/dashboard/ src/cryodaq/gui/shell/main_window_v2.py tests/gui/dashboard/
git commit -m "ui(phase-1-v2): block B.1 — DashboardView skeleton with placeholder zones

First sub-block of Block B (dashboard rewrite). Creates new
src/cryodaq/gui/dashboard/ directory with DashboardView containing
five labeled placeholder zones. Wires DashboardView into
MainWindowV2 in place of OverviewPanel.

Legacy OverviewPanel class remains untouched and will be deleted
in Block B.7 after all sub-blocks B.2-B.6 are complete.

No data flow yet — on_reading is a no-op stub. Plot widgets,
sensor grid, phase-aware widget, and collapsible quick log come
in B.2-B.6."
```

Print: `BLOCK B.1 COMPLETE — visual fix committed, Codex audit below`
followed by the Codex output.

**Stop. Do not start B.2.** Vladimir reviews skeleton visually + Codex
findings, then approves B.2 spec.

---

## Success criteria

- New directory `src/cryodaq/gui/dashboard/` exists with two files
- `DashboardView` class is importable as `from cryodaq.gui.dashboard
  import DashboardView`
- `DashboardView` instantiates with `ChannelManager` argument
- `DashboardView.on_reading(reading)` accepts a Reading without raising
- Five zones present with correct object names: `phaseZone`,
  `tempPlotZone`, `pressurePlotZone`, `sensorGridZone`, `quickLogZone`
- Each zone has a Russian placeholder label
- Stretch ratios sum to 100 (14/38/14/30/4)
- `MainWindowV2._build_ui` constructs DashboardView instead of
  OverviewPanel (one-line change)
- `MainWindowV2._dispatch_reading` unchanged — still calls
  `self._overview_panel.on_reading(reading)` which now hits the stub
- Tests: **843 passed, 6 skipped** (840 baseline + 3 new)
- Visual verification: launching via `cryodaq` and `cryodaq-gui` shows
  five labeled placeholder zones in dashboard area, all shell features
  work
- Codex audit pass with no CRITICAL findings, ideally no HIGH findings
- Commit message includes context that this is B.1 of 7

## After Vladimir's review

If approved → B.2 spec (temperature plot widget + pressure plot widget
in their respective zones, replacing placeholder labels with real
pyqtgraph widgets that receive data via `on_reading`).

If something is wrong → B.1.1 micro-fix.

If Codex finds a critical foundation issue → emergency fix block.
