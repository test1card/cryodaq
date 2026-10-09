---
title: Color Usage Rules
keywords: color, token, palette, accent, status, semantic, hardcoded, hex, icon, inheritance
applies_to: all widgets using color
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Color Usage Rules

Enforcement rules for how color tokens from `tokens/colors.md` are applied in widget code. Violations are bugs. All rules have `enforcement: strict` unless marked otherwise.

Enforce in code via `# DESIGN: RULE-COLOR-XXX` comment marker.

**Rule index:**
- RULE-COLOR-001 — No raw hex in widget code
- RULE-COLOR-002 — Status color semantic lock
- RULE-COLOR-003 — One primary accent per composition
- RULE-COLOR-004 — ACCENT reserved for focus/selection affordance
- RULE-COLOR-005 — Icon color inheritance from text
- RULE-COLOR-006 — Hover state uses MUTED, never ACCENT
- RULE-COLOR-007 — Destructive actions use DESTRUCTIVE token (aliased to STATUS_FAULT)
- RULE-COLOR-008 — Text on colored surface uses ON_* paired token
- RULE-COLOR-009 — COLD_HIGHLIGHT vs STATUS_INFO semantic distinction
- RULE-COLOR-010 — Legacy STONE_* tokens read-only in new code

---

## RULE-COLOR-001: No raw hex in widget code

**TL;DR:** Never write `#1a1a1a` or `rgb(...)` directly in widget code. Always reference a token from `theme.py`.

**Statement:** Widget code MUST use `theme.*` token constants for all color values. Raw hex literals, `rgb(...)`, and `rgba(...)` are forbidden anywhere in `src/cryodaq/gui/`. This applies to Python code, QSS stylesheets embedded in Python strings, and any SVG assets generated at runtime.

**Rationale:** Raw hex bypasses the token system. If the theme changes or a token value is adjusted, widgets with hardcoded hex do not update — creating drift. Tokens exist as the single source of truth; raw hex is per-definition a violation.

**Applies to:** all widgets, QSS strings, runtime-generated SVG

**Example (good):**

```python
# DESIGN: RULE-COLOR-001
from cryodaq.gui import theme

self._card.setStyleSheet(
    f"background: {theme.SURFACE_ELEVATED};"
    f"border: 1px solid {theme.BORDER};"
    f"border-radius: {theme.RADIUS_LG}px;"
)
```

**Example (bad):**

```python
# Raw hex literals — theme changes don't propagate
self._card.setStyleSheet(
    "background: #22252f;"      # should be {theme.SURFACE_ELEVATED}
    "border: 1px solid #2d3038;" # should be {theme.BORDER}
    "border-radius: 8px;"        # should be {theme.RADIUS_LG}px
)
```

**Detection:**

```bash
# Any raw hex in gui code is a violation
rg -n '#[0-9a-fA-F]{6}\b' src/cryodaq/gui/ --glob '!theme.py' --glob '!assets/**'
```

Only `theme.py` defines raw hex values. Asset SVG files may contain hex if immutable (no runtime recoloring); if runtime-recolored, hex is stripped/replaced at load time.

**Exception:** None. Raw hex is strictly forbidden in widget code. Need a new value? Add a token to `theme.py` first.

**Related rules:** RULE-GOV-001 (token naming), RULE-COLOR-005 (icon color inheritance)

---

## RULE-COLOR-002: Status color semantic lock

**TL;DR:** `STATUS_OK`, `STATUS_WARNING`, `STATUS_CAUTION`, `STATUS_FAULT`, `STATUS_INFO`, `STATUS_STALE`, `COLD_HIGHLIGHT` carry locked semantic meanings. Do not reuse for non-matching concepts.

**Statement:** Each status token has a single locked semantic role (defined in `tokens/colors.md` Status palette). Using a status color for any other concept is a violation. Examples of violations: using `STATUS_OK` green for a generic "active" indicator, using `STATUS_FAULT` red for a "delete" button without destructive semantics, using `STATUS_INFO` blue for a generic accent.

**Rationale:** Operators learn status colors under stress. If `STATUS_OK` green can mean "healthy sensor" OR "active tab" OR "completed task," color loses signal value. Under alarm conditions, the operator wastes perception cycles disambiguating. Status colors must be predictable.

**Applies to:** any widget displaying status, state, or semantic categorical information

**Example (good):**

```python
# DESIGN: RULE-COLOR-002
# Active phase uses STATUS_OK — "this phase is operationally active and healthy"
active_phase_pill.setStyleSheet(
    f"border: 2px solid {theme.STATUS_OK};"
    f"color: {theme.FOREGROUND};"
)

# Fault indicator uses STATUS_FAULT
fault_banner.setStyleSheet(
    f"background: {theme.STATUS_FAULT};"
    f"color: {theme.ON_DESTRUCTIVE};"
)
```

**Example (bad):**

```python
# STATUS_OK misused as "selected tab" accent — not a status concept
selected_tab.setStyleSheet(
    f"border-bottom: 2px solid {theme.STATUS_OK};"  # WRONG
)
# Correct: use ACCENT for selection affordance (RULE-COLOR-004)

# STATUS_FAULT misused as generic delete button — not a fault
delete_button.setStyleSheet(
    f"background: {theme.STATUS_FAULT};"  # ambiguous
)
# Correct: use DESTRUCTIVE token (RULE-COLOR-007) which is an alias but
# carries destructive-action semantics, distinguishing from fault state
```

**Related rules:** RULE-COLOR-004 (ACCENT), RULE-COLOR-007 (DESTRUCTIVE), RULE-COLOR-009 (COLD_HIGHLIGHT vs INFO)

---

## RULE-COLOR-003: One primary accent per composition

**TL;DR:** A single surface (card, overlay, dashboard section) has exactly ONE primary accent color present. Multiple competing accents dilute hierarchy.

**Statement:** In any composition (dashboard tile, modal card content, overlay panel), only one accent may dominate. "Accent" here means a saturated or distinctive color that draws the eye — STATUS_* colors, ACCENT, COLD_HIGHLIGHT. Body elements use FOREGROUND and MUTED_FOREGROUND (neutral). The single accent signals the one thing that matters.

**Rationale:** If a card has STATUS_OK green border AND ACCENT violet focus ring AND STATUS_WARNING amber highlight AND COLD_HIGHLIGHT blue chart series — operators see four competing signals, cannot quickly parse which is most important. One accent preserves signal-to-noise.

**Applies to:** card interiors, modal compositions, overlay panels, BentoGrid tile contents

**Example (good):**

```python
# DESIGN: RULE-COLOR-003
# SensorCell — STATUS_OK (dominant accent on normal channel)
# Text uses FOREGROUND, MUTED_FOREGROUND — neutral
sensor_cell.setStyleSheet(
    f"QFrame#sensorCell {{ "
    f"  background: {theme.SURFACE_CARD}; "
    f"  border: 1px solid {theme.BORDER}; "
    f"  border-radius: {theme.RADIUS_MD}px; "
    f"}} "
    f"QLabel#sensorValue {{ color: {theme.FOREGROUND}; }} "
    f"QLabel#sensorLabel {{ color: {theme.MUTED_FOREGROUND}; }} "
    f"QLabel#sensorStatus {{ color: {theme.STATUS_OK}; }}"  # single accent
)
```

**Example (bad):**

```python
# Multiple competing accents in one tile
sensor_cell.setStyleSheet(
    f"border: 2px solid {theme.ACCENT}; "       # accent 1: purple
    f"QLabel#title {{ color: {theme.STATUS_OK}; }} "   # accent 2: green
    f"QLabel#value {{ color: {theme.COLD_HIGHLIGHT}; }} " # accent 3: blue
    f"QLabel#badge {{ background: {theme.STATUS_WARNING}; }}"  # accent 4: amber
)
# Result: eye doesn't know where to look
```

**Exception:** Data plots with multi-series use `PLOT_LINE_PALETTE` (8 accent colors) deliberately — that IS the data. Chart context is exempted; primary accent rule applies to non-data UI chrome.

**Related rules:** RULE-COLOR-002 (status semantic lock), RULE-COLOR-004 (ACCENT discipline)

---

## RULE-COLOR-004: ACCENT reserved for focus/selection affordance

**TL;DR:** `ACCENT #7c8cff` (and `RING`, same hex) is the focus/selection color ONLY. Not for status, not for phase indication, not for hover, not for primary buttons.

**Statement:** `theme.ACCENT` has exactly ONE semantic role: **focus or selection affordance**. Valid uses:

- Keyboard focus ring on any interactive widget
- Selected tab indicator (underline or background)
- Selected navigation item background in ToolRail
- Focused text input border
- Link color in text
- `TEXT_ACCENT` color for current selection label

Invalid uses (violations):

- Status color (use `STATUS_*`)
- Phase indication / active phase (use `STATUS_OK`)
- Hover state background (use `MUTED`, see RULE-COLOR-006)
- "Primary button" color — CryoDAQ has no primary button style; forms use `SECONDARY` surface
- Decorative accent (use neutral `FOREGROUND` or `MUTED_FOREGROUND`)

**Rationale:** Phase 0 decision. ACCENT was being used as both "focus ring" AND "active phase indicator" on dashboard PhaseStepper (violet fill for active phase). Two different semantic roles sharing one color = operators cannot distinguish "focused UI element" from "active experiment phase." Locking ACCENT to focus/selection restores clarity.

**Historical context:** Dashboard PhaseStepper previously used ACCENT as active-phase fill — this was the visual inconsistency Vladimir identified in first Phase I.1 review. ExperimentOverlay correctly used STATUS_OK green for active phase. Phase II.9 rebuild migrates PhaseStepper to STATUS_OK.

**Applies to:** any widget considering using `ACCENT` / `RING` / `TEXT_ACCENT`

**Example (good):**

```python
# DESIGN: RULE-COLOR-004
# Keyboard focus ring — correct ACCENT usage
text_input.setStyleSheet(
    f"QLineEdit {{ "
    f"  border: 1px solid {theme.BORDER}; "
    f"  border-radius: {theme.RADIUS_SM}px; "
    f"}} "
    f"QLineEdit:focus {{ "
    f"  border: 2px solid {theme.ACCENT};"  # focus ring — correct
    f"}}"
)

# Selected tab indicator — correct
selected_tab.setStyleSheet(
    f"border-bottom: 2px solid {theme.ACCENT};"  # selection — correct
)

# Active phase — uses STATUS_OK, NOT ACCENT
active_phase_pill.setStyleSheet(
    f"border: 2px solid {theme.STATUS_OK};"  # correct per RULE-COLOR-002
)
```

**Example (bad):**

```python
# ACCENT misused as active phase
active_phase_pill.setStyleSheet(
    f"background: {theme.ACCENT};"  # WRONG — active phase is status, not selection
    f"color: {theme.ON_ACCENT};"
)

# ACCENT misused as status color
success_banner.setStyleSheet(
    f"background: {theme.ACCENT};"  # WRONG — use STATUS_OK
)

# ACCENT misused as generic "primary button"
submit_button.setStyleSheet(
    f"background: {theme.ACCENT};"  # WRONG — no primary button style in CryoDAQ
)
```

**Detection:**

```bash
# Any ACCENT usage outside focus/selection context is suspicious
rg -n "theme\.ACCENT" src/cryodaq/gui/ | grep -v "focus\|:focus\|selected\|FocusRing\|focus_ring"
```

**Related rules:** RULE-COLOR-002 (status semantic), RULE-COLOR-006 (hover state)

---

## RULE-COLOR-005: Icon color inheritance from text

**TL;DR:** Icons must inherit color from surrounding text, not carry their own hue. An icon in body text is `FOREGROUND`; in muted caption is `MUTED_FOREGROUND`; in status context matches the status token.

**Statement:** SVG icons (from Lucide bundle) MUST render in the same color as adjacent text, or as the semantic color of the status they represent. Icons never have a fixed fill/stroke color hardcoded at rendering time. Color is applied dynamically via QPainter, SVG `currentColor`, or pre-processed SVG at load.

**Rationale:** Icons are typographic glyphs that happen to be vector art. A bell icon inline with "3 уведомления" text should render in the same color as "3 уведомления" — otherwise the icon visually detaches from the label it belongs to. Inheriting text color maintains the icon-as-glyph metaphor.

**Applies to:** all SVG icon rendering (Lucide bundle, status icons, inline emoji replacements)

**Example (good):**

```python
# DESIGN: RULE-COLOR-005
# Inline alert icon with warning status label — both amber
row = QHBoxLayout()
row.setSpacing(theme.SPACE_1)

icon = QLabel()
icon.setPixmap(
    load_colored_icon("alert-triangle", color=theme.STATUS_WARNING)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)  # proposed: theme.ICON_SIZE_SM — not yet in theme.py
)

label = QLabel("Внимание: калибровка устарела")
label.setStyleSheet(f"color: {theme.STATUS_WARNING};")

row.addWidget(icon)
row.addWidget(label)
```

```python
# Helper function pattern (proposed for cryodaq.gui.icon_utils)
def load_colored_icon(name: str, color: str = None) -> QIcon:
    """Load Lucide SVG and recolor stroke/fill to specified color.
    Default color: theme.FOREGROUND."""
    color = color or theme.FOREGROUND
    svg_path = assets_dir / f"{name}.svg"
    svg_text = svg_path.read_text()
    # Replace stroke and fill with target color
    svg_text = re.sub(r'stroke="[^"]*"', f'stroke="{color}"', svg_text)
    svg_text = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_text)
    # Render to pixmap
    ...
```

**Example (bad):**

```python
# Icon has its own hardcoded fill — doesn't respect context
# SVG file contains: <svg ... stroke="#7c8cff">...</svg>
icon.setPixmap(QPixmap("assets/icons/alert.svg"))  # fixed color regardless of context
label = QLabel("Норма")  # FOREGROUND text
# Result: blue icon next to white "Норма" — disconnected
```

**Exception:** Icons that are themselves logos or brand marks (e.g., if CryoDAQ ever has a brand logo in header) may carry fixed brand colors — these are not semantic icons, they are imagery.

**Related rules:** RULE-COLOR-001 (no raw hex), RULE-SPACE-008 (icon vertical alignment)

---

## RULE-COLOR-006: Hover state uses MUTED, never ACCENT

**TL;DR:** Hover background on buttons, list rows, and interactive elements uses `theme.MUTED` (subtle dark overlay). Never `theme.ACCENT` (ACCENT is for focus/selection only).

**Statement:** Mouse hover indicates "can interact with this." It is a subtle affordance, not a committed state. Hover state uses `MUTED #1d2028` (one shade above CARD background) as subtle highlight. Focus/selected/active states use ACCENT or STATUS_OK — those are committed states (user has navigated to, selected, or activated). Hover ≠ focus; their colors differ.

**Rationale:** Conflating hover with focus destroys keyboard navigation affordance. If hover paints ACCENT and focus paints ACCENT, operator can't tell by looking at the screen whether a button is "cursor is over it" or "keyboard has focused it" — two very different states.

**Applies to:** buttons, list rows, menu items, tile cards, any interactive element

**Example (good):**

```python
# DESIGN: RULE-COLOR-006
# Button with distinct hover, focus, active states
button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
    }}
    QPushButton:hover {{
        background: {theme.MUTED};  /* subtle hover */
    }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};  /* focus ring */
    }}
    QPushButton:pressed {{
        background: {theme.BORDER};  /* pressed = darker than hover */
    }}
""")
```

**Example (bad):**

```python
# Hover uses ACCENT — conflates with focus
button.setStyleSheet(f"""
    QPushButton:hover {{
        background: {theme.ACCENT};  /* WRONG — looks like focus */
        color: {theme.ON_ACCENT};
    }}
    QPushButton:focus {{
        background: {theme.ACCENT};  /* identical to hover — indistinguishable */
        color: {theme.ON_ACCENT};
    }}
""")
```

**Related rules:** RULE-COLOR-004 (ACCENT semantic lock), RULE-INTER-001 (focus ring mandatory)

---

## RULE-COLOR-007: Destructive actions use DESTRUCTIVE token

**TL;DR:** Destructive action buttons (АВАР. ОТКЛ., Удалить эксперимент) use `theme.DESTRUCTIVE`, not raw `STATUS_FAULT`. They are aliases but semantic intent differs.

**Statement:** `DESTRUCTIVE` and `STATUS_FAULT` resolve to the same hex `#c44545` but represent different concepts:
- `STATUS_FAULT` — the system IS in fault state (descriptive; something went wrong)
- `DESTRUCTIVE` — an action that WILL cause fault / data loss / irreversible change (prescriptive; about to do something dangerous)

Use `DESTRUCTIVE` on buttons that initiate destructive actions. Use `STATUS_FAULT` on indicators showing a fault has occurred.

**Rationale:** Same hex, different code-level semantics. Future theme evolution might separate them (e.g., darker shade for DESTRUCTIVE to differentiate from FAULT status). Using the correct alias at call site preserves intent.

**Applies to:** destructive action buttons (emergency stop, delete, cancel-with-data-loss), confirmation dialogs

**Example (good):**

```python
# DESIGN: RULE-COLOR-007
# Emergency stop button — destructive action
emergency_stop = QPushButton("АВАР. ОТКЛ.")
emergency_stop.setStyleSheet(f"""
    QPushButton {{
        background: {theme.DESTRUCTIVE};
        color: {theme.ON_DESTRUCTIVE};
        border-radius: {theme.RADIUS_SM}px;
        font-weight: {theme.FONT_WEIGHT_SEMIBOLD};
    }}
""")

# Fault banner — fault state occurred
fault_banner.setStyleSheet(f"""
    background: {theme.STATUS_FAULT};
    color: {theme.ON_DESTRUCTIVE};
""")
```

**Example (bad):**

```python
# Emergency stop uses STATUS_FAULT — semantic confusion
# "Is the system in fault, or is this button about to cause fault?"
emergency_stop.setStyleSheet(
    f"background: {theme.STATUS_FAULT};"  # WRONG — use DESTRUCTIVE
)

# Fault banner uses DESTRUCTIVE — semantic confusion
fault_banner.setStyleSheet(
    f"background: {theme.DESTRUCTIVE};"  # WRONG — use STATUS_FAULT
)
```

**Detection:**

```bash
# Destructive action buttons should reference DESTRUCTIVE, not STATUS_FAULT
rg -n "АВАР|Удалить|Delete|Emergency" src/cryodaq/gui/ -A 5 | grep "STATUS_FAULT"
# ↑ any matches are likely violations
```

**Related rules:** RULE-COLOR-002 (status semantic lock), RULE-INTER-004 (destructive confirmation)

---

## RULE-COLOR-008: Text on colored surface uses ON_* paired token

**TL;DR:** When text sits on a colored background (not the default `BACKGROUND`), use the matching `ON_*` token for text color. Don't hardcode white or `FOREGROUND`.

**Statement:** Colored backgrounds have paired text colors defined via `ON_*` tokens:
- `ON_ACCENT #0d0e12` — text on `ACCENT` background (darker because ACCENT is light violet)
- `ON_PRIMARY #e8eaf0` — text on `PRIMARY` surface (same as CARD — this is a neutral pair)
- `ON_SECONDARY #e8eaf0` — text on `SECONDARY` surface (same as SURFACE_ELEVATED — neutral pair)
- `ON_DESTRUCTIVE #e8eaf0` — text on `DESTRUCTIVE` / `STATUS_FAULT` red background (light foreground for contrast)

Using ON_* preserves the token-pairing contract. If theme updates change background shade, the paired ON_* color updates accordingly, maintaining contrast.

**Rationale:** shadcn/ui convention — foreground/background tokens come in pairs. Treating them as pairs (not independent choices) keeps contrast relationships explicit and updateable.

**Applies to:** any widget with colored background containing text (status banners, destructive buttons, selected tab text, ACCENT-background chips)

**Example (good):**

```python
# DESIGN: RULE-COLOR-008
# Selected tab — ACCENT background, ON_ACCENT text
selected_tab.setStyleSheet(
    f"background: {theme.ACCENT};"
    f"color: {theme.ON_ACCENT};"  # dark text on light violet
)

# Destructive button — DESTRUCTIVE background, ON_DESTRUCTIVE text
delete_button.setStyleSheet(
    f"background: {theme.DESTRUCTIVE};"
    f"color: {theme.ON_DESTRUCTIVE};"  # light text on red
)
```

**Example (bad):**

```python
# Hardcoded white text on ACCENT — may or may not contrast
selected_tab.setStyleSheet(
    f"background: {theme.ACCENT};"
    f"color: #FFFFFF;"  # WRONG — also violates RULE-COLOR-001
)

# FOREGROUND on ACCENT — wrong color direction
# FOREGROUND is light text (intended for dark bg); on light ACCENT it lacks contrast
tab.setStyleSheet(
    f"background: {theme.ACCENT};"
    f"color: {theme.FOREGROUND};"  # WRONG — should be ON_ACCENT (dark)
)
```

**Related rules:** RULE-COLOR-001 (no raw hex), RULE-A11Y-003 (contrast requirements)

---

## RULE-COLOR-009: COLD_HIGHLIGHT vs STATUS_INFO semantic distinction

**TL;DR:** `COLD_HIGHLIGHT #5b8db8` and `STATUS_INFO #4a7ba8` are similar dusty blues but are NOT interchangeable. Cold = cryogenic state indicator. Info = neutral informational notice.

**Statement:** Despite visual similarity (both are muted slate-blues), these tokens carry distinct semantics:

- **`COLD_HIGHLIGHT`** — domain-specific indicator that something is cold or cryogenic. Used for:
  - Chart series for cold-channel temperature traces
  - Highlighting Т5 (Экран 77К) or Т6 (Экран 4К) in sensor grid
  - Pressure-temperature phase diagram cold region
  
- **`STATUS_INFO`** — generic informational emphasis. Used for:
  - Info badge / neutral notice
  - Hover hint containing technical details
  - "Did you know?" operator guidance

Do not substitute one for the other. An operator seeing COLD_HIGHLIGHT interprets "cryogenic"; seeing STATUS_INFO interprets "for your information."

**Rationale:** Domain semantics are foundational for cryogenic lab UI. A visual cue meaning "this is cold" is not the same as "this is informational." Separating preserves domain clarity even if visual distinction is subtle.

**Visual note:** The colors ARE similar by design — both are muted slate-blues consistent with desaturated aesthetic. Distinction is by context where they appear, not by eye alone. Code usage makes the distinction explicit.

**Applies to:** status displays, chart series, inline hints, domain indicators

**Example (good):**

```python
# DESIGN: RULE-COLOR-009
# Cold channel highlight — cryogenic state
cold_sensor_label.setStyleSheet(
    f"color: {theme.COLD_HIGHLIGHT};"  # cold state
    f"font-weight: {theme.FONT_WEIGHT_MEDIUM};"
)

# Information notice — not cold, just informational
info_notice.setStyleSheet(
    f"border-left: 3px solid {theme.STATUS_INFO};"  # info context
    f"background: {theme.SURFACE_CARD};"
)
```

**Example (bad):**

```python
# Cold sensor uses STATUS_INFO — loses domain meaning
cold_sensor_label.setStyleSheet(
    f"color: {theme.STATUS_INFO};"  # AMBIGUOUS — looks cold but means "info"
)

# Info notice uses COLD_HIGHLIGHT — implies "cryogenic notice" which is meaningless
info_notice.setStyleSheet(
    f"border-left: 3px solid {theme.COLD_HIGHLIGHT};"  # WRONG semantic
)
```

**Related rules:** RULE-COLOR-002 (status semantic lock), RULE-DATA-007 (chart palette)

---

## RULE-COLOR-010: Legacy STONE_* tokens read-only in new code

**TL;DR:** `STONE_0` through `STONE_1000` are legacy aliases from qdarktheme. Existing code may continue using them; new code MUST use modern semantic names.

**Statement:** 13 `STONE_*` tokens exist as backward-compat aliases (see `tokens/colors.md` Legacy palette). They map to modern names:
- `STONE_0`, `STONE_50` → `BACKGROUND`
- `STONE_100`, `STONE_150` → `CARD`
- `STONE_200` → `SECONDARY` / `SURFACE_ELEVATED`
- `STONE_300` → `BORDER`
- `STONE_500` → `TEXT_DISABLED`
- `STONE_600`, `STONE_700` → `MUTED_FOREGROUND`
- `STONE_900` → `FOREGROUND`
- `STONE_400`, `STONE_800`, `STONE_1000` — no modern equivalent (light theme inverse shades)

**New code:** Use modern semantic name. `theme.BACKGROUND`, not `theme.STONE_0`.

**Existing code:** Leave as-is during natural refactoring cadence. Do not force mass migration as a separate task.

**Eventually removed code:** STONE_400, STONE_800, STONE_1000 have no modern equivalent. Do not introduce new uses — they exist only for qdarktheme integration and will be removed if/when qdarktheme dependency is dropped.

**Rationale:** Zero breaking change policy for this refactor phase. Legacy aliases preserve continuity while new code adopts modern names naturally over time.

**Applies to:** new widget code, any widget modifications

**Example (good):**

```python
# DESIGN: RULE-COLOR-010
# New code uses modern names
new_card.setStyleSheet(
    f"background: {theme.CARD};"                # not STONE_100
    f"color: {theme.FOREGROUND};"               # not STONE_900
    f"border: 1px solid {theme.BORDER};"        # not STONE_300
)
```

**Example (acceptable — existing code):**

```python
# Existing widget in dashboard/ uses STONE_* — leave alone
# During natural refactor opportunity, migrate to modern names
existing_widget.setStyleSheet(
    f"background: {theme.STONE_100};"  # OK if predates this rule
)
```

**Example (bad):**

```python
# New code introducing STONE_* usage
freshly_written_widget.setStyleSheet(
    f"background: {theme.STONE_100};"  # WRONG — use CARD instead
)
```

**Detection:**

```bash
# Count STONE_* usage over time — should decline, not grow
rg -n "theme\.STONE_" src/cryodaq/gui/ | wc -l
# Track this number in governance review; growth is a red flag
```

**Related rules:** RULE-GOV-003 (deprecation policy — see `governance/deprecation-policy.md`)

---

## Changelog

- 2026-04-17: Initial version. 10 rules covering hex literals, status semantic lock, ACCENT discipline, icon color inheritance, hover/focus distinction, destructive actions, text-on-color pairing, COLD_HIGHLIGHT vs INFO distinction, STONE_* legacy policy. RULE-COLOR-005 (icon color inheritance) absorbed from earlier proposed standalone "icon" category per audit decision.
