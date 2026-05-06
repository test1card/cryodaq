# HF v0.47.3 — Display name resolution в Intent Classifier (LATE BINDING)

> Real-world test показал что Vladimir переименовал датчики через
> ChannelEditor (Т12 → "Азотная плита", Т11 → "2 ступень"), но
> Гемма не resolve'ит operator queries по display name. Запрос
> "что у нас на азотной плите?" пропустил Т12 и вернул generic
> mix.
>
> ARCHITECT REQUEST source: realworld testing 2026-05-01 13:06.
>
> Severity: HIGH UX — operator changes channel names через GUI
> чтобы work conversationally, но Гемма игнорирует. Critical
> для real lab use.
>
> **CRITICAL design constraint** (architect-Vladimir clarification
> 2026-05-01): channel renames happen MID-CAMPAIGN, not at engine
> startup. Lab workflow: engine starts → preparation phase →
> sensor mounting + naming through GUI ChannelEditor → vacuum →
> cooldown → measurement → operator queries Гемма. If classifier
> prompt frozen at engine start, Гемма uses stale names forever.
> Engine restart НЕ ВАРИАНТ — destroys campaign state (BrokerSnapshot,
> alarm history, periodic counters, active experiment context).
>
> Solution: LATE BINDING — classifier reads ChannelManager fresh
> on every classify() call. ChannelManager is in-memory dict,
> per-call rebuild trivially cheap (~720 chars/24 channels), no
> performance concern.
>
> Effort: S (~80 LOC + 35 tests).

---

## 0. Context

### 0.1 Problem

Vladimir changed channel display names через ChannelEditor:
- Т11: "Теплообменник 1" → "2 ступень"
- Т12: "Теплообменник 2" → "Азотная плита"

These changes work в GUI и в `/temps` slash command (uses
`get_display_name()`). But Гемма Live Query Agent intent classifier
doesn't know about display names — `target_channels` resolution
fails.

### 0.2 Conversation that triggered this

```
Vladimir: А что у нас на азотной плите?
Гемма:    [returned Т1, Т2, Т7 + Т3, Т20 — generic mix, missed Т12]
```

Expected:

```
Гемма: На азотной плите (Т12) сейчас 78.4 K. Это нормальная
       рабочая температура для 1-й ступени GM-cooler.
```

### 0.3 Critical lab workflow constraint

Engine startup → preparation phase → operator mounts sensors →
operator names sensors via GUI ChannelEditor (these are
operational decisions made DURING preparation, not before engine
boot) → vacuum phase → cooldown → measurement → operator queries
Гемма.

Engine restart мid-campaign destroys:
- BrokerSnapshot cache (subscriber loses queued readings)
- Active alarm history (in-memory ring buffer, не persisted)
- Periodic report countdown timer
- Active experiment context
- Cooldown predictor accumulated history
- Sensor diagnostics rolling buffers
- Vacuum trend predictor data window

Architecturally HF must support **rename mid-campaign** without
restart. Classifier reads fresh state each query.

### 0.4 Issues

**I1 — Intent classifier doesn't know channel display names.**
INTENT_CLASSIFIER_SYSTEM prompt has hardcoded examples like
"какая T1" but no dynamic mapping from current ChannelManager
state.

**I2 — No fallback resolution layer.** If classifier returned
target_channels=["Т12"] for "азотная плита", flow would work.
Currently classifier doesn't even attempt to resolve.

**I3 — Possible operator vocabulary beyond display names.**
Aliases like "1-я ступень", "холодная точка", "болометр" —
not currently in display_name field. Defer to v0.47.4 if needed.

---

## 1. Architect decisions baked in

| Decision | Verdict | Rationale |
|---|---|---|
| Source of channel labels | `ChannelManager.get_display_name()` | Single source of truth |
| **When to inject mapping в prompt** | **At every classify() call — LATE BINDING** | **Operator renames mid-campaign. Engine restart NOT acceptable.** |
| Performance | Acceptable | ~24 channels × 30 chars = ~720 chars/query overhead, negligible vs LLM token costs |
| Channel state observer pattern | DEFER | Per-query rebuild reads fresh state correctly |
| Format в prompt | Channel ID → display name table | LLM uses for resolution |
| Fallback resolution | After classifier, в Router | If classifier returned target_channels, validate against ChannelManager; fuzzy match for partial |
| Aliases system | DEFER — v0.47.4 if needed | Display names cover most cases per current usage |

---

## 2. Implementation phases

### 2.1 Phase A — Intent classifier с late-binding ChannelManager (~30 LOC + tests)

`src/cryodaq/agents/assistant/query/intent_classifier.py`.

#### 2.1.1 Build channel hint section dynamically

```python
def _build_channel_hint(channel_manager: "ChannelManager | None") -> str:
    """Build channel reference table for classifier prompt.
    
    Reads CURRENT ChannelManager state — reflects all renames done
    via GUI ChannelEditor since engine startup (or anywhere).
    """
    if channel_manager is None:
        return ""
    
    visible_channels = []
    for ch_id in channel_manager.get_all():
        if not channel_manager.is_visible(ch_id):
            continue
        display = channel_manager.get_display_name(ch_id)
        # display = "Т12 Азотная плита" — extract just the name part
        parts = display.split(" ", 1)
        name = parts[1] if len(parts) > 1 else parts[0]
        visible_channels.append(f"  {ch_id} → \"{name}\"")
    
    if not visible_channels:
        return ""
    
    return (
        "\n\nДоступные каналы (channel_id → название):\n"
        + "\n".join(visible_channels)
        + "\n\nКогда оператор называет канал по имени (например "
        "\"азотная плита\", \"болометр\", \"детектор\"), "
        "найди соответствующий channel_id и положи в target_channels.\n"
    )
```

#### 2.1.2 Store ChannelManager reference, build prompt per-call

Modify `IntentClassifier.__init__`:

```python
class IntentClassifier:
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        model: str = "gemma4:e2b",
        temperature: float = 0.1,
        timeout_s: float = 15.0,
        channel_manager: "ChannelManager | None" = None,  # NEW
    ) -> None:
        self._ollama = ollama_client
        self._model = model
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._channel_manager = channel_manager  # store reference, NOT cached prompt
```

`classify()` rebuilds prompt per call:

```python
async def classify(self, query: str) -> QueryIntent:
    # LATE BINDING: rebuild channel hint section on every call.
    # Reflects GUI ChannelEditor renames since engine startup or last call.
    channel_hint = _build_channel_hint(self._channel_manager)
    system_prompt = INTENT_CLASSIFIER_SYSTEM + channel_hint
    
    # ... rest of classification logic uses system_prompt ...
```

This keeps the classifier stateless re channel data. ChannelManager
is a singleton in-memory dict updated by GUI commands; per-query
read picks up changes immediately, no notification mechanism needed.

#### 2.1.3 Engine wiring

`engine.py` query agent setup — add `channel_manager` to classifier
construction:

```python
intent_classifier = IntentClassifier(
    ollama_client=_q_ollama,
    model=_gemma_config.query_intent_model,
    temperature=_gemma_config.query_intent_temperature,
    timeout_s=_gemma_config.query_intent_timeout_s,
    channel_manager=get_channel_manager(),  # NEW — singleton, shared
)
```

`AssistantQueryAgent` accepts pre-constructed classifier or
constructs internally — match existing pattern. Whichever path:
ensure `channel_manager` reference reaches the classifier.

#### 2.1.4 Tests

```python
def test_classifier_rebuilds_prompt_on_every_call():
    """CRITICAL: prompt reflects current ChannelManager state, not cached.
    
    Setup: classifier with ChannelManager containing Т12="Теплообменник 2"
    Action 1: classify "что на теплообменнике 2" → should resolve to Т12
    Action 2: rename Т12 to "Азотная плита" via channel_manager.set_name()
    Action 3: classify "что на азотной плите" → should resolve to Т12
    
    Verify both queries succeed with their respective name resolutions.
    Verify second classify() rebuilds prompt with new name.
    """

def test_classifier_picks_up_channel_rename_without_restart():
    """Operator renames Т12 from 'Теплообменник 2' to 'Азотная плита'
    via ChannelManager.set_name() between two classify() calls.
    Second call sees new name in prompt without engine restart.
    Confirms LATE BINDING design holds."""

def test_classifier_prompt_includes_channel_hints_when_manager_provided():
    """ChannelManager provided → system prompt contains channel mapping table."""

def test_classifier_prompt_omits_hints_when_no_manager():
    """ChannelManager=None → no hint section appended."""

def test_classifier_prompt_skips_invisible_channels():
    """is_visible=False channels not in hint."""

def test_classifier_resolves_renamed_channel_in_query():
    """Mock LLM call: 'азотная плита' → target_channels=['Т12'] when ChannelManager
    contains Т12='Азотная плита'."""

def test_classifier_handles_channel_with_no_display_name():
    """Channel with empty name field → fallback uses channel_id alone."""

def test_classifier_perf_per_call_overhead():
    """Per-call prompt rebuild adds <50ms overhead vs cached.
    Verifies LATE BINDING doesn't degrade typical 5-10s classification latency."""

def test_classifier_handles_concurrent_queries():
    """Two classify() calls concurrent. Each gets its own consistent prompt
    snapshot. No torn read of ChannelManager state mid-call."""
```

### 2.2 Phase B — Router fallback resolution (~25 LOC + tests)

`src/cryodaq/agents/assistant/query/router.py` — after classifier
returns intent, validate target_channels against ChannelManager
state (also reads fresh — late binding):

```python
class QueryRouter:
    def __init__(
        self,
        ...,
        channel_manager: "ChannelManager | None" = None,  # NEW
    ) -> None:
        ...
        self._channel_manager = channel_manager
    
    def _resolve_target_channels(
        self,
        intent: QueryIntent,
    ) -> list[str] | None:
        """Validate and resolve target_channels against current ChannelManager."""
        if not intent.target_channels:
            return None
        if self._channel_manager is None:
            return list(intent.target_channels)
        
        # Fresh read of ChannelManager state — late binding pattern
        all_channel_ids = set(self._channel_manager.get_all())
        resolved: list[str] = []
        
        for raw in intent.target_channels:
            raw_stripped = raw.strip()
            # Direct ID match (Т7, Т12, etc)
            if raw_stripped in all_channel_ids:
                resolved.append(raw_stripped)
                continue
            # Display name match (case-insensitive, partial)
            match_id = self._channel_manager.find_by_name(raw_stripped)
            if match_id:
                resolved.append(match_id)
                continue
            # Could not resolve — log and drop
            logger.warning(
                "Could not resolve target_channel '%s' to known channel ID",
                raw,
            )
        
        return resolved if resolved else None
```

#### 2.2.1 New ChannelManager method

`src/cryodaq/core/channel_manager.py`:

```python
def find_by_name(self, name: str) -> str | None:
    """Find channel ID by display name (case-insensitive, partial match).
    
    Tries exact match first, then substring match. Returns first hit
    or None if no match.
    
    Used by query agent router for late-binding channel resolution
    when operator references channel by display name.
    """
    name_lower = name.lower().strip()
    if not name_lower:
        return None
    
    # First pass: exact match
    for ch_id, ch_data in self._channels.items():
        ch_name = ch_data.get("name", "").lower()
        if name_lower == ch_name:
            return ch_id
    
    # Second pass: substring match (operator typed "плита" for "Азотная плита")
    for ch_id, ch_data in self._channels.items():
        ch_name = ch_data.get("name", "").lower()
        if name_lower in ch_name or ch_name in name_lower:
            return ch_id
    
    return None
```

Two-pass approach avoids substring bias when exact match exists.

#### 2.2.2 Tests

```python
def test_router_resolves_direct_channel_id():
    """target_channels=['Т7'] → ['Т7']."""

def test_router_resolves_display_name_to_id():
    """target_channels=['Азотная плита'] → ['Т12']."""

def test_router_picks_up_rename_without_restart():
    """Critical: rename Т12 mid-test, verify subsequent resolution
    uses new name. LATE BINDING verification."""

def test_router_drops_unresolvable_with_warning():
    """target_channels=['нечто странное'] → None, warning logged."""

def test_router_partial_match_fuzzy():
    """target_channels=['плита'] → ['Т12'] (substring of 'Азотная плита')."""

def test_router_exact_match_wins_over_substring():
    """If both 'Плита' and 'Азотная плита' exist, exact match returns first."""

def test_router_handles_empty_target_channels():
def test_router_passes_through_when_no_channel_manager():

def test_channel_manager_find_by_name_exact():
def test_channel_manager_find_by_name_substring():
def test_channel_manager_find_by_name_case_insensitive():
def test_channel_manager_find_by_name_returns_none_no_match():
```

### 2.3 Phase C — Smoke test (manual, with rename mid-session)

Critical scenario: verify LATE BINDING works in real lab workflow.

After engine restart с обновлённым кодом:

1. **Direct query, default name:**
   ```
   Vladimir: Какая Т7?
   Expected: "Т7 Детектор сейчас X.XX K..."
   ```

2. **Display name query, current channels.yaml state:**
   ```
   Vladimir: Что на азотной плите?
   Expected: "На азотной плите (Т12) сейчас X.XX K..."
   ```

3. **Mid-session rename — CRITICAL TEST:**
   - Open GUI ChannelEditor while engine running
   - Rename Т7 from "Детектор" to "Болометр свежий"
   - Save
   - DO NOT restart engine
   - Send query:
     ```
     Vladimir: Какой болометр?
     Expected: "Т7 Болометр свежий сейчас X.XX K..."
     
     Vladimir: А детектор?
     Expected: graceful — "не нашёл канал «детектор» в текущей конфигурации"
     ```
   - Verify Гемма uses new name immediately

4. **Direct ID always works regardless of rename:**
   ```
   Vladimir: какая Т7?
   Expected: "Т7 Болометр свежий сейчас X.XX K..." (uses current name in response)
   ```

5. **Backward compat slash command:**
   ```
   /temps
   Expected: lists 24 channels с current display names
   ```

If LATE BINDING не работает — surface specific case с audit JSON,
verify what prompt classifier received vs what ChannelManager
returns.

### 2.4 Phase D — Codex audit + v0.47.3 release

Single-verifier (S scope per ORCHESTRATION v1.4 §16.3).

Focus on:
- LATE BINDING correctness — classifier reads fresh state
- No regression в existing F30 tests
- Race condition safety — concurrent classify() calls don't corrupt
  each other's prompt

CHANGELOG:
```markdown
## [0.47.3] — 2026-05-XX — HF: Display name resolution в Intent Classifier (LATE BINDING)

### Added
- IntentClassifier accepts ChannelManager reference. Builds channel
  display name table в system prompt at EVERY classify() call (late
  binding) — picks up GUI ChannelEditor renames mid-campaign without
  engine restart.
- `ChannelManager.find_by_name()` — case-insensitive exact + substring
  display name → channel ID resolution
- QueryRouter fallback: validates target_channels against current
  ChannelManager state, fuzzy match для partial display names.

### Fixed
- "Что на азотной плите?" — Гемма resolves operator vocabulary
  (renamed via ChannelEditor) к channel IDs. Previously dropped
  through к full snapshot, LLM picked random channels.
- Sensor renaming в GUI ChannelEditor immediately reflects в Гемма
  responses на NEXT query — NO engine restart needed. Critical for
  real lab workflow where operators rename sensors during preparation
  phase before campaign launch.

### Reference
- ARCHITECT REQUEST: realworld testing 2026-05-01 13:06
- Architect-Vladimir clarification on rename-mid-campaign workflow:
  per-query rebuild instead of construction-time freeze.
- HF spec: CC_PROMPT_HF_V0.47.3_DISPLAY_NAME_RESOLUTION.md
```

---

## 3. Acceptance criteria

1. ✅ "Что на азотной плите?" returns Т12 reading correctly
2. ✅ "Сколько на 2 ступени?" returns Т11 correctly
3. ✅ Direct ID queries ("Какая Т7?") still work
4. ✅ **Display name renamed via ChannelEditor mid-session → reflected
   в Гемма responses on NEXT query, NO restart needed** (LATE BINDING)
5. ✅ Unresolvable channel name → graceful (drops + logs warning,
   not crash)
6. ✅ Existing F30 tests still pass (backward compat)
7. ✅ Per-query overhead from prompt rebuild <50ms
8. ✅ ≥12 new tests covering classifier (including rename mid-session),
   router, ChannelManager.find_by_name

---

## 4. Out of scope (defer)

- **Aliases system** (1-я ступень / холодная точка / болометр):
  display names cover most cases per current usage. Re-evaluate
  after smoke testing if operator complains.
- **Group-level queries** ("что на компрессоре?"): different
  feature category, defer to v0.48+ if requested.
- **ChannelManager modification observer notification**: per-query
  rebuild handles renames correctly without explicit notification.
  Future enhancement (cache invalidation, pub/sub) only if perf
  becomes issue.

---

## 5. Begin

1. Phase A — classifier late-binding (recon IntentClassifier code first)
2. Phase B — router fallback (recon Router code и ChannelManager API)
3. Phase C — smoke (mid-session rename test critical)
4. Phase D — Codex audit + release v0.47.3

GO.
