# HF v0.47.4 — Channel ID architecture: drivers vs ChannelManager mismatch

> Real-world test 2026-05-01 16:04 показал что `current_value` queries
> ВСЕГДА возвращают "Пока не вижу" — даже для direct channel ID `Т7`
> (Cyrillic). Composite queries работают и показывают `Т7 Детектор 3.89 K`.
>
> Architect recon (filesystem read, no edits) identified ROOT CAUSE:
> two sources of truth for channel names disagree.
>
> - `config/instruments.yaml` driver channel_labels:
>   `7: "Т7 Детектор"` (long composite string)
> - `config/channels.yaml` ChannelManager:
>   `Т7: {name: "Детектор"}` (short ID + separate display)
>
> Drivers emit `Reading.channel="Т7 Детектор"` (long form from
> instruments.yaml). BrokerSnapshot._latest cache stores under that
> long key. When operator says "Т7", router resolves via ChannelManager
> to "Т7" (short), adapter calls `snapshot.latest("Т7")` → returns None
> (cache key is long form, not short).
>
> ALSO: GUI ChannelEditor renames update channels.yaml only —
> instruments.yaml frozen. So renames don't actually propagate to
> what drivers emit. ChannelManager renames currently invisible
> к broker pipeline.
>
> Severity: CRITICAL — current_value queries unusable, defeats Гемма UX.
> Mid-session ChannelEditor renames don't work either (defeats v0.47.3
> LATE BINDING design — late binding picks up channels.yaml changes,
> but driver emission unchanged).
>
> Effort: M (architectural — investigate depth + implement). Estimated
> 2-3 hours including investigation.

---

## 1. Pre-flight checks (mandatory before any code changes)

### 1.1 SSL invariant (regression check)

```bash
grep -c "verify_ssl" \
  src/cryodaq/notifications/telegram.py \
  src/cryodaq/notifications/telegram_commands.py \
  src/cryodaq/engine.py
# MUST report ≥14 total occurrences (current baseline after v0.47.2 final fixup)
```

### 1.2 No merge conflict markers

```bash
grep -rn "<<<<<<< Updated\|>>>>>>> Stashed\|======= " \
  src/cryodaq/ config/ tests/ 2>/dev/null | wc -l
# MUST be 0
```

### 1.3 Engine smoke

```bash
python -c "import cryodaq.engine"
# MUST exit 0
```

### 1.4 Test baseline

```bash
pytest tests/ --tb=line -q 2>&1 | tail -5
# MUST end с "312 passed" minimum (current after v0.47.2 final fixup)
```

If ANY pre-flight fails — STOP, surface to architect.

---

## 2. Diagnostic confirmation (CC must run before fix)

### 2.1 Verify current channel ID form in cache

After engine starts in mock mode, observe via debugger or temporary
log:

```python
# Add to BrokerSnapshot._consume_loop temporarily:
logger.info("BrokerSnapshot received reading.channel=%r", reading.channel)
```

Run engine for 30s. Confirm log lines like:
```
BrokerSnapshot received reading.channel='Т7 Детектор'
BrokerSnapshot received reading.channel='Т12 Теплообменник 2'
BrokerSnapshot received reading.channel='VSP63D_1/pressure'
```

This confirms long-form channel IDs from drivers.

### 2.2 Verify ChannelManager keys

```python
# Temporary diagnostic
from cryodaq.core.channel_manager import get_channel_manager
cm = get_channel_manager()
print("Channel Manager keys:", list(cm.get_all())[:5])
# Expected: ['Т1', 'Т2', 'Т3', 'Т4', 'Т5']
```

Confirms short-form IDs in ChannelManager.

### 2.3 Verify mismatch

`snapshot.latest("Т7")` returns None.
`snapshot.latest("Т7 Детектор")` returns Reading.

Surface findings to architect before proceeding to fix selection.

---

## 3. Fix options (architect's preliminary analysis)

### Option A — Clean architecture (PREFERRED if safe)

instruments.yaml uses short canonical IDs:

```yaml
# BEFORE
channels:
  7: "Т7 Детектор"
  12: "Т12 Теплообменник 2"

# AFTER
channels:
  7: "Т7"
  12: "Т12"
```

Drivers emit short IDs. ChannelManager owns ALL display names via
channels.yaml. ChannelEditor renames work end-to-end.

**Required investigation depth:**

```bash
# Find every consumer of Reading.channel
grep -rn "reading\.channel\|Reading.channel" src/ tests/ | wc -l
grep -rn "channel_labels\|channel_label" src/ | wc -l

# SQLite schema — does it store long or short form?
grep -A 5 "CREATE TABLE\|channel.*TEXT\|channel.*VARCHAR" src/cryodaq/storage/

# Existing DB rows
sqlite3 data/data_2026-05-01.db "SELECT DISTINCT channel FROM samples LIMIT 20" 2>/dev/null

# Alarm rules reference channels by which form?
grep "channel:" config/alarms*.yaml | head -10

# Calibration store keys
grep -rn "calibration_store\|sensor_id" src/cryodaq/analytics/calibration*.py | head
```

If SQLite, alarms, calibration all use long form → migration scope is
LARGE (data migration, schema versioning). Option A becomes risky for
hotfix scope.

If они already use short form OR могут быть updated cleanly → Option A
is the architecturally correct choice.

**Migration plan if Option A chosen:**
1. Update `config/instruments.yaml` — change all 24 channel labels к short IDs
2. ChannelManager handles display names entirely
3. SQLite migration: ALTER schema to add `display_name` column OR
   keep `channel` as canonical short ID и derive display via lookup
4. Existing DB data: add migration script to UPDATE rows from long → short
   form (regex-based: extract Т<digit>+ prefix)
5. Alarm rules: update to use short channel IDs if currently long
6. Calibration store: same
7. ALL tests update (fixtures с long-form channel names → short)

### Option B — Minimal-touch hotfix (RECOMMENDED if Option A migration too large)

`BrokerSnapshot._consume_loop` normalizes на ingest:

```python
async def _consume_loop(self) -> None:
    assert self._queue is not None
    while True:
        try:
            reading = await self._queue.get()
            short_id = self._normalize_channel_id(reading.channel)
            async with self._lock:
                self._latest[short_id] = reading
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("BrokerSnapshot consume error: %s", exc)

@staticmethod
def _normalize_channel_id(ch: str) -> str:
    """Extract short canonical channel ID.
    
    'Т7 Детектор' → 'Т7'
    'Т12 Азотная плита' → 'Т12'
    'VSP63D_1/pressure' → 'VSP63D_1/pressure' (no change — non-Т pattern)
    'Keithley_1/voltage' → no change
    'CH3' → 'CH3' (no change — fallback form)
    """
    # Try Cyrillic Т<digits> prefix
    parts = ch.split(" ", 1)
    first = parts[0] if parts else ch
    if first and first[0] == "Т" and len(first) >= 2 and first[1:].isdigit():
        return first
    return ch
```

Driver, SQLite, alarm engine, calibration store all unchanged.
ChannelManager renames automatically reflect (BrokerSnapshot stores
short ID, `display_name(ch)` looks up current ChannelManager state per
call — late binding pattern preserved).

**Pros:**
- Minimal change scope, low risk
- Doesn't touch driver, storage, alarm subsystems
- Existing SQLite data unchanged (alarm rules etc still work)
- Fix lands in single file (broker_snapshot.py) plus tests

**Cons:**
- Two channel ID forms in codebase (long в storage, short в broker cache)
- Future maintenance: developer must remember which form active в which layer
- Doesn't fix instruments.yaml architectural redundancy с channels.yaml

### Architect recommendation

CC investigate Option A migration scope first (§3.1 grep commands).
Surface findings:
- How many consumers of Reading.channel exist? (≥10 → Option B safer)
- What format does SQLite schema use? (long form → Option B safer for
  hotfix; rework as separate F-task later)
- Do alarm rules use channel by long or short form?

**If Option A migration scope ≤3 files outside instruments.yaml:** apply Option A.
**If Option A migration scope >3 files OR involves schema migration:** apply Option B.

CC must surface migration scope to architect и await confirmation
before proceeding с either Option.

---

## 4. Issue 2 — Experiment UUID display (secondary)

```
Гемма: "Эксперимент cc35331d8c89 находится в фазе захолаживания"
```

ExperimentInfo `name` / `title` field empty, `display_name` falls back
к UUID. Fix:

`src/cryodaq/agents/assistant/query/adapters/experiment_adapter.py`:

```python
def _resolve_display_name(self, info: ExperimentInfo) -> str:
    """Human-friendly experiment label, never raw UUID."""
    # 1. Use title if set
    title = (getattr(info, "title", None) or "").strip()
    if title:
        return title
    # 2. Use name if set
    name = (getattr(info, "name", None) or "").strip()
    if name:
        return name
    # 3. Fallback к "эксперимент-N" using sequence number from started_at
    started = getattr(info, "started_at", None)
    if started is not None:
        # Use date-derived label
        return f"эксперимент {started.strftime('%Y-%m-%d')}"
    # 4. Last resort: short UUID prefix
    uuid_str = str(info.experiment_id) if hasattr(info, "experiment_id") else "?"
    return f"эксперимент {uuid_str[:8]}"
```

Tests:
- `test_experiment_display_uses_title_when_set`
- `test_experiment_display_uses_name_when_title_empty`
- `test_experiment_display_uses_date_when_no_title_or_name`
- `test_experiment_display_never_returns_full_uuid`

---

## 5. Issue 3 — Stray response after greeting (low priority)

```
16:02:02 Bot: Привет. Чем могу помочь в лаборатории? Можешь спросить, что сейчас, ETA вакуума или в какой фазе?

Пока не вижу этих показаний.   ← stray, source unknown
```

После greeting message bot отправил вторую line "Пока не вижу этих
показаний." — unprovoked. Either:
- Greeting handler concatenates a degraded current_value response
- Multi-message dispatch from same query hits two paths
- Message buffer issue в TelegramCommandBot

Investigate:
```bash
grep -A 5 "_send_greeting\|handle_greeting\|greeting_text" \
  src/cryodaq/notifications/telegram_commands.py \
  src/cryodaq/agents/assistant/query/agent.py
```

Likely fix: ensure greeting handler returns single response, не falls
through к other handlers. Defer if investigation shows unrelated to
main current_value bug.

---

## 6. Implementation phases

### Phase 1 — Pre-flight (§1)

If any check fails — STOP.

### Phase 2 — Diagnostic confirmation (§2)

Run 2.1 + 2.2 + 2.3. Document findings. Surface к architect:
- Confirmed long-form channel IDs in BrokerSnapshot._latest cache
- Confirmed short-form keys in ChannelManager
- Confirmed `latest("Т7")` returns None while `latest("Т7 Детектор")` works

### Phase 3 — Option selection investigation (§3)

Run grep commands из §3.1. Surface findings:
- Count of `Reading.channel` consumers
- SQLite schema format
- Alarm rule channel form
- Calibration store format

Architect responds с **Option A** or **Option B** decision based on findings.

### Phase 4 — Implement chosen option

**If Option A:**
- Update instruments.yaml (24 channels)
- Verify driver tests still pass after channel_label changes
- SQLite migration script
- Alarm rule updates if needed
- Calibration store updates if needed
- All affected test fixtures
- Smoke each layer after change

**If Option B:**
- Add `_normalize_channel_id` static method к BrokerSnapshot
- Apply normalization in `_consume_loop`
- Tests:
  - `test_normalize_short_id_passthrough`
  - `test_normalize_long_id_extracts_short`
  - `test_normalize_pressure_channel_unchanged`
  - `test_normalize_keithley_channel_unchanged`
  - `test_normalize_ch_fallback_unchanged`
  - `test_consume_loop_stores_short_id`
  - `test_latest_short_id_returns_reading`
  - `test_latest_with_labels_uses_display_name_via_channel_manager`

### Phase 5 — Experiment display name fix (§4)

Independent track. Apply regardless of Option chosen.

Tests as listed в §4.

### Phase 6 — Stray response investigation (§5)

If discovered cause is greeting handler — fix. Else surface, defer.

### Phase 7 — Smoke testing (mandatory)

Vladimir performs от phone после restart:

1. `Привет!` → friendly greeting only, NO stray "Пока не вижу"
2. `выдай полную сводку` → composite Russian, **experiment display
   shows human label NOT UUID**
3. `Какая температура на Т7` → returns Т7 reading correctly
4. `Какая температура на T7` (Latin) → same, via Latin/Cyrillic norm
5. `Какая температура на детекторе?` → resolves to Т7 via display name
6. **Mid-session rename test:** rename Т7 в GUI ChannelEditor →
   `Какая температура на детекторе?` → fails (renamed),
   `Какая температура на <new name>?` → succeeds
7. **Mid-session rename direct ID:** Т7 still queryable as `Т7`
   regardless of display name state

If ANY scenario fails → surface, fix-up.

### Phase 8 — Multi-verifier audit

Foundational scope per ORCHESTRATION v1.4 §16.3 — Codex + GLM-5.1
minimum.

Auditor focus:
- §1 invariants preserved (SSL, merge markers, baseline tests)
- Option choice rationale correct
- Implementation matches spec
- Tests cover regression cases

### Phase 9 — Tag v0.47.4

CHANGELOG entry templates по applied option.

---

## 7. Acceptance criteria

1. ✅ Pre-flight checks pass (§1)
2. ✅ Diagnostic confirmation runs cleanly (§2)
3. ✅ Architect ratified Option A or B selection
4. ✅ `Какая температура на Т7` returns reading (Cyrillic direct ID)
5. ✅ `Какая температура на T7` returns reading (Latin → Cyrillic norm)
6. ✅ `Какая температура на детекторе?` resolves via display name to Т7
7. ✅ Composite query shows human experiment label, NOT UUID
8. ✅ Mid-session rename via GUI ChannelEditor reflects в next query
   without engine restart
9. ✅ NO stray "Пока не вижу" after greeting
10. ✅ All existing 312 tests still pass (no regression)
11. ✅ ≥15 new tests covering normalization + experiment display
12. ✅ SSL invariant preserved (≥14 verify_ssl occurrences)
13. ✅ Multi-verifier audit clean

---

## 8. Hard stops

- Pre-flight check fails → STOP, surface SSL/merge/import regression
- Diagnostic shows different root cause than architect identified → STOP, surface
- Option A migration scope larger than expected → STOP, surface to architect
  for Option B fallback decision
- Existing tests fail after change → STOP, regression
- Smoke fails any of 7 scenarios → STOP, fix-up

---

## 9. Begin

1. Phase 1 — pre-flight checks (§1)
2. Phase 2 — diagnostic confirmation, surface findings
3. Phase 3 — Option selection investigation, AWAIT architect decision
4. Phase 4 — implement chosen Option
5. Phase 5 — experiment display fix (parallel track)
6. Phase 6 — stray response investigation
7. Phase 7 — Vladimir smoke testing (manual)
8. Phase 8 — multi-verifier audit
9. Phase 9 — tag и push

GO.
