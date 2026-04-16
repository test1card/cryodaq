---
title: Content and Voice Rules
keywords: copy, text, russian, cyrillic, vocabulary, emoji, units, error, message, case, decimal, imperative
applies_to: all operator-facing text
enforcement: strict
priority: high
last_updated: 2026-04-17
status: canonical
---

# Content and Voice Rules

Rules for writing operator-facing text in CryoDAQ UI. Russian-language, cryogenic-lab context, professional operator audience. These rules govern both the words used and the form they take.

Enforce in code and copy review via `# DESIGN: RULE-COPY-XXX` comment marker (for generated copy) or PR review for static strings.

**Rule index:**
- RULE-COPY-001 — Cyrillic Т (U+0422) for temperature channels
- RULE-COPY-002 — Russian technical vocabulary (lab domain terms)
- RULE-COPY-003 — Sentence case for body text
- RULE-COPY-004 — Error message style: actionable, concrete
- RULE-COPY-005 — No emoji in UI chrome
- RULE-COPY-006 — SI units only, written correctly
- RULE-COPY-007 — Imperative for actions, descriptive for states
- RULE-COPY-008 — Russian number decimal convention (space thousands, comma decimal)

---

## RULE-COPY-001: Cyrillic Т (U+0422) for temperature channels

**TL;DR:** Temperature channel labels use Cyrillic `Т` (U+0422), never Latin `T` (U+0054). Applies to T1–T24 channel IDs in user-facing strings.

**Statement:** All temperature channel identifiers displayed to operators MUST use Cyrillic letter `Т` (U+0422). Latin `T` (U+0054) is visually identical but distinct at code-point level and breaks consistency. Applies to:

- Channel labels in SensorCell (`Т1`, `Т2`, ..., `Т24`)
- Channel names in channels.yaml display strings
- Chart legend entries for temperature series
- Alarm messages referencing specific channels
- Operator log entries
- Dialog labels and titles

Code-level channel IDs in backend, database, and configuration keys MAY use Latin `T` for ASCII compatibility — this rule applies only to user-facing strings.

**Rationale:** Russian operator expects Russian text. Mixing Latin `T` with Cyrillic context creates visual jitter. Many fonts render Cyrillic `Т` with different metrics than Latin `T` (especially in monospace at small sizes) — mixing causes subtle layout drift. Code review must catch this because it's easy to type Latin T on Latin keyboard.

**Applies to:** channels.yaml display names, GUI widgets showing channel IDs, alarm text, log messages, dialog text

**Example (good):**

```yaml
# DESIGN: RULE-COPY-001
# channels.yaml — Cyrillic Т
channels:
  Т1:
    name: "Криостат верх"
    visible: true
    group: "криостат"
  Т2:
    name: "Криостат низ"
    visible: true
```

```python
# DESIGN: RULE-COPY-001
# Sensor label
label = QLabel("Т5")  # U+0422 Cyrillic Т
```

```python
# Alarm message
fault_message = f"Канал Т11 превысил лимит: {value:.2f} K"  # Cyrillic Т
```

**Example (bad):**

```python
# Latin T — visually identical, semantically wrong
label = QLabel("T5")  # U+0054 Latin T — WRONG

# Mixed Latin / Cyrillic in same string
message = f"Temperature T1 → Т2 transition"  # inconsistent
```

**Detection:**

```bash
# Find Latin T used as channel prefix in user-facing strings
# (matches "T" followed by digit, inside Russian-text context)
rg -n '\bT[0-9]+' src/cryodaq/gui/ --type py | grep -i "label\|text\|tooltip\|qlabel"
# Manual review — verify each is code-level, not operator-facing

# Scan yaml configs for user-visible Latin T
rg -n '\bT[0-9]+' config/channels.yaml
```

**Migration tool (one-off):**

```python
# Replace Latin T with Cyrillic Т in user-facing YAML strings
import re
from pathlib import Path

def fix_channel_ids(yaml_path: Path):
    text = yaml_path.read_text(encoding='utf-8')
    # Match Latin T followed by digit at start of line / after whitespace
    fixed = re.sub(r'(\s|^)T(\d+):', r'\1Т\2:', text)
    yaml_path.write_text(fixed, encoding='utf-8-sig')  # BOM for Windows
```

**Related rules:** RULE-TYPO-002 (Fira fonts include Cyrillic), RULE-COPY-002 (Russian vocabulary)

---

## RULE-COPY-002: Russian technical vocabulary

**TL;DR:** Use established Russian cryogenic-lab vocabulary. Don't transliterate English tech terms when Russian equivalent exists.

**Statement:** User-facing copy in CryoDAQ MUST use standard Russian technical terms. Transliterations (e.g., `«cooldown»` → «кулдаун») and anglicisms are forbidden when a established Russian term exists.

**Vocabulary table (normative):**

| Concept | Use | Don't use |
|---|---|---|
| Cooldown phase | «Захолаживание» | «Кулдаун», «Cooling» |
| Warmup phase | «Отогрев» | «Вармап», «Warmup» |
| Emergency stop | «Аварийное отключение» or «АВАР. ОТКЛ.» | «Экстренная остановка», «Emergency Stop» |
| Interlock | «Блокировка» | «Интерлок» |
| Sensor | «Датчик» | «Сенсор» |
| Channel | «Канал» | «Ченнел» |
| Readout / reading | «Показание», «Измерение» | «Ридинг» |
| Cryostat | «Криостат» | — (уже русский) |
| Vacuum | «Вакуум» | — |
| Pressure | «Давление» | «Прешер» |
| Temperature | «Температура» | «Температьюр» |
| Experiment | «Эксперимент» | — |
| Phase (of experiment) | «Фаза» | «Стадия» (менее точно в данном домене) |
| Start (action) | «Начать», «Запустить» | «Стартануть» |
| Abort | «Прервать», «Отменить» | «Абортить», «Эбортить» |
| Log (verb) | «Зафиксировать», «Записать» | «Залогировать» |
| Log (noun) | «Журнал» | «Лог» (в UI; в коде/комментах OK) |
| Fault / alarm | «Авария», «Тревога» | «Фолт» |
| Preflight check | «Проверка готовности» | «Префлайт», «Pre-flight» |

**Rationale:** Operators are Russian-speaking professionals. Anglicisms in UI create impression of rushed/unserious software. Established Russian terms are more precise in domain context — «Захолаживание» has a specific physical meaning in cryogenic context that «Кулдаун» does not carry.

**Applies to:** all user-facing copy — buttons, labels, tooltips, dialogs, log messages, alarm text, help text

**Example (good):**

```python
# DESIGN: RULE-COPY-002
button_start = QPushButton("Начать захолаживание")
button_abort = QPushButton("Прервать эксперимент")
label = QLabel("Датчик не откликается")
```

**Example (bad):**

```python
# Anglicisms and transliterations
button = QPushButton("Запустить кулдаун")  # WRONG — «Начать захолаживание»
label = QLabel("Сенсор не откликается")      # WRONG — «Датчик»
alarm = QLabel("Фолт детектед")               # WRONG — «Авария»
```

**Exception:** Technical terms with no established Russian equivalent (e.g., «SCPI», «GPIB», «TSP», «HDF5», «ZMQ») remain in original form. Product names («Keithley», «LakeShore», «Thyracont») are proper nouns, not translated.

**Related rules:** RULE-COPY-001 (Cyrillic Т), RULE-COPY-003 (sentence case)

---

## RULE-COPY-003: Sentence case for body text

**TL;DR:** Russian body prose uses sentence case — only the first letter and proper nouns capitalized. Title Case (English convention of capitalizing every word) is wrong for Russian.

**Statement:** Russian body text — labels, tooltips, dialog content, alert messages, log entries, table headers — MUST use sentence case:
- First letter of sentence: capital
- Rest: lowercase
- Exception: proper nouns (LakeShore, Millimetron), standard abbreviations (UTC, SI)

UPPERCASE is permitted only per RULE-TYPO-008 (category labels, tile titles, destructive buttons). Russian does NOT use Title Case (English pattern «Click Here To Start»).

**Rationale:** Russian typographic convention uses sentence case for body. Title Case is unnatural and marks text as machine-translated or AI-generated. Operators reading Russian expect Russian conventions.

**Applies to:** dialog text, tooltips, table headers, alert bodies, log entries, form labels, help text

**Example (good):**

```python
# DESIGN: RULE-COPY-003
dialog.setText("Завершить эксперимент? Несохранённые данные будут потеряны.")
tooltip = "Открыть журнал оператора (Ctrl+L)"
table_header = "Температура канала"
log_entry = "Датчик Т11 восстановил связь в 14:32"
```

**Example (bad):**

```python
# Title Case — English pattern applied to Russian
dialog.setText("Завершить Эксперимент? Несохранённые Данные Будут Потеряны.")  # WRONG
tooltip = "Открыть Журнал Оператора (Ctrl+L)"                                    # WRONG
table_header = "Температура Канала"                                               # WRONG

# All-lowercase even at sentence start
log_entry = "датчик т11 восстановил связь"  # WRONG — Cyrillic Т missing + no capital
```

**Exception per RULE-TYPO-008:** Category labels, tile titles, destructive action buttons MAY be UPPERCASE («ДАВЛЕНИЕ», «АВАР. ОТКЛ.»). That is a separate convention for labels, not prose.

**Related rules:** RULE-TYPO-008 (uppercase convention), RULE-COPY-002 (vocabulary)

---

## RULE-COPY-004: Error message style — actionable, concrete

**TL;DR:** Error messages state what happened AND what the operator should do. "Ошибка" alone is forbidden — always include context and next step.

**Statement:** Error messages shown to operators MUST contain three components:

1. **What** — concrete description of what failed (not "Ошибка" generic)
2. **Where / why** — specific channel, instrument, or condition (not "произошла")
3. **What next** — actionable guidance (check, retry, contact, ignore)

Length: 1–3 sentences. Too short lacks context; too long gets skipped under stress.

**Rationale:** Operator sees error during experiment — stress level is high. Generic "Ошибка системы" forces them to dig into logs to diagnose. Specific, actionable message lets them respond immediately. Actionability reduces time-to-recovery.

**Applies to:** error dialogs, alarm banners, toast notifications, log entries flagged as errors

**Example (good):**

```python
# DESIGN: RULE-COPY-004
# Specific, actionable
"Канал Т11 не обновлялся более 10 секунд. Проверьте подключение LakeShore #2 (GPIB 14)."

"Keithley 2604B не отвечает на heartbeat. Возможно потеряно USB-соединение. Переподключите кабель и нажмите «Повторить»."

"Запись в SQLite не удалась: диск заполнен. Освободите место в /var/cryodaq/archive или выберите другой каталог."

# Good length — ~1–2 sentences
```

**Example (bad):**

```text
# Generic, non-actionable
"Ошибка."                                 # WRONG — no context, no next step

"Ошибка системы. Попробуйте позже."       # WRONG — no specifics, "позже" useless

"Произошла внутренняя ошибка (код 0x42)." # WRONG — operator cannot act on this

"Сенсор фолт."                             # WRONG — anglicism (RULE-COPY-002), vague

# Too long — one message split across three concatenated strings
"В процессе циклического опроса температурных датчиков канала Т11 контроллером LakeShore 218S "
"#2 через интерфейс GPIB по адресу 14 была обнаружена ситуация отсутствия обновления значения "
"в течение временного интервала, превышающего установленный порог в 10 секунд..."
# WRONG — operator skips this under stress
```

**Template pattern:**

```
[Что] не [состояние/действие].
[Дополнительный контекст одним предложением].
Выполните [действие].
```

**Examples of template fit:**

```
Датчик Т7 потерял связь.
Последнее измерение в 14:32:15, сейчас 14:32:28.
Проверьте подключение LakeShore #1.

Запись архива не выполнена.
Диск /var/cryodaq/archive заполнен на 98%.
Освободите место или выберите другой каталог в Настройках.
```

**Related rules:** RULE-COPY-002 (vocabulary), RULE-COPY-007 (imperative)

---

## RULE-COPY-005: No emoji in UI chrome

**TL;DR:** UI labels, buttons, status indicators, tile titles, log entries — no emoji. Use Lucide SVG icons from the icon bundle instead.

**Statement:** Emoji characters (🔔 📊 ⚠️ ✅ 🚨 etc.) are FORBIDDEN in any operator-facing UI chrome. This includes:

- Button labels
- Tile titles
- Status indicators
- Log entry prefixes
- Alarm banners
- Dialog titles
- Tooltip text

Use vector icons from the Lucide bundle (`alert-triangle`, `bell`, `chart-line`, `check`, `x`) rendered via `load_colored_icon()` — icons styled with design-system colors.

**Rationale:**

1. **Inconsistent rendering.** Emoji glyphs differ between Windows, macOS, Linux (especially between KDE/GNOME). Bell emoji 🔔 looks different on each — design becomes OS-dependent.
2. **Aesthetic mismatch.** Industrial dark UI with colorful cartoon emoji looks unprofessional. Emoji belongs to messaging apps, not cryogenic lab control software.
3. **Accessibility.** Screen readers read emoji as descriptive names that may not fit context (e.g., 🔔 reads as "Bell"). Even without screen reader: icon semantics are stronger when consistent.
4. **Color fidelity.** Emoji have fixed colors; they don't adapt to theme or state. A 🚨 emoji stays red even on fault state, where surrounding UI has deliberate desaturated red.

**Phase 0 instance:** During Phase 0 UI audit, Vladimir explicitly identified emoji bell 🔔 on alarm badge as "выглядит ужасно" — removed in Phase 0 product decision. This rule codifies the principle.

**Applies to:** all user-facing UI text, button labels, dialog content, log display, alarm badges, tile headers

**Example (good):**

```python
# DESIGN: RULE-COPY-005
# Lucide bell icon via helper
alarm_badge = QHBoxLayout()
alarm_badge.setSpacing(theme.SPACE_1)

icon = QLabel()
icon.setPixmap(
    load_colored_icon("bell", color=theme.STATUS_WARNING)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)
)
alarm_badge.addWidget(icon)

label = QLabel("3 тревоги")
alarm_badge.addWidget(label)
```

**Example (bad):**

```python
# Emoji in button label
button = QPushButton("🔔 Уведомления")  # WRONG — emoji in chrome

# Emoji in alarm banner
alarm_text = "🚨 АВАРИЯ: Канал Т11"  # WRONG — emoji prefix

# Emoji in log entry
log_entry = "✅ Эксперимент завершён"  # WRONG — use Lucide 'check' instead
```

**Detection:**

```bash
# Find emoji characters in GUI source files
# Emoji in Unicode generally U+1F000-U+1FFFF range
rg -n '[\x{1F000}-\x{1FFFF}]|[\x{2600}-\x{26FF}]|[\x{2700}-\x{27BF}]' src/cryodaq/gui/
# Also config/channels.yaml, dialog text, anything displayed to operator
```

**Exception:** Chat messages between developers (git commit messages, code comments) MAY contain emoji — that is developer-facing, not operator-facing. Operator-facing text is the strict constraint.

**Related rules:** `tokens/icons.md` (Lucide bundle), RULE-COLOR-005 (icon color inheritance)

---

## RULE-COPY-006: SI units only, written correctly

**TL;DR:** Display values in SI units with correct Russian spacing and symbols. `3.90 K` (space between value and unit), `1.23 × 10⁻⁶ мбар`, `42 Вт`.

**Statement:** All physical quantity displays MUST follow SI unit conventions:

1. **Space between value and unit.** `3.90 K`, not `3.90K`. (Thin space NBSP `\u202F` or regular space; use regular space for ASCII fallback.)
2. **Standard symbols.** Temperature: `K` (Kelvin). Pressure: `мбар` (millibar) or `Па` (Pascal). Power: `Вт` (Watt). Current: `А` (Ampere). Voltage: `В` (Volt). Resistance: `Ом` (Ohm).
3. **Scientific notation for small/large values.** Pressure in vacuum ranges uses `1.23 × 10⁻⁶ мбар` or `1.23e-6 мбар`. Don't write `0.00000123 мбар`.
4. **No Imperial units.** No Fahrenheit, no psi, no inches. CryoDAQ is metric-only.
5. **Units in Russian where established.** `мбар` not `mbar`, `Вт` not `W`, `Ом` not `Ohm`. Kelvin stays `K` (international convention for temperature).

**Rationale:** Russian scientific convention. Metric SI is the standard; deviating confuses operators and makes the UI look amateurish. Proper spacing makes values easier to read and parse.

**Applies to:** SensorCell displays, tile values, axis labels, log entries, dialog content, alarm messages

**Example (good):**

```python
# DESIGN: RULE-COPY-006
# Temperature — space between value and unit, K international
temp_display = f"{value:.2f} K"  # "3.90 K"

# Pressure — scientific notation, Russian unit
pressure_display = f"{value:.2e} мбар"  # "1.23e-06 мбар"

# Power — Russian symbol
power_display = f"{value:.3f} Вт"  # "0.125 Вт"

# Voltage / Current
voltage_display = f"{value:.3f} В"  # "12.500 В"
current_display = f"{value:.3f} А"  # "0.250 А"
```

**Example (bad):**

```python
# No space between value and unit
temp_display = f"{value:.2f}K"  # WRONG — "3.90K" hard to parse

# English unit symbols
pressure_display = f"{value:.2e} mbar"  # WRONG — use "мбар"
power_display = f"{value:.3f} W"         # WRONG — use "Вт"

# Imperial units
temp_display = f"{fahrenheit:.1f} °F"  # WRONG — SI only, always K

# Not scientific notation for small values
pressure_display = f"{value:.10f} мбар"  # WRONG — "0.0000012345 мбар" unreadable
```

**Formatting helpers (proposed):**

```python
# In cryodaq.gui.formatting
def format_temperature(value_K: float) -> str:
    """3.90 K — always 2 decimals, Kelvin."""
    return f"{value_K:.2f} K"

def format_pressure(value_mbar: float) -> str:
    """1.23e-06 мбар — scientific, 2 significant figures, Russian unit."""
    return f"{value_mbar:.2e} мбар"

def format_power(value_W: float) -> str:
    """0.125 Вт — 3 decimals, Russian unit."""
    return f"{value_W:.3f} Вт"
```

**Related rules:** RULE-DATA-005 (sensor reading format), RULE-DATA-006 (units always displayed), RULE-COPY-008 (decimal convention)

---

## RULE-COPY-007: Imperative for actions, descriptive for states

**TL;DR:** Button labels and action prompts use imperative verbs («Начать», «Сохранить»). State descriptions use indicative («Идёт захолаживание», «Эксперимент завершён»). Don't mix.

**Statement:** Text form follows function:

- **Actions the operator takes** (buttons, commands, confirmations) — imperative verb. «Начать», «Прервать», «Сохранить», «Применить», «Отмена».
- **State descriptions** (what the system is doing, has done, will do) — indicative. «Идёт захолаживание», «Эксперимент завершён», «Датчик не откликается».
- **Questions to operator** (confirmation dialogs) — interrogative. «Завершить эксперимент?», «Сохранить изменения?».

Don't write "Захолаживание" on a button that starts cooldown — that's descriptive, not imperative. Write "Начать захолаживание."

**Rationale:** Grammar signals intent. Imperative says "click me, I'll do this." Descriptive says "this is happening right now." Button with descriptive label creates ambiguity — is this a state indicator or an action?

**Applies to:** button labels, dialog prompts, status banners, log entries, alarm messages

**Example (good):**

```python
# DESIGN: RULE-COPY-007
# Buttons — imperative
QPushButton("Начать эксперимент")      # action
QPushButton("Прервать")                 # action
QPushButton("Сохранить изменения")      # action
QPushButton("Отменить")                 # action
QPushButton("Применить")                # action

# Status labels — descriptive
QLabel("Идёт захолаживание")            # current state
QLabel("Эксперимент завершён")          # past state
QLabel("Датчик Т7 не откликается")      # current state

# Dialog — interrogative
dialog.setText("Завершить эксперимент досрочно?")
```

**Example (bad):**

```python
# Button with descriptive label — unclear if action or state
QPushButton("Захолаживание")            # WRONG — «Начать захолаживание»

# State with imperative — confuses "happening" vs "do this"
QLabel("Начните захолаживание")         # WRONG if this is a state indicator
# Should be either:
#   «Идёт захолаживание» (if state)
#   button «Начать захолаживание» (if action)

# Dialog with statement instead of question
dialog.setText("Завершение эксперимента.")  # WRONG — ambiguous
# Should be interrogative: «Завершить эксперимент?»
```

**Related rules:** RULE-COPY-004 (error actionability), `patterns/copy-voice.md`

---

## RULE-COPY-008: Russian number decimal convention

**TL;DR:** Russian convention uses comma as decimal separator («3,90 K») and space as thousands separator («1 234 567»). BUT in scientific/technical UI, point decimal («3.90 K») is acceptable and often preferred.

**Statement:** CryoDAQ uses **point decimal** («3.90 K») in UI displays for technical/scientific consistency with plot axes, log output, and Python literal values. This is a deliberate deviation from pure Russian convention where comma decimal («3,90 K») is standard in prose.

**Justification for point decimal:**
- Plot axis labels in pyqtgraph render with point decimal by default
- Log file output uses point decimal for machine parseability
- SQLite / Parquet stored values use point decimal
- Scientific notation `1.23e-06` uses point — mixing with comma elsewhere creates inconsistency

**Thousands separator:** Use space (Russian convention) or nothing. NEVER comma (English convention).

- `1 234 567` (Russian thousands) ✓
- `1234567` (no separator) ✓
- `1,234,567` (English thousands) ✗ — in Russian reads as `1.234.567`

**Rationale:** Tradeoff between two consistency domains. Pure Russian = comma decimal everywhere, but then plots render differently and operators see inconsistency between "UI readout 3,90 K" and "plot axis 3.90 K." Tech audiences are trained to read point decimal. Chose technical consistency over linguistic purity.

**Applies to:** all numeric displays, axis labels, table cells, log output

**Example (good):**

```python
# DESIGN: RULE-COPY-008
# Point decimal, space thousands
temp_display = f"{value:.2f} K"            # "3.90 K"
count_display = f"{count:,}".replace(",", " ")  # "1 234 567 записей"
pressure = f"{value:.2e} мбар"              # "1.23e-06 мбар"
```

**Example (bad):**

```python
# Comma decimal — inconsistent with plot axes / logs
temp_display = f"{value:.2f}".replace(".", ",") + " K"  # "3,90 K" — WRONG

# English thousands
count_display = f"{count:,} записей"  # "1,234,567 записей" — reads as 1.234.567 in Russian

# Mixed
display = f"{value:.2f} K, всего {count:,}"  # WRONG — mixes conventions
```

**Exception:** Prose text outside numeric displays (tooltips, dialog bodies, log descriptions) MAY use comma decimal when embedded in sentences, per Russian convention:

```python
# Prose context — comma decimal acceptable
tooltip = "Температура повысилась на 0,5 K за минуту"  # acceptable in prose
# But widget numeric display itself still uses point:
QLabel("0.5 K")  # UI readout, point decimal
```

**Related rules:** RULE-COPY-006 (SI units), RULE-DATA-004 (fixed precision)

---

## Changelog

- 2026-04-17: Initial version. 8 rules covering Cyrillic Т, Russian vocabulary, sentence case, error style, emoji prohibition, SI units, imperative/descriptive, decimal convention. RULE-COPY-004 fills the previously-reserved gap.
- 2026-04-17 (v1.0.1): Verified canonical operator-facing pressure unit is `мбар` per RULE-COPY-006 (FR-016). No content change here — this file already states the canonical unit; downstream files (typography.md, chart-tokens.md, top-watch-bar.md, data-display-rules.md) updated to match.
