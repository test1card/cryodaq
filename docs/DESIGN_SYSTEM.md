> **SUPERSEDED.** This document (v0.3) is replaced by `docs/design-system/README.md` (v1.0.1). Retained for historical context.

# CryoDAQ Design System v0.3

> **Источник истины** для визуального языка CryoDAQ GUI. Спецификация, не код.
>
> **Scope:** только CryoDAQ. Primary target — лабораторный PC Linux, один
> монитор FHD 1920×1080 или 1920×1200, fullscreen. Dev target — MacBook Pro
> 14" M5 в окне. Web dashboard — отдельный target в UI-3, здесь не
> рассматривается.
>
> **Связанные документы:**
> - `docs/UI_REWORK_ROADMAP.md` — screen-by-screen specs, phase planning, что
>   делается когда. Этот документ содержит **правила**, roadmap содержит
>   **планы**.
>
> **Что изменилось относительно v0.2:**
> - Accent: warm amber → cool indigo (холодный акцент на тёплой базе даёт
>   сильнее statement и снимает риск конфликта с warning orange)
> - `status.exp` удалён (over-engineering, не подтверждён реальной моделью
>   состояний)
> - Sensor card fault state упрощён до двух channel
> - Добавлены keyboard / accessibility / color vision секции
> - Добавлен document lifecycle
> - Decision log расширен до 25+ записей
> - Screen-by-screen specs вынесены в отдельный файл (roadmap)
> - Все конкретные пиксельные числа помечены как подлежащие калибровке на
>   реальном железе лаборатории

---

## Оглавление

1. [Эстетический манифест](#1-эстетический-манифест)
2. [Architecture principles](#2-architecture-principles)
3. [Foundation tokens](#3-foundation-tokens)
4. [Plot system](#4-plot-system)
5. [Component patterns](#5-component-patterns)
6. [Interaction system](#6-interaction-system)
7. [Motion и feedback](#7-motion-и-feedback)
8. [Accessibility и color vision](#8-accessibility-и-color-vision)
9. [Anti-patterns](#9-anti-patterns)
10. [Decision log](#10-decision-log)
11. [Document lifecycle](#11-document-lifecycle)

---

## 1. Эстетический манифест

### 1.1 Кто оператор и в каких условиях

- **Дневная смена**: эксперт за столом, активная работа с экспериментом,
  калибровкой, аналитикой. Окружение освещено, оператор фокусирован.
- **Ночная смена**: дежурный лаборант, периферийное внимание, главная задача —
  заметить аномалию среди многочасового спокойного течения. Окружение
  частично затемнено, оператор устал.
- **Web мониторинг** (планируется в UI-3): one-glance проверка с телефона
  дома или с другого ПК. Не рассматривается в этом документе.

CryoDAQ — **professional instrument**, не consumer software. Оператор знает
свою установку, ожидает что интерфейс уважает его время, не нуждается в
onboarding, нуждается в полной честной картине в любой момент.

### 1.2 Что мы хотим оставить как впечатление

> "Это сделано кем-то кто знает что такое лаборатория, и кто заботится о том
> как его инструмент выглядит."

Не должен подумать:

> "Это GitHub dashboard."
> "Это Bootstrap admin panel."
> "Какой-то generic dark theme."
> "Что эта кнопка вообще делает."

Конкретные качества:

- **Точность.** Каждое число читается мгновенно. Каждая единица явная. Каждый
  статус однозначный. Нет "примерно".
- **Тишина в норме.** Когда всё хорошо — интерфейс не просит внимания. Hover
  не вспыхивает, idle elements не пульсируют.
- **Срочность когда нужно.** Fault states ломают визуальное спокойствие
  намеренно — это **единственная** причина для visual disruption.
- **Уважение к плотности.** 24 канала, давление, источник, alarms, фазы
  эксперимента — вся картина видна, не прячется за drilldown.
- **Инструментальность.** У хорошего инструмента эстетика следует за функцией
  так плотно что они становятся одним.
- **Температурный контраст.** Тёплая stone база + холодный indigo акцент.
  Это характерное "лицо" которое нельзя спутать ни с GitHub, ни с Bootstrap,
  ни с типичной dark theme.

### 1.3 Эстетическая позиция

Референсы (в порядке влияния):

- **Linear** — typography discipline, monochrome + single accent, низкий
  ceremony, тонкая иерархия через размер шрифта. Главный референс для
  **типографики** и **spacing rhythm**.
- **Ableton Live** — информационная плотность, цвет как канал данных,
  professional tool attitude. Главный референс для **density** и
  **dealing with complexity**.
- **Raycast** — structured hierarchy, command-result-hint паттерн,
  keyboard-first feel. Главный референс для **hierarchy clarity** и
  **keyboard-first interaction**.

Дисциплины (формальные источники):

- **Apple HIG** — density, hierarchy, form design
- **Material Design 3** — token architecture
- **Edward Tufte** — data-ink ratio, plot styling
- **WCAG 2.2** — contrast lower bounds, accessibility

Что **не** берём от референсов:

- От Linear — колд slate базу (мы теплее для характера)
- От Ableton — skeumorphic detail и chrome (мы flat)
- От Raycast — command palette как primary interaction (у нас не launcher)

### 1.4 Температурный контраст как ядро identity

Ключевое дизайнерское решение: **тёплая нейтральная база + холодный акцент.**

Тёплый stone neutral создаёт ощущение "лабораторного уюта" — это не
холодный операционный зал, это место где люди работают часами. Холодный
indigo accent — это **точечное вмешательство разума** в эту тёплую среду:
фокусный ring, primary action, selected state. Как холодный LED индикатор на
тёплом деревянном столе.

Эта комбинация **невозможна** в generic dark themes (которые либо полностью
cool, либо полностью warm), поэтому она гарантирует что CryoDAQ не будет
перепутан ни с одним существующим инструментом.

Warm warning/caution semantic colors **усиливают** тёплую базу — они в том
же температурном семействе. Cold fault red и indigo accent **выламываются**
из тёплой базы контрастно, что делает их немедленно заметными.

---

## 2. Architecture principles

### 2.1 Token architecture

Двухуровневая система (Material Design 3 style):

- **Reference tokens** (raw values): hex, размеры, шрифты. Имена
  нейтральные. Пример: `stone.100`, `accent.400`, `space.4`.
- **Semantic tokens** (mapped to reference): имена описывают **назначение**.
  Пример: `surface.base`, `text.primary`, `status.fault`.

**Правило:** виджеты используют **только** semantic tokens. Reference
существуют только в `theme.py` как промежуточный слой. Это позволяет
переключить `accent.400` → `accent.500` в одном месте и обновить весь
интерфейс.

### 2.2 Density calibration philosophy

**Density будет калиброваться на реальном лабораторном Linux PC**, не на
dev Mac. Все конкретные пиксельные значения spacing, card heights, layout
dimensions помечены в документе как `[calibrate]` и представляют **первые
разумные defaults**, а не финальные решения.

**Калибровочный процесс:**
1. Phase UI-1 реализует token structure с default values
2. Bundle развёртывается на лабораторном Linux PC
3. Визуальная проверка на реальном FHD мониторе в реальном лабораторном
   освещении
4. Итеративная корректировка значений в `theme.py` (одно место правки)
5. Финальные калиброванные значения коммитятся как часть Phase UI-1 closure

**Что калибруется:**
- Spacing scale pixel values (space.1..space.6)
- Type scale pixel values (font sizes и line heights)
- Card minimum widths (sensor card, big readout, hero)
- Layout breakpoint для compact vs standard
- Plot minimum heights
- Panel fixed widths (sidebar, filter card)

**Что НЕ калибруется (это architectural decisions):**
- Число ступеней в scale (6 в spacing, 6 в type — фиксировано)
- Modular ratio type scale (1.2 — фиксировано)
- Количество density modes (один глобальный — фиксировано)
- Какие tokens какие назначения имеют

### 2.3 Discipline over flexibility

Ключевой принцип: **жёсткие правила, мало исключений, нет "альтернативных
вариантов"**.

- Один токен → одно назначение
- Один статус → один цвет
- Один тип действия → одна кнопка
- Один fault state → один primary visual channel

Это **упрощает** имплементацию и **делает невозможными** случайные
inconsistencies. Стоимость — меньше гибкости. Для single-developer проекта
это правильный trade-off.

### 2.4 No light theme

CryoDAQ — **native dark interface**. Светлой темы как полноценного варианта
нет. Решения принимаются как для dark-first продукта, без компромиссов.

**Единственное** исключение: print mode для plot widgets (для скриншотов в
отчёты). Это узкий technical compromise, не alternate theme.

Если когда-нибудь понадобится full light theme — это отдельный большой
проект, не "включить флажок".

---

## 3. Foundation tokens

### 3.1 Цветовая система

#### 3.1.1 Neutral scale — warm stone

12 ступеней. R немного больше B (тёплый). Не cold slate.

```
stone.0    #0a0a0c   pure base, deeper than typical dark themes
stone.50   #0f1014   primary surface (window background)
stone.100  #14151a   raised surface (panels, plot containers)
stone.150  #191b21   elevated surface (cards inside panels)
stone.200  #1f2128   modal/popup base
stone.300  #292c34   subtle borders, separators
stone.400  #3a3e48   hard borders, disabled outlines
stone.500  #555a66   disabled text, very muted icons
stone.600  #767c88   muted text (units, hints, secondary labels)
stone.700  #9aa0ac   secondary text (body, descriptions)
stone.800  #c8ccd4   primary text (values, labels in cards)
stone.900  #e8eaf0   high-contrast text (large numbers, headlines)
stone.1000 #f7f8fb   pure highlight (rare, hover-on-text only)
```

**WCAG contrast** против `stone.50` (#0f1014):
- `stone.900` → ~14.8:1 (AAA)
- `stone.800` → ~10.6:1 (AAA)
- `stone.700` → ~6.9:1 (AAA)
- `stone.600` → ~4.7:1 (AA минимум для body)
- `stone.500` → ~3.4:1 (AA для крупного текста — disabled only)

Почему 12 ступеней (не 8, не 16): 12 даёт достаточную гранулярность для
надёжной elevation hierarchy (5 surface levels) + 5 text levels + 2 border
levels без overlap. 8 ступеней не хватает на это, 16 создаёт неразличимые
соседние ступени.

Тёплый оттенок проявляется через R+1..R+2 относительно G и B. Едва заметно,
но в сочетании с cool indigo accent создаёт характерный температурный
контраст.

#### 3.1.2 UI accent — cool indigo

**Один** primary accent. Используется для: focus rings, selected states,
primary action buttons (только primary), active tab indicator, progress bars,
link-like elements.

```
accent.300   #6470d9   muted indigo (idle, inactive states)
accent.400   #7c8cff   primary indigo — DEFAULT
accent.500   #95a3ff   bright indigo (hover, active press)
accent.600   #b8c0ff   pale indigo (focus ring glow at 30% opacity)
```

**Почему cool indigo на warm base, а не warm amber:**

1. **Температурный контраст сильнее как statement.** Warm + warm = monotone,
   warm + cool = характерная identity.
2. **Категорически не конфликтует с warning/fault.** Warning orange и fault
   red — warm spectrum. Indigo — cool spectrum. Оператор не может спутать
   accent с alarm состоянием даже периферийным зрением.
3. **Linear и Raycast используют cool accents.** Наш главный референс для
   typography (Linear) и hierarchy (Raycast) оба cool. Мы совпадаем с ними
   **концептуально** (cool accent) оставаясь **отличительными** (warm base).
4. **Cool accent легче для глаз в длинных сессиях.** Warm accents более
   активные и утомляют на многочасовых ночных сменах.

WCAG: `accent.400` на `stone.50` → ~6.8:1 (AAA для текста).

#### 3.1.3 Semantic palette — статусы

Используются **только** для индикации состояний. Никогда для UI chrome.
Никогда как декорация. Никогда для группировки.

```
status.fault     #ff3344   red       серьёзная авария, требует немедленной реакции
status.warning   #ff9d3f   orange    warning, требует внимания
status.caution   #f5c542   yellow    attention without urgency
status.ok        #4ade80   green     штатно
status.info      #60a5fa   blue      информационный, neutral состояние
status.stale     #6b7280   gray      stale data, неактуально
```

**Семейная организация:**
- **"Плохо"** (warm warning spectrum): fault → warning → caution
- **"Хорошо"** (cool friendly spectrum): ok → info
- **"Stale"** — нейтральный серый

6 distinct semantic states + stale. Это изменение от v0.2 где был ещё
`status.exp` (фиолетовый) для "experiment phase active" — удалён как
over-engineering. Состояние эксперимента — это **свойство процесса**, а не
**свойство канала**, и показывается через dedicated experiment indicator в
header, не через цвет sensor card.

**WCAG contrast** против `stone.50`:
- `status.fault` → ~5.5:1 (AA)
- `status.warning` → ~8.4:1 (AAA)
- `status.caution` → ~11.1:1 (AAA)
- `status.ok` → ~9.8:1 (AAA)
- `status.info` → ~7.6:1 (AAA)

**Правила применения:**
- **Один статус — один цвет.** Не "fault может быть тёмно-красный или
  ярко-красный в зависимости от контекста". Один token → один hex. Везде.
- **Semantic colors не смешиваются с accent.** Кнопка "Acknowledge alarm"
  использует `accent.indigo`, **не** `status.fault`, даже если она про
  fault. Цвет кнопки = цвет действия (primary), цвет статуса = цвет
  состояния (semantic).
- **Semantic colors применяются точечно**, не заливают карточки. Sensor card
  в fault state имеет pulsing background + red value text, не полностью
  красная карточка. Полная заливка зарезервирована для модальных alarm
  dialogs.
- **Semantic colors никогда не применяются как UI chrome.** Никаких цветных
  borders вокруг компонентов "для красоты" (текущий anti-pattern в
  Аналитика tab — оранжевая рамка вокруг R_thermal card).

#### 3.1.4 Plot line palette

Отдельная от UI и semantic palette. Критерии: mutual distinguishability (8
линий на одном графике), контраст к plot background, различимость для
оператора с color vision deficiency (см. секцию 8).

8 цветов в фиксированном порядке. Многоканальный график берёт
`plot.line[i % 8]`.

```
plot.line.0  #6cc4f5   sky blue
plot.line.1  #c490e0   soft violet
plot.line.2  #80deea   pale teal
plot.line.3  #a3e635   lime
plot.line.4  #ff8a80   pale coral
plot.line.5  #ffd866   pale yellow
plot.line.6  #f48fb1   pale pink
plot.line.7  #b8c0ff   pale indigo
```

**Не пересекается с status palette.** Plot lines имеют **низкую saturation**
относительно semantic colors, что визуально их разводит. Saturation difference
— один из самых надёжных способов различения в Qt widgets где мы не можем
менять shape легко.

**Не пересекается с accent.** `plot.line.7` pale indigo близок к accent, но
это **pale** версия, а accent — saturated. Они не путаются при сравнении.

**Проверено на color blindness compatibility:** palette разработана так
чтобы deuteranomaly (самая частая CVD, ~5% мужчин) пользователь мог
различить все 8 линий через combination of hue и saturation. Формальная
проверка симулятором — задача Phase UI-1 Block 3 (smoke test на реальном
железе может выявить проблемы которые теория не показала).

#### 3.1.5 Surface tokens (semantic)

```
surface.window      = stone.50    main window background
surface.panel       = stone.100   tab content panels
surface.card        = stone.150   sensor cards, info tiles inside panels
surface.elevated    = stone.200   modals, popups, dropdowns
surface.sunken      = stone.0     plot containers, "deep" recess
surface.overlay     = stone.0 @ 60%   modal backdrop scrim
```

#### 3.1.6 Border tokens

```
border.subtle       = stone.300    decorative dividers, card outlines
border.strong       = stone.400    actionable borders (input fields, buttons)
border.focus        = accent.400   focus ring (1.5px outset)
```

Обрати внимание: `border.fault` удалён относительно v0.2. Fault state в
sensor card не использует цветной border — вместо этого используется pulse
background + red value text (см. 5.1). Один visual channel primary, один
secondary, без избыточных три канала.

#### 3.1.7 Text tokens

```
text.primary        = stone.900    main labels, large numbers
text.secondary      = stone.800    body text
text.muted          = stone.700    units (К, mbar), descriptions
text.disabled       = stone.500    disabled controls, "no data"
text.inverse        = stone.50     text on accent buttons
text.fault          = status.fault fault values (semantic application)
text.ok             = status.ok    confirmed-safe values
text.info           = status.info  informational values
text.accent         = accent.400   links, primary action labels
```

### 3.2 Типографика

#### 3.2.1 Шрифты

**Два шрифта в системе. Никаких исключений.**

- **Inter** (UI sans, OFL, bundled). Весь UI текст: лейблы, кнопки, табы,
  диалоги, сообщения. Inter разработан специально для интерфейсов, его
  читаемость на малых размерах в dark themes — лучшая среди open-source
  sans-serif. Linear использует Inter.

- **JetBrains Mono** (numeric monospace, OFL, bundled). Используется
  **исключительно** для числовых значений: показания датчиков, время,
  частоты, токи, температуры. Имеет идеально tabular figures — критично
  чтобы цифры не "прыгали" по ширине при обновлении. Лучшая бесплатная
  альтернатива SF Mono.

Почему bundled а не system fonts: Mac dev и Ubuntu лаб PC имеют гигантски
разные system fonts (SF Pro vs Ubuntu/Cantarell). Это сломало бы design
language feel при deployment. +5MB bundle — negligible для лабораторного
железа.

#### 3.2.2 Type scale

6 ступеней modular scale ratio 1.2 ("minor third"). Каждая ступень имеет
фиксированный размер, line-height, weight.

Конкретные pixel values `[calibrate on lab PC]` — это первые разумные
defaults, финальная калибровка на реальном мониторе:

```
display    32px / 40px / 600    hero readouts (T11, T12)
title      22px / 28px / 600    tab titles, modal headers
heading    18px / 24px / 600    panel headers, group headers
body       14px / 20px / 400    primary UI text, labels, buttons
label      12px / 16px / 500    units, hints, metadata, tab labels
mono.value 15px / 20px / 500    JetBrains Mono — sensor values
mono.small 12px / 16px / 500    JetBrains Mono — timestamps, log entries
```

Ratio: 32 → 22 → 18 → 14 → 12 ≈ ×0.78. Математически disciplined.

**Правила применения:**

- `display` — только для главных числовых значений. T11 и T12 (certified)
  в `display`. Остальные каналы — в `mono.value`.
- `title` — заголовок tab + заголовок modal. **Не** для заголовков карточек.
- `heading` — group headers ("КРИОСТАТ", "КОМПРЕССОР"), section headers,
  panel titles.
- `body` — **всё** UI текст по умолчанию. Кнопки, лейблы, описания.
- `label` — единицы измерения, временные метки, вторичная инфа, tab labels.
- `mono.value` — самый часто видимый mono. Все живые числа в карточках
  датчиков, в Source панели, в vacuum readout.
- `mono.small` — таймстампы в логах, alarm history, archive list.

**Никогда не делаем:**
- Bold body для эмфазиса (используем `text.primary` вместо `text.secondary`)
- Italic (не существует в pro tools)
- Letter-spacing > 0 (кроме group headers где +0.5px намеренно)
- Произвольные размеры вне scale

#### 3.2.3 Tabular figures обязательны

JetBrains Mono — по умолчанию. Inter — опционально через OpenType feature
`tnum`, включать явно через `font.setFeature("tnum", 1)`. Без этого числа в
Inter "прыгают" при обновлении. **Требование, не опция.**

### 3.3 Spacing scale

4px base unit, 6 ступеней. Конкретные значения `[calibrate on lab PC]`:

```
space.0   0px     no gap
space.1   4px     intra-element (icon ↔ label)
space.2   8px     tight (label ↔ value, inside small components)
space.3   12px    cosy (within a card, between related rows)
space.4   16px    standard (between cards, between sections)
space.5   24px    section separator within a tab
space.6   32px    major section break, modal padding
```

**Правило:** одна ступень — одно назначение. Если 8px не работает — переходи
на 12px, не на 9px.

Почему 6 ступеней (не 8 из v0.1): в реальном использовании последние 2
ступени (48px, 64px) почти не нужны. Проще система — меньше опций для
неправильного выбора.

### 3.4 Radius scale

3 ступени.

```
radius.sm   3px    inputs, small buttons, status pills
radius.md   5px    cards, panels, primary buttons
radius.lg   6px    modals, large containers
```

Никаких circular elements кроме status indicator dots. Никаких pill buttons
(radius = height / 2). Никаких скруглений >6px — это выглядит
consumer-friendly, не instrumental.

### 3.5 Elevation (без shadows)

Qt рендерит box-shadows плохо (через QGraphicsDropShadowEffect — медленно и
blurry). Кроме того, shadows в pro tool выглядят как Bootstrap. Elevation
выражается через **четыре механизма**, никогда через shadows:

1. **Background shift.** Карточка чуть светлее панели: `surface.card`
   (#191b21) на `surface.panel` (#14151a). Едва заметно глазом, но создаёт
   сепарацию.
2. **Subtle border.** `border.subtle` (1px, `stone.300`) обводит raised
   элемент.
3. **Top edge highlight.** Для hover/active — top border на 1px светлее
   остального contour. Имитация "света сверху" без shadow.
4. **Bottom edge separator.** Для разделения секций — 1px `stone.200` снизу.

Иерархия elevation:
```
window           flat (stone.50)
panel            background shift only (stone.100)
card             background shift + subtle border (stone.150 + stone.300 1px)
card hover       + top edge highlight
card focus       border.focus full ring (accent.400 1.5px)
modal            elevated bg + border + scrim backdrop
```

---

## 4. Plot system

Графики — **первоклассный гражданин**. Значительная часть времени оператор
смотрит именно на них. Это требует отдельной дисциплины.

### 4.1 Tufte-инспирированные принципы

- **Maximize data-ink.** Минимум non-data ink. Нет border вокруг plot area.
  Нет titlebar над графиком.
- **Erase to reveal.** Сетка серая, полупрозрачная, **за** линиями данных.
  Линии данных всегда поверх сетки.
- **Avoid chartjunk.** Никаких 3D, никаких градиентных fills, никаких drop
  shadows на маркерах.
- **Density of information.** На Overview 8 каналов одновременно на одном
  графике — это норма. Тонкие линии, без markers по умолчанию.

### 4.2 Plot tokens

```
plot.bg              = stone.0 (#0a0a0c)         deeper than panel
plot.fg              = stone.700                  axes, ticks
plot.grid            = stone.300 @ 35% opacity
plot.label           = stone.700                  axis labels (label size)
plot.tick            = stone.800                  tick numbers (mono.small)
plot.line.width      = 1.5px (default)
plot.line.width.hi   = 2.5px (selected/highlighted line)
plot.crosshair       = stone.700 @ 60% opacity
plot.region.fault    = status.fault @ 12% opacity (alarm region overlay)
plot.region.warn     = status.warning @ 10% opacity
```

### 4.3 Plot anatomy

```
┌─────────────────────────────────────────────┐
│ surface.sunken (#0a0a0c) — plot container   │
│  - 4px padding from edges                   │
│  - no border                                │
│                                             │
│  axis labels: label / text.muted            │
│  tick labels: mono.small / text.secondary   │
│  gridlines: stone.300 @ 35% opacity, 1px    │
│  data lines: plot.line.* @ 1.5px            │
│  legend: top-right inset, no background     │
│                                             │
└─────────────────────────────────────────────┘
```

### 4.4 Plot states

#### Empty state

```
┌─────────────────────────────────────────────┐
│                                             │
│           [icon: chart-line 32px,           │
│            stroke stone.500]                │
│                                             │
│             Нет данных                      │  ← body / text.muted
│                                             │
│      Запустите эксперимент чтобы            │  ← label / text.disabled
│         начать сбор данных                  │
│                                             │
└─────────────────────────────────────────────┘
```

Vertically + horizontally centered. Конкретная инструкция, не "Loading...".

#### Stale state

Линии графика становятся `status.stale`. Маленький pill `STALE 12s ago` в
top-right plot area, размер `label`, `border.subtle`, `text.muted`. Не
блокирует данные — оператор всё ещё видит последние значения.

#### Fault region overlay

Когда канал входит в fault state, на графике появляется полупрозрачная
вертикальная заливка (`plot.region.fault`) от момента входа в fault до
текущего момента (или до acknowledge). Это **не** меняет цвет линии — линия
остаётся своего обычного цвета. Заливка живёт **под** линией.

### 4.5 Multi-line discipline

**Максимум 8 линий на одном plot widget.** Если каналов больше — либо
группировать, либо два plot widget стопкой, либо selectable visibility.

Легенда всегда top-right, inset, без background fill. Названия каналов в
`label / text.secondary`, цветные dots слева от названия (4px diameter).

### 4.6 Plot toolbar

Toolbar **внизу** plot widget, не сверху. Кнопки tertiary style (text-only,
размер `label`, цвет `text.muted`, hover → `text.secondary`). Расположение
справа.

```
                                          Lin Y · log Y · PNG · CSV
                                          all in label / text.muted
                                          separator: middle dot
```

Никаких borders на этих кнопках. Никакого background. Просто текст.

### 4.7 Print mode (единственное light theme исключение)

Для `overview_panel.py` print mode (скриншоты в отчёты):
- `plot.bg` = `#ffffff`
- `plot.fg` = `#1a1a1a`
- `plot.grid` = `#dddddd` @ 60% opacity
- `plot.line.*` остаются те же (достаточно saturated для белого фона)

Это **единственное** место в системе с light theme.

---

## 5. Component patterns

### 5.1 Sensor Card

Самый часто встречающийся компонент. На Overview tab их 24 одновременно.

#### Anatomy

```
┌─────────────────────────────────────┐  ← surface.card, border.subtle, radius.md
│ space.3 padding inside              │
│                                     │
│ Т11 Теплообменник 1                 │  ← body / text.secondary
│ space.2 gap                         │
│                                     │
│  77.42  К                           │  ← mono.value text.primary
│                                     │     + label text.muted
│ space.2 gap                         │
│                                     │
│ ▼ −0.3 К/мин   12s ago              │  ← label
│   ↑text.ok        ↑text.disabled    │
│                                     │
└─────────────────────────────────────┘
```

**Минимальная ширина:** `[calibrate]` ~140px.
**Высота:** content-driven, ~`[calibrate]` ~110px типично.

#### States (упрощены относительно v0.2)

Принцип: **один primary visual channel + один secondary** на состояние.
Никаких три канала на одно состояние.

- **Normal:** `surface.card` background, `border.subtle`.
- **Hover:** top edge highlight 1px (subtle). No other change.
- **Selected** (clicked, opens detail): `border.focus` full ring (accent.400
  1.5px).
- **Stale** (no update >5 sec):
  - Primary: value text → `text.disabled`
  - Secondary: "12s ago" → "STALE 47s ago"
- **Caution** (channel in caution range):
  - Primary: value text → `text.caution`
  - Secondary: trend line → `text.caution`
- **Warning** (channel in warning range):
  - Primary: value text → `text.warning`
  - Secondary: trend line → `text.warning`
- **Fault** (channel in fault range):
  - Primary: **pulse animation** — card background animates between
    `surface.card` and `status.fault @ 5%`, cycle 1.5s sine (see D-013)
  - Secondary: value text → `text.fault`
  - **No** left edge, **no** border change — избыточно с pulse
- **Disabled** (channel hidden in config): card not rendered.

#### Что **не** делает sensor card

- Не имеет min/max range visualization
- Не имеет sparkline (Phase UI-2 enhancement)
- Не имеет inline action buttons (clicking opens detail panel)
- Не имеет loading state

### 5.2 Big Number Readout (Hero)

Используется только для T11, T12 (certified). На Overview — два hero
вверху страницы.

```
┌──────────────────────────────────────┐  ← surface.card, radius.md, border.subtle
│ space.5 padding                      │
│                                      │
│ Т11 — Теплообменник 1                │  ← heading text.secondary
│ space.4 gap                          │
│                                      │
│      77.428                          │  ← display mono text.primary
│       К                              │  ← title mono text.muted
│                                      │
│ space.3 gap                          │
│ ▼ −0.31 К/мин                        │  ← body 500 text.ok
│ ±0.005 К  •  калибр. 12.03           │  ← label text.muted
│                                      │
└──────────────────────────────────────┘
```

**Размер:** `[calibrate]` — на Overview два hero делят ширину пополам,
минимальная ширина одного ~400px, высота ~180px.

### 5.3 Status Pill (упрощён)

Компактный indicator состояния. Для safety state, instrument connection,
experiment phase, alarm levels.

```
┌──────────────────┐
│ ● RUNNING        │   ← label / 600 weight, padding space.1 / space.2
└──────────────────┘     radius.sm
   ↑ 6px circle, status color
```

**Упрощение относительно v0.2:** два visual channel вместо трёх.

States и visual channels:

```
SAFE_OFF       dot stone.500    + text.muted        (no bg tint)
READY          dot status.info  + text.secondary    (no bg tint)
RUN_PERMITTED  dot status.ok    + text.primary      (no bg tint)
RUNNING        dot status.ok    + text.ok           (no bg tint)
WARNING        dot status.warn  + text.warning      (no bg tint)
FAULT_LATCHED  dot status.fault + text.fault        (no bg tint)
```

Background tint убран — pill маленький, dot + text color достаточно для
всех состояний. Меньше visual complexity.

**Размер фиксирован.** Pill не растягивается шире чем content + 2× space.2.

### 5.4 Action Button hierarchy

Три уровня. **Только три.**

#### Primary

Главное действие в форме / диалоге / панели. **Один primary на view.**

```
┌─────────────────────┐
│   Запустить         │  ← body 600, text.inverse on accent.400
└─────────────────────┘     padding space.2 / space.4, radius.md
```

`accent.400` background, `text.inverse` text. Hover: `accent.500`. Disabled:
`stone.300` bg, `text.disabled` text.

#### Secondary

Альтернативное действие. **Может быть несколько.**

```
┌─────────────────────┐
│   Отмена            │  ← body 500, text.secondary
└─────────────────────┘     transparent bg, border.strong, radius.md
```

Transparent background, `border.strong` 1px. Hover: `surface.elevated`
background, `text.primary`.

#### Tertiary (text-only)

Низкоприоритетные действия. Links, plot toolbar, "show more".

```
   Подробнее →           ← body 500, text.accent
```

Без background, без border. Только текст в `text.accent`. Hover: underline.

#### Destructive variant

Для irreversible critical actions (emergency off, permanent delete):

```
┌─────────────────────┐
│   АВАР. ОТКЛ        │  ← body 700, text.inverse on status.fault
└─────────────────────┘     padding space.2 / space.4, radius.md
```

**Используется** только для irreversible critical actions. Не для "Stop"
или "Cancel" — это secondary.

### 5.5 Header bar (global)

Единый header bar фиксированной высоты на самом верху окна. Высота
`[calibrate]` ~56px.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ● Engine: работает    [tabs: Обзор | Эксп | ...]      [Web] [Restart]  │
│ ↑ space.4 left       ↑ centered                    ↑ tertiary ↑ secondary│
└─────────────────────────────────────────────────────────────────────────┘
  surface.panel background, border.subtle bottom 1px
```

Содержимое:
- **Engine indicator** слева (status pill style, label size)
- **Tabs** центр (см. 5.6)
- **Global actions** справа

Settings, preferences, и другие infrequent items **не** живут в header —
они в Приборы tab.

### 5.6 Tab bar

10 tabs с иконками + текст.

```
┌──────────┬──────────────┬─────────────┬──────────┬─...
│ ◰  Обзор │ 🜔 Эксп.    │ ⚡ Источник │ 🛎 Алармы│
│   ▔▔▔    │              │             │          │
└──────────┴──────────────┴─────────────┴──────────┴─...
```

- Иконки 14px, monochrome stroke (Lucide-style SVG, bundled в qresources)
- Inactive: icon `text.muted`, label `text.muted`
- Hover: icon `text.secondary`, label `text.secondary`
- Active: icon `accent.400`, label `text.primary`, **bottom underline 2px
  `accent.400`**
- Padding: `space.2` vertical, `space.3` horizontal
- Font: `label / 500`
- Background: transparent

Иконки per tab:
- **Обзор** — `grid` (3×3 dots)
- **Эксперимент** — `flask`
- **Источник мощности** — `zap` (lightning)
- **Аналитика** — `trending-up`
- **Теплопроводность** — `thermometer`
- **Алармы** — `bell`
- **Служебный лог** — `file-text`
- **Архив** — `archive`
- **Калибровка** — `sliders`
- **Приборы** — `cpu`

### 5.7 Status bar (bottom)

Bottom bar высотой `[calibrate]` ~32px. Global system status информация.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ● SAFE_OFF │ Аптайм 02:34:17 │ 0 алармов │ 730 ГБ │ Подключено │ 12 изм/с│
└─────────────────────────────────────────────────────────────────────────┘
  surface.panel, border.subtle top 1px
```

Содержимое:
- **Safety state pill** (с цветным dot)
- **Аптайм** (mono.small + label, muted)
- **Алармов:** N (если N > 0 → text.warning, иначе text.muted)
- **Свободно:** N ГБ (text.muted, → text.warning < 50GB, → text.fault < 10GB)
- **Подключено / Нет связи** (status pill)
- **Измерений/сек** (mono.small, text.muted)

### 5.8 Modal Dialog

```
                ┌────────────────────────────────────┐
                │ space.6 padding                    │
                │                                    │
                │ Подтверждение остановки            │  ← title
                │ space.4 gap                        │
                │                                    │
                │ Источник питания будет обесточен.  │  ← body, text.secondary
                │ Эксперимент перейдёт в фазу        │
                │ остановки. Это действие нельзя     │
                │ отменить.                          │
                │                                    │
                │ space.5 gap                        │
                │                                    │
                │             [Отмена]  [Остановить] │  ← secondary, primary
                │                                    │
                └────────────────────────────────────┘
                  surface.elevated, border.subtle, radius.lg
                  scrim: surface.overlay (stone.0 @ 60%)
                  min-width 400px, max-width 600px
```

**Кнопки внизу справа.** Primary справа, secondary слева (Linux convention,
лаб PC на Ubuntu).

Никаких "OK/Cancel" — всегда конкретные глаголы ("Остановить", "Удалить",
"Применить").

### 5.9 Input Field

```
Имя эксперимента                              ← label / text.muted, space.1 below
┌───────────────────────────────────────┐
│ cooldown_2026_04_09_run3              │      ← body / text.primary
└───────────────────────────────────────┘     surface.sunken bg, border.strong, radius.sm
                                              padding space.2 / space.3, height [calibrate] ~32px
```

States:
- **Idle:** `surface.sunken` bg, `border.strong`, `text.primary`
- **Focus:** `border.focus` 1.5px, no background change
- **Disabled:** `surface.panel` bg, `text.disabled`, `border.subtle`
- **Error:** border = `status.fault`, error message under field в
  `label / text.fault`

**Никаких** placeholders как замены лейблу.

### 5.10 Empty state (универсальный)

```
┌─────────────────────────────────────────────┐
│                                             │
│         [icon 32px monochrome,              │
│          stroke text.disabled]              │
│              space.3                        │
│           Нет активных алармов              │  ← heading / text.secondary
│              space.2                        │
│         Все каналы в норме                  │  ← body / text.muted
│              space.4                        │
│       [Запустить эксперимент →]             │  ← tertiary action (optional)
│                                             │
└─────────────────────────────────────────────┘
```

Vertically + horizontally centered. Icon 32px monochrome stroke
(Lucide-style).

Структура:
1. Icon (mandatory)
2. heading (mandatory) — что отсутствует
3. body (mandatory) — почему отсутствует или что значит
4. tertiary action (optional) — link куда пойти если оператор хочет это
   изменить

**Никаких primary buttons** в empty state — primary action принадлежит
основному flow.

### 5.11 Toast notification

Top-center, под header bar.

```
                ┌──────────────────────────────┐
                │ ✓ Эксперимент запущен        │  ← body / text.primary
                │ run3_2026_04_09 — 14:32:17   │  ← label / text.muted
                └──────────────────────────────┘
                  surface.elevated, border.subtle, radius.md
                  auto-dismiss 4s, max 3 stacked
```

Types:
- **Success**: leading icon ✓ в `status.ok`
- **Info**: leading icon · в `status.info`
- **Warning**: leading icon ! в `status.warning`
- **Error**: leading icon × в `status.fault`, **doesn't auto-dismiss**,
  has manual close button

### 5.12 Alarm row

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ●  14:32:17  Т7 Детектор          315.2 K > 310 K        [✓ ACK]       │
└─────────────────────────────────────────────────────────────────────────┘
 ↑6px  ↑mono.small ↑body            ↑mono.value           ↑label tertiary
```

- Высота `[calibrate]` ~32px
- Padding: `space.2` vertical, `space.3` horizontal
- Border: только нижний `border.subtle` (separator)
- Hover: top edge highlight (subtle)
- Selected: `border.focus` левая граница 2px

States:
- **Active**: dot `status.fault`, value `text.fault`, bg `status.fault @ 6%`
- **Acknowledged**: dot `status.warning`, value `text.primary`, `[✓ ACK]`
  label `text.ok`
- **Resolved**: dot `status.ok`, value `text.muted`, row fully muted
- **Historical**: dot `text.disabled`, all `text.muted`

### 5.13 Group header

```
КРИОСТАТ                                                           8 каналов
─────────────────────────────────────────────────────────────────────
↑ heading + uppercase + letter-spacing +0.5px, text.muted       ↑ label text.disabled
```

- `heading` size в **uppercase** с letter-spacing +0.5px (**единственное**
  место в системе где используется uppercase + letter-spacing)
- `text.muted` (не primary — не конкурирует с contents)
- `space.5` top padding, `space.3` bottom padding
- 1px `border.subtle` bottom
- Right side: `label / text.disabled` count metadata
- Clickable: collapse/expand (Phase UI-2 feature)

### 5.14 Source channel indicator (V/I/R/P)

В Source панели есть color coding для четырёх physical quantities. Это
**универсальная конвенция** в электронике.

```
quantity.voltage     #6cc4f5   sky blue (= plot.line.0)
quantity.current     #4ade80   green (= status.ok)
quantity.resistance  #ff9d3f   warm orange (= status.warning)
quantity.power       #ff5252   red-coral (≠ status.fault, чуть более warm)
```

**Переиспользование цветов:** voltage, current, resistance пересекаются с
plot/status palette. Это **единственное** место в UI где цвета пересекаются.

Trade-off принят потому что:
1. Convention universal в электронике (V=blue, I=green, R=orange, P=red).
   Оператор узнаёт мгновенно.
2. Source panel — изолированный контекст без визуальной близости с status
   indicators в других частях UI.
3. Альтернативные цвета сломали бы общие знания оператора от мультиметров
   и SMU.

Применяются **только** в Source panel и Аналитика как value text color или
dot indicator. Не как borders или bg fills (это было anti-pattern в v0.2
current implementation).

---

## 6. Interaction system

### 6.1 Input methods и priorities

CryoDAQ — pro tool. Оператор часто работает **не мышью**, особенно во время
активного эксперимента когда руки на приборах или записывают в лабораторный
журнал. Keyboard — first-class interaction channel, не afterthought.

Priority:
1. **Keyboard** — основной метод для power users, всё доступно через
   shortcuts
2. **Mouse** — для browsing, selection, drag where applicable
3. **Touch** — не поддерживается (лабораторные мониторы не тач)

### 6.2 Keyboard shortcuts convention

CryoDAQ уже имеет существующие shortcuts в `main_window.py` (Ctrl+L/E/1-9,
F5, Ctrl+Shift+X) — эти shortcuts **сохраняются** и расширяются.

#### Global shortcuts

```
F1              Открыть help / shortcuts reference
F5              Refresh / re-poll instruments
F11             Toggle fullscreen
Ctrl+1 .. Ctrl+0  Switch to tab 1..10
Ctrl+Shift+X    Emergency off (с confirmation modal)
Ctrl+L          Operator log entry (quick note)
Ctrl+E          Start/pause experiment
Ctrl+,          Open preferences (if exists)
Esc             Close modal, deselect, cancel
```

#### Navigation shortcuts в Overview

```
Arrow keys      Navigate between sensor cards
Enter           Open selected card details
/               Focus sensor search/filter (if exists)
g g             Go to top (vim-style, optional Phase UI-3)
```

#### Experiment tab shortcuts

```
Ctrl+N          New experiment
Ctrl+S          Save experiment
Ctrl+Enter      Submit form
```

#### Discoverability

Все shortcuts должны быть **discoverable**:
- Menu items показывают свой shortcut справа
- Tooltip на кнопке включает shortcut в скобках
- `F1` открывает cheat sheet modal со всеми shortcuts

**Никаких** hidden shortcuts которых нельзя найти через UI.

### 6.3 Focus management

Focus ring — `border.focus` (accent.400 1.5px outset). Виден **всегда** на
keyboard-focused элементе. Никогда не скрывается через `outline: none`.

Tab order:
- **Logical** — сверху вниз, слева направо в каждой панели
- **Skippable** — можно пропускать sections через keyboard
- **Predictable** — Tab всегда идёт "вперёд", Shift+Tab "назад", никаких
  сюрпризов

Focus trap в модальных диалогах: Tab и Shift+Tab циклируют только внутри
modal, не уходят в background.

### 6.4 Esc behavior

`Esc` всегда имеет значение:
- В modal: закрывает modal (как clicking "Отмена")
- В dropdown: закрывает dropdown
- В active input field: deselects (blur)
- В sensor detail panel: закрывает panel
- Ничего открытого: no-op (не крашит, не switches tab)

### 6.5 Click targets

Минимальный click target — `[calibrate]` ~32px × 32px для плотного UI,
~40px × 40px для comfortable. Это WCAG 2.2 recommendation.

Между кликабельными элементами — минимум `space.1` (4px) gap чтобы не
случались mis-clicks.

Tab bar buttons, sensor cards, alarm rows — все соответствуют минимуму.

### 6.6 Drag and drop

**Минимально используется.** Только для:
- Plot pan/zoom (встроено в pyqtgraph)
- Reordering experiment notes list (Phase UI-3, optional)

Никаких drag-and-drop как **единственного** способа сделать что-то. Всё
что можно drag — можно также сделать через меню или context action.

---

## 7. Motion и feedback

### 7.1 Что анимируется

| Что | Длительность | Easing |
|---|---|---|
| Tab switch | 0ms | none |
| Modal open | 120ms | ease-out |
| Modal close | 80ms | ease-in |
| Sensor card hover | 80ms | linear |
| Focus ring appear | 100ms | ease-out |
| Plot data update | 0ms | none — данные не "анимируются" |
| Sensor card non-fault state change | 0ms | none |
| Progress bar fill | 200ms | linear |
| Panel collapse/expand | 150ms | ease-in-out |
| Toast appear | 120ms | ease-out |
| Toast dismiss | 80ms | ease-in |
| **Fault pulse (D-013)** | 1500ms cycle | sine |

**Total motion budget per single interaction: 200ms.** Fault pulse —
исключение (см. 7.2).

### 7.2 Fault pulse — намеренное исключение

**Единственное** место в системе с idle repeating animation.

Когда канал в fault state:
- Sensor card background пульсирует между `surface.card` и
  `status.fault @ 5%`
- Cycle: 1.5 sec (0.75 in, 0.75 out)
- Easing: sine wave (smooth, не дёрганый)

**Обоснование**: ночная смена, периферийное зрение. Static red indicator на
одной из 24 sensor cards может быть пропущен. Slow gentle pulse привлекает
peripheral vision без visual agressiveness.

Нарушает общее правило "no idle animation" — это **единственное**
разрешённое исключение, записанное в D-013.

**Важно**: pulse применяется **только** в `status.fault` состоянии, не в
warning или caution. Это резервирует самый агрессивный visual channel для
самого серьёзного состояния.

### 7.3 Feedback channels

В порядке предпочтения:
1. **Visual state change** в самом элементе (button hover, focus ring)
2. **Result appears immediately** в связанном элементе
3. **Toast notification** top-center (для асинхронных результатов)
4. **Modal dialog** для критичных подтверждений и blocking errors
5. **Лог в служебном логе** — всегда, для всего (audit trail, не feedback)

**Никогда:**
- Sound feedback (лаборатория имеет реальные beeps на железе)
- Browser-style `alert()` для рутинных событий
- "Loading..." spinners как единственный feedback

### 7.4 No indeterminate progress

Никаких indeterminate spinners. Если процесс indeterminate — показываем
"Обработка..." текстом в `text.muted`, без visual element. Spinner создаёт
ложное ощущение прогресса.

Определённый прогресс — progress bar с конкретными числами (не только %).
"50.4 К → 4.2 К • ETA 2ч 14мин" + `[▓▓▓▓▓░░░░░]` — не только `62%`.

---

## 8. Accessibility и color vision

### 8.1 Контраст

Все контрасты проверены по WCAG 2.2:
- Body text (`stone.700` / `text.muted`) на background (`stone.50`) →
  ~6.9:1 (AAA)
- Large text (`stone.500` / disabled) на background → ~3.4:1 (AA для large)
- Semantic colors на background → все AA+ (большинство AAA)

**Правило**: новые tokens добавляются только с проверенным contrast.
Добавление token без contrast check — нарушение дисциплины.

### 8.2 Color vision deficiency

~5% мужчин имеют deuteranomaly (частичный red-green colorblindness),
~2% — другие формы. Для лаборатории на 5-10 человек это **очень вероятно**
хотя бы один оператор с CVD.

**Правило**: критичные состояния имеют **secondary visual channel** помимо
цвета.

#### Fault / OK как critical pair

Fault и OK — самая частая проблемная пара для CVD. Наши механизмы
различения:

1. **Cvl difference через saturation** — наш fault saturated red
   (#ff3344), наш ok medium green (#4ade80). Saturation различается.
2. **Position difference** — fault в sensor card виден через **pulse
   animation** (D-013), которого нет у ok state. Это motion-based channel
   который работает независимо от цвета.
3. **Text content** — value text в fault всегда читаем в context
   ("315.2 K > 310 K" — сам текст содержит информацию "превышение")
4. **Size / position difference для status pills** — не реализован в v0.3,
   отложен до UI-2

#### Semantic icons для statuses (UI-2 enhancement)

В Phase UI-2 добавить shape-based icons рядом с status dots:
- Fault = triangle с `!`
- Warning = diamond с `!`
- OK = circle (filled)
- Info = circle с `i`
- Caution = circle с `!`
- Stale = circle (outline)

Это даёт **shape channel** в дополнение к color channel. Deuteranomaly
оператор видит shape даже когда путает красный/зелёный.

**Не в Phase UI-1** потому что UI-1 не создаёт новые визуальные компоненты,
только tokens и cleanup. Phase UI-2 отвечает за component implementation.

### 8.3 Screen reader support

Не первостепенная задача (никто в лаборатории не использует), но бесплатные
wins где возможно:
- Все meaningful widgets имеют `accessibleName` и `accessibleDescription`
- Buttons имеют text labels (не только иконки)
- Form fields имеют associated labels
- Status pills имеют text content (не только цвет)

Реализация — Phase UI-2 или UI-3, не Phase UI-1.

### 8.4 Focus visibility

Focus ring всегда виден:
- Accent color `#7c8cff` — AAA contrast против background
- Outset 1.5px — достаточно видим без перекрытия content
- Applied uniformly через все interactive elements

Никогда не скрывается `outline: none` / `QWidget { border: none }` без
замены на другой visible focus indicator.

---

## 9. Anti-patterns

Правила-запреты. Если на ревью появляется один из них — стоп.

### 9.1 Visual anti-patterns

- ❌ **Никаких градиентов** в UI chrome. Только flat fills. Исключение:
  scrim overlay для модальных диалогов.
- ❌ **Никаких box-shadows для elevation.** Qt рендерит плохо, выглядит как
  Bootstrap.
- ❌ **Никаких rounded corners > 6px.** Consumer-friendly, не instrumental.
- ❌ **Никаких glow effects, neon borders, pulsing highlights** (кроме
  D-013 fault pulse).
- ❌ **Никаких background images, textures, patterns.**
- ❌ **Никаких эмодзи** в operator-facing chrome.
- ❌ **Никаких decorative dividers** с custom symbols (·•◇).
- ❌ **Никакого italic text.**
- ❌ **Никакого ALL CAPS в body text** (только group headers с намеренной
  typographic discipline).
- ❌ **Никаких multiple accent colors.** Один accent на всю систему.
- ❌ **Никаких cards in cards in cards** (max 2 levels of containment).
- ❌ **Никакой vertical text orientation.**
- ❌ **Никаких custom scrollbars с цветом отличным от neutral.**

### 9.2 Interaction anti-patterns

- ❌ **Никакого hover-revealed information.** Информация видна или её нет.
- ❌ **Никаких tooltips длиннее 1 строки.**
- ❌ **Никаких modal dialogs с одной кнопкой "OK"** (если не на чем
  кликать, не должно быть modal).
- ❌ **Никаких confirmations на каждое действие** ("Вы точно хотите
  сохранить?" — нет).
- ❌ **Никаких disabled buttons без tooltip** объясняющего почему.
- ❌ **Никакого drag-and-drop как единственного способа** сделать что-то.
- ❌ **Никакого double-click для primary actions.**
- ❌ **Никаких right-click context menus с уникальными командами** (всё в
  context menu должно быть доступно и через primary UI).
- ❌ **Никаких keyboard shortcuts без discoverability.**
- ❌ **Никакого auto-refresh пользовательских inputs** (форма должна
  оставаться где оператор её оставил).

### 9.3 Information anti-patterns

- ❌ **Числа без units.**
- ❌ **Времена без явного формата.**
- ❌ **"Last updated" без указания когда.**
- ❌ **Status text без явного state** ("Готово" — готово что?).
- ❌ **Аббревиатуры без full form** где-то рядом.
- ❌ **Локализация наполовину** (если интерфейс на русском — все строки на
  русском).
- ❌ **Технический жаргон где можно по-русски** ("emergency_off" →
  "Аварийная остановка").
- ❌ **Числа с >5 значащими цифр в живых readouts.**
- ❌ **Скрытый state** (если что-то "включено где-то" — это видно где-то).
- ❌ **Playful copy.** "Упс, что-то пошло не так!" — нет. Технический русский.

### 9.4 Code anti-patterns (для defensive enforcement)

- ❌ **Hardcoded hex values** в widget files. Используй theme tokens.
- ❌ **`setStyleSheet` с inline color literal.**
- ❌ **`setBackground` с literal hex** (используй `theme.PG_BACKGROUND`).
- ❌ **Числовые spacing/padding значения вне `theme.SPACE_*`.**
- ❌ **Любой font name строкой кроме `theme.FONT_UI` / `theme.FONT_MONO`.**
- ❌ **"Magic" pixel values в layouts** (10px, 13px, 17px).
- ❌ **Inline f-strings собирающие QSS из переменных.**
- ❌ **Светлая тема как "tweakable flag".** Нет светлой темы.

### 9.5 Status color anti-patterns

Специфически про применение semantic colors:

- ❌ **Status colors как UI chrome** — оранжевая рамка вокруг "R thermal"
  card в v0.2 current implementation.
- ❌ **Status colors для группировки** — синий для одной группы, зелёный
  для другой. Группировка через headers, не цвет.
- ❌ **Status colors для decorative highlight** — "давайте выделим эту
  карточку зелёным чтобы она выделялась". Нет.
- ❌ **Один статус в двух оттенках** — "fault dark red и fault bright red".
  Один токен, один hex.
- ❌ **Accent используется вместо status** — "кнопка acknowledge fault
  красная". Нет, кнопка amber/indigo accent, fault color принадлежит
  состоянию.

---

## 10. Decision log

Полный журнал принятых решений с обоснованиями. Когда через месяц возникнет
вопрос "почему так?", ответ здесь.

### D-001: Custom bundled fonts (Inter + JetBrains Mono)

**Решение:** bundle Inter и JetBrains Mono в PyInstaller, не system fonts.

**Альтернативы:** system fonts (SF Pro / Ubuntu / Cantarell), Google Fonts
download at runtime.

**Обоснование:** Mac dev и Ubuntu лаб PC имеют визуально гигантски разные
system fonts. Сломает design language feel при deployment. +5MB bundle
acceptable для лабораторного железа. Inter используется Linear (наш
референс). JetBrains Mono — лучшая бесплатная monospace с tabular figures.

**Статус:** approved v0.3.

---

### D-002: Cool indigo accent на warm neutral base

**Решение:** primary accent = `#7c8cff` cool indigo. Neutral = warm stone.

**Альтернативы:** warm amber (v0.2), GitHub blue (current), cyan, teal,
magenta.

**Обоснование:** Tемпературный контраст (warm base + cool accent) даёт
более сильное identity statement чем любая монотонная палитра. Cool accent:
1. Категорически не пересекается с warning/fault orange/red
2. Соответствует Linear / Raycast референсам
3. Меньше утомляет глаз ночью
4. Создаёт "холодный разумный огонёк в тёплой лаборатории" метафору

Изменение с v0.2 warm amber: amber был близок к warning orange по hue и
создавал риск микро-путаницы. Cool indigo исключает эту возможность.

**Trade-off:** отдаление от "instrumental vintage LED" вибы. Принимаем —
это был post-hoc rationalization.

**Статус:** approved v0.3.

---

### D-003: Saturated red для fault, простой `#ff3344`

**Решение:** `status.fault = #ff3344`.

**Альтернативы:** deep red, orange-red, "cold red" (v0.1 theory).

**Обоснование:** Оператор видит "красный = плохо", это работает 100 лет.
"Температурная теория" cold red из v0.1 была over-engineering.
Дополнительный visual channel — pulse animation D-013, не оттенок hue.

**Статус:** approved v0.3.

---

### D-004: Никаких box-shadows для elevation

**Решение:** elevation через background shifts + borders + edge highlights.

**Альтернативы:** Material Design 3 shadows (3-5 levels), neumorphic
dual-shadow.

**Обоснование:** Qt рендерит box-shadows медленно и blurry через
QGraphicsDropShadowEffect. В pro tool выглядит как Bootstrap. Background
shifts работают на любом железе без performance cost.

**Статус:** approved v0.3.

---

### D-005: Plot palette отдельная от semantic palette

**Решение:** plot.line.* не пересекаются с status.*.

**Альтернативы:** переиспользовать status colors как plot lines (v0.1).

**Обоснование:** Когнитивный конфликт реален. Оператор учит "красный =
плохо", видит красную линию на графике T17, момент замешательства. Чистое
разделение лучше. Plot palette имеет низкую saturation, status palette —
высокую saturation — дополнительный visual channel различения.

**Статус:** approved v0.3.

---

### D-006: Один global density mode

**Решение:** один density mode на всё приложение, не per-tab.

**Альтернативы:** per-tab density (v0.1), runtime user-selectable.

**Обоснование:** Linear, Raycast не имеют per-screen density. У них один
rhythm на всё приложение. Per-tab добавляет complexity без real benefit.
Tabs которые "хотят" больше density добиваются через размер cards, не
через density tokens.

**Статус:** approved v0.3.

---

### D-007: Type scale modular ratio 1.2, 6 ступеней

**Решение:** display/title/heading/body/label + mono.value/mono.small.

**Альтернативы:** Material 3 type scale (15 ступеней), 4-step scale.

**Обоснование:** Math discipline (×0.78 каждая ступень). 6 ступеней
покрывают все паттерны без overlap. Больше ступеней = больше шанс выбрать
"не ту" ступень = визуальный chaos.

Почему не 4: 4 ступени недостаточно для different contexts (display vs
body vs label — разные назначения).
Почему не 8+: diminishing returns, увеличение cognitive load при выборе.

**Статус:** approved v0.3.

---

### D-008: No light theme except print mode

**Решение:** CryoDAQ — native dark. Light только для plot print mode.

**Альтернативы:** full light theme support, auto theme switching.

**Обоснование:** Лабораторное окружение dim. Day-mode на dark interface
лучше для глаз чем full light theme. Maintaining двух тем удваивает работу.
Print mode — узкое исключение для конкретного use case.

**Статус:** approved v0.3.

---

### D-009: Иконки в tab bar

**Решение:** Tabs с иконками + текст. 10 tabs, 14px Lucide-style icons.

**Альтернативы:** только текст (v0.1), только иконки.

**Обоснование:** 10 текстовых tabs визуально размываются. Иконки добавляют
landmarks, ускоряют scanning. Lucide-style monochrome stroke = минимальный
визуальный шум.

**Статус:** approved v0.3.

---

### D-010: Status pill размер фиксирован

**Решение:** Status pill не растягивается шире content + 2× space.2.

**Альтернативы:** flexible width pills.

**Обоснование:** Все system statuses короткие (SAFE_OFF, RUNNING,
FAULT_LATCHED). Если статус не влезает — это сигнал что naming плохой, не
что pill должен расти.

**Статус:** approved v0.3.

---

### D-011: T11/T12 hero status

**Решение:** T11 и T12 получают Big Number Readout hero treatment вверху
Overview tab.

**Альтернативы:** обычные sensor cards без специального treatment.

**Обоснование:** T11 и T12 — единственные метрологически certified каналы.
В текущем UI они неотличимы от остальных 22. Hero treatment даёт immediate
visual primacy к самым важным числам. Pressure НЕ становится hero (slow
signal, не нужен real-time hero attention).

**Статус:** approved v0.3.

---

### D-012: Sensor cards grouped by channels.yaml groups

**Решение:** Group headers КРИОСТАТ / КОМПРЕССОР / ОПТИКА / РЕЗЕРВ в
Overview.

**Альтернативы:** flat 6×4 grid (current implementation).

**Обоснование:** Flat grid не передаёт структуру установки. Grouping
позволяет мгновенно локализовать "что-то не так с компрессором". Pattern
доказан в Калибровка tab — применяем в Overview.

**Статус:** approved v0.3.

---

### D-013: Fault pulse animation — намеренное исключение

**Решение:** sensor card в fault state пульсирует background между
`surface.card` и `status.fault @ 5%`, cycle 1.5s, sine easing.

**Альтернативы:** static red indicator, blinking (harsh), color-only без
motion.

**Обоснование:** Безопасность критична. Ночная смена, периферийное зрение,
24 sensor cards — static red может быть пропущен. Slow gentle pulse
привлекает peripheral vision без визуальной агрессии.

**Нарушает** anti-pattern "никаких idle pulsing" — **единственное**
разрешённое исключение. Применяется только к fault (не warning/caution).

**Статус:** approved v0.3.

---

### D-014: Quantity color coding в Source переиспользует цвета

**Решение:** V/I/R/P в Source panel переиспользуют plot/status colors.
Единственное место в UI где цвета пересекаются.

**Альтернативы:** уникальные quantity colors не пересекающиеся с другими
palette.

**Обоснование:** Universal convention в электронике (V=blue, I=green,
R=orange, P=red). Source panel — изолированный контекст. Альтернативные
цвета сломали бы знания оператора от мультиметров и SMU. Применяются как
value text color или dot indicator, не как borders — что изолирует их от
других visual уровней.

**Статус:** approved v0.3.

---

### D-015: Header bar consolidation

**Решение:** engine indicator + tabs + global actions в один header bar.
Status info (safety state, uptime, alarms count, disk, connection) в bottom
status bar.

**Альтернативы:** текущая фрагментация (engine row + tabs row + status
scattered).

**Обоснование:** Текущая фрагментация создаёт визуальный шов и тратит
вертикальное пространство. Top header = navigation, bottom bar = system
status. Standard desktop convention.

**Статус:** approved v0.3.

---

### D-016: Toast position top-center

**Решение:** toasts top-center под header, не bottom-right.

**Альтернативы:** bottom-right (browser standard), top-right, center-screen.

**Обоснование:** Bottom area занят live plots на большинстве tabs.
Bottom-right toast перекрывает критичные данные. Top-center не перекрывает
контент (там tab bar) и легко замечается.

**Статус:** approved v0.3.

---

### D-017: Modal buttons bottom-right (Linux convention)

**Решение:** primary button справа, secondary слева.

**Альтернативы:** Windows convention (primary left).

**Обоснование:** Лаб PC мигрирует на Ubuntu. Linux/macOS native convention
= primary right. Деплоя не было — нет привычки которую ломать. GNOME HIG
рекомендует primary right.

**Статус:** approved v0.3.

---

### D-018: Удалён status.exp

**Решение:** удалён отдельный semantic slot для "experiment phase active"
(фиолетовый в v0.2).

**Альтернативы:** оставить (v0.2).

**Обоснование:** Это было over-engineering. Состояние "канал участвует в
фазе эксперимента" — это **свойство процесса**, не свойство канала.
Показывается через dedicated experiment indicator в header, не через цвет
sensor card. Простая система лучше.

**Статус:** approved v0.3.

---

### D-019: Sensor card fault state упрощён до двух channel

**Решение:** fault state = pulse animation (primary) + red value text
(secondary). Убраны: left edge red stripe, colored border ring.

**Альтернативы:** три channel одновременно (v0.2), один channel только
(color).

**Обоснование:** Три канала избыточны — pulse привлекает внимание, red
value text identifies which value. Left edge + border ring — лишний шум
который не добавляет информации. Принцип discipline: один primary channel
+ один secondary на каждое состояние.

**Статус:** approved v0.3.

---

### D-020: Status pill фон tint убран

**Решение:** status pill использует только dot + text color, без background
tint.

**Альтернативы:** dot + text + bg tint (v0.2).

**Обоснование:** Pill маленький, два channel (dot + text) достаточно для
всех состояний. Bg tint — лишний шум который не различает состояния лучше.
Симметричное упрощение с D-019 sensor card.

**Статус:** approved v0.3.

---

### D-021: Warm stone neutral (12 ступеней)

**Решение:** 12-step warm stone neutral scale.

**Альтернативы:** cold slate, 8 ступеней, 16 ступеней.

**Обоснование:**
- **Warm над cold:** создаёт температурный контраст с cool indigo accent,
  формирует характерную identity
- **12 ступеней:** достаточно для 5 surface levels + 5 text levels + 2
  border levels без overlap. 8 — недостаточно, 16 — создаёт неразличимые
  соседние.
- **R+1..R+2 шифт:** едва заметно, но в сочетании с accent даёт
  характерное "лицо"

**Статус:** approved v0.3.

---

### D-022: Spacing scale 6 ступеней

**Решение:** 6-step spacing scale (space.0..space.6).

**Альтернативы:** 8 ступеней (v0.1), 4 ступени.

**Обоснование:** В реальном использовании последние 2 ступени из v0.1
(48px, 64px) почти не нужны. 6 ступеней покрывают все паттерны. Меньше
опций для неправильного выбора = более disciplined результат.

**Статус:** approved v0.3.

---

### D-023: Radius 3 ступени

**Решение:** 3-step radius (sm 3px, md 5px, lg 6px).

**Альтернативы:** 2 ступени, 4+ ступени.

**Обоснование:** 3 уровня достаточно для differentiation (inputs / cards /
modals). Меньше — размывается иерархия. Больше — невидимые различия
соседних ступеней.

**Статус:** approved v0.3.

---

### D-024: No indeterminate progress spinners

**Решение:** никаких indeterminate spinners. Indeterminate состояние —
текст "Обработка..." без visual element.

**Альтернативы:** spinners (default Qt).

**Обоснование:** Spinner создаёт ложное ощущение прогресса. Если мы не
знаем что происходит — честно признаться текстом, не крутить колёсико.

**Статус:** approved v0.3.

---

### D-025: Keyboard-first interaction

**Решение:** keyboard — first-class interaction channel, все actions
доступны через shortcuts, focus ring всегда виден.

**Альтернативы:** mouse-first с optional keyboard.

**Обоснование:** CryoDAQ — pro tool. Оператор часто работает не мышью
(руки на приборах или в лабораторном журнале). Shortcuts уже частично есть
в existing code — расширяем systematically.

**Статус:** approved v0.3.

---

### D-026: Secondary visual channel для color-critical states

**Решение:** fault/ok/warning состояния имеют **secondary visual channel**
помимо цвета. Для CVD compatibility.

**Channels:**
- Fault: color + **motion** (pulse animation D-013)
- Stale: color + **position** (staleness pill появляется)
- В Phase UI-2: status pill icons (shape channel) для warning/ok/info

**Обоснование:** ~5% мужчин имеют deuteranomaly. В лаборатории на 5-10
человек высокая вероятность хотя бы одного CVD оператора. Color-only
indication — failure mode для них. Secondary channel обеспечивает
доступность без compromising визуальный язык.

**Статус:** approved v0.3 (implementation — Phase UI-2).

---

### D-027: Pixel values calibrated on lab hardware

**Решение:** все конкретные pixel values (spacing, sizes, heights) —
калибруются на реальном лабораторном Linux PC, не на Mac dev.

**Альтернативы:** калибровать на Mac и надеяться что хорошо перенесётся.

**Обоснование:** Mac Retina scaling и Linux raw pixel rendering дают разные
результаты. Ночной оператор будет работать на лабораторном мониторе, не на
MBP. Калибровка на target hardware — единственный способ получить
правильные значения.

**Процесс:**
1. Phase UI-1 реализует tokens с default values
2. Bundle deploys на лаб PC
3. Визуальная проверка в реальных условиях
4. Итерация значений в `theme.py`
5. Финальные значения коммитятся как часть Phase UI-1 closure

**Статус:** approved v0.3.

---

## 11. Document lifecycle

### 11.1 Versioning

- **Minor version bump** (v0.3 → v0.4): правки формулировок, добавление
  decision log entries, уточнения. Не ломает token compatibility.
- **Patch bump** (v0.3 → v0.3.1): исправление опечаток, уточнение
  неясностей. Формальный changelog не обязателен.
- **Major version bump** (v0.3 → v1.0): после первого production deployment
  на лабораторном PC и подтверждения что система работает. До v1.0 система
  считается в active development.
- **Breaking version bump** (v1.0 → v2.0): фундаментальное изменение token
  architecture или эстетики. Требует явного обсуждения и rework.

### 11.2 Когда обновлять документ

Документ обновляется в следующих случаях:

1. **На Phase completion**: после каждой UI phase закрытия, фиксация
   changes и learnings в новой версии документа
2. **При обнаружении gap**: если во время implementation обнаружен
   пропущенный token / pattern / rule — добавить в документ **до**
   имплементации
3. **При конфликте между кодом и документом**: документ — источник истины.
   Код приводится в соответствие с документом, или документ меняется **и
   записывается в decision log** почему
4. **По feedback от operators**: после deployment, реальный feedback от
   ночных операторов может потребовать изменений. Documented in decision
   log с operator quote.

### 11.3 Кто может менять document

- **Vladimir (project owner)**: любые изменения
- **Claude (design consultant)**: proposed changes через explicit review,
  Vladimir approval required
- **Claude Code (implementation agent)**: **не** может менять document
  independently. Если CC обнаруживает проблему в spec — report в issue,
  human decides.

### 11.4 Changelog location

Changelog хранится в decision log секции (раздел 10). Каждый approved
change получает numbered entry D-### с датой, обоснованием, альтернативами,
финальным статусом.

**Нет отдельного CHANGELOG.md файла.** Decision log = changelog для design
system.

### 11.5 Backwards compatibility

Когда token меняется (например, accent hex updated):

1. **Token rename**: не делаем. `accent.400` остаётся `accent.400` даже
   если hex меняется. Имя стабильное, значение может эволюционировать.
2. **Token deletion**: требует major bump. Существующий код не должен
   полагаться на deleted token.
3. **Token addition**: безопасно в minor bump. Новые tokens не ломают
   существующий код.

Существующие скриншоты в отчётах использующие старую палитру остаются как
historical record. Они **не** должны быть "обновлены" — они документируют
состояние системы на момент генерации.

### 11.6 Open questions

Вопросы которые **оставлены открытыми** в v0.3 и требуют решения:

- **[OPEN-01]** Конкретные pixel values для spacing, type, sizing —
  калибровка на лаб PC, Phase UI-1 Block 3 / closure.
- **[OPEN-02]** Warm stone vs cool slate final temperature — подтверждение
  визуально на реальном мониторе. Вариант отмены warm в пользу cool если
  "желтушно".
- **[OPEN-03]** Status pill icons (shape channel) для CVD compatibility —
  design icons и добавить в Phase UI-2.
- **[OPEN-04]** Keyboard shortcut полный список — расширить существующий в
  `main_window.py` до систематического списка. Phase UI-2 или UI-3.
- **[OPEN-05]** Плот print mode exact light theme tokens — финальная
  калибровка при реальной генерации отчётов. Phase UI-2.

Открытые вопросы решаются и закрываются как новые decision log entries.

---

## Конец документа v0.3

Стабильные части этого документа (foundation tokens, principles, patterns,
decision log) должны меняться редко и обдуманно. Screen-by-screen specs и
phase planning вынесены в отдельный файл `docs/UI_REWORK_ROADMAP.md` чтобы
design system оставался стабильным независимо от iteration на конкретных
экранах.
