---
title: Typography Rules
keywords: typography, font, size, weight, tabular, ligature, cyrillic, fira, preset, scale
applies_to: all widgets rendering text
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Typography Rules

Enforcement rules for typography usage from `tokens/typography.md`. Typography is load-bearing for data readability — violations compound over 12-hour operator shifts.

Enforce in code via `# DESIGN: RULE-TYPO-XXX` comment marker.

**Rule index:**
- RULE-TYPO-001 — Prefer Tier 2 preset over Tier 1 primitives
- RULE-TYPO-002 — Bundle Fira fonts via QFontDatabase
- RULE-TYPO-003 — Tabular numbers (`tnum`) mandatory on numeric displays
- RULE-TYPO-004 — Programming ligatures (`liga`) disabled in UI context
- RULE-TYPO-005 — Cyrillic uppercase requires positive letter-spacing
- RULE-TYPO-006 — Minimum font-weight 400 in operator UI
- RULE-TYPO-007 — Off-scale sizes (15, 32) protected from normalization
- RULE-TYPO-008 — Uppercase convention for labels and tile titles
- RULE-TYPO-009 — Line-height ratios follow scale guidance
- RULE-TYPO-010 — Text color paired with typography context

---

## RULE-TYPO-001: Prefer Tier 2 preset over Tier 1 primitives

**TL;DR:** Use complete semantic presets (`FONT_BODY_*`, `FONT_DISPLAY_*`, etc.) instead of assembling font from `FONT_SIZE_BASE` + `FONT_WEIGHT_REGULAR` + custom line-height manually.

**Statement:** Typography tokens come in two tiers (see `tokens/typography.md`):
- **Tier 1 primitives**: `FONT_BODY` (family), `FONT_SIZE_BASE` (size), `FONT_WEIGHT_REGULAR` (weight) — reusable building blocks
- **Tier 2 semantic presets**: `FONT_BODY_SIZE` / `FONT_BODY_WEIGHT` / `FONT_BODY_HEIGHT` — complete triples for a text role

Widgets MUST use Tier 2 presets where one matches the use case. Tier 1 primitives are for exceptional contexts (plot axis font computed dynamically, custom one-off display).

**Rationale:** Presets lock together size + weight + line-height for a specific text role. Composing manually from primitives creates drift — two widgets using "body" text might end up with slightly different line-heights, making vertical rhythm inconsistent.

**Applies to:** all widget font configuration

**Example (good):**

```python
# DESIGN: RULE-TYPO-001
# Using semantic preset — FONT_MONO_VALUE_* for sensor data cell
font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
# Line-height applied via QLabel padding or stylesheet
value_label.setFont(font)
value_label.setStyleSheet(
    f"line-height: {theme.FONT_MONO_VALUE_HEIGHT}px;"
)
```

**Example (acceptable — exceptional case):**

```python
# Plot axis font — dynamically sized based on plot widget
# No semantic preset covers "axis ticks at computed zoom level"
# DESIGN: RULE-TYPO-001 exception: plot-axis font computed from zoom
font = QFont(theme.FONT_MONO, theme.FONT_SIZE_SM)  # Tier 1 primitives
font.setWeight(theme.FONT_WEIGHT_MEDIUM)
plot.getAxis('left').setTickFont(font)
```

**Example (bad):**

```python
# Assembling "body text" from primitives when FONT_BODY_* preset exists
font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
font.setWeight(theme.FONT_WEIGHT_REGULAR)
# Using 16px line-height — but FONT_BODY_HEIGHT = 20, and this drift accumulates
label.setFont(font)
label.setStyleSheet("line-height: 16px;")  # WRONG — preset says 20
```

**Related rules:** RULE-TYPO-009 (line-height ratios), RULE-TYPO-010 (text color pairing)

---

## RULE-TYPO-002: Bundle Fira fonts via QFontDatabase

**TL;DR:** Fira Sans and Fira Code are NOT installed on macOS/Windows by default. Application MUST register bundled `.ttf` files at startup via `QFontDatabase.addApplicationFont()`.

**Statement:** Font files MUST be bundled at `src/cryodaq/gui/assets/fonts/` and registered at application startup before any QWidget is instantiated. If registration fails (file missing, corrupt), application logs a warning and Qt fallback chain applies (see `tokens/typography.md` fallback chain).

**Rationale:** Vladimir's Mac dev machine does NOT have Fira Sans / Fira Code installed. Qt falls back to Helvetica, breaking aesthetic. Lab PC (Ubuntu) similarly may not have Fira installed. Bundling ensures consistent rendering across all machines.

Observed evidence: Qt warning during Phase I.1 development: `qt.qpa.fonts: Replace uses of missing font family "Fira Sans" with one that exists`.

**Applies to:** application startup code (launcher, main app init)

**Example (good):**

```python
# DESIGN: RULE-TYPO-002
# In src/cryodaq/gui/fonts.py (or launcher init)
from pathlib import Path
from PySide6.QtGui import QFontDatabase
import logging

log = logging.getLogger(__name__)

FONT_FILES = [
    "FiraSans-Regular.ttf",
    "FiraSans-Medium.ttf",
    "FiraSans-SemiBold.ttf",
    "FiraSans-Bold.ttf",
    "FiraCode-Regular.ttf",
    "FiraCode-Medium.ttf",
    "FiraCode-SemiBold.ttf",
    "FiraCode-Bold.ttf",
]

def register_fonts() -> None:
    """Register bundled Fira fonts. Must be called before any QWidget."""
    assets_dir = Path(__file__).parent / "assets" / "fonts"
    for font_file in FONT_FILES:
        path = assets_dir / font_file
        if not path.exists():
            log.warning(f"Font file missing: {path}")
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            log.error(f"Failed to register font: {path}")
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            log.info(f"Registered font: {families}")

# In main launcher, BEFORE creating QApplication widgets:
def main():
    app = QApplication(sys.argv)
    register_fonts()  # MUST be before MainWindow() or any widget
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
```

**Example (bad):**

```python
# No font registration — relies on system-installed fonts
def main():
    app = QApplication(sys.argv)
    window = MainWindow()  # MainWindow uses theme.FONT_BODY="Fira Sans"
    # On macOS dev machine without Fira installed: Qt falls back to Helvetica
    # Aesthetic broken, monospace data cells misaligned
    window.show()
```

**Deployment note:** Font licensing: Fira fonts are SIL Open Font License (permissive, commercial-use OK). Bundle with application, attribution in LICENSE if distributed.

**Related rules:** `tokens/typography.md` fallback chain

---

## RULE-TYPO-003: Tabular numbers mandatory on numeric displays

**TL;DR:** Any widget displaying a live-updating number MUST enable OpenType `tnum` feature. Without this, digit widths differ; value changes from "4.21" to "4.30" cause horizontal jitter.

**Statement:** When displaying numeric values that change over time (sensor readings, timestamps, measurements, counters), font MUST have `tnum` (tabular numbers) OpenType feature activated. This renders all digit glyphs at equal width, preventing layout shift on value update.

Fira Code (used in `FONT_MONO`, `FONT_DISPLAY`) has tnum by default (monospace fundamental). Fira Sans (used in `FONT_BODY`) requires explicit activation.

**Rationale:** Non-tabular numbers in real-time data is visually jarring and functionally broken. When a temperature changes from 4.21 K → 4.30 K, if "2" and "3" have different widths, the "1" on the right shifts horizontally by 1-2 pixels. Over a 2Hz update, this creates visible jitter. Operators lose precision when reading jittering values.

**Applies to:** SensorCell values, Keithley readouts, pressure displays, timers, percentage indicators, any live-updating numeric text

**Example (good):**

```python
# DESIGN: RULE-TYPO-003
# SensorCell value using Fira Code (inherently tabular)
font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
# Fira Code has tnum by default — but explicit is safer
# Qt 6.5+ supports setFeature; older versions use setFeatures dict
font.setFeature("tnum", 1)
value_label.setFont(font)
```

```python
# Numeric value in Fira Sans body context — must explicitly enable tnum
percent_label_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
percent_label_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
percent_label_font.setFeature("tnum", 1)  # MANDATORY for Fira Sans + numbers
percent_label.setFont(percent_label_font)
percent_label.setText("47%")
```

**Example (bad):**

```python
# Live sensor value in Fira Sans without tnum
font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
value_label.setFont(font)
# As value updates every 500ms, "4.21" → "4.30" → "4.45" causes horizontal jitter
# Operators see "twitching" readings
```

**Detection:**

```bash
# Any widget setting font on live-data label should have tnum activation
rg -n "setFont.*FONT_(BODY|LABEL)" src/cryodaq/gui/ -A 3 | grep -B 1 "setText.*%\|sensor\|value"
# Check each match for tnum feature activation
```

**Related rules:** RULE-TYPO-004 (liga off), RULE-DATA-003 (no jitter on updates)

---

## RULE-TYPO-004: Programming ligatures disabled in UI context

**TL;DR:** Fira Code has programming ligatures (`!=`, `==`, `->`, `>=`) that merge into single glyphs. Disable via `liga: 0` feature for UI text where these sequences might appear.

**Statement:** Fira Code, when rendered with default OpenType settings, converts character sequences like `!=`, `==`, `>=`, `->`, `<=` into single programmer-friendly ligature glyphs. In UI context (labels, status text, data comments), these sequences are rare but possible, and when they occur, operators see confusing merged glyphs.

Widgets using `FONT_MONO` or `FONT_DISPLAY` (both Fira Code) MUST disable ligatures unless the context is explicitly source code display (currently: no such context in CryoDAQ).

**Rationale:** Programming ligatures are designed for code editors where `a != b` reads as "a not-equal b" with a special glyph. In operator comments or status text, "reached 5 != limit" might appear, and the `!=` becoming a single glyph looks like a typo or corruption.

Fira Sans does not have programming ligatures; `liga: 0` on FONT_BODY is harmless but unnecessary.

**Applies to:** widgets using FONT_MONO (data cells, timestamps, log entries) and FONT_DISPLAY (TopWatchBar headers)

**Example (good):**

```python
# DESIGN: RULE-TYPO-004
# Mono value cell — disable ligatures
font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
font.setFeature("tnum", 1)  # RULE-TYPO-003
font.setFeature("liga", 0)  # RULE-TYPO-004 — disable ligatures
value_label.setFont(font)
```

**Example (bad):**

```python
# Mono font without liga disable
font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
# Default Fira Code has liga on
value_label.setFont(font)
value_label.setText("Predicted cooldown -> 48 minutes")
# Operators see "Predicted cooldown [merged-arrow] 48 minutes"
# Confusing if they expect "->" as plain ASCII
```

**Exception:** If CryoDAQ ever adds a source code viewer (e.g., TSP script editor for Keithley custom commands per K4), ligatures MAY be enabled in that specific widget for code readability.

**Related rules:** RULE-TYPO-003 (tnum), `tokens/typography.md` OpenType features

---

## RULE-TYPO-005: Cyrillic uppercase requires positive letter-spacing

**TL;DR:** UPPERCASE Cyrillic labels ("АВАР. ОТКЛ.", "ЭКСПЕРИМЕНТ") need `letter-spacing: 0.05em` because default Cyrillic uppercase tracks narrower than Latin. Without this, letters visually cram together.

**Statement:** When rendering Russian uppercase labels at any size, widget font MUST apply positive letter-spacing. Fira Sans (and most fonts) are optimized for Latin uppercase tracking; Cyrillic uppercase glyphs are on average 5-10% narrower, causing visual cramping when tracked at zero.

Recommended tracking: `0.05em` (5% of font size). This corresponds to `QFont.setLetterSpacing(QFont.AbsoluteSpacing, 0.05 * font_size)` or stylesheet `letter-spacing: 0.05em`.

**Rationale:** Typography is tuned for Latin. Cyrillic has denser glyph structure. Without explicit tracking, an uppercase label like "АВАР. ОТКЛ." renders as "АВАРОТКЛ"-like visual blob. Latin equivalent "EMERG. STOP." looks fine at same tracking due to wider Latin letterforms.

**Applies to:** any widget displaying uppercase Cyrillic text at any size, especially headers, buttons, status labels

**Example (good):**

```python
# DESIGN: RULE-TYPO-005
# Destructive button with Cyrillic uppercase label
button_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
button_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
button_font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing,
    0.05 * theme.FONT_LABEL_SIZE  # 0.6px for 12px font
)
emergency_button = QPushButton("АВАР. ОТКЛ.")
emergency_button.setFont(button_font)
```

**Alternative via stylesheet:**

```python
button.setStyleSheet(f"""
    QPushButton {{
        font-family: {theme.FONT_BODY};
        font-size: {theme.FONT_LABEL_SIZE}px;
        font-weight: {theme.FONT_WEIGHT_SEMIBOLD};
        letter-spacing: 0.05em;  /* 5% of font-size */
        text-transform: none; /* explicit — text is already uppercase */
    }}
""")
button.setText("АВАР. ОТКЛ.")
```

**Example (bad):**

```python
# No letter-spacing — Cyrillic uppercase cramps
button_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
button_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
button = QPushButton("АВАР. ОТКЛ.")
button.setFont(button_font)
# Visual result: "АВАР.ОТКЛ." appears cramped, period almost touches "О"
```

**Exception:** Lowercase or title-case Cyrillic (e.g., "Эксперимент", "Захолаживание") does NOT need explicit letter-spacing. Default tracking is optimized for mixed-case Cyrillic. Rule applies only to UPPERCASE.

**Related rules:** RULE-TYPO-008 (when to use uppercase), RULE-COPY-002 (Russian text conventions)

---

## RULE-TYPO-006: Minimum font-weight 400 in operator UI

**TL;DR:** No text below `FONT_WEIGHT_REGULAR` (400) in operator-facing widgets. Weights 100-300 render as "ghostly" on low-DPI lab monitors and fail readability at arm's length.

**Statement:** Any text displayed to operators MUST use font-weight ≥ 400 (REGULAR). Lighter weights (100 THIN, 200 EXTRALIGHT, 300 LIGHT) are forbidden even though Fira Sans supports them.

Typography scale weights: REGULAR 400, MEDIUM 500, SEMIBOLD 600, BOLD 700 (see `tokens/typography.md`). All four are valid choices.

**Rationale:** Lab PC is non-retina LCD at 96 DPI. At typical viewing distance (~60cm), font weights below 400 render with pixel artifacts — letters appear broken or translucent. Operators during night shifts with tired eyes cannot read light-weight text reliably. Minimum weight 400 ensures all text passes readability threshold.

**Applies to:** any widget displaying operator-facing text. Does NOT apply to decorative or diagnostic text not meant for operators.

**Example (good):**

```python
# DESIGN: RULE-TYPO-006
# Body text — REGULAR 400 minimum
body_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
body_font.setWeight(theme.FONT_WEIGHT_REGULAR)  # 400
label.setFont(body_font)

# Emphasized label — MEDIUM 500
label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
label_font.setWeight(theme.FONT_WEIGHT_MEDIUM)  # 500
emphasized.setFont(label_font)

# Section heading — SEMIBOLD 600
heading_font = QFont(theme.FONT_BODY, theme.FONT_HEADING_SIZE)
heading_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)  # 600
heading.setFont(heading_font)
```

**Example (bad):**

```python
# LIGHT weight in operator UI
subtitle_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_LG)
subtitle_font.setWeight(300)  # WRONG — too light for lab monitor
subtitle.setFont(subtitle_font)
# Visual result: "ghostly" text, hard to read at arm's length
```

**Detection:**

```bash
# Any font weight < 400 in widget code
rg -n "setWeight\(([0-3][0-9]{2}|100|200|300)\)" src/cryodaq/gui/
# Also rg -n "font-weight:\s*(100|200|300)" src/cryodaq/gui/
```

**Related rules:** RULE-A11Y-005 (readability at distance), `tokens/typography.md`

---

## RULE-TYPO-007: Off-scale sizes protected from normalization

**TL;DR:** `FONT_MONO_VALUE_SIZE = 15` and `FONT_DISPLAY_SIZE = 32` are intentionally off-scale (not in `FONT_SIZE_*` primitives). Do not "normalize" them to scale values. They solve specific problems.

**Statement:** Two font sizes in `tokens/typography.md` do not appear in the primary scale (XS=11, SM=12, BASE=14, LG=16, XL=20, 2XL=28, 3XL=40):

- **`FONT_MONO_VALUE_SIZE = 15`** — used only in `FONT_MONO_VALUE_*` preset for SensorCell values. Between BASE (14) and LG (16). Optimized for 4-digit temperature readings in Fira Code Medium.
- **`FONT_DISPLAY_SIZE = 32`** — used only in `FONT_DISPLAY_*` preset for TopWatchBar headers. Between 2XL (28) and 3XL (40). Optimized to be larger than page titles but smaller than hero.

These values are PROTECTED. Do not change them to match scale "for consistency." They are calibrated to specific widgets' legibility requirements.

**Rationale:** A future developer seeing `FONT_MONO_VALUE_SIZE = 15` might think "this is an outlier; let's normalize to `FONT_SIZE_BASE = 14` or `FONT_SIZE_LG = 16` to match the scale." That "normalization" would break SensorCell readability.

4-digit temperature readouts (e.g., "292.15 K") at:
- 14px: just below legibility threshold for quick scanning
- 15px: sweet spot — readable at 60cm distance, fits compact cell
- 16px: too large — breaks 2-column sensor grid layout on 1920 viewport

Similar tuning for 32 vs 28/40 in display context.

**Applies to:** `tokens/typography.md` size constant definitions, any refactoring touching typography tokens

**Example (good):**

```python
# DESIGN: RULE-TYPO-007
# Using protected size directly — correct
value_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)  # 15px
```

**Example (bad):**

```python
# "Normalizing" to scale — breaks SensorCell legibility
# In a refactoring PR someone decides to align to scale:
FONT_MONO_VALUE_SIZE = theme.FONT_SIZE_BASE  # 14 — WRONG, now too small
# OR:
FONT_MONO_VALUE_SIZE = theme.FONT_SIZE_LG  # 16 — WRONG, breaks layout
```

**If you genuinely think an off-scale size needs changing:**

1. Verify on actual lab hardware (1440-1920 viewport, 96 DPI)
2. Measure SensorCell 4-digit readability at arm's length
3. Check layout impact on 1920 viewport with full sensor grid
4. Discuss with Vladimir before changing

**Related rules:** `tokens/typography.md` off-scale sizes note

---

## RULE-TYPO-008: Uppercase convention for labels and tile titles

**TL;DR:** Labels and tile titles MAY be UPPERCASE when they function as category headers (KPI card title, status chip). Body prose and running text stay in natural case.

**Statement:** UPPERCASE Cyrillic usage in CryoDAQ UI follows this convention:

**Valid uppercase contexts:**
- Tile titles in BentoGrid: "ДАВЛЕНИЕ", "ТЕМПЕРАТУРА", "АНАЛИТИКА" (compact header labels)
- Status chips / badges: "НОРМА", "ВНИМАНИЕ", "АВАРИЯ"
- Destructive action buttons: "АВАР. ОТКЛ."
- Section dividers (rare): "ПРИБОРЫ"

**Invalid uppercase contexts:**
- Body prose: "ЭКСПЕРИМЕНТ НАЧАТ В 14:32" → use "Эксперимент начат в 14:32"
- Tooltips: "НАЖМИТЕ ДЛЯ ОТКРЫТИЯ" → use "Нажмите для открытия"
- Alert messages: "ТЕМПЕРАТУРА ВЫШЕ ПРЕДЕЛА" → use "Температура выше предела"
- Button labels with action phrasing: "СОХРАНИТЬ ЭКСПЕРИМЕНТ" → use "Сохранить эксперимент"

**Rationale:** Uppercase functions as a compact category label in dense data dashboards (Swiss typography tradition — category labels uppercase, body sentence case). Reading long uppercase text is significantly slower than mixed case; uppercase prose is tiring and less legible.

When uppercase IS used, it MUST combine with:
- `FONT_LABEL_*` preset typically (MEDIUM weight, SM size)
- Letter-spacing per RULE-TYPO-005

**Applies to:** copy writing, label construction, UI text decisions

**Example (good):**

```python
# DESIGN: RULE-TYPO-008
# Tile title — uppercase category header
tile_title = QLabel("ДАВЛЕНИЕ")  # category label
tile_title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
tile_title_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
tile_title_font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
)
tile_title.setFont(tile_title_font)

# Body text — sentence case
body_text = QLabel("Эксперимент переведён в фазу захолаживания")
body_font = QFont(theme.FONT_BODY, theme.FONT_BODY_SIZE)
body_font.setWeight(theme.FONT_BODY_WEIGHT)
body_text.setFont(body_font)
```

**Example (bad):**

```python
# Uppercase body prose — hard to read
status_label = QLabel("ЭКСПЕРИМЕНТ ПЕРЕВЕДЁН В ФАЗУ ЗАХОЛАЖИВАНИЯ")
# Should be: "Эксперимент переведён в фазу захолаживания"

# Uppercase tooltip
button.setToolTip("НАЖМИТЕ ДЛЯ НАЧАЛА ЭКСПЕРИМЕНТА")  # WRONG
# Should be: "Нажмите для начала эксперимента"
```

**Related rules:** RULE-TYPO-005 (Cyrillic uppercase letter-spacing), RULE-COPY-003 (Russian UI text style)

---

## RULE-TYPO-009: Line-height ratios follow scale guidance

**TL;DR:** Line-height ratio 1.4-1.5 for body text, 1.1-1.25 for headings, 1.1 for display numerics. Use Tier 2 presets which encode correct ratios, or follow `tokens/typography.md` reference table.

**Statement:** When setting line-height explicitly (in QSS stylesheet or via QLabel height), values MUST follow the ratio guidance in `tokens/typography.md` "Line-height reference" table. Deviations require documented reason.

Key ratios:
- Body text (11-16px): line-height 1.4-1.5 (multi-line readability)
- Headings (18-28px): line-height 1.1-1.25 (tight density)
- Display numerics (32-40px): line-height 1.1 (near-monoline)

**Rationale:** Typography vertical rhythm depends on consistent line-height ratios. Too tight (1.0x) makes lines feel cramped and multi-line reading slow. Too loose (1.8x) creates visual gaps disconnecting lines. The 1.4-1.5 body range matches reading ergonomics research.

**Applies to:** custom line-height settings, QLabel heights, stylesheet line-height properties

**Example (good):**

```python
# DESIGN: RULE-TYPO-009
# Body text — ratio 1.43 (20/14)
body_label.setStyleSheet(
    f"font-size: {theme.FONT_BODY_SIZE}px;"       # 14
    f"line-height: {theme.FONT_BODY_HEIGHT}px;"   # 20 → ratio 1.43 ✓
)

# Heading — ratio 1.14 (32/28)
heading.setStyleSheet(
    f"font-size: {theme.FONT_SIZE_2XL}px;"   # 28
    f"line-height: 32px;"                    # ratio 1.14 ✓
)
```

**Example (bad):**

```python
# Body text at line-height 1.0 — cramped
body.setStyleSheet(
    f"font-size: 14px;"
    f"line-height: 14px;"  # WRONG — ratio 1.0, no room for descenders
)

# Heading at line-height 1.8 — loose, disconnected
heading.setStyleSheet(
    f"font-size: 28px;"
    f"line-height: 50px;"  # WRONG — ratio 1.79, far too loose
)
```

**Related rules:** RULE-TYPO-001 (prefer presets), `tokens/typography.md` reference table

---

## RULE-TYPO-010: Text color paired with typography context

**TL;DR:** Text color follows typography role. Body text → `FOREGROUND`. Labels → `FOREGROUND` or `MUTED_FOREGROUND`. Captions/timestamps → `MUTED_FOREGROUND`. Status text → TEXT_* semantic alias.

**Statement:** Color choice for text MUST match its typographic role (see mapping table below). Do not set `color: {theme.ACCENT}` on a body paragraph or `color: {theme.FOREGROUND}` on a timestamp.

| Text role (Tier 2 preset) | Default color | Alternative |
|---|---|---|
| `FONT_DISPLAY_*` (hero numeric) | `FOREGROUND` | Domain color (e.g., COLD_HIGHLIGHT for cold sensor) |
| `FONT_TITLE_*` (page/modal title) | `FOREGROUND` | — |
| `FONT_HEADING_*` (section heading) | `FOREGROUND` | — |
| `FONT_LABEL_*` (label, category) | `FOREGROUND` or `MUTED_FOREGROUND` | `TEXT_OK`, `TEXT_WARNING`, etc. for status |
| `FONT_BODY_*` (body text) | `FOREGROUND` | `MUTED_FOREGROUND` for secondary body |
| `FONT_MONO_VALUE_*` (data cell) | `FOREGROUND` | Domain color (COLD_HIGHLIGHT for cold, or STATUS_* for flagged) |
| `FONT_MONO_SMALL_*` (timestamp, axis label) | `MUTED_FOREGROUND` | — |

**Rationale:** Color + typography combine to signal information hierarchy. A hero numeric in MUTED_FOREGROUND loses prominence. A timestamp in FOREGROUND competes for attention with primary content. Pairing ensures hierarchy.

**Applies to:** any text widget configuration

**Example (good):**

```python
# DESIGN: RULE-TYPO-010
# Hero numeric (FONT_DISPLAY) — FOREGROUND
hero_value = QLabel("3.90")
hero_value.setStyleSheet(f"color: {theme.FOREGROUND};")
# plus FONT_DISPLAY_* font configuration

# Timestamp (FONT_MONO_SMALL) — MUTED_FOREGROUND
timestamp = QLabel("23:08:15")
timestamp.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")

# Warning status badge (FONT_LABEL with TEXT_WARNING)
status_badge = QLabel("ВНИМАНИЕ")
status_badge.setStyleSheet(f"color: {theme.TEXT_WARNING};")
```

**Example (bad):**

```python
# Hero numeric in MUTED — loses prominence
hero_value.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")  # WRONG

# Timestamp in FOREGROUND — competes with primary content
timestamp.setStyleSheet(f"color: {theme.FOREGROUND};")  # WRONG, should be muted

# Body text in ACCENT — makes every word look like a link
body.setStyleSheet(f"color: {theme.TEXT_ACCENT};")  # WRONG
```

**Related rules:** RULE-COLOR-008 (ON_* pairing), `tokens/typography.md` preset roles

---

## Changelog

- 2026-04-17: Initial version. 10 rules covering preset preference, font loading, tnum/liga features, Cyrillic typography, weight minimums, off-scale size protection, uppercase convention, line-height ratios, text color pairing.
