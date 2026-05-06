# HF v0.47.2 — Final fix-up cycle: query agent wiring + SSL invariant + display name resolution

> Multi-track fix-up cycle aggregating ALL outstanding regressions
> и pending features накопленных в real-world testing 2026-05-01.
>
> **CRITICAL CONTEXT:** Architect manually fixed 2 regressions
> в this session (engine.py + instruments.yaml merge conflict
> markers, plus SSL config knob in telegram.py / telegram_commands.py
> / engine.py wiring) because CC keeps regressing them. Architect
> manual intervention is COSTLY и should be last resort. CC must
> protect baseline behaviors.
>
> Effort: M (~250 LOC code + ~80 tests = ~330 LOC total).
> Estimated: 3-4 hours.

---

## 0. Operating posture

- Branch: `hotfix/v0.47.2-final-fixup` from current master
- Architect synchronously available
- SHIP PRIORITY: protect SSL invariant, restore Гемма conversation,
  add display name resolution, complete russification, attach charts
- Multi-verifier per ORCHESTRATION v1.4 §16.3: foundational scope —
  Codex + GLM-5.1 minimum. SSL invariant must be in audit checklist.

---

## 1. CRITICAL — DO NOT REGRESS BASELINE

These behaviors MUST work after every CC commit. Verify before
every push.

### 1.1 SSL config knob (v0.47.1)

```bash
# Regression check command — MUST show ≥6 verify_ssl occurrences
grep -n "verify_ssl" \
  src/cryodaq/notifications/telegram.py \
  src/cryodaq/notifications/telegram_commands.py \
  src/cryodaq/engine.py | wc -l
```

Required state:

| File | Required occurrences |
|---|---|
| `src/cryodaq/notifications/telegram.py` | ≥4: constructor param, `self._verify_ssl =`, WARNING log conditional, `_get_session` connector, `from_config` reads tg.get("verify_ssl") |
| `src/cryodaq/notifications/telegram_commands.py` | ≥4: same pattern |
| `src/cryodaq/engine.py` | ≥3: read из tg_cfg, pass к TelegramCommandBot, pass к TelegramNotifier для escalation |

Required runtime behavior:
- `verify_ssl=False` → `aiohttp.TCPConnector(ssl=False)` passed to ClientSession
- `verify_ssl=False` → WARNING logged once at construction
- `verify_ssl=True` (default) → existing aiohttp default behavior preserved

Test file `tests/notifications/test_telegram_ssl_verification.py` MUST
exist and pass. If absent — STOP, surface to architect (was deleted
by previous cycle).

### 1.2 No merge conflict markers

```bash
# Regression check — MUST return zero results
grep -rn "<<<<<<< Updated\|>>>>>>> Stashed\|======= " \
  src/cryodaq/ config/ tests/ 2>/dev/null
```

If `git stash pop` leaves markers — STOP, manual resolve required.

### 1.3 ChannelManager wiring (v0.47.2)

```bash
grep -n "channel_manager" src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py
grep -n "get_display_name" src/cryodaq/agents/assistant/query/adapters/composite_adapter.py
```

`BrokerSnapshot` must accept `channel_manager` parameter.
`CompositeAdapter` must use display labels from ChannelManager,
not raw channel IDs.

### 1.4 Engine smoke check

After any commit touching engine.py:

```bash
python -c "import cryodaq.engine"
# MUST exit 0. If syntax error → STOP, fix immediately.
```

### 1.5 Test baseline

```bash
pytest tests/ --tb=line -q 2>&1 | tail -5
# MUST end с "228 passed" minimum (allow growth — never shrink).
```

---

## 2. Outstanding issues from real-world testing

### Issue 1 (CRITICAL) — Гемма не отвечает на free-text queries

```
13:54:35 Vladimir: Привет!
13:54:35 Bot: Я понимаю только slash-команды. /help для списка.

13:55:08 Vladimir: /ask Привет!
13:55:09 Bot: Я понимаю только slash-команды. /help для списка.
```

Bot returns "I understand only slash commands" fallback. This means
`TelegramCommandBot._handle_text` sees `self._query_agent is None`
either always или conditionally.

Either:
- `AssistantQueryAgent` failed construction (silent exception
  during engine startup)
- Engine не выполнил `telegram_bot._query_agent = _query_agent`
  assignment
- `_handle_text` checks something other than `_query_agent`

Plus `/ask` command also returns slash-only fallback — `/ask <query>`
handler must also route к query agent.

### Issue 2 (CRITICAL) — Chart не приходит на composite queries

Per previous smoke FAIL spec — chart dispatch wired but doesn't
fire. Investigate в Phase 2.

### Issue 3 (HIGH) — "Температуры отсутствуют" race

BrokerSnapshot empty в первые секунды после engine startup. Per
previous smoke spec Track B — defensive empty-snapshot detection.

### Issue 4 (HIGH) — Display name resolution

Operator says "что на азотной плите?", classifier doesn't know
Т12 = "Азотная плита" (renamed via GUI ChannelEditor). Per
v0.47.3 spec — late binding ChannelManager в classifier.

**Vladimir clarified:** rename happens MID-CAMPAIGN. Engine restart
NOT acceptable. Classifier must read ChannelManager fresh on
EVERY classify() call (late binding).

### Issue 5 (MEDIUM) — Complete russification

Phase enum still leaks "cooldown" в operator-facing output.
Format prompts contain "physics", "engineering", "current state".
Per v0.47.2 fix-up spec Track C.

### Issue 6 (MEDIUM) — Composite text starts с channel name

"Т7 Детектор, сейчас система в фазе..." anti-pattern. Per fix-up
spec Track D — explicit negative example в prompt.

### Issue 7 (HIGH) — Latin vs Cyrillic channel ID confusion

Real-world test 2026-05-01 14:41:51:
```
WARNING: QueryRouter: cannot resolve target_channel 'T12' to known ID
```

LLM classifier returned target_channels=["T12"] — **Latin T**. Real
channel IDs use **Cyrillic Т** ("Т12" — different Unicode code
point U+0422 vs U+0054). visually identical, semantically distinct.

Root causes:
- INTENT_CLASSIFIER_SYSTEM contains examples with Latin "T1", "T_cold"
  — LLM learns Latin pattern
- find_by_name() doesn't normalize Latin↔Cyrillic confusables
- Operator может typo any way (Russian keyboard layout makes Cyrillic
  default; English layout makes Latin default)

Fix: BOTH paths
1. INTENT_CLASSIFIER_SYSTEM examples ALL use Cyrillic Т matching real
   channel IDs (грep prompts.py для any Latin T occurrences in
   channel context, replace)
2. ChannelManager.find_by_name() and resolve logic: try resolution with
   confusable normalization. Map Latin {T,t,K,k,M,m,O,o,P,p,A,a,B,B,c,C,e,E,H,h,X,x,y,Y}
   к Cyrillic equivalents and vice versa, retry lookup.
   Simpler: just normalize "T"→"Т" в input (most common operator confusion
   case).

### Issue 8 (HIGH) — Timestamp hallucination в response

Real-world test 2026-05-01 14:42:50:
```
Гемма: "Эксперимент начался в 00:00 UTC."
```

Engine startup в 14:41 UTC, current time 14:42 UTC. "00:00 UTC" —
pure hallucination. Adapter likely passed `experiment_start_time:
null` or default datetime(0) к format prompt, LLM made up reasonable-
sounding value.

Fix:
- ExperimentAdapter must populate experiment_start_time correctly
  (real timestamp from ExperimentInfo.start_time)
- FORMAT_PHASE_INFO_USER prompt must explicitly instruct: "Если
  поле X = null или не указано — НЕ ПРИДУМЫВАЙ значение, скажи
  'не зафиксировано'"
- Anti-hallucination test scenarios в smoke (see §5)

### Issue 9 (HIGH) — Russification regression (phase still says "cooldown")

Real-world test 2026-05-01 14:42:50:
```
Гемма: "Сейчас мы находимся в фазе cooldown."
```

Previous session 03:32 had "захолаживание". Now "cooldown" again.
Track E (russification) regressed OR was never applied to this code
path.

Verify:
```bash
grep -n "PHASE_DISPLAY_NAMES_RU\|phase_display_name" \
  src/cryodaq/agents/assistant/query/ \
  src/cryodaq/agents/assistant/query/adapters/ \
  src/cryodaq/core/experiment.py
```

If phase_display_name() helper exists but adapters don't call it —
add call. If helper missing — implement per FIXUP spec §4.1.

---

## 3. Implementation tracks

Apply ALL tracks в single cycle, single commit per track,
final smoke + audit before tag.

### Track A — Diagnose & fix query agent wiring (CRITICAL)

Recon first:

```bash
# Check construction path
grep -n "AssistantQueryAgent\|_query_agent" src/cryodaq/engine.py
grep -n "_query_agent" src/cryodaq/notifications/telegram_commands.py

# Check _handle_text logic
grep -A 20 "_handle_text\|_handle_message" src/cryodaq/notifications/telegram_commands.py
```

Hypotheses:

**H1.** `AssistantQueryAgent` construction throws silently. Check
`agent.query.enabled` in `agent.yaml` — if `false`, agent never
constructed. Verify config file value.

**H2.** Construction succeeds но `_query_agent` reference не
assigned to `telegram_bot._query_agent`. Verify line:
```python
if telegram_bot is not None:
    telegram_bot._query_agent = _query_agent
```

**H3.** `_handle_text` checks wrong attribute. Should be:
```python
if self._query_agent is None:
    return slash_only_fallback
result = await self._query_agent.handle_query(text, chat_id=chat_id)
```

**H4.** `_handle_text` not even called for non-slash messages —
maybe text-handler dispatch path missing. Check
`_process_update` / message dispatch logic.

**H5.** `/ask <query>` handler exists but routes to slash-only
fallback instead of query agent. Should strip `/ask ` prefix and
call query agent same path as free-text.

Apply fix per investigation. After fix, smoke verify:

1. Send `Привет!` to bot → expect time-aware greeting (LATE
   BINDING note: classifier prompt rebuilds per call)
2. Send `что сейчас?` → expect composite status
3. Send `/ask что сейчас?` → expect identical to free-text path

### Track B — Display name resolution с LATE BINDING

Per `CC_PROMPT_HF_V0.47.3_DISPLAY_NAME_RESOLUTION.md` (recon
that file before implementing):

- IntentClassifier accepts `channel_manager: ChannelManager | None`
- `classify()` reads ChannelManager fresh on EVERY call (NOT
  cached at construction)
- Builds dynamic channel hint section in system prompt per call
- ChannelManager.find_by_name() — case-insensitive exact +
  substring match
- QueryRouter validates target_channels against ChannelManager
  state (also late-binding)

Smoke scenario CRITICAL: rename channel mid-session, verify next
classify() uses new name without engine restart. See
`CC_PROMPT_HF_V0.47.3` §2.3 step 3 для precise test.

### Track C — Defensive empty-snapshot handling

Per `CC_PROMPT_HF_V0.47.2_FIXUP_PHASE_E_FAIL.md` Phase 3:

```python
@dataclass
class CompositeStatus:
    timestamp: datetime
    snapshot_empty: bool  # NEW
    snapshot_age_s: float | None  # NEW — None если empty
    # ... rest ...
```

`BrokerSnapshot.oldest_age_s()` method.

Format prompt branch для warming-up state — operator sees
"поток данных только запускается, обычно занимает 5-15 секунд"
вместо "температуры отсутствуют".

### Track D — Chart dispatch fix

Per Fix scenarios 1A-1D в FIXUP spec. Investigation first via
audit JSON inspection или engine logs grep:

```bash
grep -i "chart\|send_photo\|sendPhoto" data/logs/engine.log | tail -30
ls data/agents/assistant/audit/2026-05-01/ | tail
```

Apply Fix 1A (engine wiring) / 1B (category mismatch) / 1C
(send_photo not exposed) / 1D (async crash) per investigation.

Plus unconditional: add `task.add_done_callback(_log_exception)`
к chart dispatch task — prevent silent failures forever.

### Track E — Complete russification

Per FIXUP spec Phase 4:

- ExperimentPhase display layer (захолаживание, отогрев,
  измерение, подготовка, откачка вакуума, разборка)
- ExperimentStatus display layer (работает, завершён, прерван)
- All FORMAT_* prompts: English content words → Russian
- ru_bool() helper для boolean rendering
- Regression test `test_format_prompts_no_english_leakage`

Mapping table in FIXUP spec §4.3.

### Track G — Latin/Cyrillic confusable normalization

**Sub-track G.1 — INTENT_CLASSIFIER_SYSTEM cleanup:**

```bash
# Find all Latin T mentions в classifier prompt
grep -n "T1\|T_\|t_cold\|T_cold" src/cryodaq/agents/assistant/query/prompts.py
```

Replace ALL Latin channel references (T1, T_cold, T_warm, T_4K) с
Cyrillic Т где они context'но channel IDs:
- "какая T1" → "какая Т1"
- "T_cold?" → leave as physics quantity reference (not channel)
- "температура T1" → "температура Т1"

Keep Latin physical-quantity letters (T as temperature symbol в
formulas, не channel ID).

**Sub-track G.2 — ChannelManager.find_by_name() Latin→Cyrillic fallback:**

After exact + substring fail, try Latin→Cyrillic normalization:

```python
# In ChannelManager
_LATIN_TO_CYRILLIC = str.maketrans({
    "T": "Т", "t": "т",  # most common: T→Т for channel IDs
    "A": "А", "a": "а",  # also confusable
    "K": "К", "k": "к",
    "M": "М", "O": "О", "o": "о",
    "P": "Р", "p": "р",
    "H": "Н", "E": "Е", "e": "е",
    "B": "В", "C": "С", "c": "с",
    "X": "Х", "x": "х", "y": "у", "Y": "У",
})

def find_by_name(self, name: str) -> str | None:
    # ... existing exact + substring logic ...
    
    # Final fallback: Latin→Cyrillic confusable normalization
    normalized = name.translate(_LATIN_TO_CYRILLIC)
    if normalized != name:  # if any substitution happened
        # Retry exact ID match с normalized version
        if normalized in self._channels:
            return normalized
        # Retry substring match с normalized
        normalized_lower = normalized.lower().strip()
        for ch_id, ch_data in self._channels.items():
            ch_name = ch_data.get("name", "").lower()
            if normalized_lower == ch_name or normalized_lower in ch_name:
                return ch_id
    
    return None
```

**Sub-track G.3 — Tests:**

```python
def test_find_by_name_resolves_latin_t_to_cyrillic_id():
    """'T12' → 'Т12' (Latin T → Cyrillic Т fallback)."""

def test_find_by_name_resolves_latin_t_in_substring():
    """'T7 sensor' → 'Т7' even with Latin T."""

def test_router_resolves_latin_t_via_channelmanager():
    """target_channels=['T12'] → resolved to 'Т12' via Latin fallback."""

def test_classifier_prompt_no_latin_channel_refs():
    """INTENT_CLASSIFIER_SYSTEM contains zero Latin 'T<digit>' patterns
    (all replaced with Cyrillic Т<digit>)."""
```

### Track H — Anti-hallucination prompt strengthening

**Issue:** "Эксперимент начался в 00:00 UTC" hallucination. Format
LLM получил null/empty timestamp field, invented plausible value.

**Sub-track H.1 — Adapter null-safety:**

ExperimentAdapter must explicitly populate timestamp fields:

```python
@dataclass
class ExperimentStatus:
    experiment_id: str
    display_name: str | None
    phase: str | None
    phase_started_at: float | None
    phase_started_human: str | None  # "14:41 MSK 01.05.2026" или None
    experiment_started_at: float | None
    experiment_started_human: str | None  # NEW
    experiment_age_s: float
    target_temp: float | None
    sample_id: str | None
```

CompositeAdapter.format_experiment_text():
```python
if status.experiment_started_human:
    text = f"эксперимент «{status.display_name}» начат {status.experiment_started_human}"
else:
    # Empty timestamp — DON'T make up value
    text = f"эксперимент «{status.display_name}»"  # omit start time entirely
```

**Sub-track H.2 — Format prompt explicit anti-hallucination:**

Add к FORMAT_RESPONSE_SYSTEM:

```
КРИТИЧНО ПРОТИВ ВЫДУМЫВАНИЯ:
- Если в данных значение = None / null / отсутствует / пусто:
  НЕ ПРИДУМЫВАЙ значение. Скажи "не зафиксировано" или
  пропусти упоминание этого поля совсем.
- Если timestamp не указан — НЕ пиши "00:00", "начало эпохи",
  "вчера в полдень" или любое другое выдуманное время.
- Если канал не упомянут в данных — НЕ упоминай его.
- Если фаза None — скажи "фаза не определена" а не выбирай
  одну из возможных вариантов.
```

**Sub-track H.3 — Tests:**

```python
def test_format_doesnt_invent_timestamp_when_none():
    """experiment_started_at=None → response не contains '00:00' или
    other invented timestamps."""

def test_format_doesnt_invent_phase_when_none():
    """phase=None → response says 'фаза не определена' or omits."""

def test_adapter_populates_human_timestamps():
    """experiment_started_human field correctly formatted from datetime."""
```

### Track F — Composite anti-pattern в prompt

Per FIXUP spec Phase 5:

```python
FORMAT_COMPOSITE_STATUS_USER = """\
...

ВАЖНО — структура ответа:
- НЕ начинай ответ с упоминания канала или прибора как обращения.

Пример хорошего ответа:
"У нас идёт «эксперимент-001» в фазе захолаживания. ..."

Пример ПЛОХОГО ответа (НЕ ДЕЛАЙ ТАК):
"Т7 Детектор, сейчас система в фазе захолаживания..."
^^^ Канал в начале предложения как обращение — НЕЛЬЗЯ.
"""
```

---

## 4. Implementation order

Apply tracks sequentially, commit per track. Final smoke after
all tracks complete.

1. **Pre-flight checks (§1):** verify SSL invariant intact,
   no merge markers, baseline tests pass, engine imports clean.
   STOP if any fails.
2. **Track A** — query agent wiring (highest priority — без
   него весь rest unverifiable).
3. **Track C** — empty-snapshot defensive (helps Track A smoke).
4. **Track B** — display name resolution.
5. **Track E** — russification.
6. **Track F** — composite anti-pattern.
7. **Track D** — chart dispatch (last — depends на A working).
8. **Final regression check (§1):** SSL + markers + tests pass.
9. **Real-world smoke** (Vladimir с phone, manual).
10. **Multi-verifier audit:** Codex + GLM-5.1 минимум. SSL invariant
    в auditor focus list.
11. **Tag v0.47.2** (replacing the broken v0.47.2 already pushed —
    use force-push only with architect approval, OR ship as v0.47.3
    с changelog note про superseding).

---

## 5. Acceptance criteria

After all tracks:

1. ✅ "Привет!" → friendly greeting, NO slash-only fallback
2. ✅ "что сейчас?" → composite Russian response
3. ✅ "/ask что сейчас?" → identical к free-text path
4. ✅ "что на азотной плите?" → resolves к Т12 (display name)
5. ✅ Mid-session rename → next query uses new name (LATE BINDING)
6. ✅ Composite query → PNG chart attached
7. ✅ NO "Cooldown" / "warmup" / "measurement" English leaks
8. ✅ NO "Т7 Детектор, сейчас..." anti-pattern (composite не
   starts с channel)
9. ✅ Empty BrokerSnapshot → "поток данных только запускается"
   message, NOT "температуры отсутствуют"
10. ✅ SSL config knob preserved (regression check §1.1 passes)
11. ✅ ALL existing tests pass (228+ baseline)
12. ✅ ≥30 new tests across all tracks
13. ✅ Engine starts cleanly (`python -c "import cryodaq.engine"` zero)
14. ✅ Multi-verifier audit clean (Codex + GLM)

---

## 6. Hard stops

- Pre-flight check (§1) reveals SSL regression → STOP, restore
  before any other work
- Engine import fails → STOP, fix immediately
- Track A investigation reveals architectural issue → STOP, surface
- 228 baseline tests fail после any track → STOP, regression
- Audit finds CRITICAL post-fix → STOP, fix-up cycle on this branch

---

## 7. Architect comm-out discipline

Surface immediately:
- Track A diagnosis result (which Hypothesis applies)
- Any merge conflict marker discovery (means git stash pop happened)
- SSL regression found (means baseline broken)
- Test count reduction (regression somewhere)

---

## 8. Begin

1. Pre-flight (§1) — STOP if any fails
2. Track A — query agent wiring (recon + fix + smoke each scenario)
3. Track C — empty-snapshot defensive
4. Track B — display name resolution с LATE BINDING
5. Track E — russification
6. Track F — composite anti-pattern
7. Track D — chart dispatch
8. Final regression check
9. Real-world smoke (manual Vladimir testing)
10. Multi-verifier audit (Codex + GLM-5.1)
11. Tag и push

GO.
