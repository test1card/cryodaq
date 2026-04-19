# Theme Follow-Ups (post-landing debt)

Minor issues и design-debt, обнаруженные после landing шести новых
тем (`26059fa`, `e015295`, 2026-04-19) или унаследованные от
предыдущих packs (pre-ADR 001).

Статус каждого: **tracked, не блокирующий для Phase II/III**.

---

## FU-THEME-1 — warm_stone ACCENT ↔ STATUS_OK hue collision

**Severity:** LOW (cosmetic, pre-existing legacy bug)
**Introduced:** до 2026-04-19 (landed с первой волной theme packs
`9ac307e`, 2026-04-18)
**Discovered:** 2026-04-19 Codex sweep при landing шести новых тем.

### Детали

Pre-ADR pack `warm_stone.yaml` имеет ACCENT и STATUS_OK на одном
hue ≈138.8°. Это нарушает design rule «ACCENT hue ≥30° от каждого
STATUS hue» установленное в v1.0.1 handoff.

`config/themes/warm_stone.yaml:21` — ACCENT `#3c8256` (green).
`config/themes/warm_stone.yaml:28` — STATUS_OK `#4a8a5e` (green).

### Impact

На UI операторa в теме `warm_stone`:
- «primary action» кнопка (ACCENT) и «OK status» badge
  визуально неотличимы.
- Не safety-critical — оператор не перепутает действие с
  состоянием, они в разных контекстах.
- Cosmetic — обе фигуры green, не читается как bug на первый
  взгляд.

### Test coverage

`tests/gui/test_theme_loader.py::test_accent_hue_distance_from_status`
— scoped только на шесть ADR-001 packs (`signal`, `instrument`,
`amber`, `gost`, `xcode`, `braun`). Pre-ADR packs НЕ проверяются.
При retrofit — scope теста расширить на все 12 packs.

### Fix direction

Один из:

1. **Shift ACCENT.** Сдвинуть warm_stone ACCENT на другой hue —
   вероятно hue 25° (amber-orange), чтобы не конфликтовать ни с
   STATUS_OK (139°), ни с STATUS_WARNING (33°). Запрашивает
   architect approval т.к. меняет ощущение темы.
2. **Оставить как есть.** warm_stone — legacy pack, мало кто
   выбирает, retrofit создаёт noise без user value.

**Предпочтение architect:** вариант 2, revisit если поступит
жалоба от оператора.

---

## FU-THEME-2 — Signal theme BG below recommended floor

**Severity:** INFO (intentional design choice, not a bug)
**Introduced:** 2026-04-19 при landing `signal.yaml` (commit `26059fa`).

### Детали

`config/themes/signal.yaml` — BG `#070809` (luminance ≈0.24%).
Design-system rule §7.6 запрещает pure black BG и рекомендует
luminance ≥0.5% для избежания OLED edge-sharpening.

`signal.yaml` сознательно нарушает это правило как часть
эстетической концепции (Pan Sonic / Raster-Noton визуальный
язык).

### Impact

- На IPS-мониторах в лаборатории — норм.
- На OLED-дисплеях MacBook Pro / Studio Display — может давать
  edge sharpening на thin UI lines.

### Fix direction

Operator-side preference. Если пользуешься `signal` на OLED и
замечаешь sharpening — выбирай `default_cool` или
`anthropic_mono`. В HANDOFF_THEMES_V2.md §1 «Trade-offs» это
уже задокументировано.

---

## FU-THEME-3 — dark-theme STATUS visibility на near-black BG

**Severity:** LOW (potential issue, not yet observed)
**Discovered:** 2026-04-19 при анализе `signal.yaml`.

### Детали

На очень тёмных темах (`signal` BG 0.24%, `anthropic_mono` BG
~1%) dark-STATUS значения могут быть недостаточно контрастными
для optimal visibility. ADR 001 рассматривал этот вопрос и
отложил — нужны метрики с реальных дисплеев.

### Action

После того как оператор использует `signal` несколько недель и
даст feedback — собрать screenshots с живых данных (OK badge,
WARNING, FAULT) и проверить читаемость. Если визуально теряется
— открыть отдельное ADR о L-bump для dark-themes с экстремально
низкой BG luminance.

Не приоритетно до получения feedback.

---

## Ссылки

- `docs/design-system/HANDOFF_THEMES_V2.md`
- `docs/design-system/adr/001-light-theme-status-unlock.md`
- `config/themes/*.yaml`
- `tests/gui/test_theme_loader.py`
