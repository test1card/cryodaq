# Montana + Hardening — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the safe-additive / inert-behind-flag half of the Montana-inspired
strategy + perimeter hardening, without touching the shipped fail-closed safety
core in any way an operator would feel.

**Architecture:** Each task is independently testable, TDD-first, and either
(a) additive (new module/endpoint), (b) a fail-closed tightening of an edge, or
(c) inert behind a default-OFF flag. One feature branch: `feat/montana-phase1`.

**Tech Stack:** Python 3.12+, asyncio, SQLite (WAL), FastAPI, PySide6, pyqtgraph,
pytest, ruff. venv interpreter: `.venv/bin/python` (`python` is NOT on PATH).

## Global Constraints

- **Model discipline:** implementation by **Opus** subagents; **Fable** (coordinator) reviews; **Codex** (`gpt-5.5`, reasoning high) reviews every meaningful step. Verbatim.
- **No AI traces** in commits/code/PRs (no Co-Authored-By / Claude / Codex mentions). Commit body carries `Ref:` and `Risk:` lines (ORCHESTRATION.md §5.5).
- **TDD mandatory:** failing test first; prove it fails without the fix (git stash of src); ruff clean on touched files; coordinator reviews diff before commit.
- **CI budget:** full `.venv/bin/python -m pytest -q` on tasks touching widely-imported modules (`zmq_bridge.py`, `safety_manager.py`, `engine.py`); targeted `pytest <file>` otherwise.
- **Russian** for operator-facing GUI text and CHANGELOG.
- **Do not push / tag** anything; coordinator holds for architect OK.
- **Safety invariant:** SafetyManager remains sole on/off authority; no task adds a second control path or bypasses it.

## Per-task review gate (runs after each task's implementation, before commit)

1. Opus subagent implements the task TDD-first, writes a short report to `scratchpad/montana/impl_<task>.md`, leaves changes uncommitted.
2. **Fable review:** diff read, fails-without-fix confirmed, ruff + targeted tests green, safety-invariant check.
3. **Codex review** (meaningful steps = every task except pure-doc ME-17): `codex exec -m gpt-5.5 -c model_reasoning_effort="high" -s read-only "<task diff + brief>" > scratchpad/montana/codex_<task>.md`. Resolve CRITICAL/HIGH before commit; log LOW as residual.
4. Coordinator commits with `Ref:`/`Risk:`. Then next task.

## File Structure (Phase 1)

- Modify `src/cryodaq/core/safety_manager.py` — S1 bool-honoring stop_source.
- Modify `src/cryodaq/engine.py` + `src/cryodaq/storage/sqlite_writer.py` — readings_history clamp.
- Create `src/cryodaq/core/path_jail.py`; modify `src/cryodaq/engine.py` — ME-6 jail.
- Modify `src/cryodaq/core/zmq_bridge.py` — socket-level size caps.
- Regenerate `requirements-lock.txt`; add CI drift check.
- Rewrite `CLAUDE.md` module index; create `tests/test_claudemd_index.py` — ME-17.
- Create `src/cryodaq/web/rest_api.py`; modify `src/cryodaq/web/server.py` — REST reads.
- Create `src/cryodaq/analytics/cooldown_fingerprint.py`, `cooldown_compare.py`; modify `cooldown_service.py`; new GUI card — cooldown baseline.
- Rewrite `tsp/p_const.lua` → `tsp/cryodaq_wdog.lua`; modify `keithley_2604b.py` — watchdog plumbing (default-OFF flag).

---

### Task 1: S1 — interlock `stop_source` must honor `emergency_off()` bool (CRITICAL, safety-path)

**Files:**
- Modify: `src/cryodaq/core/safety_manager.py:~1148-1180` (the `action == "stop_source"` branch)
- Test: `tests/core/test_safety_fixes.py` (add cases near existing emergency_off fail-closed tests)

**Interfaces:**
- Consumes: `Keithley2604B.emergency_off() -> bool` (CR-2 contract: never raises; True iff all channels verified OFF).
- Produces: nothing new; behavior change only.

**Context:** CR-2 (v0.57.0) made driver `emergency_off` never-raise + return bool, and fixed the operator + `_fault` call sites. The interlock `stop_source` call site (`safety_manager.py:~1154`) still only catches exceptions (which no longer occur) and ignores the bool — so a `False` (output NOT confirmed off) still falls through to `_active_sources.clear()` + transition to `SAFE_OFF`. This is the third call site of the CR-2 class. Fail-closed fix: `False` → escalate to `_fault` (latch), same as the other sites.

- [ ] **Step 1: Write failing test** — `emergency_off` returns False in stop_source path ⇒ state ends FAULT_LATCHED, not SAFE_OFF.

```python
async def test_interlock_stop_source_faults_when_off_unconfirmed():
    mgr, broker = await _make_manager()
    k = _mock_keithley()
    k.emergency_off = AsyncMock(return_value=False)  # output NOT confirmed off
    mgr._keithley = k
    # drive to RUNNING with an active source, then trip a stop_source interlock
    await _get_to_running(mgr, broker)
    await mgr.on_interlock_trip("overheat_soft", "Т5 Радиатор", 320.0, action="stop_source")
    assert mgr.state == SafetyState.FAULT_LATCHED, (
        f"unconfirmed OFF on interlock stop must latch FAULT, got {mgr.state}"
    )
```
(Adapt `on_interlock_trip` call to the actual signature; if `action` is resolved internally per interlock name, configure a stop_source interlock in the test manager instead.)

- [ ] **Step 2: Run test, verify it FAILS** (state ends SAFE_OFF today). `.venv/bin/python -m pytest tests/core/test_safety_fixes.py::test_interlock_stop_source_faults_when_off_unconfirmed -v`
- [ ] **Step 3: Implement** — in the `stop_source` branch, capture the bool and escalate on False:

```python
if self._keithley is not None:
    try:
        ok = await self._keithley.emergency_off()
    except Exception as exc:  # defensive; CR-2 contract says it won't raise
        await self._fault(f"{reason} (emergency_off raised: {exc})", channel=channel, value=value)
        return
    if not ok:
        await self._fault(f"{reason} (emergency_off could not confirm OFF)", channel=channel, value=value)
        return
# only reach here when OFF is confirmed
self._active_sources.clear()
```
- [ ] **Step 4: Run test, verify PASS**; also run the full safety suite: `.venv/bin/python -m pytest tests/core/test_safety_fixes.py tests/core/test_safety_manager.py -q`
- [ ] **Step 5: Codex review** of the diff (safety-path — mandatory), resolve findings.
- [ ] **Step 6: Commit** — `fix(safety): interlock stop_source latches FAULT when OFF is unconfirmed` · Ref: audit CR-2 class, third call site (Codex D7.1) · Risk: safety-path; full safety suite green.

---

### Task 2: readings_history clamp (semantic-DoS)

**Files:**
- Modify: `src/cryodaq/engine.py:~2790` (`readings_history` command handler) and/or `src/cryodaq/storage/sqlite_writer.py:~760` (`read_readings_history`)
- Test: `tests/core/test_sqlite_writer.py` or `tests/test_engine_commands.py`

**Context:** `readings_history` accepts an unbounded `channels` list and `limit`, and fetches all rows before truncation. Clamp: cap `limit` (e.g. `_HISTORY_MAX_ROWS = 100_000`), cap channel-list length (e.g. 64), and push `LIMIT` into the SQL, not post-fetch.

- [ ] **Step 1: Failing test** — request with `limit=10_000_000` and 500 channels returns clamped counts and the SQL used a bounded LIMIT (assert via a small dataset that only ≤ cap rows come back).
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** clamp constants + `min()` clamps + `LIMIT ?` in the query; reject/truncate over-long channel lists.
- [ ] **Step 4: Verify PASS** + `.venv/bin/python -m pytest tests/core/test_sqlite_writer.py -q`.
- [ ] **Step 5: Codex review.**
- [ ] **Step 6: Commit** — `fix(storage): clamp readings_history channels/limit and push LIMIT into SQL` · Ref: Codex D7.3 semantic-DoS · Risk: read path; bounded.

---

### Task 3: ME-6 — calibration import/export path jail

**Files:**
- Create: `src/cryodaq/core/path_jail.py`
- Modify: `src/cryodaq/engine.py:1203-1257` (5 path params: json_path, table_path, curve_cof_path, curve_340_path, import path)
- Test: `tests/core/test_path_jail.py`

**Context:** paths built straight from the command dict, no confinement, over unauthenticated loopback REP. Base dir = the CalibrationStore's existing `_exports_dir` (`calibration.py:219`, `<base>/exports`) — no new dir decision. Import needs an allow-list + the existing `load_curve`/`.340` parse is the content validator.

**Interfaces:**
- Produces: `resolve_within(base: Path, user_path: str) -> Path` (raises `ValueError` on escape); used by engine calibration handlers.

- [ ] **Step 1: Failing tests** — `../../etc/x`, `~/.ssh/y`, absolute `/tmp/z`, and a symlink-inside-base-pointing-out all raise `ValueError`; an in-base relative name resolves under base.

```python
def test_resolve_within_rejects_traversal(tmp_path):
    base = tmp_path / "exports"; base.mkdir()
    for bad in ["../../etc/x", "/tmp/z", "~/y"]:
        with pytest.raises(ValueError):
            resolve_within(base, bad)
    ok = resolve_within(base, "curve_T12.json")
    assert str(ok).startswith(str(base.resolve()))
```
- [ ] **Step 2: Verify FAIL** (module missing).
- [ ] **Step 3: Implement** `resolve_within` with `os.path.realpath` + `commonpath` check, `normcase` (Windows case-fold), reject `~`, reject absolute-outside-base, resolve symlink final target. Wire all 5 engine call sites; on `ValueError` return `{"ok": False, "error": "path outside allowed directory"}`.
- [ ] **Step 4: Verify PASS** + engine calibration command tests green.
- [ ] **Step 5: Codex review** — ask specifically about Windows UNC/drive-relative + TOCTOU + NFD normalization (Codex D5).
- [ ] **Step 6: Commit** — `fix(security): confine calibration import/export paths to the exports dir` · Ref: ME-6 / Codex D5 · Risk: rejects out-of-base paths (base = existing exports dir, no workflow change).

---

### Task 4: ZMQ command/data size caps (socket-level)

**Files:**
- Modify: `src/cryodaq/core/zmq_bridge.py` (REP `recv()` ~:538; SUB msgpack `unpackb` ~:187)
- Test: `tests/test_zmq_safety.py`

**Context:** REP command frame has no byte cap; SUB msgpack `unpackb` has no `max_buffer_size`. Codex D6: caps must be socket-level (`ZMQ_MAXMSGSIZE`) before allocation, not `len(raw)` after recv, plus bounded msgpack.

- [ ] **Step 1: Failing tests** — set `MAXMSGSIZE` on REP + SUB sockets (assert via `get`/`getsockopt`); `msgpack.unpackb(payload, max_buffer_size=2*1024*1024)` rejects an oversize map with the expected exception.
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** `socket.setsockopt(zmq.MAXMSGSIZE, N)` on the REP and SUB sockets at creation; add `max_buffer_size` to `unpackb`; keep a defensive `len(raw)` guard too.
- [ ] **Step 4: Verify PASS** + **FULL suite** (zmq_bridge is widely imported): `.venv/bin/python -m pytest -q`.
- [ ] **Step 5: Codex review.**
- [ ] **Step 6: Commit** — `fix(ipc): socket-level size caps on ZMQ REP/SUB + bounded msgpack` · Ref: audit C.2 / Codex D6 · Risk: touches zmq_bridge; full suite green.

---

### Task 5: HI-5 — regenerate requirements-lock.txt + CI drift check

**Files:**
- Modify: `requirements-lock.txt`; add CI step (`.github/workflows/*.yml`) or a `scripts/check_lock_drift.py`.
- Test: the drift check itself (resolve pyproject → diff against lock → fail on missing pins).

**Context:** lock is stale — missing `lancedb`, `pypdf`, `tzdata`, `httpx`. `build.sh` uses `--no-deps`, so frozen bundles break (RAG ImportError, Windows parquet ZoneInfoNotFoundError). **Verify on the Windows target, not just macOS** — mark that as a manual gate in the commit body.

- [ ] **Step 1** Regenerate lock via pip-compile/uv from current `pyproject.toml`; confirm all 4 present.
- [ ] **Step 2** Add `scripts/check_lock_drift.py` that resolves and fails on drift; a test invoking it on the fixed lock passes, on a synthetic stale lock fails.
- [ ] **Step 3** Wire into CI.
- [ ] **Step 4** Codex review (light).
- [ ] **Step 5** Commit — `build: regenerate requirements-lock (lancedb/pypdf/tzdata/httpx) + CI drift gate` · Ref: HI-5 · Risk: build-only; **needs Windows frozen-build smoke verification (manual gate).**

---

### Task 6: ME-17 — rebuild CLAUDE.md module index + doc-lint (doc-only, no Codex step)

**Files:**
- Modify: `CLAUDE.md` (module index section)
- Create: `tests/test_claudemd_index.py`

**Context:** index omits 13 live modules and lists retired v1 tabs as current. Rebuild to match reality; add a doc-lint test so it can't drift.

- [ ] **Step 1: Failing test** — every `src/cryodaq/**/*.py` (excluding `__pycache__`, private `_*`) appears in the CLAUDE.md module index, and every path mentioned in the index exists.
- [ ] **Step 2: Verify FAIL** (13 missing).
- [ ] **Step 3: Implement** — rebuild the index; make the test pass.
- [ ] **Step 4: Verify PASS.**
- [ ] **Step 5: Commit** — `docs: rebuild CLAUDE.md module index + drift-lint test` · Ref: ME-17 · Risk: doc-only.

---

### Task 7: REST read-only facade + Swagger + field whitelist

**Files:**
- Create: `src/cryodaq/web/rest_api.py` (APIRouter `/api/v1`)
- Modify: `src/cryodaq/web/server.py` (mount router; add "API docs" link)
- Test: `tests/test_rest_api.py`

**Context:** thin read-only layer over the SAME command/cache path (`_ServerState.last_readings`, `_query_history`, read commands). FastAPI gives Swagger/OpenAPI free. **Codex D6: responses must whitelist fields** — redact operator/sample/notes/config_snapshot/artifact paths (`experiment.py:116-137`) and operator-log authors; add request-size middleware. Loopback-only unchanged. **No write endpoints.**

**Interfaces:**
- Produces endpoints: `GET /api/v1/{state,temperatures,pressure,readings,history,alarms,experiment,log}` — all read-only, all field-whitelisted.

- [ ] **Step 1: Failing tests** (TestClient, patch `_async_engine_command`): `/api/v1/temperatures` returns K-unit readings; `/api/v1/experiment` response does **NOT** contain `operator`/`sample`/`notes`/`config_snapshot`; oversize request body → 413 before engine call. Mirror `tests/test_web_dashboard.py` patterns.
- [ ] **Step 2: Verify FAIL** (router missing).
- [ ] **Step 3: Implement** router + Pydantic response models that expose only whitelisted fields + size middleware; mount in `create_app`. Keep `test_no_public_bind_in_docs` green.
- [ ] **Step 4: Verify PASS** + `.venv/bin/python -m pytest tests/test_rest_api.py tests/test_web_dashboard.py -q`.
- [ ] **Step 5: Codex review** — focus on field-leak + that no write path exists.
- [ ] **Step 6: Commit** — `feat(web): read-only REST /api/v1 with Swagger docs and field whitelist` · Ref: Report B (reads) / Codex D6 · Risk: additive, loopback-only, read-only, redacted.

---

### Task 8: Cooldown baseline DB (fingerprint + baseline + compare + GUI)

**Files:**
- Create: `src/cryodaq/analytics/cooldown_fingerprint.py`, `src/cryodaq/analytics/cooldown_compare.py`
- Modify: `src/cryodaq/analytics/cooldown_service.py:~600` (tap before `_buffer.clear()`, config-flagged)
- Modify: config `config/plugins.yaml` (new `cooldown_baseline:` block)
- GUI: new "История охлаждений" card in the Архив overlay + live verdict badge in Аналитика
- Test: `tests/analytics/test_cooldown_fingerprint.py`, `test_cooldown_compare.py`, fixtures

**Context:** the detector already holds `(t_hours, T_cold, T_warm)` + `cooldown_start_ts` at `_on_cooldown_end`; add a tap. Store JSON per fingerprint under `data/cooldown_history/` (glob, no new DB). Golden baseline = `baseline.json` pointer. Compare in log-space for vacuum. Ultimate-vacuum via off-hot-path `read_readings_history`. Fully additive; reuse `validate_new_curve` quality gate = the same `is_usable` idea. **This is the largest task — subagent may split into 8a (fingerprint+compare+tap, backend) and 8b (GUI card), reviewed separately.**

- [ ] **Step 1 (8a): Failing tests** — `build_fingerprint` computes duration, `T_cold_final=min`, `time_to_base`, `time_to_50K`, `ultimate_vacuum=min(p)`; `compare` flags degraded on +30% time-to-base and 1-decade-worse vacuum; golden-vs-golden = all ok. Synthetic-cooldown fixtures.
- [ ] **Step 2** Verify FAIL.
- [ ] **Step 3** Implement `cooldown_fingerprint.py` (dataclass + builder + atomic JSON IO via existing `atomic_write_text`), `cooldown_compare.py` (deltas + verdicts + thresholds from config), the flagged tap, baseline pin/history.
- [ ] **Step 4** Verify PASS + `.venv/bin/python -m pytest tests/analytics -q`.
- [ ] **Step 5** Codex review (8a).
- [ ] **Step 6** Commit 8a — `feat(analytics): per-cooldown fingerprint + golden-baseline comparison` · Ref: Report C · Risk: additive, off hot-path, flag-guarded.
- [ ] **Step 7 (8b)** GUI card (design-system tokens, offscreen-Qt smoke test) → Fable+Codex review → commit `feat(gui): cooldown history card with baseline overlay`.

---

### Task 9: Keithley TSP watchdog plumbing (inert behind default-OFF flag)

**Files:**
- Rewrite: `tsp/p_const.lua` → `tsp/cryodaq_wdog.lua` (pure watchdog, both channels; salvage heartbeat, drop regulation)
- Modify: `src/cryodaq/drivers/instruments/keithley_2604b.py` (upload/arm/pet/disarm command emission behind `_wdog_enabled`, default False; mock-mode skip; upload-failure-non-fatal)
- Modify: `src/cryodaq/core/safety_manager.py` (reconcile: `cryodaq_wdog_tripped` → `_fault`)
- Config: `config/instruments.yaml` `keithley.watchdog.{enabled:false, timeout_s:5.0}`
- Test: `tests/drivers/test_keithley_watchdog.py`, algorithm-contract test

**Context:** ONLY the host plumbing + Lua + tests, all inert while flag is OFF. No hardware, no go-live. T defaults **5.0s** (bench-conservative). Reconcile path is the important one (a firmware save the host silently re-runs from is worse than no watchdog).

- [ ] **Step 1: Failing tests** (fake transport, assert exact command strings): arm-on-start emits upload + `CRYODAQ_WDOG_TIMEOUT_S = 5.0` + run; pet-on-poll emits N `cryodaq_wdog_pet()` for N polls; disarm-on-stop; upload-failure → connect/start still succeed + `_wdog_armed False` + CRITICAL log; mock-mode → zero wdog writes; reconcile: transport reports `cryodaq_wdog_tripped=1` → SafetyManager FAULT_LATCHED. Plus a pure-Python algorithm-contract test of the deadline logic.
- [ ] **Step 2** Verify FAIL.
- [ ] **Step 3** Implement Lua rewrite + host plumbing (all gated on `_wdog_enabled`, default False) + reconcile.
- [ ] **Step 4** Verify PASS + `.venv/bin/python -m pytest tests/drivers -q`.
- [ ] **Step 5** Codex review — feed it the 2600B TSP execution-semantics question (D3) and the reconcile path.
- [ ] **Step 6** Commit — `feat(safety): Keithley TSP dead-man watchdog plumbing (inert, default-OFF)` · Ref: Report A / Codex D3 · Risk: inert behind flag; go-live is a separate bench-gated phase.

---

## Self-Review notes

- **Coverage:** S1 (Codex D7.1), ME-6 (D5), ZMQ caps (D6), readings_history (D7.3), REST whitelist (D6), rate-guard/sentinel/1b-debounce are **Phase 2** (NaN doctrine) — intentionally not here. HI-5, ME-17, cooldown, watchdog-plumbing = the ratified safe-additive/inert set.
- **Order rationale:** safety-path S1 first (highest value, smallest, isolated). Then cheap SA hardening (2–6). Then additive value (7–8). Watchdog plumbing (9) last — largest, but inert.
- **Not in Phase 1 (needs Phase-2 doctrine or bench/architect):** sentinel persistence (ME-4), interlock NaN debounce (1b), rate-clock guard (C-5), lock-token (deprioritized), ME-16 deletion, watchdog go-live.
