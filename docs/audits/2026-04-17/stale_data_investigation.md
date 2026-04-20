# Stale Data Investigation

Date: 2026-04-17

Scope: cold forensics only. I did not run `cryodaq-engine`, `cryodaq-gui`, or any lab hardware. This note is based on repository inspection plus targeted external documentation review.

## 1. Ranked hypotheses

### 1. SQLite writer stall at the first explicit WAL checkpoint blocks publication globally — 42%

Most likely failure chain:

1. Every instrument poll reaches `Scheduler._process_readings()`.
2. The scheduler enforces persistence-first ordering and awaits `SQLiteWriter.write_immediate()` before any `DataBroker` or `SafetyBroker` publish.
3. The writer uses a single write executor thread.
4. The writer issues an explicit `PRAGMA wal_checkpoint(PASSIVE)` every 60 commits.
5. With the current poll rates, the engine reaches commit 60 at exactly 20.0 seconds:

```text
3 × LakeShore @ 2.0 s  => 3 × 0.5 = 1.5 commits/s
1 × Keithley  @ 1.0 s  => 1.0 commits/s
1 × VSP63D    @ 2.0 s  => 0.5 commits/s
Total                       3.0 commits/s

60 commits / 3.0 commits/s = 20.0 s
```

If that checkpoint or surrounding SQLite commit path stalls, all channels stop being published at once while both engine and GUI processes stay alive. That matches the operator report unusually well.

### 2. A hung PyVISA GPIB read deadlocks the shared `GPIB0` poll task during recovery — 26%

The three LakeShore 218S units share one GPIB bus and are intentionally serialized in one scheduler task. The GPIB transport also uses one dedicated worker thread per transport. If a PyVISA `read()` hangs in that worker, the scheduler times out at the coroutine level, but the underlying executor thread can remain occupied. After three errors the scheduler calls `await driver.disconnect()`, and `disconnect()` uses the same single-worker executor for `resource.close()`. That creates a credible deadlock shape: the read is still stuck, the close cannot run, and the shared `GPIB0` poll task stops making forward progress.

This is a strong hardware-specific candidate for the 24 temperature channels. It ranks below hypothesis 1 because it does not naturally explain Keithley and Thyracont freezing too, unless the operator meant "all temperature channels".

### 3. Disk-full / persistence-failure latch suppresses all downstream publication and requires manual acknowledgement — 14%

There is an explicit global latch for persistence failures. If SQLite detects disk-full, the writer sets `_disk_full=True`, signals `SafetyManager.on_persistence_failure()`, and the scheduler thereafter returns early from `_process_readings()` before publishing anything. Recovery is intentionally manual. This also produces "processes alive, data stale forever" behavior.

This ranks below hypothesis 1 because the timing is not naturally "~20 seconds" unless disk pressure happened to coincide with early startup.

### 4. GUI bridge stays "healthy" on heartbeats while data delivery is already dead — 11%

This is probably not the primary root cause, but it is a plausible reason the GUI never self-recovers once upstream data flow stops. The GUI restarts the ZMQ subprocess only when the subprocess dies or its heartbeats stop. It does not monitor actual reading throughput. So any upstream failure that stops readings but leaves the bridge subprocess alive will end as permanent stale UI until operator restart.

### 5. Startup-burst adaptive liveness math is not the main cause on the shipped v2 dashboard — 7%

The prompt's median-times-multiplier theory is real in legacy widgets, but it does not fit the current v2 shell path that renders the main dashboard cells and top bar:

- `SensorCell` stale logic is fixed at 30.0 s, not adaptive.
- `TopWatchBar` channel freshness is fixed at 30.0 s, not adaptive.
- The legacy adaptive widgets floor their timeout at 10.0 s, so a startup burst would yield a 10 s timeout, not ~20 s.

So the adaptive-timeout theory remains a valid legacy-widget footgun, but it does not match the active shipped dashboard path or the reported timing.

## 2. Evidence per hypothesis

### Hypothesis 1: SQLite writer stall at first WAL checkpoint

- Persistence-first gate: the scheduler writes first, and only after a successful write does it publish to brokers. If `write_immediate()` hangs or fails, downstream delivery stops for that poll cycle. See `src/cryodaq/core/scheduler.py:322-381`.
- Engine wiring confirms the scheduler is intentionally placed in front of ZMQ publication: `Scheduler(...)`, then `broker.subscribe("zmq_publisher")`, then `ZMQPublisher()`. See `src/cryodaq/engine.py:928-943`.
- The writer uses a single write executor thread: `ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")`. See `src/cryodaq/storage/sqlite_writer.py:143-152`.
- `write_immediate()` awaits that same single executor thread synchronously. See `src/cryodaq/storage/sqlite_writer.py:556-571`.
- Explicit WAL checkpoint cadence: `_checkpoint_counter += 1`, then `PRAGMA wal_checkpoint(PASSIVE)` when the counter reaches 60. See `src/cryodaq/storage/sqlite_writer.py:387-396`.
- Current poll rates are 2.0 s, 2.0 s, 2.0 s, 1.0 s, 2.0 s for the deployed instruments. See `config/instruments.yaml:2-53`.
- Math reconstruction: those rates produce exactly 3.0 commits/s, so the first explicit checkpoint lands at 20.0 s. That is the only exact 20-second boundary I found in the hot path.
- External context: SQLite documents that checkpoints initiated by `sqlite3_wal_checkpoint()` are PASSIVE checkpoints. Source: https://sqlite.org/wal.html
- External context: the repo itself now warns that SQLite versions before 3.51.3 are affected by a March 2026 WAL bug when multiple connections across threads/processes write or checkpoint "at the same instant". See `src/cryodaq/storage/sqlite_writer.py:97-119`.

Why this fits the symptom best:

- One stall point explains all channels going stale together.
- Engine process can remain alive because the event loop itself is not necessarily dead; it can simply be awaiting the blocked write path.
- GUI process can remain alive because it only consumes published readings; it does not know why they stopped.

### Hypothesis 2: Hung GPIB read plus deadlocked disconnect path

- Scheduler design: all instruments on the same GPIB bus are grouped into one sequential task specifically because NI GPIB-USB-HS does not tolerate concurrent access. See `src/cryodaq/core/scheduler.py:1-10` and `src/cryodaq/core/scheduler.py:184-200`.
- GPIB poll loop timeout is 3.0 s and reconnect interval is 30.0 s. See `src/cryodaq/core/scheduler.py:190-195`.
- After any poll exception, the loop increments per-device and per-bus error counts; after three consecutive device errors it executes `await driver.disconnect()`. See `src/cryodaq/core/scheduler.py:249-314`.
- `GPIBTransport` uses a dedicated single-worker executor per transport. See `src/cryodaq/drivers/transport/gpib.py:60-64` and `src/cryodaq/drivers/transport/gpib.py:102-110`.
- `query()` runs `_blocking_query()` inside that single-worker executor. See `src/cryodaq/drivers/transport/gpib.py:170-196`.
- `_blocking_query()` does `write -> sleep(100ms) -> read`, and on exception it attempts clear/drain, then re-raises. See `src/cryodaq/drivers/transport/gpib.py:260-295`.
- `close()` also runs `self._resource.close` inside that same single-worker executor. See `src/cryodaq/drivers/transport/gpib.py:134-153`.
- Therefore a hung executor-side `read()` can block the later `close()` forever because both need the same single worker.
- The three LakeShore drivers all live on `GPIB0`. See `config/instruments.yaml:2-42`.
- LakeShore per-channel fallback degrades gracefully for partial parse failures, so a mere bad response does not explain a total freeze; the more plausible GPIB failure is a transport-level hang. See `src/cryodaq/drivers/instruments/lakeshore_218s.py:157-243`.
- External context: PyVISA documents that resource I/O operations obey `timeout`, and when an operation exceeds it an exception is raised. Source: https://pyvisa.readthedocs.io/en/1.8/resources.html and https://pyvisa.readthedocs.io/en/1.15.0/introduction/communication.html

Why this ranks second, not first:

- It is a strong match for the three LakeShore devices.
- It is not a clean explanation for Keithley and Thyracont freezing too, because those are not on `GPIB0` and use separate poll loops.

### Hypothesis 3: Disk-full / persistence-failure latch

- Writer disk-full handling: on matching `sqlite3.OperationalError` text, the writer logs critical, sets `_disk_full=True`, signals persistence failure, and intentionally does not re-raise. See `src/cryodaq/storage/sqlite_writer.py:356-385`.
- Scheduler short-circuits the entire pipeline when `is_disk_full` is true. See `src/cryodaq/core/scheduler.py:327-335`.
- Even if free space later recovers, the code explicitly requires operator acknowledgement before polling resumes. See `src/cryodaq/storage/sqlite_writer.py:156-163`, `src/cryodaq/core/disk_monitor.py:99-115`, `src/cryodaq/engine.py:887-898`, and `src/cryodaq/core/safety_manager.py:1029-1044`.
- This yields exactly the observed shape: engine and GUI still running, data permanently stale, no automatic recovery.

Why it ranks below hypotheses 1 and 2:

- I found the latching mechanism, but not an in-repo reason it should trigger specifically at ~20 s.

### Hypothesis 4: GUI bridge remains healthy while data path is dead

- GUI bridge subprocess heartbeat every 5 s: `{"__type": "heartbeat"}` is emitted independently of reading flow. See `src/cryodaq/core/zmq_subprocess.py:145-154`.
- GUI health check only verifies subprocess alive plus recent heartbeat `< 30.0 s`; it does not require fresh data. See `src/cryodaq/gui/zmq_client.py:143-151`.
- GUI restart logic in `_tick()` only reacts to failed `is_healthy()`. See `src/cryodaq/gui/app.py:274-285`.
- The bridge subprocess silently drops malformed readings with `except Exception: pass  # skip malformed`. See `src/cryodaq/core/zmq_subprocess.py:98-114`.
- The GUI drains the multiprocessing queue non-blockingly and only logs processing errors; it has no receive-thread watchdog tied to reading age. See `src/cryodaq/gui/zmq_client.py:121-141`.
- External context: the repo does not set explicit HWM values on the engine PUB or bridge SUB sockets. See `src/cryodaq/core/zmq_bridge.py:143-153` and `src/cryodaq/core/zmq_subprocess.py:72-77`.
- External context: ZeroMQ documents default SNDHWM/RCVHWM as 1000 messages, and for PUB/SUB sockets HWM overflow drops rather than blocks. Sources: https://api.zeromq.org/3-3:zmq-setsockopt and https://api.zeromq.org/2-2:zmq-socket

Interpretation:

- ZMQ overflow or malformed-message loss is a weak primary-cause candidate.
- The stronger GUI-side finding is that once upstream data dies, the GUI has no watchdog that distinguishes "heartbeat only" from "actual readings still arriving".

### Hypothesis 5: adaptive liveness bootstrap bug is legacy-only here

- Legacy adaptive liveness still exists in `InstrumentStatusPanel`: timeout is `max(10.0, median_interval * 5.0)` after at least 3 intervals; before that it is 300.0 s. See `src/cryodaq/gui/widgets/instrument_status.py:38-42` and `src/cryodaq/gui/widgets/instrument_status.py:104-128`.
- Legacy `OverviewPanel` uses similar logic: `max(10.0, median * 5.0)`, otherwise 30.0 s. See `src/cryodaq/gui/widgets/overview_panel.py:455-468`.
- The active v2 dashboard `SensorCell` uses fixed `_STALE_THRESHOLD_S = 30.0`. See `src/cryodaq/gui/dashboard/sensor_cell.py:31` and `src/cryodaq/gui/dashboard/sensor_cell.py:221-249`.
- The active `TopWatchBar` uses fixed `_STALE_TIMEOUT_S = 30.0`. See `src/cryodaq/gui/shell/top_watch_bar.py:27` and `src/cryodaq/gui/shell/top_watch_bar.py:471-505`.
- `MainWindowV2` routes readings into the v2 dashboard/top bar path. See `src/cryodaq/gui/shell/main_window_v2.py:257-309`.

Math:

- If startup readings arrive every 0.1 s, then `median * 5 = 0.5 s`.
- Both legacy implementations clamp that upward to 10.0 s.
- Therefore adaptive bootstrap cannot explain a ~20 s threshold, and it cannot explain the main v2 dashboard at all.

## 3. What would confirm each hypothesis

### Hypothesis 1

- Engine stdout/stderr shows one of:
  - `CRITICAL: Ошибка записи ... данные НЕ отправлены подписчикам`
  - `Periodic WAL checkpoint failed`
  - `PERSISTENCE FAILURE: ...`
- The SQLite DB or WAL file stops growing at the same moment readings disappear from the GUI.
- A thread dump shows the `sqlite_write` worker blocked inside `conn.commit()` or `PRAGMA wal_checkpoint(PASSIVE)`.
- GUI continues receiving bridge heartbeats but no readings.

### Hypothesis 2

- Engine logs repeated lines such as:
  - `Ошибка опроса 'LS218_*'`
  - `'LS218_*': 3+ ошибок, disconnect + skip`
  - `GPIB bus GPIB0: ... resetting ResourceManager`
- A Python thread dump shows a `visa_gpib_*` worker stuck inside PyVISA `read()` while the scheduler task is awaiting `driver.disconnect()`.
- Keithley and Thyracont continue updating while all 24 temperature channels freeze. That pattern would strongly favor the GPIB hypothesis over the global SQLite hypothesis.

### Hypothesis 3

- Engine logs:
  - `DISK FULL detected in SQLite write`
  - `PERSISTENCE FAILURE: disk full: ...`
- `system/disk_free_gb` is near the configured critical threshold.
- Safety state becomes fault-latched and remains so until `acknowledge_fault`.

### Hypothesis 4

- GUI-side logs show bridge heartbeat warnings absent, bridge subprocess still alive, but no new readings dispatched.
- Capturing the bridge queues shows heartbeat control messages still arriving every 5 s but no reading payloads.
- Restarting only the GUI does not help, but restarting the engine does. That would indicate the GUI bridge is merely reflecting upstream silence.

### Hypothesis 5

- Reproduction happens only in legacy panels that still use adaptive timeout.
- v2 `SensorCell` widgets stay healthy for 30 s after the last reading, while a legacy `InstrumentStatusPanel` or `OverviewPanel` shows stale much earlier.

## 4. Mock-mode reproduction candidates

| Hypothesis | Reproducible with `cryodaq-engine --mock` on macOS? | Why |
|---|---|---|
| 1. SQLite writer stall at first WAL checkpoint | Yes, partially | Hardware is irrelevant here. A mock run with concurrent DB readers or heavy WAL activity can exercise the same persistence-first choke point and the same commit-60 checkpoint timing. |
| 2. Hung GPIB read / deadlocked disconnect | No | Mock mode bypasses the real PyVISA + linux GPIB stack, which is the entire failure surface. |
| 3. Disk-full / persistence-failure latch | Yes | This path is hardware-independent. A constrained or unwritable data directory would exercise the same latch logic. |
| 4. GUI bridge healthy-but-no-data | Yes, partially | Any way of pausing upstream data while leaving the bridge subprocess alive should reproduce the no-auto-restart behavior. |
| 5. Legacy adaptive liveness bootstrap | Yes | Pure GUI timing logic; easy to reproduce with synthetic fast-start then slow-cadence readings, but only on legacy widgets. |

Best mock candidate: hypothesis 1, because it is independent of lab hardware and matches the 20-second timing exactly.

## 5. Questions for next lab session

1. When the next failure happens, do Keithley and pressure freeze too, or only the 24 temperature channels?
2. What are the last 50-100 lines of engine stdout/stderr around the 15-30 second window after startup?
3. Does the SQLite DB or `-wal` file stop growing at the moment the GUI stops updating?
4. Is there any `Periodic WAL checkpoint failed`, `CRITICAL: Ошибка записи`, `PERSISTENCE FAILURE`, or `DISK FULL` log line?
5. Are there repeated `Ошибка опроса 'LS218_*'` or `GPIB bus GPIB0` recovery messages before the freeze?
6. Does the safety state fault-latch about 10 seconds after data stops, which would indicate the engine truly stopped publishing fresh critical channels?
7. If only the GUI is restarted while the engine keeps running, do fresh readings return immediately or stay stale?
8. What exact SQLite version is bundled on the Ubuntu lab PC (`python -c "import sqlite3; print(sqlite3.sqlite_version)"`)?
9. Is the Ubuntu lab PC using the system `libsqlite3` from 22.04, or a bundled newer SQLite in the CryoDAQ build?
10. Can a Python thread dump be captured from the running engine during the freeze to see whether `sqlite_write` or `visa_gpib_*` threads are blocked?
