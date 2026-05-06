# Overnight Runner 2026-05-01 — Group 1 features (F17 + F26 + F13)

> Single mega-prompt. Sonnet executes 3 features sequentially overnight.
> Architect ASLEEP throughout. Morning review of everything at once.

---

## 0. Operating posture

- **Architect is asleep.** No mid-night chat. Sonnet makes tactical
  decisions per ORCHESTRATION v1.3 §13 autonomy band; strategic
  ambiguities go to handoff with "ARCHITECT DECISION NEEDED".
- **No quota anxiety.** Burn audits freely. Re-audit until convergence.
- **Time budget:** ~5-7 hours total across 3 features.
- **Sonnet model.** Same approach as F3 + F10 + F19-F25 overnights.
- **Architect: web Claude Opus 4.7** — not active during the night.

This is a focused **3-feature sprint** on Group 1 autonomous-friendly
infrastructure work:
- **F26** — XS polish (~20 LOC) — quick warmup
- **F17** — M operational maturity (~350 LOC) — substantial
- **F13** — M engineering metric (~200 LOC) — physical lab value

All three independent, executable in one session. Two batched
feature branches for coherent merge units.

---

## 1. Feature scope summary

| F | Effort | Branch | Reason batched |
|---|---|---|---|
| F26 | XS (~20 LOC) | feat/overnight-f26-sqlite-whitelist | Independent, mechanical |
| F17 | M (~350 LOC) | feat/overnight-f17-cold-rotation | Storage subsystem, standalone |
| F13 | M (~200 LOC) | feat/overnight-f13-leak-rate | Vacuum analytics, standalone |

**Three separate branches.** None depend on each other.

DO NOT merge any branch autonomously. Architect reviews all three
in morning, decides merge order.

---

## 2. F26 — SQLite WAL gate backport whitelist

**Source:** ROADMAP F26. Architect note from F25 ship 2026-04-30.

**Branch:** `feat/overnight-f26-sqlite-whitelist`

### 2.1 Background

F25 (shipped v0.43.0) hard-fails engine startup on SQLite versions
in `[3.7.0, 3.51.3)` per WAL-reset corruption bug.

Per SQLite official docs (verified by architect 2026-04-30 via
sqlite.org/wal.html), backports of the fix are available for
specific patch versions:
- `3.44.6` (backport of fix; 3.44.7+ does NOT have backport)
- `3.50.7` (backport of fix; 3.50.8..3.51.2 does NOT have backport)

Current F25 implementation false-positive blocks these two
specific patch builds. Add whitelist to allow them through without
requiring `CRYODAQ_ALLOW_BROKEN_SQLITE=1` bypass.

### 2.2 Spec

Read `src/cryodaq/storage/sqlite_writer.py` `_check_sqlite_version()`.

Modify logic:

```python
# Pseudocode shape — adapt to actual function signature
SQLITE_BACKPORT_SAFE = frozenset([
    (3, 44, 6),
    (3, 50, 7),
])

def _check_sqlite_version() -> None:
    v = _get_sqlite_version_tuple()  # existing helper
    if v < (3, 7, 0):
        return  # too old to have WAL bug
    if v >= (3, 51, 3):
        return  # fix landed
    if v in SQLITE_BACKPORT_SAFE:
        return  # specific backport whitelist
    
    # Existing code: raise RuntimeError or bypass via env var
    ...
```

Exact integration shape may differ — preserve existing error
message format, env var bypass, and module flag
`_SQLITE_VERSION_CHECKED`. ONLY add the whitelist check.

### 2.3 Tests

`tests/storage/test_sqlite_writer_executor_separation.py` (or
wherever F25 tests live — find via grep `_check_sqlite_version`):

Add 2 new tests:
- `test_sqlite_3_44_6_backport_safe_passes` — version (3, 44, 6) does NOT raise
- `test_sqlite_3_50_7_backport_safe_passes` — version (3, 50, 7) does NOT raise

Verify existing tests still pass (3.44.5, 3.44.7, 3.50.6, 3.50.8,
3.51.2 should still raise without env var bypass).

### 2.4 Commit + push

```
git checkout -b feat/overnight-f26-sqlite-whitelist
# implement + tests
.venv/bin/pytest tests/storage/ -v
git add src/cryodaq/storage/sqlite_writer.py tests/storage/
git commit -m "feat(sqlite): F26 backport whitelist for WAL-fix patch versions

Per SQLite official advisory (sqlite.org/wal.html), the WAL-reset
corruption fix is backported to two specific patch versions:
- 3.44.6 (NOT 3.44.7+; backport is single-version)
- 3.50.7 (NOT 3.50.8..3.51.2)

F25 (v0.43.0) currently false-positive blocks these versions.
Add SQLITE_BACKPORT_SAFE frozenset whitelist to allow these
specific patch builds through the startup gate without requiring
CRYODAQ_ALLOW_BROKEN_SQLITE=1 bypass.

Tests: 2 new (3.44.6 passes, 3.50.7 passes).
Existing F25 tests unchanged.

Ref: ROADMAP.md F26
Ref: artifacts/calibration/2026-04-30/MASTER-SUMMARY.md (F25 architect note)
Batch: phase-D / overnight-2026-05-01 / F26
Risk: low — narrow whitelist addition, no behavior change for non-whitelisted versions."

git push -u origin feat/overnight-f26-sqlite-whitelist
```

### 2.5 Audit

Per ORCHESTRATION §14.2: dual-verifier (Codex + Gemini) for code
changes. F26 is XS but touches startup gate — audit anyway.

Audit prompts at:
`artifacts/consultations/2026-05-01-overnight-f26/codex-audit.prompt.md`
`artifacts/consultations/2026-05-01-overnight-f26/gemini-audit.prompt.md`

Per existing dispatch syntax (see prior overnight runner specs).
If Gemini quota: skip, document. If Codex returns CRITICAL/HIGH
findings: fix-up loop until PASS or 5 iterations.

### 2.6 F26 handoff

`artifacts/handoffs/2026-05-01-f26-handoff.md` per per-feature
handoff template.

---

## 3. F17 — SQLite → Parquet cold-storage rotation

**Source:** ROADMAP F17. Operational maturity feature for long-term
lab use.

**Branch:** `feat/overnight-f17-cold-rotation`

### 3.1 Background

`data/data_*.db` SQLite files accumulate forever currently. Through
3-6 months of lab usage, disk pressure becomes real concern.

F1 (Parquet archive per-experiment, shipped v0.34.0) provides the
underlying export mechanism. F17 adds a **housekeeping daemon** that:
- Identifies SQLite files older than configurable threshold (default
  N=30 days)
- Exports to Parquet with Zstd compression
- Lays out under `data/archive/year=YYYY/month=MM/` partitioning
- Deletes original SQLite ONLY after successful Parquet write
  (atomicity)
- Read-path replay layer reads both: SQLite (recent) + Parquet
  (archive)

### 3.2 Architecture

#### 3.2.1 Cold rotation service

New module: `src/cryodaq/storage/cold_rotation.py`

`ColdRotationService` class:
- `__init__(data_dir, archive_dir, age_days, scheduler)` — config
- `async run_once()` — single rotation pass: scan, identify, rotate
- `async start()` / `async stop()` — daemon lifecycle (scheduler-driven)
- Default schedule: once daily at configurable time (e.g., 03:00 UTC
  local low-traffic window)

Per-file rotation:
1. Acquire file-level lock (advisory — verify no live writes via
   SQLiteWriter ownership check)
2. Read all rows from SQLite via streaming query
3. Write to Parquet at `<archive_dir>/year=<YYYY>/month=<MM>/<original_name>.parquet`
   with Zstd compression
4. Verify Parquet file integrity (row count match, sample content
   read-back)
5. Compute checksum, store in archive index
6. ONLY THEN delete original SQLite file + WAL + SHM auxiliaries
7. Log rotation event via existing event_logger pattern

Error handling:
- Parquet write fails → leave SQLite untouched, log error, abort
  this file's rotation
- Verification fails → leave SQLite, delete partial Parquet, abort
- Lock acquisition fails (live writes) → skip file, retry next pass
- Disk full → graceful abort, log

#### 3.2.2 Replay layer

New module: `src/cryodaq/storage/archive_reader.py` (or extend
existing reader)

`ArchiveReader` class:
- `query(channels, from_ts, to_ts) -> AsyncIterator[Reading]` — unified
  read across SQLite + Parquet sources
- Time-based source selection:
  - If `to_ts` within recent (SQLite-covered) range → SQLite query
  - If `from_ts` in archive range → Parquet scan
  - If span crosses boundary → both, merged in time order
- Handles missing files gracefully (logged, query returns partial)

Existing readers (whatever components query historical data —
e.g., experiment manager finalize, archive overlay queries) call
`ArchiveReader` instead of direct SQLite queries.

#### 3.2.3 Configuration

`config/housekeeping.yaml` extension:

```yaml
cold_rotation:
  enabled: true
  archive_dir: data/archive
  age_days: 30
  schedule_time: "03:00"  # local time daily
  zstd_compression_level: 3
```

#### 3.2.4 Index

New file: `data/archive/index.json` (or sqlite-based index — choose
simpler):

```json
{
  "files": [
    {
      "original_name": "data_2026-03-15.db",
      "archive_path": "year=2026/month=03/data_2026-03-15.db.parquet",
      "rotated_at": "2026-04-15T03:01:23+03:00",
      "row_count": 12345678,
      "size_bytes_original": 524288000,
      "size_bytes_archive": 87654321,
      "checksum_md5": "abc123..."
    }
  ]
}
```

ArchiveReader uses this index for O(1) file lookup vs filesystem
scan.

### 3.3 Acceptance criteria

1. Service identifies SQLite files older than `age_days`
2. Rotation produces valid Parquet with same data (row count match,
   sample content read-back identical)
3. Original SQLite deleted ONLY after successful Parquet verification
4. Rotation atomicity: crash mid-rotation doesn't leave inconsistent
   state (either both files exist or only Parquet)
5. Index updated with each successful rotation
6. ArchiveReader serves queries unified across both sources
7. Live SQLiteWriter writes never blocked by rotation pass
8. Configurable disable via `cold_rotation.enabled: false`
9. Tests cover: rotation success, rotation atomicity, replay across
   boundary, disabled state, lock contention, disk full
10. No regression in existing storage tests

### 3.4 Tests

`tests/storage/test_cold_rotation.py` (new, ~200 LOC):
- test_rotation_identifies_old_files
- test_rotation_produces_valid_parquet
- test_original_deleted_only_after_verification
- test_rotation_atomicity_on_crash (mock failure mid-write)
- test_disabled_state_no_rotation
- test_lock_contention_skips_file
- test_disk_full_graceful_abort

`tests/storage/test_archive_reader.py` (new, ~150 LOC):
- test_query_recent_uses_sqlite
- test_query_archived_uses_parquet
- test_query_crosses_boundary_merges_sources
- test_missing_archive_file_logged_partial_result
- test_existing_sqlite_reader_callers_unchanged_behavior

### 3.5 Implementation cycles

**Cycle 1: cold_rotation.py + tests** — service implementation
**Cycle 2: archive_reader.py + tests** — replay layer
**Cycle 3: integration + housekeeping config + engine wiring** —
make daemon actually run

Each cycle dual-verifier audit per ORCHESTRATION §14.2.
Convergence loop per cycle.

After all cycles done, branch pushed, NOT merged.

### 3.6 F17 handoff

`artifacts/handoffs/2026-05-01-f17-handoff.md`.

Architect decisions to surface:
- Index format choice (JSON vs SQLite-based) — defer to simpler
  unless implementation reveals constraint
- Schedule_time default (03:00 chose; verify reasonable for lab
  ops timezone)
- `age_days` default 30 — verify reasonable

---

## 4. F13 — Vacuum leak rate estimator

**Source:** ROADMAP F13.

**Branch:** `feat/overnight-f13-leak-rate`

### 4.1 Background

After valve close, pressure rise rate gives leak rate:

```
leak_rate = (dP/dt) * V_chamber  [mbar·L/s]
```

This is a standard cryostat health metric. Operators normally do
this manually with stopwatch + pressure log. F13 automates:
- Detection of "valve closed" state (operator-triggered or
  inferred from pressure signature)
- Sampling pressure for configurable duration after valve close
- Linear regression: `dP/dt`
- Computation: `leak_rate = (dP/dt) * V_chamber`
- Logging to historical leak rate as cryostat health metric over
  time
- Alarm threshold: warning if leak_rate exceeds configurable bound

### 4.2 Architecture

Read `src/cryodaq/analytics/vacuum_trend.py` for existing patterns
during recon. Reuse where possible.

#### 4.2.1 LeakRateEstimator class

New module: `src/cryodaq/analytics/leak_rate.py`

```python
@dataclass
class LeakRateMeasurement:
    started_at: datetime
    duration_s: float
    initial_pressure_mbar: float
    final_pressure_mbar: float
    dpdt_mbar_per_s: float
    chamber_volume_l: float
    leak_rate_mbar_l_per_s: float
    fit_quality_r2: float  # R² of linear fit
    samples_n: int

class LeakRateEstimator:
    def __init__(self, chamber_volume_l: float, sample_window_s: float = 300.0):
        # chamber_volume_l from config/instruments.yaml or chamber config
        ...
    
    def start_measurement(self, t0: datetime, p0_mbar: float) -> None:
        ...
    
    def add_sample(self, t: datetime, p_mbar: float) -> None:
        ...
    
    def finalize(self) -> LeakRateMeasurement:
        # Linear regression, return measurement
        ...
```

#### 4.2.2 Trigger logic

Two trigger modes:

**Mode A — Operator-triggered (primary).**
- ZMQ command `leak_rate_start` with optional duration override
- ZMQ command `leak_rate_stop` to early-finalize
- GUI button somewhere reasonable (architect spec leaves this to
  CC's mechanical judgment per existing GUI patterns — Settings
  overlay or Instruments overlay are candidates)

**Mode B — Auto-trigger (best-effort).**
- Watch pressure signature: pressure stable for >60s, then valve
  close indicator (pressure plateau → small rise transition)
- Auto-start measurement on detection
- DEFER mode B if implementation gets hairy. Mode A is sufficient
  for v1.

If Mode B not implemented: document in commit + handoff.

#### 4.2.3 Storage

Each measurement persisted as event in event_logger (existing
pattern). Plus optional dedicated `leak_rate_history.json` for
trend tracking.

#### 4.2.4 Alarm integration (optional, simple)

If `leak_rate_warning_threshold_mbar_l_per_s` configured:
- Measurement that exceeds threshold publishes warning alarm via
  AlarmEngine v2 (existing diagnostic publish pattern from F10)
- DEFER if integration adds significant complexity. Operator can
  read from event log for v1.

### 4.3 Configuration

`config/instruments.yaml` extension (or new `config/chamber.yaml`):

```yaml
chamber:
  volume_l: 50.0  # operator fills in actual chamber volume
  
leak_rate:
  enabled: true
  default_sample_window_s: 300.0  # 5 min default
  warning_threshold_mbar_l_per_s: 1.0e-4  # configurable per chamber
```

If chamber volume not set: `leak_rate_start` returns error
"chamber volume not configured".

### 4.4 Acceptance criteria

1. Operator can trigger leak rate measurement via ZMQ command
2. Measurement runs for configured duration
3. Result computed via linear regression with R² quality metric
4. Result logged to event_logger
5. Configurable disable via `leak_rate.enabled: false`
6. Missing chamber volume → graceful error (not crash)
7. Tests cover: measurement lifecycle, regression accuracy, edge
   cases (constant pressure → zero leak, noisy data → low R²),
   missing chamber volume

### 4.5 Tests

`tests/analytics/test_leak_rate.py` (new, ~150 LOC):
- test_leak_rate_estimator_linear_fit_known_data
- test_leak_rate_zero_when_pressure_constant
- test_leak_rate_low_r2_on_noisy_data
- test_measurement_lifecycle (start → samples → finalize)
- test_chamber_volume_unset_raises
- test_disabled_state

`tests/core/test_engine_leak_rate_command.py` (new, ~50 LOC):
- test_leak_rate_start_command_handler
- test_leak_rate_stop_command_handler

### 4.6 Implementation cycles

**Cycle 1: LeakRateEstimator + unit tests** — math + lifecycle
**Cycle 2: Engine ZMQ commands + integration test** — command plane wiring
**Cycle 3: Optional GUI button + alarm integration** — IF time/budget allows

If Cycle 3 cuts: defer with note, F13 polish to F-task entry.

Each cycle dual-verifier audit. Convergence loop per cycle.

### 4.7 F13 handoff

`artifacts/handoffs/2026-05-01-f13-handoff.md`.

Architect decisions to surface:
- GUI button location (Mode A primary trigger UI)
- Whether Mode B (auto-trigger) implemented or deferred
- Chamber volume default — leave unset, require operator config?
- Alarm integration shipped or deferred to F-task polish?

---

## 5. Per-feature execution discipline

For each of F26, F17, F13:

1. **Recon (§14.1):** read spec section, verify file paths exist,
   grep existing patterns
2. **Branch:** `feat/overnight-f<NN>-<slug>` from current master
3. **Implement** per spec
4. **Test scoped** then **test full suite**
5. **Commit on branch**
6. **Push to origin**
7. **Dispatch dual-verifier audit** (Codex + Gemini)
8. **Wait** (12-min timeout cap per wave)
9. **Read responses, classify findings**
10. **Fix-up loop** until PASS or 5 iterations
11. **Per-feature handoff**
12. **Move to next feature**

DO NOT auto-merge any branch. Architect reviews all 3 in morning.

Order of execution:
- F26 first (XS, ~30 min, warmup)
- F17 second (largest, 3-4h)
- F13 third (medium, 1-2h)

If F17 stuck or runs over budget: STOP F17 with incomplete handoff,
move to F13. Don't burn remaining night on stuck cycle.

---

## 6. Audit prompt template (per feature)

Per-feature dual-verifier dispatch via direct Chutes API
(per ORCHESTRATION v1.3 §15.1) for Codex+Gemini-equivalent models
OR per-existing CLI dispatch for Codex/Gemini.

### 6.1 Codex dispatch

```bash
mkdir -p ~/Projects/cryodaq/artifacts/consultations/2026-05-01-overnight-f<NN>

nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox workspace-write --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < ~/Projects/cryodaq/artifacts/consultations/2026-05-01-overnight-f<NN>/codex-audit-iter<M>.prompt.md \
  > ~/Projects/cryodaq/artifacts/consultations/2026-05-01-overnight-f<NN>/codex-audit-iter<M>.response.md 2>&1 &
echo "Codex PID: $!"
```

Note `--sandbox workspace-write` per ORCHESTRATION v1.3 §15.3.

### 6.2 Gemini dispatch

```bash
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat ~/Projects/cryodaq/artifacts/consultations/2026-05-01-overnight-f<NN>/gemini-audit-iter<M>.prompt.md)" \
  > ~/Projects/cryodaq/artifacts/consultations/2026-05-01-overnight-f<NN>/gemini-audit-iter<M>.response.md 2>&1 &
echo "Gemini PID: $!"
```

If Gemini quota exhausted: skip Gemini, document, proceed with
Codex sole verifier (per calibration v1.0 routing — Codex strong
for narrow code review).

### 6.3 Wait pattern

```bash
for i in $(seq 1 12); do
  sleep 60
  CR=$(pgrep -f "codex exec" > /dev/null && echo "yes" || echo "no")
  GR=$(pgrep -f "gemini -m gemini" > /dev/null && echo "yes" || echo "no")
  echo "minute $i: codex=$CR gemini=$GR"
  if [ "$CR" = "no" ] && [ "$GR" = "no" ]; then
    break
  fi
done
```

12-min cap; if cap hit: kill, work with partial.

---

## 7. Doc + vault sync (mandatory final phase)

**This phase runs AFTER all features done (or stopped) but BEFORE
the master summary handoff.** Standard closure for every overnight
runner from 2026-05-01 onward.

**Why:** Each feature changes runtime behavior. README, PROJECT_STATUS,
ROADMAP, CHANGELOG, vault subsystem notes describe runtime behavior.
If docs aren't synced at the end of the work, they drift. We learned
this 2026-04-30 (README v0.33.0 stale through 14 features shipped,
vault notes pre-F19-F25, etc).

### 7.1 Scope of sync

CC determines what to update based on what landed during this run.
Only touch docs whose claims are affected by this run's features.
Do NOT do general doc rewrite — that's a separate audit session.

For each feature merged or pushed-but-pending:

**Repo docs:**
- `ROADMAP.md` — F-row status update if shipped (DONE) or note if
  branch pending architect merge
- `CHANGELOG.md [Unreleased]` — append summary entry per shipped
  feature
- `PROJECT_STATUS.md` — only if invariants added (HF-class fix) OR
  if metrics changed (test count, LOC delta worth updating)
- `docs/NEXT_SESSION.md` — move completed items to "Recent
  completions", refresh open work table
- Feature-specific docs:
  - F26 → no specific doc impact (XS polish to F25)
  - F17 → `docs/architecture.md` if cold rotation is significant
    architectural addition; mention briefly in subsystem map
  - F13 → `docs/instruments.md` if leak rate is operator-facing
    procedure; add brief section

**Vault notes (use Obsidian MCP, in-place extensions per
ORCHESTRATION-approved pattern):**
- `60 Roadmap/F-table backlog.md` — sync F-row status
- `60 Roadmap/Versions.md` — DO NOT add tag row (tagging is
  architect morning task); but if Unreleased section exists, note
  pending features
- `10 Subsystems/<relevant>.md` — only if a feature substantively
  changes the subsystem behavior described:
  - F26 → `10 Subsystems/Persistence-first.md` — extend F25 section
    with backport whitelist
  - F17 → likely needs new `10 Subsystems/Cold rotation.md` note OR
    extend `Persistence-first.md` with rotation section
  - F13 → `10 Subsystems/Vacuum trend.md` extension OR new
    `10 Subsystems/Leak rate.md` note (architect-decision; if
    ambiguous, default to extending nearest existing note)
- Update `last_synced` field on every touched note to today's date
- Run vault source map regen + verify 0 broken wikilinks
- Append `_meta/build log.md` entry

### 7.2 Scope discipline

DO update:
- Docs whose specific claims are made wrong by this run's changes
- Vault notes about subsystems this run touched
- Index files (Versions, F-table, ROADMAP F-row)

DO NOT update:
- Docs unaffected by this run (full audit is separate session)
- Tag rows in Versions.md (architect's tagging decision)
- Anything requiring architect-domain decision (archive vs refresh,
  doc retirement, etc.)

If updating a doc would require architect-domain decision, write
"ARCHITECT DECISION NEEDED" to handoff and skip that doc.

### 7.3 Verification

After sync:

```bash
# Repo docs
grep -rn "v0\.4[0-3]" --include="*.md" PROJECT_STATUS.md ROADMAP.md \
     CHANGELOG.md docs/NEXT_SESSION.md
# Verify no v0.43 stale references that should be v0.44 if release
# imminent (architect decides actual tag)

# Vault
python3 ~/Projects/cryodaq/artifacts/vault-build/build_source_map.py
# Expect: 0 broken wikilinks
```

### 7.4 Sync commit

Group all repo doc updates into ONE commit at end:

```bash
git add ROADMAP.md CHANGELOG.md PROJECT_STATUS.md docs/NEXT_SESSION.md \
        [any feature-specific docs touched]
git commit -m "docs(sync): post-overnight 2026-05-01 doc + vault sync

Reflects features F26 + F17 + F13 status (3 feature branches pushed,
awaiting architect merge). Vault subsystem notes refreshed for
affected subsystems only.

No doc-domain decisions made autonomously — anything requiring
architect-domain judgment surfaced via handoff 'ARCHITECT DECISION
NEEDED' markers.

Docs touched:
- ROADMAP.md: F26/F17/F13 row status
- CHANGELOG.md [Unreleased]: pending feature entries
- docs/NEXT_SESSION.md: open items refresh
- [list other touched docs]

Vault touched (in-place via Obsidian MCP):
- 60 Roadmap/F-table backlog.md
- 10 Subsystems/Persistence-first.md (F26 + F17)
- 10 Subsystems/Vacuum trend.md (F13) [or as actually touched]

Source map regen: 0 broken wikilinks.

Ref: CC_PROMPT_OVERNIGHT_2026-05-01.md Phase 7
Batch: phase-D / overnight-2026-05-01 / doc-sync
Risk: docs only."

git push origin master
```

### 7.5 Sync handoff

Write `artifacts/handoffs/2026-05-01-doc-sync-handoff.md`:

```markdown
# Doc + vault sync handoff — overnight 2026-05-01

## Repo docs updated
| File | Section / claim updated |
|---|---|

## Vault notes updated
| Note | What changed | last_synced |
|---|---|---|

## Vault notes added
[if any new notes — should be rare per in-place pattern]

## Docs NOT updated despite touched-feature
[if a doc obviously needed update but architect-decision required]

## ARCHITECT DECISION NEEDED
- ...

## Verification
- Source map regen: 0 broken wikilinks ✓
- grep for stale version references: clean ✓
```

---

## 8. Master summary handoff

After all 3 features done (or stopped) AND doc sync (Phase 7) done:

`artifacts/handoffs/2026-05-01-overnight-summary.md`:

```markdown
# Overnight 2026-05-01 — Master Summary

## Features
| F | Branch | Status | Tests | Audit verdict |
|---|---|---|---|---|
| F26 | feat/overnight-f26-sqlite-whitelist | DONE-PASSED | N/N green | Codex PASS, Gemini ... |
| F17 | feat/overnight-f17-cold-rotation | ... | ... | ... |
| F13 | feat/overnight-f13-leak-rate | ... | ... | ... |

## Master HEAD
Pre-night: c44c575 (or whatever)
Post-night: <SHA> (no auto-merges)

## Branches awaiting review
- feat/overnight-f26-sqlite-whitelist at <SHA>
- feat/overnight-f17-cold-rotation at <SHA>
- feat/overnight-f13-leak-rate at <SHA>

## Architect morning queue
1. Read this summary
2. Review F26 handoff (smallest, easiest first)
3. Review F17 handoff
4. Review F13 handoff
5. Decide merge order
6. ROADMAP F26+F17+F13 → ✅ DONE after merge
7. Tag candidate: v0.44.0 if substantial work

## ARCHITECT DECISION NEEDED markers
[aggregate from per-feature handoffs]

## Outstanding
- F19 channel heuristic refinement (LOW)
- Lab Ubuntu PC verification
- Future: F8/F9 research (cooldown ML pause, TIM auto-report)
- F12, F14, F16, F18 — backlog or retire decision pending

## Confidence
[HIGH/MEDIUM/LOW per feature]
```

Wake-up echo:

```bash
echo "═══════════════════════════════════════"
echo "OVERNIGHT 2026-05-01 COMPLETE"
echo "═══════════════════════════════════════"
echo "Master: $(git log -1 --format='%h %s' master)"
echo "Branches awaiting review:"
git branch -av | grep "feat/overnight-f[0-9]"
echo "Handoffs:"
ls artifacts/handoffs/2026-05-01-* | head -10
echo "═══════════════════════════════════════"
echo "Architect: read 2026-05-01-overnight-summary.md first"
```

---

## 9. Hard stops (whole-night-level)

These STOP THE ENTIRE NIGHT:

- Master HEAD different from `c44c575` at start (drift since v0.43.0)
- Test infrastructure broken on master baseline
- Disk full / OOM
- F26 (warmup) fails entirely — environment issue
- All audit dispatch (Codex + Gemini both) fails on first feature

Single feature stuck does NOT stop the night. Move to next feature.

---

## 10. Architect comm-out discipline

Sonnet does not see chat. Write everything to handoffs.

When unsure: apply safest interpretation, document in handoff
under "ARCHITECT DECISION NEEDED", continue.

Examples of safest interpretation:
- Spec ambiguous on GUI placement (F13 trigger button) → use
  pattern from existing nearest analogous control
- F17 archive index format ambiguous → JSON simpler than SQLite
  unless implementation reveals constraint
- F17 schedule_time default → 03:00 local (low-traffic)
- F13 Mode B auto-trigger gets hairy → defer Mode B, ship Mode A

---

## 11. Tracking discipline

Per-feature handoff schema:

```markdown
# F<NN> overnight 2026-05-01 — architect review

## Branch
feat/overnight-f<NN>-<slug> at <SHA>

## Implementation
Files changed: <list with line counts>
LOC: +X / -Y
Tests added: <count>

## Acceptance criteria
1. [PASS / FAIL / PARTIAL] <criterion>
...

## Audit history
| Iter | Codex | Codex# | Gemini | Gemini# | Action |
|---|---|---|---|---|---|

## Final unfixed findings
| # | Severity | Notes |

## Spec deviations
- None / list with rationale

## Architect decisions needed (morning)
- ...
```

---

## 12. Begin

F26 first. Read spec fully. Verify clean master at `c44c575` or
later (post-v0.43.0 + post-docs-audit if those landed).

Per ORCHESTRATION v1.3 §10 session-start checklist:
- Read CLAUDE.md
- Skill registry refresh (if any new skills added past 24h)
- Recon before execution (verify HEAD, tags, file existence)
- Note any plugins auto-loaded (per §10 plugin auto-load awareness)

GO.
