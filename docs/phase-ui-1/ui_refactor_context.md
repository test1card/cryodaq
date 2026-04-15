# CryoDAQ UI Refactor — Context Document

**Status:** Living reference. Update as new findings emerge from operator feedback or implementation surprises.

**Audience:** Architect (Claude in any future chat session) + Vladimir.

**Purpose:** Single source of truth для понимания **зачем** мы рефакторим UI.
Каждое design decision должно ссылаться на pain point из §2 (что решает) или
constraint из §3 (что сохраняет). Никаких abstract "best practices" без anchor.

---

## §1 — Legacy Inventory

Технический audit всех 10 legacy GUI tabs. Делается отдельным CC read-only block
(spec приложен ниже). Result — markdown reports per tab, аналогично
`legacy_experiment_workspace_inventory.md` (893 строки legacy → 14KB inventory).

### Status

| Tab | Inventory status | Report path |
|-----|------------------|-------------|
| Эксперимент (ExperimentWorkspace) | ✓ DONE | `/tmp/legacy_experiment_workspace_inventory.md` |
| Обзор (Overview) | ✓ DONE | `docs/legacy-inventory/overview.md` |
| Источник мощности (Keithley) | ✓ DONE | `docs/legacy-inventory/keithley.md` |
| Аналитика | ✓ DONE | `docs/legacy-inventory/analytics.md` |
| Теплопроводность (Conductivity) | ✓ DONE | `docs/legacy-inventory/conductivity.md` |
| Алармы | ✓ DONE | `docs/legacy-inventory/alarms.md` |
| Служебный лог | ✓ DONE | `docs/legacy-inventory/operator_log.md` |
| Архив | ✓ DONE | `docs/legacy-inventory/archive.md` |
| Калибровка | ✓ DONE | `docs/legacy-inventory/calibration.md` |
| Приборы | ✓ DONE | `docs/legacy-inventory/instruments.md` |
| Датчики (диагностика) | ✓ DONE | `docs/legacy-inventory/sensor_diag.md` |

Spec для Legacy Inventory audit — см. отдельный Block в roadmap (Phase 0).

---

## §2 — Why We Refactored (Pain Points)

Validated by Vladimir. Все pain points действительно ощущались операторами в v1.

### P1 — Constant tab-switching to understand state

В v1 оператор должен был **постоянно переключаться между вкладками** чтобы
понять что происходит:
- Чтобы посмотреть температуры → вкладка Обзор
- Чтобы проверить нет ли алармов → вкладка Алармы
- Чтобы понять в какой фазе эксперимент → вкладка Эксперимент
- Чтобы посмотреть давление в течение часа → вкладка Аналитика

10 вкладок одинакового веса, никакой иерархии. Cognitive load высокая.

**Что должен решать рефакторинг:** ambient awareness без переключений. Главное
видно постоянно, детали по drill-down.

### P2 — Alarms could be missed

Алармы жили в **отдельной вкладке** «Алармы». Если оператор был на любой другой
вкладке — он мог не заметить что сработал alarm. Особенно при week-long
experiments когда оператор смотрит UI 5-10 секунд раз в час.

**Что должен решать рефакторинг:** alarm visibility вне зависимости от того
куда оператор смотрит. Alarm как persistent badge в shell, не как content
зависящий от tab.

### P3 — Shift handovers были устные

При смене смены коллеге надо было **словесно рассказывать** что было сделано
за смену, в какой фазе эксперимент, что замечено, какие отклонения. Никакого
formalized handover surface не было.

**Что должен решать рефакторинг:** shift handoff context built into UI. Что
произошло за смену видимо новому оператору без устного briefing.

### P4 — Repetitive form filling for new experiments

При создании нового эксперимента оператор каждый раз заполнял **одни и те же
поля заново**: оператор, sample, cryostat. Не было autocomplete history.

**Что должен решать рефакторинг:** muscle-memory friction reduction. Form
автозаполняется last-used values, autocomplete from history, template suggests
name. (B.8.0.2 уже реализовал это для experiment creation.)

### P5 — Phase elapsed time invisible

Не было видно **сколько времени прошло в текущей фазе**. Только timestamp
начала фазы в лучшем случае. Оператор должен был считать в уме.

**Что должен решать рефакторинг:** elapsed time везде где это relevant —
текущая фаза, total experiment duration, time since last reading. Готовые
формaty (`4ч 36мин`), не raw timestamps.

### P6 — Plots in different places, can't compare

Графики температуры были на одной вкладке (Обзор), графики давления на другой
(Аналитика), thermal conductivity на третьей. Нельзя было **сравнить
коррелированные параметры** without manually opening multiple tabs.

**Что должен решать рефакторинг:** correlated data co-located. Pressure trend
рядом с T trend на dashboard (B.5.x уже сделал). Когда нужен deep zoom —
analytics overlay содержит все relevant chart types.

### P7 — No notifications when operator away

Оператор уходит на обед / в курилку / на ночь — **никаких notifications**
о критических событиях. Возвращается через 2 часа, эксперимент уже сломался.

**Что должен решать рефакторинг:** out-of-band notifications для critical
events. Telegram bot integration уже есть (chat ID 770134831), но нужно убедиться
что используется для всех пороговых alarms (P3, fault transitions, source off).
Возможно расширить на phase transitions completed для shift planning.

---

## §3 — What To Preserve (Don't Break)

Validated by Vladimir. Все эти фичи реально используются операторами регулярно.
Удаление = саботаж workflow.

### Preserve list

| # | Feature | Where currently | Notes |
|---|---------|-----------------|-------|
| K1 | **Service log с хронологией всех событий** | Служебный лог tab | Операторы читают для понимания что было до них. Должен остаться доступен. Filter by experiment — один из вариантов. |
| K2 | **Архив завершённых экспериментов** | Архив tab | Чтение прошлых, экспорт, анализ. Должен остаться полнофункциональным. Не minify до toy version. |
| K3 | **Calibration workflow (CalibrationFitter pipeline)** | Калибровка tab | Setup → Acquisition → Results, .330/.340/JSON export, runtime apply per-channel policy. Сложный workflow, нельзя ломать. |
| K4 | **Прямой контроль Keithley с custom commands** | Источник мощности tab | Operators sometimes нужно отправить custom TSP/SCPI команду для отладки. Не убирать в advanced-mode. |
| K5 | **Plot history с zoom/pan** | Обзор + Аналитика tabs | pyqtgraph zoom/pan/legend toggle/data inspection. Operators анализируют trends на месте. |
| K6 | **Export CSV/HDF5/Excel** | File menu | Экспорт для дальнейшей обработки в внешних tools. Все 3 формата используются (CSV для Excel, HDF5 для Python analysis, Excel для отчётов). |
| K7 | **Phase Detector plugin** | Background analytics | Auto-detection фаз эксперимента. Используется для phase progression suggestions. Не выпиливать. |

### Implications для design

- K1 → ХРОНИКА overlay column (B.8.0.2) good first step, но **standalone Operator Log overlay** должен остаться (filter, search, export).
- K2 → Archive overlay должен быть **full-functional**, не reduced. Browse, filter, view experiment details, export.
- K3 → Calibration overlay = three-mode workflow (Setup/Acquisition/Results) preserved, не упрощать в "one-click calibrate".
- K4 → Keithley overlay должен expose custom command field, possibly behind small "Advanced" toggle.
- K5 → Все pyqtgraph plots сохраняют zoom/pan/legend behavior. Не делать static images.
- K6 → File menu или explicit export buttons на Archive overlay. Все 3 формата.
- K7 → Phase Detector keeps running, но output теперь **highlights в overlay** (suggested next phase = blue highlight on Next button).

---

## §4 — Cross-cutting Design Principles

Derived from §2 + §3 above. Apply to every overlay/widget:

1. **Ambient first, drill-down second.** Dashboard = peripheral awareness. Overlay = focused work. Don't put detail-work content on dashboard, don't force ambient awareness through overlay.

2. **Persistent global indicators.** Alarms, connection status, current phase, experiment name — visible regardless of which overlay is open. TopWatchBar + BottomStatusBar (already done) carry this.

3. **Reduce repetition.** Autocomplete from history, name suggestion, last-used defaults. (B.8.0.2 уже сделал это для experiment creation. Apply same pattern везде где есть form input.)

4. **Time везде где relevant.** Elapsed times pre-formatted (`4ч 36мин`), not raw timestamps. Phase durations on past pills (B.8.0.2 уже сделал это).

5. **Co-locate correlated data.** Pressure + temperature in one view when both relevant. Card + Хроника side-by-side (B.8.0.2 pattern). Don't separate causation pairs.

6. **Out-of-band notifications для critical.** Telegram for fault transitions, source off events, alarm thresholds crossed. Operator может быть away from screen.

7. **Preserve power-user workflows.** Custom commands, advanced settings, full export options остаются accessible. Не hiding behind "simplified" UI.

---

## §5 — Lifecycle of this document

- **Update §1** when each Legacy Inventory block completes (CC fills in tab inventories one-by-one).
- **Update §2** if Vladimir или operators identify new pain points через usage feedback.
- **Update §3** if operator complains "you removed X which I used daily" — capture immediately.
- **Update §4** if a new overarching principle emerges from multiple block iterations.

This document is **prerequisite reading** for any new chat session working on Phase UI-1 v2. Architect should open this doc before designing any block.
