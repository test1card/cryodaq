---
title: TopWatchBar
keywords: top-bar, watch-bar, header, chrome, vitals, at-a-glance, pressure, temperature, mode-badge
applies_to: persistent top chrome showing engine, experiment, fixed physical references, channel summary, alarms, and mode
status: active
implements: src/cryodaq/gui/shell/top_watch_bar.py (Phase B.4/B.4.5.2)
last_updated: 2026-07-16
references: rules/data-display-rules.md, rules/color-rules.md, rules/content-voice-rules.md
---

# TopWatchBar

Horizontal chrome strip at the top of every screen. It keeps engine state,
experiment/phase context, the current mode, three fixed physical readings,
channel health, and alarm count visible across operator surfaces.

> **Implementation status.** The shipped TopWatchBar at
> `src/cryodaq/gui/shell/top_watch_bar.py` is aligned with this spec:
> height = `HEADER_HEIGHT` (56px), pressure formatted in `мбар`
> (Cyrillic), `Т 2-й ступени` / `Т плиты N₂` locked to `Т12` / `Т11` (positionally
> fixed reference channels), no emoji in the alarms cell. The canonical
> anatomy is the shipped zone-based layout: engine; experiment, phase, elapsed
> time, and mode; persistent pressure/T12/T11 context; channel summary; and
> alarms. Heater current is intentionally absent here and remains available in
> the Keithley panel.
>
> **Batch A (2026-04-17) cleanup:** zone separators now carry explicit
> `background: transparent` (Fusion palette was painting them as
> filled rectangles around the 1px divider); the heater cell was
> removed from the context strip (low-signal for operators; heater
> current still surfaces on the Keithley panel) so the strip is now
> **pressure + second-stage temperature + nitrogen-plate temperature**; the time-window echo label was
> removed from the header (picker remains on `TempPlotWidget` — the
> header does not echo it).

**When to use:**
- Single instance in `MainWindow`, always visible at the top
- Any overlay should NOT hide the TopWatchBar — it's global chrome

**When NOT to use:**
- Don't instantiate multiple copies; it's a singleton of the shell
- Don't use as a generic header for panels (panels use their own Card header or breadcrumb)

## Anatomy

```text
Engine | Experiment · phase · elapsed [mode] |
Pressure · Т 2-й ступени (Т12) · Т плиты N₂ (Т11) | channels | alarms
```

The implementation may elide a long experiment name, but its complete text
remains available through the tooltip. Current values and state/provenance
cues must not be replaced by a summary-only presentation.

## Parts

| Part | Required | Description |
|---|---|---|
| **Bar frame** | Yes | Horizontal strip, `HEADER_HEIGHT` tall, spans viewport width |
| **Engine zone** | Yes | Engine connection/state with a non-color cue |
| **Experiment zone** | Yes | Active experiment, phase, elapsed time, and «Эксперимент»/«Отладка»/replay identity |
| **Physical context** | 3 fixed readings | Давление, `Т 2-й ступени` (`Т12`), `Т плиты N₂` (`Т11`) — in that order |
| **Channel summary** | Yes | Current normal/total count without replacing channel detail |
| **Alarm zone** | Yes | Validated attention count, worst severity, availability, and route to alarm detail |
| **Divider** | Implicit | 1px bottom border separates bar from main content |

## Invariants

1. **Height = HEADER_HEIGHT (56).** Coupled to TOOL_RAIL_WIDTH per RULE-SPACE-006 (corner square).
2. **Exactly three persistent physical readings.** Order is fixed: pressure → `Т 2-й ступени` (`Т12`) → `Т плиты N₂` (`Т11`). Heater current remains in the Keithley panel; it is not a TopWatchBar vital.
3. **Pressure always in мбар, scientific notation.** (RULE-COPY-006, RULE-DATA-005)
4. **Physical labels identify fixed channels, not extrema.** `Т 2-й ступени` reads only `Т12`; `Т плиты N₂` reads only `Т11`. These references are positionally fixed and cannot be relocated without dismantling the rheostat. Other temperature channels may change position between experiments, so neither fleet-wide minima/maxima nor substitute channels may be presented under these labels.
5. **Mode badge always visible.** Even during fault states. Operator must always know whether actions have real-world consequences.
6. **Instant fault rendering.** If a vital goes into fault, color changes immediately — no fade. (RULE-INTER-006)
7. **Tabular numbers.** Physical values use the canonical monospace/tabular-number treatment. (RULE-TYPO-003, RULE-DATA-003)
8. **Physical names remain explicit.** Never abbreviate the two fixed temperatures as minimum/maximum.
9. **Physical readings are not controls.** Experiment/mode/alarm zones may expose their documented routes; reading labels never imply actuation.
10. **Alarm truth has one writer.** The alarm panel owns validated snapshot
    identity, revision, availability, attention count, and worst severity. The
    top bar never polls alarm status independently. Before the first accepted
    snapshot, after disconnect, or after a rejected poll it shows
    `Тревоги: нет данных` in the stale/neutral presentation. A valid nonzero
    count uses `STATUS_INFO`, `STATUS_CAUTION`, or `STATUS_FAULT` according to
    the worst unacknowledged alarm; unknown severity fails closed to fault.
10. **No background shift on hover.** Bar is chrome, not interactive surface.

## Layout structure

```
Bar frame (HBoxLayout)
├── Engine state
├── Experiment + phase + elapsed
├── Mode badge
├── Context: pressure · Т12 second stage · Т11 nitrogen plate
├── Channel summary
└── Alarm count
```

## Physical-value anatomy

Each physical reference pairs an explicit location/quantity label with its
current value. Stale state retains the last value, dims it, and adds visible
stale wording; unavailable state shows an em dash rather than invented truth.

```
┌──────────────────────┐
│                      │
│   ДАВЛЕНИЕ           │  ◀── category label
│                      │     FONT_LABEL_SIZE (12)
│   1.23e-06 мбар      │     uppercase, letter-spacing 0.05em
│                      │     color: MUTED_FOREGROUND
│                      │  ◀── value
└──────────────────────┘     FONT_MONO_VALUE_SIZE (15, off-scale protected)
                             tnum + liga:0
                             color: FOREGROUND (or STATUS_* on alarm)
```

## Conceptual value contract

The shipped widget ingests `Reading` objects through `on_reading()` and polls
the existing engine/experiment/alarm clients. The signatures below name the
three physical values for design discussion only; they are not a second public
widget API and must not be added alongside the existing ingestion path.

```python
# src/cryodaq/gui/shell/top_watch_bar.py

class VitalCell(QWidget):
    """Conceptual rendering of one persistent physical reference."""
    def __init__(
        self,
        label: str,            # "ДАВЛЕНИЕ"
        parent: QWidget | None = None,
    ) -> None: ...
    
    def set_value(self, formatted: str, status: str = "ok") -> None:
        """Update displayed value + status color."""
    
    def set_stale(self, stale: bool) -> None:
        """Stale: data not updating; visual treatment per RULE-A11Y-002."""


class ModeBadge(QLabel):
    """Experiment / Debug mode pill."""
    MODE_EXPERIMENT = "experiment"
    MODE_DEBUG = "debug"
    
    def set_mode(self, mode: str) -> None: ...


class TopWatchBar(QWidget):
    """Top global chrome. Singleton in MainWindow."""
    
    def __init__(self, parent: QWidget) -> None: ...
    
    def set_pressure(self, mbar: float, status: str = "ok") -> None: ...  # parameter name stays Latin
    def set_second_stage_temperature(self, kelvin: float, status: str = "ok") -> None: ...
    def set_n2_plate_temperature(self, kelvin: float, status: str = "ok") -> None: ...
    def set_mode(self, mode: str) -> None: ...
    def set_stale_vital(self, vital_key: str, stale: bool) -> None: ...
```

## Historical value-cell sketch (non-canonical)

This sketch illustrates token use inside a value cell. It does not replace the
canonical shipped zone layout or its `on_reading()` ingestion path.

```python
class TopWatchBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(theme.HEADER_HEIGHT)  # DESIGN: RULE-SPACE-006
        self.setObjectName("topWatchBar")
        self.setStyleSheet(f"""
            #topWatchBar {{
                background: {theme.SURFACE_CARD};
                border: none;
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)
        
        row = QHBoxLayout(self)
        row.setContentsMargins(
            theme.TOOL_RAIL_WIDTH + theme.SPACE_5,  # align past left rail
            0,
            theme.SPACE_5,
            0,
        )
        row.setSpacing(theme.SPACE_6)  # 32px gap between vitals
        
        # Three physical readings in fixed order; heater remains in Keithley.
        self._pressure = VitalCell("ДАВЛЕНИЕ")
        self._second_stage = VitalCell("Т 2-Й СТУПЕНИ")
        self._n2_plate = VitalCell("Т ПЛИТЫ N₂")
        
        for cell in (self._pressure, self._second_stage, self._n2_plate):
            row.addWidget(cell, 1)  # equal stretch
        
        row.addStretch(0)
        
        self._mode_badge = ModeBadge()
        self._mode_badge.set_mode(ModeBadge.MODE_EXPERIMENT)
        row.addWidget(self._mode_badge, 0, Qt.AlignmentFlag.AlignVCenter)
```

## VitalCell reference

```python
class VitalCell(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # labels and values are tightly stacked
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # DESIGN: RULE-TYPO-005, RULE-TYPO-008
        self._label = QLabel(label)
        label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        label_font.setWeight(theme.FONT_LABEL_WEIGHT)
        label_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        self._label.setFont(label_font)
        self._label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(self._label)
        
        # DESIGN: RULE-TYPO-003 (tnum), RULE-TYPO-007 (15px off-scale protected)
        self._value = QLabel("—")
        value_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        value_font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
        value_font.setFeature("tnum", 1)
        value_font.setFeature("liga", 0)
        self._value.setFont(value_font)
        self._value.setStyleSheet(f"color: {theme.FOREGROUND};")
        layout.addWidget(self._value)
    
    def set_value(self, formatted: str, status: str = "ok") -> None:
        self._value.setText(formatted)
        color = self._status_color(status)
        self._value.setStyleSheet(f"color: {color};")
    
    def _status_color(self, status: str) -> str:
        # DESIGN: RULE-COLOR-002
        return {
            "ok":      theme.FOREGROUND,
            "warning": theme.STATUS_CAUTION,  # legacy source alias
            "caution": theme.STATUS_CAUTION,
            "fault":   theme.STATUS_FAULT,
            "stale":   theme.STATUS_STALE,
        }.get(status, theme.FOREGROUND)
    
    def set_stale(self, stale: bool) -> None:
        """Stale: dim value + add tooltip 'Данные не обновляются'."""
        if stale:
            self._value.setStyleSheet(f"color: {theme.STATUS_STALE};")
            self.setToolTip("Данные не обновляются")
        else:
            self.setToolTip("")
```

## Historical ModeBadge styling sketch (non-canonical)

The shipped badge uses neutral experiment styling and attention styling for
debug/replay. This snippet records the semantic mapping only.

```python
class ModeBadge(QLabel):
    """«Эксперимент» or «Отладка» pill."""
    
    MODE_EXPERIMENT = "experiment"
    MODE_DEBUG = "debug"
    
    _MODE_CONFIG = {
        "experiment": {
            "text": "Эксперимент",
            "bg": "SURFACE_ELEVATED",  # identity, not safety state
            "fg": "FOREGROUND",
        },
        "debug": {
            "text": "Отладка",
            "bg": "STATUS_CAUTION",  # NOT operational — operator attention
            "fg": "ON_DESTRUCTIVE",
        },
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(26)
        self.setMinimumWidth(120)
    
    def set_mode(self, mode: str) -> None:
        cfg = self._MODE_CONFIG[mode]
        bg = getattr(theme, cfg["bg"])
        fg = getattr(theme, cfg["fg"])
        self.setText(cfg["text"])  # DESIGN: RULE-COPY-003 sentence case
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border: none;
                border-radius: {theme.RADIUS_SM}px;
                padding: {theme.SPACE_1}px {theme.SPACE_3}px;
            }}
        """)
```

## Data flow

```
Scheduler / DataBroker (engine process)
           │
           ▼
    ZMQ PUB "vitals"
           │
           ▼
    GUI ZMQ SUB
           │
           ▼
    TopWatchBar.set_pressure()
    TopWatchBar second-stage display (Т12)
    TopWatchBar nitrogen-plate display (Т11)
```

Human-readable presentation must not exceed 2 Hz per RULE-DATA-002. The shipped
channel summary/context refresh is currently 1 Hz; faster engine readings
update the cache without making the digits fly.

Stale detection for this header uses the shipped `_STALE_TIMEOUT_S = 30.0`.
This presentation threshold does not replace backend safety freshness truth.

## Mode badge semantics

| Mode | Meaning | Color | When active |
|---|---|---|---|
| «Эксперимент» | Real operational run — commands have real-world effects, data persisted to archive | Neutral surface/foreground identity treatment | Operator starts real experiment |
| «Отладка» | Debug run — commands execute but no archive entry created | STATUS_CAUTION (amber) | Operator selects Debug mode |
| `REPLAY` | Archived evidence, not a live run | STATUS_CAUTION (legacy `warning` input maps to the same presentation) | Operator opens replay |

**Why badge is critical:** the very same UI affords both real and debug operations. Operator error risk: pressing «АВАР. ОТКЛ.» thinking they're in Debug when actually in Experiment (or vice versa). Persistent visible badge reduces this risk.

## States

| State | Treatment |
|---|---|
| **Normal operation** | Physical values use FOREGROUND; experiment mode is neutral; debug/replay uses STATUS_CAUTION |
| **Cold start / no channel readings** | Diamond cue + persistent «Нет текущих данных · N ожидают» in stale treatment; never seeded or rendered as OK |
| **Vital in caution / legacy warning input** | That vital's value → STATUS_CAUTION color; others unchanged |
| **Vital in fault** | Value → STATUS_FAULT; immediate no-fade (RULE-INTER-006) |
| **Vital stale** | Value → STATUS_STALE; tooltip describes |
| **Engine disconnected** | All three physical readings → STATUS_STALE + explicit unavailable/stale wording; mode badge to `—` greyed |
| **Replay** | `REPLAY` badge is pinned before asynchronous polling and cannot be overwritten by a later live/debug/unknown status result |

## Common mistakes

1. **Using extrema or substitute channels for physical references.** `Т 2-й ступени` is always Т12 and `Т плиты N₂` is always Т11. Т1 / Т7 may be relocated between experiments and must not populate either readout.

2. **Pressure in linear units.** Always scientific notation. (RULE-COPY-006, RULE-DATA-008 note — mandatory log in plots; here scientific display similar rationale).

3. **Mode badge missing.** Without badge, operator can't tell Experiment vs Debug. Always present.

4. **Unbounded pressure formatting.** Use the shipped compact scientific formatter (`1.5e-6`) so exponent zeros do not consume header width. (RULE-DATA-003, RULE-DATA-004)

5. **Animating vital value transitions.** Fade or tween between old and new value. Violates RULE-DATA-001 atomic, RULE-DATA-009 no animation.

6. **Hover on vitals triggers drill-down.** If vitals become clickable via hover, operator opens panels accidentally. Keep non-interactive, or require explicit click.

7. **Experiment identity rendered as safe green.** A running experiment is not proof of safety. Use neutral identity treatment; reserve STATUS_CAUTION for debug/replay attention and safety colors for their locked meanings.

8. **Hiding TopWatchBar under a modal.** Modals do not hide TopWatchBar — the bar stays visible above (outside the modal's overlay). This is deliberate: operator retains situational awareness even inside drill-downs.

9. **Latin T for channel labels.** `T 2-й ступени` with Latin T is invalid; use Cyrillic `Т`. RULE-COPY-001.

## Change-impact record: physical labels

| Field | Assessment |
|---|---|
| Better | The bar names the actual hardware locations and exposes the exact Т12/Т11 provenance; it no longer implies a computed minimum or maximum. |
| Worse | The labels are longer and operators familiar with the terse min/max shorthand need a brief adaptation period. |
| Safety/operator goal | Stable physical identity improves anomaly interpretation and prevents an operator from mistaking one fixed sensor for a fleet-wide extremum. |
| Mitigation and evidence | Preserve the existing order, values, stale treatment, and update cadence; focused widget tests assert both exact Russian labels and channel-to-widget routing. |
| Revert trigger | If the labels clip at the supported minimum viewport or operators cannot identify the two locations in scenario review, adjust spacing or wording without restoring false min/max semantics. |

## Related components

- `cryodaq-primitives/tool-rail.md` — Left counterpart (both are global chrome)
- `cryodaq-primitives/bottom-status-bar.md` — Bottom status complement
- `cryodaq-primitives/sensor-cell.md` — Individual channel cell (similar structure at smaller scale)
- `cryodaq-primitives/alarm-badge.md` — Alarm indicator that might sit near mode badge
- `tokens/layout.md` — HEADER_HEIGHT / TOOL_RAIL_WIDTH coupling

## Changelog

- 2026-07-16: Made the shipped zone layout canonical, removed the stale heater/extrema anatomy, kept experiment identity neutral, and mapped legacy warning input onto the single operator-facing caution rung.
- 2026-07-15: Replaced comparative `Т мин` / `Т макс` copy with physical labels `Т 2-й ступени` (Т12) and `Т плиты N₂` (Т11); recorded the operator/safety tradeoff and retained fixed-channel, stale, and cadence semantics.
- 2026-07-12 (v1.2.0): Cold start no longer seeds channel OK truth; unavailable/stale text plus diamond is shown until real readings arrive. Replay mode is pinned before polling so the archive identity cannot be overwritten.
- 2026-04-17: Initial version. Documents B.4 / B.4.5.2 implementation. 4 fixed vitals (Pressure / T min / T max / Heater) + mode badge. T-min / T-max locked to Т11 / Т12 — positionally fixed reference channels on the second stage (nitrogen plate), not relocatable without dismantling the rheostat. Mode badge distinguishes Experiment from Debug.
- 2026-04-17 (v1.0.1): Fixed `mбар` → `мбар` in pressure invariant (FR-016) — was a typo mixing Latin `m` with Cyrillic `бар`. Code identifier `mbar:` in `set_pressure` API stays Latin (parameter name).
