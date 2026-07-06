# NaN-доктрина — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Same execution protocol as Phase 1: Opus implements TDD-first (uncommitted, report to
> `scratchpad/montana/impl_p2_<task>.md`), Fable reviews per task and commits with
> `Ref:`/`Risk:`, Codex gpt-5.5 high reviews batched per wave. No push/tag without OK.

**Goal:** replace the point-guards of v0.57.0 with one doctrine:
a Reading is either FINITE-VALID or NON-FINITE-ERROR, discriminated by
`ChannelStatus` on every layer — never by float value, never silent.
Closes C-4, ME-4, D-C19, ME-15 with one rule. Release candidate: v0.59.0.

**Branch:** `feat/nan-doctrine` (stacked on `feat/montana-phase1`).

**Ratified basis (Vladimir 2026-07-06 + verification amendments):**
- 1a: sentinel + ChannelStatus discriminator, no migration, one shared render-helper.
  Hard contract: (a) writer REJECTS a sentinel-valued row whose status is non-error;
  (b) the три status-dropping readers (xlsx pivot ~`xlsx_export.py:136`,
  `archive_reader.py:140`, web history) must include status in SELECT or mask sentinel.
- 1b interlock NaN: **SIGNED OFF 2026-07-06** — debounced escalation (amendment; was:
  ratified log-loud). Implement as P2-5 after the doctrine predicate lands.
- Retrofit HI-2 / D-C19 / ME-15 guards under the doctrine (single `is_usable()`).
- Phase-3 rider (after doctrine lands): C-5 rate-clock guard, RESET-not-drop
  (any gap backward or >4×poll forward → clear channel buffer, new sample = anchor).

## Global Constraints
Same as Phase 1 plan (model discipline, no AI traces, TDD with RED evidence,
`.venv/bin/python -m pytest`, ruff, Russian operator text, safety invariant:
SafetyManager sole authority). CI budget: full suite on tasks touching
sqlite_writer/engine/safety_manager; targeted otherwise.

---

### Task P2-1: Doctrine core — status classifier at the Reading boundary

**Files:** `src/cryodaq/drivers/base.py` (or `core/`, follow where Reading lives),
new tests. Produce ONE predicate (e.g. `Reading.is_usable` / module fn):
usable ⇔ status is an OK-class status AND value is finite. NON-FINITE-ERROR ⇔
non-finite value OR error-class status. No float-based checks anywhere downstream.
- [ ] Failing tests: NaN+OK → not usable; finite+ERROR → not usable; finite+OK → usable; ±inf → not usable.
- [ ] Implement; grep analytics ingest push-sites and switch them to the predicate
      (cooldown_service, steady_state, vacuum_trend, sensor_diagnostics ingest edges).
- [ ] Targeted analytics + drivers tests green.

### Task P2-2: ME-4 sentinel persistence + writer contract

**Files:** `src/cryodaq/storage/sqlite_writer.py`, shared render-helper module, tests.
- [ ] Failing tests: non-finite value persists as sentinel WITH error status (invariant
      «if DataBroker has it, SQLite has it» becomes literally true); writer raises/rejects
      sentinel-value + non-error status (contract a); round-trip read maps sentinel+status
      back to NaN-presentation via the shared helper.
- [ ] Implement sentinel + discriminator + helper. No schema migration.
- [ ] Full sqlite_writer suite green.

### Task P2-3: status-dropping readers retrofit

**Files:** `src/cryodaq/storage/xlsx_export.py` (~:136 pivot), `storage/archive_reader.py`
(~:140), web history path (`web/server.py` `_query_history`). Each must carry status or
mask sentinel via the shared helper — an exported XLSX/parquet/JSON must never show the
sentinel as a real number.
- [ ] Failing tests per reader (sentinel row → masked/NaN in output, never the raw sentinel).
- [ ] Implement via the P2-2 helper. Targeted export/web tests green.

### Task P2-4: retrofit HI-2 / D-C19 / ME-15 under the doctrine

**Files:** rate-estimator ingest (HI-2), sensor_diagnostics (D-C19), vacuum_trend/ME-15
site. Replace local NaN-guards with the P2-1 predicate; behavior must stay fail-closed.
- [ ] Failing tests where a guard is currently local/inconsistent.
- [ ] Implement; targeted suites green.

### Task P2-5 (SIGNED OFF 2026-07-06, autonomous authorization): interlock NaN debounced escalation

Amendment 1b: transient NaN on an interlock channel → CRITICAL log + alarm-v2, no trip;
PERSISTENT NaN (≥10 s / ≥5 samples) on an interlock channel while RUNNING → fault.
Outside sourcing: log/alarm only. (Codex proved Т1–Т10 are protected only by interlocks —
log-only is fail-open on the heated zone; ratified log-loud stands until sign-off.)
- [ ] Sign-off recorded in ledger 2026-07-06 — proceed after P2-1..4 (depends on doctrine predicate).

### Task P2-6 (Phase-3 rider, after P2-1..4 committed): C-5 rate-clock guard, reset-not-drop

**Files:** `src/cryodaq/core/rate_estimator.py` (+ safety_manager call path), tests.
Any timestamp gap backward, or forward >4× poll period → clear that channel's buffer,
current sample becomes the new anchor (blindness bounded by the min_points refill window,
~30 s). Keep measurement-time (no revert to monotonic).
- [ ] Failing tests: NTP step back / big forward step → buffer reset, no false rate-fault,
      protection re-arms after refill; normal jitter untouched.
- [ ] Implement; full safety suite green (touches safety path).

---

## Wave plan
Wave B = P2-1 … P2-4 (parallel where files are disjoint: P2-1 first — P2-2..4 depend on
its predicate/helper; then P2-2 solo (sqlite_writer), P2-3+P2-4 parallel).
Then batch Codex review → fix wave → P2-6. P2-5 only after sign-off.
