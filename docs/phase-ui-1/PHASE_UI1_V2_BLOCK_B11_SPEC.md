# Phase UI-1 v2 — Block B.1.1: dashboard zone reorder

## Context

Block B.1 created `DashboardView` with five placeholder zones in the
order from `PHASE_UI1_V2_WIREFRAME.md` section 6:

1. Phase
2. Temperature plot
3. Pressure plot
4. Sensor grid
5. Quick log

After visual review on Mac dev, Vladimir requested a different order
and proportions:

1. Phase
2. **Sensor grid** (moved up, sized smaller)
3. Temperature plot (larger)
4. Pressure plot (larger)
5. Quick log

**Reasoning:** dispatcher walks up to the screen and wants to see all
current channel values immediately as a compact overview strip under
the phase widget, then graphs below give time-series context. Sensor
grid is a snapshot, plots are the trend.

This is **B.1.1**, a micro-fix block. Single file change. No new code,
no new tests, just stretch ratios and zone order in the existing
`_build_ui` method.

## Branch and baseline

- Branch: `feat/ui-phase-1-v2` (continue from current HEAD)
- Last commit: `ui(phase-1-v2): block B.1 — DashboardView skeleton with placeholder zones`
- Baseline tests: **842 passed, 7 skipped**

## Russian language hard rule

No new strings introduced. Existing Russian placeholder labels stay as
they are.

---

## Task — Reorder zones and update stretch ratios

**File:** `src/cryodaq/gui/dashboard/dashboard_view.py`

In `_build_ui` (or wherever zones are added to the root layout), change
the order of `addWidget(zone, stretch=N)` calls so they appear in this
order top-to-bottom:

| # | objectName | label text | Stretch |
|---|---|---|---|
| 1 | `phaseZone` | `[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]` | **10** |
| 2 | `sensorGridZone` | `[ДАТЧИКИ — будет в B.3]` | **22** |
| 3 | `tempPlotZone` | `[ГРАФИК ТЕМПЕРАТУР — будет в B.2]` | **44** |
| 4 | `pressurePlotZone` | `[ГРАФИК ДАВЛЕНИЯ — будет в B.2]` | **20** |
| 5 | `quickLogZone` | `[ЖУРНАЛ — будет в B.6]` | **4** |

Stretch numbers sum to 100.

Three rules during the change:

1. **Object names stay identical** — `phaseZone`, `sensorGridZone`,
   `tempPlotZone`, `pressurePlotZone`, `quickLogZone`. Tests in
   `test_dashboard_view.py::test_dashboard_view_has_five_zones` check
   for exactly these five names.
2. **Russian labels stay identical** — only order and stretch change.
3. **No structural refactoring** — do not introduce new helper methods,
   do not rename `_make_zone`, do not extract zone definitions to a
   separate constant. This is a one-pattern change in `_build_ui`.

## Out of scope

- Do NOT touch `theme.py`
- Do NOT touch `main_window_v2.py`
- Do NOT touch any shell file
- Do NOT touch `tests/gui/dashboard/test_dashboard_view.py` — test
  asserts on object names, not order, so it should still pass
- Do NOT change zone styles, borders, fonts, label colors
- Do NOT add real plot widgets (B.2)
- Do NOT add real sensor grid (B.3)

## Tests

```bash
.venv/bin/python -m pytest tests/gui/dashboard/ -q 2>&1 | tail -5
.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: **842 passed, 7 skipped** (no change from B.1).

If `test_dashboard_view_has_five_zones` fails because it checks order
instead of just presence — update the test minimally to check presence
(set membership). If it passes — leave the test alone.

## Visual verification

Launch via:
```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq
```

Expected:
- Phase zone at top (small, ~10% of dashboard area height)
- **Sensor grid zone right under phase** (larger, ~22%)
- Temperature plot zone (largest, ~44%)
- Pressure plot zone (~20%)
- Quick log zone at bottom (thin strip, ~4%)
- Total layout fills the dashboard area without scroll
- All other shell features unchanged

## No Codex audit for this micro-block

B.1.1 is a single-line ordering change inside one file. Codex audit is
overkill for this scope. Skip the audit step. Block B.2 will run audit
again.

## Commit and stop

```bash
git add src/cryodaq/gui/dashboard/dashboard_view.py
git commit -m "ui(phase-1-v2): block B.1.1 — reorder dashboard zones (sensors above plots)

Vladimir review of B.1 skeleton: sensor grid moved up to sit directly
under phase widget. Plots gain proportion (44% temp + 20% pressure
= 64% of dashboard height). Sensor grid trimmed to 22%. Phase
trimmed to 10%. Quick log stays 4% collapsed.

New order top-to-bottom:
  phaseZone (10) → sensorGridZone (22) → tempPlotZone (44)
  → pressurePlotZone (20) → quickLogZone (4)

No structural changes — only stretch values and addWidget order
inside _build_ui."
```

Print: `BLOCK B.1.1 COMPLETE — awaiting visual review`

**Stop. Do not start B.2.** Vladimir reviews the new layout and
approves before B.2 spec arrives.

## Success criteria

- Five zones present in new top-to-bottom order
- Stretch ratios 10/22/44/20/4 sum to 100
- Tests: 842 passed, 7 skipped (no regression)
- Visual: launching via cryodaq shows the new order
- Single commit, single file changed
