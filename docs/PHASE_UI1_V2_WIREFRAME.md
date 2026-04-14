# CryoDAQ — Phase UI-1 v2 Wireframe & Architecture

> **Purpose:** Архитектурный документ нового UI основанный на реальных user
> flows из интервью с Vladimir, не на теоретической design system. Заменяет
> провалившийся подход Phase UI-1 v1 (token swap без layout changes).
>
> **Status:** First cut wireframe v0.1, awaiting Vladimir review.
>
> **Source of truth для design tokens:** `docs/DESIGN_SYSTEM.md` v0.3
> остаётся в силе. Этот документ применяет tokens к **новой layout
> архитектуре** на конкретных экранах.
>
> **Target hardware:** FHD 1920×1080 single monitor (минимум) и 1920×1200
> (комфортно). Fullscreen mode только. Один монитор.
>
> **Operator model:** 5 человек, без ролей и прав, все могут всё.

---

## Оглавление

1. [Архитектурный сдвиг](#1-архитектурный-сдвиг)
2. [Layout zones FHD 1920×1080](#2-layout-zones-fhd-1920-1080)
3. [Top Watch Bar — спецификация](#3-top-watch-bar)
4. [Tool Rail — спецификация](#4-tool-rail)
5. [Bottom Status Bar](#5-bottom-status-bar)
6. [Dashboard view (default)](#6-dashboard-view-default)
7. [Phase-aware top widget — 7 режимов](#7-phase-aware-top-widget)
8. [Detail panels (overlay full takeover)](#8-detail-panels)
9. [Click budget для частых действий](#9-click-budget)
10. [Component inventory](#10-component-inventory)
11. [Что выкидывается](#11-что-выкидывается)
12. [Phase UI-1 v2 plan](#12-phase-ui-1-v2-plan)

---

## 1. Архитектурный сдвиг

### Старая модель (Phase UI-1 v1, провалилась)
**10 равноправных табов**, между которыми оператор переключается. Каждый
таб — отдельный экран. Дашборд (Обзор) — один из 10. Token swap без
layout changes сохранил эту структуру.

**Почему провалилась:** оператор работает в режиме «фоновый мониторинг + редкие
drill-downs». Tab-based навигация заставляет постоянно переключаться чтобы
проверить «как давление пока я в Эксперименте». Главный экран не оптимизирован
под основную задачу — следить за прогрессом длинного эксперимента.

### Новая модель
**Дашборд = постоянный главный экран.** Tool rail слева — узкая полоса с
иконками для drill-down operations. Detail panels открываются как
**full-screen overlay** (не side-by-side) поверх дашборда. Watch bar
сверху всегда содержит критическую информацию о состоянии — оператор не
теряет ambient awareness даже когда работает в overlay.

**Принципы:**
1. **Ambient awareness on default** — открыл программу, видишь всё важное
   за 1 секунду, без переключений
2. **Drill-down on demand** — детальные операции (Источник мощности,
   Аналитика, и т.д.) живут в overlay panels, не в равноправных табах
3. **Phase-aware дашборд** — главный widget наверху меняет содержимое в
   зависимости от текущей фазы эксперимента (preparation / vacuum /
   cooldown / measurement / warmup / teardown / no experiment)
4. **Persistent watch** — top bar содержит критическую информацию (engine,
   experiment, channel summary, alarms) **на любом экране**, в overlay
   panels тоже
5. **Configurable density** — text labels в tool rail можно
   включить/выключить, sensor grid поджимается под видимые каналы
6. **No hero readouts** — все 24 канала равны, никаких "T11/T12 как
   главные". Reference points меняются от эксперимента к эксперименту.

---

## 2. Layout zones FHD 1920×1080

```
┌─────────────────────────────────────────────────────────────────────┐  ← y=0
│                    TOP WATCH BAR     ~ 48px height                  │
│   always visible, на любом view                                     │
├──┬──────────────────────────────────────────────────────────────────┤  ← y=48
│  │                                                                  │
│ T│                                                                  │
│ O│                                                                  │
│ O│                                                                  │
│ L│      MAIN AREA — height ~1008px                                  │
│  │                                                                  │
│ R│      содержит ОДНО из:                                           │
│ A│      • Dashboard (default)                                       │
│ I│      • Detail panel overlay (full takeover)                      │
│ L│                                                                  │
│  │                                                                  │
│ ~│                                                                  │
│50│                                                                  │
│px│                                                                  │
│  │                                                                  │
│  │                                                                  │
│  │                                                                  │
│  │                                                                  │
├──┴──────────────────────────────────────────────────────────────────┤  ← y=1056
│              BOTTOM STATUS BAR    ~ 24px height                     │
└─────────────────────────────────────────────────────────────────────┘  ← y=1080
   x=0  x=50                                                  x=1920
```

**Размеры зон (initial values, calibrate on lab PC):**

| Zone | Width | Height | Position |
|---|---|---|---|
| Top Watch Bar | 1920px | 48px | (0, 0) |
| Tool Rail (compact) | 50px | 1008px | (0, 48) |
| Tool Rail (expanded) | 160px | 1008px | (0, 48) |
| Main Area | 1870px or 1760px | 1008px | (50, 48) or (160, 48) |
| Bottom Status Bar | 1920px | 24px | (0, 1056) |

**Tool rail width зависит от toggle** «показывать названия». Когда
expanded — main area уменьшается на 110px. Это сознательный trade-off для
новых операторов.

---

## 3. Top Watch Bar

**Назначение:** показывать **критическую информацию** которая нужна
оператору всегда, на любом экране, без переключений. После вопросов Q8
все четыре блока (a, b, c, d) имеют priority 7/7 — все обязательны.

**Высота:** 48px fixed.
**Background:** `surface.panel` (stone.100).
**Bottom border:** 1px `border.subtle`.
**Padding:** `space.4` left/right, `space.2` top/bottom.

### Зоны watch bar (слева направо)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ● Engine OK │ ● Эксп: cooldown_v3 · Cooldown 3/6 · 3д 14ч │ ● 22/24 OK │ 🛎 0 │
│             │                                              │         │       │
│  ZONE 1     │              ZONE 2                          │ ZONE 3  │ ZONE 4│
│  ~150px     │              ~700px                          │ ~250px  │ ~120px│
└─────────────────────────────────────────────────────────────────────┘
```

#### Zone 1 — Engine status (~150px)

```
● Engine OK              ← status.ok dot + body / text.secondary
```

States:
- `Engine OK` — `status.ok` dot, text.secondary
- `Engine offline` — `status.fault` dot, text.fault, click → reconnect
- `Engine starting` — `status.info` dot, text.info, with spinner-replacement: just dots animation

**Click action:** none. Это статус-индикатор только.

#### Zone 2 — Active experiment + phase + elapsed (~700px)

```
● cooldown_v3_2026_04_09 · Cooldown 3/6 · 3д 14ч 22мин
```

Components:
- `●` dot — `status.exp` или `status.ok` если активный, `status.stale` если нет
- Experiment name — body, text.primary, truncate с ellipsis если длинное
- ` · ` separator — text.muted
- Phase name + indicator — body, text.primary
- Elapsed time — mono.value, text.muted

**Когда нет активного эксперимента:**
```
○ Нет активного эксперимента
```
text.muted, click action отсутствует.

**Click action на эту зону:** открывает Эксперимент detail panel
(быстрый jump).

#### Zone 3 — Channel summary (~250px)

```
● 22/24 OK · 2 в caution
```

Логика:
- Подсчёт каналов по состояниям: ok / caution / warning / fault / stale
- Показать summary в формате "N/total OK" + secondary "M caution" если
  есть non-ok каналы
- Цвет dot — самый плохой статус среди каналов:
  - все OK → `status.ok`
  - есть caution → `status.caution`
  - есть warning → `status.warning`
  - есть fault → `status.fault` (мерцающий — D-013 fault pulse)

**Примеры:**
- `● 24/24 OK` (all good)
- `● 22/24 OK · 2 в caution`
- `● 18/24 OK · 4 caution · 2 warning`
- `● 21/24 OK · 1 fault` (с pulse animation на dot)

**Click action:** scroll к sensor grid на дашборде. Если в overlay —
переключиться на дашборд + scroll.

#### Zone 4 — Alarms (~120px)

```
🛎 0           ← bell icon, text.muted, when no alarms
🛎 3 active   ← bell icon, text.fault, when alarms present
```

**Click action:** открыть Алармы overlay panel (один из частых
drill-downs).

**Состояния:**
- `🛎 0` — text.muted, default
- `🛎 N active` — text.fault, where N > 0
- При появлении нового аларма — короткий attention animation (200ms
  scale flash), не повторяющийся

---

## 4. Tool Rail

**Назначение:** левая вертикальная навигационная полоса. Содержит иконки
для drill-down operations + переход домой на дашборд.

**Default width:** 50px (compact, icons only)
**Expanded width:** 160px (icons + text labels)
**Toggle:** в «Settings» submenu или прямо в tool rail внизу как ⋯
**Persisted:** выбор сохраняется в local config

**Background:** `surface.panel` (stone.100).
**Right border:** 1px `border.subtle`.

### Структура (compact mode)

```
┌────┐
│ ⌂  │  ← Дашборд (home)             [active highlight when current view]
├────┤
│    │
│ +  │  ← Создать новый эксперимент   (opens modal)
│    │
├────┤
│ 🜔  │  ← Эксперимент (управление)    (opens overlay)
│ ⚡ │  ← Источник мощности            (opens overlay)
│ ↗  │  ← Аналитика                    (opens overlay)
│ θ  │  ← Теплопроводность             (opens overlay)
│ 🛎 │  ← Алармы                       (opens overlay)
│ 📋 │  ← Служебный лог                (opens overlay)
│ 🔌 │  ← Приборы                      (opens overlay)
│    │
├────┤
│ ⋯  │  ← Ещё (submenu)
│    │     ↳ Архив
│    │     ↳ Калибровка (раз в год)
│    │     ↳ Settings
│    │     ↳ Toggle text labels
└────┘
```

### Структура (expanded mode)

```
┌──────────────────┐
│ ⌂  Дашборд       │
├──────────────────┤
│                  │
│ +  Новый экспер. │
│                  │
├──────────────────┤
│ 🜔  Эксперимент  │
│ ⚡ Источник мощ. │
│ ↗  Аналитика    │
│ θ  Теплопровод.  │
│ 🛎 Алармы        │
│ 📋 Служебный лог │
│ 🔌 Приборы       │
│                  │
├──────────────────┤
│ ⋯  Ещё...        │
└──────────────────┘
```

### Tool rail иконка spec

Каждая иконка — кликабельная зона ~50×40px (compact) или 160×40px
(expanded).

**States:**
- **Idle** — icon `text.muted`, label (если visible) `text.muted`
- **Hover** — icon `text.secondary`, label `text.secondary`, background
  `surface.card` (subtle hover bg)
- **Active** (current view) — icon `accent.400`, label `text.primary`,
  **left edge accent rail 3px** `accent.400` (вертикальная полоска
  marker)
- **Disabled** — icon `text.disabled` (например когда нет активного
  эксперимента — Эксперимент icon disabled? Нет — оставляем active
  всегда, просто внутри overlay показывает empty state)

**Tooltip:** в compact mode tooltip всегда показывает full label при
hover. В expanded mode tooltip отключён.

### Click actions

| Иконка | Action |
|---|---|
| ⌂ Дашборд | Возврат на дашборд (default view). Если уже на дашборде — no-op |
| + Новый эксп. | Открывает modal dialog для создания эксперимента |
| 🜔 Эксперимент | Открывает Эксперимент overlay (управление активным экспериментом, фазы) |
| ⚡ Источник | Открывает Источник мощности overlay (Keithley control) |
| ↗ Аналитика | Открывает Аналитика overlay (R thermal, vacuum prognosis, charts) |
| θ Теплопровод. | Открывает Теплопроводность overlay |
| 🛎 Алармы | Открывает Алармы overlay |
| 📋 Лог | Открывает Служебный лог overlay (full log view) |
| 🔌 Приборы | Открывает Приборы overlay (instrument status, диагностика) |
| ⋯ Ещё | Открывает popover menu с rare options |

---

## 5. Bottom Status Bar

**Назначение:** низкоприоритетная техническая информация которая
нужна реже чем то что в watch bar. Disk space, data rate, current time,
connection state.

**Высота:** 24px fixed.
**Background:** `surface.panel`.
**Top border:** 1px `border.subtle`.
**Font:** `mono.small` для чисел, `label` для меток.

```
┌─────────────────────────────────────────────────────────────────────┐
│ SAFE_OFF │ Аптайм 02:34:17 │ Диск 719ГБ │ 12 изм/с │ ● Connected │ 14:32:17 │
└─────────────────────────────────────────────────────────────────────┘
```

Зоны слева направо:
1. Safety FSM state — pill style, цвет по state
2. Engine uptime — mono.small, text.muted
3. Disk space — mono.small + label, text.muted (warning if <50GB,
   fault if <10GB)
4. Data rate — measurements/sec, mono.small, text.muted
5. Connection state — dot + label
6. Current time — mono.small, text.muted (на правом краю)

Разделители — vertical 1px lines `border.subtle`, padding `space.3`
между зонами.

**Никаких click actions.** Это passive readout.

---

## 6. Dashboard view (default)

**Это главный экран.** Открыл программу — увидел дашборд. Закрыл overlay
— вернулся на дашборд. Большую часть времени работы оператор смотрит
именно сюда.

**Полное пространство:**
- Width: 1870px (compact tool rail) или 1760px (expanded)
- Height: 1008px (между watch bar и status bar)

### Vertical layout (top to bottom)

```
┌─ Phase-aware top widget ─────────────────────── ~140px ──────┐
│  Содержимое зависит от фазы (см. раздел 7)                    │
└────────────────────────────────────────────────────────────────┘
                       space.4 (16px gap)
┌─ Большой график температур ───────────────────── ~380px ─────┐
│                                                                │
│  [1мин] [1ч] [6ч] [24ч] [Весь]    ↑ time window picker        │
│                                                                │
│  multi-channel plot, 8 colors palette                          │
│  inline legend top-right                                       │
│  selectable channels via legend click                          │
│                                                                │
└────────────────────────────────────────────────────────────────┘
                       space.4 (16px gap)
┌─ Compact график давления ──────────────────────── ~140px ────┐
│                                                                │
│  log Y axis, same X time scale as temperature plot above      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
                       space.4 (16px gap)
┌─ Sensor grid ──────────────────────────────────── ~270px ────┐
│                                                                │
│  Dynamic auto-pack видимых каналов                            │
│  Cards width ~140-160px (стандартный размер)                  │
│  Длинные labels на 2 строки если нужно                        │
│                                                                │
│  4-5 строк cards × 7-8 cards в строку (auto-fit)              │
│                                                                │
└────────────────────────────────────────────────────────────────┘
                       space.2 (8px gap)
┌─ Quick log block (collapsed by default) ─────── ~32px ──────┐
│  📋 Журнал [▼]                                                 │
└────────────────────────────────────────────────────────────────┘
```

**Vertical sum:**
- Phase widget: 140
- Gap: 16
- Temp plot: 380
- Gap: 16
- Pressure plot: 140
- Gap: 16
- Sensor grid: 270
- Gap: 8
- Quick log collapsed: 32
- **Total: 1018px**

vs Available 1008px → tight, **переполнение 10px**. Calibration на лаб PC
скорректирует. Возможные ужатия:
- Phase widget 140 → 120
- Temp plot 380 → 360
- Sensor grid 270 → 250 (с 4 строками вместо 4-5)

**Когда Quick log раскрыт:**

```
┌─ Quick log block (expanded) ──────────────────── ~80px ──────┐
│  📋 Журнал [▲]                                                 │
│  ┌──────────────────────────────────────────┐ [Записать]      │
│  │ Заметка оператора...                      │                 │
│  └──────────────────────────────────────────┘                 │
└────────────────────────────────────────────────────────────────┘
```

В expanded состоянии log block увеличивается с 32 до 80px, sensor grid
поджимается соответственно. Это **временное** состояние — оператор
написал заметку, нажал Записать (или Enter) → блок снова collapsed.

### Sensor grid spec

**Не статичный 8×3 grid.** Auto-pack логика:

1. Берёт `channels.yaml` → отбирает каналы с `visible: true`
2. Группирует по `group` field (КРИОСТАТ / КОМПРЕССОР / ОПТИКА /
   РЕЗЕРВ)
3. Для каждой группы создаёт **тонкий group separator** (1px line
   + group label `КРИОСТАТ` heading uppercase + counter «7 каналов»)
4. Под separator — flow layout cards, auto-wrap по доступной ширине

**Если канал hidden** в config — он физически отсутствует, grid
поджимается. Если все каналы группы скрыты — separator группы тоже
пропадает.

**Card spec** (стандартный, как было):
- Width: ~140-160px (calibrate)
- Height: ~80-100px (calibrate)
- Background: `surface.card`
- Border: 1px `border.subtle`
- Radius: `radius.md`
- Padding: `space.2`

**Card content:**
```
┌─────────────────────────────┐
│ Т11 Теплообменник 1          │  ← body, text.secondary, 1-2 lines
│                              │
│  77.42  К                    │  ← mono.value, text.primary
│                              │
│ ▼ −0.3 K/мин   12s          │  ← label, text.muted/text.ok
└─────────────────────────────┘
```

**Inline rename:** click на label → label превращается в editable
QLineEdit, Enter сохраняет, Esc отменяет, click outside сохраняет.
**Это NEW feature** относительно текущего UI где имена меняются через
Channel Editor.

### Plot widget spec

**Большой график температур:**

- Background: `theme.PLOT_BG` (stone.0) — наследуется от global pyqtgraph
  config
- Foreground: `theme.PLOT_FG`
- Grid: `theme.PLOT_GRID_COLOR` @ 35% alpha
- Lines: `theme.PLOT_LINE_PALETTE` cycling, width 1.5px
- Inline legend top-right corner, no background fill
- Time window picker: tertiary buttons row above plot
  `[1мин] [1ч] [6ч] [24ч] [Весь]`
- Active button: `accent.400` underline + `text.primary`
- Channel toggle: click on legend entry → toggle visibility

**Compact график давления:**

- То же стилистически, log Y axis
- Same X time scale **synchronized** с temp plot above (когда меняешь
  time window — оба графика обновляются одновременно)
- Высота меньше — это secondary plot, не main focus

### Quick log block spec

**Collapsed (default):**
```
📋 Журнал [▼]
```
- Height 32px
- Single row, icon + label + collapse arrow
- Background `surface.card`, subtle hover effect
- Click на любую часть → expand

**Expanded:**
```
📋 Журнал [▲]
[ Заметка оператора...                              ] [Записать]
```
- Height 80px
- QLineEdit with placeholder, Enter to submit, Записать button
- Click на arrow [▲] → collapse
- After submit → toast "Запись сохранена" (top-center, 4s) + auto-collapse

**Storage:** запись идёт в operator log через ZMQ command (existing
endpoint).

---

## 7. Phase-aware top widget

**Это центральная инновация нового дашборда.** Один widget на одном месте,
содержимое **полностью меняется** в зависимости от фазы активного
эксперимента (или его отсутствия).

**Width:** full main area width
**Height:** ~140px (calibrate)
**Background:** `surface.card`
**Border:** 1px `border.subtle`
**Radius:** `radius.md`
**Padding:** `space.4`

### Семь режимов

#### 7.1 — No active experiment

Когда `experiment_status` returns `active_experiment: None`.

```
┌────────────────────────────────────────────────────────────────┐
│  Нет активного эксперимента                                     │
│                                                                  │
│  Последний:  cooldown_v3_2026_04_03 · 6 дней · завершён 14ч назад│
│                                                                  │
│  [+ Создать новый эксперимент]                                  │
└────────────────────────────────────────────────────────────────┘
```

- Heading: "Нет активного эксперимента", `heading`, `text.secondary`
- Last experiment summary: `body`, `text.muted`
- Primary button: "+ Создать новый эксперимент", primary variant, opens
  modal dialog

#### 7.2 — Phase: preparation (probe view)

Эта фаза = диагностика датчиков руками. Top widget сам становится
**probe view** для прозванивания.

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Подготовка                          [→ Перейти к Vacuum] │
│                                                                  │
│  ┌─ Probe rolling 15 min ─────────────────────────────────────┐ │
│  │                                                              │ │
│  │  real-time temperature trace, выбранные каналы              │ │
│  │                                                              │ │
│  └─────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

- Phase title: "ФАЗА: Подготовка", `label`, uppercase, text.muted
- Right-aligned: "Перейти к Vacuum →" tertiary button (manual phase
  transition)
- Inside: rolling 15-min plot, height ~85px
- Plot is real-time, scrolls left as new data comes in
- Channel selection: top channels of interest for diagnostics (configurable
  later)

**Зачем именно здесь:** ты сказал что probe view нужен но
"место ворует". Решение — он живёт **только** в preparation phase
widget'е, не на дашборде вообще. Когда нет preparation — нет probe
view вообще, место освобождается для других режимов.

#### 7.3 — Phase: vacuum (откачка)

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Откачка                            [→ Перейти к Cooldown]│
│                                                                  │
│  ETA до 1×10⁻⁵ мбар:    2ч 14мин                                │
│  Текущее P:             4.2×10⁻³ мбар                           │
│  Тренд:                 стабильное снижение  ●                  │
│  Уверенность модели:    87%                                     │
└────────────────────────────────────────────────────────────────┘
```

- Phase title + manual transition button
- Big ETA value: `display`, mono, `text.primary`
- Current P: `mono.value`, `text.secondary`
- Trend: status text + dot (status.ok if pumping down, status.warning
  if stable, status.fault if rising)
- Confidence: percentage, text.muted
- All values pulled from VacuumTrendPanel logic (existing code)

#### 7.4 — Phase: cooldown (захолаживание)

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Захолаживание                    [→ Перейти к Measurement]│
│                                                                  │
│  ETA до 4.2 K:          12ч 14мин                               │
│  Текущая dT/dt:         −0.31 K/мин                             │
│  План:                  −0.30 K/мин (по графику)                │
│  Reference канал:       T11 (на текущий момент 77.4 K)          │
└────────────────────────────────────────────────────────────────┘
```

- Phase title + manual transition button
- Big ETA value: `display`, mono, `text.primary`
- Current rate: `mono.value`, color по plan match (status.ok if matching,
  status.caution if drifting)
- Plan rate: `mono.value`, text.muted
- Reference channel: from cooldown predictor logic
- All values pulled from CooldownPredictor (existing code)

#### 7.5 — Phase: measurement (измерение)

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Измерение                         [→ Перейти к Warmup]   │
│                                                                  │
│  R thermal:             3.42 К/Вт   ±0.05                       │
│  Steady state:          ✓ стабильно (12 мин)                    │
│  Active source:         smua: 0.500 W                           │
│  Текущий dT:            +0.02 K/мин (within tolerance)          │
└────────────────────────────────────────────────────────────────┘
```

- Phase title + manual transition button
- R thermal: `display`, mono, `text.primary` + tolerance label.muted
- Steady state indicator with checkmark + duration
- Active source readout (Keithley current state)
- Drift indicator

#### 7.6 — Phase: warmup (нагрев)

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Нагрев                            [→ Перейти к Teardown] │
│                                                                  │
│  ETA до 295 K:          8ч 22мин                                │
│  Текущая dT/dt:         +0.42 K/мин                             │
│  Reference канал:       T11 (на текущий момент 142.7 K)         │
└────────────────────────────────────────────────────────────────┘
```

- Same layout as cooldown but reversed (rate is positive, ETA is to
  warmup target)

#### 7.7 — Phase: teardown (разборка) / experiment ended

```
┌────────────────────────────────────────────────────────────────┐
│  ФАЗА: Разборка                          [✓ Завершить]           │
│                                                                  │
│  ИСТОРИЯ ИСПЫТАНИЯ                                              │
│  Подготовка    →  4ч 12мин   ✓                                  │
│  Откачка       →  18ч 33мин  ✓                                  │
│  Захолаживание →  14ч 02мин  ✓                                  │
│  Измерение     →  4д 8ч      ✓                                  │
│  Нагрев        →  9ч 18мин   ✓                                  │
│  Разборка      →  идёт...                                       │
└────────────────────────────────────────────────────────────────┘
```

- Phase title + final action button "Завершить" (closes experiment)
- Below: timeline of completed phases with their durations
- Each row: phase name + duration + checkmark
- Current phase row: "идёт..." instead of duration
- After "Завершить" → confirmation modal → experiment archived → widget
  switches to "no active experiment" state

### Phase transition logic

**Manual + auto-correction safety net** (per Q13):

- Кнопки "→ Перейти к ..." всегда видны в правой части widget'а
- Click → opens confirmation popover:
  ```
  Перейти из фазы Cooldown в фазу Measurement?
  
  ⚠ Детектор считает что фаза должна была закончиться 4ч 22мин назад
    (реальный момент перехода: 14:32:11)
  
  [Применить ретроактивно (14:32:11)]  [Сейчас (18:54:33)]  [Отмена]
  ```
- Если детектор не сработал — нет warning, просто confirmation
- After confirm → engine updates phase + timestamps → widget refreshes
  to next phase mode

**Engine work needed for this** (out of UI scope, parallel track on
master with Codex):
- Phase transition detector (some heuristic per phase: vacuum done when
  P < threshold for N seconds; cooldown done when T11 stable for M
  minutes; etc)
- Retroactive timestamp correction in experiment.py
- ZMQ command `experiment_phase_transition` with optional
  `retroactive_timestamp` parameter

---

## 8. Detail panels

**Все detail panels — full takeover overlay.** Дашборд скрывается,
panel занимает всё пространство main area (1870 или 1760 width × 1008
height). Top watch bar и tool rail остаются видимы.

**Закрыть overlay:** click на ⌂ Дашборд в tool rail, или Esc, или
click на текущую active иконку tool rail (toggle off).

**При активном overlay:** соответствующая иконка в tool rail в active
state (accent left edge rail + accent icon color). Это явно показывает
"ты сейчас не на дашборде, ты в overlay X".

### 8.1 — Эксперимент overlay

Управление активным экспериментом — фазы, метаданные, заметки,
артефакты.

```
┌── ЭКСПЕРИМЕНТ ───────────────────────────────────────[× Закрыть]┐
│                                                                  │
│  cooldown_v3_2026_04_09  · Cooldown · 3д 14ч                    │
│                                                                  │
│  ┌─ Метаданные ──────────────┐  ┌─ Phase timeline ────────────┐ │
│  │ Шаблон:    Cooldown       │  │ ✓ Подготовка    4ч 12мин    │ │
│  │ Оператор:  Иванов И.И.    │  │ ✓ Откачка       18ч 33мин   │ │
│  │ Образец:   Sample-X42     │  │ ● Cooldown      идёт 14ч    │ │
│  │ Криостат:  АКЦ ФИАН       │  │ ○ Измерение                 │ │
│  │ Описание:  ...             │  │ ○ Нагрев                    │ │
│  └────────────────────────────┘  │ ○ Разборка                  │ │
│                                  └──────────────────────────────┘ │
│                                                                  │
│  ┌─ Заметки ──────────────────────────────────────────────────┐ │
│  │ 14:32  Запуск эксперимента                                  │ │
│  │ 18:42  Достигнуто P = 1e-4, переход в cooldown              │ │
│  │ 22:15  T11 на 200K, всё штатно                              │ │
│  │ ...                                                          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Артефакты ────────────────────────────────────────────────┐ │
│  │ readings.parquet  · 142 МБ                                   │ │
│  │ alarms.csv         · 4 КБ                                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                                              [Завершить эксперимент]│
└─────────────────────────────────────────────────────────────────┘
```

**Что НЕ здесь:** создание нового эксперимента — это modal dialog (см.
8.2), не overlay panel. Этот overlay — для управления **активным**.

### 8.2 — Создание эксперимента (modal dialog, не overlay)

Открывается через `+` в tool rail. Modal centered, scrim behind.

```
                ┌─────────────────────────────────────────┐
                │  Создать новый эксперимент               │
                │                                          │
                │  Шаблон     [Cooldown ▼]                 │
                │  Имя        [_______________________]     │
                │  Оператор   [Иванов И.И. ▼]              │
                │  Образец    [_______________________]     │
                │  Криостат   [АКЦ ФИАН ▼]                 │
                │                                          │
                │  Описание                                │
                │  [_____________________________________] │
                │  [_____________________________________] │
                │                                          │
                │  Заметки (необязательно)                 │
                │  [_____________________________________] │
                │                                          │
                │           [Отмена]    [Создать]          │
                └─────────────────────────────────────────┘
                  600px width × 540px height (calibrate)
                  centered, surface.elevated, scrim behind
```

After "Создать" → modal closes → дашборд auto-switches to phase widget
showing newly created experiment in preparation phase.

### 8.3 — Источник мощности overlay

Layout похож на текущий Источник мощности tab, но с чистой стилистикой
из design system. Two columns smua / smub, big readouts V/I/R/P
(neutral borders, quantity color только в title text), 2x2 plots grid
per channel.

Структура уже спроектирована в `UI_REWORK_ROADMAP.md` секция 5.3 —
применить как есть с обновлёнными tokens.

### 8.4 — Аналитика overlay

Hero metric cards (R thermal + Cooldown predict) с **нейтральными**
borders, R_thermal plot (с empty state), Vacuum prognosis card
(консолидированный, two-column inside).

Структура из roadmap 5.4 как есть.

### 8.5 — Теплопроводность overlay

Two-column layout: left 320px controls, right flex results+plot.
Group headers для трёх секций (Выбор датчиков / Источник P /
Автоизмерение).

Структура из roadmap 5.5 как есть.

### 8.6 — Алармы overlay

Empty state when no active alarms. Active section + history section
when alarms present.

Структура из roadmap 5.6 как есть.

### 8.7 — Служебный лог overlay

Add entry section (нормальная textarea, normal button) + entries list
с empty state.

Структура из roadmap 5.7 как есть.

### 8.8 — Приборы overlay

Instrument cards с **left edge color indicators** (3px vertical),
sensor diagnostics table.

Структура из roadmap 5.10 как есть.

### 8.9 — Архив overlay (rare, через ⋯ Ещё)

Filter card + two-column results.

Структура из roadmap 5.8 как есть.

### 8.10 — Калибровка overlay (раз в год, через ⋯ Ещё)

Структура из roadmap 5.9 как есть.

---

## 9. Click budget

**Цель Phase UI-1 v2:** уменьшить число кликов для частых действий до
минимума.

| Действие | Сейчас (старый UI) | Новый UI | Дельта |
|---|---|---|---|
| Посмотреть текущую T любого канала | 0 (на Обзоре) | 0 (на дашборде) | = |
| Посмотреть текущее давление | 0 (на Обзоре) | 0 (всегда видно в watch bar zone 3 + на дашборде) | = |
| Посмотреть фазу эксперимента | 1 клик (переключиться в Эксперимент) | **0** (всегда в watch bar zone 2) | **−1** |
| Посмотреть alarms count | 1 клик (переключиться в Алармы) | **0** (всегда в watch bar zone 4) | **−1** |
| Посмотреть ETA cooldown | 1 клик (переключиться в Аналитика) | **0** (на дашборде в phase widget) | **−1** |
| Записать заметку в журнал | 2 клика (на Обзоре snip log + ввод) | **2** (раскрыть log + ввод) | = |
| Открыть Источник мощности | 1 клик (tab) | 1 клик (tool rail icon) | = |
| Открыть Аналитику | 1 клик (tab) | 1 клик (tool rail icon) | = |
| Создать новый эксперимент | 2-3 клика (Эксп tab → форма → Создать) | 2 клика (+ icon → форма → Создать) | **−1** |
| Acknowledge alarm | 2 клика (Алармы tab → ACK button) | 2 клика (🛎 watch bar → ACK button) | = |
| Переименовать датчик | 4-5 кликов (Settings → Channel editor → row → edit → save) | **2 клика** (click on label → edit → Enter) | **−2 to −3** |
| Переключить time window графика | 1 клик | 1 клик | = |
| Переключиться обратно на дашборд из любого overlay | 1 клик (другой tab) | 1 клик (⌂ icon) или Esc | = |

**Net win:** 5-6 операций экономят клики, ничего не дороже. Inline
rename — **самый большой выигрыш** (−2 до −3 кликов на операцию).

**Ambient awareness wins** (что **видно без кликов** что раньше требовало
переключения):
- Текущая фаза эксперимента
- Время с начала эксперимента
- Количество активных алармов
- ETA текущей фазы
- Health всех 24 каналов в одну строку
- Engine state

---

## 10. Component inventory

Что нужно построить/обновить/удалить.

### Новые widgets (не существуют сейчас)

| Widget | Назначение | Сложность |
|---|---|---|
| `TopWatchBar` | persistent watch bar 48px | Medium |
| `BottomStatusBar` | bottom status 24px | Small |
| `ToolRail` | left vertical navigation 50/160px | Medium |
| `PhaseAwareWidget` | top widget на дашборде, 7 режимов | **Large** |
| `ProbeView` | rolling 15-min plot для preparation phase | Medium |
| `DashboardView` | container собирающий всё на дашборде | Medium |
| `OverlayContainer` | контейнер для full takeover detail panels | Small |
| `MainWindow` (rewrite) | новый main window заменяющий tab-based | Large |
| `NewExperimentDialog` | modal dialog для создания эксп | Medium |
| `SensorCardWithRename` | sensor card с inline rename | Medium |
| `DynamicSensorGrid` | auto-pack visible channels grid | Medium |
| `QuickLogBlock` | collapsible log block | Small |
| `TimeWindowPicker` | tertiary buttons для plot time selection | Small |

### Обновляемые widgets (существуют, нужен rework)

| Widget | Что меняется |
|---|---|
| `OverviewPanel` | **полностью переписывается** как `DashboardView` |
| `ExperimentWorkspace` | переписывается как `ExperimentOverlay` |
| `KeithleyPanel` | minor styling cleanup, layout остаётся |
| `AnalyticsPanel` | rework hero cards (без цветных borders уже сделано), vacuum prognosis consolidation |
| `ConductivityPanel` | left column group headers |
| `AlarmPanel` | empty state, active/history sections |
| `OperatorLogPanel` | normal button sizes |
| `ArchivePanel` | filter card, empty states |
| `InstrumentStatusPanel` | left edge color indicators |

### Удаляемые widgets / классы

| Что | Почему |
|---|---|
| `TempCardGrid` (фиксированный 8×3) | заменяется на `DynamicSensorGrid` |
| `_PlaceholderCard` | не нужны placeholders в dynamic grid |
| `ExperimentStatusWidget` (на Overview) | переезжает в `TopWatchBar` zone 2 |
| `KeithleyStrip` (на Overview) | удаляется, source visible через `⚡` overlay |
| `QuickLogWidget` (старый) | заменяется на `QuickLogBlock` (collapsible) |
| `_separator` mini widget | заменяется на bottom status bar |
| `autosweep_panel.py` | deprecated, формально удаляется |
| Top tab bar | заменяется на tool rail |

### Что остаётся как есть

- `theme.py` (foundation tokens) — без изменений, **используется массово**
- `common.py` helpers (после Block 6 already updated)
- Engine, drivers, core, safety, storage, analytics, reporting — **не
  трогаем**
- ZMQ commands API — без изменений, GUI просто использует existing endpoints
- Plot widgets pyqtgraph base — без изменений, global config из theme.py

---

## 11. Что выкидывается из старого подхода

Чтобы не было путаницы — что мы **активно убираем** относительно текущего
UI:

1. **Tab bar сверху** — заменяется на tool rail слева
2. **Top header bar в текущем виде** (engine + tabs + buttons separated) —
   консолидируется в watch bar
3. **«Обзор» как один из табов** — становится **default view**
   приложения, не таб
4. **T11/T12 hero readouts** — концепция отменена, все каналы равны
5. **Static 8×3 sensor grid** с placeholder cells — заменяется на
   dynamic grid
6. **Channel naming через Settings** — заменяется на inline rename
7. **Bottom Keithley strip на Overview** — удаляется, info в Source overlay
8. **«Журнал» input на Overview без collapse** — заменяется на
   collapsible block
9. **Цветные borders на cards в Аналитика и Источник** — нейтрализованы
   (уже сделано в Block 6, остаётся как есть)
10. **Отдельный «Эксперимент» tab как полу-форма с пустотой справа** —
    заменяется на modal dialog (создание) + overlay (управление)
11. **Disabled grey buttons в Архив** — заменяются на пустое место
12. **Декоративные colored section headers** в формах (зелёный/синий/фиолетовый
    QGroupBox titles) — нейтрализованы

---

## 12. Phase UI-1 v2 plan

### Подход

Phase UI-1 v2 — это **rewrite дашборда + supporting infrastructure**, не
точечный cleanup. Большая работа но focused: один экран (дашборд) +
shell (watch bar + tool rail + status bar) + 2-3 supporting components.

**Что делается в Phase UI-1 v2:**
1. New shell: TopWatchBar + ToolRail + BottomStatusBar
2. New `MainWindow` rewrite использующий новый shell + overlay container
3. New `DashboardView` со всеми блоками (phase widget, plots, sensor
   grid, quick log)
4. New `PhaseAwareWidget` со всеми 7 режимами
5. New `DynamicSensorGrid` + `SensorCardWithRename` (inline rename)
6. New `NewExperimentDialog` (modal)
7. Existing detail panels работают **как есть** (со styling из Block 6)
   — открываются через tool rail в overlay container
8. Calibration на лаб PC — pixel values, density, font sizes

**Что НЕ делается в Phase UI-1 v2 (откладывается на UI-2):**
1. Rework existing detail panels' internal layouts (Аналитика hero cards
   restructure, Теплопроводность two-column, Архив filter card,
   Алармы empty state) — пока работают как есть
2. Empty states everywhere — только на дашборде
3. Toast system — только базовый для quick log submit
4. Web dashboard styling — Phase UI-3
5. Custom tab bar icons — нет tab bar вообще
6. Fault pulse animation D-013 — Phase UI-2 with proper SensorCard

### Block структура

**Block A — Shell scaffold (foundation)**
- Создать `TopWatchBar`, `BottomStatusBar`, `ToolRail` widgets
- Создать `OverlayContainer` widget
- Переписать `MainWindow` использующий новый shell
- Существующие panels подключаются через overlay container (как было,
  но без tab bar)
- Tool rail icons работают, overlay открываются/закрываются
- Дашборд = пока **stub** "Coming soon"
- Tests pass, smoke test работает

**Block B — DashboardView skeleton**
- Создать `DashboardView` widget
- В нём — placeholder для PhaseAwareWidget + temp plot + pressure plot +
  sensor grid + quick log
- Plots работают (pyqtgraph + theme), показывают данные через ZMQ
  существующим способом
- Sensor grid пока статичный (как в OverviewPanel)
- Quick log collapsed by default
- Phase widget — заглушка "Phase widget here"

**Block C — DynamicSensorGrid + SensorCardWithRename**
- Заменить статичный grid на dynamic auto-pack
- Group headers
- Card с inline rename feature
- Connection с channels.yaml visibility

**Block D — PhaseAwareWidget (7 modes)**
- Базовая инфраструктура switching между режимами по `current_phase`
- Реализовать каждый из 7 режимов отдельно (можно по одному за коммит)
- Manual phase transition button + confirmation popover
- Auto-correction safety net — UI часть готова, ждёт engine support

**Block E — NewExperimentDialog**
- Modal dialog с формой
- Submit → ZMQ create_experiment command
- Triggered from `+` icon в tool rail

**Block F — TopWatchBar содержимое**
- Реализовать все 4 zone в watch bar с реальными данными через ZMQ
- Channel summary live update (count by status)
- Alarm count live update
- Click handlers (Zone 2 → Эксперимент overlay, Zone 4 → Алармы overlay)

**Block G — QuickLogBlock collapsible**
- Collapse/expand
- Submit through existing log endpoint

**Block H — Tool rail polish**
- Toggle "Show labels" в Settings или Ещё submenu
- Persisted state
- Hover tooltips
- Active state highlighting

**Block I — Lab PC calibration**
- Bundle, deploy, visual review on real monitor
- Iterate on theme.py pixel values
- Type scale calibration
- Spacing scale calibration
- Sensor card sizing
- Plot heights
- Final commit of calibrated values

### Estimated effort

Это **значительно больше** чем v1 Phase UI-1. Реалистично:
- Block A: 1 session (~1-2 hours CC)
- Block B: 1 session
- Block C: 1 session
- Block D: 2-3 sessions (большой block, 7 mode реализаций)
- Block E: 0.5 session
- Block F: 1 session
- Block G: 0.5 session
- Block H: 0.5 session
- Block I: 1-2 sessions с iterations

**Total:** ~9-12 sessions of CC work + Vladimir review между блоками.

### Branch strategy

- Создать новую ветку **`feat/ui-phase-1-v2`** от current `feat/ui-phase-1`
  HEAD (т.е. поверх всех 7 коммитов v1)
- Все Block 6 token swaps **сохраняются** — они правильные, мы их
  используем массово
- В UI v2 вся новая код использует tokens из `theme.py` с самого начала,
  никаких hardcoded hex
- При конфликте с CodexBranch на master — merge master вручную в
  определённый момент после Block H

### Что НЕ деплоим до конца

Phase UI-1 v2 **не деплоим на лаб PC** до Block I calibration. Текущая
v1 ветка остаётся как baseline для отката.

### Success criteria

- 829+ tests passing (baseline сохранён, новые tests добавлены для
  новых widgets)
- Visual review на лаб PC показывает: дашборд читается за 1 секунду,
  все важные числа видны без кликов, оператор может работать без
  переключения "табов"
- Vladimir говорит "Это уже что-то": не "ну неплохо", а реально
  visual transformation
- Clickbudget: large reductions в frequent actions (см. секцию 9)

---

## Конец wireframe v0.1

**Что сейчас:**
1. Vladimir читает этот документ
2. Корректирует / возражает / задаёт вопросы
3. После 1-2 итераций — wireframe становится v0.2 final
4. Я пишу детальную спеку для Block A (новый CC prompt)
5. CC начинает работу

**Что НЕ сейчас:**
- Нет кода
- Нет коммитов
- Нет CC prompt
- Только архитектурное соглашение о форме
