---
title: Badge
keywords: badge, chip, status, label, count, indicator, pill
applies_to: static status and count indicators
status: partial
implements: inline status labels in dashboard and experiment overlay (formalization pending)
last_updated: 2026-04-17
references: rules/color-rules.md, rules/typography-rules.md, tokens/colors.md
---

# Badge

Small static chip that communicates status, count, or category. Display-only; not interactive.

**When to use:**
- Status label: «НОРМА», «ВНИМАНИЕ», «АВАРИЯ», «УСТАРЕЛО»
- Count indicator: «3 тревоги», «12 каналов» 
- Category tag: «Эксперимент», «Калибровка», «Диагностика»
- Phase indicator in compact form (inline, not the full phase-stepper widget)

**When NOT to use:**
- Clickable — if user can click it, use a `Button` (icon-only if tiny)
- Large informational panel — use a `Card` with content
- Count in a number readout context — use a numeric display with proper font presets
- Progress indication — use a progress bar, not a badge

## Anatomy

```
 Status badge (filled)           Status badge (outline)        Count badge
┌──────────────┐                ┌──────────────────┐          ┌───┐
│   АВАРИЯ     │                │    ВНИМАНИЕ       │          │ 3 │  Тревоги
└──────────────┘                └──────────────────┘          └───┘
 bg: STATUS_FAULT                bg: transparent                bg: STATUS_WARNING
 text: ON_DESTRUCTIVE            border: 1px STATUS_WARNING     text: ON_*
 letter-spacing: 0.05em          text: STATUS_WARNING           small numeric font
 font-weight: SEMIBOLD           letter-spacing: 0.05em
 padding: SPACE_1 SPACE_2        padding: SPACE_1 SPACE_2
 height: ~22-24px                height: ~22-24px
 radius: RADIUS_SM               radius: RADIUS_SM

 Inline indicator (dot + label)
 ● Норма                ◀── 8px color circle + 4px gap + body-case label
 ● Авария канала Т11
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Pill body** | Filled/outline variants | QLabel with background and border-radius |
| **Label text** | Yes | Short, uppercase for filled status (RULE-TYPO-008); sentence case for count/category |
| **Icon prefix** | Conditional | Lucide icon when critical for a11y (RULE-A11Y-002) |
| **Count number** | Count variant | Distinct numeric glyph via FONT_MONO_VALUE for at-a-glance read |

## Invariants

1. **Status color matches semantic role.** STATUS_OK for healthy, STATUS_WARNING for attention, STATUS_FAULT for fault. Never arbitrary green/red. (RULE-COLOR-002)
2. **Color never sole signal.** Status badge MUST include text label or icon. Color-blind safety. (RULE-A11Y-002)
3. **Uppercase Cyrillic has letter-spacing.** Filled status badges use `0.05em` tracking. (RULE-TYPO-005)
4. **Filled badges use ON_* text colors.** Text on filled status background uses paired ON_* token. (RULE-COLOR-008)
5. **Height compact.** Badges are smaller than ROW_HEIGHT — typically 22–26px. Badge is not a button.
6. **Not interactive.** No `:hover` elevation, no cursor change, no `:pressed` state. If it needs hover, it's not a badge.
7. **No raw hex.** (RULE-COLOR-001)

## API (proposed)

```python
# src/cryodaq/gui/widgets/badges.py  (proposed)

class StatusBadge(QLabel):
    """Filled or outline status chip."""
    
    def __init__(
        self,
        text: str,
        status: str,  # "ok" | "warning" | "caution" | "fault" | "info" | "stale"
        parent: QWidget | None = None,
        *,
        variant: str = "filled",  # "filled" | "outline"
    ) -> None: ...
    
    def set_status(self, status: str) -> None: ...
    def set_text(self, text: str) -> None: ...

class CountBadge(QWidget):
    """Numeric count + label pair."""
    
    def __init__(
        self,
        count: int,
        label: str,
        status: str = "info",
        parent: QWidget | None = None,
    ) -> None: ...
    
    def set_count(self, count: int) -> None: ...

class InlineIndicator(QWidget):
    """Small color dot + label inline. Minimal chrome."""
    
    def __init__(
        self,
        label: str,
        status: str,
        parent: QWidget | None = None,
    ) -> None: ...
```

## Variants

### Variant 1: Filled status badge

Loud announcement. Use for active states.

```python
# DESIGN: RULE-COLOR-002, RULE-COLOR-008, RULE-TYPO-005, RULE-TYPO-008
status_colors = {
    "ok":       (theme.STATUS_OK,       theme.ON_DESTRUCTIVE),  # ON_DESTRUCTIVE = light text, works
    "warning":  (theme.STATUS_WARNING,  theme.ON_DESTRUCTIVE),
    "caution":  (theme.STATUS_CAUTION,  theme.ON_DESTRUCTIVE),
    "fault":    (theme.STATUS_FAULT,    theme.ON_DESTRUCTIVE),
    "info":     (theme.STATUS_INFO,     theme.ON_DESTRUCTIVE),
    "stale":    (theme.STATUS_STALE,    theme.ON_DESTRUCTIVE),
}

bg, fg = status_colors["fault"]

badge = QLabel("АВАРИЯ")
badge_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
badge_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
badge_font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
)
badge.setFont(badge_font)
badge.setStyleSheet(f"""
    QLabel {{
        background: {bg};
        color: {fg};
        border: none;
        border-radius: {theme.RADIUS_SM}px;
        padding: {theme.SPACE_1}px {theme.SPACE_2}px;
    }}
""")
badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
```

### Variant 2: Outline status badge

Subtle. Use for informational context or when multiple badges compete.

```python
# DESIGN: RULE-COLOR-002
status_color = theme.STATUS_WARNING

badge = QLabel("ВНИМАНИЕ")
badge.setFont(badge_font)  # same as Variant 1
badge.setStyleSheet(f"""
    QLabel {{
        background: transparent;
        color: {status_color};
        border: 1px solid {status_color};
        border-radius: {theme.RADIUS_SM}px;
        padding: {theme.SPACE_1}px {theme.SPACE_2}px;
    }}
""")
```

> **Contrast note per RULE-A11Y-003:** STATUS_FAULT (3.94:1) and STATUS_INFO (4.31:1) fail AA body. At badge size with letter-spacing and semibold weight, they may pass AA large (18pt equivalent) — verify per context. For body-size outline badges with failing colors, pair with an icon prefix (RULE-A11Y-002).

### Variant 3: Count badge

Numeric + label. Use in stats panels, header summaries.

```python
# DESIGN: RULE-TYPO-003 (tnum), RULE-TYPO-010 (text color pairs typography)
count = QLabel("3")
count_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
count_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
count_font.setFeature("tnum", 1)
count_font.setFeature("liga", 0)
count.setFont(count_font)
count.setAlignment(Qt.AlignmentFlag.AlignCenter)
count.setFixedSize(24, 22)
count.setStyleSheet(f"""
    QLabel {{
        background: {theme.STATUS_WARNING};
        color: {theme.ON_DESTRUCTIVE};
        border-radius: {theme.RADIUS_SM}px;
    }}
""")

label = QLabel("тревоги")
label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")

row = QHBoxLayout()
row.setSpacing(theme.SPACE_1)  # 4px
row.setContentsMargins(0, 0, 0, 0)
row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
row.addWidget(count)
row.addWidget(label)
```

### Variant 4: Inline indicator

Minimal chrome — just color dot + label. Use in dense lists, log entries, status bar.

```python
# DESIGN: RULE-SPACE-008, RULE-A11Y-002 (dot is redundant with label)
class InlineIndicator(QWidget):
    def __init__(self, label: str, status: str, parent=None):
        super().__init__(parent)
        
        status_color = {
            "ok": theme.STATUS_OK,
            "warning": theme.STATUS_WARNING,
            "fault": theme.STATUS_FAULT,
            "info": theme.STATUS_INFO,
            "stale": theme.STATUS_STALE,
        }[status]
        
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_1)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # Color dot
        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"""
            QFrame {{
                background: {status_color};
                border-radius: 4px;
            }}
        """)
        row.addWidget(self._dot)
        
        # Label (sentence case)
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {theme.FOREGROUND};")
        row.addWidget(self._label)
        row.addStretch()
```

Usage: `● Норма`, `● Авария канала Т11`, `● Ожидание подключения`.

### Variant 5: Phase badge (compact phase indicator)

Use in TopWatchBar or inline references. Not the full PhaseStepper (which is `cryodaq-primitives/phase-stepper.md`).

```python
# DESIGN: RULE-COLOR-004 — active phase uses STATUS_OK, NOT ACCENT
# Badge for active phase
phase_name = "Захолаживание"

badge = QLabel(phase_name)
badge_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
badge_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
badge.setFont(badge_font)
badge.setStyleSheet(f"""
    QLabel {{
        background: transparent;
        color: {theme.STATUS_OK};
        border: 1px solid {theme.STATUS_OK};
        border-radius: {theme.RADIUS_SM}px;
        padding: {theme.SPACE_1}px {theme.SPACE_2}px;
    }}
""")
```

## States

Badges are static — they do not have interactive states. Transitions between badge states (e.g., channel goes from STATUS_OK to STATUS_WARNING) are **instant** per RULE-INTER-006 for fault transitions. No fade-in, no animation — snap to new state.

## Accessibility

Per RULE-A11Y-002 (status never by color alone):

- **Filled badges** satisfy the rule via text label (the text IS the channel, not just color)
- **Outline badges** also satisfy via text
- **Inline indicators** satisfy via the label next to the dot — the dot alone would fail; dot+label passes
- **Icon-only status indicators** MUST pair icon with text or tooltip describing the status

```python
# DESIGN: RULE-A11Y-002 — color + icon + label = redundant channels
row = QHBoxLayout()
row.setSpacing(theme.SPACE_1)

icon = QLabel()
icon.setPixmap(
    load_colored_icon("alert-triangle", color=theme.STATUS_WARNING)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)  # proposed: theme.ICON_SIZE_SM — not yet in theme.py
)
row.addWidget(icon)

badge = QLabel("ВНИМАНИЕ")  # the text label IS a redundant channel
badge.setStyleSheet(f"color: {theme.STATUS_WARNING};")
row.addWidget(badge)
```

## Sizing

| Context | Font size | Padding | Height |
|---|---|---|---|
| Standard | FONT_LABEL_SIZE (12) | SPACE_1 vert, SPACE_2 horiz | ~22-24px |
| Compact (dense table) | FONT_SIZE_XS (11) | 2px vert, SPACE_1 horiz | ~18-20px |
| Large (hero indicator) | FONT_SIZE_BASE (14) | SPACE_2 vert, SPACE_3 horiz | ~30-32px |

All sizes below ROW_HEIGHT. Badges are small.

## Common mistakes

1. **Badge is clickable.** If the chip can be clicked/toggled, it's a Button (pill-shaped icon-only button), not a Badge. Don't give Badges hover states or cursor changes.

2. **Color-only indicator without label.** A colored dot with no label fails RULE-A11Y-002. Always pair with text or icon.

3. **Wrong status semantic.** Using STATUS_OK green for "active phase" instead of "healthy state" — this was the Phase 0 Dashboard PhaseStepper violation. Active phase IS status (it's operationally healthy and running), so STATUS_OK is correct there. But if you use STATUS_OK for "selected tab" — that's RULE-COLOR-004 violation. Selected uses ACCENT.

4. **Cyrillic uppercase without letter-spacing.** "АВАРИЯ" cramps without tracking. RULE-TYPO-005.

5. **Badge too large.** 36px tall "badge" is actually a button. Keep badges 18-24px. If it's hero-size, it's a heading.

6. **Fault badge in body prose color.** STATUS_FAULT at body size fails AA contrast (3.94:1). Either use larger text (AA large passes at 3.0:1) or swap to filled variant with ON_DESTRUCTIVE text. RULE-A11Y-003.

7. **Using raw count like "3 АВАРИИ" instead of badge pattern.** Mix of count + uppercase category in running text. Break into CountBadge (numeric) + separate category label.

## Related components

- `components/button.md` — If interactive, it's a button, not a badge
- `cryodaq-primitives/alarm-badge.md` — Domain-specific: header alarm indicator with count
- `cryodaq-primitives/phase-stepper.md` — Full phase navigation (the expanded form of Variant 5)
- `patterns/state-visualization.md` — Where to use badges vs other status indicators

## Changelog

- 2026-04-17: Initial version. 5 variants (filled status, outline status, count, inline indicator, phase badge). API proposed — current legacy code uses ad-hoc QLabels with stylesheets; formalization Phase II follow-up.
