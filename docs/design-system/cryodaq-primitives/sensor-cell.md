---
title: SensorCell
keywords: sensor, cell, channel, temperature, pressure, reading, kelvin, tile, grid-item, cold, warm
applies_to: single-channel data cell widget
status: active
implements: src/cryodaq/gui/shell/overlays/_design_system/dynamic_sensor_grid.py (Phase B.3)
last_updated: 2026-04-17
---

# SensorCell

Smallest atom of the sensor grid. Displays one channel: channel ID (Cyrillic Т#) + current value + unit + state-aware color. Appears in grids of many at once (DynamicSensorGrid with 24 channels, typical 14 visible).

**When to use:**
- Inside DynamicSensorGrid on dashboard
- Anywhere a single channel's current value needs compact, at-a-glance display
- Alarm panels showing which channels are in fault

**When NOT to use:**
- Historical / plotted data — use `ChartTile`
- Controllable output (not a readout) — use `InputField` or a dedicated SMU widget
- Hero-sized single reading (takes up big area) — use `ExecutiveKpiTile` in BentoGrid instead

## Anatomy

```
┌───────────────────────┐
│                       │
│  Т11                  │ ◀── channel ID (Cyrillic Т)
│                       │     FONT_LABEL_SIZE, MUTED_FOREGROUND
│  4.21 K               │ ◀── value + unit
│                       │     FONT_MONO_VALUE_SIZE (15)
│  Теплообменник 1      │     tnum, color varies by status
│                       │ ◀── optional friendly name
└───────────────────────┘     FONT_SIZE_XS (11), MUTED_FOREGROUND
  ◀── RADIUS_SM (4) — smallest in cascade
  ◀── padding: SPACE_2 all sides
  ◀── background: varies by state
```

Minimum cell size: ~120×64px. Maximum: grid-determined. At 8 cells per row, ~240px wide each.

## Parts

| Part | Required | Description |
|---|---|---|
| **Cell frame** | Yes | Small rounded rect with status-aware surface |
| **Channel ID** | Yes | «Т1», «Т11», «Т24» — Cyrillic letter always |
| **Value + unit** | Yes | «4.21 K», «1.23e-06 мбар», «0.125 Вт» |
| **Friendly name** | Optional | Second-line descriptor from channels.yaml (e.g. «Теплообменник 1») |
| **Cold/warm indicator** | Conditional | 3px left edge color or icon distinguishing cold (is_cold=true) from warm channels |

## Invariants

1. **Channel ID uses Cyrillic Т (U+0422).** Never Latin T. (RULE-COPY-001)
2. **Value format fixed per unit.** Temperature `{:.2f} K`, pressure `{:.2e} мбар`, voltage `{:.3f} В`. (RULE-DATA-004, RULE-COPY-006)
3. **Tabular numbers.** FONT_MONO_VALUE with `tnum` feature. Digits don't shift width. (RULE-TYPO-003, RULE-DATA-003)
4. **Atomic value updates.** No tween, no count-up animation. Snap. (RULE-DATA-001, RULE-DATA-009)
5. **Color always paired with value change.** Fault → red; warning → amber; stale → grey. But color alone is insufficient — pair with icon or dedicated indicator for accessibility. (RULE-A11Y-002)
6. **RADIUS_SM (4)** subordinate in cascade when inside BentoTile (RADIUS_MD=6) or Card (RADIUS_LG=8). (RULE-SURF-006)
7. **Positionally fixed reference channels matter.** Т11 / Т12 are the only channels with guaranteed fixed physical location — mounted on the second stage (nitrogen plate), cannot be relocated without dismantling the rheostat. All temperature channels are metrologically calibrated, but other channels may change position between experiments, which disqualifies them as fixed reference points for quantitative thresholds. SensorCell itself does not enforce consumer policy — but consumers (TopWatchBar T-min / T-max, alarm thresholds) must prefer Т11 / Т12 for cross-experiment quantitative comparisons. Document in tooltip.
8. **No emoji / no icon in default state.** Clean. Icon prefix only when channel has a specific state to communicate (fault icon next to value if fault). (RULE-COPY-005)
9. **Height default = ROW_HEIGHT × 1.8** or so — enough for 2-3 lines of stacked text. Not exactly ROW_HEIGHT (which is buttons).
10. **Interactive on click/double-click** — click shows hover info (popover), double-click opens full channel diagnostic. Single-click on cell must NOT execute destructive command.

## Visual state matrix

| State | Border | Background | Value color | Friendly name color |
|---|---|---|---|---|
| **OK** (normal) | 1px BORDER | SURFACE_CARD | FOREGROUND | MUTED_FOREGROUND |
| **Warning** (approaching limit) | 1px STATUS_WARNING | SURFACE_CARD | STATUS_WARNING | MUTED_FOREGROUND |
| **Caution** | 1px STATUS_CAUTION | SURFACE_CARD | STATUS_CAUTION | MUTED_FOREGROUND |
| **Fault** (hard limit exceeded) | 2px STATUS_FAULT | SURFACE_CARD | FOREGROUND* | MUTED_FOREGROUND |
| **Stale** (not updating) | 1px BORDER | SURFACE_CARD | STATUS_STALE | STATUS_STALE |
| **Disconnected** | 1px dashed BORDER | MUTED | TEXT_DISABLED | TEXT_DISABLED |
| **Cold channel (is_cold=true)** | same border + 3px left edge COLD_HIGHLIGHT | — | — | — |

\* For fault state, value stays FOREGROUND and border becomes 2px STATUS_FAULT — two-channel redundancy (border + icon prefix). Making value text STATUS_FAULT would fail body contrast (3.94:1 per RULE-A11Y-003).

## API (proposed)

```python
# src/cryodaq/gui/widgets/sensor_cell.py

@dataclass
class SensorReading:
    channel_id: str        # "Т11" (Cyrillic)
    friendly_name: str     # "Теплообменник 1"
    is_cold: bool          # from channels.yaml
    unit: str              # "K", "мбар", "Вт", "В", "А"
    precision: int         # decimal places (2 for temp, -1 for scientific)
    value: float | None    # None = no data yet
    status: str            # "ok" | "warning" | "caution" | "fault" | "stale" | "disconnected"
    last_update_t: float | None


class SensorCell(QFrame):
    """Single-channel data cell."""
    
    clicked = Signal(str)         # emits channel_id
    double_clicked = Signal(str)  # emits channel_id (for diagnostic drill-down)
    
    def __init__(
        self,
        reading: SensorReading,
        parent: QWidget | None = None,
        *,
        show_friendly_name: bool = True,
    ) -> None: ...
    
    def update_reading(self, reading: SensorReading) -> None:
        """Update displayed value + status. Atomic — no animation."""
```

## Reference implementation

```python
class SensorCell(QFrame):
    clicked = Signal(str)
    double_clicked = Signal(str)
    
    def __init__(self, reading: SensorReading, parent=None, *, show_friendly_name=True):
        super().__init__(parent)
        self._reading = reading
        self._show_friendly_name = show_friendly_name
        
        self.setObjectName("sensorCell")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(120, 64)
        
        layout = QVBoxLayout(self)
        # DESIGN: RULE-SURF-003 symmetric
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        layout.setSpacing(0)
        
        # Channel ID row
        # DESIGN: RULE-COPY-001 — Cyrillic Т
        self._id_label = QLabel(reading.channel_id)
        id_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        id_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
        self._id_label.setFont(id_font)
        self._id_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(self._id_label)
        
        # Value row
        # DESIGN: RULE-TYPO-003 tnum, RULE-TYPO-007 off-scale 15px protected
        self._value_label = QLabel(self._format_value(reading))
        value_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        value_font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
        value_font.setFeature("tnum", 1)
        value_font.setFeature("liga", 0)
        self._value_label.setFont(value_font)
        layout.addWidget(self._value_label)
        
        # Friendly name row (optional)
        self._name_label: QLabel | None = None
        if show_friendly_name and reading.friendly_name:
            self._name_label = QLabel(reading.friendly_name)
            name_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_XS)
            self._name_label.setFont(name_font)
            self._name_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            layout.addWidget(self._name_label)
        
        layout.addStretch()
        self._apply_style()
        self._apply_tooltip()
    
    def _format_value(self, r: SensorReading) -> str:
        if r.value is None:
            return "—"
        
        # DESIGN: RULE-COPY-006 (SI units, Russian where applicable)
        # DESIGN: RULE-DATA-004 (fixed precision per quantity)
        if r.unit == "K":
            return f"{r.value:.2f} K"
        elif r.unit == "мбар":
            return f"{r.value:.2e} мбар"
        elif r.unit == "Вт":
            return f"{r.value:.3f} Вт"
        elif r.unit == "В":
            return f"{r.value:.3f} В"
        elif r.unit == "А":
            return f"{r.value:.3f} А"
        else:
            return f"{r.value} {r.unit}"
    
    def _apply_style(self) -> None:
        r = self._reading
        # DESIGN: RULE-COLOR-001, RULE-COLOR-002
        border_color, border_width = self._border_for_status(r.status)
        bg = theme.SURFACE_CARD if r.status != "disconnected" else theme.MUTED
        value_color = self._value_color_for_status(r.status)
        
        # Cold-channel 3px left accent
        # DESIGN: RULE-COLOR-009 — COLD_HIGHLIGHT distinct from STATUS_INFO
        left_accent = f"3px solid {theme.COLD_HIGHLIGHT};" if r.is_cold else "0"
        
        self.setStyleSheet(f"""
            #sensorCell {{
                background: {bg};
                border: {border_width}px solid {border_color};
                border-left: {left_accent};
                border-radius: {theme.RADIUS_SM}px;
            }}
        """)
        self._value_label.setStyleSheet(f"color: {value_color};")
    
    def _border_for_status(self, status: str) -> tuple[str, int]:
        if status == "fault":
            return (theme.STATUS_FAULT, 2)  # thicker border for fault attention
        elif status == "warning":
            return (theme.STATUS_WARNING, 1)
        elif status == "caution":
            return (theme.STATUS_CAUTION, 1)
        else:
            return (theme.BORDER, 1)
    
    def _value_color_for_status(self, status: str) -> str:
        # DESIGN: RULE-A11Y-003 — STATUS_FAULT fails body contrast; use FOREGROUND + border
        if status in ("warning", "caution"):
            return getattr(theme, f"STATUS_{status.upper()}")
        elif status == "stale":
            return theme.STATUS_STALE
        elif status == "disconnected":
            return theme.TEXT_DISABLED
        else:
            # ok or fault: FOREGROUND (fault also uses border + icon for redundancy)
            return theme.FOREGROUND
    
    def _apply_tooltip(self) -> None:
        r = self._reading
        # DESIGN: RULE-INTER-008 tooltip informative
        lines = [
            f"{r.channel_id} — {r.friendly_name}",
            f"Единица: {r.unit}",
            f"Тип: {'Холодный' if r.is_cold else 'Тёплый'}",
        ]
        if r.channel_id in ("Т11", "Т12"):
            lines.append("✓ Неподвижный опорный канал (вторая ступень, азотная плита)")
        if r.last_update_t:
            age = time.time() - r.last_update_t
            lines.append(f"Последнее обновление: {age:.1f}с назад")
        self.setToolTip("\n".join(lines))
    
    def update_reading(self, reading: SensorReading) -> None:
        self._reading = reading
        # DESIGN: RULE-DATA-001 atomic update
        self._value_label.setText(self._format_value(reading))
        self._apply_style()
        self._apply_tooltip()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._reading.channel_id)
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._reading.channel_id)
        super().mouseDoubleClickEvent(event)
```

## Integration with DynamicSensorGrid

Phase B.3 implementation details to preserve:

- **Responsive 8-column grid** at default viewport
- **Hidden channels** (channels.yaml `visible: false`) not rendered
- **Double-click rename** inline edit of friendly name (updates channels.yaml via engine roundtrip)
- **Right-click context menu** with «Скрыть», «Переименовать», «Диагностика»

These are properties of the parent grid, not SensorCell itself; they call back into SensorCell's interface.

## Fault annotation pattern (RULE-A11Y-002 redundant channel)

When status is `fault`, add a small icon inline next to channel ID for icon + color + border = 3 redundant channels:

```python
if r.status == "fault":
    id_row = QHBoxLayout()
    id_row.setContentsMargins(0, 0, 0, 0)
    id_row.setSpacing(theme.SPACE_1)
    
    fault_icon = QLabel()
    fault_icon.setPixmap(
        load_colored_icon("alert-triangle", color=theme.STATUS_FAULT)
          .pixmap(theme.ICON_SIZE_XS, theme.ICON_SIZE_XS)
    )
    id_row.addWidget(fault_icon)
    id_row.addWidget(self._id_label)
    id_row.addStretch()
```

## Common mistakes

1. **Latin T in channel ID.** `QLabel("T11")` with Latin T. Should be Cyrillic `"Т11"`. RULE-COPY-001.

2. **Precision drift.** `f"{v}"` instead of `f"{v:.2f}"` — digit count varies, cell width jitters. RULE-DATA-004.

3. **Value text in STATUS_FAULT color.** Body-size STATUS_FAULT text fails AA contrast (3.94:1). Keep value FOREGROUND; signal fault via border + icon. RULE-A11Y-003.

4. **Color as only fault signal.** Red value with no other indicator. Color-blind operators miss it. Pair with border thickness + icon. RULE-A11Y-002.

5. **Alarm firing on relocatable channel for fixed-threshold decisions.** Quantitative cross-experiment alarm on Т5 (a relocatable channel). Threshold that's meaningful in one experiment layout may be meaningless in the next if the sensor moved. Safety rule at safety engine level; display-level cue: SensorCell tooltip should mark Т11 / Т12 as «Неподвижный опорный канал» so alarm panels know which cells are position-stable reference points.

6. **COLD_HIGHLIGHT 3px on right edge.** Tested on left edge per layout convention (color coding leads the value). Right edge reads as a decoration.

7. **Scientific notation for temperature.** `4.21e+00 K` is wrong. Temperature is `{:.2f} K`. Only pressure uses scientific.

8. **Tween animation on fault transition.** Fault must appear instantly. RULE-INTER-006 + RULE-DATA-001.

9. **Missing unit space.** `4.21K` (no space) violates RULE-COPY-006. Always `4.21 K` with space.

10. **Disabled cursor on clickable cell.** Default cursor signals no interaction — use `PointingHandCursor` if cell responds to click. RULE-INTER-011.

## Related components

- `components/bento-tile.md` — DataDenseTile variant often hosts SensorCell grid
- `components/bento-grid.md` — The layout engine wrapping
- `cryodaq-primitives/alarm-badge.md` — Alarms reference specific SensorCells
- `tokens/colors.md` — STATUS_*, COLD_HIGHLIGHT definitions
- `channels.yaml` — Configuration source for channel_id, friendly_name, is_cold

## Changelog

- 2026-04-17: Initial version. Documents Phase B.3 implementation (DynamicSensorGrid with responsive 8-column). Cold/warm distinction via COLD_HIGHLIGHT left edge. Positionally fixed reference status surfaced in tooltip for Т11 / Т12 («Неподвижный опорный канал»). Fault state uses border + icon + color redundancy.
