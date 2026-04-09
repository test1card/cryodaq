# CryoDAQ UI Rework Roadmap

> **Живой документ** с планами переработки каждого экрана CryoDAQ GUI и
> распределением работы по Phase UI-1 / UI-2 / UI-3.
>
> **Связанные документы:**
> - `docs/DESIGN_SYSTEM.md` — foundation tokens, patterns, principles.
>   Источник истины для визуального языка. Этот файл применяет правила из
>   design system к конкретным экранам.
>
> **Отличие от design system:** design system — это **правила**, roadmap —
> это **планы**. Design system стабилен и меняется редко. Roadmap —
> обновляется по мере работы, отслеживает прогресс, содержит TODOs.
>
> **Scope:** только CryoDAQ, все 10 tabs. Primary target — лабораторный PC
> Linux FHD 1920×1080.

---

## Оглавление

1. [Phase planning overview](#1-phase-planning-overview)
2. [Phase UI-1: foundation + cleanup](#2-phase-ui-1-foundation--cleanup)
3. [Phase UI-2: component patterns + layout rework](#3-phase-ui-2-component-patterns--layout-rework)
4. [Phase UI-3: polish + edge cases](#4-phase-ui-3-polish--edge-cases)
5. [Screen specifications](#5-screen-specifications)
6. [Open issues и decisions needed](#6-open-issues-и-decisions-needed)

---

## 1. Phase planning overview

CryoDAQ UI rework делится на **три фазы**. Каждая фаза имеет чёткий scope,
deliverables, и success criteria. Phase не пересекаются — UI-2 не
начинается до закрытия UI-1.

### 1.1 Phase UI-1 — Foundation + Cleanup

**Цель:** ввести theme.py со всеми foundation tokens из design system,
очистить весь hardcoded styling из widget files, применить новые цвета,
шрифты, plot styling без layout changes.

**Что меняется визуально:**
- Цветовая палитра (warm stone + cool indigo + semantic palette)
- Шрифты (Inter + JetBrains Mono)
- Plot styling (background, lines, grid, axes)
- Status colors везде где они hardcoded
- Base card styling через qdarktheme

**Что НЕ меняется:**
- Layout — никаких перестановок, новых компонентов, перегруппировок
- Custom widgets — никаких новых классов
- Behavior — никакой логики

**Success criteria:**
- 829 tests passing (baseline preserved)
- Все hardcoded hex заменены на tokens
- Bundle smoke test passes
- Visual check on Mac + on лаб PC подтверждает правильность tokens

**Deliverables:**
- `src/cryodaq/gui/theme.py` (новый)
- `pyproject.toml` + lockfile (pyqtdarktheme-fork added)
- `build_scripts/cryodaq.spec` (hidden imports, font resources)
- Все widgets в `src/cryodaq/gui/widgets/` обновлены
- Design system tokens **calibrated** на лаб PC

### 1.2 Phase UI-2 — Component patterns + Layout rework

**Цель:** реализовать все custom components из design system (sensor card,
hero readout, status pill, alarm row, group header, etc) и переработать
layout ключевых экранов.

**Что меняется:**
- Custom widget classes
- Layout реструктуризация всех экранов
- Header bar consolidation
- Status bar (bottom)
- Empty states
- Toast system
- Tab bar с иконками
- Overview rework с hero readouts и group headers
- Form layouts
- Modal dialog system

**Success criteria:**
- Все component patterns из design system имплементированы
- Все 10 tabs приведены в соответствие со screen specs ниже
- Все tests updated / new tests added для new components
- Bundle smoke test passes на лаб PC
- Operator feedback собран и addressed

### 1.3 Phase UI-3 — Polish + Edge cases

**Цель:** окончательная шлифовка, accessibility improvements,
responsive behavior для других разрешений, Web dashboard styling.

**Что меняется:**
- Density audit на разных разрешениях
- Adaptive layout rules (compact vs standard)
- Web dashboard styling (отдельный target)
- Accessibility audit (keyboard nav, focus order, contrast verification)
- Animation polish
- Tab order optimization на основе usage patterns
- Status pill icons (CVD compatibility)
- Full keyboard shortcut coverage

**Success criteria:**
- Accessibility audit passes
- Responsive на compact (<1280) и large (>2560) screens
- Web dashboard styled consistently

### 1.4 Phase ordering и dependencies

```
Phase UI-1 (Foundation)
    ↓ (requires: 829 tests baseline, feat/ui-phase-1 branch)
    ↓ (blocks: UI-2 until theme.py stable)
Phase UI-2 (Components + Layout)
    ↓ (requires: UI-1 merged to master)
    ↓ (blocks: UI-3 until components stable)
Phase UI-3 (Polish)
    ↓ (requires: UI-2 deployed to lab PC + operator feedback)
    ↓
Production-ready v1.0
```

Phases **не перекрываются** — каждая закрывается до начала следующей.

---

## 2. Phase UI-1: foundation + cleanup

### 2.1 Scope (что делается)

1. **Создать `gui/theme.py`** со всеми foundation tokens из design system
   секции 3
2. **Установить pyqtdarktheme-fork** и применить с `custom_colors` для
   warm stone + cool indigo
3. **Применить pyqtgraph global config** (background, foreground, antialias)
4. **Установить bundled fonts** (Inter + JetBrains Mono) через
   QFontDatabase с tabular figures enabled
5. **Cleanup всех `setStyleSheet`** в виджетах:
   - Все hardcoded hex → tokens
   - Все hardcoded font sizes → type scale
   - Все hardcoded paddings → spacing scale
6. **Cleanup всех `setBackground` на plots** → используют
   `theme.PG_BACKGROUND`
7. **Apply plot tokens**: line palette, line width, axis fg, grid opacity
8. **Apply semantic colors** к существующим status indicators (цвета
   меняются на новые `status.*` tokens, **без переразмещения**)
9. **PyInstaller updates** для bundled fonts + qdarktheme resources
10. **Bundle smoke test** на Mac и на лаб PC
11. **Calibrate pixel values** на реальном лабораторном Linux PC —
    iterate на `theme.py` spacing/type/sizing values

### 2.2 Scope (что НЕ делается)

**Layout changes** — не в UI-1:
- Overview group headers — UI-2
- Эксперимент two-column — UI-2
- Hero readouts T11/T12 — UI-2
- Header bar consolidation — UI-2
- Status bar (bottom) — UI-2
- Tab bar icons — UI-2
- Sensor card grouping — UI-2

**Component patterns** — не в UI-1:
- Sensor card redesign со всеми states — UI-2
- Status pill component — UI-2
- Alarm row redesign — UI-2
- Group header component — UI-2
- Empty states — UI-2
- Toast system — UI-2
- Modal dialog system — UI-2

**Features** — не в UI-1:
- Fault pulse animation (D-013) — UI-2
- Keyboard shortcut expansion — UI-2 / UI-3
- CVD status pill icons — UI-2 / UI-3

Всё это **остаётся из design system** но реализуется позже. UI-1 только
готовит foundation.

### 2.3 Files touched

**New files:**
- `src/cryodaq/gui/theme.py`
- `src/cryodaq/gui/resources/fonts/Inter-*.ttf` (bundled)
- `src/cryodaq/gui/resources/fonts/JetBrainsMono-*.ttf` (bundled)

**Modified files:**
- `pyproject.toml` — add pyqtdarktheme-fork dependency
- `requirements-lock.txt` — pin and hash pyqtdarktheme-fork
- `src/cryodaq/gui/app.py` — import theme, apply qdarktheme, load fonts
- `build_scripts/cryodaq.spec` — hidden imports, data files
- `src/cryodaq/gui/widgets/*.py` — cleanup hardcoded styles (19 files)

**Not touched:**
- Engine, core, drivers, safety, storage, analytics, reporting, web,
  notifications, instruments — любой не-GUI код
- Layout structures in widgets — только styling замены
- Test files — except где tests assert on specific style strings

### 2.4 Block structure

Phase UI-1 делится на 8 блоков с STOP points для review между ними:

**Block 1:** pyqtdarktheme-fork install + baseline verification
**Block 2:** Create `theme.py` с foundation tokens
**Block 3:** Hook theme into `app.py` + visual smoke test
**Block 4:** setStyleSheet audit (classification document, read-only)
**Block 5:** setStyleSheet cleanup (mechanical application of table)
**Block 6:** pyqtgraph local setBackground cleanup
**Block 7:** PyInstaller bundle smoke
**Block 8:** Final regression + calibration on lab PC

Detailed block specifications — в отдельном **Phase UI-1 CC Prompt**
документе (создаётся после approval этого roadmap).

### 2.5 Calibration checkpoint

**После Block 3** (когда theme впервые применяется визуально):
- Bundle deploys on лаб PC
- Vladimir проверяет визуально:
  - Warm stone vs cool slate temperature — не "желтушно"?
  - Cool indigo accent — читаемо, не режет глаз?
  - Type scale — 14px body readable ночью?
  - Spacing — density комфортная?
- Если что-то не так — iterate на `theme.py` values
- Calibrated values коммитятся как часть Block 8 closure

**Open calibration questions** (из design system [OPEN-01] .. [OPEN-02]):
- Final spacing pixel values
- Final type scale pixel values
- Sensor card min width
- Big readout dimensions
- Warm stone vs cool slate final decision
- Plot line width (1.5px может быть толсто на FHD)

---

## 3. Phase UI-2: component patterns + layout rework

### 3.1 Scope overview

Phase UI-2 — это где CryoDAQ **visually transforms**. Все custom components
реализуются, все layout перерабатываются согласно screen specs ниже.

Примерный порядок работы (subject to adjustment после UI-1 completion):

1. **Custom widget base classes** — `SensorCard`, `HeroReadout`,
   `StatusPill`, `AlarmRow`, `GroupHeader`, `MetricCard`
2. **Header bar consolidation** — `MainHeaderBar` component
3. **Status bar** — `BottomStatusBar` component
4. **Tab bar** с иконками
5. **Overview rework** — hero row, plots row, grouped sensor cards
6. **Эксперимент rework** — two-column layout, form redesign
7. **Источник мощности** — chrome cleanup (structure уже правильная)
8. **Аналитика rework** — hero metrics без colored borders, vacuum prognosis
   card restructure
9. **Теплопроводность rework** — left column с group headers
10. **Алармы rework** — empty state, active/history sections
11. **Служебный лог rework** — normal button sizes, textarea height
12. **Архив rework** — filter card, empty states, disabled buttons cleanup
13. **Калибровка** — minimal chrome refinement
14. **Приборы** — instrument card left-edge indicators
15. **Empty states** во всех applicable places
16. **Toast system** implementation
17. **Modal dialog** consistent styling
18. **Fault pulse animation** (D-013)

### 3.2 Detailed specs

Каждый экран имеет detailed spec в секции 5 этого документа.

### 3.3 Success criteria

- All 10 tabs visually match their screen specs
- All custom components implement their design system patterns
- Bundle smoke test on лаб PC passes
- Operator feedback collected и addressed
- Tests updated / new tests added

---

## 4. Phase UI-3: polish + edge cases

### 4.1 Scope

1. **Density audit** — проверка на разных разрешениях (1366×768 compact,
   FHD standard, 2560×1440 large, 4K)
2. **Adaptive layout rules** — explicit breakpoint handling
3. **Web dashboard styling** — FastAPI dashboard получает свой design
   language aligned с main GUI
4. **Accessibility audit**:
   - Keyboard navigation complete coverage
   - Focus order logical в всех панелях
   - Screen reader accessibleName/Description on all meaningful widgets
   - Contrast verification на всех новых tokens
   - Color vision deficiency verification
5. **Status pill icons** (CVD shape channel) — UI-3 addition из D-026
6. **Full keyboard shortcut coverage** — из design system 6.2
7. **Animation polish** — easing curves verification на лаб PC
8. **Tab order optimization** на основе real usage patterns
9. **Print mode** finalization для отчётов

### 4.2 Success criteria

- Accessibility audit passes (AA minimum для все interactive elements)
- Responsive на compact (<1280) и large (>2560)
- Web dashboard visually consistent с main GUI
- Keyboard-only operation возможен для all primary workflows

---

## 5. Screen specifications

Detailed specs для каждого из 10 tabs. Эти specs — target после Phase UI-2
completion. Phase UI-1 **не реализует** layout changes, только styling.

### 5.1 Обзор (Overview)

**Текущее состояние** (based on image 1 from review):
- Header + tabs + status bar separated, gap между ними
- Sensor cards flat 7 в ряд × 3 ряда
- Pressure card отдельно справа на уровне sensor cards row
- Temperature plot большой, Pressure plot обрезан
- Bottom: Keithley status mini bar + Журнал заметка input

**Target layout:**

```
┌─ Header bar (56px) ─────────────────────────────────────────────────────┐
│ ● Engine     [Обзор] [Эксп] [...]                        [Web] [Restart]│
└─────────────────────────────────────────────────────────────────────────┘
┌─ Smena status row (48px) ────────────────────────────────────────────────┐
│  Смена: Иванов И.И.  ·  Начало 22:00  ·  3ч 12мин            [Сдать смену]│
└─────────────────────────────────────────────────────────────────────────┘
┌─ Hero readouts row (180px) ─────────────────────────────────────────────┐
│  ┌──────────────────────────┐  ┌──────────────────────────┐            │
│  │ T11 Hero Big Number       │  │ T12 Hero Big Number       │            │
│  └──────────────────────────┘  └──────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────────┘
┌─ Plots row (320px) ─────────────────────────────────────────────────────┐
│ ┌──────────────────────────────────────────┐  ┌─────────────────────┐  │
│ │ Temperature plot (selected channels)      │  │ Pressure plot (log) │  │
│ │  height 320px, 70% width                  │  │  height 320px, 30%  │  │
│ └──────────────────────────────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
┌─ Sensor cards by group ─────────────────────────────────────────────────┐
│  КРИОСТАТ                                                    7 каналов  │
│  ───────────────────────────────────────────────────────────────────    │
│  [card] [card] [card] [card] [card] [card] [card]                       │
│                                                                         │
│  КОМПРЕССОР                                                  7 каналов  │
│  ───────────────────────────────────────────────────────────────────    │
│  [card] [card] [card] [card] [card] [card] [card]                       │
│                                                                         │
│  ОПТИКА                                                      4 канала   │
│  ───────────────────────────────────────────────────────────────────    │
│  [card] [card] [card] [card]                                            │
└─────────────────────────────────────────────────────────────────────────┘
┌─ Status bar (32px) ─────────────────────────────────────────────────────┐
│ ● SAFE_OFF · Аптайм 02:34 · 0 алармов · 730 ГБ · ● Подкл. · 12 изм/с    │
└─────────────────────────────────────────────────────────────────────────┘
```

**Изменения относительно текущего:**
- Header consolidated
- Smena row отдельно под header (48px)
- T11 + T12 hero readouts (новое)
- Temperature plot 70% + Pressure plot 30% в одной row
- Sensor cards **по группам** с group headers
- Bottom Keithley row + Журнал заметка удаляются с overview
- Pressure card справа sensor cards row удаляется
- Status bar внизу

**Phase assignment:**
- UI-1: styling cleanup (colors, fonts, plot lines) на existing layout
- UI-2: full layout rework согласно specs выше

### 5.2 Эксперимент

**Текущее:** form занимает левую треть с пустотой справа.

**Target:**

```
┌─ Header (56px) ──────────────────────────────────────────────────────┐
└──────────────────────────────────────────────────────────────────────┘
┌─ Mode selector row ──────────────────────────────────────────────────┐
│  Режим:  [Эксперимент] [Отладка]                                      │
│         ↑ secondary tabs, не buttons                                   │
└──────────────────────────────────────────────────────────────────────┘
┌─ Two-column workspace ───────────────────────────────────────────────┐
│ ┌── Left column (60%) ──────────┐  ┌── Right column (40%) ─────────┐ │
│ │ Создание эксперимента          │  │ Активный эксперимент          │ │
│ │ ─────────────────────────────  │  │ ─────────────────────────────  │ │
│ │                                │  │                                │ │
│ │ Шаблон     [Калибровка ▼]      │  │ [empty state if none active]  │ │
│ │ Название   [_____________]     │  │                                │ │
│ │ Оператор   [Иванов И ▼]        │  │ ИЛИ active experiment card:    │ │
│ │ Образец    [_____________]     │  │                                │ │
│ │ Криостат   [АКЦ ФИАН ▼]        │  │ • Status pill                  │ │
│ │ Описание   [_____________]     │  │ • Phase indicator              │ │
│ │            [_____________]     │  │ • Elapsed time                 │ │
│ │ Заметки    [_____________]     │  │ • Active params                │ │
│ │            [_____________]     │  │ • [Завершить эксперимент]      │ │
│ │                                │  │                                │ │
│ │ [Создать эксперимент] (primary)│  │                                │ │
│ └────────────────────────────────┘  └────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Two-column layout заполняет ширину экрана
- Forms имеют semantic widths (не full stretch)
- Active experiment card справа всегда видна
- "ЭКСПЕРИМЕНТ" зелёный кричащий header удаляется, mode selector =
  secondary tabs стиля
- Заметки field здесь, не на overview

**Phase:** UI-2

### 5.3 Источник мощности

**Текущее:** two column smua + smub, big readouts, plots снизу. Структура
правильная, нужен только chrome cleanup.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Source toolbar row ──────────────────────────────────────────────────┐
│ Keithley 2604B                                                         │
│ Независимое управление каналами A / B и общий аварийный режим A+B     │
│                                                                        │
│ [Старт A+B] [Стоп A+B]                                  [АВАР. ОТКЛ.]  │
└────────────────────────────────────────────────────────────────────────┘
┌─ Two channels row ────────────────────────────────────────────────────┐
│ ┌── Канал A (smua) ──────────────┐  ┌── Канал B (smub) ─────────────┐ │
│ │                            ВЫКЛ │  │                          ВЫКЛ │ │
│ │ ─────────────────────────────── │  │ ─────────────────────────────  │ │
│ │ P цель  V предел  I предел      │  │ P цель  V предел  I предел     │ │
│ │ [0.500] [40.00]   [1.000]       │  │ [0.500] [40.00]   [1.000]      │ │
│ │ [Старт] [Стоп] [ВАР. ОТКЛ.]     │  │ [Старт] [Стоп] [ВАР. ОТКЛ.]    │ │
│ │                                 │  │                                │ │
│ │ ┌─Big readouts (4 cards) ─────┐ │  │ ┌─Big readouts (4 cards) ───┐ │ │
│ │ │ V    I    R    P            │ │  │ │ V    I    R    P          │ │ │
│ │ │ 0V   0A   2.32Ω 0W          │ │  │ │ 0V   0A   1.624Ω 0W       │ │ │
│ │ └─────────────────────────────┘ │  │ └────────────────────────────┘ │ │
│ │                                 │  │                                │ │
│ │ ┌─Plots (2x2 grid) ───────────┐ │  │ ┌─Plots (2x2 grid) ──────────┐ │ │
│ │ │ V plot       I plot          │ │  │ │ V plot       I plot         │ │ │
│ │ │ R plot       P plot          │ │  │ │ R plot       P plot         │ │ │
│ │ └─────────────────────────────┘ │  │ └────────────────────────────┘ │ │
│ └─────────────────────────────────┘  └────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Big readouts используют quantity color tokens (V/I/R/P) но borders
  убираем — color применяется к **value text** или **dot indicator**
- Plot styling consistent с rest of app
- АВАР. ОТКЛ — destructive button variant
- Channel A/B header более явный

**Phase:** UI-1 styling cleanup, UI-2 big readouts refinement

### 5.4 Аналитика

**Текущее:** два hero metric cards с цветными borders как декорация, plot
пустой, vacuum prognosis controls cluttered.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Top row: hero metrics ──────────────────────────────────────────────┐
│ ┌── R thermal ──────────────┐  ┌── Cooldown predict ────────────────┐ │
│ │ Тепловое сопротивление    │  │ Прогноз охлаждения                 │ │
│ │                           │  │                                    │ │
│ │  3.42  К/Вт              │  │  ETA  2ч 14мин                     │ │
│ │  display mono             │  │  display mono text.accent          │ │
│ │                           │  │                                    │ │
│ │  Точность ±0.05           │  │  4.2 К → 50.4 К                    │ │
│ │  label muted              │  │  Уверенность 87%                   │ │
│ │                           │  │  label                              │ │
│ └───────────────────────────┘  └────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
┌─ R_thermal plot ───────────────────────────────────────────────────────┐
│  height 240px, full width                                              │
│  empty state if no data (proper empty state)                           │
└────────────────────────────────────────────────────────────────────────┘
┌─ Vacuum prognosis card ────────────────────────────────────────────────┐
│  ПРОГНОЗ ВАКУУМА                                       [Экспонента ▼] │
│  ───────────────────────────────────────────────────────────────────   │
│ ┌── Status & params (left 25%) ─┐  ┌── Plot (right 75%) ─────────────┐ │
│ │ Тренд: ● Стабильно             │  │                                 │ │
│ │ ETA:                           │  │  log P plot                     │ │
│ │  1.0e-06  4ч 55мин             │  │  height 240px                   │ │
│ │  1.0e-05  ✓                    │  │                                 │ │
│ │  1.0e-04  ✓                    │  │                                 │ │
│ │ P предельное: 1.0e-20          │  │                                 │ │
│ │ Модель: Экспонента             │  │                                 │ │
│ │ R²: 0.038                      │  │                                 │ │
│ │ Уверенность:                   │  │                                 │ │
│ │ [▓ 3%]                         │  │                                 │ │
│ └────────────────────────────────┘  └─────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Hero metric cards убирают цветные borders (anti-pattern — status colors
  as decoration)
- "Прогноз охлаждения" использует `text.accent` для главного числа (не
  `text.exp` — этот токен удалён)
- R_thermal plot имеет proper empty state
- Vacuum prognosis — single container с two-column inside
- "Стабильно" pill из жёлтого в `status.ok` (зелёный) — стабильно = хорошо
- "Уверенность 3%" выделяется через `status.fault` и поднимается в
  более видимое место

**Phase:** UI-2

### 5.5 Теплопроводность

**Текущее:** левая колонка 4 разных смысловых группы стопкой без
separation.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Page header card ─────────────────────────────────────────────────────┐
│  Теплопроводность                                          [Экспорт CSV] │
│  Оценка R и G по выбранной цепочке датчиков                              │
└────────────────────────────────────────────────────────────────────────┘
┌─ Two-column layout ────────────────────────────────────────────────────┐
│ ┌── Left column (320px fixed) ──┐  ┌── Right column (flex) ──────────┐ │
│ │ ВЫБОР ДАТЧИКОВ                 │  │ Стабильность: P = 0 Вт          │ │
│ │ ──────────                     │  │                                  │ │
│ │ ☐ T1 Криостат верх             │  │ Results table (10 columns)      │ │
│ │ ☐ T2 Криостат низ              │  │                                  │ │
│ │ ☑ T3 Радиатор 1                │  │ Пара | T гор | T хол | dT | ... │ │
│ │ ...                            │  │                                  │ │
│ │                                │  │ ─────────────────────────────    │ │
│ │ ─── space.5 ───                │  │                                  │ │
│ │                                │  │ Plot temperature evolution       │ │
│ │ ИСТОЧНИК P                     │  │                                  │ │
│ │ ──────                         │  │                                  │ │
│ │ Канал [Keithley_1/smua/power▼] │  │                                  │ │
│ │ [Вверх] [Вниз]                 │  │                                  │ │
│ │                                │  │                                  │ │
│ │ ─── space.5 ───                │  │                                  │ │
│ │                                │  │                                  │ │
│ │ АВТОИЗМЕРЕНИЕ                  │  │                                  │ │
│ │ ──────────────                 │  │                                  │ │
│ │ ☐ Включено                     │  │                                  │ │
│ │ Начальная P [0.0001 Вт]        │  │                                  │ │
│ │ Шаг P       [0.0100 Вт]        │  │                                  │ │
│ │ Кол-во шагов [10]              │  │                                  │ │
│ │ Стабилизация [95.0 %]          │  │                                  │ │
│ │ Мин. ожидание [30.00 с]        │  │                                  │ │
│ │ [Старт] [Стоп]                 │  │                                  │ │
│ └────────────────────────────────┘  └─────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Left column имеет **три явные смысловые группы** с group headers:
  1. Выбор датчиков
  2. Источник P
  3. Автоизмерение
- "Экспорт CSV" переезжает в page header (global action)
- Group headers использует heading + uppercase + letter-spacing pattern

**Phase:** UI-2

### 5.6 Алармы

**Текущее:** пустые таблицы Алармы + Алармы v2, нет empty state.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Page header card ─────────────────────────────────────────────────────┐
│  Алармы                              [Активные ▼]    [Очистить старые] │
│  3 активных, 12 в истории за 24 ч                                       │
└────────────────────────────────────────────────────────────────────────┘

Empty state if no active:

┌─ Empty state ──────────────────────────────────────────────────────────┐
│                                                                         │
│              [icon: bell-off 32px]                                      │
│                                                                         │
│            Нет активных алармов                                         │
│         Все каналы в норме                                              │
│                                                                         │
│        Показать историю алармов →                                       │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘

OR if active:

┌─ Active alarms section ────────────────────────────────────────────────┐
│  АКТИВНЫЕ                                              3 алармa         │
│  ─────────────────────────────────────────────────────                  │
│  ● 14:32:17  Т7 Детектор          315.2 K > 310 K       [✓ ACK]        │
│  ● 14:35:02  Т11 Теплообм 1       82.4 K > 80 K         [✓ ACK]        │
│  ● 14:35:11  VSP63D pressure      1e-3 mbar > 1e-4      [✓ ACK]        │
└────────────────────────────────────────────────────────────────────────┘
┌─ History section ──────────────────────────────────────────────────────┐
│  ИСТОРИЯ ЗА 24 Ч                                       12 записей      │
│  ─────────────────────────────────────────────────────                  │
│  ● 13:21:08  Т4 Радиатор 2        78.1 K > 78 K         resolved 13:42 │
│  ...                                                                    │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Default view = empty state (не пустые таблицы)
- Когда есть активные — две sections
- Фильтр dropdown в page header
- Двойная секция Алармы / Алармы v2 объединяется через filter

**Phase:** UI-2

### 5.7 Служебный лог

**Текущее:** кнопка "Сохранить запись" растянута на половину ширины,
textarea узкая.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Page header card ─────────────────────────────────────────────────────┐
│  Служебный журнал                                  [Обновить] [Фильтр]  │
│  Технический лог для совместимости                                      │
└────────────────────────────────────────────────────────────────────────┘
┌─ Add entry section ────────────────────────────────────────────────────┐
│  Новая запись                                                           │
│  ─────────────────                                                      │
│  Автор:  [petrov_____]                                                  │
│  ☐ Только текущий эксперимент                                           │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Введите операторскую запись...                                      │ │
│  │ (textarea, min height 120px)                                        │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  [Сохранить запись]                                                     │
│  ↑ primary, normal width                                                │
└────────────────────────────────────────────────────────────────────────┘
┌─ Entries list ─────────────────────────────────────────────────────────┐
│  Empty state OR list of entries                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Button normal width, not half-screen
- Textarea min height 120px, expandable
- Separated sections (add / list)
- "Записей нет" — proper empty state

**Phase:** UI-2

### 5.8 Архив

**Текущее:** filter row + two-column, empty state looks broken.

**Target:**

```
┌─ Header ──────────────────────────────────────────────────────────────┐
┌─ Filter card ──────────────────────────────────────────────────────────┐
│  Архив экспериментов                                       [Обновить]   │
│  ──────────────────────────────                                         │
│  Шаблон [Все ▼]  Оператор [_______]  Образец [_______]                  │
│  С [2026-03-10] По [2026-04-09]  Отчёт [Все ▼]  Сортировка [Новые ▼]   │
└────────────────────────────────────────────────────────────────────────┘
┌─ Two-column results ───────────────────────────────────────────────────┐
│ ┌── Experiment list (50%) ──┐  ┌── Details panel (50%) ──────────────┐ │
│ │ [empty state if none] OR   │  │ [empty state if none selected] OR   │ │
│ │                            │  │                                      │ │
│ │ row 1 selected             │  │ Сведения                             │ │
│ │ row 2                      │  │ Шаблон: ...                          │ │
│ │ row 3                      │  │ ...                                  │ │
│ │ ...                        │  │                                      │ │
│ │                            │  │ Артефакты                            │ │
│ │                            │  │ • file1.csv                          │ │
│ │                            │  │                                      │ │
│ │                            │  │ [Открыть папку] [PDF] [DOCX]         │ │
│ └────────────────────────────┘  └──────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

**Изменения:**
- Filter row consolidated в filter card
- Empty states proper в обеих колонках
- Disabled buttons убираем — нет → нет кнопок, не disabled
- Inner tab bar removed

**Phase:** UI-2

### 5.9 Калибровка

**Текущее:** структура хорошая, нужен только chrome refinement.

**Минимальные изменения:**
- Headers `LS218_1` / `LS218_2` / `LS218_3` → group header pattern
- Зелёная "Начать калибровочный прогон" → primary button standard
- Import buttons → secondary style, normal size
- Таблица "Существующие кривые" → proper table styling, empty state

**Phase:** UI-1 styling cleanup (group headers), UI-2 button refinement

### 5.10 Приборы

**Текущее:** instrument cards с heavy colored borders + диагностика
таблица.

**Target:**
- Instrument cards: `border.subtle` с **left edge indicator** 3px (status
  color), не full-card colored border. Не перегружает визуально когда
  несколько инструментов в fault.
- Таблица "Диагностика датчиков" — group header pattern, существующая
  цветная градация здоровья (100/80/60/40) сохраняется (функциональна)

**Phase:** UI-2

---

## 6. Open issues и decisions needed

### 6.1 Calibration tasks (требуют лабораторный PC)

- **CAL-01**: Final spacing pixel values (space.1..space.6)
- **CAL-02**: Final type scale pixel values (все 7 размеров)
- **CAL-03**: Sensor card minimum width
- **CAL-04**: Big readout card dimensions (width, height)
- **CAL-05**: Plot minimum height для temperature plot
- **CAL-06**: Header bar height (56px target)
- **CAL-07**: Status bar height (32px target)
- **CAL-08**: Smena row height (48px target)
- **CAL-09**: Plot line width (1.5px default, may need 2px на FHD)
- **CAL-10**: Temperature — warm stone не слишком желтушно на реальном
  мониторе?

Все эти values **начинаются** с defaults из design system, **калибруются**
на лаб PC в Phase UI-1 Block 8.

### 6.2 Design decisions needed

- **DEC-01**: T11/T12 hero — какой компонент "smart": показывает live
  trend overlay или просто big number? [Phase UI-2 decision]
- **DEC-02**: Overview "Всё" button — сохраняется как есть или
  переработать как part of plot toolbar? [Phase UI-2 decision]
- **DEC-03**: Sensor card click behavior — opens modal detail panel или
  inline expand? [Phase UI-2 decision]
- **DEC-04**: Group header click — collapse/expand (UI-2 feature) или
  оставить static? [Phase UI-2/UI-3 decision]
- **DEC-05**: Alarm acknowledge workflow — single click или modal
  confirmation? [Phase UI-2 decision]

### 6.3 Technical issues to verify

- **TECH-01**: pyqtdarktheme-fork совместимость с Python 3.14 — проверено
  через PyPI classifier, confirmed в research. Real deployment test в
  Phase UI-1 Block 1.
- **TECH-02**: Inter + JetBrains Mono bundling в PyInstaller — проверить
  что ресурсы попадают в frozen bundle, применяются через QFontDatabase
  до первого QWidget render.
- **TECH-03**: Plot rendering performance с custom palette + 8 lines —
  проверить на слабом железе лаб PC (GTX 1050 Ti, не топовый GPU).
- **TECH-04**: pyqtgraph global config с `setConfigOption` — **must be
  imported before any PlotWidget creation**. Risk: class-level
  PlotWidget instantiation в existing code. Требует проверки grep'ом.
- **TECH-05**: pyqtdarktheme + custom QFont combination — верификация
  что bundled fonts применяются когда qdarktheme stylesheet активен.

### 6.4 Dependencies между tasks

```
Block 1 (pyqtdarktheme install) → Block 2 (theme.py)
Block 2 (theme.py) → Block 3 (app.py hook)
Block 3 (app.py hook) → Block 5 (setStyleSheet cleanup)
Block 4 (classification) → Block 5 (cleanup)
Block 5 → Block 6 (pyqtgraph cleanup)
Block 6 → Block 7 (bundle smoke)
Block 7 → Block 8 (lab PC deploy + calibration)
```

Blocks **не** могут идти параллельно — каждый зависит от предыдущего.

### 6.5 Risks и mitigation

**Risk 1: Theme не применяется правильно в frozen bundle**
- Mitigation: Block 7 explicit bundle smoke test
- Fallback: hidden imports tuning в spec file

**Risk 2: Baseline 829 tests сломается**
- Mitigation: tests run после каждого block, stop at failure
- Fallback: revert block, investigate root cause before continuing

**Risk 3: Visual result "желтушный" на реальном мониторе (warm stone не
работает)**
- Mitigation: Block 8 calibration на лаб PC, early visual check
- Fallback: pivot к cool slate neutral (одна правка в stone.* values)

**Risk 4: Font loading fails в PyInstaller frozen mode**
- Mitigation: explicit font resource collection в cryodaq.spec
- Fallback: fall back to system fonts + warning в log

**Risk 5: pyqtdarktheme-fork не поддерживает Python 3.14 correctly**
- Mitigation: Block 1 explicit install + import test
- Fallback: pin Python к 3.13 в venv (больше работы) или использовать
  pyqtdarktheme2 (требует Python 3.12-3.13)

---

## Конец документа roadmap v0.3
