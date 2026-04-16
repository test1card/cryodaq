---
title: Numeric Formatting
keywords: numbers, formatting, precision, units, kelvin, pressure, voltage, current, scientific, tabular-nums, russian-decimal
applies_to: how numeric values are formatted for display across CryoDAQ
status: canonical
references: rules/data-display-rules.md, rules/typography-rules.md, rules/content-voice-rules.md
last_updated: 2026-04-17
---

# Numeric Formatting

Rules for formatting numeric values — temperatures, pressures, voltages, currents, elapsed times, counts — for consistent display across all surfaces.

## The operator's expectation

A trained cryogenic-lab operator reads values fluently when they follow expected conventions. Break convention — swap Kelvin for Celsius, use comma decimals where points are standard, put the unit before the number — and reading speed drops, errors creep in. This doc makes the conventions explicit so every widget renders numbers the same way.

## Per-quantity format reference

| Quantity | Format | Unit | Example |
|---|---|---|---|
| **Temperature** | `{:.2f}` | K (Cyrillic К also valid, prefer Latin K for SI) | `4.21 K`, `77.30 K`, `350.00 K` |
| **Pressure** | `{:.2e}` | мбар | `1.23e-06 мбар`, `9.87e-03 мбар` |
| **Voltage** | `{:.3f}` | В | `12.345 В`, `0.001 В` |
| **Current** | `{:.3f}` | А | `0.050 А`, `1.000 А` |
| **Power** | `{:.3f}` | Вт | `0.125 Вт`, `1.234 Вт` |
| **Resistance** | `{:.2f}` | Ом | `51.20 Ом` |
| **Time (elapsed)** | `{:d}` min, `{:d}` s | мин, с | `47 мин`, `3.5 с` |
| **Heating rate** | `{:.2f}` | K/мин | `1.25 K/мин` |
| **Cooling rate** | `{:.2f}` | K/мин | `-2.50 K/мин` |
| **Heartbeat interval** | `{:.1f}` | с | `0.5 с`, `12.3 с` |
| **Count (alarms, entries)** | `{:d}` | — | `3`, `128` |
| **Percentage** | `{:.0f}` | % | `42%`, `100%` |
| **Date (short)** | `DD.MM` | — | `17.04` |
| **Date (full)** | `DD.MM.YYYY` | — | `17.04.2026` |
| **Time of day** | `HH:MM:SS` | UTC±N | `14:32:15 UTC+3` |

Precision is ALWAYS fixed per quantity. A temperature is always 2 decimals — not «4.2» one moment and «4.21» the next. RULE-DATA-004.

## Unit placement

**Unit always AFTER the number with one space separator.**

```
4.21 K        ← correct
4.21K         ← wrong (missing space; RULE-COPY-006)
K 4.21        ← wrong (unit before)
4.21·K        ← wrong (special separator instead of space)
4.21 Kelvin   ← wrong (symbol, not word)
```

Exception: percentage sign attaches directly (no space): `42%`, not `42 %`.

## Decimal separator

**Display: point (`.`) decimal, SPACE thousands separator.**

```
4.21            ← point decimal
1 234.56        ← space thousands + point decimal
0.001           ← leading zero present
```

Not Russian comma-decimal. Not comma thousands separator. Rationale: technical consistency with SI notation + `float` parsing + international scientific literature. Documented in RULE-COPY-008.

**Input: accept both** `.` and `,` — operator may type `0,125` naturally; normalize to `0.125` before storage/display.

## Scientific notation (for pressure)

Pressure values span ~10 orders of magnitude in a cryogenic system (atmospheric 1e3 мбар → ultra-high vacuum 1e-10 мбар). Always scientific notation with 2 decimals in the mantissa:

```
1.23e-06 мбар   ← canonical form
9.87e-03 мбар
1.00e+00 мбар
1.23e+03 мбар   ← atmospheric
```

**Format specifier:** `{:.2e}` produces exactly this. Uppercase E is also valid (`1.23E-06`) but prefer lowercase for visual density.

Never linear: `0.00000123 мбар` is unreadable at-a-glance; count of zeros hides magnitude.

Never engineering-notation (`1.23e-6`, mantissa times 10^-6): same magnitude but visually less consistent with how the rest of the world writes scientific.

Per RULE-DATA-005 and RULE-DATA-008 (log-scale for pressure plots).

## Zero values

Zeros always display with their precision:

```
0.00 K         ← not "0 K" or "0.0 K"
0.000 В        ← not "0 В"
0.00e+00 мбар  ← not "0 мбар"
```

Rationale: same-width rendering via tabular numbers prevents visual jitter when the value transitions from 0.00 → 0.25 → 0.50.

## Negative values

Minus sign directly before digit, no space:

```
-2.50 K          ← correct
- 2.50 K         ← wrong (space after minus)
–2.50 K          ← wrong (en-dash; RULE-TYPO-like)
−2.50 K          ← wrong (Unicode minus; inconsistent rendering)
```

Use standard hyphen-minus (ASCII 0x2D). Font metrics for tabular numbers include matching width for the minus sign.

## Large magnitudes

For values > 999 (common: elapsed seconds, counts, sample indices):

```
1 234            ← space thousands
12 345
1 234 567
```

Not `1,234` (comma — conflicts with comma-decimal in input). Not `1234` (unreadable beyond 4 digits).

Python format: `f"{value:,}".replace(",", " ")` works. Or use a helper `format_thousands(v)`.

## Rounding and precision

- **Round to precision, then format.** `f"{4.216:.2f}"` = `"4.22"` — standard Python behavior.
- **Never truncate.** `f"{4.219:.2f}"` must be `"4.22"`, not `"4.21"`.
- **Don't use banker's rounding for user-facing display** (Python's default is round-half-to-even which is fine for most values; "half" cases are rare with two decimals on physical measurements).

## Leading zeros

Always present for values < 1:

```
0.125        ← correct
.125         ← wrong (missing leading zero)
```

Exception: pressure in scientific notation, where leading zero in mantissa IS the point (`1.23e-06`, not `0.123e-05`).

## Tabular-numbers requirement

Every numeric readout uses a font with tabular-nums enabled:

```python
font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
font.setFeature("tnum", 1)  # DESIGN: RULE-TYPO-003
font.setFeature("liga", 0)  # DESIGN: RULE-TYPO-004 (ligatures OFF)
```

Tabular-nums make digits all same width, so `777` and `111` occupy the same pixel count. Without this, values jitter horizontally as they change — breaks RULE-DATA-003 (no jitter).

Applies to:
- All SensorCell values
- All TopWatchBar vitals
- All chart axis labels
- All elapsed counters
- Timestamps
- Count badges
- Any numeric input

## Date/time formats

**Absolute time of day** (primary clock display, log timestamps):

```
14:32:15 UTC+3      ← with explicit offset
14:32:15             ← when TZ is established elsewhere (e.g., session header)
```

Always 24-hour clock. Never AM/PM. Russian lab context uses 24h exclusively.

**Relative time** (log entries, staleness hints):

```
сейчас              ← <60s ago
5 мин назад          ← within current hour
2 ч назад            ← within current day
вчера               ← 1 calendar day ago
3 дн назад           ← within week
17.04                ← older than week, in current year
17.04.2026          ← older than 1 year (rare)
```

Rationale: absolute time for "when exactly", relative time for "how long ago" — operator glancing at recent logs wants "ago", reviewing historical archive wants absolute.

**Date format:** DD.MM.YYYY (Russian convention). Not YYYY-MM-DD (ISO) in operator text, because most operators read DD.MM faster. Internal timestamps and file names still use ISO.

**Mix allowed when useful:** «Калибровка 14 дн назад (03.04.2026)» — relative anchor + absolute for precision.

## Ranges

Two values with a dash, spaces around the dash:

```
Т1 – Т14            ← using en-dash (U+2013) for range
4.21 – 77.30 K      ← numeric range
-20 – +400 K        ← with negative low bound
```

Not `Т1-Т14` (hyphen, tight). Not `Т1 to Т14` (English «to»).

Exception: timestamp spans may use compressed format `14:32:15 – 14:45:00` or `14:32 – 14:45`.

## Uncertainty / error bars

When uncertainty is displayed:

```
4.21 ± 0.02 K       ← with explicit uncertainty
4.21 ± 0.5% K       ← relative uncertainty
```

Symbol `±` (U+00B1), spaces around. Only display when measurement has known uncertainty; don't invent a «±0.0» for precision-only values.

## Missing data

Single em-dash `—` (U+2014):

```
— K                ← missing temperature
—                  ← missing generic value
```

Not `N/A`, not `нет данных` (too long for inline), not `?`, not empty string.

Tooltip on the `—` widget explains why: «Ожидание первого измерения» or «Канал отключён».

## Vernier-style displays (e.g., setpoint vs measured)

When showing setpoint AND measured together:

```
Установка: 0.100 А
Измерено:  0.099 А
```

Align on decimal point via monospace. Use separate lines or a 2-column grid (label + value). Don't squish into one line.

## Count formatting edge cases

- **Zero count:** display differently based on context. «Нет активных тревог» (empty state text), not «0 тревог».
- **Approximate count:** `~100` if estimation; only used in historical / archive contexts, not live data.
- **Plural agreement:** Russian has complex plural rules (1 аварий? 2 аварии? 5 аварий?). Default: use neutral forms in count labels — «3 активные тревоги» (с «ы» endings for 2-4), «5 активных тревог» (for 5-20). Simplest universal form: «3 шт.» / «128 шт.» (fewer plural issues). When in doubt, use the «шт.» neutralizer.

## Computed units inline

When combining two quantities into a rate:

```
2.50 K/мин          ← temperature rate
0.125 Вт            ← power (derived, V·A)
1.23 л/с            ← flow rate (rare)
```

Solidus `/` between numerator and denominator; no spaces. Unit always in Russian where applicable.

## Rules applied

- **RULE-DATA-003** — no jitter (tabular-nums, fixed precision)
- **RULE-DATA-004** — fixed precision per quantity
- **RULE-DATA-005** — pressure scientific notation
- **RULE-DATA-006** — unit required
- **RULE-COPY-006** — unit format conventions
- **RULE-COPY-008** — point decimal, space thousands
- **RULE-TYPO-003** — tabular-nums feature
- **RULE-TYPO-004** — ligatures OFF in mono

## Common mistakes

1. **Variable precision.** `4.2` / `4.21` / `4.213`. Pick one per quantity and stick with it. RULE-DATA-004.

2. **Comma decimal in display.** `4,21 K`. Display is point; input accepts both. RULE-COPY-008.

3. **Missing unit.** `4.21` with no unit. Ambiguous (K? °C?). Always include unit. RULE-DATA-006.

4. **Unit attached without space.** `4.21K`. Always space. RULE-COPY-006.

5. **Linear pressure.** `0.00000123 мбар`. Use scientific. RULE-DATA-005.

6. **Auto-rounding to "nicer" value.** Truncating `4.216` to `4.2` because "looks cleaner". Round, don't truncate.

7. **Non-tabular font on numbers.** FONT_BODY (proportional) on a live counter. Digits jitter. Use FONT_MONO + tnum. RULE-TYPO-003.

8. **Celsius instead of Kelvin.** Violates SI convention; operator reads Kelvin natively. Always Kelvin.

9. **Missing thousands separator on 4+ digit numbers.** `1234567`. Use space: `1 234 567`. RULE-COPY-008.

10. **Inconsistent missing-value representation.** `—` in one widget, `N/A` in another, `—` in third. Pick `—` everywhere.

11. **AM/PM time.** `2:32:15 PM`. Russian convention is 24h. Always `14:32:15`.

12. **Leading zero missing.** `.125`. Always `0.125`. Especially critical when negative: `.125` and `-.125` look visually similar — always use `0.125` / `-0.125`.

13. **ISO date in operator UI.** `2026-04-17` in a log timestamp. Use `17.04.2026` (Russian DD.MM.YYYY). ISO reserved for internal file names.

## Related patterns

- `patterns/real-time-data.md` — when / how often numeric values update
- `patterns/state-visualization.md` — how numeric values are colored by state
- `patterns/copy-voice.md` — units as part of operator vocabulary

## Changelog

- 2026-04-17: Initial version. Per-quantity format reference. Unit placement. Decimal separator rules (point display, both-accepted input). Scientific pressure. Tabular-nums requirement. Date/time formats including relative/absolute mix.
