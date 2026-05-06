# HF v0.47.2 — Phase E fix-up cycle (chart + race + complete russian-fication)

> Phase E smoke surfaced 4 issues. STOP per spec §5. Diagnose +
> fix before Phase G tag.
>
> Architect verdict on smoke: FAIL (2 critical + 2 medium)

---

## Smoke results from real Telegram session (03:32-03:37 MSK)

Conversation:
```
03:32:01 Гемма: Доброй ночи! Я Гемма, могу рассказать что сейчас в системе.
                Попробуй: «что сейчас?», «ETA вакуума?», «в какой фазе?»,
                «есть ли тревоги?».

03:32:08 Vladimir: Расскажи как у нас дела сейчас

03:32:22 Гемма: Т7 Детектор, сейчас система в фазе cooldown по эксперименту-001.
                Ключевые температуры пока не отображаются, так как они отсутствуют
                в отчете. Давление установлено на 1.65e-06 mbar. Прогнозы по
                охлаждению и вакууму пока не вижу. Активных тревог нет.

03:37:36 Vladimir: /status
03:37:36 Гемма: [42 каналов, все приборы активны, тревог нет]

03:37:56 Vladimir: /temps
03:37:56 Гемма: [24 канала с display names — все температуры РЕАЛЬНО есть]
```

### What PASSED

- ✅ Greeting time-aware: "Доброй ночи! Я Гемма..."
- ✅ ChannelManager display names в /temps: 24 channels с "Т7 Детектор"
- ✅ UUID suppression: response says "эксперимент-001" not UUID
- ✅ ETA degradation message ("пока не вижу") conversational

### What FAILED

#### CRITICAL Issue 1 — No chart attached к composite query

Vladimir asked composite_status at 03:32:08. Text arrived 03:32:22
(14s, OK). **No PNG chart followed.**

Spec §2.4 acceptance: "Charts rendered for composite_status and
range_stats categories". Phase D ChartDispatcher wiring failed in
production despite tests passing.

#### CRITICAL Issue 2 — "Температуры отсутствуют" but they exist

Composite (03:32:22) said "Ключевые температуры пока не отображаются,
отсутствуют в отчете". /temps (03:37:56, 5min later) returned 24
real channels с values.

Hypothesis: BrokerSnapshot._latest was empty when composite query
fired — BrokerSnapshot subscriber hadn't yet consumed initial
readings (engine startup ~03:31, first reading propagation ~0.5-2s,
query at 03:32:08 may or may not have caught up).

#### MEDIUM Issue 3 — English leakage в operator output

Multiple English terms in single response:
- "в фазе **cooldown**" — phase enum value English
- "по охлаждению и **вакууму**" — OK ("вакуум" is borrowed but acceptable)
- response ID "**эксперименту-001**" — OK

Plus systemic English-leak vectors:
- `ExperimentPhase` enum has English values: `cooldown`, `vacuum`,
  `measurement`, `warmup`, `teardown`, `preparation`
- Format prompts use English field names: `t_cold`, `cooldown_active`,
  `current_mbar`, `target_mbar`, `n_references`, `t_remaining_str`,
  `T_cold сейчас:` (line label)
- Format prompts contain English instruction words: "physics /
  engineering" (FORMAT_OUT_OF_SCOPE_GENERAL_USER), "current state"
  (FORMAT_OUT_OF_SCOPE_HISTORICAL_USER)
- Telegram replies for slash commands include "RUNNING", "ACTIVE"
  (если они приходят из ExperimentStatus enum) — нужно verify

Vladimir explicit goal: "полностью исключить английский" — operator
sees ZERO English words in conversational responses (units like
mbar, K, technical abbreviations like ETA acceptable; everything
else translated).

#### MEDIUM Issue 4 — Composite text begins with "Т7 Детектор,"

Response started "Т7 Детектор, сейчас система в фазе...". LLM
interpreted first temperature row as greeting target. Prompt
structure too loose.

---

## Fix architecture

Three orthogonal fix tracks, applied in single cycle:

**Track A** — Diagnose + fix chart dispatch (Issue 1)
**Track B** — Defensive empty-snapshot handling (Issue 2)
**Track C** — Complete russian-fication (Issue 3)
**Track D** — Composite prompt anti-pattern (Issue 4)

Tracks B+C+D are pure code/prompt changes, deterministic. Track A
requires investigation first (logs analysis).

---

## Phase 1 — Track A investigation (priority, 30 min)

```bash
cd /Users/vladimir/Projects/cryodaq

# Engine logs around smoke session
grep -i "chart\|send_photo\|sendPhoto\|chart_dispatcher\|ChartDispatcher" \
    data/logs/engine.log | tail -100

# Audit JSON для composite query at 03:32
ls -la data/agents/assistant/audit/2026-05-01/ 2>/dev/null
grep -l "composite_status" data/agents/assistant/audit/2026-05-01/*.json
# Read full audit JSON
```

Determine which Fix scenario applies:

**Fix 1A** — ChartDispatcher not constructed в engine.py wiring
**Fix 1B** — ChartDispatcher.maybe_dispatch() returns False (category mismatch)
**Fix 1C** — TelegramCommandBot.send_photo() not exposed
**Fix 1D** — asyncio.create_task crashed silently без exception handler

Surface findings to architect before applying fix.

---

## Phase 2 — Apply Track A fix (per investigation, 30 min)

Implement based on Phase 1 result. See spec §"Fix actions per
investigation result" for each scenario's fix.

Add unconditionally: exception handler on chart dispatch task:

```python
def _log_task_exception(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Chart dispatch task failed")

task = asyncio.create_task(self._chart_dispatcher.maybe_dispatch(...))
task.add_done_callback(_log_task_exception)
```

This prevents future silent failures regardless of root cause.

---

## Phase 3 — Track B: defensive empty-snapshot (30 min)

`CompositeAdapter.status` and `CurrentValueAdapter.value` check if
BrokerSnapshot has data:

```python
async def status(self) -> CompositeStatus:
    snapshot = await self._broker_snapshot.latest_with_labels()
    
    # Detect warming-up state
    snapshot_empty = not snapshot
    
    # ... fetch other adapters in parallel ...
    
    return CompositeStatus(
        timestamp=...,
        snapshot_empty=snapshot_empty,
        snapshot_age_s=self._broker_snapshot.oldest_age_s() if snapshot else None,
        # ... rest ...
    )
```

`BrokerSnapshot` exposes age:

```python
async def oldest_age_s(self) -> float | None:
    """Age of OLDEST cached reading. None if cache empty."""
    async with self._lock:
        if not self._latest:
            return None
        oldest_ts = min(r.timestamp for r in self._latest.values())
        return (datetime.now(UTC) - oldest_ts).total_seconds()
```

Format prompt detects warming up state:

```python
# In CompositeAdapter formatting
if status.snapshot_empty:
    temps_text = (
        "(температуры пока не пришли — поток данных только запускается, "
        "обычно занимает 5-15 секунд)"
    )
else:
    temps_text = format_temps_with_labels(...)
```

Tests:
- `test_composite_warming_up_when_snapshot_empty`
- `test_composite_normal_when_snapshot_populated`
- `test_broker_snapshot_oldest_age_s_returns_none_when_empty`

---

## Phase 4 — Track C: complete russian-fication (1.5 hours)

This is **substantial scope** but Vladimir's explicit goal. Apply
systematically across operator-facing surface.

### 4.1 Phase enum russian-fication

`src/cryodaq/core/experiment.py`:

```python
class ExperimentPhase(StrEnum):
    PREPARATION = "preparation"  # internal value
    VACUUM = "vacuum"
    COOLDOWN = "cooldown"
    MEASUREMENT = "measurement"
    WARMUP = "warmup"
    TEARDOWN = "teardown"
```

Two options:

**Option C1 (preferred)** — Keep enum English internally (DB schema,
code), add display layer:

```python
PHASE_DISPLAY_NAMES_RU = {
    ExperimentPhase.PREPARATION: "подготовка",
    ExperimentPhase.VACUUM: "откачка вакуума",
    ExperimentPhase.COOLDOWN: "захолаживание",
    ExperimentPhase.MEASUREMENT: "измерение",
    ExperimentPhase.WARMUP: "отогрев",
    ExperimentPhase.TEARDOWN: "разборка",
}

def phase_display_name(phase: ExperimentPhase | str) -> str:
    """Operator-facing Russian label for phase."""
    if isinstance(phase, str):
        try:
            phase = ExperimentPhase(phase)
        except ValueError:
            return phase  # passthrough unknown
    return PHASE_DISPLAY_NAMES_RU.get(phase, phase.value)
```

ExperimentAdapter calls phase_display_name() before passing to
prompt. Format prompts receive Russian phase string directly.

**Option C2 (avoid)** — Change enum string values к Russian.
Breaks DB schema, migration headache, не recommended.

Architect picks C1.

### 4.2 Format prompt field names russian-fication

Replace ALL English internal field names в format prompt templates
с Russian:

`prompts.py` BEFORE/AFTER:

```python
# BEFORE
FORMAT_ETA_COOLDOWN_USER = """\
Запрос: {query}

Прогноз охлаждения:
- T_cold сейчас: {t_cold} K
- Прогресс: {progress_pct:.1f}%
- Фаза: {phase}
- Осталось до 4К: {t_remaining_str} (CI 68%: {ci_low:.1f}-{ci_high:.1f} ч)
- Кривых в ансамбле: {n_references}
- Cooldown активен: {cooldown_active}

Если cooldown не активен или прогноза нет — честно скажи.
"""

# AFTER
FORMAT_ETA_COOLDOWN_USER = """\
Запрос: {query}

Прогноз захолаживания:
- Холодная температура сейчас: {t_cold} K
- Прогресс: {progress_pct:.1f}%
- Фаза: {phase_ru}
- Осталось до 4К: {t_remaining_str} (доверительный интервал 68%: {ci_low:.1f}-{ci_high:.1f} ч)
- Кривых в ансамбле: {n_references}
- Захолаживание активно: {cooldown_active_ru}

Если захолаживание не идёт или прогноза нет — честно скажи по-человечески.
"""
```

Pattern: every English label/term/word в operator-facing prompt
content → Russian equivalent. Format strings still use Python
parameter names (English `{phase_ru}` syntax) but human-readable
content all Russian.

Apply same translation к ALL templates:
- FORMAT_RESPONSE_SYSTEM (instruction words)
- FORMAT_CURRENT_VALUE_USER
- FORMAT_ETA_COOLDOWN_USER
- FORMAT_ETA_VACUUM_USER
- FORMAT_RANGE_STATS_USER
- FORMAT_PHASE_INFO_USER
- FORMAT_ALARM_STATUS_USER
- FORMAT_COMPOSITE_STATUS_USER
- FORMAT_OUT_OF_SCOPE_HISTORICAL_USER
- FORMAT_OUT_OF_SCOPE_GENERAL_USER
- FORMAT_UNKNOWN_USER

### 4.3 Critical translations

Mapping table (architect compiled, apply consistently):

| English | Russian (operator-facing) |
|---|---|
| cooldown | захолаживание |
| warmup | отогрев |
| measurement | измерение |
| preparation | подготовка |
| vacuum (phase) | откачка вакуума |
| teardown | разборка |
| Cooldown active | Захолаживание активно |
| current_mbar | давление сейчас |
| target_mbar | цель |
| t_cold | холодная температура |
| t_warm | тёплая температура |
| t_remaining | осталось |
| n_references | кривых в ансамбле |
| confidence | уверенность |
| trend | тренд (acceptable, общеупотребимо) |
| CI 68% | доверительный интервал 68% |
| min / max / mean / σ | мин / макс / среднее / σ (σ acceptable) |
| precision | точность |
| Unicode | Юникод |
| LaTeX | без замены — техническое название |
| physics / engineering | физика / инженерия |
| current state | текущее состояние |
| live query | онлайн-запрос (или "запрос текущего состояния") |
| ETA | ETA (общеупотребимо в технической русской, можно оставить) ИЛИ "прогноз времени" |
| RUNNING (status) | работает |
| ACTIVE | активен |
| COMPLETED | завершён |
| ABORTED | прерван |

Notes:
- **Units stay**: K, mbar, sec, min, ч, %, σ, π, R²
- **Channel IDs stay**: Т1-Т24 (already Cyrillic)
- **API/protocol terms stay**: JSON, UUID (внутреннее, не показываем
  оператору в любом случае), HTTP, REST
- **ETA debate**: общеупотребимо в технической русской
  (Wikipedia на русском использует "ETA"), но Vladimir может
  предпочесть "прогноз времени" — surface для ratify

### 4.4 Boolean stringification

`cooldown_active: True` → `"да"` / `"нет"` через helper:

```python
def ru_bool(value: bool | None) -> str:
    """Russian rendering for boolean fields in prompts."""
    if value is None:
        return "неизвестно"
    return "да" if value else "нет"
```

Apply at adapter formatting layer (where dict→str conversion happens
before prompt fill).

### 4.5 ExperimentStatus enum russian-fication

Same Option C1 pattern:

```python
EXPERIMENT_STATUS_RU = {
    ExperimentStatus.RUNNING: "работает",
    ExperimentStatus.COMPLETED: "завершён",
    ExperimentStatus.ABORTED: "прерван",
}

def experiment_status_display(status: ExperimentStatus | str) -> str:
    if isinstance(status, str):
        try:
            status = ExperimentStatus(status)
        except ValueError:
            return status
    return EXPERIMENT_STATUS_RU.get(status, status.value)
```

### 4.6 Slash command outputs check

Recon TelegramCommandBot slash command handlers (/status, /alarms,
/keithley, etc) for any English leakage. Common candidates:
- "Аптайм" (это OK, "uptime" calque already в Russian) — keep
- "Тревоги: нет" — OK
- "приборов: <name> активен" — OK (already Russian)

Likely already mostly Russian. Verify `/status`, `/alarms`,
`/help`, `/phase`. Fix any remaining English.

### 4.7 Tests

```python
# tests/agents/assistant/test_russian_fication.py

def test_phase_display_name_russian():
    assert phase_display_name(ExperimentPhase.COOLDOWN) == "захолаживание"
    assert phase_display_name(ExperimentPhase.WARMUP) == "отогрев"
    assert phase_display_name(ExperimentPhase.MEASUREMENT) == "измерение"

def test_phase_display_name_passthrough_unknown():
    assert phase_display_name("unknown_phase") == "unknown_phase"

def test_experiment_status_display_russian():
    assert experiment_status_display(ExperimentStatus.RUNNING) == "работает"
    assert experiment_status_display(ExperimentStatus.COMPLETED) == "завершён"

def test_ru_bool():
    assert ru_bool(True) == "да"
    assert ru_bool(False) == "нет"
    assert ru_bool(None) == "неизвестно"

def test_format_prompts_no_english_leakage():
    """Verify FORMAT_* prompts contain no English content words."""
    import re
    from cryodaq.agents.assistant.query import prompts as p
    
    # Allowed English: units, technical abbreviations, parameter names
    ALLOWED_ENGLISH = {
        "K", "mbar", "Pa", "torr", "ETA", "JSON", "LaTeX", "Unicode",
        "min", "max", "GUI", "API", "F33", "v0.49.0",
    }
    
    PROMPTS_TO_CHECK = [
        p.FORMAT_RESPONSE_SYSTEM,
        p.FORMAT_CURRENT_VALUE_USER,
        p.FORMAT_ETA_COOLDOWN_USER,
        p.FORMAT_ETA_VACUUM_USER,
        p.FORMAT_RANGE_STATS_USER,
        p.FORMAT_PHASE_INFO_USER,
        p.FORMAT_ALARM_STATUS_USER,
        p.FORMAT_COMPOSITE_STATUS_USER,
        p.FORMAT_OUT_OF_SCOPE_HISTORICAL_USER,
        p.FORMAT_OUT_OF_SCOPE_GENERAL_USER,
        p.FORMAT_UNKNOWN_USER,
    ]
    
    for prompt in PROMPTS_TO_CHECK:
        # Find English words (3+ alphabetic chars, all-ASCII)
        # Excluding format placeholders {...}
        # Excluding allowed terms
        without_placeholders = re.sub(r"\{[^}]*\}", "", prompt)
        english_words = re.findall(r"\b[A-Za-z]{3,}\b", without_placeholders)
        leaked = [w for w in english_words if w not in ALLOWED_ENGLISH]
        assert not leaked, f"English leakage in prompt: {leaked}\nPrompt:\n{prompt[:200]}..."

def test_eta_cooldown_uses_zaholazhivanie():
    """FORMAT_ETA_COOLDOWN_USER uses "захолаживание" not "cooldown"."""
    from cryodaq.agents.assistant.query import prompts as p
    assert "захолаживан" in p.FORMAT_ETA_COOLDOWN_USER
    assert "cooldown" not in p.FORMAT_ETA_COOLDOWN_USER.lower()
```

---

## Phase 5 — Track D: composite prompt anti-pattern (15 min)

`FORMAT_COMPOSITE_STATUS_USER` strengthening:

```python
FORMAT_COMPOSITE_STATUS_USER = """\
Запрос: {query}

Полный статус системы:

Эксперимент: {experiment_text}
Фаза: {phase_text}
Ключевые температуры: {temps_text}
Давление: {pressure_text}
Прогноз захолаживания: {cooldown_eta_text}
Прогноз вакуума (до 10⁻⁶): {vacuum_eta_text}
Активные тревоги: {alarms_text}

ВАЖНО — структура ответа:
- НЕ начинай ответ с упоминания канала или прибора как обращения.
- Начни с состояния системы (фаза, эксперимент) или с приветствия,
  если оператор поздоровался.
- Каналы упоминай в перечислении, не в начале предложения.

Пример хорошего ответа:
"У нас идёт «эксперимент-001» в фазе захолаживания. Все ключевые
температуры в норме: Т7 Детектор 3.9 K, Т6 Экран 4К 4.09 K,
Т1 Криостат верх 4.20 K. Давление 1.65·10⁻⁶ mbar. Тревог нет."

Пример ПЛОХОГО ответа (НЕ ДЕЛАЙ ТАК):
"Т7 Детектор, сейчас система в фазе захолаживания..."
^^^ Канал в начале предложения как обращение — НЕЛЬЗЯ.

Сгенерируй сводку (3-5 предложений).
"""
```

Negative example в prompt — LLMs learn от concrete anti-patterns
лучше чем abstract rules.

Test:
```python
def test_composite_response_doesnt_start_with_channel_name():
    """LLM smoke output не начинается с 'Т<N> ...'."""
    # Mock LLM response check OR real Ollama smoke
```

---

## Phase 6 — Re-smoke (30 min)

Manual repeat from Vladimir's phone после restart с обновлённым кодом:

### Smoke scenarios

1. "привет" → greeting (regression check)
2. "что сейчас?" — composite query:
   - Чарт ДОЛЖЕН прийти (Track A fix)
   - НЕТ "температуры отсутствуют" — либо real values OR honest "пока не пришли — поток только запускается" (Track B)
   - НЕТ начала с "Т7 Детектор," (Track D)
   - НЕТ "cooldown" — ДА "захолаживание" (Track C)
   - НЕТ "Cooldown активен" — ДА "захолаживание активно/идёт"
3. "ETA охлаждения" → ответ с "захолаживание" (Track C)
4. "в какой фазе?" → русское название фазы (Track C)
5. "в каком диапазоне P?" → range_stats response, чарт также arrives
6. Edge case: composite query within first 5s after engine restart →
   honest "поток данных только запускается" message (Track B)

After all 6 scenarios PASS:

Document в `artifacts/handoffs/2026-05-XX-hf-v0.47.2-resmoke-pass.md`
с before/after sample texts AND chart screenshots.

If any scenario FAILS → STOP, surface issue.

---

## Phase 7 — Codex audit (single-verifier)

Per ORCHESTRATION v1.4 §16.3 — fix-up scope (not new feature),
1-model audit sufficient.

Focus auditor on:
- Track A fix correctness (chart dispatch path traced end-to-end)
- Track B race handling (warming-up reason path exercised in tests)
- Track C russian-fication completeness (all FORMAT_* prompts checked)
- Track D anti-pattern reproducibility (negative example renders correctly)
- Backward compat: existing F30 + F28 + F29 tests stay green
- No new English leakage in operator-facing surface

Append calibration log record.

---

## Phase 8 — v0.47.2 release

After re-smoke PASS + audit PASS:

1. Bump pyproject.toml: 0.47.1 → 0.47.2
2. CHANGELOG entry (extend v0.47.2 section с fix-up cycle additions)
3. ROADMAP unchanged (no F-task structural changes)
4. Tag, push to master

CHANGELOG addition:
```markdown
### Fixed (Phase E fix-up)
- Chart attachment now actually dispatches to Telegram (was wired
  but failed silently — exception handler added к async task)
- Empty BrokerSnapshot no longer reports "температуры отсутствуют"
  on engine startup race; honest "поток данных только запускается"
  message instead
- Composite response no longer starts with channel name as greeting
  ("Т7 Детектор, сейчас..." anti-pattern eliminated via prompt
  example)
- Complete russian-fication of operator-facing surface:
  - ExperimentPhase enum gets Russian display layer (захолаживание,
    отогрев, измерение, подготовка, откачка вакуума, разборка)
  - ExperimentStatus enum (работает, завершён, прерван)
  - All FORMAT_* prompt content English → Russian
  - Boolean fields render as да/нет/неизвестно
  - Field name labels in prompts русифицированы
  - test_format_prompts_no_english_leakage prevents regression
```

---

## Hard stops

- Phase 1 reveals architectural issue не covered by Fix 1A-D → STOP, architect spec amendment
- Phase 4.7 `test_format_prompts_no_english_leakage` failures cannot be resolved without breaking other tests → STOP, surface
- Re-smoke FAILS → STOP, deeper architectural issue
- Existing F28/F29/F30 tests start failing после fixes → STOP, regression

---

## Begin

1. Phase 1 — Track A investigation (30 min)
2. Surface Phase 1 findings to architect, await ratify
3. Phase 2 — Track A fix (30 min)
4. Phase 3 — Track B defensive (30 min)
5. Phase 4 — Track C russian-fication (1.5 hours)
6. Phase 5 — Track D prompt fix (15 min)
7. Phase 6 — re-smoke from phone (30 min)
8. Phase 7 — Codex audit (15 min wait + classify)
9. Phase 8 — v0.47.2 release (10 min)

Total estimate: ~4 hours.

GO.
