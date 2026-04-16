---
title: AlarmBadge
keywords: alarm, badge, notification, count, bell, indicator, active-alarms, header
applies_to: header-area alarm count indicator
status: partial
implements: legacy inline bell indicator (recently cleaned of emoji per Phase 0 decision)
last_updated: 2026-04-17
---

# AlarmBadge

Compact indicator showing active alarm count, typically embedded near the TopWatchBar or in a dashboard corner. Clicking opens the full Alarms panel.

**When to use:**
- Top chrome area — companion to TopWatchBar, high-visibility location
- Persistent presence whenever alarms might fire (always visible, not conditional)
- Quick-glance «how many things need attention right now»

**When NOT to use:**
- Inside sensor cells or per-channel widgets — those use their own state via border/color (RULE-A11Y-002)
- Transient «just fired» notification — use `Toast` for the firing event, AlarmBadge reflects persistent count
- Acknowledged / cleared alarms — badge shows ACTIVE count only

## AlarmBadge vs Toast vs Dialog

| Event | Where | Pattern |
|---|---|---|
| Alarm fires (new) | Toast (transient, 5s) AND AlarmBadge count increments | Two signal channels |
| Alarm persists | AlarmBadge count visible | Persistent |
| Critical fault requires ack | Dialog alert | Blocking |
| Operator reviews alarms | Alarms panel (opened from badge click or ToolRail) | Full detail |

AlarmBadge is the persistent count reflecting the current state. Toast is the "just now" announcement. Dialog is forced acknowledgement.

## Anatomy

```
 Default (with alarms):                 Empty (no alarms):
┌─────────────────────┐                ┌─────────────────────┐
│                     │                │                     │
│   🔔  3             │                │   🔔                 │
│   └─  └── count     │                │   └── bell icon      │
│   bell icon         │                │       MUTED_FOREGROUND│
│                     │                │       dim             │
└─────────────────────┘                └─────────────────────┘
  bg: STATUS_WARNING                     bg: transparent
  text: ON_DESTRUCTIVE                   no border
  radius: RADIUS_SM                      hover: MUTED bg
  padding: SPACE_1 SPACE_2
  cursor: PointingHandCursor
  height: ~28-30 (fits in bottom-bar
          or top-bar inline contexts)
```

Note: 🔔 in diagram shows position; actual implementation uses Lucide `bell` SVG, NOT the emoji. RULE-COPY-005.

## Parts

| Part | Required | Description |
|---|---|---|
| **Container frame** | Yes | Clickable widget; pill-shaped when alarms present, icon-only when empty |
| **Bell icon** | Yes | Lucide `bell` SVG, color inherits from state |
| **Count label** | When count > 0 | Numeric count in FONT_MONO_VALUE |
| **Severity hint** | Optional | Color ramp: 1 alarm = WARNING, any FAULT = FAULT; when no alarms, MUTED_FOREGROUND |

## Invariants

1. **No emoji.** Lucide `bell` SVG only. (RULE-COPY-005)
2. **Clickable — cursor PointingHand.** Opens Alarms panel on click. (RULE-INTER-011)
3. **Tooltip mandatory** since this is icon-primary. Tooltip: «3 активные тревоги» or «Нет активных тревог». (RULE-INTER-008)
4. **Color reflects worst severity present.** 5 warnings + 0 faults → STATUS_WARNING. 1 fault + 10 warnings → STATUS_FAULT. Highest severity wins.
5. **Count uses tabular mono font.** Prevents width jitter as count increments. (RULE-TYPO-003)
6. **Two-channel signal: icon + count.** Not color alone. (RULE-A11Y-002)
7. **Fires instantly, no fade.** State transitions are fault events. (RULE-INTER-006)
8. **Empty state stays visible.** Don't hide badge when 0 alarms — operator needs to see that the system is watching. Just dim.
9. **Click shortcut: Ctrl+A** (or similar). Register per keyboard-shortcuts registry.
10. **No animation for count changes.** Old count snaps to new count. No tween. (RULE-DATA-001, RULE-DATA-009)

## API (proposed)

```python
# src/cryodaq/gui/widgets/alarm_badge.py

@dataclass
class AlarmSummary:
    total_active: int           # total count across all severities
    fault_count: int            # faulted alarms
    warning_count: int          # warnings
    caution_count: int          # cautions


class AlarmBadge(QWidget):
    """Header alarm count indicator."""
    
    clicked = Signal()  # emitted on click; consumer opens Alarms panel
    
    def __init__(self, parent: QWidget | None = None) -> None: ...
    
    def set_summary(self, summary: AlarmSummary) -> None:
        """Update count and worst-severity color. Atomic."""
```

## Reference implementation

```python
class AlarmBadge(QWidget):
    clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary = AlarmSummary(0, 0, 0, 0)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1)
        row.setSpacing(theme.SPACE_1)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # DESIGN: RULE-COPY-005 — Lucide bell SVG, not emoji
        # DESIGN: RULE-COLOR-005 — icon color inherits (recolored per severity)
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._icon_label)
        
        # DESIGN: RULE-TYPO-003 — tnum for count
        self._count_label = QLabel("")
        count_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        count_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
        count_font.setFeature("tnum", 1)
        count_font.setFeature("liga", 0)
        self._count_label.setFont(count_font)
        row.addWidget(self._count_label)
        
        self._apply_state()
    
    def set_summary(self, summary: AlarmSummary) -> None:
        self._summary = summary
        # DESIGN: RULE-DATA-001 atomic
        self._apply_state()
    
    def _apply_state(self) -> None:
        s = self._summary
        
        # Determine worst severity present
        if s.fault_count > 0:
            severity = "fault"
            bg_color = theme.STATUS_FAULT
            fg_color = theme.ON_DESTRUCTIVE
            icon_color = theme.ON_DESTRUCTIVE
        elif s.warning_count > 0:
            severity = "warning"
            bg_color = theme.STATUS_WARNING
            fg_color = theme.ON_DESTRUCTIVE
            icon_color = theme.ON_DESTRUCTIVE
        elif s.caution_count > 0:
            severity = "caution"
            bg_color = theme.STATUS_CAUTION
            fg_color = theme.ON_DESTRUCTIVE
            icon_color = theme.ON_DESTRUCTIVE
        else:
            severity = "empty"
            bg_color = "transparent"
            fg_color = theme.MUTED_FOREGROUND
            icon_color = theme.MUTED_FOREGROUND
        
        # Update icon color
        pixmap = load_colored_icon("bell", color=icon_color).pixmap(
            theme.ICON_SIZE_SM, theme.ICON_SIZE_SM
        )
        self._icon_label.setPixmap(pixmap)
        
        # Update count label
        if s.total_active > 0:
            self._count_label.setText(str(s.total_active))
            self._count_label.setVisible(True)
        else:
            self._count_label.setVisible(False)
        self._count_label.setStyleSheet(f"color: {fg_color};")
        
        # Update container style
        if severity == "empty":
            style = f"""
                AlarmBadge {{
                    background: transparent;
                    border: none;
                    border-radius: {theme.RADIUS_SM}px;
                }}
                AlarmBadge:hover {{
                    background: {theme.MUTED};
                }}
            """
        else:
            style = f"""
                AlarmBadge {{
                    background: {bg_color};
                    border: none;
                    border-radius: {theme.RADIUS_SM}px;
                }}
            """
        self.setStyleSheet(style)
        
        # Tooltip
        # DESIGN: RULE-COPY-003, RULE-INTER-008
        if s.total_active == 0:
            self.setToolTip("Нет активных тревог")
        else:
            parts = []
            if s.fault_count:
                parts.append(f"{s.fault_count} аварий")
            if s.warning_count:
                parts.append(f"{s.warning_count} предупреждений")
            if s.caution_count:
                parts.append(f"{s.caution_count} замечаний")
            self.setToolTip(
                f"{s.total_active} активных тревог: {', '.join(parts)} (Ctrl+A)"
            )
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
```

## Severity ramp

```
fault ≥ 1  →  STATUS_FAULT    (red pill)
fault = 0, warning ≥ 1  →  STATUS_WARNING  (amber pill)
fault = 0, warning = 0, caution ≥ 1  →  STATUS_CAUTION  (orange pill)
all counts = 0  →  transparent + dim icon
```

This ensures operator sees the worst severity at a glance, not a mixed-color ambiguity.

## Placement in layout

Typical positions:
- **Top-right** of TopWatchBar area, next to mode badge
- **Standalone row** above main content (less common)
- **Inside dashboard tile header** (if dashboard has an "alerts" region)

The badge is small (height ~30, width depends on count digits). Fits naturally in existing chrome areas.

## States

| State | Visual treatment |
|---|---|
| **No alarms** | Transparent bg, dim bell icon, no count. Hover: MUTED bg |
| **Caution only** | STATUS_CAUTION pill, count visible, icon + text high-contrast |
| **Warning present** | STATUS_WARNING pill |
| **Fault present** | STATUS_FAULT pill |
| **Click (pressed)** | Pressed state ~100ms, then opens panel |
| **Focus** | 2px ACCENT border (via :focus) replacing normal border |
| **Disabled** | Should not be disabled; if system offline, show stale state via count «—» |

## Integration

```
Engine Alarm Engine
    └── publishes via ZMQ: alarms.summary
             {"total_active": N, "fault_count": ..., ...}
                     │
                     ▼
             GUI subscribes
                     │
                     ▼
             AlarmBadge.set_summary(summary)

User clicks badge:
    AlarmBadge.clicked  →  ToolRail or MainWindow handler  →  navigate to Alarms panel
```

Shortcut: `Ctrl+A` should also activate the same behavior (open Alarms panel), registered via tool-rail or application-level.

## Common mistakes

1. **Emoji bell 🔔.** Phase 0 explicitly removed this. Use Lucide `bell`. RULE-COPY-005.

2. **Fading / pulsing when alarms fire.** Pulse animations distract from fault state. Snap + persistent color is adequate. RULE-INTER-006.

3. **Count text in raw variable-width digits.** «9 → 10 → 11» causes layout shift. Use FONT_MONO + tnum. RULE-TYPO-003.

4. **Color only, no count.** Red pill with no number. Operator doesn't know if it's 1 fault or 50. Always show count when > 0.

5. **Hiding badge when empty.** Operator can't verify system is watching. Empty badge = dim bell + no count, but still rendered. Zero-count is information.

6. **Mixed severity via gradient.** Gradient from amber to red showing mix. Use single color of worst severity. Mixing is ambiguous.

7. **Badge as static widget with no click.** Operator sees something is wrong but can't navigate to details without hunting for the Alarms panel. Always clickable.

8. **Missing tooltip.** Icon-primary widget without tooltip fails RULE-INTER-008. Tooltip must describe count and severity.

9. **Showing non-active alarms.** Acknowledged, cleared, or historical alarms don't count here. Only active.

10. **Placing badge in ToolRail slot.** ToolRail slots are navigation, not live counters. Place AlarmBadge near TopWatchBar. ToolRail's alarm slot opens the panel; that's a different concept.

## Related components

- `cryodaq-primitives/top-watch-bar.md` — Typical neighbor location
- `cryodaq-primitives/sensor-cell.md` — Individual cell state (per-channel fault)
- `components/toast.md` — Transient «just fired» announcement
- `components/dialog.md` — Blocking acknowledgement of critical alarm
- `tokens/icons.md` — Lucide bell icon

## Changelog

- 2026-04-17: Initial version. Documents the post-Phase-0 emoji removal. Severity ramp rules codified. Cursor / click / tooltip / keyboard shortcut patterns specified. Empty state kept visible (dim) per operator situational awareness requirement.
