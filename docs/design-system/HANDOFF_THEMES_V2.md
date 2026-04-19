# HANDOFF — Themes v2: шесть новых палитр

**Статус:** Spec, ожидает implementation (Settings → Тема menu wiring).
**Дата:** 2026-04-19
**ADR:** [001-light-theme-status-unlock.md](./adr/001-light-theme-status-unlock.md)
**Файлы:** `config/themes/signal.yaml`, `instrument.yaml`, `amber.yaml`,
`gost.yaml`, `xcode.yaml`, `braun.yaml` (all present, 25 tokens each).

---

## Краткая сводка

Шесть новых палитр в `config/themes/` дополняют существующие шесть
(`default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`,
`taupe_quiet`, `rose_dusk`). Каждая из новых ведётся **одной
design-осью**, не hue. Три dark, три light.

| Файл | Имя | Режим | Ведущая ось | ACCENT hue |
|---|---|---|---|---|
| `signal.yaml` | Сигнал | dark | чёрная точка + плоская лестница | 325° hot magenta |
| `instrument.yaml` | Приборный | dark | крупная лестница + видимые бордюры | 270° violet |
| `amber.yaml` | Янтарь | dark | сниженная амплитуда FG↔BG (60%) | 291° wine-plum |
| `gost.yaml` | ГОСТ | light | кремовая бумага + wine accent | 315° wine-maroon |
| `xcode.yaml` | Xcode | light | cool off-white + pure white CARD | 260° indigo |
| `braun.yaml` | Braun | light | кремовая product surface + видимые borders | 90° olive |

**Ключевое решение (ADR 001):** STATUS-палитра имеет два hex-комплекта
(dark и light), связанных hue-инвариантом. Светлые темы используют
shifted-L комплект для AA-контраста на CARD. Hue каждого STATUS-токена
идентичен в обоих комплектах; изменяется только lightness.

---

## 1. Dark — Сигнал (`signal.yaml`)

**Ассоциативный якорь:** Pan Sonic, Raster-Noton, Ikeda. Noise-проект
владельца — тесткард — той же семьи.

**Ведущая ось:** чёрная точка + плоская лестница + невидимые бордюры.
BG L=0.24% на грани чистого чёрного, шаги между поверхностями
0.06–0.15% (функционально невидимая дымка), BORDER на 1.08:1 к CARD.
Плоский silhouette, UI растворяется до данных. Акцент — hot magenta
325°, единственный signal color в монохромной среде.

**Метрики:**
- Лестница SUNK 0.09 → BG 0.24 → PANEL 0.30 → CARD 0.40 → ELEV 0.52%,
  Δ 0.06–0.15% (плоская)
- Амплитуда FG↔BG = 82%
- FG/BG 16.62:1 · FG/CARD 16.11:1 · TEXT2/CARD 7.37:1 ·
  MUTED/CARD 3.27:1
- ACCENT/BG 5.30:1 · ON_PRIMARY/ACCENT 5.38:1
- ACCENT 325° min-distance 35° до FAULT (safe)

**Trade-offs:**
- BG `#070809` сознательно нарушает §7.6 «BACKGROUND не pure black».
  На IPS-мониторе в лаборатории норм, на OLED-ноуте даст edge
  sharpening — предупредить владельца.
- Отсутствие лестницы и бордюров переносит иерархию на typographic
  weight и spacing. Если дашборд полагается на BORDER для разделения
  блоков — они сольются, проверить на реальном UI.

---

## 2. Dark — Приборный (`instrument.yaml`)

**Ассоциативный якорь:** HP, Tektronix, LakeShore — аппаратура,
которая физически стоит в лаборатории.

**Ведущая ось:** архитектурная лестница + видимые бордюры. Шаги
0.44 → 0.77 → 1.00 → 1.28% (в 2–3 раза крупнее остальных dark-тем).
BORDER 1.44:1 к CARD — «ridge» на powder-coated панели. Hue нейтралей
220° при sat 10% — steel, не graphite. Акцент — сдержанный violet
270°, функциональный.

**Метрики:**
- Лестница SUNK 0.71 → BG 1.15 → PANEL 1.93 → CARD 2.93 → ELEV 4.20%
- Амплитуда FG↔BG = 79.4%
- FG/BG 13.91:1 · FG/CARD 10.80:1 · TEXT2/CARD 5.42:1 ·
  MUTED/CARD 3.73:1
- ACCENT/BG 5.77:1 · ACCENT/CARD 4.48:1 · ON_PRIMARY/ACCENT 6.31:1
- ACCENT 270° min-distance 43° до STALE

**Trade-offs:**
- Самая «тяжёлая» dark-палитра по визуальному шуму. На плотном
  48-канальном дашборде крупные ступени + видимые бордюры могут
  читаться загромождённо.
- Violet accent формально далёк от приборной традиции (реальные
  lab-индикаторы — blue/green/amber, все на status-hue). Жанровая
  отсылка частичная.

---

## 3. Dark — Янтарь (`amber.yaml`)

**Ассоциативный якорь:** Тарковский, аналоговая warm-медитативность.

**Ведущая ось:** пониженная контрастная амплитуда. FG↔BG = 60% против
79–82% у остальных. Цифры ≥9.5:1 на CARD, читаются уверенно, но глаз
не устаёт после 4–6 часов. Hue нейтралей 30° sat 23% — обожжённый
амбер, в 3 раза насыщеннее warm_stone. Акцент — wine-plum 291°,
холодная нота на тёплой базе, ассоциативно читается как warm
(«пролитое вино»).

**Метрики:**
- Лестница SUNK 0.56 → BG 0.86 → PANEL 1.31 → CARD 1.96 → ELEV 2.70%
- **Амплитуда FG↔BG = 60.3% (ключевое отличие)**
- FG/BG 11.29:1 · FG/CARD 9.50:1 · TEXT2/CARD 5.65:1 ·
  MUTED/CARD 3.71:1
- ACCENT/BG 5.10:1 · ON_PRIMARY/ACCENT 5.10:1
- ACCENT 291° min-distance 64° до STALE (большой запас)

**Trade-offs:**
- Низкая амплитуда — для тихого мониторинга в ночную смену правильный
  режим, для быстрого реагирования на alarm или работы с подробным UI
  в дневное время может быть недостаточно контрастной на секундном
  восприятии.
- Жанрово самая «авторская» палитра, читается как «кабинет», не
  «пультовая».

---

## 4. Light — ГОСТ (`gost.yaml`)

**Ассоциативный якорь:** советская инженерная документация ВНИИФТРИ,
техпаспорта приборов, бумажный архив ФИАН. Эстетика физического
места, где владелец работает.

**Ведущая ось:** кремовая бумага + чёрная типографика + wine-maroon
accent как восковая печать. Hue нейтралей 47° sat 30–40% (тёплая
бумажность, не жёлтая желтушность). Лестница крупная и видимая —
каждый уровень читается как «страница / вкладка / поле данных». FG
`#1a1711` — warm near-black, «типографская краска», не pure black.

**Метрики:**
- Лестница SUNK 63.7 → PANEL 71.5 → BG 79.8 → CARD 87.8 → ELEV 97.2%,
  Δ 7.8–9.4% (крупная, видимая)
- Амплитуда FG↔BG = 78.9%
- FG/BG 14.44:1 · FG/CARD 15.80:1 · TEXT2/CARD 8.04:1 ·
  MUTED/CARD 4.11:1
- ACCENT/BG 7.74:1 · ACCENT/CARD 8.48:1 · ON_PRIMARY/ACCENT 9.59:1
- ACCENT 315° min-distance 45° до FAULT
- Light STATUS на CARD: 5.16–7.44:1 (все ≥4.5)

**Обоснование choices:**
- BG hue 47° sat 38% — тёплая бумага, но не жёлтая. При sat >50%
  уходит в «охру», при sat <25% в «нейтральный beige» (теряется
  ассоциация с документом).
- Accent hue 315° выбран после исключения исторически-архивных
  кандидатов: ink-blue 220° = конфликт с INFO/STALE, dark red 0° =
  конфликт с FAULT, dark green 150° = конфликт с OK. Wine/maroon
  315° остаётся в «архивно-винной» семье (сургучная печать) и чист
  по hue.
- BORDER `#9e957c` 2.64:1 к CARD — намеренно видимый, «линия
  линейки». Для light-тем BORDER-контраст 2.0–3.0 — норма.

**Trade-offs:**
- Wine-magenta accent — неожиданный цвет для «советской документации»
  на первый взгляд, но безопаснее и ассоциативно честнее чем red/blue
  альтернативы. Эстетически — это «печать на бумаге», не «штамп
  гост-красным».
- Если владелец хочет именно red stamp — придётся разморозить FAULT
  для этой палитры (большая инвазивность).

---

## 5. Light — Xcode (`xcode.yaml`)

**Ассоциативный якорь:** Apple Xcode / Finder / Developer Tools в
light-режиме — реальный инструмент владельца на MacBook M5.
Прагматика, без эстетического флёра.

**Ведущая ось:** cool off-white + pure white working surface + indigo
system accent. Apple pro-tool characteristic: минимум decoration,
максимум «technical clarity». Hue нейтралей 215° sat 20–30% —
микроскопический cool shift. FG `#1d2128` — neutral cool near-black,
не warm, не cold.

**Метрики:**
- Лестница SUNK 81.3 → PANEL 87.7 → BG 92.8 → CARD/ELEV 100%,
  Δ 5.2–7.2% (средняя)
- Амплитуда FG↔BG = 91.3% (высокая)
- FG/BG 15.05:1 · FG/CARD 16.15:1 · TEXT2/CARD 7.71:1 ·
  MUTED/CARD 3.85:1
- ACCENT/BG 6.55:1 · ACCENT/CARD 7.03:1 · ON_PRIMARY/ACCENT 7.03:1
- ACCENT 260° min-distance 33° до STALE
- Light STATUS на CARD: 5.84–8.42:1

**Обоснование choices:**
- Apple-native системный blue — около 210°, прямой конфликт со
  STATUS_INFO 214°. Пришлось сдвинуть в indigo 260° чтобы набрать
  ≥30° отступа. Результат — индиго, не «классический Apple blue».
  Эстетически: ближе к Swift logo purple territory чем к macOS
  accent blue. Owned trade-off.
- CARD = pure white (#ffffff) — Apple-характерно для working surface
  (текстовые редакторы, таблицы). На длинных сессиях может вызвать
  «snow fatigue», но это часть эстетики.
- Hue нейтралей 215° sat 25% — slight cool, не cold. При sat 0%
  («pure gray») тема теряет Apple-характер и становится generic.

**Trade-offs:**
- Chase-white CARD на 12-часовых кулдаун-сессиях может утомлять.
- Indigo вместо Apple-blue — формальное нарушение brand-авторства,
  но необходимое для safety.

---

## 6. Light — Braun (`braun.yaml`)

**Ассоциативный якорь:** Dieter Rams (Braun T3, ET66, SK4, TAM-1),
немецкий функционализм, Jony Ive's direct progenitor — эстетическая
ДНК ранней Apple до разбавления.

**Ведущая ось:** кремово-песочная база + геометрические видимые
borders + olive-moss accent. Hue нейтралей 45° sat 25% (меньше чем у
ГОСТ — ближе к «белой поверхности продукта», не к «старой бумаге»).
FG `#151412` — precise near-black, слегка тёплый. BORDER 2.42:1 —
выраженная геометрическая линия, Rams-характерная.

**Метрики:**
- Лестница SUNK 61.1 → PANEL 70.9 → BG 80.8 → CARD 92.2 → ELEV 97.2%,
  Δ 5.1–11.4% (крупная, видимая)
- Амплитуда FG↔BG = 80.1%
- FG/BG 15.05:1 · FG/CARD 17.04:1 · TEXT2/CARD 8.63:1 ·
  MUTED/CARD 4.22:1
- ACCENT/BG 4.82:1 · ACCENT/CARD 5.46:1 · ON_PRIMARY/ACCENT 5.89:1
- ACCENT 90° min-distance 52° до OK
- Light STATUS на CARD: 5.41–7.79:1

**Обоснование choices:**
- **Accent hue 90° — компромисс, не Braun-authentic.** Настоящая
  Braun-палитра продуктов использовала yellow/orange/red (ET66 calc,
  T3 radio, AB20 clock, TAM-1) — все три семьи заняты status-палитрой.
  Olive 90° — ближайшая «mid-century modern functional» семья, которая
  не конфликтует ни с одним статусом (52° от OK, 57° от WARNING).
  Читается как «moss/sage/forest-service» accent — не-Braun буквально,
  но Braun-adjacent по эстетическому классу.
- BG hue 43° sat 27% — теплее Xcode (cool), прохладнее ГОСТ (warm
  paper). «Industrial product surface» — ассоциация с powder-coated
  metal / matte plastic, не с бумагой.
- BORDER 2.42:1 — Rams-характерно видимая геометрическая линия.

**Trade-offs:**
- Accent не Braun-authentic. Если владелец конкретно хочет
  yellow/orange — только через разморозку WARNING/CAUTION, что
  семантически опаснее чем текущий компромисс.
- Тема ближе к «Braun-влияние» чем к «Braun-reproduction».

---

## Разморозка STATUS для light-тем (сводка ADR 001)

Полное обоснование в
[adr/001-light-theme-status-unlock.md](./adr/001-light-theme-status-unlock.md).
Здесь — сжатая таблица соответствия hex-значений:

| Token | dark hex | light hex | hue |
|---|---|---|---|
| STATUS_OK | `#4a8a5e` | `#2e6b45` | 139° |
| STATUS_WARNING | `#c4862e` | `#8c5a1c` | 33° |
| STATUS_CAUTION | `#b35a38` | `#9c4a2c` | 16° |
| STATUS_FAULT | `#c44545` | `#a53838` | 0° |
| STATUS_INFO | `#6490c4` | `#355e94` | 214° |
| STATUS_STALE | `#5a5d68` | `#4a4d58` | 227° |
| COLD_HIGHLIGHT | `#7ab8c4` | `#2f6876` | 190° |

**Инвариант:** hue токена одинаковый; lightness адаптирована под
substrate. Семантика («амбер = WARNING, красный = FAULT») сохраняется
1:1 — оператор, переключающийся с dark на light, видит те же цветовые
семьи в более тёмной яркости.

---

## Implementation checklist (для Claude Code)

1. **YAML-файлы** — уже созданы в `config/themes/`:
   - `signal.yaml`, `instrument.yaml`, `amber.yaml` (dark)
   - `gost.yaml`, `xcode.yaml`, `braun.yaml` (light)

2. **`_theme_loader.py`** — проверить что новые имена принимаются
   без правок (loader читает каждый YAML из `config/themes/`
   generic, не hardcoded список). Если hardcoded — расширить.

3. **Settings → Тема menu** — добавить radio-selection пункты для
   всех шести. Порядок display: сначала все dark, потом все light
   (dark: `default_cool`, `anthropic_mono`, `signal`, `instrument`,
   `amber`; light: `warm_stone`, `ochre_bloom`, `taupe_quiet`,
   `rose_dusk`, `gost`, `xcode`, `braun`).

4. **Tests:**
   - `tests/design_system/test_theme_loader.py` — добавить test
     что все шесть новых тем загружаются без ошибок и дают
     полный 25-token комплект.
   - `tests/design_system/test_theme_contrast.py` — для каждой
     light-темы проверить что STATUS/CARD ≥4.5:1 (см. Таблицу 2
     в ADR).
   - Hue-collision test ≥30° — все шесть проходят; подтвердить
     регрессией.

5. **Documentation:**
   - `docs/design-system/tokens/colors.md` — обновить раздел
     STATUS с указанием на ADR 001.
   - `CHANGELOG.md` → `[Unreleased]` → `### Added`:
     «Six new themes: signal, instrument, amber (dark); gost,
     xcode, braun (light). STATUS palette unlocked for lightness
     (hue still locked) per ADR 001 to restore AA contrast on
     light substrates.»

---

## Pre-release smoke list

После Settings menu wiring владелец даст screenshot-feedback с
живых дашбордов. Возможные точки уточнения (все — однострочные
правки в YAML):

- **Сигнал:** удерживает ли UI иерархию без видимых бордюров.
  Если нет — поднять BORDER до `#1e2028` (1.3:1 vs CARD).
- **Приборный:** не перегружает ли ladder-плотность дашборд.
  Если да — уменьшить шаги: `BG: #1a1c20 → #181a1e`,
  `CARD: #2c3037 → #282c32`.
- **Янтарь:** удерживает ли low-amplitude FG читаемость. Если
  нет — поднять FG до `#e0d5c6`.
- **ГОСТ:** при возражениях на wine-magenta accent — альтернатива
  deep ink-brown `#4a3424` (hue 25°, 8° от CAUTION — borderline,
  потребуется test-escape).
- **Xcode:** если пользователь хочет ближе к native Apple blue
  — сдвинуть на 250° (borderline 24° до STALE, потребуется
  test-escape).
- **Braun:** при возражениях на olive — альтернатива deep
  Klein-blue `#1a3aa8` (230°, 3° от INFO — потребуется полный
  override).

---

## Ссылки

- **ADR 001:** [adr/001-light-theme-status-unlock.md](./adr/001-light-theme-status-unlock.md)
- **YAML-файлы:** `config/themes/{signal,instrument,amber,gost,xcode,braun}.yaml`
- **Предыдущий handoff (v1):** ссылается на существующие шесть
  палитр в `config/themes/`, status-policy старого handoff
  частично superseded ADR 001.
- **Token authority:** `docs/design-system/tokens/colors.md`
- **Test infrastructure:** `tests/design_system/`
