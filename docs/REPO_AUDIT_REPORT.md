# CryoDAQ Repository Audit

---

## Audit 2026-04-30 (repo cleanup pass)

**Дата:** 2026-04-30
**Commit:** `6662981` (cleanup: Phase 5 living docs refresh)
**Latest release tag:** v0.42.0 → `751b4cf` (2026-04-29)
**Ветка:** master
**Метод:** repo cleanup + living-doc refresh pass. Read-only for code; docs/structure changed per CC_PROMPT_REPO_CLEANUP_2026-04-30.md.

### State

| Метрика | Значение |
|---|---|
| Python `src/cryodaq/` | **~48 500** строк в **145** файлах |
| Python `tests/` | **~38 800** строк в **206** файлах |
| Тесты | **1 931 passed, 4 skipped** (baseline v0.42.0) |
| Coverage | stale — re-run pending |
| Версия пакета | **0.42.0** |
| Коммитов с начала | **536** |
| Design System | v1.0.1, 67 canonical .md, 139 токенов |
| TODO/FIXME в src/ | **0** |
| Untracked files в root | **21** |

### Cleanup actions taken (this audit)

- 14 CC_PROMPT_* files archived → `docs/cc-prompts-archive/2026-04/`
- 2 stale handoff files moved → `docs/handoffs-archive/2026-04/`
- 1 doc moved from root → `docs/codex-architecture-control-plane.md`
- 4 recon files reorganized → `artifacts/recon/`
- 3 living docs refreshed: PROJECT_STATUS.md, DOC_REALITY_MAP.md (addendum), docs/NEXT_SESSION.md

### Repo root after cleanup

Kept (legitimate):
- Active prompts: `CC_PROMPT_CALIBRATION_2026-04-30.md`, `CC_PROMPT_METASWARM_F17.md`, `CC_PROMPT_REPO_CLEANUP_2026-04-30.md`
- Living docs: `CHANGELOG.md`, `CLAUDE.md`, `DOC_REALITY_MAP.md`, `PROJECT_STATUS.md`, `ROADMAP.md`, `README.md`, `RELEASE_CHECKLIST.md`, `THIRD_PARTY_NOTICES.md`
- Config: `pyproject.toml`, `requirements-lock.txt`, `.gitattributes`, `.gitignore`, `.graphifyignore`
- Scripts: `create_shortcut.py`, `release_notes.py`, `install.bat`, `start*.bat`, `start*.sh`

### Outstanding (architect-only decisions — not addressed this pass)

| Item | Notes |
|---|---|
| `~/` directory in repo root | Shell mkdir mistake. `rm -rf ~/Projects/cryodaq/\~/` when architect present |
| `draft.py`, `draft2.py` | Word-count scratch scripts. Safe to delete (not production, not referenced) |
| `graphify-out.stale-pre-merge/` | Gitignored stale graph — safe to rm locally |
| `agentswarm/` | Gitignored local cache — architect can move outside repo |

### Ignored / out-of-scope

- `src/`, `tests/`, `config/` — production, no cleanup
- `.venv/`, `.pytest_cache/`, `build/`, `dist/` — gitignored
- `.worktrees/`, `.swarm/`, `.audit-run/`, `.omc/` — gitignored agent workspaces
- `artifacts/calibration/` — active session output

### Health metrics

- Untracked files in root: 21 (includes active CC_PROMPT files, draft.py/draft2.py, graphify-out dirs)
- Stale docs >14 days at root: 0 (DOC_REALITY_MAP.md is 13 days, marked HISTORICAL)
- TODO/FIXME density in src/: 0

---

## Audit 2026-04-17

**Дата:** 2026-04-17
**Commit:** `d8ec668c82f37add016ab6969388930498eadcb6` (`style: fix 587 ruff lint errors (CI green)`, 2026-04-17)
**Ветка:** master
**Метод:** read-only инвентаризация (`wc`, `git log`, first-lines reads); ничего не удалено и не переписано. Отчёт создан в `docs/REPO_AUDIT_REPORT.md`.

---

## Сводка

| Метрика | Значение |
|---|---|
| Python `src/cryodaq/` (всего строк, включая пустые/комменты) | **41 397** в 133 файлах |
| Python `tests/` (всего строк) | **24 275** в 150 файлах |
| Тестов в сьюте | **1 089 собранных** (последний прогон: 1087 passed / 2 skipped) |
| Coverage (сэмпл на `src/cryodaq/core` — 492 теста) | **79%** (3 853 операторов; 825 пропущено) |
| **Полный suite coverage** | **66%** (21 522 stmts; 7 305 пропущено) — см. §5 |
| Design System (канонич.) | **67 .md** (v1.0.1, 139 токенов); **73** с учётом 6 audit/review артефактов внутри `docs/design-system/` |
| Documents вне DS | **54 .md** (без `.pytest_cache`, `dist/`, `graphify-out.stale-pre-merge/`, `.venv`) |
| Config файлы (`config/`) | **13 YAML**, 836 строк суммарно (+ `experiment_templates/`) |
| CI/CD | `.github/workflows/main.yml` — 1 workflow |
| Lua | 1 draft TSP (`tsp/p_const.lua`, 56 строк — **не используется** host-side) |
| `CC_PROMPT_*` / `CC_FIX_*` в трекинге | **0** (оба audit прошли без сохранения промптов в git) |

---

## 1. Код по подсистемам

### 1.1 `src/cryodaq/`

| Подсистема | Файлов | Строк |
|---|---:|---:|
| `core` | 26 | 8 285 |
| `gui` (суммарно) | 58 | 17 400 |
| &nbsp;&nbsp;→ `gui/shell` | 14 | 3 192 |
| &nbsp;&nbsp;→ `gui/dashboard` | 15 | 2 229 |
| &nbsp;&nbsp;→ `gui/shell/overlays` | 6 | 559 |
| &nbsp;&nbsp;→ `gui/widgets` (v1, legacy) | 22 | **10 522** |
| `storage` | 7 | 1 903 |
| `analytics` | 9 | 4 677 |
| `reporting` | 4 | 1 275 |
| `web` | 2 | 525 |
| `notifications` | 6 | 1 361 |
| `drivers` (`instruments` + `transport`) | 10 | 2 532 |
| `tools` | 2 | 283 |

**Наблюдение.** `gui/widgets` (legacy v1) — 10 522 строк в 22 файлах — **самая тяжёлая подсистема после `core`**. По CLAUDE.md эти модули «kept alive until Block B.7». Технический долг ожидаемый, но существенный.

### 1.2 `tests/`

| Директория | Файлов | Строк |
|---|---:|---:|
| `tests/core` | 48 | 11 154 |
| `tests/gui` | 53 | 5 326 |
| `tests/storage` | 7 | 1 210 |
| `tests/analytics` | 11 | 3 039 |
| `tests/reporting` | 1 | 316 |
| `tests/web` | 2 | **33** |
| `tests/notifications` | 5 | 579 |
| `tests/drivers` | 11 | 1 802 |
| `tests/config` | 3 | 75 |

**Наблюдение.** `tests/web` — 33 строки на 525 строк кода. Покрытие минимальное. См. §3 ниже — зона API без документации и с тонким тестовым слоем.

### 1.3 YAML конфиги

| Файл | Строк |
|---|---:|
| `config/alarms_v3.yaml` | самый большой; часть 836 |
| `config/interlocks.yaml` | 48 |
| `config/cooldown.yaml` | 15 |
| Остальные (`alarms.yaml`, `channels.yaml`, `instruments.yaml`, `safety.yaml`, `plugins.yaml`, `housekeeping.yaml`, `notifications.yaml`, `shifts.yaml`, `.local.yaml.example` × 2) | … |

### 1.4 CI

- `.github/workflows/main.yml` — единственный workflow. Прочих проверок (preview deploy, docs build, coverage gate) нет.

---

## 2. Документы по группам

Все даты ниже — последний коммит, затронувший файл (`git log -1 --format=%ai`).

### A. Живая документация (активная, актуальная)

| Файл | Дата | Строк | Заметка |
|---|---|---:|---|
| `README.md` | 2026-04-14 | 291 | Главная ссылка / overview |
| `CLAUDE.md` | 2026-04-17 | 402 | Rebuilt сегодня (Phase I.1 module index) |
| `CHANGELOG.md` | 2026-04-16 | 1 148 | Keep-a-Changelog, формат актуальный |
| `THIRD_PARTY_NOTICES.md` | 2026-04-15 | 67 | Атрибуция (UI UX Pro Max skill) |
| `docs/deployment.md` | 2026-04-08 | 277 | Описывает текущий install path |
| `docs/operator_manual.md` | 2026-04-15 | 274 | Оператор-facing, v0.13.0 |
| `docs/architecture.md` | 2026-03-22 | 349 | «Реализованная система», согласуется с CLAUDE.md |
| `docs/first_deployment.md` | 2026-03-21 | 207 | Windows первый деплой; пересекается с `deployment.md` |
| `RELEASE_CHECKLIST.md` | 2026-03-21 | 155 | Чек-лист релиза; generic, остаётся актуальным |
| `docs/design-system/**` | active | 67 файлов | v1.0.1 canonical (см. MANIFEST) |
| `src/cryodaq/gui/shell/overlays/_design_system/README.md` | в коде | 36 | В-коде README для overlay DS primitives |

### B. Архитектурные решения и спеки

| Файл | Дата | Строк | Роль |
|---|---|---:|---|
| `docs/phase-ui-1/phase_ui_v2_roadmap.md` | 2026-04-16 | 387 | **Living roadmap** Phase UI-1 v2 (через B.8.0.2) |
| `docs/phase-ui-1/ui_refactor_context.md` | 2026-04-16 | 181 | Pain points + preserve list (читать первым) |
| `docs/phase-ui-1/PANELS_REBUILD_STRATEGY.md` | 2026-04-15 | 491 | Стратегия ребилда панелей |
| `docs/phase-ui-1/SPEC_AUTHORING_CHECKLIST.md` | 2026-04-15 | 543 | Как писать Phase II specs |
| `docs/phase-ui-1/phase_0_audit_report.md` | 2026-04-16 | 283 | Phase 0 аудит |
| `docs/phase-ui-1/preserve_features_verification.md` | 2026-04-16 | 203 | Проверка preserve list |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_A8_SPEC.md` | 2026-04-14 | 275 | Block spec (выполнен) |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_A9_SPEC.md` | 2026-04-14 | 427 | Block spec |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B1_SPEC.md` | 2026-04-14 | 481 | Block B.1 (выполнен) |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B2_SPEC.md` | 2026-04-14 | 818 | Block B.2 (выполнен) |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B11_SPEC.md` | 2026-04-14 | 150 | Block B.11 spec |
| `docs/phase-ui-1/DESIGN_SYSTEM_FINDINGS.md` | untracked→tracked | 600 | В WIP; только что в git |
| `docs/phase-ui-1/setstylesheet-classification.md` | 2026-04-09 | 686 | Классификация QSS usages (research artifact) |
| `docs/legacy-inventory/*.md` (10 файлов) | 2026-04-16 | 1 296 суммарно | **Pre-refactor widget inventory** для Phase II ref (упомянуты в CLAUDE.md как reference) |

### C. Task prompts (CC / Codex инструкции)

В git-трекинге **нет** файлов `CC_PROMPT_*`, `CC_FIX_*`, `CODEX_PROMPT_*` на HEAD. Последние аудит-промпты (включая этот `CC_REPO_AUDIT`, а также `CC_FIX_DEEP_AUDIT_QUICK`, `CC_PROMPT_CLAUDE_MD_AND_A1_SAFETY` из текущей сессии) приходят ad-hoc через чат и не коммитятся.

Исключения: Codex-генерированные отчёты-результаты (не промпты) в `docs/audits/`:

| Файл | Дата | Статус |
|---|---|---|
| `docs/audits/CODEX_FULL_AUDIT.md` | 2026-04-14 | **Выполнен** — findings обработаны в последующих фиксах |
| `docs/audits/CODEX_ROUND_2_AUDIT.md` | 2026-04-14 | **Выполнен** — findings обработаны |

Рекомендация: если держать task-prompts в репо — заводить `docs/prompts/` с явной policy (иначе мусор на root).

### D. Stale / устаревшие

| Файл | Дата | Что не так |
|---|---|---|
| `PROJECT_STATUS.md` | 2026-04-14 | Говорит `934 passed`, commit `7b453d5`, Phase 2d complete. Реальность на HEAD: **1087 passed**, commit `d8ec668`, и далее уже через d8ec668 (ruff cleanup). **Stale по числам и по фронтиру.** |
| `DOC_REALITY_MAP.md` | 2026-04-12 | Meta-doc о состоянии документации на commit `7aaeb2b`. Мы на d8ec668; этот reality map сам стал устаревшим reality map. |
| `docs/DESIGN_SYSTEM.md` | 2026-04-09 | 1 910 строк «Design System **v0.3**» — **предшественник** canonical `docs/design-system/` v1.0.1. Per CLAUDE.md `## Источник истины по UI/визуальному дизайну` — новая спецификация canonical. Старый файл теперь дублирующий, частично противоречит v1.0.1 (у него, например, 126 токенов, не 139). |
| `docs/UI_REWORK_ROADMAP.md` | 2026-04-09 | 826 строк, ссылается на `docs/DESIGN_SYSTEM.md v0.3` как companion. План «переработки каждого экрана» до Phase UI-1 v2. Phase UI-1 v2 уже merged через B.2 — роадмап superseded `docs/phase-ui-1/phase_ui_v2_roadmap.md`. |
| `docs/PHASE_UI1_V2_WIREFRAME.md` | 2026-04-10 | 1 126 строк, помечен «**First cut wireframe v0.1, awaiting Vladimir review**». Wireframe был реализован и merged. Документ сохраняет историческую ценность, но не operational. |
| `DEEP_AUDIT_CC.md` | 2026-04-14 | 940 строк; historical pre-Phase-2c audit artifact (commit msg `chore: commit historical pre-Phase-2c audit artifacts`). Purpose served. |
| `DEEP_AUDIT_CC_POST_2C.md` | 2026-04-09 | 1 240 строк; post-2c CC audit. Findings обработаны. |
| `DEEP_AUDIT_CODEX.md` | 2026-04-14 | 438 строк; historical pre-2c. Purpose served. |
| `DEEP_AUDIT_CODEX_POST_2C.md` | 2026-04-09 | 763 строки; post-2c Codex audit. Обработан. |
| `CONFIG_FILES_AUDIT.md` | 2026-04-09 | 719 строк; audit. Findings обработаны. |
| `DEPENDENCY_CVE_SWEEP.md` | 2026-04-09 | 286 строк; CVE sweep results; актуально только на дату прогона. |
| `DRIVER_FAULT_INJECTION.md` | 2026-04-09 | 1 366 строк; scenarios audit. Historical. |
| `MASTER_TRIAGE.md` | 2026-04-09 | 307 строк; синтез других audit'ов 2026-04-09. Superseded последующими фиксами. |
| `PERSISTENCE_INVARIANT_DEEP_DIVE.md` | 2026-04-09 | 1 090 строк; single-shot deep dive. Finding уже в CLAUDE.md. |
| `REPORTING_ANALYTICS_DEEP_DIVE.md` | 2026-04-09 | 572 строки; single-shot. |
| `SAFETY_MANAGER_DEEP_DIVE.md` | 2026-04-09 | 1 062 строки; FSM анализ. Findings в коде + CLAUDE.md. |
| `VERIFICATION_PASS_HIGHS.md` | 2026-04-09 | 1 005 строк; verification pass результат. Single-shot. |
| `docs/audits/*` (9 других файлов от 2026-04-14) | 2026-04-14 | Branch inventory, dead code scan, git archaeology — одноразовые отчёты. **Не противоречат** коду, но и не ведутся дальше. |
| `docs/changelog/RETRO_ANALYSIS.md` (+ V2, V3) | 2026-04-14 | 1 677 / 2 014 / 2 660 строк. Три версии ретроспективы одного периода. V1 → V2 → V3 выглядят как итерации draft → final; **V1 и V2 скорее всего избыточны** после публикации V3. |

**Итого «stale»:** ~**18 файлов** совокупно ≈ **15 000+ строк**. Ни один не >3 месяцев, но большинство — артефакты одноразовых audit циклов, которые выполнили свою задачу.

### E. Мусор (кандидаты на удаление)

| Цель | Статус |
|---|---|
| `.pytest_cache/README.md` | Авто-генерируемый pytest. **Не tracked** в git (по `.gitignore` нет записи, но `git ls-files` пуст). OK. |
| `dist/**` | `.gitignore` покрывает `dist/`. Локальная PyInstaller-сборка, не в репо. OK. |
| `graphify-out.stale-pre-merge/**` | Папка с суффиксом `.stale-pre-merge`. **Не tracked** (`git check-ignore` фильтрует). Локальный артефакт. Можно безопасно удалить с диска руками. |
| `docs/.DS_Store`, `docs/phase-ui-1/.DS_Store` | macOS metadata. **Не tracked**. OK. |
| Дубликаты `RETRO_ANALYSIS.md` / `V2` / `V3` | Все три в git. Рекомендация: оставить V3, переименовать V1/V2 или перенести в `docs/changelog/archive/`. |

---

## 3. Оценка документации по зонам

| Зона | Документация | Статус | Что нужно |
|---|---|---|---|
| Установка / деплой | `docs/deployment.md` (2026-04-08, 277 строк) + `docs/first_deployment.md` (2026-03-21, 207 строк) | **OK** | Пересекающиеся документы. Консолидировать в один `docs/deployment.md` с разделами «Первый деплой на Windows-ПК» и «Обновление». `first_deployment.md` → архив. |
| Оператор (manual) | `docs/operator_manual.md` (2026-04-15, 274 строки) | **OK** | Свежее, соответствует текущему workflow (Эксперимент / Отладка, experiment card, dual-channel Keithley). Поддерживать. |
| Архитектура | `CLAUDE.md` + `docs/architecture.md` | **OK** | Обе актуальны; частично дублируются (module index в CLAUDE теперь точнее). Убедиться что `architecture.md` не разрастается в параллельный LLM-instruction файл. |
| Safety path | `config/safety.yaml` + `src/cryodaq/core/safety_manager.py` + `SAFETY_MANAGER_DEEP_DIVE.md` | **Частично** | FSM описан в CLAUDE.md. Но **user-facing** документа safety (что оператор делает при fault_latched / manual_recovery) нет. `SAFETY_MANAGER_DEEP_DIVE.md` — для разработчика, не для оператора. |
| Калибровка | Только CLAUDE.md упоминание; `src/cryodaq/analytics/calibration.py`, `calibration_fitter.py`, `core/calibration_acquisition.py`; `src/cryodaq/gui/widgets/calibration_panel.py` | **GAP** | Документа оператора по калибровочному workflow (Setup → Acquisition → Results, `.330`/`.340`/JSON export) **не существует**. В `docs/operator_manual.md` раздел есть? — проверить, но calibration v2 с continuous SRDG требует отдельного раздела. |
| Design System | `docs/design-system/` v1.0.1 (67 + 6 audit файлов) | **Canonical** | Отличное состояние. MANIFEST / README up-to-date; недавний cleanup завершён коммитом `1c61268` + `eb267c4` + постфиксом `8840922`. |
| API (web) | `src/cryodaq/web/server.py` docstring + `tests/web/test_xss_escaping.py` (33 строки всего) | **GAP** | Нет user-doc для `/status`, `/history`, `/api/status`, `/api/log`, WebSocket `/ws`. Нет описания JSON schemas. Нет example curl. `DEPENDENCY_CVE_SWEEP.md` упоминает FastAPI deprecation (`on_event`) — это migrated, но не в docs. |
| Приборы (GPIB / TSP) | `src/cryodaq/drivers/instruments/*.py` docstrings + `tsp/p_const.lua` (draft, not loaded) | **Частично** | Драйверы задокументированы inline. Но «как подключить новый прибор / переконфигурировать LakeShore / сменить GPIB address» — **не задокументировано** в user-doc. TSP P=const (Phase 3) не имеет спеки. |

---

## 4. Рекомендации

### 4.1 Обновить (дешёвые правки)

1. **`PROJECT_STATUS.md`** — переписать под HEAD `d8ec668`, тесты 1087/2, Phase 2e / Phase I.1 фронтир. Либо переименовать в `PROJECT_STATUS_2026-04-14.md` и положить в `docs/status-snapshots/`. В ином виде файл врёт о текущем состоянии (самое опасное — лжёт про test count).
2. **`DOC_REALITY_MAP.md`** — это meta-doc о docs на commit `7aaeb2b`; либо обновить под HEAD, либо пометить `status: historical`. В идеале — пересобрать raw, но с опорой на этот audit report.
3. **`docs/DESIGN_SYSTEM.md`** (старый v0.3) — добавить front-matter `status: superseded` + одно-предложенческий pointer на `docs/design-system/README.md`; тело можно оставить как исторический контекст. Вариант b — перенести в `docs/archive/DESIGN_SYSTEM_v0.3.md`.
4. **`docs/UI_REWORK_ROADMAP.md`** и **`docs/PHASE_UI1_V2_WIREFRAME.md`** — те же правила: маркер superseded + pointer на `docs/phase-ui-1/phase_ui_v2_roadmap.md`.
5. **Консолидировать `docs/deployment.md` ← `docs/first_deployment.md`.** Оставить один.
6. **`docs/changelog/RETRO_ANALYSIS.md` vs V2 vs V3** — оставить V3 как canonical, V1/V2 → `docs/changelog/archive/`.

### 4.2 Написать (новые документы под GAP'ы)

7. **`docs/api.md`** — Web API spec (`/status`, `/history`, `/api/status`, `/api/log`, `/ws`). JSON-schemas, примеры curl, auth/CORS (или их отсутствие). Текущий `tests/web/` слишком тонкий для self-документирования.
8. **`docs/calibration.md`** — user-doc калибровочного workflow: три режима (Setup → Acquisition → Results), continuous SRDG, post-run pipeline, export форматов `.330` / `.340` / JSON, runtime apply policy.
9. **`docs/instruments.md`** — «Как настроить прибор»: LakeShore 218S GPIB, Keithley 2604B USB-TMC, Thyracont VSP63D serial. Где редактировать `config/instruments.yaml`, как проверить связь, mock-режим.
10. **`docs/safety-operator.md`** — оператор-facing safety guide: что значит каждое состояние FSM, как реагировать на FAULT_LATCHED, как выполнить acknowledge_fault, какие preconditions при восстановлении. Отдельно от `SAFETY_MANAGER_DEEP_DIVE.md` (который для разработчика).
11. **`tsp/README.md`** (или `docs/tsp.md`) — статус Phase 3 TSP watchdog: почему `p_const.lua` **не** загружен, когда планируется, как тестировать.

### 4.3 Убрать с root (deep-audit артефакты)

Root-level scatter из 10+ audit файлов 2026-04-09/04-14 (`DEEP_AUDIT_*`, `*_DEEP_DIVE.md`, `MASTER_TRIAGE.md`, `CONFIG_FILES_AUDIT.md`, `DEPENDENCY_CVE_SWEEP.md`, `DRIVER_FAULT_INJECTION.md`, `VERIFICATION_PASS_HIGHS.md`) — переместить в `docs/audits/2026-04-09/` одним `git mv`. Root останется чистым. Git history сохранится. Ни один из этих файлов не является живым документом.

**Не удалять** — историческая ценность есть (findings, которые привели к коду). Но root они засоряют.

### 4.4 Policy для будущих audit циклов

- **Prompts**: если хранить в репо — `docs/prompts/YYYY-MM-DD_<slug>.md`. Иначе — чат-only, не коммитить.
- **Audit reports**: всегда в `docs/audits/YYYY-MM-DD/`, не в root.
- **Retrospectives**: одна canonical версия в `docs/changelog/`, черновики — в `docs/changelog/drafts/` и после финализации удалять или архивировать.
- **Design doc survival**: как только документ становится `superseded` — front-matter `status: superseded` + `replaced_by: <path>`.

---

## 5. Тесты и покрытие

### 5.1 Коллекция

- `pytest tests/ --co -q` → **1 089 тестов собрано**.
- Последний полный прогон (эта сессия, Part 2 safety fixes): **1 087 passed / 2 skipped / 39 warnings** за 285 с.
- Таргетированный `pytest -k "test_safety or test_interlock or test_fault"`: **98 passed** за 51 с.

### 5.2 Покрытие (pytest-cov 7.1.0 установлен)

**Сэмпл `src/cryodaq/core` (492 теста из `tests/core/`):**

```
TOTAL                                          3853    825    79%
```

Наиболее низкопокрытые core-модули:
| Модуль | Statements | Miss | Coverage |
|---|---:|---:|---:|
| `core/zmq_bridge.py` | 229 | 187 | **18%** |
| `core/zmq_subprocess.py` | 86 | 74 | **14%** |
| `core/scheduler.py` | 308 | 118 | 62% |
| `core/safety_broker.py` | 64 | 16 | 75% |
| `core/housekeeping.py` | 295 | 71 | 76% |

Высокопокрытые:
- `phase_labels.py`, `event_logger.py`, `smu_channel.py` — 100%
- `channel_state.py`, `rate_estimator.py` — 99% / 97%
- `sensor_diagnostics.py` — 94%
- `interlock.py` — 91%
- `experiment.py` — 90%
- `safety_manager.py` — 86%

ZMQ-слой слабо покрыт — ожидаемо (subprocess boundary сложно тестировать без фреймворка). Scheduler 62% — стоит взглянуть что именно не покрыто.

**Полный suite coverage** (`pytest tests/ --cov=src/cryodaq`, 264 с):

```
TOTAL                                                                    21522   7305    66%
1087 passed, 2 skipped, 57 warnings in 264.41s
```

**0% coverage (вообще не exercised):**

| Модуль | Statements | Комментарий |
|---|---:|---|
| `gui/widgets/autosweep_panel.py` | 404 | Помечен DEPRECATED в CLAUDE.md — ожидаемо |
| `gui/widgets/pressure_panel.py` | 120 | Legacy v1 панель — нет теста |
| `gui/widgets/temp_panel.py` | 196 | Legacy v1 панель — нет теста |
| `tools/cooldown_cli.py` | 151 | CLI entry point |

Суммарно **871 stmts мёртвого (для тестов) кода**, из которых ~720 — legacy v1 панели. Совпадает с рекомендацией из CLAUDE.md «kept alive until Block B.7».

**Низкое покрытие (<50%), требуют внимания:**

| Модуль | Coverage | Statements |
|---|---:|---:|
| `notifications/periodic_report.py` | 11% | 238 |
| `launcher.py` | 13% | 504 |
| `core/zmq_subprocess.py` | 14% | 86 |
| `core/zmq_bridge.py` | 18% | 229 |
| `gui/widgets/connection_settings.py` | 19% | 140 |
| `gui/widgets/channel_editor.py` | 21% | 81 |
| `notifications/telegram_commands.py` | 42% | 267 |
| `gui/widgets/conductivity_panel.py` | 44% | 698 |
| `gui/zmq_client.py` | 44% | 151 |

**Высокое покрытие (≥90%):**
- `gui/theme.py` — 100% (146 stmts)
- `gui/widgets/common.py`, `core/phase_labels.py`, `core/event_logger.py`, `core/smu_channel.py`, `gui/shell/overlays/_design_system/bento_grid.py` — 100%
- `gui/widgets/experiment_dialogs.py` — 99%, `sensor_diag_panel.py` — 99%, `core/channel_state.py` — 99%
- `core/rate_estimator.py` — 97%, `gui/widgets/operator_log_panel.py` — 96%, `gui/shell/overlays/_design_system/modal_card.py` — 96%
- `gui/widgets/vacuum_trend_panel.py` — 95%, `core/sensor_diagnostics.py` — 94%
- `paths.py` — 93%, `reporting/generator.py` — 93%, `gui/shell/overlays/_design_system/drill_down_breadcrumb.py` — 93%
- `gui/shell/overlays/_design_system/_showcase.py` — 92%, `gui/widgets/keithley_panel.py` — 91%, `reporting/data.py` — 91%, `core/interlock.py` — 91%, `core/experiment.py` — 90%

**Вывод по coverage.** 66% — приемлемо для проекта этого размера, но явно видны зоны:
1. **ZMQ subprocess boundary** (14-18%) — сложно тестировать без фреймворка.
2. **Launcher + periodic_report** (11-13%) — интеграционный код, smoke-тесты бы помогли.
3. **Legacy panels, которые никогда не тестировались** (`temp_panel`, `pressure_panel`, `channel_editor`, `connection_settings`) — кандидаты на удаление после Block B.7 миграции, а не на дополнительные тесты.
4. **`conductivity_panel` 44% на 698 stmts** — крупная недокоммитированная в тесты зона; при любом рефакторе рискованно.

---

## 6. Инварианты audit'а

- **Read-only**: код, конфиги, существующие docs **не изменены**. Единственное изменение в рабочем дереве — создание `docs/REPO_AUDIT_REPORT.md`.
- **Дат источник**: `git log -1 --format=%ai`, не файловые mtime.
- **Coverage**: `pytest-cov` 7.1.0 установлен; сэмпл по `core` показан, полный прогон запущен отдельной задачей.
- **Не tracked в git, но присутствуют на диске**: `dist/`, `.pytest_cache/`, `graphify-out.stale-pre-merge/`, `docs/.DS_Store` — все в `.gitignore` или покрыты паттернами.
- **Честная оценка**: root-level audit-документы выполнили свою функцию (findings уже в коде + CLAUDE.md), но лежат как мусор и конкурируют с живой документацией за внимание. Это **не** «storage plus» — это показатель, что прошлые audit-циклы не имели policy куда складывать результат.
