# Language audit triage — 2026-05-03

## Stats

- Tier 1 GUI files scanned: all src/cryodaq/gui/ (~60+ files)
- Tier 1 raw grep candidates: 1194 (includes false positives: theme tokens, objectName, font names, dynamic data reads)
- Tier 1 filtered visible candidates (QLabel/QPushButton/setText): 26
- Tier 1 actual operator text needing translation: 4 button labels ("Lin Y"/"Log Y", 2 files)
- Tier 1 judgment cases: 1 (Lin Y/Log Y — physics notation, may be fine as-is)
- Tier 1 alarm messages: 0 (clean — already Russian)
- Tier 1 Telegram/assistant output: 0 (clean — russified in v0.47.x)
- Tier 1 operator log: 0 (clean)
- Tier 2 README.md: 0 (100% Russian section headers and content ✓)
- Tier 2 CHANGELOG.md: 30 English bullets — mostly dev/technical, see judgment below
- Tier 2 docs/operator/analytics-tab.md: needs full Russian translation (~50 lines)
- Tier 2 reports (src/cryodaq/reporting/): 0 candidates (clean)
- App display name: already "CryoDAQ" in app.py:247 + launcher.py:1267 ✓
- Phase labels: `core/phase_labels.py` + `PHASE_LABELS_RU` — already Russian throughout ✓

---

## Tier 1 — Runtime operator-visible

### Auto-translatable (high confidence)

**"Lin Y" / "Log Y" axis scale buttons — 4 occurrences:**

```
src/cryodaq/gui/dashboard/temp_plot_widget.py:84
    QPushButton("Lin Y")  →  QPushButton("Лин Y")
src/cryodaq/gui/dashboard/temp_plot_widget.py:193
    setText("Log Y" if checked else "Lin Y")  →  setText("Лог Y" if checked else "Лин Y")
src/cryodaq/gui/widgets/overview_panel.py:1165
    QPushButton("Lin Y")  →  QPushButton("Лин Y")
src/cryodaq/gui/widgets/overview_panel.py:1743
    setText("Log Y" if self._is_log_y else "Lin Y")  →  setText("Лог Y" if self._is_log_y else "Лин Y")
```

Note: "Лин" and "Лог" are standard Russian physics/engineering abbreviations for linear/logarithmic.
Tests asserting on "Lin Y" / "Log Y" strings would need updating in the same commit.

### Keep as-is (proper names / technical terms)

- `archive_panel.py:641` — QPushButton("DOCX") — file format name → KEEP
- `calibration_panel.py:783` — QPushButton("JSON") — file format name → KEEP
- `overview_panel.py:719` — QLabel("Keithley") — instrument name → KEEP
- `main_window_v2.py:109` — setWindowTitle("CryoDAQ") — product name → KEEP
- `overlays/_design_system/_showcase.py:60` — "CryoDAQ Overlay Design System Showcase" — dev-only showcase file, Tier 3 → SKIP

### False positives (not operator-visible strings)

All remaining 21 of 26 candidates are dynamic data reads: `exp.get("name")`,
`entry.get("message")`, `field.get("default")`, `active.get("operator")` etc.
These read user-provided values (experiment names, custom fields, log entries)
rather than hardcoded UI strings. SKIP.

### Judgment cases (architect ratify)

**"Lin Y" / "Log Y"**
Context: toggle button on temperature plot and overview panel — switches Y axis scale.
CC proposes "Лин Y" / "Лог Y" (consistent Russian abbreviations).
Counter-argument: "Lin/Log Y" is universally understood by physics lab staff across
all languages. Changing may confuse operators who've seen this notation in other software.
CC recommendation: translate (consistency with Russian-first UI principle).
Architect ratification needed: **YES → translate, NO → leave**.

---

## Tier 2 — Offline operator-visible

### README.md

**Status: CLEAN.** All section headers already Russian:
Статус, Архитектура, Поддерживаемые приборы, Реализованные рабочие процессы, GUI,
Установка, Запуск, Конфигурация, Артефакты экспериментов, Отчёты, Keithley TSP,
Структура проекта, Тесты, Местный AI-ассистент, Известные ограничения, Лицензия.
NO CHANGES NEEDED.

### CHANGELOG.md

**Status: ARCHITECT JUDGMENT NEEDED.**

The CHANGELOG has English technical bullets in entry bodies (e.g. "Engine: _physical_alarms_tick
task...", "Branch: feat/f-x-v3...", "Spec: CC_PROMPT_F..."). These mix:
- Feature description narrative (could be translated)
- Internal technical references (branch names, spec filenames, test counts — should stay English)

The 30 candidates are almost all technical/dev-facing:
- Branch names, spec file references → KEEP English (Tier 3 boundary)
- "Prediction line: STATUS_INFO..." → technical implementation detail → KEEP
- "Operator sends experiment composition photo via Telegram..." → could translate
- "Pillow added as dependency..." → dev-facing → KEEP

**CC recommendation:** Leave CHANGELOG in current English-dominant form.
CHANGELOG is developer-facing technical record; the operator-facing interface is the
GUI and docs/operator/. Tier 2 scope for CHANGELOG was likely overstated in the prompt.
Architect ratification needed: **YES → translate narrative-only bullets, NO → skip entirely**.

### docs/operator/analytics-tab.md (written in fb59916)

**Status: NEEDS FULL RUSSIAN TRANSLATION.** The entire file is in English.
This is an operator-facing document in a confirmed Tier 2 location.

Scope of changes:
- Document title: "Analytics tab — operator guide" → "Вкладка Аналитика — руководство оператора"
- All section headers (##, ###)
- Table headers: Phase, Main, Top right, Bottom right → Фаза, Основной, Справа сверху, Справа снизу
- Phase names in table: preparation→Подготовка, vacuum→Вакуумирование, cooldown→Захолаживание,
  measurement→Измерение, warmup→Отогрев, disassembly→Разборка, (no experiment)→(без эксперимента)
- Widget descriptions in table: Temperature channels→Каналы температуры, Pressure→Давление,
  Sensor health→Здоровье датчиков, Vacuum projection→Прогноз вакуума,
  Cooldown trajectory→Траектория охлаждения, R_thermal (F8)→R тепловое (F8),
  R_thermal (live)→R тепловое (прямой эфир), Keithley power→Мощность Keithley,
  Temperature history→История температуры, Past cooldowns→Прошлые охлаждения,
  Experiment summary→Сводка эксперимента
- Body text for each section
- "Common questions" section and answers

Estimated: ~80 lines changed. Russian inline strings (Ожидание данных, Охлаждение не активно, etc.) already correct — keep.

---

## Files confirmed NOT touched (Tier 3 boundary)

- All code comments ✓
- All docstrings ✓  
- CLAUDE.md, ORCHESTRATION.md, CUSTOM_INSTRUCTIONS.md ✓
- docs/decisions/ ✓
- CC_PROMPT_*.md ✓
- ROADMAP.md, PROJECT_STATUS.md ✓
- pyproject.toml description ✓
- Test names and docstrings ✓
- Internal logger.info/debug strings (dev-only) ✓
- Vault files ✓
- Theme token names (BACKGROUND, FOREGROUND, ACCENT, etc.) ✓
- Qt objectName strings (not visible to operator) ✓
- Font names (Fira Code, Fira Sans) ✓

---

## Recommended ship strategy

**v0.52.1 patch** — scope is minimal:
- Tier 1: 4 button label changes ("Lin Y"/"Log Y") — ~4-8 LOC
- Tier 2: docs/operator/analytics-tab.md full Russian translation — ~80 LOC
- Total: ~90 LOC across 3 files
- No structural changes, no engine changes, no CHANGELOG needed (docs-only + minor UI fix)

This does NOT warrant v0.53.0 minor.

Condition on architect ratification:
- If "Lin Y"/"Log Y" → YES: Batch A (GUI) + Batch F (docs) commits → v0.52.1
- If "Lin Y"/"Log Y" → NO: Batch F (docs only) → v0.52.1
- If CHANGELOG → YES: adds Batch E, still v0.52.1
- If CHANGELOG → NO (CC recommendation): skip, still v0.52.1

---

## Pending architect ratification (before Phase 3)

1. **"Lin Y"/"Log Y"** — translate to "Лин Y"/"Лог Y"?
   CC recommendation: YES (Russian-first UI consistency)

2. **CHANGELOG entry bodies** — translate narrative bullets?
   CC recommendation: NO (dev-facing technical record)

STOP — awaiting architect "go" before Phase 3.
