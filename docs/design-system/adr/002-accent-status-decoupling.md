# ADR 002 — ACCENT / STATUS decoupling + neutral interaction tokens

**Status:** Accepted
**Date:** 2026-04-19
**Scope:** Phase III.A — DS semantic cleanup blocking III.B/C/D.

---

## Контекст

К концу Phase II все overlays мигрированы на DS v1.0.1-токены и
реэкспортированы из `src/cryodaq/gui/shell/overlays/`. Но один
семантический conflict остался: `STATUS_OK` («безопасно / норма /
здоров») использовался в:

- backgrounds primary-кнопок (`«Старт»`, `«Сохранить»`, `«Экспорт
  CSV»`, `«Применить»`, etc);
- mode-badge «Эксперимент» в `TopWatchBar` и `ExperimentCard`;
- QProgressBar::chunk (прогресс фоновой задачи);
- active-tab indicator в нескольких overlay (косвенно через
  primary-style helper).

Плюс в двух темах (`warm_stone`, `taupe_quiet`) `ACCENT === STATUS_OK`
буквально — один и тот же hex. В одной из них (`taupe_quiet`) с
комментарием «matches STATUS_OK by design», что теперь читается как
архивный компромисс.

**Проблема для оператора:** когда safety-green одновременно кодирует
«канал здоров» и «я выделил эту вкладку / нажал кнопку / попал в
experiment mode», операторский парсинг ломается. Безопасное состояние
и UI-активация сливаются визуально.

Плюс два light-theme паттерна уже столкнулись с похожей проблемой:
`braun` ACCENT `#476f20` оказался олив hue ≈90°, при STATUS_OK hue
≈143° → 53° расстояния, на грани confusable.

## Решение

Ввести два **нейтральных interaction-токена**, decouple'ить
`ACCENT` от STATUS-семантики в 11 темах (тема `default_cool`
остаётся с историческим indigo `#7c8cff`).

### Новые токены

```yaml
# В каждой theme YAML, Phase III.A
SELECTION_BG: "<тёмный ненасыщенный нейтраль, ближе к FG чем к BG>"
FOCUS_RING:   "<средне-нейтральный, видимый контур>"
```

Назначение:
- `SELECTION_BG` — фон выделенной строки / активного item'а / selected
  state'а. Никогда не status.
- `FOCUS_RING` — обводка input'а / button'а на focus. Никогда не status.

Для dark тем оба — затемнённые хроматически-нейтральные оттенки ближе
к FOREGROUND; для light тем (gost / xcode / braun) — светлые shadow-
tint'ы.

### Миграция

| Сайт | Было | Стало |
|---|---|---|
| `operator_log_panel._style_button("primary")` | STATUS_OK + ON_PRIMARY | ACCENT + ON_ACCENT |
| `archive_panel._style_button("primary")` | STATUS_OK + ON_PRIMARY | ACCENT + ON_ACCENT |
| `calibration_panel._style_button("primary")` | STATUS_OK + ON_PRIMARY | ACCENT + ON_ACCENT |
| `conductivity_panel._style_button("primary")` | STATUS_OK + ON_PRIMARY | ACCENT + ON_ACCENT |
| `keithley_panel._style_button("primary")` | STATUS_OK + ON_PRIMARY | ACCENT + ON_ACCENT |
| `conductivity_panel` auto-sweep progress chunk | STATUS_OK bg | ACCENT bg |
| `TopWatchBar` mode badge «Эксперимент» | STATUS_OK bg + ON_DESTRUCTIVE fg (filled pill) | SURFACE_ELEVATED bg + FOREGROUND fg + BORDER_SUBTLE (low-emphasis chip) |
| `ExperimentCard` mode badge (mirror) | STATUS_OK bg + ON_DESTRUCTIVE fg | SURFACE_ELEVATED bg + FOREGROUND fg + BORDER_SUBTLE |
| `TopWatchBar` mode badge «Отладка» | STATUS_CAUTION solid pill | SURFACE_ELEVATED bg + STATUS_CAUTION fg + STATUS_CAUTION border (keeps operator-attention semantics via color but de-emphasises shape) |
| `ExperimentCard` mode badge «Отладка» (mirror) | STATUS_CAUTION solid pill | SURFACE_ELEVATED bg + STATUS_CAUTION fg + STATUS_CAUTION border |

**НЕ затронуто** (остаётся STATUS_OK):
- `bottom_status_bar` connection + safety labels
- `top_watch_bar` engine-state + channel-status labels
- `conductivity_panel` stability / steady-state / coverage banners
- `instruments_panel._health_color` helper
- `calibration_panel.CoverageBar` dense segments (spec explicitly
  excludes — dense IS a status)
- `keithley_panel` channel state (`on`/`fault`) indicators
- `phase_stepper` current-phase border (state indicator, not UI
  activation)
- `experiment_overlay` current-phase pill border (same precedent)
- `sensor_cell` ChannelStatus.OK colour
- `SeverityChip` widget (alarm v1 / v2)

### Per-theme ACCENT recalibration

| Theme | Prior ACCENT | Action | New ACCENT |
|---|---|---|---|
| default_cool | `#7c8cff` indigo | **KEEP** (historical baseline) | `#7c8cff` |
| warm_stone | `#4a8a5e` = STATUS_OK | **REPLACE** (bug) | `#b89e7a` warm sand |
| anthropic_mono | `#d97757` terracotta | **KEEP** (brand) | — |
| ochre_bloom | `#a39450` olive ≈49° | **KEEP** (distance 90° from STATUS_OK 139°) | — |
| taupe_quiet | `#4a8a5e` = STATUS_OK | **REPLACE** (bug, «by design» comment removed) | `#a39482` warm taupe |
| rose_dusk | `#d07890` dusty rose | **KEEP** | — |
| signal | `#e046a0` magenta | **KEEP** (theme signature) | — |
| instrument | `#ad85d6` violet | **KEEP** | — |
| amber | `#a878b0` wine-plum | **KEEP** | — |
| gost | `#772262` wine-maroon | **KEEP** (theme signature) | — |
| xcode | `#6839c6` indigo | **KEEP** (theme signature) | — |
| braun | `#476f20` olive ≈90° | **REPLACE** (invariant violation: 53° from light STATUS_OK 143°) | `#6a7530` moss-olive ≈70° |

## Инварианты (tested)

1. **SELECTION_BG и FOCUS_RING обязательны во всех 12 packs** —
   `_theme_loader.REQUIRED_TOKENS` enforces load-failure иначе.
2. **SELECTION_BG и FOCUS_RING distinct from STATUS_OK** — либо hue
   distance ≥30°, либо luminance distance ≥0.15.
3. **ACCENT hue distance from STATUS_OK ≥60°** во всех 12 темах.
   `default_cool` исторический indigo (230°, vs STATUS_OK 138°, delta
   92°) удовлетворяет естественно.
4. **ACCENT hue distance ≥30° from every STATUS hue** для
   ADR-001-scope packs (signal / instrument / amber / gost / xcode /
   braun) — тот же инвариант что в ADR 001, не ослаблен.
5. **default_cool ACCENT preserved as `#7c8cff`** — explicit regression
   guard (ADR 002 test).
6. **warm_stone + taupe_quiet ACCENT ≠ STATUS_OK** — explicit
   regression guard.

## Tooling

`tools/theme_previewer.py` — новый standalone PySide6 script:
`python -m tools.theme_previewer`. Рендерит grid 4×3 с 12 preview
tile'ами, каждый демонстрирует новые ACCENT / SELECTION_BG /
FOCUS_RING + STATUS_OK chip для визуального сравнения. Architect
использует для approve/veto per-theme выбора. Не operator-facing,
лежит в `tools/` а не в `src/cryodaq/gui/`.

## Что НЕ затронуто

- `PLOT_LINE_PALETTE` — отдельная desaturated палитра, не пересекается
  с STATUS семантикой.
- Status-tier hex values — locked across tems per ADR 001. Этот ADR
  не трогает сами STATUS-цвета, только их использование в UI.
- Alarm engine / calibration engine / experiment manager — только DS
  косметика.
- Public API of overlays — unchanged.

## References

- `docs/design-system/adr/001-light-theme-status-unlock.md` — prior
  status-palette ADR.
- `docs/design-system/rules/color-rules.md` RULE-COLOR-004 — ACCENT
  reserved for focus/selection (now properly enforced).
- `docs/design-system/tokens/colors.md` — token catalog (updated for
  SELECTION_BG / FOCUS_RING).
- `docs/design-system/MANIFEST.md` — token inventory.
