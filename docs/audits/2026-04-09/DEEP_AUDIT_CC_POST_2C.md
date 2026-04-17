# CryoDAQ Deep Audit — Post Phase 2c (CC run)

**Commit:** `1698150` (Phase 2c + Overview "Всё" button merged)
**Date:** 2026-04-09
**Agent:** Claude Code (Opus 4.6 1M)
**Scope:** core + drivers + storage + analytics + reporting + notifications + web + engine + launcher + frozen_main + paths + logging_setup + config + build + tsp
**Modules audited:** ~46 source files (out of ~67 in scope), targeted reads + grep sweeps for known anti-patterns
**External lookups:** 0 (relied on prior Phase 1–2c web work; this pass focused on code reading)

## Summary

- **CRITICAL:** 0 findings
- **HIGH:** 6 findings
- **MEDIUM:** 19 findings
- **LOW:** 14 findings
- **OK (verified correct):** 12 items

## Methodology notes

This pass was a fresh code read of the production tree as of `1698150`. Focus
areas: alarm engines, experiment lifecycle, calibration acquisition, web
server, cooldown service, sqlite writer + reader, sensor diagnostics, scheduler
recovery ladder, all instrument drivers, all transports, launcher subprocess
management, safety manager `_fault` flow, broker overflow semantics, telegram
HTML rendering, FastAPI auth surface.

I deliberately did **not** re-derive Phase 1/2a/2b/2c findings — they were
filtered by reading the relevant code regions and tagging anything that was
*still wrong* despite the prior fix, OR was fundamentally a different concern.
Some items here may overlap with previously closed findings; the user
explicitly asked me to flag rather than skip when uncertain.

GUI widgets are out of scope (per the prompt) except `gui/zmq_client.py` and
`gui/app.py` entry-point glue, which were checked in Phase 2c work and are
left untouched here.

I did not run pytest, did not edit any code, and did not commit anything
beyond this document.

---

## Findings

### A. Core (safety, alarms, experiment, broker, scheduler, calibration acq)

#### A.1 [HIGH] AlarmStateManager.acknowledge does not actually suppress an alarm

**Location:** `src/cryodaq/core/alarm_v2.py:505-509` (acknowledge method); see
also `_active` dict at line 408.

**Description:** `acknowledge(alarm_id)` only logs an INFO line and returns
`True/False` based on whether the alarm is currently active. It does **not**
remove the alarm from `self._active`, set a flag, or change any state. The
next GUI poll (`alarm_v2_status` ZMQ command) will continue to return the
alarm in the active set.

**Impact:** Operators clicking "Acknowledge" in the GUI see no change to the
red alarm count or the active list. They will conclude the GUI is broken and
either ignore future alarms (alert fatigue) or repeatedly click thinking
something is wrong.

**Evidence:**
```python
def acknowledge(self, alarm_id: str) -> bool:
    if alarm_id in self._active:
        logger.info("ALARM ACKNOWLEDGED: %s", alarm_id)
        return True
    return False
```

**Proposed fix:** Add a sibling `_acknowledged: set[str]` and exclude
acknowledged alarms from `get_active()`, OR add an `acknowledged_at` field to
the `AlarmEvent`/`_AlarmRecord` and have `get_active` filter them out. Phase 1
`alarm.py` has the correct pattern (`_AlarmRecord.state` field).

---

#### A.2 [MEDIUM] AlarmStateManager hysteresis is silently ignored

**Location:** `src/cryodaq/core/alarm_v2.py:483-494` (`_check_hysteresis_cleared`)

**Description:** `_check_hysteresis_cleared` always `return True`. The
docstring acknowledges it's a no-op fallback. Any `hysteresis:` config in
`alarms_v3.yaml` is therefore silently ignored — alarms clear immediately
when the underlying condition flips, with no damping.

**Impact:** Threshold-crossing alarms (e.g. `vacuum_loss_cold` with
`hysteresis: {pressure: 5e-4}` per `config/alarms_v3.yaml:55`) will oscillate
on noisy signals, generating duplicate Telegram pages. Operator confusion +
alert fatigue.

**Evidence:** Method body literally `return True`. The `hysteresis` field is
parsed in `alarm_config.py` (loaded into `cfg`) but never consulted at evaluate
time.

**Proposed fix:** When the alarm clears the threshold but is still within
`config.threshold ± hysteresis`, return `False` so the alarm stays active.
Requires the evaluator to expose the latest value/threshold for the channel
that triggered, which `_eval_threshold`/`_eval_composite` already track.

---

#### A.3 [MEDIUM] `_resolve_channels` ignores `channel_group` despite the schema documenting it

**Location:** `src/cryodaq/core/alarm_v2.py:367-375`

**Description:** The helper handles `channels` (list) and `channel` (str) but
does **not** look up `channel_group` against the top-level `channel_groups`
map in `alarms_v3.yaml`. The Phase 2b housekeeping loader does this correctly
(`housekeeping.py: load_critical_channels_from_alarms_v3`); the alarm v2
evaluator never received the same fix.

**Impact:** Alarms that reference `channel_group: calibrated` (or similar)
will see an empty channel set and never trigger. `config/alarms_v3.yaml:289`
declares `interlocks.overheat_cryostat.channel_group: all_temp` which goes
through `interlock.py` separately, but ANY alarm-side use of channel_group is
broken.

**Evidence:**
```python
def _resolve_channels(self, cfg: dict) -> list[str]:
    if "channels" in cfg:
        return list(cfg["channels"])
    if "channel" in cfg:
        ch = cfg["channel"]
        if ch != "phase_elapsed_s":
            return [ch]
    return []
```

**Proposed fix:** Pass the loaded `channel_groups` dict into `AlarmEvaluator`
at construction; expand `channel_group: <name>` to its member channel list
before evaluation. Reuse `_extract_channel_refs` from
`housekeeping.py:67-110` if convenient.

---

#### A.4 [HIGH] ExperimentManager.finalize_experiment blocks the engine event loop

**Location:** `src/cryodaq/core/experiment.py:732-738`
(also `_write_artifact`, `_build_archive_snapshot`, `_write_end` ~700-731)

**Description:** `finalize_experiment` calls `ReportGenerator(...).generate(...)`
**synchronously** from inside an async context handler. `ReportGenerator.generate`
runs `Document.save`, `subprocess.run([soffice, ...])` and a heavy
`SECTION_REGISTRY[...](document, dataset, assets_dir)` loop. None of these
go through `run_in_executor`. The engine event loop is frozen for tens of
seconds during finalize, possibly minutes if `soffice` runs (E.1 makes that
unbounded).

**Impact:** During every experiment finalize the engine stops:
- publishing readings (broker fan-out blocks)
- processing safety checks (`_monitor_loop` does not tick)
- responding to GUI commands
- heartbeat to subprocess (GUI sees engine "frozen")

The `SafetyManager` heartbeat-timeout for Keithley
(`heartbeat_timeout_s=15.0`) can fire mid-finalize, latching FAULT on a
healthy run that just happens to be finishing.

**Evidence:**
```python
if finished.report_enabled:
    try:
        from cryodaq.reporting.generator import ReportGenerator
        ReportGenerator(self.data_dir).generate(finished.experiment_id)
    except Exception as exc:
        logger.warning("Failed to auto-generate reports for %s: %s", ...)
```

**Proposed fix:** Wrap `ReportGenerator(...).generate(...)` in
`asyncio.to_thread(...)` (or `run_in_executor` with a dedicated single-worker
pool — same pattern as `SQLiteWriter._executor`). Also fold `_write_start` /
`_write_artifact` / `_write_end` into the same executor since each does
sync SQLite + JSON disk writes from async context.

---

#### A.5 [LOW] Experiment ID is only 48 bits of randomness

**Location:** `src/cryodaq/core/experiment.py:578`
`experiment_id = uuid.uuid4().hex[:12]`

**Description:** Truncating UUIDv4 to 12 hex chars → 48 bits of entropy.
Birthday-collision probability over 10⁵ experiments is ~3·10⁻⁵ — small but
non-zero. SQLite `experiments.experiment_id` is `PRIMARY KEY` so a collision
would silently overwrite or raise `IntegrityError` mid-create.

**Impact:** A single bad collision destroys the older experiment's metadata
row (constraint failure) or creates ambiguity in `data/experiments/<id>/`
directory naming.

**Proposed fix:** Use `uuid.uuid4().hex` (32 chars) or
`uuid.uuid4().hex[:16]` (64 bits, ~10¹² safe).

---

#### A.6 [MEDIUM] SafetyBroker.publish abandons remaining subscribers when one queue is full

**Location:** `src/cryodaq/core/safety_broker.py:85-99`

**Description:** When the loop encounters a full queue, it logs CRITICAL,
fires the overflow callback, and **returns early** — never attempts to
publish to subscribers later in the iteration order. A single broken/slow
subscriber blocks the safety pipeline for the rest of the subscribers.

**Impact:** If a future subscriber (e.g. a third-party safety logger added
in Phase 3) ever lags, the SafetyManager itself stops receiving fresh data
and `_run_checks` will fault on stale-data timeout. The fault chain triggers
correctly but the root cause is buried under "stale data" rather than
"safety queue overflow".

**Evidence:**
```python
for sub in self._subscribers.values():
    if sub.queue.full():
        logger.critical(...)
        if self._overflow_callback:
            ...
        return  # Не пытаемся положить в полную очередь
```

**Proposed fix:** Continue the loop after the overflow callback for the
broken subscriber; deliver to remaining healthy queues. The overflow
callback is idempotent (SafetyManager._fault state-latches first), so
firing it once per overflowed sub per batch is fine.

---

#### A.7 [LOW] CooldownDetector mixes wall-clock and monotonic semantics

**Location:** `src/cryodaq/analytics/cooldown_service.py:297-315`

**Description:** `_consume_loop` constructs `reading_ts =
reading.timestamp.timestamp()` (wall-clock from `Reading.now() →
datetime.now(timezone.utc)`) and feeds it into `_detector.update(reading_ts,
...)`. The detector uses this as time for `_estimate_rate()` (linear regression)
and for `_confirm_start_ts` deadlines. Meanwhile `_do_predict()` computes
elapsed via `time.time() - self._cooldown_wall_start` — also wall-clock,
consistent. **However**, an NTP step adjustment during a long cooldown can
make `dT/dt` momentarily go to ±∞ when one reading's timestamp jumps.

**Impact:** Spurious `cooldown started` or `cooldown ended` detections
during rare clock adjustments. Not catastrophic.

**Proposed fix:** Standardise on a monotonic clock (`time.monotonic()`)
captured at scheduler poll time, OR add an outlier filter to the rate
estimator that rejects |dt| > 5 s between consecutive points.

---

#### A.8 [MEDIUM] InterlockEngine._trip awaits `action_callable` inside the per-reading loop, blocking subsequent interlocks

**Location:** `src/cryodaq/core/interlock.py:430-447`

**Description:** `_trip` is called from `_process_reading`, which is called
from `_check_loop` for every published reading. Inside `_trip` the
`action_callable()` is awaited (and so is `trip_handler`). If the action is
slow — e.g. `safety_manager._fault → keithley.emergency_off → 8 VISA writes
+ readback verifies` — the entire interlock check loop is paused, blocking
evaluation of any later reading that might trip a *different* interlock.

**Impact:** If two interlocks could fire concurrently (e.g. overheat AND
overpower at the same poll cycle), the second one waits for the first
action to complete. In a well-tuned setup the first action handles both
(emergency_off), so probably a non-issue in practice — but the assumption
is undocumented.

**Proposed fix:** Either document that interlock actions are serial, OR
fire-and-forget the action via `asyncio.create_task` with strong-ref tracking
(same pattern as Phase 2a `_pending_publishes`). Strong-ref is mandatory.

---

#### A.9 [LOW] CalibrationAcquisitionService activation doesn't prevent target_channels mutation mid-cycle

**Location:** `src/cryodaq/core/calibration_acquisition.py:31-43`

**Description:** `activate()` overwrites `_target_channels` without checking
whether the previous calibration cycle has finished writing. If a new
calibration is activated while the scheduler is mid-`on_readings()`, the
channel set under iteration may change. Single-task scheduler probably
makes this benign in practice.

**Impact:** Race window between scheduler poll and operator-driven
re-configuration. Bound to be small.

**Proposed fix:** Add an asyncio.Lock or document that activate/deactivate
are only safe to call from the engine command handler (which is
single-threaded asyncio).

---

### B. Drivers (instrument + transport)

#### B.1 [HIGH] LakeShore OVERRANGE readings are silently dropped from SQLite

**Location:** `src/cryodaq/storage/sqlite_writer.py:299` (filter) +
`src/cryodaq/drivers/instruments/lakeshore_218s.py:368-377` (OVL → +inf)

**Description:** `lakeshore_218s._parse_response` produces a `Reading` with
`value=float("inf")` and `status=ChannelStatus.OVERRANGE` for `+OVL`
responses. `sqlite_writer._write_day_batch` filters out any reading where
`not math.isfinite(value)`, logging only a `WARNING` count of skipped
readings — the OVERRANGE is **never persisted**. The reading does reach the
broker (in-memory), but historical reconstruction (post-mortem, reports,
GUI history reload) shows a **gap** rather than an OVERRANGE event.

**Impact:** A sensor reaching OVL is exactly the failure mode operators
need to investigate after the fact ("what was T7 doing when the heater
runaway happened?"). The historical record has no evidence — only a
warning line in the log file.

**Evidence:**
```python
# sqlite_writer.py:299
if r.value is None or (isinstance(r.value, float) and not math.isfinite(r.value)):
    skipped += 1
    continue
```

**Proposed fix:** Persist OVERRANGE/UNDERRANGE with a sentinel — either
write `value=NaN` with `status='overrange'` (requires schema change to
allow NULL value) OR write `value=±9.999e30` (LakeShore convention) with
status preserved. The schema currently has `value REAL NOT NULL`, so the
NULL approach needs a migration.

---

#### B.2 [LOW] LakeShore.read_channels has dead code that would crash on a frozen Reading

**Location:** `src/cryodaq/drivers/instruments/lakeshore_218s.py:144-145`

**Description:** The block
```python
if r.metadata is None:
    r.metadata = {}
```
would raise `dataclasses.FrozenInstanceError` because `Reading` is
`@dataclass(frozen=True, slots=True)`. In practice `Reading.metadata` is
declared with `field(default_factory=dict)` so it is never `None`, so the
branch is unreachable. But if a future change makes the field nullable
(or someone constructs a Reading via the binary unpacker with metadata=None),
the line will explode at runtime.

**Impact:** Latent crash bomb. Currently dead code.

**Proposed fix:** Delete the `if r.metadata is None` branch — `Reading.metadata`
is already always a dict.

---

#### B.3 [MEDIUM] Keithley start_source has no rollback on partial-write failure

**Location:** `src/cryodaq/drivers/instruments/keithley_2604b.py:240-247`

**Description:** `start_source` issues 8 sequential VISA writes
(`reset → func → autorange × 2 → limitv → limiti → levelv=0 → output=ON`).
If any write fails, the SMU is left in a partially-configured state and
the exception bubbles to `safety_manager.request_run` which calls `_fault`
which calls `emergency_off`. Most paths converge to safe.

But: if `levelv = 0` (write 7) fails and `output = OUTPUT_ON` (write 8)
succeeds (very unlikely sequence but possible on a transient I/O glitch),
the SMU enables output at the **previously programmed voltage** (whatever
was there before — could be the last voltage from the prior session).

**Impact:** Edge case glitch could energise a heater at the previous
session's voltage rather than 0 V. Magnitude depends on what was last set;
worst case 40 V at 1 A compliance = 40 W heater shock.

**Proposed fix:** Either (a) wrap the configure-then-output sequence in a
try/except that explicitly issues `output = OFF` on any failure, or (b)
verify `source.levelv` readback is 0 before flipping `output = ON`.

---

#### B.4 [MEDIUM] Serial transport `close()` has no timeout on `wait_closed()`

**Location:** `src/cryodaq/drivers/transport/serial.py:81-83`

**Description:** `await self._writer.wait_closed()` is unbounded. On
Windows, when a USB-Serial adapter is yanked mid-operation, pyserial-asyncio
has a known issue where `wait_closed()` hangs indefinitely
(pyserial/pyserial-asyncio#87). The Phase 2b audit flagged this as `F.4`
but Phase 2c scope didn't include `serial.py`.

**Impact:** A USB cable yank during Thyracont disconnect freezes the
scheduler GPIB+serial loop forever. SafetyManager fail-on-silence catches
it eventually via stale-data, but the disconnect path itself is wedged.

**Proposed fix:** Wrap `wait_closed()` in `asyncio.wait_for(..., timeout=2.0)`
and log a warning on timeout, leaving `_writer` to garbage collect.

---

#### B.5 [LOW] Keithley runtime.active diverges from hardware truth on read failure

**Location:** `src/cryodaq/drivers/instruments/keithley_2604b.py:209-211`

**Description:** When `read_channels` catches a non-OSError exception per
SMU channel, it logs and produces SENSOR_ERROR readings, but does **not**
update `runtime.active` for that channel. SafetyManager continues to think
the channel is active until the scheduler's `consecutive_errors >= 3`
trips `disconnect()` which calls `emergency_off()`. In the gap, GUI Keithley
panel and SafetyManager see `active=True` but the SMU's actual state is
unknown.

**Impact:** Brief inconsistency between Python state and instrument state.
Self-corrects within 3 poll cycles (≤ 3 s typical).

**Proposed fix:** On consecutive read failure (>= 1), call
`emergency_off(smu_channel)` defensively before producing the SENSOR_ERROR
reading, so the instrument is in known-safe state matching the runtime
flag. Or document the gap explicitly.

---

#### B.6 [LOW] Thyracont V1 checksum uses errors="replace" — silently corrupts on non-ASCII bytes

**Location:** `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:305`

**Description:** `byte in payload.encode("ascii", errors="replace")` —
non-ASCII bytes (would only happen on a corrupted RS-232 line) are encoded
as `?` (0x3F) in the checksum computation, but the original byte's value is
lost. The checksum will mismatch, which is the right outcome, but the
diagnostic log message would show the corrupted form, not the original.

**Impact:** Diagnostic ambiguity only. Safe behaviour.

**Proposed fix:** Use `errors="strict"` and let the encode raise on
non-ASCII; treat that as a checksum failure. Or operate on raw bytes
directly without encoding.

---

### C. Storage

#### C.1 [MEDIUM] Skip-NaN behaviour in writer hides sensor errors from history

(Same root cause as B.1 — listed here as the storage-side responsibility.)

**Location:** `src/cryodaq/storage/sqlite_writer.py:299`

**Description:** The writer treats every non-finite reading as garbage and
drops it. The contract should distinguish "this reading IS the sensor
state" (OVERRANGE/UNDERRANGE/SENSOR_ERROR) from "this is a corrupt value
to discard". As-is, the SQLite history loses all evidence of out-of-range
events.

**Impact:** Post-mortem investigations cannot reconstruct the sequence of
failure events for any sensor that hits OVL.

**Proposed fix:** See B.1.

---

#### C.2 [LOW] `_read_readings_history` opens connections without query_only PRAGMA

**Location:** `src/cryodaq/storage/sqlite_writer.py:671`

**Description:** Each daily DB file is opened with
`sqlite3.connect(str(db_path), timeout=5)` and immediately queried. No
`PRAGMA query_only = ON;` is set. SQLite's WAL semantics already prevent
readers from interfering with the writer, but accidentally upgrading a
read connection to a writer (e.g. by a future code change calling
`conn.execute("INSERT ...")`) would corrupt the writer's view.

**Impact:** Defense-in-depth gap.

**Proposed fix:** Add `conn.execute("PRAGMA query_only = ON;")` after
connect.

---

#### C.3 [LOW] parquet_archive read iterates row-by-row in Python

**Location:** `src/cryodaq/storage/parquet_archive.py:108-118`

**Description:** `read_experiment_parquet` does a Python `for i in
range(table.num_rows)` and calls `ts_us[i].as_py()` per element. Defeats
the purpose of using Arrow/Parquet — should use vectorised numpy/pylist
extraction.

**Impact:** Slow read of large experiment archives. ~10× slower than
necessary.

**Proposed fix:** `ts_array = ts_us.to_numpy() / 1e6; values_array =
table.column("value").to_numpy()` then group with numpy, OR use pyarrow's
`groupby`.

---

### D. Analytics

#### D.1 [MEDIUM] Cooldown service uses default executor for scipy work

**Location:** `src/cryodaq/analytics/cooldown_service.py:245, 372, 458`

**Description:** Phase 2b moved VISA transports to dedicated single-worker
executors but did **not** touch `cooldown_service`. The three sites
(`load_model`, `predict`, `ingest_from_raw_arrays`) use
`run_in_executor(None, ...)`. Default pool is `min(32, cpu+4)` workers,
shared across the entire engine process.

**Impact:** A scipy `predict` call (~100ms) competes for the same pool
as `_query_history` from the web server, plus any other future executor
work. Under heavy concurrent load (operator browsing history while a
cooldown is in progress), prediction latency spikes.

**Proposed fix:** Add a dedicated `ThreadPoolExecutor(max_workers=2,
thread_name_prefix="analytics")` to `CooldownService.__init__` and use it
in the three call sites. Match Phase 2b transport executor pattern.

---

#### D.2 [LOW] cooldown_predictor.predict can divide-by-zero in weight normalisation

**Location:** `src/cryodaq/analytics/cooldown_predictor.py:463`
`weights /= weights.sum()`

**Description:** If all `w_total` values are 0 (e.g. extreme outlier rate
where `w_rate` collapses every curve), `weights.sum()` is 0 and division
yields NaN/Inf. The fallback at line 457 only handles
`(use_rate_cold or use_rate_warm) and np.max(rate_weights) < 0.01` —
which doesn't catch the case where `w_prog` is also 0.

**Impact:** `np.average` with NaN weights raises ZeroDivisionError →
caught by `_do_predict` exception handler → log + skip prediction. So
the failure is non-fatal but a prediction tick is silently dropped.

**Proposed fix:** Before normalisation, `if weights.sum() < 1e-9:
weights = np.ones_like(weights)` (uniform fallback).

---

#### D.3 [LOW] vacuum_trend.push silently rejects P <= 0

**Location:** `src/cryodaq/analytics/vacuum_trend.py:126-128`

**Description:** Pressure ≤ 0 reading is dropped without logging. Sensor
zero-output bug, calibration failure, or instrument fault would silently
disable vacuum trend until the next valid reading.

**Impact:** Diagnostic gap — operator wonders why vacuum prediction stopped
updating with no log line.

**Proposed fix:** Log WARNING on first reject, periodic INFO every N
rejects.

---

#### D.4 [LOW] sensor_diagnostics correlation alignment uses 1ms timestamp rounding

**Location:** `src/cryodaq/core/sensor_diagnostics.py:364-365`

**Description:** Two channels with sub-ms timestamp jitter (e.g. one from
GPIB poll at t=1.0001 and the other from a different bus at t=1.0002) round
to the same millisecond, fine. But if the jitter happens across a 0.5 ms
boundary, the rounding lands them on different keys and they never match.
The min_points check then fails and correlation = None.

**Impact:** Underreports correlation between cross-bus channels in
high-jitter conditions.

**Proposed fix:** Use a tolerance-based merge (e.g. ±50 ms window) instead
of exact rounded keys. Or accept the underreport — sensor diagnostics
correlation is a quality-of-life metric, not safety-critical.

---

### E. Reporting

#### E.1 [HIGH] LibreOffice subprocess has no timeout

**Location:** `src/cryodaq/reporting/generator.py:212-216`

**Description:** `subprocess.run([soffice, "--headless", "--convert-to",
"pdf", ...], check=False, capture_output=True)` has **no `timeout=`
argument**. If LibreOffice hangs (corrupt DOCX, font cache rebuild, network
filesystem stall, X server attempt on a headless box), the call blocks
forever.

**Impact:** Combined with A.4 (synchronous call from engine event loop),
a stuck `soffice` freezes the engine indefinitely. Operator ends up
killing the engine process.

**Evidence:**
```python
subprocess.run(
    [soffice, "--headless", "--convert-to", "pdf", str(source_docx_path), "--outdir", str(output_dir)],
    check=False,
    capture_output=True,
)
```

**Proposed fix:** Add `timeout=120` (or whatever ceiling matches expected
PDF generation time). Catch `subprocess.TimeoutExpired`, log WARNING,
return None — best-effort PDF semantics is already documented.

---

#### E.2 [MEDIUM] ReportGenerator runs synchronously in async context

(Same root cause as A.4. Listed here for the reporting-side responsibility.)

**Location:** `src/cryodaq/reporting/generator.py:50-89`

**Description:** Every method on `ReportGenerator` is synchronous and does
blocking disk I/O (`Document.save`, `subprocess.run`, file copies). The
class is consumed from `experiment.finalize_experiment`, which is itself
called from the engine command handler — an async context.

**Impact:** Engine event loop stalls during finalize.

**Proposed fix:** Either expose `ReportGenerator.generate_async()` that
wraps the sync work in `asyncio.to_thread`, OR have callers
(`experiment.finalize_experiment`) do the wrap themselves.

---

#### E.3 [LOW] _resolve_raw_sections silently filters unknown section names

**Location:** `src/cryodaq/reporting/generator.py:196-205`

**Description:** Sections from `template["report_sections"]` that aren't
in `SECTION_REGISTRY` are silently dropped (`if name in SECTION_REGISTRY`).
A typo in `experiment_templates/*.yaml` produces a report missing a
section with no warning to the operator.

**Impact:** Silent template-config errors. Operator wonders why a section
is missing.

**Proposed fix:** When filtering, log WARNING with the dropped name + list
of valid names.

---

### F. Notifications

#### F.1 [MEDIUM] Telegram alarm message has no HTML escaping

**Location:** `src/cryodaq/notifications/telegram.py:160-177`

**Description:** `_format_message` builds an HTML payload using
f-strings:
```python
f"<b>{event.alarm_name}</b>",
f"Канал: <code>{event.channel}</code>",
```
with `parse_mode="HTML"` set in `_send`. If `event.alarm_name` or
`event.channel` contains `<`, `>`, `&` (or worse: a closing `</b>` tag),
Telegram will render or reject the message. The values are operator-controlled
config so this is **not** an exploit — but it is a fragility.

**Impact:** A `&` in a channel name (e.g. "T7 & T8") breaks the Telegram
HTML parser and the message is rejected. Operator misses the alarm.

**Proposed fix:** Wrap each interpolation in `html.escape(...)`, OR switch
to `parse_mode="MarkdownV2"` with proper escaping.

---

#### F.2 [LOW] telegram._send swallows transient network errors with no retry

**Location:** `src/cryodaq/notifications/telegram.py:225-236`

**Description:** Network errors during `session.post` are caught and
logged, but no retry is attempted. A single transient DNS hiccup loses an
alarm notification permanently (the escalation chain DOES retry per-level
with delays, but the per-message send has no retry).

**Impact:** Single missed alarm during a network blip. Not catastrophic
because escalation chain catches it on the next level.

**Proposed fix:** Add a tiny retry-once with a 1 s delay before logging
failure. Or accept that escalation handles it.

---

#### F.3 [LOW] EscalationService._pending grows over time

**Location:** `src/cryodaq/notifications/escalation.py:44, 70-74`

**Description:** `_pending: dict[str, asyncio.Task]` is only pruned when
`cancel(event_type)` is called or when escalate() encounters a duplicate
key (and cancels the existing task before overwriting). Tasks that complete
normally remain in the dict until the next cancel() with their key prefix.

**Impact:** Memory leak proportional to escalation events × levels over
the engine uptime. Each entry is small (~1 KB) so a year of running
eventually accumulates a few hundred KB. Not material.

**Proposed fix:** Add `task.add_done_callback(lambda _: self._pending.pop(key, None))`
when scheduling.

---

#### F.4 [LOW] telegram_commands._poll_loop logs at INFO every iteration

**Location:** `src/cryodaq/notifications/telegram_commands.py:186-188`

**Description:** Every poll iteration (every 2 seconds by default) logs:
```python
logger.info("Telegram polling #%d, offset=%s", iteration, self._last_update_id)
```
That's ~43,000 lines/day at INFO. Overflows log files quickly and
drowns out actually-interesting INFO entries.

**Impact:** Log noise. With 14-day rotation per Phase 2b setup, ~600k
lines accumulate in the active file before rotation.

**Proposed fix:** Drop to DEBUG, OR log only every N iterations (e.g. 1
in 50, ≈ once per 100 s).

---

### G. Web Dashboard

#### G.1 [HIGH] Web endpoints have no authentication

**Location:** `src/cryodaq/web/server.py:325-406` (all endpoints)

**Description:** `/`, `/status`, `/api/status`, `/api/log`, `/history`,
`/ws` accept any incoming HTTP request. No API key, no IP allowlist, no
basic auth. The deployment doc instructs `uvicorn ... --host 0.0.0.0
--port 8080` which exposes the server to the entire LAN. `/api/log` already
forwards `log_get` to the engine; if any future endpoint adds a write
operation it inherits the same wide-open surface.

**Impact:** Any device on the lab LAN can read system state, query
historical data, see safety state, see operator log entries (which may
contain sample/operator names). Worse, the WebSocket has no Origin check
(see G.6).

**Evidence:** No `Depends(...)` on any endpoint. No CORS config. No
middleware that filters by IP.

**Proposed fix:** At minimum add a per-deployment shared bearer token via
env var, validated by a `Depends(...)` on every endpoint. Better: bind to
`127.0.0.1` by default and require operators to opt into LAN exposure
explicitly via a config flag.

---

#### G.2 [MEDIUM] _broadcast iterates _state.clients without snapshotting

**Location:** `src/cryodaq/web/server.py:166-178`

**Description:**
```python
for ws in _state.clients:
    try:
        await ws.send_text(message)
    except Exception:
        disconnected.append(ws)
for ws in disconnected:
    _state.clients.discard(ws)
```
The first loop iterates the live `set` while the websocket endpoint
(`websocket_endpoint` line 392) can `add()`/`discard()` from concurrent
async tasks. Python `set` is not safe to iterate while modifying. CPython
will raise `RuntimeError: Set changed size during iteration` if the
modification happens on the same loop iteration step.

**Impact:** Rare crash in `_broadcast` under concurrent connect/disconnect
storms. Web server task dies and is not restarted (the lifespan handler
has no respawn).

**Proposed fix:** `for ws in list(_state.clients):` to snapshot.

---

#### G.3 [MEDIUM] Dashboard HTML has XSS-equivalent on operator-controlled channel names

**Location:** `src/cryodaq/web/server.py:476-478` (template literal)

**Description:** The inline JS does:
```javascript
temps += `<div class="temp-card"><div class="name">${ch.split(' ')[0]}</div>...
```
and assigns via `innerHTML` (line 484). Channel name comes from server
JSON which comes from operator-edited config files. If a channel name
contains `<script>`, it's executed in the browser's context. Not a
network-side exploit, but a config-error → operator-browser code-execution
path.

**Impact:** Lab operator with malicious YAML can run JS in another
operator's browser. Trust boundary inside the lab — low real risk, but
still incorrect.

**Proposed fix:** Use `textContent` instead of innerHTML for the channel
name field. Or escape via a tiny helper.

---

#### G.4 [MEDIUM] /history has no upper bound on minutes parameter

**Location:** `src/cryodaq/web/server.py:375-390`

**Description:** `async def history(minutes: int = 60)` accepts any int.
A request `?minutes=10000000` will scan all daily DB files and load every
row into memory.

**Impact:** OOM in engine + browser when a curious user/script issues a
huge query. No `LIMIT` is applied per channel either.

**Proposed fix:** `minutes = max(1, min(minutes, 10080))` (cap at 1 week).
Add `limit` parameter to `_query_history`.

---

#### G.5 [MEDIUM] _query_history runs on default executor

**Location:** `src/cryodaq/web/server.py:389`
`channels = await loop.run_in_executor(None, _query_history, minutes)`

**Description:** Same root cause as D.1 — uses default `None` executor.
A history query for several hours competes with analytics, VISA, etc.

**Impact:** History request can starve other engine work.

**Proposed fix:** Dedicated `ThreadPoolExecutor(max_workers=1,
thread_name_prefix="web_history")` in the FastAPI app state.

---

#### G.6 [LOW] WebSocket /ws doesn't validate Origin header

**Location:** `src/cryodaq/web/server.py:392-406`

**Description:** `websocket_endpoint` accepts the WebSocket without
checking `ws.headers.get("origin")`. A browser-based attacker can establish
a WebSocket from any origin (same-origin policy doesn't apply to WebSocket).

**Impact:** Combined with G.1, any LAN-accessible browser can drain the
data stream. Not a privilege-escalation, just a confidentiality leak.

**Proposed fix:** Reject if Origin header is missing or doesn't match an
allowlist.

---

#### G.7 [LOW] FastAPI on_event handlers are deprecated

**Location:** `src/cryodaq/web/server.py:301, 310`

**Description:** `@application.on_event("startup")` and `("shutdown")` are
deprecated since Starlette 0.27 / FastAPI 0.111. They emit
`DeprecationWarning` (visible in Phase 2b test output). New code should use
the `lifespan` async context manager pattern.

**Impact:** Cosmetic; will become a hard error in FastAPI 1.x.

**Proposed fix:** Convert to lifespan pattern. ~15-line refactor.

---

### H. Engine & Launcher

#### H.1 [HIGH] Launcher uses `time.sleep()` inside the Qt main thread

**Location:** `src/cryodaq/launcher.py:255, 312, 340`

**Description:**
- Line 255: `time.sleep(0.5)` in 30-iteration loop = up to **15 seconds
  of frozen UI** during engine probe
- Line 312: `time.sleep(0.5)` in 10-iteration loop = up to **5 seconds**
  during `_wait_engine_ready`
- Line 340: `time.sleep(1)` during `_restart_engine`

Both run on the Qt main thread (called from `_start_engine` and
`_restart_engine`, which are invoked from Qt slots). The Qt event loop
cannot process redraws or input during these sleeps.

**Impact:** UI freezes ("Application not responding") during normal
engine startup or restart. Operator may force-quit thinking it crashed.

**Proposed fix:** Replace blocking loops with `QTimer.singleShot` chains
or run engine startup probing in a `QThread` worker. Or use `qasync` for
proper asyncio integration.

---

#### H.2 [MEDIUM] Engine subprocess output piped to DEVNULL hides early-startup crashes

**Location:** `src/cryodaq/launcher.py:298-299`

**Description:** `subprocess.Popen(... stdout=subprocess.DEVNULL,
stderr=subprocess.DEVNULL ...)`. The Phase 2b logging_setup writes to file
once `setup_logging("engine")` is called from `engine.main()` — but ANY
output BEFORE that point (Python tracebacks during import, missing
dependency errors, multiprocessing fork failures) is silently discarded.

**Impact:** If engine fails to start due to e.g. missing pyvisa backend
or yaml import failure, the launcher sees "engine not responding" with
no diagnostic anywhere on disk. Operator has nothing to troubleshoot.

**Proposed fix:** Pipe stderr to a file in `get_logs_dir()/engine_stderr.log`
(append mode, fixed path so launcher can show it on failure). Tee
`tail -20` of that file into the operator-facing crash modal from H.3.

---

#### H.3 [MEDIUM] Launcher cannot restart an `_engine_external` engine

**Location:** `src/cryodaq/launcher.py:320-321`

**Description:** When `_start_engine` detects a pre-existing engine on
the ZMQ port and sets `_engine_external = True`, the launcher loses all
control over it. `_stop_engine` returns immediately, `_restart_engine`
calls `_stop_engine` then `_start_engine` (which detects external again
and refuses to start a new one) — leaving the operator stuck if the
external engine has gone bad.

**Impact:** Operator has to kill the external engine via OS-level tools,
launcher cannot help.

**Proposed fix:** Add a "Force takeover" menu item that runs
`cryodaq-engine --force` (which already exists per `engine.main(args.force)`)
to kill the external engine and start fresh.

---

#### H.4 [MEDIUM] No engine API exposes wall-clock start time

**Location:** `src/cryodaq/engine.py:772` `start_ts = time.monotonic()`;
`src/cryodaq/gui/widgets/overview_panel.py:_panel_start_ts` (Phase 2c
workaround uses panel construction time instead).

**Description:** The engine tracks its own start in `time.monotonic()`,
which is process-local. The new Overview "Всё" preset (Phase 2c) needs
the engine wall-clock start to render history "since engine launch", and
falls back to `time.time()` captured at GUI panel construction. This is
a few hundred ms off because launcher → engine → GUI startup is not
instantaneous, and totally wrong if the operator opens the GUI long after
the engine started (e.g. via `_engine_external`).

**Impact:** Overview "Всё" button shows wrong start time when launching
the GUI hours after the engine. Cosmetic but operator-facing.

**Proposed fix:** Add `engine_start_wall_ts` field to the existing
`safety_status` or `experiment_status` ZMQ command response (whichever the
GUI already polls), populated from `time.time()` captured at engine
startup. The GUI's "Всё" preset reads from there.

---

#### H.5 [LOW] _watchdog logs INFO every 60s — unconditional

**Location:** `src/cryodaq/engine.py:752-761`

**Description:** Every minute the engine writes a `HEARTBEAT | uptime=…`
INFO line, regardless of whether anything changed. Useful for diagnostics
but adds 1440 lines/day to engine.log.

**Impact:** Log volume.

**Proposed fix:** Drop to DEBUG, or log only on state change / drop count
change.

---

### I. Build & Packaging

#### I.1 [LOW] requirements-lock.txt has no `--hash` lines

**Location:** `requirements-lock.txt`, `build_scripts/build.sh`

**Description:** Phase 2c generated the lockfile via
`pip-compile --extra=dev --extra=web --output-file=requirements-lock.txt
pyproject.toml` — without `--generate-hashes`. The build script attempts
`pip install --require-hashes -r ... 2>/dev/null || pip install -r ...`
which always falls through to the unsafe path because there are no hashes.

**Impact:** Supply-chain integrity is not enforced. If a transitive
package is hijacked on PyPI between builds, the new bundle could include
the malicious version.

**Proposed fix:** Re-run `pip-compile` with `--generate-hashes`. If a
package has cross-platform wheels causing hash mismatch, switch to
`--allow-unsafe` or pin individually.

---

#### I.2 [LOW] PyInstaller spec excludes are a hand-maintained allowlist

**Location:** `build_scripts/cryodaq.spec` (excludes block)

**Description:** A long list of `PySide6.QtBluetooth`, `QtWebEngine`, etc
is excluded. New PySide6 versions may add modules that are not in the
exclude list and silently bloat the bundle. Conversely, if the project
later actually needs one of these, they have to remember to remove the
exclude.

**Impact:** Bundle size drift.

**Proposed fix:** Periodically grep the production tree for `PySide6.Qt*`
imports and regenerate the exclude list.

---

#### I.3 [OK] _frozen_main.py freeze_support ordering

**Location:** `src/cryodaq/_frozen_main.py:43-95`

**Description:** Verified: `multiprocessing.freeze_support()` is the FIRST
statement in every `main_*` function before any cryodaq/PySide6 import.
Phase 1 fix is intact.

---

### J. Config

#### J.1 [LOW] No JSON Schema validation for any *.yaml config

**Location:** all `config/*.yaml` loaders (`engine.py`, `safety_manager.py`,
`alarm_config.py`, `housekeeping.py`, `interlock.py`, `experiment.py`)

**Description:** Each loader does `yaml.safe_load(...)` then accesses keys
directly via `raw["foo"]` or `raw.get("foo", default)`. No schema
validation. Operator typos (`stale_timeout: 10` instead of
`stale_timeout_s: 10`) are silently ignored — the default value is used
and the operator never finds out their configured threshold isn't active.

**Impact:** Silent config errors. The Phase 2b YAML-error → exit-code-2
fix only catches **parse** errors, not semantic errors.

**Proposed fix:** Add `pydantic` (or `jsonschema`) validation per config
file. Phase 2c added Apache 2.0 license metadata via PEP 621 — pydantic is
already a transitive dep of FastAPI (via uvicorn extras).

---

#### J.2 [OK] All YAML loaded via yaml.safe_load

Verified by grep across `src/cryodaq/`. Zero `yaml.load(` (unsafe)
occurrences. Phase 2b finding closed.

---

### K. TSP

#### K.1 [OK] tsp/p_const.lua is not loaded at runtime

**Description:** `keithley_2604b.py:3` says explicitly "no TSP scripts
are uploaded". `tsp/p_const.lua` is a draft for Phase 3 hardware watchdog
upload. Phase 2a deleted the misleading `p_const_single.lua`. The
remaining file is correctly described as a draft.

---

### Z. Verified correct (OK items)

#### Z.1 [OK] SafetyManager._fault deliberately not under _cmd_lock

**Location:** `src/cryodaq/core/safety_manager.py:538-556`

`_fault` is called from multiple contexts (overflow callback, _run_checks,
on_persistence_failure) some of which already hold `_cmd_lock` indirectly
or run from threads. Phase 2a deliberately keeps it unlocked, with the
synchronous `_transition(FAULT_LATCHED)` happening before any await so
the state change is observable to all waiting tasks immediately. Verified.

#### Z.2 [OK] SafetyBroker.freeze() prevents subscribers being added at runtime

`subscribe()` raises `RuntimeError` after `freeze()`. Engine startup
freezes the broker after wiring all known subscribers. Verified at line
54-55.

#### Z.3 [OK] LakeShore IDN retry-after-clear (Phase 2c)

`lakeshore_218s.connect` lines 56-95: validates `LSCI` + `218`, retries
once after `clear_bus()`, raises RuntimeError if still invalid.

#### Z.4 [OK] Keithley OUTPUT_OFF on connect (Phase 2a)

`keithley_2604b.connect` lines 78-115: forces `OUTPUT_OFF` on both SMU
channels in non-mock mode after errorqueue.clear, before assuming control.
Best-effort with critical-log fallback.

#### Z.5 [OK] _bind_with_retry in zmq_bridge (Phase 2b)

Both `ZMQPublisher.start` and `ZMQCommandServer.start` set LINGER=0 then
call `_bind_with_retry` which handles EADDRINUSE with exponential backoff.
Verified.

#### Z.6 [OK] SecretStr wrapping for Telegram tokens (Phase 2b)

`telegram.py`, `telegram_commands.py`, `periodic_report.py` all use
`SecretStr` for `_bot_token`. URL is computed on demand via
`_build_api_url` / `@property _api` / inline local variable.

#### Z.7 [OK] Interlock action differentiation (Phase 2a)

`safety_manager.on_interlock_trip` correctly distinguishes
`emergency_off` (full latch) from `stop_source` (soft, no latch).
Unknown action escalates to fault. Trip handler in engine.py wraps the
call in try/except with last-resort `_fault` escalation.

#### Z.8 [OK] Disk-full graceful degradation (Phase 2a)

`sqlite_writer._write_day_batch` detects disk-full via phrase match,
sets `_disk_full` flag, schedules `safety_manager.on_persistence_failure`
via `run_coroutine_threadsafe`. Scheduler skips polling on the flag.
DiskMonitor logs recovery but does NOT auto-clear (Phase 2b Codex P1 fix).

#### Z.9 [OK] atomic_write helper

`core/atomic_write.py`: tempfile.mkstemp in same dir + fsync + os.replace,
cleanup on failure. Correct atomic-write pattern.

#### Z.10 [OK] paths.py is_frozen + CRYODAQ_ROOT precedence

Verified: env override > sys.frozen → exe parent > repo root walk.
`get_tsp_dir` returns inside _MEIPASS in frozen mode (read-only constants).

#### Z.11 [OK] logging_setup token redact filter handles tuple/dict args

Wraps `record.msg` AND `record.args` (both tuple and dict cases) in the
two-form regex (URL `bot{id}:secret` and bare `{id}:secret`). FD-leak fix
on idempotent setup is present (close before remove).

#### Z.12 [OK] ZMQCommandServer reply guarantee on every error path

Every `recv` is followed by a guaranteed `send`. Handler exception, JSON
decode error, serialization error, even CancelledError each take a
distinct branch and emit a reply. Phase 2a fix verified intact at
`zmq_bridge.py:282-342`.

---

## Cross-cutting observations

1. **`run_in_executor(None, ...)` still in two places.** Phase 2b only
   migrated VISA transports. Analytics (`cooldown_service.py`) and web
   (`server.py`) still use the default executor. The pattern should be
   audited engine-wide and a convention adopted ("always use a named
   ThreadPoolExecutor for blocking work in the engine process").

2. **HTML escaping missing in two places.** Both `telegram._format_message`
   and `web/server.py` dashboard JS interpolate operator-controlled
   strings without escaping. Adding `html.escape()` is a one-line fix per
   site.

3. **Synchronous I/O in async context** is a recurring pattern: 
   `experiment.py` (SQLite, json.dump, file copies),
   `reporting/generator.py` (Document.save, subprocess.run),
   `engine.py` various YAML loads. Each blocks the engine event loop for
   the duration of the I/O. The cumulative cost is hard to measure but
   high during finalize/start. Pattern: anything that does disk I/O from
   a coroutine should go through `asyncio.to_thread` unless it's already
   in a dedicated executor.

4. **`assert` statements in production paths.** 8 occurrences across
   `plugin_loader`, `interlock`, `safety_manager`, `web/server`,
   `housekeeping`, `notifications/telegram_commands`, `notifications/periodic_report`,
   `core/alarm`. All are "queue is not None" guards in async loops. Python
   `-O` mode strips asserts, so these become no-ops in production. The
   loops would then dereference `None`. Replace with explicit `if … is
   None: raise RuntimeError(...)` if the invariant matters, or rely on
   the AttributeError if it doesn't.

5. **No JSON Schema validation for any config.** Each YAML loader
   accesses keys directly. Operator typos go undetected until runtime
   raises a confusing KeyError or silently uses a default. The lab will
   eventually hit this — pydantic-based validation is cheap to add.

6. **Web server has zero authentication and zero rate limiting.** This
   is fine if it's bound to localhost only, but the deployment doc tells
   operators to bind 0.0.0.0:8080. Combined with G.1/G.4/G.6 this is the
   biggest exposure surface in the system. Recommend either localhost-only
   default OR a shared bearer token.

7. **GUI ↔ engine wall-clock synchronisation is approximate.** Phase 2c
   "Всё" preset uses GUI panel construction time as a proxy for engine
   start. There is no engine API to expose its actual wall-clock start.
   Same gap exists for "uptime" semantics — engine has monotonic uptime
   (process-local) but no wall-clock start_ts in any ZMQ response.

8. **Multiple `time.sleep()` calls in the launcher** block the Qt main
   thread (H.1). Engine event loop also has `time.sleep()` in
   `engine.py:1667` (during `_force_kill_existing` in `main()`, before
   the asyncio loop starts — that's fine). Pattern: any async-code module
   should use `await asyncio.sleep`; sync entry points should keep their
   sleeps but not on the GUI thread.

9. **Several long-running loops use `time.time()` for timing**, others
   use `time.monotonic()`. CooldownService is the most visible offender
   (A.7). The engine should establish a convention (monotonic for
   intervals, wall-clock only for timestamps that need to survive
   restart).

10. **No error budget for external systems.** LibreOffice (E.1), pyvisa,
    pyserial-asyncio, NI-VISA — all external dependencies that can hang.
    The system has timeouts in some places (Phase 2c added LakeShore IDN
    retry, Phase 2b added VISA executor isolation) but no consistent
    "every external call has a timeout" rule.

---

## Modules skipped / unable to audit

I did not perform deep reads on the following modules in this pass:

- `src/cryodaq/core/alarm.py` (618 lines) — only spot-checked the
  `acknowledge` and `start` methods. Phase 1 alarm engine works in
  parallel with alarm v2 and may have its own subset of A.1/A.2 issues.
- `src/cryodaq/core/channel_manager.py`, `channel_state.py`,
  `user_preferences.py` — small files, not in the high-risk path,
  skipped after grep showed no anti-patterns.
- `src/cryodaq/core/alarm_providers.py` — small adapter for ExperimentManager
  → AlarmEvaluator; not audited.
- `src/cryodaq/storage/csv_export.py`, `hdf5_export.py`, `xlsx_export.py`,
  `replay.py` — export utilities, only used during file-menu actions;
  skipped.
- `src/cryodaq/analytics/calibration.py` (1245 lines), `calibration_fitter.py`
  (391 lines), `steady_state.py`, `base_plugin.py` — only spot-checked
  the top 100 lines + key functions for D.2-style numerical issues.
- `src/cryodaq/reporting/sections.py` (713 lines), `data.py` (200 lines)
  — only checked the entry point `generator.py` for the report-pipeline
  blocking issue. Section-by-section rendering is heavy but not
  audited individually.
- `src/cryodaq/notifications/periodic_report.py` (502 lines) — checked
  imports + bot_token wrapping (Phase 2b OK), did not audit periodic
  send/matplotlib pipeline.
- Most of `engine.py` (1749 lines) — read `main()`, `_run_engine`
  startup, `_handle_gui_command` Keithley/safety/alarm branches, the
  `_alarm_v2_tick` task, `_watchdog`, but did not read every command
  handler.
- `gui/zmq_client.py` and `gui/main_window.py` were left alone per the
  scope rules (gui/widgets out, but these two are entry-point glue).
  They were already audited in Phase 1 + Phase 2c so no new pass here.
- `tsp/p_const.lua` — read in earlier phases, no new audit.

If the operator wants any of these modules covered in a follow-up pass,
the highest-value additional reads are: `alarm.py` (legacy alarm engine
might mirror alarm_v2 issues), `calibration.py` (numerical stability of
Chebyshev fit at low T), `reporting/sections.py` (each section is a
potential blocking IO site).
