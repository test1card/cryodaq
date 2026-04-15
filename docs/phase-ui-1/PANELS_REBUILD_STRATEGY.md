# Стратегия перестройки legacy overlay panels

## 1. Покрытие документа

Этот документ — delta поверх трёх авторитетных источников:

| Источник | Отвечает за | Что добавляет этот документ |
|----------|-------------|---------------------------|
| `PHASE_UI1_V2_WIREFRAME.md` | Архитектура, 7 phase modes, click budget, component inventory | Актуальный triage каждой panel + порядок блоков после B.5 |
| `DESIGN_SYSTEM_FINDINGS.md` | Palette, typography, anti-patterns, skill extraction | Skill UX/chart findings per panel category, protocol |
| `design-system/MASTER.md` | Locked token reference | Не дублируется, ссылки по имени токена |

Документ не повторяет содержание источников. Ссылки по формату
`wireframe §N` / `FINDINGS §section` / `MASTER §section`.

**Статус:** ветка `master`, последний коммит `537d85d` (Block B.5),
baseline tests 999 passed / 2 skipped.

---

## 2. Workflow inventory

Три workflow из `operator_manual.md` §7 + один инженерный.

### 2.1. Запуск и проведение эксперимента

**Panels:** PhaseAwareWidget (дашборд) → ExperimentWorkspace (overlay)
→ OperatorLogPanel → AnalyticsPanel → ConductivityPanel → KeithleyPanel

**Частота:** 2-3 раза в месяц, длительность 4-7 дней каждый.

**Критичность:** Critical — это основная операторская задача.

### 2.2. Мониторинг во время эксперимента (непрерывный)

**Panels:** Dashboard (sensor grid, plots, phase widget, context strip)
→ AlarmPanel (по событию) → InstrumentStatus (по проблеме)

**Частота:** Непрерывно в течение 4-7 дней. Оператор проверяет экран
каждые 15-30 минут.

**Критичность:** Critical — ambient awareness workflow, дашборд уже
реализован (B.1-B.5).

### 2.3. Завершение и архивирование

**Panels:** ExperimentWorkspace (finalize) → ArchivePanel (проверка
артефактов, повторная генерация отчёта)

**Частота:** 2-3 раза в месяц, 5-10 минут за сессию.

**Критичность:** High — без этого эксперимент формально не закрыт.

### 2.4. Калибровка приборов

**Panels:** CalibrationPanel (3 режима: Setup → Acquisition → Results)

**Частота:** 1-2 раза в год, сессия 2-4 часа.

**Критичность:** Low (частота) но High (ценность результата).

---

## 3. Шесть UX-правил из мануала

Из `operator_manual.md` §8 «Что считать нормальным, а что нет» —
конвертировано в позитивные design rules для всех panels.

**R1. Backend truth first.** GUI показывает состояние только когда
имеет подтверждение от backend. Нет backend status → нет ON/healthy
индикатора. (Skill UX: «Loading States HIGH — Show feedback during
async operations».)

**R2. Файловая честность.** Если артефакт (отчёт, экспорт) не существует
на диске, GUI не показывает его как существующий. Нет файла → явное
«отсутствует». (Skill UX: «Submit Feedback HIGH — Show loading then
success/error state».)

**R3. Отмена = отмена.** Закрытие file dialog не запускает backend
работу. Cancel действия не должно иметь side effects.

**R4. Transparent fallback.** Если calibration runtime откатился на
KRDG вместо SRDG + curve, GUI показывает это явно, не прячет за
оптимистичным «applied».

**R5. Engine-GUI separation.** Закрытие GUI не останавливает engine.
Панели не должны быть источником истины для runtime state.

**R6. Mode awareness.** Режим Отладка не создаёт архивных записей.
GUI должен показывать текущий режим оператору. (Текущий статус: gap —
см. §5.)

---

## 4. Per-panel triage

### Логика triage

- **Rebuild** — Critical/High workflow centrality + Heavy interaction
- **Wrap** — Medium centrality + Medium interaction
- **Restyle** — Low/Rare centrality ИЛИ Light interaction

### Приоритет Владимира

experiment card → keithley → analytics + plots → conductivity → log
→ alarms → sensor diag.

### Таблица

| Panel | Файл | Строк | setStyleSheet | Workflow | Взаимодействие | Подход | Размер | Обоснование | Skill UX rules | Chart patterns |
|-------|------|-------|---------------|----------|---------------|--------|--------|-------------|---------------|---------------|
| ExperimentWorkspace | experiment_workspace.py | 897 | 8 | Critical | Heavy (7 ZMQ cmds, mode toggle, card view, phases) | Rebuild | XL | Центральный workflow, 8 QGroupBox, дублирует phase display с B.5, содержит mode toggle | Forms: Submit Feedback HIGH; Forms: Labels HIGH | — |
| KeithleyPanel | keithley_panel.py | 586 | 6 | Critical | Heavy (5 ZMQ cmds, dual-channel, start/stop/emergency) | Rebuild | Large | Dual-SMU control, operator_manual §4.2, wireframe §8.3 | Loading States HIGH (command feedback); Navigation: context preservation | — |
| AnalyticsPanel | analytics_panel.py | 521 | 12 | High | Light (passive, on_reading only, 0 commands) | Restyle | Medium | 12 hardcoded styles — наибольшая стилистическая задолженность, но layout рабочий | — | Time series: Line Chart; Anomaly: Line with Highlights; Forecast: Line with Confidence Band |
| ConductivityPanel | conductivity_panel.py | 1068 | 4 | High | Heavy (auto-measurement FSM, Keithley cmds) | Wrap | XL | Самая большая панель, 2 QGroupBox, сложная FSM — wrap сохраняет логику, обновляет chrome | Forms: Submit Feedback HIGH; Loading States HIGH | — |
| AlarmPanel | alarm_panel.py | 378 | 3 | High | Medium (3 cmds: ack/status) | Wrap | Medium | Рабочая логика ack/clear, нужны empty states и design tokens | Loading Indicators HIGH | — |
| OperatorLogPanel | operator_log_panel.py | 171 | 0 | Medium | Light (2 cmds, простая форма) | Restyle | Small | Самая простая панель, 0 setStyleSheet, только form + list | Forms: Labels HIGH | — |
| ArchivePanel | archive_panel.py | 529 | 0 | Medium | Medium (filter form + result list, 2 cmds) | Wrap | Large | 5 QGroupBox для фильтров, нужны empty states per wireframe §8.9 | Forms: Submit Feedback HIGH; Table Handling MEDIUM | — |
| CalibrationPanel | calibration_panel.py | 499 | 5 | Low (1-2/год) | Heavy (3-mode FSM, 7 QGroupBox, 2 QStackedWidget) | Restyle | Medium | Сложная FSM уже работает, frequency низкая — restyle tokens достаточно | Forms: Submit Feedback HIGH | — |
| SensorDiagPanel | sensor_diag_panel.py | 211 | 2 | Low | Light (1 cmd, table) | Restyle | Small | Простая таблица диагностики | Table Handling MEDIUM | — |
| InstrumentStatus | instrument_status.py | 308 | 2 | Medium | Light (passive + liveness timer) | Restyle | Small | Card-based, 2 setStyleSheet, layout рабочий | Loading Indicators HIGH | — |

---

## 5. Mode toggle gap

### Требование

`operator_manual.md` §5: «Главная operator workflow должна различать
режимы Эксперимент и Отладка. В режиме Отладка не должны создаваться
архивные карточки экспериментов и запускаться автоматические отчёты.»

### Текущий статус

**Backend:** полностью реализован. `AppMode` enum (DEBUG / EXPERIMENT)
в `experiment.py:62`. ZMQ команды `get_app_mode` и `set_app_mode`
в `engine.py:394-405`. Состояние персистится через `ExperimentState`.

**Legacy GUI:** mode toggle есть в `experiment_workspace.py:610-640` —
метка «ЭКСПЕРИМЕНТ» / «ОТЛАДКА» и кнопка переключения.

**Новый GUI (MainWindowV2):** mode toggle **не поверхностный**.
TopWatchBar не показывает текущий mode. PhaseAwareWidget не учитывает
mode при отображении. DashboardView не знает о mode.

### Рекомендация

Первый блок новой последовательности. Маленький scope:
- Badge в TopWatchBar zone 2: «ОТЛАДКА» жёлтым или «ЭКСП» зелёным
- Чтение `app_mode` из `/status` response (уже есть в payload)
- Без toggle UI (toggle остаётся в ExperimentWorkspace до его Rebuild)

Это закрывает safety gap без большого рефакторинга.

---

## 6. Обновлённая последовательность блоков

Продолжение от B.5 (текущий HEAD).

### B.6 — QuickLogBlock (Small, 1 сессия)

**Подход:** новый виджет, заменяет placeholder quickLogZone в
DashboardView.

**Workflow gaps:** запись заметки оператора прямо с дашборда (без
перехода в overlay).

**Зависимости:** нет (ZMQ endpoint log_entry существует).

**Skill queries для спеки:** `"form input submit inline compact"
--domain ux`, `"collapsible expand collapse toggle" --domain ux`.

### B.7 — Mode Toggle Badge (Small, 0.5 сессии)

**Подход:** расширение TopWatchBar — badge из `app_mode` в `/status`.

**Workflow gaps:** safety gap §5 мануала.

**Зависимости:** нет.

**Skill queries:** `"status badge indicator state" --domain ux`.

### B.8 — ExperimentWorkspace Rebuild (XL, 3-4 сессии)

**Подход:** Rebuild. Новый ExperimentOverlay по wireframe §8.1.
Metadata card + phase timeline + notes + artifacts + «Завершить».

**Workflow gaps:** создание/управление/финализация эксперимента в новом
дизайне.

**Зависимости:** B.7 (mode toggle видимый оператору), B.6 (quick log
для notes interplay).

**Skill queries:** `"form card metadata edit save" --domain ux`,
`"timeline vertical progress history" --domain ux`.

### B.9 — KeithleyPanel Rebuild (Large, 2-3 сессии)

**Подход:** Rebuild. Dual-column smua/smub, big readouts V/I/R/P,
2x2 plots per channel по wireframe §8.3.

**Workflow gaps:** управление источником мощности в новом дизайне.

**Зависимости:** нет (standalone overlay).

**Skill queries:** `"control panel start stop emergency" --domain ux`,
`"real-time value readout" --domain ux`. Chart: `"real-time gauge
meter" --domain chart`.

### B.10 — Restyle batch (Medium, 1-2 сессии)

**Подход:** Restyle. Один блок для всех Restyle-панелей:
AnalyticsPanel, OperatorLogPanel, CalibrationPanel, SensorDiagPanel,
InstrumentStatus.

**Scope:** замена hardcoded цветов на theme.* токены, замена
hardcoded шрифтов, WA_StyledBackground, #objectName selectors. Без
изменения layout или логики.

**Workflow gaps:** визуальная консистентность.

**Зависимости:** нет.

**Skill queries:** `"consistency design system tokens" --domain ux`.

### B.11 — ConductivityPanel Wrap (XL, 2-3 сессии)

**Подход:** Wrap. Существующая FSM логика остаётся, обёртка с
group headers, design system chrome, по wireframe §8.5.

**Workflow gaps:** теплопроводность в новом дизайне.

**Зависимости:** B.9 (Keithley cmds shared).

**Skill queries:** `"form wizard multi-step state machine"
--domain ux`, `"group section header divider" --domain ux`.

### B.12 — AlarmPanel Wrap (Medium, 1-2 сессии)

**Подход:** Wrap. Empty states, active/history sections по
wireframe §8.6.

**Workflow gaps:** управление тревогами в новом дизайне.

**Зависимости:** нет.

**Skill queries:** `"empty state no data placeholder" --domain ux`,
`"alert notification priority" --domain ux`.

### B.13 — ArchivePanel Wrap (Large, 2 сессии)

**Подход:** Wrap. Filter card + two-column results по wireframe §8.9.

**Workflow gaps:** поиск и просмотр архивных экспериментов.

**Зависимости:** B.8 (experiment card format compatibility).

**Skill queries:** `"search filter results list card" --domain ux`,
`"data table sortable" --domain ux`.

### B.14 — Legacy cleanup (Medium, 1-2 сессии)

**Подход:** удаление. Убрать старые Inter/JetBrainsMono шрифты,
backwards-compatible aliases из theme.py, autosweep_panel.py,
_ZONES stale labels, dead code after all panels migrated.

**Зависимости:** все предыдущие блоки.

### B.15 — Lab PC calibration (Medium, 1-2 сессии)

**Подход:** deploy на лаб PC, визуальная калибровка pixel values,
type scale, spacing. Итеративно.

**Зависимости:** B.14 (чистый codebase).

---

## 7. Skill usage protocol

### Per-block pre-investigation (обязательно)

Каждый блок B.6+ должен включить в pre-investigation:

1. 1-3 skill UX queries scoped к категории панели:
   - Forms для dialog/editor panels
   - Tables для archive/log/diagnostics
   - Alerts для alarm panel
   - Loading для любой панели с async operations
2. 1-2 skill chart queries если панель содержит data viz
3. Один skill style query для подтверждения консистентности с
   adopted Real-Time Monitoring + Data-Dense Dashboard hybrid

Команда:
```
python3 /Users/vladimir/Downloads/ui-ux-pro-max-skill-2.5.0/src/ui-ux-pro-max/scripts/search.py "query" --domain ux|chart|style -n N
```

### Что берётся из skill output

- HIGH/CRITICAL severity findings → обязательные правила в блок-спеке
- Chart type recommendation → если панель содержит data viz
- Anti-patterns to avoid → cross-reference с rejection list в
  DESIGN_SYSTEM_FINDINGS

### Что игнорируется из skill output

- Цветовые рекомендации (locked в MASTER.md)
- Шрифтовые рекомендации (Fira Code + Fira Sans locked)
- Spacing values (8px grid locked)
- Анимации pulse/blink/glow (rejected в B.4.5, FINDINGS §Anti-patterns)
- Style recommendations противоречащие adopted hybrid

### Conflict resolution

Если skill finding противоречит locked design system → local wins.
Конфликт логируется в блок-спеке для traceability. Обнаруженные
конфликты из текущего pre-investigation:

1. Real-Time Monitoring style: «alert pulse/glow, blink animation» →
   rejected (FINDINGS §Anti-patterns rejected)
2. Chart color guidance: #0080FF / #FF0000 / #FFA500 →
   contradict desaturated palette (FINDINGS §Tone-down revision)
3. Anomaly chart: #FF0000 markers → STATUS_FAULT = #c44545
4. Comparison chart ranges: Tailwind-style → rejected palette

---

## 8. Documentation update protocol

Каждый блок Rebuild/Wrap/Restyle имеет обязательные deliverables:

| Deliverable | Когда обновляется |
|-------------|-------------------|
| `CHANGELOG.md` | Added / Changed / Fixed формат |
| `CLAUDE.md` module index | Если файловая структура изменилась |
| `README.md` | Если изменилась user-facing surface |
| `operator_manual.md` | Rewrite секции для перестроенной панели |
| `SPEC_AUTHORING_CHECKLIST.md` | Append если обнаружен новый паттерн |

Это policy, не рекомендация. Пропуск documentation deliverable =
блок не закрыт.

---

## 9. Lessons из B.1-B.5

Извлечено из CHANGELOG entries и SPEC_AUTHORING_CHECKLIST.

| # | Lesson | Блок-источник | Добавить в checklist? |
|---|--------|--------------|----------------------|
| L1 | QSS via #objectName, never ClassName | A.7 | Уже есть |
| L2 | Cleanup: closeEvent + destroyed signal | B.3 | Уже есть |
| L3 | Multi-variable state: check ALL transitions | B.3 | Уже есть |
| L4 | Design adoption requires visual preview at target density | B.4.5.1 | Уже есть |
| L5 | WA_StyledBackground for composite QWidget | B.4.5.2 | Уже есть |
| L6 | Status forwarding: reuse existing polls, don't add new | B.5 | Нет — **добавить** |
| L7 | Phase labels must match across surfaces (TopWatchBar, PhaseAwareWidget, ExperimentWorkspace) | B.5 Codex | Нет — **добавить** |
| L8 | active_experiment vs current_phase: two distinct states | B.5 Codex | Нет — **добавить** |
| L9 | Match existing command dispatch pattern (dict, not named method) | B.5 Task 1 | Нет — **добавить** |

**L6-L9** должны быть добавлены в checklist при следующем обновлении.

---

## 10. Risk register

| # | Риск | Серьёзность | Митигация |
|---|------|-------------|-----------|
| R1 | Mode toggle не видим в новом UI — оператор может случайно работать в режиме Отладка | High | B.7 badge в TopWatchBar — первый блок |
| R2 | CalibrationPanel 3-mode FSM + 7 QGroupBox + 2 QStackedWidget — restyle может оказаться недостаточным | Medium | Если visual review покажет проблемы → upgrade до Wrap |
| R3 | ConductivityPanel 1068 строк — самая большая панель, wrap требует deep understanding FSM | Medium | Wrap header без изменения FSM state machine |
| R4 | AnalyticsPanel 12 setStyleSheet — bulk restyle может пропустить edge cases | Low | Codex audit на restyle commit |
| R5 | ExperimentWorkspace дублирует phase display с PhaseAwareWidget | Medium | Rebuild убирает дубликат, но нужна migration path для mode toggle |
| R6 | Legacy widget removal: grep для всех import paths | Low | Grep scan в B.14, не ранее |
| R7 | Plot widget coupling: temp_plot + pressure_plot share X-link | Low | Не трогаем — coupling рабочий |
| R8 | Hardcoded hex colors в legacy widgets (12 в analytics, 8 в experiment) | Medium | Restyle batch (B.10) закрывает |
| R9 | Phase labels inconsistency: 3 разных набора русских названий фаз | Medium | Единый PHASE_LABELS_RU в shared module до B.8 |
| R10 | _ZONES stale labels в dashboard_view.py | Low | Cleanup в B.14 |

---

## 11. Open questions для Владимира

1. **ExperimentWorkspace и «+ Создать»:** wireframe §8.2 предлагает
   modal dialog для создания (уже реализован как NewExperimentDialog).
   Текущий ExperimentWorkspace совмещает создание и управление.
   При Rebuild — оставлять оба или только overlay для управления +
   dialog для создания?

2. **Wrap panels — кто владеет header?** Wrapper добавляет свой header
   с заголовком и кнопкой закрытия, или legacy panel сохраняет свой
   верхний ряд?

3. **CalibrationPanel: Restyle достаточно?** 3-mode FSM + 7 QGroupBox +
   2 QStackedWidget — при visual review может оказаться что restyle
   оставляет визуально «чужую» панель. Upgrade до Wrap?

4. **SensorDiagPanel: overlay или fold в dashboard?** Wireframe §8.8
   упоминает sensor diagnostics в instrument overlay. Альтернатива:
   right-click «Диагностика» в sensor grid cell → inline popover
   вместо отдельного overlay.

5. **Порядок B.6 vs B.7:** Quick log (B.6) закрывает последний
   dashboard placeholder. Mode toggle (B.7) закрывает safety gap.
   Что важнее первым?

6. **Phase labels: какой набор канонический?** TopWatchBar использует
   «Откачка/Захолаживание/Растепление/Разборка». ExperimentWorkspace
   тоже. PhaseAwareWidget (B.5) использовал spec-given
   «Вакуум/Охлаждение/Нагрев/Завершение», Codex поймал, выровняли с
   TopWatchBar. Подтвердить что TopWatchBar набор = canonical?

7. **Restyle batch (B.10): одним блоком или по одной панели?** Одним
   блоком экономит overhead, но Codex audit на 5 файлов одновременно
   менее focused.

8. **Lab PC calibration (B.15): нужен ли remote access?** Если lab PC
   недоступен удалённо, calibration требует физического присутствия
   с CryoDAQ запущенным в mock mode на lab monitor.
