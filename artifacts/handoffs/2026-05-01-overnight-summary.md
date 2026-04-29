# Overnight sprint 2026-05-01 — master summary

Session: overnight autonomous sprint executing `CC_PROMPT_OVERNIGHT_2026-05-01.md`
Architect: asleep. All branches pending morning review.

---

## Branches produced

| Feature | Branch | SHA | Tests | Codex verdict |
|---------|--------|-----|-------|---------------|
| F26 WAL backport whitelist | `feat/overnight-f26-sqlite-whitelist` | `649fb1a` | 14 pass | PASS (2 cycles) |
| F17 cold-storage rotation | `feat/overnight-f17-cold-rotation` | `0435121` | 16 pass | PASS (3 cycles) |
| F13 leak rate estimator | `feat/overnight-f13-leak-rate` | `02afa77` | 19 pass | PASS (2 cycles) |

Total: 49 tests passing across 3 branches. All Codex-audited to PASS.

---

## F26 — SQLite WAL gate backport whitelist

**Files:** `src/cryodaq/storage/sqlite_writer.py` (+14 LOC), `tests/core/test_f23_f24_f25_misc.py` (+22 LOC)

XS scope: `SQLITE_BACKPORT_SAFE = frozenset([(3,44,6),(3,50,7)])` constant + whitelist check
inserted inside affected-range gate before env var bypass. Both versions skip RuntimeError.
Adjacent versions still raise.

**Audit:** CONDITIONAL (missing negative tests) → PASS after adding 4 parametrized boundary tests.

---

## F17 — SQLite → Parquet cold-storage rotation

**Files:** `src/cryodaq/storage/cold_rotation.py` (446 LOC), `src/cryodaq/storage/archive_reader.py` (175 LOC), `config/housekeeping.yaml` (+10 LOC), 2 test files (16 tests)

`ColdRotationService`:
- `run_once()`: glob `data_????-??-??.db`, skip today + already-rotated, rotate each via `asyncio.to_thread()`
- Rotation sequence: read all rows → write Parquet (Zstd, chunked 100k) → verify row count → update index.json → delete SQLite+WAL+SHM
- `asyncio.Lock` prevents concurrent runs
- `start()`/`stop()` daemon (86400s sleep between passes)

`ArchiveReader.query(channels, from_ts, to_ts)`: day-by-day UTC iteration, checks index → Parquet or SQLite fallback.

**Critical fixes applied:**
- `_read_index()` raises RuntimeError on corrupt JSON (both files) — aborts rotation rather than silently overwriting index
- `_update_index()` wrapped in try/except → cleans up partial Parquet on failure
- Epochs computed from UTC-normalized timestamps (not naive local-time)
- `UTC` import added to `archive_reader.py`

---

## F13 — Vacuum leak rate estimator

**Files:** `src/cryodaq/analytics/leak_rate.py` (245 LOC), engine.py (+55 LOC), config/instruments.yaml (+7 LOC), 2 test files (19 tests)

`LeakRateEstimator`:
- `start_measurement(t0, p0_mbar, *, window_s)` / `add_sample(t, p_mbar)` / `finalize()` / `cancel()`
- Sliding window: `add_sample()` trims samples older than `window_s` from front
- Auto-finalize: engine `_leak_rate_feed()` task calls `should_finalize()` after each sample; logs event on expiry
- numpy-free OLS `_linear_regression(xs, ys)` → (slope, intercept, R²); R²=0.0 on degenerate input (all-equal timestamps)
- `finalize()` clears `_samples` on call (prevents stale reuse)
- History persisted atomically to `data/leak_rate_history.json`

Engine wiring:
- `_leak_rate_feed()` subscribes to DataBroker, filters `unit=="mbar"` (optionally by `pressure_channel`)
- `leak_rate_start` handler: validates `duration_s` (positive finite float), checks `enabled` config flag
- `leak_rate_stop` handler: returns `asdict(LeakRateMeasurement)` in response payload

Config (`config/instruments.yaml`):
```yaml
chamber:
  volume_l: 0.0  # OPERATOR: set actual chamber volume in litres
  leak_rate:
    enabled: true
    default_sample_window_s: 300.0
    warning_threshold_mbar_l_per_s: 1.0e-4
```

**Critical fixes applied:**
- Engine never fed samples → added `_leak_rate_feed()` broker task
- No window trimming → sliding-window FIFO in `add_sample()`
- OLS R²=1.0 on degenerate input → changed to R²=0.0
- Double-finalize possible → `_samples` cleared in `finalize()`
- `duration_s` validation for NaN/inf/zero/negative

---

## Residual risks

| Risk | Feature | Severity | Notes |
|------|---------|----------|-------|
| F17: ArchiveReader not wired into replay.py | F17 | LOW | Read layer exists; engine replay deferred |
| F13: leak_rate.pressure_channel shares vt_cfg | F13 | LOW | Fine for single-gauge; multi-gauge needs separate key |
| F13: chamber.volume_l = 0.0 | F13 | INFO | OPERATOR must set before use; ValueError on finalize |

---

## Architect actions

1. Review and merge 3 branches (order: F26 → F17 → F13 suggested, but all independent)
2. Set `chamber.volume_l` in `config/instruments.yaml` or `config/instruments.local.yaml`
3. Tag next release when ready (v0.44.0 candidate)

---

## Test totals

- F26: 14 passed
- F17: 16 passed  
- F13: 19 passed
- **Total this sprint: 49 tests**
