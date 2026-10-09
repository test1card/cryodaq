---
title: Copy Voice
keywords: copy, voice, tone, russian, vocabulary, imperative, descriptive, fsm-states, domain-terms, placeholder
applies_to: operator-facing text across all surfaces — labels, buttons, messages, tooltips
status: canonical
references: rules/content-voice-rules.md, rules/typography-rules.md
last_updated: 2026-04-17
---

# Copy Voice

Rules for operator-facing text. CryoDAQ's UI text is Russian by default (operator working language), with specific vocabulary choices for technical domain. This doc consolidates vocabulary, tone, and register into one reference.

## The register

CryoDAQ operator UI uses **calibrated technical Russian** — somewhere between:
- Not informal / chatty («Давайте запустим эксперимент!» ← too casual)
- Not overly formal / bureaucratic («В данный момент запрашивается инициализация процедуры эксперимента» ← stilted)
- Technical and direct — the way cryogenic lab engineers speak to each other at work

Target: a lab engineer who knows the domain should read a label, button, or message and feel it was written by a colleague who also knows the domain — not by a copywriter who read about the domain.

## Sentence case vs UPPERCASE

### Sentence case (default for operator text)

- Panel titles: «Создать эксперимент», «Диагностика датчиков»
- Buttons: «Сохранить», «Начать эксперимент», «Применить»
- Tab labels: «Общие», «Датчики», «Соединения»
- Breadcrumb crumbs: «Дашборд», «Эксперимент»
- Tooltips: «Закрыть (Esc)», «Аварийное отключение обоих каналов»
- Body text in messages: «Эксперимент будет прерван.»
- Operator log entries: «Давление упало до 1.23e-6»

Only the first word capitalized, proper nouns capitalized. Russian sentence case.

### UPPERCASE (reserved for specific roles)

Only two contexts use UPPERCASE Russian:

1. **Category labels above values** (Tier-3 typography per `patterns/information-hierarchy.md`):
   - «ДАВЛЕНИЕ», «Т МИН», «Т МАКС», «НАГРЕВАТЕЛЬ» (TopWatchBar)
   - «ЭКСПЕРИМЕНТ», «ЖУРНАЛ ОПЕРАТОРА» (card titles)
   - «ДИНАМИКА ТЕМПЕРАТУР» (chart tile title)

2. **Active-state emphasis** (one-off, contextual):
   - Active PhaseStepper label: «ИЗМЕРЕНИЕ» when the experiment is in measurement phase; others sentence-case
   - Emergency destructive button: «АВАР. ОТКЛ.»

Everywhere else is sentence case. UPPERCASE Russian requires letter-spacing 0.05em per RULE-TYPO-005 — cramped without it.

Per RULE-TYPO-008.

## Imperative vs descriptive

### Imperative (action buttons)

Button labels are imperative verbs — telling the system what to do:

- «Сохранить» (not «Сохранение»)
- «Начать эксперимент» (not «Эксперимент начинается»)
- «Применить» (not «Применение параметров»)
- «Прервать» (not «Прерывание»)
- «Удалить» (not «Удаление»)
- «Отключить Keithley» (not «Отключение Keithley»)

### Descriptive (status labels, category headers)

Status / state labels are nouns or adjectives describing the current state:

- «Эксперимент» / «Отладка» (mode badge — noun describing mode)
- «Подключён» / «Нет связи» (connection status — adjective)
- «Охлаждение» / «Захолаживание» (phase name — noun describing phase)
- «Нет активных тревог» (alarm count state — descriptive phrase)

The distinction: **actions are imperatives, states are nouns/adjectives**. Don't mix — «Сохранение» on a button is a state, not an action. RULE-COPY-007.

## Vocabulary lexicon (canonical forms)

When same concept appears in multiple surfaces, use the same word.

| Concept | Canonical | Avoid |
|---|---|---|
| Experiment | эксперимент | опыт (too generic), прогон (colloquial), run (latin) |
| Start | начать / запустить | стартовать (transliteration feel) |
| Stop | остановить | стопить (colloquial) |
| Abort | прервать | отменить (for cancel — different semantic), завершить принудительно (verbose) |
| Save | сохранить | записать (reserve for log entry verb) |
| Record (verb, log) | записать | сохранить (reserve for save) |
| Apply | применить | использовать |
| Cancel | отмена | отменить (verb; use «отмена» as noun in buttons for consistency) |
| Delete | удалить | убрать (too soft), стереть (destructive undertone) |
| Remove | убрать | удалить (reserve for delete) |
| Hide | скрыть | убрать / удалить (imply destruction) |
| Connection | связь / подключение | коннект (transliteration) |
| Connected | подключён | коннектед, активен (ambiguous) |
| Disconnected | нет связи / отключён | оффлайн (too web-app) |
| Fault | авария | ошибка (reserve for software errors) |
| Warning | предупреждение | тревога (reserve for alarms) |
| Alarm | тревога | сигнал / оповещение (reserve for notifications) |
| Error (software) | ошибка | сбой (reserve for hardware failure) |
| Hardware failure | сбой | поломка (colloquial) |
| Channel (sensor) | канал | датчик (reserve for physical sensor) |
| Sensor | датчик | сенсор (transliteration) |
| Current | ток | сила тока (verbose) |
| Voltage | напряжение | вольтаж (colloquial) |
| Power | мощность | сила (ambiguous) |
| Pressure | давление | — |
| Temperature | температура | — |
| Cooldown | захолаживание | охлаждение (reserve for active cooling phase) |
| Cooling (active) | охлаждение | захолаживание (reserve for stabilization) |
| Warmup | отогрев | нагрев (reserve for heater activity) |
| Heater | нагреватель | — |
| Target channel | целевой канал | — |
| Setpoint | установка / задание | уставка (correct but bureaucratic) |
| Measured value | измеренное значение / измерено | — |
| Stale (data) | устарело / не обновляется | просрочено |
| Acknowledge | подтвердить | принять (ambiguous) |

## Subsystem names (keep in Latin)

These are kept in Latin because they're either brand names, library names, or globally-recognized technical identifiers:

- **Keithley** (not «Кейтли»)
- **Engine** (subsystem name; stays in BottomStatusBar as «Engine: подключён»)
- **ZMQ** (library; «ZMQ: 0.5с»)
- **Safety** (subsystem name; «Safety: running»)
- **SQLite**, **pyqtgraph**, **PySide6**, **Qt** (technical stack)
- **TSP**, **SCPI** (instrument control protocols; operator reference only)
- **GPIB**, **USB**, **RS-232** (bus types)
- **SMU**, **DAQ** (technical acronyms; operator familiarity)
- **Smua / smub** → internal ID only; operator UI uses «Канал А» / «Канал B»

Per RULE-COPY-002 exception for subsystem names.

## FSM state display

CryoDAQ safety state names are lowercase identifiers in the codebase, matching the engine internals:

- `safe_off`
- `ready`
- `run_permitted`
- `running`
- `fault_latched`

Display as-is in BottomStatusBar — «Safety: fault_latched». Operators learn these from logs and become fluent; translating them creates lookup friction («Was that "blocked" or "latched" last time?»).

Per CryoDAQ absolute rule (CLAUDE.md) and `cryodaq-primitives/bottom-status-bar.md`.

Note: in destructive action dialogs or operator-facing descriptions, translation is sometimes helpful:

```
«Safety: fault_latched — система в аварийном состоянии, требуется подтверждение»
```

Combined form: code identifier first, explanation after em-dash. Operator gets both the precise state name AND the human explanation.

## Channel IDs (Cyrillic Т)

Always Cyrillic Т (U+0422) in channel identifiers shown to the operator:

- «Т1», «Т11», «Т24» (not Latin «T11»)
- «Т мин», «Т макс» (TopWatchBar labels)

Latin T in channel IDs is a specific violation per RULE-COPY-001.

Per `cryodaq-primitives/sensor-cell.md` invariant 1.

## Error messages

Structure: concrete cause + next step.

**Bad** (content-free):
- «Ошибка»
- «Что-то пошло не так»
- «Внимание!»
- «Недопустимое значение»

**Good** (actionable):
- «Keithley отключён. Проверьте USB-подключение.»
- «Имя эксперимента уже занято. Введите другое.»
- «Температура превышает 400 K. Введите значение от 0 до 400.»
- «Нет связи с engine. Запустите `cryodaq-engine` или дождитесь автоматического подключения.»

Per RULE-COPY-004.

## Empty states

When a list or region has no content, show explicit message, not blank area:

- «Нет активных тревог» (empty alarm list)
- «Нет записей» (empty log / entries list)
- «Нет активного эксперимента» (dashboard empty state)
- «Ожидание первого измерения» (sensor cell with no data yet)
- «Нет данных для выбранного диапазона» (historical chart empty range)

Tone: descriptive present-tense, not «haven't loaded yet» or «loading...» (those imply the system is still working; empty state means the system is idle and there's simply nothing to show).

## Placeholder text

Placeholders in inputs are concrete examples, not instructions:

**Bad:**
- «Введите название эксперимента»
- «Введите значение»
- «Введите заметку»

**Good:**
- «calibration_run_042» (placeholder as example name — shows what shape of value is expected)
- «0.100»
- «Быстрая заметка...»

Instruction-as-placeholder violates RULE-COPY (placeholder-as-label antipattern in `components/input-field.md`).

## Tooltips

Concise. Describe what clicking / hovering does, and if there's a shortcut, include it:

- «Закрыть (Esc)»
- «Аварийное отключение обоих каналов (Ctrl+Shift+X)»
- «3 активные тревоги: 1 авария, 2 предупреждения (Ctrl+A)»
- «Неподвижный опорный канал (вторая ступень, азотная плита)»

Not full sentences; no trailing period for short tooltips; multi-line allowed (newline between main description and extra details).

## Confirmation dialog body

Per `patterns/destructive-actions.md`: concrete consequence + what's preserved + what's lost.

**Bad:**
- «Вы уверены?»
- «Это действие нельзя отменить.»

**Good:**
- «Запись эксперимента 'calibration_run_042' удалится безвозвратно. Архивные данные SQLite останутся.»

## Log entries (system-generated)

System-generated log entries (as distinct from operator-entered ones) use past-tense factual style:

- «Запущен эксперимент calibration_run_042»
- «Перешли в фазу захолаживания»
- «Keithley подключён (smua, smub активны)»
- «Давление достигло 1.23e-06 мбар»
- «Аварийное отключение по сигналу оператора (Ctrl+Shift+X)»

Not first-person («Я запустил...»), not present continuous («Запуск эксперимента...»), not future («Будет запущен...»).

## Operator-entered log entries

User's own text; don't constrain. Place within quotes if referenced elsewhere. Display verbatim.

## Units (Russian abbreviations)

Prefer Russian unit abbreviations over Latin:

- **K** (Kelvin) — Latin K is international SI; «К» Cyrillic also valid. Pick one and use consistently. Recommend Latin K for SI alignment.
- **мбар** (millibar)
- **В** (Volt)
- **А** (Ampere)
- **Вт** (Watt)
- **Ом** (Ohm)
- **мин** (minute)
- **с** (second)
- **Гц** (Hertz)
- **%** (percent)

Always after the number with one space (except %), per `patterns/numeric-formatting.md`.

## Emoji and special glyphs

**No emoji in UI chrome or operator-facing text.** Per RULE-COPY-005 (Phase 0 decision after bell emoji removal).

Unicode symbols in text content (not icons):
- `—` em-dash for missing values (U+2014)
- `±` plus-minus (U+00B1)
- `·` middle-dot for bullet separators («2 мин · 3 сек», U+00B7)
- `→` right arrow in action labels («Открыть →», «Следующая фаза →», U+2192)
- `°` degree (rare, for angles if needed, U+00B0)

Avoid:
- Heavy-weight unicode decorators (🞬, ◆, ▪, ⚡, ✦)
- Emoji bullets, emoji icons
- Mixed Cyrillic/Latin when one or the other would suffice

## Pluralization

Russian has three-way plural (1 / 2-4 / 5+) that breaks English copy tools. Safe approach for counts:

- Use «шт.» (штук) for maximum grammatical safety: «3 шт.», «128 шт.»
- OR use nominal plural + adjective: «3 активные тревоги» / «5 активных тревог»
- OR avoid count display where plural would be awkward (e.g., «Тревог: 3» with separator)

Never use English-style plural hacks: «3 тревоги(ов)», «3 тревога(и)».

## Time references in copy

- «секунд назад» / «с назад» (short form «3 с назад»)
- «минут назад» / «мин назад»
- «сейчас» for <60s
- «вчера», «завтра», «сегодня» — common relative references
- Avoid «недавно», «скоро» — too vague for log context

See `patterns/numeric-formatting.md` for full date/time format reference.

## Rules applied

- **RULE-COPY-001** — Cyrillic Т for channel IDs
- **RULE-COPY-002** — subsystem names in Latin exception
- **RULE-COPY-003** — sentence case default
- **RULE-COPY-004** — actionable error messages
- **RULE-COPY-005** — no emoji
- **RULE-COPY-006** — unit formatting
- **RULE-COPY-007** — imperative verbs for actions
- **RULE-COPY-008** — point decimal conventions (numeric-formatting cross-ref)
- **RULE-TYPO-005** — Cyrillic uppercase letter-spacing
- **RULE-TYPO-008** — UPPERCASE for category labels only

## Common mistakes

1. **Placeholder-as-label.** «Введите название» in placeholder. Use concrete example placeholder («calibration_run_042») + visible QLabel.

2. **Generic error message.** «Ошибка» / «Внимание». Useless. Always concrete cause + next step.

3. **Emoji in UI.** Bell emoji 🔔, warning emoji ⚠️. Replaced with Lucide SVG icons.

4. **English subsystem labels translated to Russian.** «Движок: подключён» — «Engine» is the subsystem name, keep Latin.

5. **Descriptive label on action button.** «Сохранение» on a save button. Use imperative «Сохранить».

6. **Different words for same concept across panels.** «Сохранить» in Keithley panel, «Записать» in Journal — use consistently across surfaces.

7. **UPPERCASE for regular labels.** «НАСТРОЙКИ» as panel title. Use sentence case «Настройки». UPPERCASE reserved per `patterns/information-hierarchy.md`.

8. **Translated FSM states.** «Safety: авария зафиксирована» instead of «Safety: fault_latched». State names are identifiers, not operator copy.

9. **Sentence case on category tile title.** «Давление» instead of «ДАВЛЕНИЕ». Tile category labels are UPPERCASE.

10. **Latin T in channel ID.** «T11» with Latin T. Must be Cyrillic Т11.

11. **«Are you sure?» dialog body.** Content-free. Use concrete consequence description.

12. **Passive-voice log entries.** «Эксперимент был запущен» — use active past: «Запущен эксперимент».

13. **Mixed en-dash / em-dash.** Be consistent — em-dash (—) for missing values and parenthetical, en-dash (–) for ranges and compound. Don't mix.

## Related patterns

- `patterns/numeric-formatting.md` — units and number formats (part of copy voice)
- `patterns/state-visualization.md` — state labels and their visual counterparts
- `patterns/destructive-actions.md` — destructive dialog copy rules
- `patterns/information-hierarchy.md` — tier-appropriate text weight

## Changelog

- 2026-04-17: Initial version. Vocabulary lexicon (canonical forms). Subsystem name Latin exception. FSM state display policy. Error / empty / placeholder / tooltip / log-entry patterns. Pluralization strategies.
