# Phase UI-1 v2 — Block A.8: child widget seams + first Codex audit

## Context

Block A.7 fixed the major shell background issue (QSS selectors using
Python class names → switched to Qt base class selectors +
`setAutoFillBackground(True)`). Visible result: shell panels now have
solid backgrounds, dashboard no longer bleeds through.

**New problem visible after A.7:** child widgets inside `TopWatchBar` and
`BottomStatusBar` have visible rectangular seams around them. Specifically:
- Around the Engine indicator (zone 1) on the left side of TopWatchBar
- Around the safety state circle/pill in BottomStatusBar bottom-left

This means child widgets are painting their own background that doesn't
match the parent panel — creating visible borders where there should be
seamless flat panel.

This is the **last expected visual issue** in the shell foundation. After
A.8, the shell foundation is considered finalized and ready for Block B
(dashboard rewrite).

A.8 also introduces **Codex audit as a workflow step** — this is the
first block where after the visual fix is committed, CC invokes `/codex`
to audit the entire shell foundation (Block A through A.8) before we
move forward.

## Branch and baseline

- Branch: `feat/ui-phase-1-v2` (continue from current HEAD)
- Last commit: `ui(phase-1-v2): block A.7 — fix tool rail / dashboard layout collision`
- Baseline tests: **840 passed, 6 skipped**

## Russian language hard rule

All operator-facing text in this spec's scope is in `src/cryodaq/gui/shell/`
which has already been audited in Block A.6. **Do not introduce any new
English strings.** If you find leftover English from previous blocks,
flag it but do not fix it inline — that's a separate cleanup.

Technical terms preserved as English: `Engine`, `Telegram`, `SMU`,
`Keithley`, `LakeShore`, `GPIB`.

---

## Task 1 — Fix child widget background seams

### Investigation steps

1. View `src/cryodaq/gui/shell/top_watch_bar.py`. Find the construction
   of zone 1 (engine indicator). Look for:
   - Inner `QFrame` or `QWidget` containers around the dot + label
   - Any `setAutoFillBackground(True)` on child widgets
   - Any `setStyleSheet("background: ...")` on child widgets
   - Any `setStyleSheet` that paints a different color than parent
     `theme.SURFACE_PANEL`
2. Same for zones 2, 3, 4 of TopWatchBar and any vertical separators
   between them.
3. View `src/cryodaq/gui/shell/bottom_status_bar.py`. Find construction
   of:
   - Safety state pill widget on the left
   - Uptime / Disk / Data rate / Connection / Time labels
   - Any vertical separators between zones
4. Identify which child widgets have explicit background settings that
   shouldn't.

### Fix strategy

**All child widgets inside TopWatchBar and BottomStatusBar must have
transparent background.** Only the parent panel paints background through
its `setAutoFillBackground(True) + palette` or stylesheet.

Concrete actions:
- Remove any `setAutoFillBackground(True)` from child widgets (keep only
  on the parent panels themselves)
- Remove any `setStyleSheet("background-color: ...")` or
  `setStyleSheet("background: ...")` from child widgets, **unless** the
  child is intentionally a colored pill/badge (status indicator, etc) in
  which case the background must explicitly match `theme.SURFACE_PANEL`
  or be a deliberate contrasting token from `theme`
- If a child widget needs styling (text color, font weight, padding), keep
  the stylesheet but **remove** the `background-*` properties from it

### Anti-pattern check (apply per `SPEC_AUTHORING_CHECKLIST.md`)

Before changing anything in QSS, verify:
- If you write a stylesheet on a child widget, make sure the selector is
  correct (use Qt base class names, not Python class names — same lesson
  as Block A.7)
- Don't combine `setAutoFillBackground` and `setStyleSheet("background: ")`
  on the same widget — pick one approach

### Verification

1. Launch via `cryodaq` (launcher mode):
   ```bash
   CRYODAQ_MOCK=1 .venv/bin/cryodaq
   ```
2. Look closely at TopWatchBar zone 1 — engine indicator dot and label
   should blend seamlessly into the panel background. **No visible
   rectangular border around the indicator.**
3. Look closely at BottomStatusBar safety state on the left — same.
4. All zones in both bars should look like text and dots floating on a
   single uniform panel surface, not as separate boxes pasted onto a
   background.
5. Launch via `cryodaq-gui` (standalone) — same checks.

---

## Task 2 — Codex audit of shell foundation

**This is the first block where Codex audit is part of the workflow.**

After Task 1 is committed, invoke `/codex` inside CC with the following
prompt verbatim:

```
Audit the shell foundation of CryoDAQ on branch feat/ui-phase-1-v2.

Scope: commits from "ui(phase-1-v2): block A — new shell scaffold" through
the most recent commit (Block A.8). The relevant directories are
src/cryodaq/gui/shell/, src/cryodaq/launcher.py, src/cryodaq/gui/app.py,
src/cryodaq/gui/widgets/overview_panel.py.

The specs for these blocks live in docs/phase-ui-1-v2/.

Look specifically for these defect categories. Report any findings in a
numbered list with severity CRITICAL / HIGH / MEDIUM / LOW. Do not suggest
stylistic improvements, only correctness defects.

1. QSS selectors using Python class names instead of Qt base class names.
   Qt only matches C++ class names; Python subclass names are silently
   ignored. Search for any setStyleSheet call where the selector is a
   custom widget class name like "TopWatchBar { ... }" instead of
   "QWidget { ... }" or "#objectName { ... }".

2. Child widgets with their own background settings that conflict with
   parent panel background, causing visible visual seams. Look for
   setAutoFillBackground(True) and setStyleSheet("background-color: ...")
   on child widgets inside TopWatchBar, BottomStatusBar, ToolRail.

3. ZMQ worker leaks or QTimer.singleShot lifetime issues in widget
   __init__ methods. Look for workers/timers that are started in
   constructors but never explicitly stopped, especially in panels that
   are constructed eagerly versus lazily.

4. Embedded mode compatibility between MainWindowV2 and LauncherWindow.
   Check that LauncherWindow can hide its own chrome (top engine bar,
   bottom status bar) without breaking its internal logic that still
   reads/writes those widgets. Check that MainWindowV2 accepts
   embedded=True parameter and exposes the surface launcher expects
   (menuBar, statusBar, dispatch_reading routing).

5. Russian localization gaps in src/cryodaq/gui/shell/. Any English
   string in operator-facing text is a defect. Technical terms allowed:
   Engine, Telegram, SMU, Keithley, LakeShore, GPIB. Anything else
   English in the shell directory is a defect.

6. Channel state aggregation in TopWatchBar zone 3 (the "N/M норма"
   readout). Verify the count logic correctly handles channels that
   haven't received any reading yet, channels in different ChannelStatus
   enum states, and stale channels. Verify it updates when channels
   transition between states.

7. Signal/slot wiring between TopWatchBar zones and MainWindowV2
   dispatchers. Check that click on zone 2 (experiment) opens the
   experiment overlay and click on zone 4 (alarms) opens the alarms
   overlay. Check that the dispatch_reading method on MainWindowV2 routes
   readings to the dashboard and to TopWatchBar's channel summary
   correctly.

8. Tool rail more menu actions. Verify "Открыть Web-панель" and
   "Перезапустить Engine" route to the correct handlers in MainWindowV2,
   and that _restart_engine correctly walks the parent chain to find
   LauncherWindow when running embedded, and shows informational message
   when running standalone via cryodaq-gui.

9. Test pollution: do any of the new shell tests in tests/gui/shell/ leak
   QTimer or worker state across tests? Are mocks of send_command
   properly scoped?

10. Any other correctness defect you find that I have not asked about
    explicitly.

Output format: numbered list, each item is one defect with:
- File and line if applicable
- Description (one sentence)
- Why it's a defect
- Severity tier
- Suggested fix in one sentence

Do not write code. Do not modify any files. This is read-only audit.
```

After Codex output, **paste it verbatim** into the CC reply for Vladimir
to read. Do not summarize, do not interpret, do not act on findings.
Vladimir will triage findings and decide what to fix in a follow-up
block (A.9 if needed) or what to record as backlog for Phase UI-2.

---

## Out of scope

- Do NOT touch `theme.py`
- Do NOT touch `main_window_v2.py` (the layout fix from A.7 is correct,
  do not touch it)
- Do NOT touch `tool_rail.py` (works fine after A.5/A.6)
- Do NOT touch the QSS selectors at the panel level (they're correct
  after A.7)
- Do NOT change `OverviewPanel` internals (that's Block B)
- Do NOT act on Codex findings inline — only report them
- Do NOT introduce new tests unless required by the visual fix

## Tests

Run after Task 1:

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -10
```

Expected: 840 passed, 6 skipped (no regression).

If any test breaks, stop and report. Do not force-fix.

## Commit and stop

```bash
git add src/cryodaq/gui/shell/top_watch_bar.py \
        src/cryodaq/gui/shell/bottom_status_bar.py
git commit -m "ui(phase-1-v2): block A.8 — fix child widget background seams"
```

Then run the Codex audit (Task 2).

After both Task 1 commit and Task 2 audit are complete, print:

```
BLOCK A.8 COMPLETE — visual fix committed, Codex audit below

[paste full Codex output here]

Stopping. Awaiting Vladimir's triage of audit findings.
```

**Stop. Do not start Block B. Do not act on any Codex finding.**

## Success criteria

- TopWatchBar zone 1 engine indicator: no visible rectangular border
  around the dot + label
- BottomStatusBar safety state: no visible rectangular border around the
  pill / circle
- All other zones in both bars: text and dots float on uniform panel
  background, no seams
- `cryodaq` launcher mode and `cryodaq-gui` standalone mode both render
  correctly
- Tests: 840 passed, 6 skipped
- Codex audit completed and output pasted in CC reply
- Single commit for the visual fix
- No regressions to launcher integration, channel summary, engine state,
  Russian localization

## After Vladimir's triage

Vladimir will look at:
1. Visual screenshot — does the seam fix work
2. Codex findings — which are real defects, which are false positives,
   which are out of scope

He will then either:
- Approve foundation as final → write spec for Block B (dashboard rewrite)
- Request a follow-up block A.9 to fix critical Codex findings
- Record some findings as backlog for Phase UI-2 with explicit
  justification
