# Phase UI-1 v2 — Block A.9: orphan widget stubs + Codex finding fixes

## Context

Block A.8 fixed shell background seams and ran the first Codex audit
which surfaced 8 defects. Vladimir's triage:

- **4 fix now (A.9):** orphan widgets, worker stacking, channel summary,
  Russian alarm label, web panel port probe
- **3 backlog → Block B:** defects inside `overview_panel.py` internals
  which are being rewritten from scratch in Block B (Findings 1, 4, 8)
- **1 already fixed:** Finding 3 (orphan widgets) was misclassified as
  background-only, but actually causes a **visible** UI bug — re-promoted
  to HIGH and included here

**Visible symptom that prompted promotion of Finding 3:** orphaned
`KeithleyStrip` instance in `OverviewPanel` calls `setVisible(True)` on
itself when Keithley data starts arriving (a few seconds after launch),
which **un-hides** the widget that Block A removed from layout. Since the
widget has no parent layout slot, Qt renders it at relative `(0, 0)` —
the top-left corner of OverviewPanel, **on top of T1 sensor card**.
Visible as fragments "Ке sm sm" + "верх" floating over the first card.

This is the **last expected mini-fix** of Phase UI-1 v2 foundation. After
A.9 the foundation is finalized and we move to Block B (dashboard
rewrite).

## Branch and baseline

- Branch: `feat/ui-phase-1-v2` (continue from current HEAD)
- Last commit: `ui(phase-1-v2): block A.8 — fix child widget background seams`
- Baseline tests: **840 passed, 6 skipped**

## Russian language hard rule

Operator-facing text — **only Russian**. Technical exceptions: `Engine`,
`Telegram`, `SMU`, `Keithley`, `LakeShore`, `GPIB`. Any new English
string in operator-facing UI is a defect.

## Anti-pattern reminders (per SPEC_AUTHORING_CHECKLIST.md)

- QSS selectors: use Qt base class or `#objectName`, not Python class names
- Child widget backgrounds: transparent unless intentional
- Workers / QTimer in `__init__`: prefer lazy construction or explicit
  lifetime management

---

## Task 1 — Replace orphan widgets with no-op stubs

**Most important task. Fixes the visible "floating window" bug.**

### Problem

`OverviewPanel.__init__` constructs four widgets that were removed from
its layout in Block A but kept as instance attributes so other methods
(`_dispatch_reading`, `set_safety_state`, `on_reading`, `set_alarm_count`,
etc) can keep calling them as no-ops:

- `self._status_strip` (StatusStrip — A.5)
- `self._experiment_status` (ExperimentStatusWidget — A)
- `self._quick_log` (QuickLogWidget — A)
- `self._keithley_strip` (KeithleyStrip — A)

The "construct + `.hide()`" approach is fragile because **the widgets
themselves can call `setVisible(True)` on data arrival**. Specifically
`KeithleyStrip._refresh_labels` does:

```python
self.setVisible(
    any(state != "off" for state in self._channel_state.values())
    or bool(self._smua_data) or bool(self._smub_data)
)
```

When Keithley readings start flowing, this overrides our `.hide()` and
the orphan widget renders at `(0, 0)` over T1.

`ExperimentStatusWidget` likely has analogous behavior. Both also keep
their `QTimer`s alive and continue polling backend in the background
(per Codex Finding 3).

### Fix

Create a single universal no-op stub class **inside** `overview_panel.py`
(near the top, after imports, before `OverviewPanel` class):

```python
class _OrphanedStub:
    """Phase UI-1 v2: no-op replacement for widgets removed during shell
    transition.

    OverviewPanel still has many code paths (_dispatch_reading,
    set_safety_state, on_reading, set_alarm_count, set_keithley_status,
    set_cooldown_eta) that call methods on widgets which were removed
    from layout. Constructing the real widgets and hiding them is
    fragile because some of them call setVisible(True) on data arrival,
    re-introducing visible orphan rendering at (0, 0).

    This stub absorbs every method call as no-op via __getattr__,
    preventing rendering, timers, and ZMQ workers entirely. Removed
    completely in Block B when OverviewPanel is rewritten.
    """

    def __getattr__(self, name):
        return _noop

def _noop(*args, **kwargs):
    return None
```

Then in `OverviewPanel.__init__`, find every place where the four
orphan widgets are constructed and replace with stub:

```python
# Phase UI-1 v2 (A.9): orphan widgets replaced with no-op stubs.
# Real widgets caused visible rendering at (0,0) when their internal
# logic called setVisible(True) on data arrival. See Block A.9 spec.
self._status_strip = _OrphanedStub()
self._experiment_status = _OrphanedStub()
self._quick_log = _OrphanedStub()
self._keithley_strip = _OrphanedStub()
```

**Investigation steps:**

1. View `overview_panel.py` to find exact lines where these four widgets
   are constructed (search for `StatusStrip(`, `ExperimentStatusWidget(`,
   `QuickLogWidget(`, `KeithleyStrip(`)
2. Replace each construction with `_OrphanedStub()`
3. Remove any `.hide()` calls that immediately follow these constructions
   — they're no longer needed since the stub renders nothing
4. Do not remove the class definitions of `StatusStrip`,
   `ExperimentStatusWidget`, `QuickLogWidget`, `KeithleyStrip` themselves
   — other code or tests may import them. They become unused dead code
   to be removed in Block B.

**Verification:**

1. Launch via `cryodaq` mock, wait 60+ seconds for Keithley data to flow
2. Verify **no fragments** floating over T1 sensor card
3. Verify all other dashboard functionality still works (sensor cards
   update, plots draw, alarm count works in TopWatchBar)
4. Tests: 840 passed, 6 skipped (no regression)

---

## Task 2 — TopWatchBar worker stacking guard

**Codex Finding 2.** Worker leak / fan-out under slow backend.

### Problem

`TopWatchBar` polling timers create new `ZmqCommandWorker` on **every
tick** without checking whether the previous worker is still running. If
backend is slow or hung, threads stack up.

### Fix

For each polling stream in `TopWatchBar`, keep one in-flight worker
reference. On each tick:

```python
def _poll_experiment_status(self):
    if self._experiment_worker is not None and not self._experiment_worker.isFinished():
        # Previous request still in flight — skip this tick
        return
    self._experiment_worker = ZmqCommandWorker({"cmd": "experiment_status"})
    self._experiment_worker.finished.connect(self._on_experiment_status_result)
    self._experiment_worker.start()
```

Apply the same pattern to **every** poll stream in TopWatchBar:
- experiment_status polling (zone 2)
- alarm count polling (zone 4)
- any other stream you find

Initialize `self._experiment_worker = None` etc in `__init__`.

**Verification:** offscreen smoke test that calls poll method multiple
times in rapid succession without finishing previous workers — verify
only one worker spawns.

---

## Task 3 — Channel summary rework using ChannelManager

**Codex Finding 5.** Visible symptom: zone 3 shows "5/5 норма" or
"8/8 норма" instead of "5/24 норма" or similar.

### Problem

`TopWatchBar` zone 3 computes channel summary from a cache that is only
populated when a Т* reading arrives. The denominator therefore equals
the count of channels that have already emitted, not the count of
visible channels in the system. Channels that haven't reported yet, or
channels that went silent, are excluded entirely.

### Fix

`TopWatchBar` should derive its denominator from `ChannelManager`:

1. Inject `ChannelManager` instance via constructor (likely already
   accessible from `MainWindowV2` which can pass it down)
2. On each refresh, query `ChannelManager` for visible channels
3. For each visible channel, look up its last reading state from cache
4. Aggregate by status:
   - **norma**: channel has recent reading and status is `OK`
   - **vne_normy** (вне нормы): channel has recent reading but status is
     `WARNING`, `CAUTION`, or `FAULT`
   - **stale**: channel has no recent reading OR last reading was more
     than `_STALE_TIMEOUT_S` ago (use a sensible default like 30 seconds,
     can calibrate later)
   - **never_seen**: channel has no reading at all yet

Display format:
- All ok: `● N/N норма` (green)
- Some not ok: `● M/N норма · K вне нормы` (caution color if any caution,
  warning color if any warning, fault color if any fault)
- Some stale or never seen: append `· S ожидают` where S = stale + never_seen

Examples:
- `● 24/24 норма` — all good
- `● 22/24 норма · 2 вне нормы` — 2 channels in warning state
- `● 5/24 норма · 19 ожидают` — system just started, only Keithley reported
- `● 22/24 норма · 2 ожидают` — 2 channels went silent

**Investigation:**

1. Find where `ChannelManager` is constructed in the codebase (probably
   `core/channel_manager.py`, accessed via singleton `get_channel_manager()`
   or passed through bridge)
2. Find what method returns visible channels (`visible_channels()`?
   `iter_visible()`?)
3. View current `TopWatchBar` zone 3 logic to understand where to plug
   the new aggregation

**Per-channel last-seen tracking:**

```python
# In TopWatchBar.__init__:
self._channel_last_seen: dict[str, tuple[float, ChannelStatus]] = {}

# When a Т* reading arrives:
def _on_temperature_reading(self, reading):
    self._channel_last_seen[reading.channel] = (
        time.monotonic(),
        reading.status
    )
    self._refresh_zone_3()
```

**Verification:**

1. Launch fresh mock, immediately observe zone 3 — should show
   `5/24 норма · 19 ожидают` (or similar based on actual visible count
   from channels.yaml) **immediately**, not `5/5 норма`
2. Wait 60s for all channels to populate, observe `24/24 норма`
3. If a channel goes stale (mock can simulate this by stopping reading
   for one channel) — verify it transitions to `ожидают`

---

## Task 4 — Russian "active" → "актив."

**Codex Finding 6.** Trivial localization gap.

In `top_watch_bar.py` line ~264, the **initial state** of zone 4 alarm
label is set to English `"active"`. The polling code already uses Russian
`"актив."`. Fix the initial state to match.

Find the discrepancy and centralize the formatter so initial state and
polling state both use the same string.

---

## Task 5 — Web-панель port probe stub

**Codex Finding 7.** Open Web-панель action opens dead port if web
server is not running.

### Problem

`MainWindowV2._open_web_panel()` calls `webbrowser.open(url)` directly
without checking whether the port is responding. If the user clicks
"Открыть Web-панель" but `cryodaq.web.server` is not running, the
browser opens to an error page.

### Fix

Add port probe before opening browser:

```python
import socket

def _open_web_panel(self):
    host = "127.0.0.1"
    port = _WEB_PORT
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except (OSError, socket.timeout):
        QMessageBox.information(
            self,
            "Web-панель",
            f"Веб-сервер не запущен на порту {port}.\n\n"
            f"Запустите его командой:\n"
            f"uvicorn cryodaq.web.server:app --host 0.0.0.0 --port {port}"
        )
        return
    webbrowser.open(f"http://{host}:{port}")
```

**Note:** the QMessageBox uses Russian per language rule. The uvicorn
command line can stay English (technical command, like a shell
incantation, not operator-facing UI text in the strict sense).

Apply the same pattern to **`launcher.py`** if it has its own web panel
opener — but check first whether launcher's web panel button is even
reachable now that launcher chrome is hidden in A.6. If unreachable,
skip the launcher fix.

**Verification:**

1. Launch via `cryodaq-gui` (no launcher), click ⋯ → "Открыть Web-панель"
2. Verify QMessageBox appears with Russian text about web server not
   running
3. Start web server in another terminal, click again → browser opens
   correctly

---

## Out of scope

The following Codex findings are **explicitly deferred to Block B** because
they live in `overview_panel.py` internals which Block B rewrites from
scratch. Fixing them in A.9 would be wasted effort:

- **Finding 1** (HIGH): `CompactTempCard {}` and `PressureCard {}` QSS
  selectors using Python class names. These card classes are deleted in
  Block B (replaced by new `SensorCardWithRename`).
- **Finding 4** (HIGH): Static `QTimer.singleShot` and parentless
  `ZmqCommandWorker` in OverviewPanel. Replaced by new dashboard widgets
  in Block B with proper lifetime management.
- **Finding 8** (MEDIUM): Test fixture doesn't drain parentless workers
  from old OverviewPanel. Becomes obsolete when those workers are
  removed in Block B.

These are tracked as `BLOCK_B_PREREQUISITES` in this commit message
trailer (see commit section).

### Other out of scope

- Do NOT touch `theme.py`
- Do NOT touch `tool_rail.py`
- Do NOT touch `main_window_v2.py` except for Task 5 web panel fix
- Do NOT change `OverviewPanel` layout, plot widgets, or any rendering
  beyond replacing the four orphan widget instances with stubs
- Do NOT remove `StatusStrip` / `ExperimentStatusWidget` / `QuickLogWidget`
  / `KeithleyStrip` class definitions — they may be imported elsewhere,
  removal happens in Block B
- Do NOT introduce new tests unless required by a fix

## Tests

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -10
```

Expected: 840 passed, 6 skipped (no regression).

If any test breaks, stop and report. Do not force-fix.

If a test was relying on `KeithleyStrip` / `ExperimentStatusWidget`
internal state from `OverviewPanel.__init__` (e.g. `panel._keithley_strip
.set_voltage(...)` from a test) — that test breaks because the stub
absorbs the call as no-op. Update the test to call the bridge directly
or mark it as expected-to-skip with reason "stub in transition, see
Block B for proper fix".

## Commit and stop

```bash
git add src/cryodaq/gui/widgets/overview_panel.py \
        src/cryodaq/gui/shell/top_watch_bar.py \
        src/cryodaq/gui/shell/main_window_v2.py
git commit -m "ui(phase-1-v2): block A.9 — orphan widget stubs + Codex finding fixes

Fixes Codex audit findings 2, 3, 5, 6, 7 from Block A.8 audit.

BLOCK_B_PREREQUISITES (deferred from A.9 audit):
- Finding 1: CompactTempCard/PressureCard QSS selectors
- Finding 4: Static QTimer/parentless ZmqCommandWorker in OverviewPanel
- Finding 8: Test fixture worker drainage
All three live in OverviewPanel internals being rewritten in Block B."
```

Print: `BLOCK A.9 COMPLETE — awaiting visual review`

**Stop. Do not start Block B. Wait for Vladimir to verify orphan widget
fix works (no floating fragments over T1) and channel summary shows
realistic count.**

## Success criteria

- No floating "Ке sm sm" / "верх" / "----" fragments over T1 sensor card,
  even after Keithley mock data starts flowing
- Zone 3 channel summary shows realistic count immediately after launch
  (e.g. `● 5/24 норма · 19 ожидают`) and converges to `● 24/24 норма`
  as channels populate
- Zone 4 initial state shows Russian text consistent with polling state
- Click "Открыть Web-панель" with no web server running → Russian
  message box, no browser open
- Click "Открыть Web-панель" with web server running → browser opens
  to dashboard
- TopWatchBar polling does not stack workers under slow backend (verify
  via smoke test calling poll methods rapidly)
- Tests: 840 passed, 6 skipped
- Single commit with detailed message including BLOCK_B_PREREQUISITES
  trailer

## After Vladimir's visual review

If success criteria met → **Phase UI-1 v2 foundation is finalized.**
Vladimir requests Block B spec (dashboard rewrite from scratch).

If something is still wrong → A.10 micro-fix.
