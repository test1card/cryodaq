# Parallel work session 2026-05-01 — full orchestration

> Architect (web Claude Opus 4.7) is busy in another conversation
> discussing strategic feature decisions for award presentation.
> CC executes a coherent batch of pending work in parallel.
>
> Full ORCHESTRATION v1.3 discipline. Multi-cycle audit per feature.
> NO auto-merge. Architect reviews everything in morning sync.

---

## 0. Operating posture

- Architect available asynchronously — surface ARCHITECT DECISION
  NEEDED markers in handoffs, do not block.
- ORCHESTRATION v1.3 §13 autonomy band applies.
- Per-feature dual-verifier audit (Codex + Gemini if quota).
- Sonnet does work, Codex/Gemini audit, Sonnet fix-up loop.
- Calibration v1.0 is **PILOT** (n=1), not validated routing.
  Use traditional dual-verifier per §14.2; route by §15 dispatch
  realities, not pilot routing matrix.

---

## 1. Work batch (sequential)

Three independent tracks. Execute in order, each fully complete
before moving to next.

| Track | Effort | Branch | Notes |
|---|---|---|---|
| A — README RU translation | S (~1h) | direct master commit | docs only |
| B — Docs audit Phase 2 execution | M (~2-3h) | direct master commits in groups | per existing spec |
| C — F26+F17+F13 merge + v0.44.0 | S (~1h) | merges + tag | release engineering |

Architect-tentative order: C → A → B.

Reasoning:
- C unblocks v0.44.0 release (F26+F17+F13 already audited PASS,
  just need merge + tag)
- A is README cleanup (already in English from yesterday's CC
  rewrite; needs RU restoration)
- B is largest scope (docs audit Phase 2 per existing spec)

---

## 2. Track C — F26+F17+F13 merge + v0.44.0

### 2.1 Pre-merge recon

```bash
cd ~/Projects/cryodaq
git status
git log -1 --format='%h %P %s' HEAD     # rtk-aware
git fetch origin
git tag -l "v0.4*" --sort=v:refname
git branch -av | grep "feat/overnight-f"
```

Expected master: `c44c575` (post-v0.43.0).
Expected branches:
- `feat/overnight-f26-sqlite-whitelist` at `649fb1a`
- `feat/overnight-f17-cold-rotation` at `0435121`
- `feat/overnight-f13-leak-rate` at `02afa77`

If master has drifted past `c44c575` (other commits): document, 
proceed against current HEAD.

### 2.2 Merge order: F26 → F17 → F13

Independent branches per overnight summary. Order is alphabetical
by F-number for predictability.

#### Merge F26

```bash
git checkout master
git rev-list --left-right --count master...feat/overnight-f26-sqlite-whitelist

git merge --no-ff feat/overnight-f26-sqlite-whitelist -m "merge: F26 SQLite WAL backport whitelist (overnight 2026-05-01)

Architect-approved per overnight summary. Codex audit PASS after
4 negative boundary tests added in amend cycle.

SQLITE_BACKPORT_SAFE = frozenset([(3,44,6),(3,50,7)]) added inside
affected-range gate before env var bypass. Adjacent versions
(3,44,5/7), (3,50,6/8), (3,51,2) still raise.

Source: SQLite official advisory (sqlite.org/wal.html) — fix
backported to two specific patch versions. F25 (v0.43.0) was
conservatively false-positive blocking these.

Tests: 6 new (2 positive whitelist, 4 negative boundary).
Full suite green.

Ref: artifacts/handoffs/2026-05-01-f26-handoff.md
Ref: ROADMAP.md F26
Batch: phase-D / overnight-2026-05-01 / F26 merge
Risk: low — narrow whitelist."

git push origin master
git log -1 --format='%h %P %s' HEAD
```

#### Merge F17

```bash
git rev-list --left-right --count master...feat/overnight-f17-cold-rotation

git merge --no-ff feat/overnight-f17-cold-rotation -m "merge: F17 SQLite→Parquet cold rotation (overnight 2026-05-01)

Architect-approved per overnight summary. Codex audit PASS after
3 cycles addressing CRITICAL findings:
- Index-overwrite on corrupt JSON → raise + abort rotation
- Naive local-time epoch → UTC-normalized timestamps
- Concurrent rotation race → asyncio.Lock guard

ColdRotationService:
- Glob data_????-??-??.db, skip today + already-rotated
- asyncio.to_thread() per file for off-loop I/O
- Read all rows → write Parquet (Zstd, chunked 100k) → verify
  row count → update index.json → delete SQLite+WAL+SHM
- Daemon mode (86400s sleep)

ArchiveReader:
- query(channels, from_ts, to_ts) day-by-day UTC
- Index lookup → Parquet OR SQLite fallback

Files:
- src/cryodaq/storage/cold_rotation.py (446 LOC)
- src/cryodaq/storage/archive_reader.py (175 LOC)
- config/housekeeping.yaml (+10 LOC)
- tests/storage/test_cold_rotation.py + test_archive_reader.py (16 tests)

LOW residual: ArchiveReader not yet wired into engine replay —
read layer exists, integration deferred. Documented in handoff.

Tests: 16 new. Full suite green.

Ref: artifacts/handoffs/2026-05-01-f17-handoff.md
Ref: ROADMAP.md F17
Batch: phase-D / overnight-2026-05-01 / F17 merge
Risk: medium — storage subsystem additive change, conservative
verification before SQLite delete."

git push origin master
git log -1 --format='%h %P %s' HEAD
```

#### Merge F13

```bash
git rev-list --left-right --count master...feat/overnight-f13-leak-rate

git merge --no-ff feat/overnight-f13-leak-rate -m "merge: F13 vacuum leak rate estimator (overnight 2026-05-01)

Architect-approved per overnight summary. Codex audit PASS after
2 cycles addressing CRITICAL findings:
- Engine never fed samples → _leak_rate_feed() broker task added
- No window trimming → sliding-window FIFO in add_sample()
- OLS R²=1.0 on degenerate input → changed to R²=0.0
- Double-finalize possible → _samples cleared in finalize()
- duration_s validation for NaN/inf/zero/negative

LeakRateEstimator:
- start_measurement(t0, p0_mbar, *, window_s) / add_sample / finalize / cancel
- Sliding window with FIFO trim
- numpy-free OLS, R²=0.0 for degenerate input
- History persisted atomically to data/leak_rate_history.json

Engine wiring:
- _leak_rate_feed() broker task subscribes, filters unit==mbar
- leak_rate_start handler: validates duration_s, checks enabled flag
- leak_rate_stop handler: returns asdict(LeakRateMeasurement)

Config (config/instruments.yaml):
- chamber.volume_l (operator must set; defaults to 0.0)
- chamber.leak_rate.enabled / .default_sample_window_s / .warning_threshold_mbar_l_per_s

Files:
- src/cryodaq/analytics/leak_rate.py (245 LOC)
- src/cryodaq/engine.py (+55 LOC)
- config/instruments.yaml (+7 LOC)
- 2 test files (19 tests)

OPERATOR ACTION: chamber.volume_l must be set in config/
instruments.local.yaml before first leak rate measurement;
ValueError on finalize if volume_l == 0.0.

Tests: 19 new. Full suite green.

Ref: artifacts/handoffs/2026-05-01-f13-handoff.md
Ref: ROADMAP.md F13
Batch: phase-D / overnight-2026-05-01 / F13 merge
Risk: medium — adds engine task + ZMQ command handlers."

git push origin master
git log -1 --format='%h %P %s' HEAD
```

### 2.3 Tag v0.44.0

```bash
sed -i.bak 's/^version = "0\.43\.0"/version = "0.44.0"/' pyproject.toml
rm pyproject.toml.bak
grep '^version' pyproject.toml
```

### 2.4 CHANGELOG entry

Update CHANGELOG.md. Move [Unreleased] content into [0.44.0]:

```markdown
## [Unreleased]

## [0.44.0] — 2026-05-01 — Storage maturity + leak rate

### Highlights
- F17: SQLite → Parquet cold rotation with day-by-day archive
  layout. ArchiveReader replay across both sources.
- F13: Vacuum leak rate estimator (LeakRateEstimator) with
  sliding-window OLS, ZMQ commands, atomic history persistence.
- F26: SQLite WAL gate backport whitelist (3.44.6, 3.50.7) per
  official SQLite advisory.

### Storage (F17, F26)
- F17 ColdRotationService: rotates SQLite files older than 30 days
  to Parquet/Zstd; verifies row count before deletion; daemon mode.
- F17 ArchiveReader: unified query across SQLite (recent) + Parquet
  (archive); UTC-normalized day iteration.
- F26 SQLITE_BACKPORT_SAFE whitelist: (3.44.6, 3.50.7) bypass the
  startup gate without env var; adjacent versions still raise.

### Vacuum analytics (F13)
- LeakRateEstimator: sliding-window OLS, numpy-free regression,
  R²=0.0 on degenerate input, atomic history persistence.
- Engine ZMQ commands: leak_rate_start, leak_rate_stop.
- Engine broker task: _leak_rate_feed() subscribes pressure samples.
- Config: chamber.volume_l (operator must set), chamber.leak_rate.*

### Operator action required
- chamber.volume_l must be set in config/instruments.local.yaml
  before first leak rate measurement.

### Tests
- 49 new tests across F26+F17+F13.
- Full suite ~2040+ passing.

### Closing commit
<F13 merge SHA from §2.2>
```

### 2.5 ROADMAP F-row updates

Update ROADMAP.md:
- F26 → ✅ DONE (shipped v0.44.0)
- F17 → ✅ DONE (shipped v0.44.0)
- F13 → ✅ DONE (shipped v0.44.0)

Update F-row index at top.

Add new entry **F28 — ArchiveReader engine replay integration**:

```markdown
### F28 — ArchiveReader engine replay integration

**Status:** ⬜ NOT STARTED.
**Effort:** S (~50 LOC).
**Source:** F17 residual risk 2026-05-01.

ArchiveReader implementation exists post-F17 but is NOT wired
into engine replay path. Live engine queries against archived
data (>30 days old) currently fail. Integration: replay.py
should select between SQLite and ArchiveReader per query
time range. Tests: time-range queries crossing rotation boundary.
```

Add **F27 — Chamber preparation photos via Telegram** entry if
not already in ROADMAP from earlier session:

```markdown
### F27 — Chamber preparation photos via Telegram

**Status:** 🟡 SPEC READY.
**Effort:** L (~700-900 LOC).
**Source:** Architect-Vladimir conversation 2026-05-01.

Operator photographs cryostat chamber layout (preparation phase
only) with multi-angle series, sends to Telegram bot. Photos
auto-attach to active experiment, GUI annotation in Archive
overlay, reports embed all photos. TREVOGA alarm if 0 photos
on preparation-leave (CRITICAL) or 1 photo (WARNING). 4-cycle
implementation planned. Predictor integration deferred.

Spec: CC_PROMPT_F27_CHAMBER_PHOTOS.md
```

### 2.6 Final commit + tag + push

```bash
git add CHANGELOG.md ROADMAP.md pyproject.toml

git commit -m "release: v0.44.0 — Storage maturity (F17, F26) + leak rate (F13)

3 features shipped from 2026-05-01 overnight Sonnet sprint:
- F17 cold rotation SQLite → Parquet (~620 LOC + 16 tests)
- F26 SQLite WAL backport whitelist (~14 LOC + 6 tests)
- F13 vacuum leak rate estimator (~300 LOC + 19 tests)

49 new tests. Full suite ~2040+ passing.

OPERATOR ACTION: set chamber.volume_l in config/instruments.local.yaml
before first leak rate use.

F28 added to ROADMAP for ArchiveReader engine replay integration
(F17 residual). F27 spec-ready for chamber photos feature.

pyproject.toml bumped 0.43.0 → 0.44.0.

Ref: artifacts/handoffs/2026-05-01-overnight-summary.md
Ref: CC_PROMPT_OVERNIGHT_2026-05-01.md
Batch: phase-D / overnight-2026-05-01 / v0.44.0 release
Risk: tagged release."

git tag -a v0.44.0 -m "v0.44.0 — Storage maturity + leak rate

F26 + F17 + F13 shipped overnight. 49 new tests. Full suite ~2040+
passing. Operational maturity feature batch closing the F-cluster
backlog."

git push origin master
git push origin v0.44.0
```

### 2.7 Track C verification

```bash
git log --oneline --graph -10
git tag -l "v0.44*"
.venv/bin/pytest tests/ --co -q | tail -3
```

---

## 3. Track A — README RU translation

### 3.1 Background

README.md was rewritten 2026-04-30 in docs-audit Phase 2. Sonnet
wrote it in English. Vladimir wants Russian-dominant style
matching original CryoDAQ doc convention (technical English terms
embedded in Russian prose).

### 3.2 Approach

Read current README.md (English). Translate to Russian preserving:
- Technical English terms inline (LakeShore, Keithley, ZMQ,
  asyncio, Chebyshev, SQLite, Parquet, etc.)
- Code blocks unchanged
- File paths unchanged
- Section headers translated
- All facts identical (no content changes, only language)

### 3.3 Voice match

Read `~/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md` for tone
reference. Russian engineer-direct style, no marketing speak,
technical terms in English where field-standard.

### 3.4 Anti-patterns

- ❌ "благодаря применению передовых технологий"
- ❌ "революционная замена"
- ❌ Inflated marketing prose
- ✅ "Заменяет 3-летний LabVIEW VI"
- ✅ "1 992+ tests passing"
- ✅ Direct engineer-to-engineer tone

### 3.5 Commit

```bash
git add README.md
git commit -m "docs(readme): restore Russian-dominant style

README.md rewritten 2026-04-30 (docs-audit Phase 2 Group I) was
in English. Vladimir's preference: Russian prose with technical
English terms embedded inline, matching project doc convention.

Content unchanged — translation only. Section structure preserved.
Code blocks, file paths, technical terms (LakeShore, ZMQ, Parquet,
etc.) untouched.

Voice reference: ~/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md.

Batch: phase-D / docs-audit / Track A
Risk: docs-only, no behavior change."

git push origin master
```

---

## 4. Track B — Docs audit Phase 2 execution

### 4.1 Spec source

Per existing spec at
`~/Projects/cryodaq/CC_PROMPT_DOCS_REWRITE_PHASE2_2026-04-30.md`.

Read full spec. Execute Groups in architect-recommended order:
**I → III → II → IV** (Group III's archive moves precede Group II's
new architecture.md write).

### 4.2 Adjustments since spec write

Some spec items may have changed during this session's work:

- README.md was rewritten in Group I (Phase 2 Group I) but is
  now being re-translated in Track A above. If Track A executes
  before Track B Group I, treat README as already done in this
  session — skip re-rewrite, just verify content reflects v0.44.0
  reality (mention F17, F26, F13 in known limitations / workflows
  if appropriate)
- pyproject.toml is now 0.44.0 (not 0.43.0). README + PROJECT_STATUS
  should reflect this.
- ROADMAP F-row reflects F26+F17+F13 ✅ DONE (Track C). DOC_REALITY_MAP
  retire decision still applies.
- CHANGELOG has [0.44.0] section (Track C).

### 4.3 Group execution discipline

Each Group:
1. Read existing files identified in spec
2. Apply rewrite per spec structure
3. Self-review against truth source (CHANGELOG, ROADMAP, src/)
4. Commit per Group commit template in spec
5. Push origin master

Surface ARCHITECT DECISION NEEDED markers in handoff for items
where current state has diverged from spec assumptions.

### 4.4 Final report

Per spec §7. After all 4 Groups land, write Phase 2 final report.

---

## 5. Master summary handoff

After all three tracks complete:

`artifacts/handoffs/2026-05-01-parallel-work-summary.md`:

```markdown
# Parallel work session 2026-05-01 — Master summary

## Tracks executed
| Track | Status | Commits | Risk |
|---|---|---|---|
| C — Merges + v0.44.0 | ... | F26 SHA, F17 SHA, F13 SHA, release SHA, tag | medium |
| A — README RU | ... | <SHA> | docs |
| B — Docs audit Phase 2 | ... | Group I-IV SHAs | docs |

## Master HEAD
Pre-session: c44c575
Post-session: <SHA> (v0.44.0 tagged)

## Tag
v0.44.0 → <SHA>

## ARCHITECT DECISION NEEDED markers
[aggregate from handoffs]

## Outstanding (post-session)
- F27 chamber photos — spec ready, multi-cycle implementation
  pending architect-Vladimir synchronous session
- F28 ArchiveReader engine replay — small follow-up to F17
- Lab Ubuntu PC verification (physical access pending)
- F19 channel heuristic refinement (LOW)
- Future: F8/F9 research items (cooldown ML, TIM auto-report)
```

Wake-up echo:
```bash
echo "═══════════════════════════════════════"
echo "PARALLEL SESSION 2026-05-01 COMPLETE"
echo "═══════════════════════════════════════"
echo "Master: $(git log -1 --format='%h %s' master)"
echo "Tag: v0.44.0 → $(git rev-parse v0.44.0 2>/dev/null | head -c 7)"
echo "═══════════════════════════════════════"
echo "Architect: read 2026-05-01-parallel-work-summary.md"
```

---

## 6. Hard stops

- Master HEAD differs from `c44c575` at session start unexpectedly
  → STOP, verify with architect
- Track C merge conflict on any of F26/F17/F13 → STOP that merge,
  document, continue with remaining + skip release if any branch
  unmerged
- Track C tag push fails → STOP
- Test regression after any merge → STOP, may need revert
- Test infrastructure broken at session start → STOP

Single track failure does NOT stop session — move to next track.

---

## 7. Architect comm-out discipline

Architect actively in another conversation. Surface ARCHITECT
DECISION NEEDED markers in per-track handoffs. Architect returns
periodically.

For ambiguous decisions:
- Apply safest interpretation
- Document in handoff
- Continue

---

## 8. Begin

Read this prompt fully. Verify clean master at `c44c575`.

Execute Tracks in order: C → A → B.

GO.
