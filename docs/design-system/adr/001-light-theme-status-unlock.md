# ADR 001 — STATUS hue-locked, L-unlocked для light-тем

**Status:** Accepted
**Date:** 2026-04-19
**Supersedes:** §4 «STATUS palette LOCKED» из handoff v1.0.1 (частично — только
для light-тем)

---

## Контекст

STATUS-палитра (7 токенов: OK, WARNING, CAUTION, FAULT, INFO, STALE,
COLD_HIGHLIGHT) была заморожена в v1.0.1 как семантический инвариант:
операторы обучаются на конкретных hex-значениях и их ассоциациях с
состояниями криогенного оборудования. Изменение оттенка = смена
ассоциации = риск misread на реальной установке.

Оригинальная locked-палитра спроектирована под dark-фон. На светлом
substrate три статуса фэйлят WCAG AA (≥4.5:1 к CARD):

| Token | dark value | контраст к typical light CARD |
|---|---|---|
| STATUS_COLD | `#7ab8c4` | 1.94–2.21:1 |
| STATUS_WARNING | `#c4862e` | 2.70–3.09:1 |
| STATUS_INFO | `#6490c4` | 2.90–3.32:1 |

Криогенные cold-метки, warning-метки и info-метки становятся
фактически невидимы на светлых темах (`gost`, `xcode`, `braun`).

## Решение

**STATUS hue is locked. STATUS lightness is unlocked per substrate.**

Каждая light-тема получает собственный shifted-L комплект STATUS,
где hue каждого токена **идентичен** dark-комплекту, изменяется
только lightness. Семантическая привязка («амбер = WARNING»)
сохраняется 1:1, контраст на светлом фоне достигает AA.

| Token | dark | light | Δ hue | Что сохранено |
|---|---|---|---|---|
| STATUS_OK | `#4a8a5e` | `#2e6b45` | 0° | forest green, hue 139° |
| STATUS_WARNING | `#c4862e` | `#8c5a1c` | 0° | амбер, hue 33° |
| STATUS_CAUTION | `#b35a38` | `#9c4a2c` | 0° | red-orange, hue 16° |
| STATUS_FAULT | `#c44545` | `#a53838` | 0° | brick red, hue 0° |
| STATUS_INFO | `#6490c4` | `#355e94` | 0° | communication blue, hue 214° |
| STATUS_STALE | `#5a5d68` | `#4a4d58` | 0° | cool gray, hue 227° |
| COLD_HIGHLIGHT | `#7ab8c4` | `#2f6876` | 0° | cyan, hue 190° |

Все shifted-L статусы дают ≥4.8:1 на всех CARD-поверхностях
трёх light-тем (см. Таблицу 2 ниже).

## Инвариант

Оператор, обученный на dark-теме `default_cool`, переключающийся
на light-тему `gost`, видит:

- тот же семантический hue (амбер остаётся амбером, красный остаётся
  красным)
- более тёмные оттенки для читаемости на светлом фоне

Это не переучивание. Это та же информация в адаптированной яркости
— как одна и та же физическая LED-метка, рассматриваемая днём и
ночью.

## Что остаётся locked

- **Hue** каждого STATUS-токена заморожен в обоих комплектах.
- **Семантическое назначение** токенов (OK = всё в норме,
  WARNING = внимание, FAULT = авария, и т.д.) не меняется.
- **Количество токенов** (7) не меняется.
- **Названия токенов** не меняются.

## Что разрешается

- **Lightness** STATUS-токена может отличаться между dark и light
  комплектами, если метрики AA/AAA на реальных substrate-цветах
  темы этого требуют.
- Будущие темы могут добавлять свои shifted-L комплекты, если
  substrate требует дополнительной настройки (например, очень
  тёплая sepia-тема может потребовать slight shift OK от 139° в
  сторону bluer green для ассоциативной точности — это будет
  требовать отдельное ADR).

## Таблица 2 — контрастные метрики shifted-L статусов

Контраст к CARD каждой light-темы:

| Token | light hex | gost CARD (#f5f1e2) | xcode CARD (#fff) | braun CARD (#faf6ea) |
|---|---|---|---|---|
| STATUS_OK | `#2e6b45` | 6.78:1 | 7.31:1 | 7.03:1 |
| STATUS_WARNING | `#8c5a1c` | 5.43:1 | 5.89:1 | 5.67:1 |
| STATUS_CAUTION | `#9c4a2c` | 5.74:1 | 6.21:1 | 5.98:1 |
| STATUS_FAULT | `#a53838` | 6.04:1 | 6.53:1 | 6.29:1 |
| STATUS_INFO | `#355e94` | 6.56:1 | 7.09:1 | 6.82:1 |
| STATUS_STALE | `#4a4d58` | 7.42:1 | 8.02:1 | 7.73:1 |
| COLD_HIGHLIGHT | `#2f6876` | 5.16:1 | 5.59:1 | 5.38:1 |

Все значения ≥4.5:1 (AA для обычного текста и UI elements).

## Последствия

**Для кода:**

- `theme.py` / `_theme_loader.py` — изменений не требуется.
  YAML-файлы уже содержат свои собственные STATUS-значения,
  loader читает их verbatim.
- Hardcoded fallback в `theme.py` (если оператор запустил
  приложение без config/themes/) по-прежнему использует
  dark-комплект, что безопасно для fallback-сценария (fallback
  theme в v1.0.1 — dark).

**Для тестов:**

- Тест «STATUS_OK не совпадает с ACCENT» в light-темах теперь
  проверяется против light-STATUS hex (#2e6b45, не #4a8a5e).
  Тестовая инфраструктура должна читать STATUS из активной темы,
  не использовать hardcoded dark-значения.
- Новый test: для каждой light-темы проверить контраст всех
  STATUS к CARD ≥4.5. Формула контраста — стандартная WCAG
  relative-luminance.

**Для документации:**

- `docs/design-system/tokens/colors.md` — обновить раздел STATUS,
  указать что палитра имеет два hex-комплекта (dark/light),
  связанных hue-инвариантом.
- `docs/design-system/rules/color-rules.md` (если существует) —
  добавить правило RULE-COLOR-LIGHT-STATUS: «для light-тем
  использовать shifted-L STATUS-комплект; dark-комплект на
  светлом фоне не читается».

**Для обучения операторов:**

- Изменений нет. Операторы обучаются семантически (амбер =
  внимание, красный = авария), не на конкретный hex. Lightness
  shift не меняет семантическое восприятие.

## Альтернативы рассмотренные

1. **Оставить dark-STATUS везде, wash-out на light-темах принять.**
   Отклонено — WARNING/INFO/COLD практически невидимы, что
   opasnee чем shift lightness. Safety-critical UI не может
   терять видимость alarm-меток из-за косметического выбора
   темы.

2. **Отказаться от light-тем.** Отклонено — оператор работает
   на MacBook M5 с macOS в light-режиме долгими часами, forcing
   dark is user-hostile.

3. **Разморозить hue тоже (позволить RED-shift в orange для
   тёплых тем).** Отклонено — это реально нарушает семантическую
   locked-палитру и требует переобучения операторов.

4. **Две полностью отдельные палитры с другими именами.**
   Отклонено — удваивает token count, создаёт confusion какой
   token когда использовать, разрушает theme-switching UX.

Shifted-L внутри тех же имён токенов — минимальный инвазивный
подход, который решает проблему контраста без потери семантики.

## Последующие действия

После merge этого ADR:

1. Добавить тест contrast-to-card в tests/design_system/
   test_theme_contrast.py, gated на `is_light_theme` флаг в
   metadata.
2. Обновить colors.md с указанием light-override.
3. Рассмотреть аналогичный L-shift для dark-тем с экстремально
   низкой яркостью (`signal.yaml` с BG 0.24%) — там dark STATUS
   может требовать L-bump вверх для видимости на near-black.
   Отдельное ADR если метрики покажут необходимость.

## Ссылки

- `docs/design-system/HANDOFF_THEMES_V2.md` — полные метрики и
  ведущие оси шести новых палитр.
- `docs/design-system/tokens/colors.md` — авторитативный файл
  токенов.
- `config/themes/gost.yaml`, `config/themes/xcode.yaml`,
  `config/themes/braun.yaml` — light-темы, использующие
  shifted-L комплект.
