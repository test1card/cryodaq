# Phase UI-1 — setStyleSheet Classification Table

> **Purpose:** This document is the authoritative classification of every
> `setStyleSheet`, `setBackground`, and `setForeground` call in
> `src/cryodaq/gui/` for Phase UI-1 Block 6 mechanical cleanup.
>
> **Scope:** Block 6 applies this table mechanically, file by file. Every
> entry has a pre-made decision. CC makes zero judgment calls.
>
> **Key principle:** `common.py` is the primary leverage point. Its helper
> functions are centralized style setters called from many widgets. Fixing
> `common.py` correctly propagates improvements to all callers automatically.
>
> **What's explicitly out of scope:**
> - Removing decorative colored borders on analytics_panel hero cards —
>   the borders stay, only hex → `theme.BORDER_SUBTLE` (layout change
>   forbidden by Phase UI-1 scope; we replace the **color** with neutral but
>   keep the border itself)
> - Removing `ChannelCard` per-state dynamic styling in temp_panel.py —
>   this is correct semantic state indication, update tokens only
> - Introducing new custom widget classes
>
> **Execution model:** CC processes one file at a time, applies all changes
> for that file in one editing pass, runs tests targeting that widget if
> they exist, moves to the next file. At the end, full pytest + smoke test
> + commit.

---

## Categories

- **delete** — pure noise duplicating qdarktheme; remove the `setStyleSheet`
  call entirely (leave `pass` if the call was the only statement in a
  block)
- **convert-to-token** — replace hardcoded color/size in the string with
  theme tokens; structure of the call stays the same
- **keep-critical-update-token** — keep the styling call (it's functionally
  important, e.g. semantic state indication or dynamic per-reading color)
  but swap all hex literals for theme tokens
- **keep-as-is** — intentional code; do not touch (e.g. print-mode toggle)
- **false-positive** — grep matched but this is `QTableWidgetItem.setBackground`
  or `QTableWidgetItem.setForeground`, not Qt widget setStyleSheet; needs
  a different treatment, documented separately

---

## Mandatory change: `common.py` helper functions

This is the **most important section**. Process `common.py` **first** before
any other widget file. Nearly all other widgets use these helpers
transitively, so fixing `common.py` propagates improvements widely.

### common.py — full rewrite of styled helpers

Add `from cryodaq.gui import theme` at the top of the file alongside existing
imports.

**Replace the entire `StatusBanner._STYLES` dict** with theme tokens:

```python
class StatusBanner(QLabel):
    _STYLES = {
        "info":    f"color: {theme.TEXT_MUTED};",
        "success": f"color: {theme.STATUS_OK};",
        "warning": f"color: {theme.STATUS_CAUTION};",
        "error":   f"color: {theme.STATUS_FAULT};",
    }
```

Note: `warning` in StatusBanner historically mapped to yellow `#FFDC00`
which in our semantic palette corresponds to `STATUS_CAUTION` (yellow), not
`STATUS_WARNING` (orange). This is intentional — "warning" in the existing
codebase is used loosely for any attention-worthy but non-urgent message,
which matches our `caution` slot.

**Replace `apply_status_label_style()` base dict** with theme tokens:

```python
def apply_status_label_style(label: QLabel, level: str, *, bold: bool = False) -> None:
    base = {
        "muted":   theme.TEXT_MUTED,
        "info":    theme.TEXT_MUTED,      # legacy: info == muted in callers
        "success": theme.STATUS_OK,
        "warning": theme.STATUS_CAUTION,  # see StatusBanner note above
        "error":   theme.STATUS_FAULT,
        "accent":  theme.TEXT_ACCENT,
    }.get(level, theme.TEXT_MUTED)
    weight = "font-weight: bold;" if bold else ""
    label.setStyleSheet(f"color: {base}; {weight}".strip())
```

**Replace `apply_button_style()` variants dict**. Buttons are one area where
we cannot simply delete local styling (qdarktheme provides a base button
look but we have variant buttons — primary/warning/danger — which need
specific treatment). Keep the function but reference tokens:

```python
def apply_button_style(button: QPushButton, variant: str = "neutral", *, compact: bool = False) -> None:
    # Tokens are string-interpolated here. This helper is the single place
    # where button variants are defined — do not duplicate elsewhere.
    variants = {
        "neutral": (theme.SURFACE_ELEVATED, theme.STONE_300, theme.TEXT_SECONDARY),
        "primary": (theme.ACCENT_400, theme.ACCENT_500, theme.TEXT_INVERSE),
        "warning": (theme.STATUS_WARNING, theme.STATUS_CAUTION, theme.TEXT_INVERSE),
        "danger":  (theme.STATUS_FAULT, theme.STATUS_FAULT, theme.TEXT_INVERSE),
    }
    bg, hover, fg = variants.get(variant, variants["neutral"])
    padding = f"{theme.SPACE_1}px {theme.SPACE_2}px" if compact else f"{theme.SPACE_2 - 2}px {theme.SPACE_3 + 2}px"
    radius = f"{theme.RADIUS_SM}px" if compact else f"{theme.RADIUS_MD - 1}px"
    button.setStyleSheet(
        "QPushButton { "
        f"background: {bg}; color: {fg}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {radius}; padding: {padding}; "
        "}"
        f"QPushButton:hover {{ background: {hover}; }}"
        "QPushButton:disabled { background: " + theme.STONE_400 + "; color: " + theme.TEXT_DISABLED + "; }"
    )
```

**Replace `apply_group_box_style()`**:

```python
def apply_group_box_style(box: QGroupBox, accent: str | None = None) -> None:
    color = accent if accent is not None else theme.TEXT_ACCENT
    box.setStyleSheet(
        "QGroupBox { "
        f"color: {color}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px; padding-top: 12px; "
        "}"
    )
```

**Replace `apply_panel_frame_style()` defaults**:

```python
def apply_panel_frame_style(
    frame: QFrame,
    *,
    background: str | None = None,
    border: str | None = None,
    radius: int | None = None,
) -> None:
    bg = background if background is not None else theme.SURFACE_PANEL
    br = border if border is not None else theme.BORDER_SUBTLE
    rd = radius if radius is not None else theme.RADIUS_MD
    frame.setStyleSheet(
        f"{frame.__class__.__name__} {{ background-color: {bg}; border: 1px solid {br}; border-radius: {rd}px; }}"
    )
```

**Replace `PanelHeader.__init__` inline styles**:

```python
class PanelHeader(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_MD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-weight: bold;")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            layout.addWidget(subtitle_label)
```

**Replace `create_panel_root()` margins** — currently uses `(8, 8, 8, 8)` and
`setSpacing(8)`. Update to theme tokens:

```python
def create_panel_root(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
    layout.setSpacing(theme.SPACE_2)
    return layout
```

**Leave unchanged** in `common.py`:
- `setup_standard_table()`
- `build_action_row()`
- `add_form_rows()`
- `snap_x_range()`

---

## Per-file classification table

### shift_handover.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 118 | `op_label.setStyleSheet("font-weight: bold;")` | keep-as-is | bold is structural, no color — leave |
| 131 | `checks_label.setStyleSheet("font-weight: bold;")` | keep-as-is | same |
| 188 | `row.setStyleSheet(...)` multiline | convert-to-token | Replace `'#2ECC40' if check['ok'] else '#FF4136'` with `theme.STATUS_OK if check['ok'] else theme.STATUS_FAULT`. Keep the rest of the f-string. |
| 252 | `info.setStyleSheet("color: #888888;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 257 | `status_label.setStyleSheet("font-weight: bold;")` | keep-as-is | bold structural |
| 268 | `self._readings_label.setStyleSheet("color: #58a6ff;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT};"` |
| 349 | `summary_label.setStyleSheet("font-weight: bold; font-size: 12pt;")` | keep-as-is | structural only |
| 359 | `summary_text.setStyleSheet("color: #c9d1d9; padding: 4px;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY}; padding: {theme.SPACE_1}px;"` |
| 441 | `self._status_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 446 | `self._elapsed_label.setStyleSheet("color: #58a6ff; border: none;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT}; border: none;"` |
| 515 | `self._status_label.setStyleSheet("color: #2ECC40; border: none;")` | convert-to-token | `f"color: {theme.STATUS_OK}; border: none;"` |
| 547 | `self._status_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |

### pressure_panel.py

**Important context:** this file has dynamic state-based color styling
(`_pressure_color(value)` function). The card border color changes based
on pressure range. This is **correct semantic state indication** — keep
the structure, update tokens.

**Find and update** the `_COLOR_GOOD` / `_COLOR_WARN` / `_COLOR_BAD` /
`_pressure_color()` module-level constants if they exist. Map them to
theme tokens:
- `_COLOR_GOOD` → `theme.STATUS_OK`
- `_COLOR_WARN` → `theme.STATUS_CAUTION` (or `STATUS_WARNING` depending on
  original semantic — if the constant value was `#FFDC00` yellow, use
  `STATUS_CAUTION`; if `#FF8C00` orange, use `STATUS_WARNING`)
- `_COLOR_BAD` → `theme.STATUS_FAULT`

If these constants don't exist (color is inline), search `pressure_panel.py`
for the `_pressure_color` function and update its return values to theme
tokens.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 52 | `self.setStyleSheet("background-color: #1A1A1A;")` | delete | qdarktheme provides panel bg; remove entirely |
| 74 | `self._card.setStyleSheet(f"background-color: #2A2A2A; border: 2px solid {_COLOR_GOOD}; border-radius: 8px;")` | keep-critical-update-token | `f"background-color: {theme.SURFACE_CARD}; border: 2px solid {theme.STATUS_OK}; border-radius: {theme.RADIUS_LG}px;"` (initial state before first reading) |
| 85 | `title.setStyleSheet("color: #AAAAAA; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 95 | `self._value_label.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 104 | `self._unit_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 112 | `self._plot.setBackground("#111111")` | **SKIP** | Handled in Block 7 — leave for now |
| 156 | `self._value_label.setStyleSheet(f"color: {color}; border: none;")` | keep-critical-update-token | Variable `color` comes from `_pressure_color()`. Ensure that function returns theme tokens (update its implementation). Call site unchanged. |
| 157 | `self._card.setStyleSheet(f"background-color: #2A2A2A; border: 2px solid {color}; border-radius: 8px;")` | keep-critical-update-token | `f"background-color: {theme.SURFACE_CARD}; border: 2px solid {color}; border-radius: {theme.RADIUS_LG}px;"` |

### overview_panel.py

This is the largest file by line count. Process carefully.

**Context for lines 229–412 area:** sensor card widget class definitions
with static card styling and per-state color logic. The `_CARD_STYLE` and
related QSS blocks are Bootstrap-style containers.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 229 | `sep.setStyleSheet("color: #555555; border: none;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none;"` |
| 276 | `self._name_label.setStyleSheet("color: #BBBBBB; border: none;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY}; border: none;"` |
| 286 | `self._value_label.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 295 | `self._trend_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 350 | `self._value_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | Stale state → `f"color: {theme.TEXT_DISABLED}; border: none;"` (disabled is correct for stale per design system 5.1) |
| 359 | `self._value_label.setStyleSheet(f"color: {value_color}; border: none;")` | keep-critical-update-token | Find where `value_color` is assigned upstream; ensure the source uses theme tokens. Call site unchanged. |
| 412 | `self.setStyleSheet(...)` multiline for SensorCard container | keep-critical-update-token | Multiline Bootstrap card QSS. Replace `#2A2A2A` → `theme.SURFACE_CARD`, `#444` or `#333` → `theme.BORDER_SUBTLE`, `border-radius: 4px` → `{theme.RADIUS_MD}px`. Keep structure. |
| 439 | `self.setStyleSheet(...)` multiline — selected state | keep-critical-update-token | Same pattern. Replace hex and radius with tokens. The "selected" border (typically brighter/thicker) should use `theme.BORDER_FOCUS` (= `theme.ACCENT_400`). |
| 535 | `self._title.setStyleSheet("color: #BBBBBB; border: none;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY}; border: none;"` |
| 545 | `self._value_label.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 570 | `self._value_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | Stale → `f"color: {theme.TEXT_DISABLED}; border: none;"` |
| 586 | `self._value_label.setStyleSheet("color: #FF4444; border: none;")` | convert-to-token | Fault → `f"color: {theme.TEXT_FAULT}; border: none;"` |
| 590 | `self._value_label.setStyleSheet("color: #FF8C00; border: none;")` | convert-to-token | Warning → `f"color: {theme.TEXT_WARNING}; border: none;"` |
| 594 | `self._value_label.setStyleSheet("color: #FFD700; border: none;")` | convert-to-token | Caution → `f"color: {theme.TEXT_CAUTION}; border: none;"` |
| 598 | `self._value_label.setStyleSheet("color: #2ECC40; border: none;")` | convert-to-token | OK → `f"color: {theme.TEXT_OK}; border: none;"` |
| 616 | `self._value_label.setStyleSheet("color: #555555; border: none;")` | convert-to-token | Disabled → `f"color: {theme.TEXT_DISABLED}; border: none;"` |
| 620 | `self._value_label.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 626 | `self.setStyleSheet(...)` multiline — card outer container | keep-critical-update-token | Same pattern as 412/439 — bg → SURFACE_CARD, borders → BORDER_SUBTLE, radius → RADIUS_MD |
| 780 | `self._status_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 787 | `self._elapsed_label.setStyleSheet("color: #58a6ff; border: none;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT}; border: none;"` |
| 821 | `self._status_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 839 | `self._status_label.setStyleSheet("color: #2ECC40; border: none;")` | convert-to-token | `f"color: {theme.STATUS_OK}; border: none;"` |
| 879 | `input_label.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 884 | `self._input.setStyleSheet(...)` multiline QLineEdit QSS | keep-critical-update-token | Replace `#21262d` → `theme.SURFACE_SUNKEN`, `#c9d1d9` → `theme.TEXT_SECONDARY`, `#30363d` → `theme.BORDER_STRONG`, `3px` → `{theme.RADIUS_SM}px`, paddings to theme.SPACE_* |
| 901 | `self._recent_label.setStyleSheet("color: #666666; border: none; font-size: 9pt;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none; font-size: 9pt;"` (keep pt size — font sizing is in separate Phase UI-2 scope) |
| 1113 | `graph_splitter.setStyleSheet("QSplitter::handle { background-color: #333333; }")` | convert-to-token | `f"QSplitter::handle {{ background-color: {theme.BORDER_SUBTLE}; }}"` |
| 1148 | `pw.setBackground("#111111")` | **SKIP** | Block 7 |
| 1177 | `pp.setBackground("#111111")` | **SKIP** | Block 7 |
| 1221 | `self._eta_overlay.setStyleSheet(...)` | convert-to-token | Multiline ETA overlay styling. Replace any hex with matching tokens (likely `TEXT_MUTED`, `SURFACE_PANEL`). |
| 1659 | `self._plot.setBackground("white")` | **SKIP** | Block 7 (print mode — will be kept as-is there) |
| 1661 | `self._plot.setBackground("#111111")` | **SKIP** | Block 7 (will become `theme.PLOT_BG`) |

### experiment_workspace.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 326 | `self._mode_title.setStyleSheet("color: #8b949e; font-size: 12px;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; font-size: 12px;"` |
| 330 | `self._mode_label.setStyleSheet("font-size: 18px; font-weight: bold;")` | keep-as-is | no color, structural only |
| 372 | `arrow.setStyleSheet("color: #555555; border: none; font-size: 11px;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none; font-size: 11px;"` |
| 375 | `lbl.setStyleSheet("color: #555555; border: none; font-size: 11px;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none; font-size: 11px;"` |
| 395 | `self._debug_message.setStyleSheet("color: #c9d1d9;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY};"` |
| 828 | `lbl.setStyleSheet("color: #2ECC40; font-weight: bold; border: none; font-size: 11px;")` | convert-to-token | `f"color: {theme.STATUS_OK}; font-weight: bold; border: none; font-size: 11px;"` |
| 831 | `lbl.setStyleSheet("color: #58a6ff; border: none; font-size: 11px;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT}; border: none; font-size: 11px;"` |
| 835 | `lbl.setStyleSheet("color: #555555; border: none; font-size: 11px;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none; font-size: 11px;"` |

### connection_settings.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 72 | `title.setStyleSheet("color: #58a6ff;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT};"` |
| 79 | `hint.setStyleSheet("color: #8b949e;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 103 | `add_btn.setStyleSheet(...)` multiline QPushButton QSS | delete | Replace the entire `setStyleSheet(...)` call with `apply_button_style(add_btn, "primary")` using the imported common helper. Import `apply_button_style` from `cryodaq.gui.widgets.common` if not already imported. |
| 113 | `apply_btn.setStyleSheet(...)` multiline | delete | Same — replace with `apply_button_style(apply_btn, "primary")` |
| 177 | `del_btn.setStyleSheet(...)` multiline | delete | Same — replace with `apply_button_style(del_btn, "danger")` |

### operator_log_panel.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 111 | `item.setForeground(QColor("#666666"))` | false-positive | This is `QTableWidgetItem.setForeground`, not Qt widget setStyleSheet. Replace `QColor("#666666")` with `QColor(theme.TEXT_DISABLED)`. Keep the call, swap the hex. |

### sensor_diag_panel.py

**Module-level constants** in this file (`_COLOR_GREEN`, `_COLOR_YELLOW`,
`_COLOR_RED`, `_COLOR_MUTED` at lines ~27-30) — **update these first**, then
all f-string call sites automatically use updated values:

```python
_COLOR_GREEN = theme.STATUS_OK          # was "#2ECC40"
_COLOR_YELLOW = theme.STATUS_CAUTION    # was "#FFDC00"
_COLOR_RED = theme.STATUS_FAULT         # was "#FF4136"
_COLOR_MUTED = theme.TEXT_MUTED         # was "#8b949e"
```

Add `from cryodaq.gui import theme` import.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 84 | `title.setStyleSheet("color: #f0f6fc;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY};"` |
| 89 | `self._summary_label.setStyleSheet(f"color: {_COLOR_MUTED};")` | keep-critical-update-token | After module constant is updated, this works automatically. No call-site change needed. |
| 102 | `self._table.setStyleSheet(...)` multiline QTableWidget QSS | delete | Replace entire QSS with empty string (or delete the `setStyleSheet` call). qdarktheme styles tables. Leave only structural settings (`setAlternatingRowColors` etc). |
| 168 | `item.setForeground(QColor(color))` | false-positive | Variable `color` — ensure the source of `color` uses theme tokens. No call-site change. |
| 180 | `self._table.item(row, col).setBackground(bg)` | false-positive | Variable `bg` — ensure the source uses theme tokens. No call-site change. |

### conductivity_panel.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 177 | `scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")` | keep-as-is | Structural (no color, no geometry change) — qdarktheme might add default borders we want to suppress |
| 180 | `ch_container.setStyleSheet("background: transparent;")` | keep-as-is | Structural transparency |
| 256 | `self._power_preview.setStyleSheet("color: #8b949e; font-size: 9pt;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; font-size: 9pt;"` |
| 355 | `self._plot.setBackground("#111111")` | **SKIP** | Block 7 |
| 361 | `self._empty_overlay.setStyleSheet("color: #666666; font-size: 14pt; background: transparent;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; font-size: 14pt; background: transparent;"` |
| 604 | `pct_item.setForeground(QColor(_pct_color(pct_val)))` | false-positive | Update `_pct_color()` function body to return theme tokens instead of hex. Call site unchanged. |

### preflight_dialog.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 203 | `title.setStyleSheet("font-weight: bold; font-size: 13px; margin-bottom: 4px;")` | keep-as-is | structural only |
| 208 | `self._loading_label.setStyleSheet("color: #888888;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 224 | `self._summary_label.setStyleSheet("margin-top: 4px;")` | keep-as-is | structural only |
| 251 | `label.setStyleSheet(f"color: {color};")` | keep-critical-update-token | Variable `color` from `_STATUS_COLOR` dict. Update the dict (module-level, likely near top of file) to use theme tokens — map "error" → `STATUS_FAULT`, "warning" → `STATUS_WARNING`, "ok" → `STATUS_OK`, "info" → `STATUS_INFO`. Call site unchanged. |
| 271 | `self._summary_label.setStyleSheet(f"font-weight: bold; color: {summary_color}; margin-top: 4px;")` | keep-critical-update-token | Same — `summary_color` comes from `_STATUS_COLOR` dict updated above. Call site unchanged. |

### archive_panel.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 278 | `data_item.setForeground(QColor("#2ECC40"))` | false-positive | Replace with `QColor(theme.STATUS_OK)`. |
| 280 | `data_item.setForeground(QColor("#555555"))` | false-positive | Replace with `QColor(theme.TEXT_DISABLED)`. |

### vacuum_trend_panel.py

**Module-level constants** (lines ~30-34) — update first:

```python
_COLOR_GREEN = theme.STATUS_OK       # was "#2ECC40"
_COLOR_YELLOW = theme.STATUS_CAUTION # was "#FFDC00"
_COLOR_RED = theme.STATUS_FAULT      # was "#FF4136"
_COLOR_WHITE = theme.TEXT_PRIMARY    # was "#c9d1d9" — note: mapping to TEXT_PRIMARY is semantically correct (value text)
_COLOR_MUTED = theme.TEXT_MUTED      # was "#8b949e"
```

Add `from cryodaq.gui import theme` import.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 107 | `title.setStyleSheet("color: #f0f6fc;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY};"` |
| 111 | `self._status_label.setStyleSheet(f"color: {_COLOR_MUTED};")` | keep-critical-update-token | Module constant updated → works automatically |
| 131 | `self._trend_icon.setStyleSheet(f"color: {_COLOR_MUTED};")` | keep-critical-update-token | same |
| 137 | `self._trend_label.setStyleSheet(f"color: {_COLOR_MUTED};")` | keep-critical-update-token | same |
| 142 | `eta_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")` | keep-critical-update-token | same |
| 153 | `p_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")` | keep-critical-update-token | same |
| 157 | `self._p_ult_label.setStyleSheet(f"color: {_COLOR_WHITE};")` | keep-critical-update-token | same |
| 163 | `self._model_label.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")` | keep-critical-update-token | same |
| 168 | `self._r2_label.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")` | keep-critical-update-token | same |
| 174 | `conf_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")` | keep-critical-update-token | same |
| 181 | `self._confidence_bar.setStyleSheet(...)` multiline QProgressBar QSS | keep-critical-update-token | Replace hex values in QSS with theme tokens. Likely chunk background → `theme.SURFACE_SUNKEN` or `STONE_200`, border → `theme.BORDER_SUBTLE`. |
| 193 | `self._plot.setBackground("#0d1117")` | **SKIP** | Block 7 |
| 222 | `self._empty_label.setStyleSheet(...)` | convert-to-token | Replace any hex with `theme.TEXT_DISABLED` or similar appropriate token |
| 313 | `self._confidence_bar.setStyleSheet(...)` runtime update | keep-critical-update-token | Update dynamic confidence-bar styling; replace hex with tokens |
| 333 | `self._trend_icon.setStyleSheet(f"color: {color};")` | keep-critical-update-token | Variable `color` from local mapping. Ensure source uses tokens. Call site unchanged. |
| 335 | `self._trend_label.setStyleSheet(f"color: {color};")` | keep-critical-update-token | same |
| 352 | `lbl.setStyleSheet(f"color: {_COLOR_WHITE}; font-size: 11px;")` | keep-critical-update-token | Module constant updated → works automatically |

### analytics_panel.py

**CRITICAL FILE** — this is where we remove the anti-pattern "status colors
as UI chrome" on hero metric cards.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 60 | `self.setStyleSheet("background-color: #1A1A1A;")` | delete | qdarktheme provides panel bg |
| 119 | `card.setStyleSheet("background-color: #2A2A2A; border: 1px solid #f0883e; border-radius: 8px;")` (R thermal hero) | keep-critical-update-token | **Anti-pattern cleanup.** Replace with `f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_LG}px;"` — **neutral border, not the orange `#f0883e`**. This removes the "status color as decoration" anti-pattern. |
| 135 | `title.setStyleSheet("color: #f0883e; border: none;")` | convert-to-token | Title text also loses the orange accent. Use `f"color: {theme.TEXT_SECONDARY}; border: none;"` — neutral title |
| 141 | `self._r_value.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 147 | `unit.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 156 | `card.setStyleSheet("background-color: #2A2A2A; border: 1px solid #58a6ff; border-radius: 8px;")` (ETA hero) | keep-critical-update-token | Same anti-pattern cleanup. Replace with `f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_LG}px;"` |
| 176 | `title.setStyleSheet("color: #58a6ff; border: none;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY}; border: none;"` — neutral |
| 183 | `self._eta_value.setStyleSheet("color: #FFFFFF; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 190 | `self._eta_subtitle.setStyleSheet("color: #888888; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 200 | `self._progress_bar.setStyleSheet(...)` multiline QProgressBar QSS | keep-critical-update-token | Replace any hex with tokens. Progress bar chunk color → `theme.ACCENT_400`, bg → `theme.SURFACE_SUNKEN`, border → `theme.BORDER_SUBTLE`. |
| 221 | `self._phase_label.setStyleSheet("color: #79c0ff; border: none;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT}; border: none;"` (was a different blue shade — normalizing to accent) |
| 229 | `self._model_label.setStyleSheet("color: #666666; border: none;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; border: none;"` |
| 239 | `self._plot.setBackground("#111111")` | **SKIP** | Block 7 |
| 245 | `self._empty_overlay.setStyleSheet("color: #666666; font-size: 14pt; background: transparent;")` | convert-to-token | `f"color: {theme.TEXT_DISABLED}; font-size: 14pt; background: transparent;"` |

### keithley_panel.py

**Context:** this file builds V/I/R/P hero readout cards. Per design system
D-014, V/I/R/P quantity colors are intentional universal electronics
convention and are applied **only as value text color / dot indicator**, not
as card borders. Current code has colored card borders — that's the same
anti-pattern as analytics_panel.py.

**Find** the `colors` dict (likely module-level or near line 150) and update:

```python
# Was hardcoded hex. Now references theme quantity tokens.
colors = {
    "voltage":    theme.QUANTITY_VOLTAGE,
    "current":    theme.QUANTITY_CURRENT,
    "resistance": theme.QUANTITY_RESISTANCE,
    "power":      theme.QUANTITY_POWER,
}
```

Add `from cryodaq.gui import theme` import.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 95 | `title.setStyleSheet("color: #f0f6fc; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 164 | `card.setStyleSheet(f"background-color: #2A2A2A; border: 1px solid {colors[key]}; border-radius: 6px;")` | keep-critical-update-token | **Anti-pattern cleanup — same as analytics_panel.** Replace with `f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px;"` — neutral border. Quantity color is applied ONLY to title text (line 172) and nowhere else. |
| 172 | `title_label.setStyleSheet(f"color: {colors[key]}; border: none;")` | keep-critical-update-token | **This** is the correct place for quantity color (per D-014). `colors[key]` now returns theme token. Call site unchanged. |
| 178 | `value_label.setStyleSheet("color: #ffffff; border: none;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY}; border: none;"` |
| 184 | `unit_label.setStyleSheet("color: #8b949e; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; border: none;"` |
| 197 | `plot.setBackground("#111111")` | **SKIP** | Block 7 |
| 220 | `label.setStyleSheet("color: #c9d1d9; border: none;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY}; border: none;"` |

### common.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 71 | `self.setStyleSheet(self._STYLES[level])` | keep-critical-update-token | Already handled by `_STYLES` dict update above |
| 84 | `label.setStyleSheet(f"color: {base}; {weight}".strip())` | keep-critical-update-token | Already handled by `base` dict update above |
| 97 | `button.setStyleSheet(...)` inside `apply_button_style` | keep-critical-update-token | Already handled by function rewrite above |
| 107 | `box.setStyleSheet(...)` inside `apply_group_box_style` | keep-critical-update-token | Already handled by function rewrite above |
| 121 | `frame.setStyleSheet(...)` inside `apply_panel_frame_style` | keep-critical-update-token | Already handled by function rewrite above |
| 136 | `self.setStyleSheet(...)` inside `PanelHeader.__init__` | keep-critical-update-token | Already handled above |
| 144 | `title_label.setStyleSheet("color: #f0f6fc; font-weight: bold;")` | keep-critical-update-token | Already handled above |
| 150 | `subtitle_label.setStyleSheet("color: #8b949e;")` | keep-critical-update-token | Already handled above |

### channel_editor.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 52 | `title.setStyleSheet("color: #58a6ff;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT};"` |
| 59 | `hint.setStyleSheet("color: #8b949e;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 77 | `reset_btn.setStyleSheet(...)` multiline | delete | Replace with `apply_button_style(reset_btn, "neutral")` |
| 85 | `apply_btn.setStyleSheet(...)` multiline | delete | Replace with `apply_button_style(apply_btn, "primary")` |

### calibration_panel.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 178 | `note.setStyleSheet("color: #888888;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 301 | `legend.setStyleSheet("color: #888888; font-size: 9pt;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; font-size: 9pt;"` |
| 307 | `self._live_label.setStyleSheet("color: #58a6ff;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT};"` |
| 313 | `note.setStyleSheet("color: #888888;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |
| 396 | `self._delta_label.setStyleSheet("color: #58a6ff;")` | convert-to-token | `f"color: {theme.TEXT_ACCENT};"` |

### temp_panel.py

**Module-level `_STATUS_COLORS` dict** — **find this at the top of the file**
and update to use theme tokens. Likely location: near imports, around line
20-40. Current values are hex strings keyed by ChannelStatus enum values.
Update:

```python
_STATUS_COLORS = {
    ChannelStatus.OK:       theme.STATUS_OK,
    ChannelStatus.WARNING:  theme.STATUS_WARNING,
    ChannelStatus.FAULT:    theme.STATUS_FAULT,
    ChannelStatus.STALE:    theme.STATUS_STALE,
    # ... whatever enum values exist
}
```

Add `from cryodaq.gui import theme` import.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 92 | `self._label.setStyleSheet("color: #CCCCCC;")` | convert-to-token | `f"color: {theme.TEXT_SECONDARY};"` |
| 103 | `self._value_label.setStyleSheet("color: #FFFFFF;")` | convert-to-token | `f"color: {theme.TEXT_PRIMARY};"` |
| 106 | `self.setStyleSheet(self._build_stylesheet(ChannelStatus.OK, selected=False))` | keep-critical-update-token | This is dynamic per-state styling. After `_build_stylesheet` and `_STATUS_COLORS` are updated, call sites work automatically. No call-site change. |
| 124 | `self.setStyleSheet(self._build_stylesheet(reading.status, self._selected))` | keep-critical-update-token | same |
| 131 | `self.setStyleSheet(self._build_stylesheet(status, selected))` | keep-critical-update-token | same |
| 148 | `self.setStyleSheet(self._build_stylesheet(self._current_status, self._selected))` | keep-critical-update-token | same |
| 175 | `self.setStyleSheet("background-color: #1A1A1A;")` | delete | qdarktheme provides |
| 212 | `cards_scroll.setStyleSheet(...)` | keep-as-is | Probably `QScrollArea { border: none; background: transparent; }` — structural transparency |
| 217 | `cards_container.setStyleSheet("background: transparent;")` | keep-as-is | structural transparency |
| 244 | `plot_frame.setStyleSheet(...)` multiline | keep-critical-update-token | Replace hex with tokens — likely SURFACE_CARD bg, BORDER_SUBTLE border |
| 256 | `title_label.setStyleSheet("color: #AAAAAA; background: transparent; border: none;")` | convert-to-token | `f"color: {theme.TEXT_MUTED}; background: transparent; border: none;"` |
| 267 | `pw.setBackground("#111111")` | **SKIP** | Block 7 |

**Also find and update** `ChannelCard._build_stylesheet` method (around line
180-200):

```python
def _build_stylesheet(self, status: ChannelStatus, selected: bool) -> str:
    border_color = _STATUS_COLORS.get(status, theme.STATUS_OK)
    border_width = 3 if selected else 1
    bg_color = theme.SURFACE_CARD if not selected else theme.SURFACE_ELEVATED
    return (
        f"ChannelCard {{"
        f"  background-color: {bg_color};"
        f"  border: {border_width}px solid {border_color};"
        f"  border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )
```

**Also find** `CompactTempCard._set_bg` method (around line 60-90) which
uses `#444` border hex:

```python
def _set_bg(self, color: str) -> None:
    if color == self._current_bg:
        return
    self._current_bg = color
    self.setStyleSheet(
        f"CompactTempCard {{ background-color: {color}; "
        f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px; }}"
    )
```

**Also find** `_PlaceholderCard.__init__` (around line 100-120):

```python
class _PlaceholderCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(80, 54)
        self.setMaximumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"background: {theme.SURFACE_PANEL}; border: 1px dashed {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_MD}px;"
        )
```

And the corresponding spot in `pressure_panel.py` `PressureCard._set_bg`
(same pattern).

### autosweep_panel.py

**Note:** this file is marked deprecated in PROJECT_STATUS.md but still in
the tree. Apply cleanup anyway — consistency matters.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 228 | `sensor_scroll.setStyleSheet("QScrollArea { border: none; }")` | keep-as-is | structural |
| 302 | `self._live_plot.setBackground("#111111")` | **SKIP** | Block 7 |

### alarm_panel.py

**Module-level `_SEVERITY_COLORS` dict** (top of file) — find and update:

```python
_SEVERITY_COLORS = {
    "critical": theme.STATUS_FAULT,
    "error":    theme.STATUS_FAULT,
    "warning":  theme.STATUS_WARNING,
    "info":     theme.STATUS_INFO,
    # keep whatever keys exist, map to appropriate tokens
}
```

Add `from cryodaq.gui import theme` import.

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 142 | `v2_label.setStyleSheet("font-weight: bold; margin-top: 8px;")` | keep-as-is | structural only |
| 228 | `severity_item.setForeground(color)` | false-positive | QTableWidgetItem — `color` comes from `_SEVERITY_COLORS` updated above |
| 241 | `value_item.setForeground(color)` | false-positive | same |
| 264 | `btn.setStyleSheet(f"background-color: {_SEVERITY_COLORS.get(alarm.severity, '#666')}; color: white; border: none; padding: 4px 8px; border-radius: 3px;")` | keep-critical-update-token | Replace with: `f"background-color: {_SEVERITY_COLORS.get(alarm.severity, theme.STONE_400)}; color: {theme.TEXT_INVERSE}; border: none; padding: {theme.SPACE_1}px {theme.SPACE_2}px; border-radius: {theme.RADIUS_SM}px;"` |
| 348 | `level_item.setForeground(color)` | false-positive | same pattern as 228 |
| 358 | `btn.setStyleSheet(...)` | keep-critical-update-token | Same as line 264 |

### instrument_status.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 172 | `self._indicator.setStyleSheet(f"color: {color};")` | keep-critical-update-token | Variable `color` — ensure source uses theme tokens. The upstream mapping (likely `_STATE_COLORS` dict or similar) must be updated to use tokens. Call site unchanged. |
| 173 | `self.setStyleSheet(f"_InstrumentCard {{ border: 2px solid {color}; border-radius: 6px; background-color: #1a1a2e; }}")` | keep-critical-update-token | Replace with `f"_InstrumentCard {{ border: 2px solid {color}; border-radius: {theme.RADIUS_LG}px; background-color: {theme.SURFACE_CARD}; }}"` |

### main_window.py

| Line | Current code | Category | Replacement |
|---|---|---|---|
| 312 | `self._sensor_diag_label.setStyleSheet(f"color: #8b949e;")` | convert-to-token | `f"color: {theme.TEXT_MUTED};"` |

---

## Files NOT in the table (no setStyleSheet found)

- `tray_status.py` — no hits in grep
- `__init__.py` files — no hits

---

## Processing order for Block 6

CC should process files in this order:

1. **`common.py`** — FIRST, because all helper function updates propagate
2. `main_window.py` — small, one line
3. `temp_panel.py` — update `_STATUS_COLORS` dict + `ChannelCard._build_stylesheet`
4. `pressure_panel.py` — update `_pressure_color` function + call sites
5. `sensor_diag_panel.py` — update module constants + table QSS delete
6. `vacuum_trend_panel.py` — update module constants
7. `preflight_dialog.py` — update `_STATUS_COLOR` dict + call sites
8. `alarm_panel.py` — update `_SEVERITY_COLORS` dict + button styles
9. `analytics_panel.py` — **anti-pattern cleanup**, border neutralization
10. `keithley_panel.py` — **anti-pattern cleanup**, `colors` dict update
11. `instrument_status.py` — dynamic state color update
12. `overview_panel.py` — largest file, many simple token swaps
13. `experiment_workspace.py`
14. `shift_handover.py`
15. `connection_settings.py`
16. `channel_editor.py`
17. `calibration_panel.py`
18. `conductivity_panel.py`
19. `operator_log_panel.py`
20. `archive_panel.py`
21. `autosweep_panel.py` (deprecated but still cleaned)

After each file: run `pytest -q tests/gui/ 2>&1 | tail -10` if that file has
targeted tests, otherwise continue. After all files: full `pytest -q`.

## Invariants for Block 6 execution

- **No layout changes.** Geometry, paddings in QBoxLayout calls, widget sizes,
  alignments — DO NOT TOUCH. Only colors, radii, and QSS-embedded padding
  inside setStyleSheet strings.
- **No new helper functions.** No new classes. No refactoring.
- **No test file changes** unless a test breaks because it asserts on a
  specific hex that no longer exists. In that case update the assertion to
  reference `theme.TOKEN`.
- **Import `theme`** in any file that newly uses tokens. Standard import:
  `from cryodaq.gui import theme`
- **Preserve Cyrillic strings** in operator-facing text. Russian comments
  can stay in Russian.
- **Double-check f-string interpolation.** When replacing `"color: #FFFFFF;"`
  with `f"color: {theme.TEXT_PRIMARY};"` — make sure the string becomes an
  f-string (prefix `f`). This is the most common mistake in mechanical
  replacements.

## Block 6 success criteria

- 829 passed, 6 skipped, 20 warnings ✓
- No `setStyleSheet` in touched files contains a hardcoded hex color
  anymore (the remaining hex values are only in print-mode overview_panel.py
  line 1659 "white", which is out of Block 6 scope and handled in Block 7)
- No `QColor("#...")` in `setForeground` / `setBackground` table item calls
  (all reference theme tokens via intermediate variables)
- No `_COLOR_*` module-level constants with hardcoded hex in any widget
  file (all point to theme tokens)
- Visual smoke test passes — no crashes, dark theme visible, plots still
  have old background (that's Block 7)
- All widgets using `common.py` helpers show consistent styling after the
  helper updates
