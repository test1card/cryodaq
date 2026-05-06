# CC prompt — Obsidian Vault update post v0.47.4 ship

> Update Vault notes to reflect 2026-05-01 session work: three HF
> releases (v0.47.2 final fixup, v0.47.3, v0.47.4), lessons learned,
> roadmap shift (F-X/F-Y identified from real-world testing).
>
> Architect handed off this thread to fresh architect. This Vault
> sync is the architect-thread → Vault persistence step.

---

## 0. Vault location и scope

Vault path: `~/Vault/CryoDAQ/` (synced via Syncthing к macOS M5,
Ubuntu lab PC).

CC has full filesystem access — read existing notes first to
understand current schema/conventions before writing. Do NOT
overwrite if existing note has richer history; APPEND new section
or edit specific outdated sections.

If Obsidian-MCP is registered и available — prefer it over raw
filesystem access (handles wikilinks, frontmatter, tags
correctly). If not available — raw filesystem write OK.

---

## 1. Pre-flight

```bash
# Check vault structure
ls -la ~/Vault/CryoDAQ/
find ~/Vault/CryoDAQ -type f -name "*.md" | head -30
```

Identify:
- Where ORCHESTRATION lives (likely `Orchestration/` or `_meta/` or root)
- Where ROADMAP lives
- Where MODEL-PROFILES would live (may not exist yet — create if missing)
- Where session journal или daily notes live
- Naming conventions (kebab-case, snake_case, Title Case)
- Frontmatter schema (tags, dates, status fields)

Surface findings to architect через короткий summary if structure
unclear. Otherwise proceed.

---

## 2. Updates to apply

### 2.1 ORCHESTRATION v1.4 → v1.5

Find ORCHESTRATION note. Either:
- Create new section "v1.5 — 2026-05-01 lessons" appending к existing
- Or create separate `ORCHESTRATION-v1.5.md` if convention is
  versioned files

Add following lessons (each as subsection):

#### 2.1.1 SSL invariant protection

CC регрессировал `verify_ssl` config knob TWICE during 2026-05-01
session. Architect manually restored both times across 3 files
(telegram.py, telegram_commands.py, engine.py). Manual cost ~40
min total architect time per regression event.

**Mitigation rule:** Every CC_PROMPT touching `notifications/` or
engine wiring section MUST include §1 "DO NOT REGRESS BASELINE"
block с regression check commands:

```bash
grep -c "verify_ssl" \
  src/cryodaq/notifications/telegram.py \
  src/cryodaq/notifications/telegram_commands.py \
  src/cryodaq/engine.py
# Must report ≥14
```

If <14 — STOP, manual restore required, surface к architect before
proceeding.

Reference specs implementing this pattern correctly:
- `CC_PROMPT_HF_V0.47.2_FIXUP_REGRESSION_BLOCK.md` §1
- `CC_PROMPT_HF_V0.47.3_DISPLAY_NAME_RESOLUTION.md` §1
- `CC_PROMPT_HF_V0.47.4_CHANNEL_ID_NORMALIZATION.md` §1

#### 2.1.2 LATE BINDING vs early binding

Real lab workflow: engine starts → preparation → operator names
sensors via GUI ChannelEditor mid-campaign → vacuum → cooldown →
measurement → operator queries Гемма.

Engine restart destroys state (BrokerSnapshot cache, alarm history,
periodic counters, experiment context, predictor history). NOT
acceptable mid-campaign.

**Architecture rule:** any component using ChannelManager-derived
data MUST read fresh state per call (late binding), NOT cache at
construction.

Working examples after v0.47.3 + v0.47.4:
- `IntentClassifier.classify()` — rebuilds prompt с current
  ChannelManager hints per call
- `QueryRouter._resolve_target_channels()` — fresh ChannelManager
  per query
- `BrokerSnapshot.latest_with_labels()` — display_name lookup per
  call (after v0.47.4 normalize-on-ingest fix)

If new feature design touches ChannelManager state — verify LATE
BINDING before approving spec.

#### 2.1.3 git stash discipline

CC's workflow does `git stash` → patches → `git stash pop`.
Pop can leave merge conflict markers if patches conflict с
stashed code. Markers commit silently — pytest doesn't catch
syntax errors when engine.py не imported by tests directly.

**Mandatory CC_PROMPT pre-flight (in addition к §2.1.1):**

```bash
grep -rn "<<<<<<< Updated\|>>>>>>> Stashed\|======= " \
  src/cryodaq/ config/ tests/ 2>/dev/null | wc -l
# Must be 0

python -c "import cryodaq.engine"
# Must exit 0
```

Apply both checks before any commit.

#### 2.1.4 Test count baseline drift

Reported baselines this session: 228 → 312 → 2300. The 312→2300
jump is suspicious — likely import failures previously masked
tests. "≥X tests passing" is unreliable acceptance criterion alone.

**Recommendation:** every release notes entry includes:

```bash
pytest --collect-only -q 2>&1 | tail -5
# Records: N items collected, M skipped
```

True baseline = items collected. Drop between releases → import
regression, surface to architect.

#### 2.1.5 Two-source-of-truth normalization boundary

v0.47.4 root cause: `instruments.yaml` driver labels embedded
display names ("Т7 Детектор"). `channels.yaml` ChannelManager
keyed short ("Т7"). Driver emission used long form, ChannelManager
renames lived в short keys, never met.

Option B (BrokerSnapshot normalizes на ingest, single-file fix)
chosen over Option A (rewrite + DB migration of 141k rows + 5+ files
including interlocks regex break).

**Lesson:** when configs overlap, look for **normalizing boundary**
first before structural rewrite. Existing `ChannelStateTracker`
(alarm_v2 path) uses same split-on-space normalization — pattern
already proven, applied в second place.

#### 2.1.6 Architect manual edits costly — protocol

**Spec → CC trigger → wait → ratify.** Manual только if CC blocking
itself in regression loop с no path forward (e.g., merge markers
breaking compile, where waiting another CC cycle would just
re-encounter same conflict).

When manual intervention happens — IMMEDIATELY add the regressed
behavior to "DO NOT REGRESS" section of next CC_PROMPT.

This session manual intervention budget = ~1 hour total (3
incidents). Target for future sessions = 0 minutes (CC handles all).

#### 2.1.7 TRUNCATED_DIFF_ARTIFACTS pattern

F29 swarm audit calibration earlier in session: rtk hook compressed
git diff 125KB → 20KB silently → mass false positives from auditors
who saw partial code.

**Workaround:** `rtk proxy git diff` instead of direct rtk diff
in CC audit prompts.

Document in CC orchestration playbook as known issue + workaround.

---

### 2.2 MODEL-PROFILES.md initial cut

If `MODEL-PROFILES.md` does not exist yet — create. Schema suggestion
(adapt to vault conventions):

```markdown
# Model profiles — CryoDAQ multi-model orchestration

> Per-model strengths, failure modes, и operational notes.
> Updated as calibration log accumulates records.

Last updated: 2026-05-01 (85+ calibration records)

## Codex (gpt-5.5)

**Verdict:** Primary verifier. Most reliable.

**Profile:**
- Hallucination rate: 0% across 85+ records
- Strengths: code review, regression detection, syntax verification
- Failure modes: none observed yet

**Usage:** Primary verifier для multi-verifier audits. If only one
verifier called — Codex.

## GLM-5.1 (Chutes TEE)

**Verdict:** Secondary verifier. Reliable when configured correctly.

**Profile:**
- Strengths: code analysis, structured review
- Failure mode: needs `max_tokens ≥ 8192` для large diffs.
  Default 4096 truncates output mid-review → false PASS verdict
  (incomplete analysis).
- Identity leakage: occasionally self-identifies as Claude. CCR logs
  are only reliable verification source.

**Usage:** Secondary verifier alongside Codex. Set
`max_tokens: 8192` minimum. Verify через CCR logs that GLM actually
ran (не Claude fallback).

## Kimi-K2.6

**Verdict:** Slow but capable.

**Profile:**
- Failed first 4 attempts (timeout/error)
- 5th attempt success: 35KB diff in 210s
- High variance, high latency

**Usage:** Backup verifier. Only когда Codex + GLM unavailable.
Budget 5+ min per audit call.

## Qwen3-Coder-Next

**Verdict:** AVOID for now — negative pattern observed.

**Profile:**
- Failure mode: Finding 5 looped 24× с path hallucination
- Output keeps repeating same finding с invented file paths

**Usage:** Skip until pattern resolved upstream.

## Gemini CLI (audit)

**Verdict:** Reliable wide-scope auditor.

**Profile:**
- Found Gemini MEDIUM finding в v0.47.4 audit (FORMAT_GREETING_USER
  missing brand_name placeholder) — Codex passed it. Different
  auditors catch different things.
- Strengths: cross-cutting concerns, prompt template consistency

**Usage:** Foundational scope audits, particularly когда prompt
templates changed.
```

Ground all numbers from session calibration log if accessible. If
not — populate with this baseline cut и mark "preliminary, refine
as records accumulate".

---

### 2.3 ROADMAP update

Find existing ROADMAP note. Update §F-tasks priority order based
on real-world testing 2026-05-01 16:30:

**Old order:**
1. F-A Anomaly detection widget (v0.48.0)
2. F-B τ-scale formulation (v0.49.0)
3. F-C Slider integration (v0.50.0)

**New order (post-2026-05-01 reframing):**

1. **F-X Channel taxonomy + phase-aware alarm bands** (v0.48.0)
   - Add `thermal_zone` field к channels.yaml schema
   - Zones: cold_4k / cold_77k / intermediate / warm_flange /
     warm_reference / disconnected_reserve
   - Phase-aware alarm_band per zone
   - Reduces false-positive alarm batches на warm channels (Т16
     Фланец, Т8 Калибровка sustained 300K — physically expected)
   - Effort: M (~400 LOC + tests + channels.yaml schema migration)

2. **F-Y Diagnostic mode rework для AnomalyResponseAgent** (v0.49.0)
   - Reframe system prompt: suggestion-mode → diagnostic-mode
   - Геммa делает выводы, не предлагает оператору проверки
   - AnalyticsAdapter computes Z-score, correlation, batch
     clustering, channel→instrument mapping upfront
   - Surface confidence ("Z=745σ batch synchronous → likely
     LakeShore disconnect") not "проверьте контакты" generic
   - Effort: M (~350 LOC analytics adapter + system prompt + audit
     fields)

3. **F-A Anomaly detection widget** (v0.50.0) — DEMOTED
   - Was first priority, moved after F-X/F-Y based on Vladimir's
     feedback about alarm noise + bot suggestion-mode being more
     pressing
   - Spec ratified for cold-start (existing 16 cooldown curves don't
     get new metadata)

4. **F-B τ-scale formulation** (v0.51.0)
   - Phase 1: validate shape-invariance assumption first
   - Q1 ratified: τ-scale not categorical buckets

5. **F-C Slider integration** (v0.52.0)

6. **F-D Physics prior** — DEFERRED post-F-C decision

**Independent tracks (no ordering dep):**
- F27 chamber photos
- F31 sinks foundation (vault writer + webhook, was F30)
- F32 RAG indexer (was F31)
- F33 archive query (was F32)
- F34 GUI chat overlay — DEFERRED

**Reasoning for F-X/F-Y promotion:**

Real-world testing 2026-05-01 16:30 showed two issues:
1. False-positive alarms on warm-by-design channels (Т16 Фланец,
   Т8 Калибровка) generate noise — alarms_v3.yaml uniform thresholds
   ignore physical context. 300K+ normal на фланцах, горячая часть
   криопальца, насос, reference blocks.
2. AnomalyResponseAgent в suggestion-mode ("предлагаю проверить
   контакты") вместо diagnostic-mode. All data needed для real
   diagnosis (Z-score, correlation, batch clustering) already в
   context, prompt forces suggestion list output.

F-X reduces alarm noise (real signal hides currently). F-Y makes
agent useful instead of pseudo-medical. Both must ship before F-A
anomaly detection widget — иначе widget shows same noise + suggests
useless suggestions.

---

### 2.4 Session journal entry

Find session journal location (likely daily notes или
`Sessions/YYYY-MM-DD.md`). Create entry для 2026-05-01 if missing.

Content (adapt format к vault convention):

```markdown
# 2026-05-01 — Live Query Agent UX hotfix sprint

## Tags
#cryodaq #hotfix #v0.47.x #live-query-agent #channel-manager

## Summary

Three iterative HF releases closing major UX gaps в Live Query Agent
(F30 Гемма):
- v0.47.2 final fix-up (commit superseded original v0.47.2 broken)
- v0.47.3 display name resolution с LATE BINDING
- v0.47.4 channel ID normalization (Option B — BrokerSnapshot ingest)

Plus session-end identification of F-X (channel taxonomy) и F-Y
(diagnostic mode) as new priorities.

## Releases shipped

### v0.47.2 final fix-up
- Track A: query agent wiring (was returning slash-only fallback)
- Track B: defensive empty-snapshot ("поток только запускается")
- Track C: complete russification (захолаживание/отогрев/etc, no
  English leaks)
- Track D: chart dispatch fix
- Track E: composite anti-pattern в prompt (no "Т7 Детектор,..."
  start)
- Track F-G: Latin/Cyrillic confusable + classifier prompt cleanup
- Track H: anti-hallucination prompt + adapter null-safety (no more
  "00:00 UTC" invented timestamps)

### v0.47.3 display name resolution
- IntentClassifier accepts ChannelManager reference
- Late binding: rebuild channel hint section на каждый classify()
  call (operator renames mid-campaign without restart)
- ChannelManager.find_by_name() — exact + substring + Latin/Cyrillic
  fallback
- QueryRouter validates target_channels against current ChannelManager

### v0.47.4 channel ID normalization (commit 3192f1c, tag f199505)
- BrokerSnapshot._normalize_channel_id() splits "Т7 Детектор" → "Т7"
  на ingest (matches ChannelStateTracker pattern)
- Fixes current_value queries (snapshot.latest("Т7") now returns
  reading вместо None)
- Bonus: ChannelEditor renames now propagate end-to-end (LATE BINDING
  unblocked through driver→broker→display)
- ExperimentAdapter._resolve_display_name(): title → name → date →
  uuid[:8] (no more raw "cc35331d8c89" в bot output)
- FORMAT_GREETING_USER + GREETING dispatch: no stray "Пока не вижу"
  appended после greeting

Multi-verifier PASS: Codex + Gemini. Tests: 19 new в
test_channel_id_normalization.py.

## Architect manual interventions (cost ~1 hour)

3 incidents this session:
1. engine.py merge conflict markers в _handle_gui_command
   leak_rate_*
2. config/instruments.yaml chamber section markers
3. SSL config knob restoration в 3 files (twice — CC kept regressing)

All addressed via DO NOT REGRESS sections в forward CC_PROMPTs.

## Lessons (added to ORCHESTRATION v1.5)

1. SSL invariant protection
2. LATE BINDING vs early binding pattern
3. git stash discipline (mandatory pre-flight checks)
4. Test count baseline drift (collect-only count more reliable)
5. Two-source-of-truth normalization boundary
6. Architect manual edits costly — protocol
7. TRUNCATED_DIFF_ARTIFACTS pattern + rtk proxy workaround

## Forward priorities

F-X (channel taxonomy + alarm bands) → F-Y (diagnostic mode rework)
→ F-A (anomaly widget) — F-A demoted based on real-world feedback
that alarm noise + suggestion-mode are more pressing.

## Smoke testing pending

Phase 7 manual smoke v0.47.4 от phone, 7 scenarios per
CC_PROMPT_HF_V0.47.4_CHANNEL_ID_NORMALIZATION.md §7. Critical:
scenario 6 mid-session ChannelEditor rename без restart.

## Architect handoff

Thread context exhausted — handed off to fresh architect. Handoff
document at `artifacts/handoffs/2026-05-01-v0.47.4-architect-handoff.md`
(CryoDAQ repo) and equivalent in vault.

```

---

### 2.5 Architect handoff document (vault copy)

Find `Handoffs/` или equivalent location в vault. If exists —
write handoff doc там as `2026-05-01-v0.47.4-architect-handoff.md`.

Content: copy from architect chat in this thread (Vladimir has it),
or compose minimal version covering:
- Last shipped: v0.47.4 commit 3192f1c tag f199505
- Awaiting: Phase 7 smoke from Vladimir phone
- Master branch state
- Vladimir directives (cheap hands / expensive cognition)
- Forward roadmap pointing к ROADMAP note (don't duplicate)
- Lessons pointing к ORCHESTRATION note (don't duplicate)
- Project context (repo path, stack, instruments, hard rules)

Cross-link к ORCHESTRATION-v1.5 и ROADMAP via wikilinks
(`[[ORCHESTRATION-v1.5]]` / `[[ROADMAP]]` / etc per vault convention).

---

### 2.6 F-X spec stub (Vault — для new architect)

In vault `Specs/` или equivalent location, create stub:
`F-X-channel-taxonomy-and-alarm-bands.md`

```markdown
# F-X — Channel taxonomy + phase-aware alarm bands

Status: STUB — awaits new architect detailed spec
Priority: Top after Phase 7 smoke confirmation
Target release: v0.48.0
Ratified: 2026-05-01 by Vladimir + outgoing architect

## Problem

`alarms_v3.yaml` uses uniform или per-channel thresholds without
physical context. Real lab observations:
- Т16 Фланец sustained 300K → triggers warning (but flange is
  normally room temp by design)
- Т8 Калибровка sustained 300K → triggers warning (reference block
  на room temp by design)
- Diagnostic alarm batch включает 6+ channels at 300K simultaneously
  → likely some are real disconnect, some are warm-by-design

Operator (Vladimir): "300K+ может быть на фланцах спокойно, на
горячей части криопальца, на насосе если туда установлен"

## Solution sketch

Add `thermal_zone` field к channels.yaml schema:

```yaml
Т7:
  name: "Детектор"
  thermal_zone: cold_4k
  alarm_band:
    cold_phase: [3.5, 5.0]      # measurement
    cooldown: [4.0, 305.0]      # transient OK
    warm: [285.0, 305.0]        # после warmup

Т8:
  name: "Калибровка"
  thermal_zone: warm_reference
  alarm_band:
    all_phases: [285.0, 310.0]

Т16:
  name: "Фланец"
  thermal_zone: warm_flange
  alarm_band:
    all_phases: [285.0, 320.0]
```

Zones: `cold_4k`, `cold_77k`, `intermediate`, `warm_flange`,
`warm_reference`, `disconnected_reserve`

Phase-aware (cooldown phase у cold_4k channel допускает transient
до 300K, measurement phase narrow [3.5, 5.0]).

## Effort

M (~400 LOC + tests + channels.yaml schema migration)

## Blockers

- Phase 7 smoke v0.47.4 must pass first
- Migration of existing channels.yaml configs (24 channels)
- AlarmEngine update to read phase-aware bands
- Validation tests на real historical data (don't break alarm
  triggering when band changes)

## Acceptance

- All 24 channels classified into thermal_zones
- Phase-aware bands applied
- Existing real alarms (cold channel disconnect at 300K) still fire
- Warm-by-design channels stop generating false positives
- ≥20 new tests covering zone classification + phase-aware logic
```

---

### 2.7 F-Y spec stub (Vault — для new architect)

In vault `Specs/`, create:
`F-Y-diagnostic-mode-rework.md`

```markdown
# F-Y — Diagnostic mode rework для AnomalyResponseAgent

Status: STUB — awaits new architect detailed spec
Priority: After F-X
Target release: v0.49.0
Ratified: 2026-05-01 by Vladimir + outgoing architect

## Problem

AnomalyResponseAgent (F28 Гемма) currently в suggestion-mode.
System prompt: "Твоя задача — предложить конкретные диагностические
действия".

Output looks pseudo-medical:
> "Предлагаю следующие диагностические действия для оператора:
>  1. Проанализировать текущее значение Т4 Радиатор 2 (300.95) и
>     сравнить с историческими данными...
>  2. Проверить корреляцию между изменением значения и трендом
>     давления..."

Vladimir feedback: "почему это не делается автоматически и не
приносится готовым?"

All data needed для actual diagnosis already в context:
- Current value, historical 60min window
- Pressure trend
- Concurrent alarm batch (10 channels simultaneously)
- Channel→instrument mapping (через instruments.yaml)

LLM could compute Z-score, correlation, batch clustering, instrument
attribution. But prompt forces suggestion list.

## Solution sketch

1. **AnalyticsAdapter** computes upfront before format prompt:
   - Z-score against historical window (300.95 vs σ≈0.3 → 745σ)
   - Batch correlation (concurrent alarms на same instrument? → r>0.99)
   - Channel→instrument mapping (which LakeShore? which Keithley?)

2. **Reframe system prompt:**
   ```
   Ты — Гемма, диагност в криогенной лаборатории.
   - Делай вывод. Один-два concrete hypothesis с обоснованием
     от данных.
   - Не предлагай оператору проверки — он знает ЧТО проверять,
     как только знает ГДЕ искать.
   - Surface confidence: "вероятно disconnect (Z=745σ, batch
     synchronous)" не "это может быть disconnect".
   - Если данных недостаточно — скажи "недостаточно для диагноза"
     явно.
   ```

3. **Audit JSON additions:**
   - `analytics.z_score`
   - `analytics.batch_correlation`
   - `analytics.instrument_attribution`
   - `analytics.disconnect_signature_match: bool`

## Effort

M (~350 LOC analytics adapter + system prompt + audit fields)

## Blockers

- F-X должен ship first (channel taxonomy informs which channels
  expected к be warm, scoping diagnostic hypotheses)
- AnalyticsAdapter design (parallel-fetch like CompositeAdapter? or
  precomputed at alarm fire?)
- Migration of existing AnomalyResponseAgent system prompts

## Acceptance

- Геммa output starts с conclusion ("Вероятно отключение
  LakeShore_3..."), not suggestion list
- Z-score, correlation, instrument attribution в response when data
  available
- "Недостаточно данных" path работает explicitly
- Existing F28 tests still pass + ≥15 new tests
```

---

## 3. Verification

After all writes:

```bash
# Verify all updates landed
ls -la ~/Vault/CryoDAQ/Sessions/2026-05-01* 2>/dev/null
ls -la ~/Vault/CryoDAQ/Specs/F-X* ~/Vault/CryoDAQ/Specs/F-Y* 2>/dev/null
ls -la ~/Vault/CryoDAQ/MODEL-PROFILES.md 2>/dev/null
grep -l "v1.5\|2026-05-01" ~/Vault/CryoDAQ/**/*.md 2>/dev/null | head -5
```

Surface к Vladimir:
- Files created/updated (full paths)
- Wikilinks added (which notes reference which)
- Any vault structure decisions made (где placed F-X/F-Y stubs если
  Specs/ folder absent)

If Obsidian app running на Vladimir's machine — он refresh'нёт
graph view sам.

---

## 4. Hard stops

- Vault structure unclear → STOP, surface к architect для guidance
- Existing notes have content that would be overwritten → STOP, ask
  if append vs replace
- Calibration log not accessible (для MODEL-PROFILES grounding) →
  use baseline cut от this prompt, mark "preliminary"

---

## 5. Begin

1. Read vault structure (§1)
2. Apply 6 updates (§2.1-2.7)
3. Verify (§3)
4. Surface summary к Vladimir

GO.
