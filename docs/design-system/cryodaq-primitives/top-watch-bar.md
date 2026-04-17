---
title: TopWatchBar
keywords: top-bar, watch-bar, header, chrome, vitals, at-a-glance, pressure, temperature, heater, mode-badge
applies_to: top chrome strip showing global vitals + mode badge
status: active
implements: src/cryodaq/gui/shell/top_watch_bar.py (Phase B.4/B.4.5.2)
last_updated: 2026-04-17
references: rules/data-display-rules.md, rules/color-rules.md, rules/content-voice-rules.md
---

# TopWatchBar

Horizontal chrome strip at the top of every screen. Shows 4 global vital readings + current mode badge. Visible from every overlay, acts as persistent operator situational awareness surface.

> **Implementation status.** The shipped TopWatchBar at
> `src/cryodaq/gui/shell/top_watch_bar.py` is aligned with this spec:
> height = `HEADER_HEIGHT` (56px), pressure formatted in `мбар`
> (Cyrillic), `Т мин` / `Т макс` locked to `Т11` / `Т12` (positionally
> fixed reference channels), no emoji in the alarms cell. The bar
> still uses a zone-based layout (engine / experiment+phase / time
> window / channel summary / alarms) with an inserted persistent
> context strip, rather than the canonical 4-vital-cell + mode-badge
> anatomy shown above. Moving to the 4-cell anatomy is tracked as
> later Phase II work.

**When to use:**
- Single instance in `MainWindow`, always visible at the top
- Any overlay should NOT hide the TopWatchBar — it's global chrome

**When NOT to use:**
- Don't instantiate multiple copies; it's a singleton of the shell
- Don't use as a generic header for panels (panels use their own Card header or breadcrumb)

## Anatomy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  Давление         Т мин         Т макс         Нагреватель    [Эксперимент] │
│  1.23e-06 мбар    4.21 K        77.3 K         0.125 Вт                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
  ◀── height: HEADER_HEIGHT (56)
  ◀── background: SURFACE_CARD (matches top edge of main content)
  ◀── border-bottom: 1px BORDER
  ◀── padding-left: coincides with TOOL_RAIL_WIDTH (56) — starts after left rail
  ◀── 4 vital slots evenly distributed + mode badge right-aligned
```

Width of each vital slot: `(available_width - mode_badge_width) / 4` minus gap.

## Parts

| Part | Required | Description |
|---|---|---|
| **Bar frame** | Yes | Horizontal strip, `HEADER_HEIGHT` tall, spans viewport width |
| **Vital cells** | 4 fixed | ДАВЛЕНИЕ, Т МИН, Т МАКС, НАГРЕВАТЕЛЬ — in that order |
| **Mode badge** | Yes | Right-aligned pill: «Эксперимент» or «Отладка» |
| **Divider** | Implicit | 1px bottom border separates bar from main content |

## Invariants

1. **Height = HEADER_HEIGHT (56).** Coupled to TOOL_RAIL_WIDTH per RULE-SPACE-006 (corner square).
2. **Exactly 4 vital cells.** Order is fixed: Pressure → T min → T max → Heater. Changing count or order requires product decision; operator muscle memory forms here.
3. **Pressure always in мбар, scientific notation.** (RULE-COPY-006, RULE-DATA-005)
4. **T min / T max use Т11 and Т12.** These are the positionally fixed reference channels — physically immovable on the second stage (nitrogen plate); cannot be relocated without dismantling the rheostat. All temperature channels are metrologically calibrated, but other channels may change position between experiments, making them unsuitable as fixed quantitative reference points. Using other channels for T min / T max thresholds is a domain violation (architect-level rule, see channels.yaml).
5. **Mode badge always visible.** Even during fault states. Operator must always know whether actions have real-world consequences.
6. **Instant fault rendering.** If a vital goes into fault, color changes immediately — no fade. (RULE-INTER-006)
7. **Tabular numbers.** Vital values use FONT_MONO_VALUE with tnum. (RULE-TYPO-003, RULE-DATA-003)
8. **UPPERCASE category labels** with letter-spacing. «ДАВЛЕНИЕ», «НАГРЕВАТЕЛЬ». (RULE-TYPO-005, RULE-TYPO-008)
9. **Not interactive by default.** Clicking vitals does nothing, or opens related drill-down if enabled. Not a tab or button.
10. **No background shift on hover.** Bar is chrome, not interactive surface.

## Layout structure

```
Bar frame (HBoxLayout)
├── Spacer to align with TOOL_RAIL_WIDTH (leaves left rail space)
├── Vital cell: Pressure      (fixed relative width or equal-stretch)
├── Vital cell: T min         (fixed relative width)
├── Vital cell: T max
├── Vital cell: Heater
├── Stretch
└── Mode badge                (right-aligned, fixed width)
```

## Vital cell anatomy

Each of the 4 vitals uses the same layout:

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

## API (proposed)

```python
# src/cryodaq/gui/shell/top_watch_bar.py

class VitalCell(QWidget):
    """One of the four vital slots."""
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
    def set_tmin(self, kelvin: float, status: str = "ok") -> None: ...
    def set_tmax(self, kelvin: float, status: str = "ok") -> None: ...
    def set_heater(self, watts: float, status: str = "ok") -> None: ...
    def set_mode(self, mode: str) -> None: ...
    def set_stale_vital(self, vital_key: str, stale: bool) -> None: ...
```

## Reference implementation sketch

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
        
        # 4 vital cells in fixed order
        self._pressure = VitalCell("ДАВЛЕНИЕ")
        self._tmin = VitalCell("Т МИН")
        self._tmax = VitalCell("Т МАКС")
        self._heater = VitalCell("НАГРЕВАТЕЛЬ")
        
        for cell in (self._pressure, self._tmin, self._tmax, self._heater):
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
            "warning": theme.STATUS_WARNING,
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

## ModeBadge reference

```python
class ModeBadge(QLabel):
    """«Эксперимент» or «Отладка» pill."""
    
    MODE_EXPERIMENT = "experiment"
    MODE_DEBUG = "debug"
    
    _MODE_CONFIG = {
        "experiment": {
            "text": "Эксперимент",
            "bg": "STATUS_OK",     # operational
            "fg": "ON_DESTRUCTIVE",
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
    TopWatchBar.set_tmin()
    TopWatchBar.set_tmax()
    TopWatchBar.set_heater()
```

Update frequency: 2Hz per RULE-DATA-002. If engine pushes faster, GUI coalesces.

Stale detection: if no update in `stale_timeout_s` (from safety.yaml, default 10s), mark vital as stale.

## Mode badge semantics

| Mode | Meaning | Color | When active |
|---|---|---|---|
| «Эксперимент» | Real operational run — commands have real-world effects, data persisted to archive | STATUS_OK (green) | Operator starts real experiment |
| «Отладка» | Debug run — commands execute but no archive entry created | STATUS_CAUTION (amber) | Operator selects Debug mode |

**Why badge is critical:** the very same UI affords both real and debug operations. Operator error risk: pressing «АВАР. ОТКЛ.» thinking they're in Debug when actually in Experiment (or vice versa). Persistent visible badge reduces this risk.

## States

| State | Treatment |
|---|---|
| **Normal operation** | All vitals FOREGROUND, mode badge STATUS_OK or STATUS_CAUTION |
| **Vital in warning** | That vital's value → STATUS_WARNING color; others unchanged |
| **Vital in fault** | Value → STATUS_FAULT; immediate no-fade (RULE-INTER-006) |
| **Vital stale** | Value → STATUS_STALE; tooltip describes |
| **Engine disconnected** | All 4 vitals → STATUS_STALE + tooltip "Нет связи с engine"; mode badge to `—` greyed |

## Common mistakes

1. **Using Т1 or Т7 for T-min / T-max thresholds.** These channels may be relocated between experiments (operator-moveable placement). Т11 / Т12 are the only physically fixed reference channels. Hardcoded channel IDs for T-min / T-max in TopWatchBar backend.

2. **Pressure in linear units.** Always scientific notation. (RULE-COPY-006, RULE-DATA-008 note — mandatory log in plots; here scientific display similar rationale).

3. **Mode badge missing.** Without badge, operator can't tell Experiment vs Debug. Always present.

4. **Variable-width pressure readout.** "1.2e-5" vs "1.23e-05" vs "1.234e-05" — different widths. Use fixed format `{:.2e}` always. (RULE-DATA-003, RULE-DATA-004)

5. **Animating vital value transitions.** Fade or tween between old and new value. Violates RULE-DATA-001 atomic, RULE-DATA-009 no animation.

6. **Hover on vitals triggers drill-down.** If vitals become clickable via hover, operator opens panels accidentally. Keep non-interactive, or require explicit click.

7. **Mode badge color = ACCENT.** ACCENT is focus only (RULE-COLOR-004). Mode uses STATUS_OK / STATUS_CAUTION.

8. **Hiding TopWatchBar under a modal.** Modals do not hide TopWatchBar — the bar stays visible above (outside the modal's overlay). This is deliberate: operator retains situational awareness even inside drill-downs.

9. **Latin T for channel labels.** "T MIN" with Latin T; should be "Т МИН" with Cyrillic. RULE-COPY-001.

## Related components

- `cryodaq-primitives/tool-rail.md` — Left counterpart (both are global chrome)
- `cryodaq-primitives/bottom-status-bar.md` — Bottom status complement
- `cryodaq-primitives/sensor-cell.md` — Individual channel cell (similar structure at smaller scale)
- `cryodaq-primitives/alarm-badge.md` — Alarm indicator that might sit near mode badge
- `tokens/layout.md` — HEADER_HEIGHT / TOOL_RAIL_WIDTH coupling

## Changelog

- 2026-04-17: Initial version. Documents B.4 / B.4.5.2 implementation. 4 fixed vitals (Pressure / T min / T max / Heater) + mode badge. T-min / T-max locked to Т11 / Т12 — positionally fixed reference channels on the second stage (nitrogen plate), not relocatable without dismantling the rheostat. Mode badge distinguishes Experiment from Debug.
- 2026-04-17 (v1.0.1): Fixed `mбар` → `мбар` in pressure invariant (FR-016) — was a typo mixing Latin `m` with Cyrillic `бар`. Code identifier `mbar:` in `set_pressure` API stays Latin (parameter name).
