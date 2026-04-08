# CryoDAQ Deep Audit — Post Phase 2c (Codex run, overnight)

**Commit:** 1698150  
**Date:** 2026-04-09  
**Agent:** Codex CLI (gpt-5.4 high reasoning)  
**Runtime:** 1h 38m  
**Scope:** core + drivers + storage + analytics + reporting + notifications + web + engine + launcher + frozen_main + paths + logging_setup + config + build + tsp  
**Modules audited:** 63 scoped package modules (19.1 KLOC) + 7 entry/wiring modules (3.3 KLOC) + 6 root plugins + 13 config files + 4 build scripts + lock/spec/TSP  
**Web lookups performed:** 24 searches, 18 fetches

## Summary

- CRITICAL: 1 finding
- HIGH: 12 findings
- MEDIUM: 8 findings
- LOW: 2 findings
- OK (verified correct): 8 items

Top concerns:

1. The Keithley fail-safe still depends on the host process. The bundled TSP watchdog exists, but the production driver explicitly does not upload or run it, so a launcher/engine crash can leave live sourcing active until a human or restart intervenes.
2. Deployment assumptions are still brittle. The design writes `data/`, `logs/`, and executable plugins next to the frozen executable, assumes a writable local filesystem, and relies on WAL semantics that fail on network shares and on Ubuntu 22.04's bundled SQLite line.
3. Several persistence/state files still bypass the repo's own atomic-write helper. For experiment metadata and calibration indexes, a power loss or process kill can leave unreadable JSON/YAML sidecars even while the main SQLite path is WAL-backed.
4. The monitoring surface is still easy to abuse operationally: the web dashboard is unauthenticated, documented for `0.0.0.0`, and exposes unbounded history/log queries; the Telegram command bot replays stale pending updates after restart.

## Methodology notes

This pass was read-first, not grep-first. I fully read the scoped modules, then validated the non-trivial patterns against primary sources: Python stdlib docs, SQLite docs, PyInstaller docs, Qt docs, aiohttp docs, Telegram Bot API docs, libzmq docs, pip docs, and NVD/GHSA entries where relevant.

The codebase reads as careful overall: the safety core is materially better than a typical lab rewrite, and several previously common failure modes are now defended explicitly. The residual issues are mostly at the boundaries: packaging, runtime filesystem assumptions, cross-process behavior, hot-reload trust, and “timeout means cancel” assumptions around blocking I/O. Those are exactly the problems that survive multiple ordinary code-review passes and then bite during long unattended runs.

## Dependency CVE review

I spot-checked the pinned runtime dependencies most relevant to CryoDAQ's attack and failure surface against NVD and vendor advisories. NVD package matching is imperfect, so “clean” here means “no pinned-version-matching advisory surfaced during this pass”, not a mathematical proof of absence.

| Package | Pinned version | CVE status | Notes |
|---------|----------------|------------|-------|
| aiohttp | 3.13.5 | clean at pinned version | NVD entries [CVE-2024-30251](https://nvd.nist.gov/vuln/detail/CVE-2024-30251) and [CVE-2025-69228](https://nvd.nist.gov/vuln/detail/CVE-2025-69228) affect older aiohttp releases; 3.13.5 is newer than both fixed versions. |
| pyinstaller | 6.19.0 | clean for reviewed issue | NVD [CVE-2025-59042](https://nvd.nist.gov/vuln/detail/CVE-2025-59042/change-record?changeRecordedOn=09%2F09%2F2025T19%3A15%3A37.403-0400) affects `< 6.0.0`; pinned version is beyond the affected range. |
| pyzmq | 26.4.0 | no matching advisory surfaced | Searched NVD/package advisories; no pinned-version match surfaced during this pass. |
| pyside6 | 6.11.0 | no matching advisory surfaced | Searched NVD/package advisories; no pinned-version match surfaced during this pass. |
| fastapi | 0.135.3 | no matching advisory surfaced | No direct FastAPI package advisory matching this version surfaced during this pass. |
| starlette | 1.0.0 | no matching advisory surfaced | No direct Starlette pinned-version advisory surfaced during this pass. |
| pyvisa | 1.16.2 | no matching advisory surfaced | No direct pyvisa pinned-version advisory surfaced during this pass. |
| pyserial | 3.5 | no matching advisory surfaced | No direct pyserial pinned-version advisory surfaced during this pass. |
| pyyaml | 6.0.3 | no matching pinned-version CVE surfaced | Older PyYAML security history is mainly around unsafe loaders; this repo consistently uses `yaml.safe_load`. |
| uvicorn | 0.44.0 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |
| numpy | 2.4.4 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |
| scipy | 1.17.1 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |
| matplotlib | 3.10.8 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |
| openpyxl | 3.1.5 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |
| python-docx | 1.2.0 | no matching advisory surfaced | No pinned-version match surfaced during this pass. |

Reviewed sources included:

- <https://nvd.nist.gov/vuln/detail/CVE-2024-30251>
- <https://nvd.nist.gov/vuln/detail/CVE-2025-69228>
- <https://nvd.nist.gov/vuln/detail/CVE-2025-59042/change-record?changeRecordedOn=09%2F09%2F2025T19%3A15%3A37.403-0400>

## Findings

### A. Core (core/)

#### A.1 [HIGH] Poll timeouts do not stop already-running executor work, so one hung instrument call can permanently brick its transport lane

**Location:** `src/cryodaq/core/scheduler.py:127`, `src/cryodaq/core/scheduler.py:198`, `src/cryodaq/drivers/base.py:84`, `src/cryodaq/drivers/transport/gpib.py:59`, `src/cryodaq/drivers/transport/usbtmc.py:39`

**Description:** Scheduler timeouts are enforced with `asyncio.wait_for(driver.safe_read(), timeout=...)`, but the actual VISA work runs in single-worker `ThreadPoolExecutor`s. Cancelling the awaiting coroutine does not stop a threadpool task that is already running. Once a blocking PyVISA call wedges, later reconnect/read/write work for that instrument queues behind the stuck worker forever.

**Impact:** A USB/GPIB glitch can escalate from “one timed out poll” to “instrument remains dead until full process restart”. In practice that means a thermometer or SMU can disappear for the rest of the run even though the scheduler appears to keep retrying.

**Evidence:**

```python
# scheduler.py
readings = await asyncio.wait_for(driver.safe_read(), timeout=cfg.read_timeout_s)

# base.py
async def safe_read(self) -> list[Reading]:
    async with self._lock:
        return await self.read_channels()

# gpib.py / usbtmc.py
self._executor = ThreadPoolExecutor(max_workers=1, ...)
await loop.run_in_executor(self._get_executor(), self._blocking_query, ...)
```

Python's `concurrent.futures` docs are explicit that `Future.cancel()` does not stop a call that is already running: “If the call is currently being executed ... the method will return `False`” and `running()` means the call “cannot be cancelled.”  
Source: <https://docs.python.org/3/library/concurrent.futures.html>

**Web research consulted:**

- <https://docs.python.org/3/library/concurrent.futures.html>
- <https://docs.python.org/3.12/library/asyncio-task.html>

**Proposed fix:** Treat transport timeouts as cooperative, not preemptive. Move hard timeouts into the transport/backend layer where possible, add connection-level abort/reset paths that replace the executor and underlying session after timeout, and avoid single-worker executors becoming permanent tombstones for stuck I/O.

---

#### A.2 [HIGH] Experiment state and metadata sidecars are still written non-atomically

**Location:** `src/cryodaq/core/experiment.py:874`, `src/cryodaq/core/experiment.py:1054`, `src/cryodaq/core/experiment.py:1149`, `src/cryodaq/core/experiment.py:1355`

**Description:** `ExperimentManager` writes operational JSON state, experiment metadata, phase history, and summary metadata directly with `Path.write_text(...)`. The repo already has `core/atomic_write.py`, but these files bypass it.

**Impact:** A power cut, process kill, or disk hiccup during write can leave the JSON truncated or empty. That does not corrupt the main SQLite data, but it can orphan the active experiment, lose phase history, or break report/archive reconstruction right when operators need post-mortem context.

**Evidence:**

```python
self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
summary_path.write_text(json.dumps(summary_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
```

Python documents `os.replace()` as atomic on success, which is the standard pattern for crash-safe sidecar updates.  
Source: <https://docs.python.org/3/library/os.html>

**Web research consulted:**

- <https://docs.python.org/3/library/os.html>

**Proposed fix:** Route all JSON/YAML sidecar writes through the existing atomic write helper backed by temp file + `os.replace()`. For safety-critical state, also `fsync` the temp file before replace.

---

#### A.3 [LOW] ZMQ bind retry blocks the event loop with `time.sleep()` during startup/rebind

**Location:** `src/cryodaq/core/zmq_bridge.py:38`

**Description:** `_bind_with_retry()` performs exponential backoff with blocking `time.sleep()` even though it is invoked from async component startup.

**Impact:** On port-collision or TIME_WAIT recovery, startup blocks the engine loop outright instead of yielding. This is not a data-loss bug, but it turns a recoverable bind delay into a whole-loop stall at the worst possible time: restart after crash.

**Evidence:**

```python
def _bind_with_retry(socket: Any, address: str) -> None:
    ...
    time.sleep(delay)
```

**Web research consulted:**

- <https://libzmq.readthedocs.io/en/latest/zmq_setsockopt.html>

**Proposed fix:** Make bind retry async and use `await asyncio.sleep(...)`, or move the whole bind/retry sequence into a clearly isolated startup thread if synchronous behavior is intended.

### B. Drivers (drivers/)

No new driver-only defects stood out beyond the cross-cutting timeout/executor issue in A.1 and the Keithley fail-safe issue in M.1. The strongest driver observations are in the verified-correct section.

### C. Storage (storage/)

#### C.1 [HIGH] Current Ubuntu 22.04 deployment target is still in the SQLite WAL-reset danger range

**Location:** `src/cryodaq/storage/sqlite_writer.py:97`

**Description:** The code correctly warns about the March 2026 WAL-reset bug, but the stated target deployment (`Ubuntu 22.04`) is exactly the environment most likely to ship an affected system SQLite unless you bundle or rebuild it.

**Impact:** This is a real deployment blocker, not a theoretical note. CryoDAQ uses concurrent WAL readers/writers across engine, web, reporting, and archive flows; running on an affected SQLite build reintroduces a corruption class in the primary persistence path.

**Evidence:**

```python
if (3, 7, 0) <= version < (3, 51, 3):
    logger.warning(
        "SQLite ... is affected by the March 2026 WAL-reset corruption bug ..."
    )
```

SQLite's WAL documentation now includes a dedicated “WAL-Reset Bug” section.  
Source: <https://www.sqlite.org/wal.html>

**Web research consulted:**

- <https://www.sqlite.org/wal.html>

**Proposed fix:** Treat SQLite version as a startup gate, not just a warning, for production/frozen builds. Bundle a known-safe libsqlite3 or explicitly fail fast on unsupported versions in deployment mode.

---

#### C.2 [HIGH] The code assumes WAL was enabled but never checks that SQLite actually returned `wal`

**Location:** `src/cryodaq/storage/sqlite_writer.py:248`, `src/cryodaq/core/experiment.py:983`

**Description:** Both the main writer and experiment metadata DB path execute `PRAGMA journal_mode=WAL;` and proceed without checking the returned mode string.

**Impact:** If the database is on an unsupported VFS or filesystem, or WAL cannot be activated for some other reason, CryoDAQ silently falls back to previous journaling mode while still assuming WAL concurrency semantics. That turns cross-process reads, web history, and reporting into surprise lock contention.

**Evidence:**

```python
conn.execute("PRAGMA journal_mode=WAL;")
```

SQLite documents that the pragma returns the actual new journal mode and stays unchanged on failure.  
Source: <https://www.sqlite.org/wal.html>

**Web research consulted:**

- <https://www.sqlite.org/wal.html>

**Proposed fix:** Read the pragma result and assert it is exactly `wal`. If not, log a deployment-blocking error that includes the DB path and filesystem assumptions.

---

#### C.3 [MEDIUM] Default `synchronous=NORMAL` still accepts recent data loss on power failure

**Location:** `src/cryodaq/storage/sqlite_writer.py:249`

**Description:** The writer defaults to `PRAGMA synchronous=NORMAL`, with a comment that production must be on a UPS or use `CRYODAQ_SQLITE_SYNC=FULL`.

**Impact:** On hard power loss, the most recent committed measurements can roll back. For lab DAQ this may be an acceptable tradeoff only if it is enforced by deployment policy; right now it is an environment assumption, not a guarded invariant.

**Evidence:**

```python
sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
conn.execute(f"PRAGMA synchronous={sync_mode};")
```

SQLite states that with WAL mode and `synchronous=NORMAL`, commit-time sync is omitted and durability is sacrificed on power loss.  
Source: <https://www.sqlite.org/wal.html>

**Web research consulted:**

- <https://www.sqlite.org/wal.html>

**Proposed fix:** Promote the UPS requirement into explicit deployment validation, or default production bundles to `FULL` and make `NORMAL` an opt-in for benchmarked environments.

### D. Analytics (analytics/)

#### D.1 [HIGH] Calibration index writes are non-atomic despite being the source of truth for runtime curve selection

**Location:** `src/cryodaq/analytics/calibration.py:731`

**Description:** `CalibrationStore._write_index()` writes the YAML index directly with `write_text(...)`.

**Impact:** A torn write can leave the curve catalog unreadable or partially updated, which in turn breaks runtime calibration assignment resolution for LakeShore channels. That does not destroy raw data, but it can silently revert the system to wrong conversion behavior after restart.

**Evidence:**

```python
self._index_path.write_text(
    yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)
```

**Web research consulted:**

- <https://docs.python.org/3/library/os.html>

**Proposed fix:** Use atomic temp-file replacement for the calibration index and any other runtime-editable YAML state. Treat calibration sidecars with the same durability discipline as experiment metadata.

---

#### D.2 [MEDIUM] `CooldownService` mixes sample time and wall clock, so NTP jumps or replayed timestamps skew ETA

**Location:** `src/cryodaq/analytics/cooldown_service.py:309`, `src/cryodaq/analytics/cooldown_service.py:352`

**Description:** The service stores `_cooldown_wall_start` from `reading.timestamp`, uses that same sample time for buffering, then later computes elapsed time using `time.time()`.

**Impact:** If wall clock jumps, replayed data is ingested, or producer timestamps lag real time, the model sees inconsistent elapsed time. The result is wrong cooldown ETA and potentially bad operator decisions during long cryogenic runs.

**Evidence:**

```python
if self._cooldown_wall_start is None:
    self._cooldown_wall_start = reading_ts

t_hours = (reading_ts - self._cooldown_wall_start) / 3600.0
...
t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
```

**Web research consulted:**

- <https://docs.python.org/3/library/time.html>

**Proposed fix:** Keep one timebase. Either compute everything from sample timestamps or use monotonic wall time exclusively for live-only models; do not mix them in the same state machine.

---

#### D.3 [MEDIUM] The shipped `cooldown_estimator` plugin repeats the same wall-clock bug at plugin level

**Location:** `plugins/cooldown_estimator.py:173`, `plugins/cooldown_estimator.py:288`

**Description:** The plugin trims its buffer and computes `t_now_from_t0` from `datetime.now(timezone.utc).timestamp()` instead of the newest sample timestamp.

**Impact:** During telemetry backlog, replay, clock correction, or simply stale batch delivery, the ETA can jump or go negative even if the temperature history itself is clean.

**Evidence:**

```python
t_now = datetime.now(timezone.utc).timestamp()
t_cutoff = t_now - self._fit_window_s
...
t_now_from_t0 = t_now - t0
```

**Web research consulted:**

- <https://docs.python.org/3/library/datetime.html>

**Proposed fix:** Derive “now” from the last buffered sample. If live wall time is needed for UI freshness, keep it in separate metadata and do not feed it into the fit itself.

### E. Reporting (reporting/)

#### E.1 [MEDIUM] Reporting and export paths still load whole datasets into memory

**Location:** `src/cryodaq/reporting/data.py:127`, `src/cryodaq/reporting/sections.py:168`, `src/cryodaq/storage/hdf5_export.py:113`, `src/cryodaq/storage/xlsx_export.py:95`

**Description:** Historical report generation uses `fetchall()` and whole-file CSV reads; HDF5/XLSX export similarly materializes large result sets before writing.

**Impact:** Large experiments can turn report/export into a RAM spike or process kill instead of a slow-but-bounded operation. On a lab PC this is mostly an ops failure, but it can happen exactly after a long cooldown when the archive matters most.

**Evidence:**

```python
for row in conn.execute(query, (...)).fetchall():
    rows.append(...)

rows = list(reader)
...
rows = cursor.fetchall()
...
all_rows.extend(self._query_db(...))
```

**Web research consulted:**

- <https://www.sqlite.org/wal.html>

**Proposed fix:** Stream DB rows and CSV previews incrementally. For report sections that only show summaries or first N rows, do not load the full table just to discard most of it.

---

#### E.2 [MEDIUM] LibreOffice PDF conversion has no timeout and ignores conversion failure details

**Location:** `src/cryodaq/reporting/generator.py:207`

**Description:** `_try_convert_pdf()` launches `soffice --headless --convert-to pdf` with `check=False`, no timeout, and only a post-hoc existence check.

**Impact:** If `soffice` hangs, report generation stalls indefinitely in the worker thread. If conversion fails, the code returns `None` without structured diagnostics, which makes deployment debugging much harder.

**Evidence:**

```python
subprocess.run(
    [soffice, "--headless", "--convert-to", "pdf", str(source_docx_path), "--outdir", str(output_dir)],
    check=False,
    capture_output=True,
)
```

**Web research consulted:**

- <https://docs.python.org/3/library/subprocess.html>

**Proposed fix:** Add a hard timeout, inspect `returncode`, and log stderr/stdout on failure. If PDF conversion is optional, degrade explicitly instead of silently.

---

#### E.3 [MEDIUM] Frozen builds launch external `soffice` without PyInstaller environment sanitization

**Location:** `src/cryodaq/reporting/generator.py:212`

**Description:** In a PyInstaller-frozen app, external system programs may inherit modified library-search state from the bundle. `ReportGenerator` launches system LibreOffice without passing a sanitized environment.

**Impact:** DOCX→PDF conversion can fail only in frozen builds, only on some target machines, and only after deployment. That is exactly the kind of packaging-only failure that slips past developer testing and appears during report generation on the lab PC.

**Evidence:** PyInstaller documents that subprocesses launched from frozen apps may load bundled libraries instead of system ones and should be started with a sanitized environment. The current code does not pass `env=` at all.

**Web research consulted:**

- <https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html>
- <https://pyinstaller.org/en/stable/runtime-information.html>

**Proposed fix:** Build an OS-specific sanitized environment before invoking external programs from a frozen app, especially on Linux (`LD_LIBRARY_PATH`) and Windows (`SetDllDirectoryW(NULL)`).

### F. Notifications (notifications/)

#### F.1 [HIGH] Telegram command bot replays stale pending commands after restart

**Location:** `src/cryodaq/notifications/telegram_commands.py:113`, `src/cryodaq/notifications/telegram_commands.py:208`

**Description:** The bot starts with `_last_update_id = 0` on every process start and does not persist or explicitly drop pending Telegram updates.

**Impact:** A `/phase` or `/log` message sent during downtime can be executed later, after restart, when it is no longer contextually valid. In a safety-sensitive operator workflow, stale remote commands are worse than rejected ones.

**Evidence:**

```python
self._last_update_id = 0
...
params: dict[str, Any] = {"timeout": 5}
if self._last_update_id:
    params["offset"] = self._last_update_id + 1
```

Telegram's Bot API states that by default `getUpdates` returns the “earliest unconfirmed update”, and an update is confirmed only when `getUpdates` is called with an offset higher than its `update_id`.  
Source: <https://core.telegram.org/bots/api>

The Telegram Bots FAQ makes the same point: long polling returns the earliest unconfirmed updates until offset advances.  
Source: <https://core.telegram.org/bots/faq>

**Web research consulted:**

- <https://core.telegram.org/bots/api>
- <https://core.telegram.org/bots/faq>

**Proposed fix:** Persist the last processed `update_id`, or intentionally discard pending updates on startup before enabling command handling. For control commands, I would default to “drop stale backlog”.

### G. Web Dashboard (web/)

#### G.1 [HIGH] The dashboard is unauthenticated and the module itself documents `--host 0.0.0.0`

**Location:** `src/cryodaq/web/server.py:11`, `src/cryodaq/web/server.py:330`

**Description:** `/status`, `/api/status`, `/api/log`, `/history`, and `/ws` expose live measurements, alarms, experiment status, and operator log content with no authentication or authorization layer. The module docstring shows the service bound on all interfaces.

**Impact:** Anyone on the reachable lab network can observe live experiment state and operator notes, and can also trigger expensive history queries. This is not a write-capable RCE surface, but it is an avoidable remote information/availability surface.

**Evidence:**

```python
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
...
@application.get("/api/status")
@application.get("/api/log")
@application.get("/history")
@application.websocket("/ws")
```

**Web research consulted:**

- <https://fastapi.tiangolo.com/es/advanced/events/>

**Proposed fix:** Treat the dashboard as privileged. Bind to loopback by default, add a minimal auth layer if remote access is required, and make “expose on LAN” an explicit deployment choice rather than the first documented startup path.

---

#### G.2 [HIGH] Client-controlled history/log query size is effectively unbounded

**Location:** `src/cryodaq/web/server.py:365`, `src/cryodaq/web/server.py:376`, `src/cryodaq/web/server.py:247`

**Description:** `/api/log?limit=` forwards user input directly to engine log retrieval, and `/history?minutes=` forwards directly to `_query_history(minutes)` which scans all daily DBs and returns all matching points.

**Impact:** A single client can request massive history windows or huge log limits and force CPU, RAM, and threadpool consumption on the monitoring service. Because `_query_history()` groups the full response in memory, this is an easy operational DoS.

**Evidence:**

```python
result = await _async_engine_command({"cmd": "log_get", "limit": limit})
...
channels = await loop.run_in_executor(None, _query_history, minutes)
...
for db_path in sorted(_DATA_DIR.glob("data_????-??-??.db")):
    rows = conn.execute(...).fetchall()
```

**Web research consulted:**

- <https://www.sqlite.org/wal.html>

**Proposed fix:** Put hard validation bounds on query size at the API boundary, paginate history, and stream or downsample rather than returning arbitrarily large raw arrays.

### H. Plugins (plugins/)

#### H.1 [HIGH] Writable plugin directory is executable code loaded in-process with no trust boundary

**Location:** `src/cryodaq/analytics/plugin_loader.py:146`, `src/cryodaq/analytics/plugin_loader.py:303`, `src/cryodaq/paths.py:66`

**Description:** The frozen deployment path makes `plugins/` writable next to the executable, and the analytics pipeline imports any `*.py` from that directory directly into the main process.

**Impact:** Any local actor or malware with write access to the bundle directory can execute arbitrary Python inside the CryoDAQ process. In a safety-critical lab system, this is the single largest local code-execution surface after the interpreter itself.

**Evidence:**

```python
spec = importlib.util.spec_from_file_location(f"cryodaq_plugin_{plugin_id}", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
...
for path in self._plugins_dir.glob("*.py")
```

**Web research consulted:**

- <https://docs.python.org/3/library/importlib.html>
- <https://pyinstaller.org/en/stable/runtime-information.html>

**Proposed fix:** Separate “operator data” from “executable extensions”. For deployment builds, either disable runtime plugin loading entirely or require signed/whitelisted plugins loaded from a read-only trusted location.

---

#### H.2 [MEDIUM] Hot reload is not transactional: a bad edit unloads the last known-good plugin first

**Location:** `src/cryodaq/analytics/plugin_loader.py:316`

**Description:** On file modification, the watcher unconditionally unloads the current plugin and then tries to import the replacement. If the replacement file is partially written, syntactically broken, or mismatched with its sidecar config, the old plugin is already gone.

**Impact:** Analytics derived metrics can disappear silently during live operation because of an editor save, partial copy, or operator mistake in the plugin directory. The pipeline keeps running, but the metric is simply absent until the next good edit.

**Evidence:**

```python
self._unload_plugin(Path(filename).stem)
self._load_plugin(self._plugins_dir / filename)
```

**Web research consulted:**

- <https://docs.python.org/3/library/os.html>

**Proposed fix:** Load and validate the replacement into a temporary module/object first, then swap it in only after successful import and configuration. Pair that with atomic file replacement on plugin deployment.

### I. Engine & Launcher & Frozen Entry

#### I.1 [LOW] Launcher swallows event-loop tick exceptions completely

**Location:** `src/cryodaq/launcher.py:741`

**Description:** The Qt-driven asyncio pump catches any exception from `_tick_async()` and drops it silently.

**Impact:** If launcher-side async machinery ever does fail at the top level, the user gets a degraded UI/bridge state with no visible cause. This is not the main safety path, but it is the wrong failure mode for overnight operation.

**Evidence:**

```python
def _tick_async(self) -> None:
    try:
        self._loop.run_until_complete(_tick_coro())
    except Exception:
        pass
```

**Web research consulted:**

- <https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html>

**Proposed fix:** At minimum log the exception once with backoff. If the custom loop pump is kept, failures should be observable in `launcher.log`.

### J. Paths & Logging

#### J.1 [HIGH] The runtime root is assumed to be a writable local directory next to the frozen executable

**Location:** `src/cryodaq/paths.py:37`, `src/cryodaq/paths.py:52`, `src/cryodaq/paths.py:59`, `src/cryodaq/web/server.py:81`

**Description:** In frozen mode, CryoDAQ resolves the runtime root to `Path(sys.executable).parent` and creates `data/` and `logs/` there. This assumes the install directory is writable and on a local filesystem.

**Impact:** The bundle breaks under common deployment locations such as `Program Files`, `/opt`, or a read-only administrative install. It also nudges operators toward “put the whole bundle on a network share” patterns that SQLite WAL explicitly does not support.

**Evidence:**

```python
if is_frozen():
    return Path(sys.executable).resolve().parent
...
d = get_project_root() / "data"
d.mkdir(parents=True, exist_ok=True)
...
_DATA_DIR = get_data_dir()
```

PyInstaller documents `sys.executable` as the actual launched frozen executable path. SQLite documents that “WAL does not work over a network filesystem” and requires shared memory on the same host.  
Sources: <https://pyinstaller.org/en/stable/runtime-information.html>, <https://www.sqlite.org/wal.html>

**Web research consulted:**

- <https://pyinstaller.org/en/stable/runtime-information.html>
- <https://www.sqlite.org/wal.html>

**Proposed fix:** Decouple writable runtime state from the bundle directory. On Windows use a per-machine or per-user application data location; on Linux use a configurable data root under a vetted local path, and reject network-share DB paths in production mode.

### K. Build & Packaging (build_scripts/, pyproject.toml, requirements-lock.txt)

#### K.1 [HIGH] Build scripts silently fall back from hash-checked installs to unhashed installs

**Location:** `build_scripts/build.sh:9`, `build_scripts/build.bat:5`

**Description:** Both build scripts try `pip install --require-hashes -r requirements-lock.txt` and then silently fall back to plain `pip install -r requirements-lock.txt` on any error.

**Impact:** A lockfile/build integrity failure degrades into an unchecked install instead of stopping the build. That defeats the purpose of `--require-hashes` and weakens the exact dependency review you are doing before deployment.

**Evidence:**

```bash
pip install --require-hashes -r requirements-lock.txt 2>/dev/null \
    || pip install -r requirements-lock.txt
```

pip's secure-install docs call hash-checking “all-or-nothing” and position `--require-hashes` as protection against tampering and network issues.  
Source: <https://pip.pypa.io/en/stable/topics/secure-installs/>

**Web research consulted:**

- <https://pip.pypa.io/en/stable/topics/secure-installs/>

**Proposed fix:** Fail the build if hash-checking fails. If the lockfile intentionally omits hashes for some platform artifacts, fix the lock generation process instead of bypassing enforcement at build time.

---

#### K.2 [HIGH] `post_build.py` copies plugin code but forgets plugin YAML sidecars

**Location:** `build_scripts/post_build.py:53`, `src/cryodaq/analytics/plugin_loader.py:186`

**Description:** The post-build step seeds `dist/CryoDAQ/plugins/` with `*.py` files only. The plugin loader separately looks for `path.with_suffix(".yaml")` and applies that config if present.

**Impact:** Example/shipped plugins in frozen builds run with missing configuration or altered defaults. That is a deployment-only behavior change, which makes it especially hard to catch before the lab PC run.

**Evidence:**

```python
# post_build.py
for plugin in plugins_src.glob("*.py"):
    shutil.copy2(plugin, dist_dir / "plugins" / plugin.name)

# plugin_loader.py
config_path = path.with_suffix(".yaml")
if config_path.exists():
    ...
```

**Web research consulted:**

- <https://pyinstaller.org/en/stable/runtime-information.html>

**Proposed fix:** Copy both plugin code and same-stem sidecars (`.yaml`, possibly other declarative assets) as one atomic plugin unit.

---

#### K.3 [MEDIUM] POSIX `onedir` PyInstaller bundles depend on preserved symlinks, but the build/deploy flow does not surface that requirement

**Location:** `build_scripts/cryodaq.spec:173`, `build_scripts/build.sh:17`

**Description:** PyInstaller 6.x `onedir` bundles on POSIX rely heavily on symbolic links. The current build scripts create the bundle, but the operator/deployment path does not warn that copying or archiving the bundle without preserving symlinks can break it.

**Impact:** A perfectly good Linux build can fail after being zipped/copied the wrong way during deployment handoff. This is a classic “works on build machine, broken on target machine” packaging trap.

**Evidence:** PyInstaller explicitly states that POSIX `onedir` bundles “make extensive use of symbolic links” and that archive/copy steps must preserve them. The current build flow does not encode that requirement.

**Web research consulted:**

- <https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html>

**Proposed fix:** Package Linux builds in a symlink-preserving format (`tar`, or documented copy procedure), and put that rule in the build/deploy checklist rather than tribal knowledge.

### L. Config Files (config/*.yaml)

No config-file-only defect rose above the threshold for a standalone finding. The config layer is mostly template data; the more important residual risks are deployment assumptions that span config, paths, storage, and packaging.

### M. TSP Supervisor (tsp/p_const.lua)

#### M.1 [CRITICAL] The bundled Keithley watchdog script is not actually part of the production safety path

**Location:** `src/cryodaq/drivers/instruments/keithley_2604b.py:1`, `src/cryodaq/drivers/instruments/keithley_2604b.py:239`, `tsp/p_const.lua:1`

**Description:** The repository ships a TSP script with a 30-second watchdog that forces output off if heartbeats stop, but the production Keithley driver explicitly states that no TSP scripts are uploaded and all constant-power control runs host-side.

**Impact:** If the host process wedges or crashes while the source is active, the SMU can keep sourcing the last programmed voltage indefinitely until a restart path or human intervention reaches it. In a cryogenic heater/control context, that is a real hardware-risk failure mode, not just a software neatness issue.

**Evidence:**

```python
# keithley_2604b.py
"""P=const control loop runs host-side in read_channels() — no TSP scripts
are uploaded to the instrument, so the VISA bus stays free for queries."""

await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
```

```lua
-- tsp/p_const.lua
if (os.time() - {SMU}_watchdog_last_heartbeat) > 30 then
    break
end
...
{SMU}_safe_shutdown()
```

Tektronix/Keithley's 2600B documentation confirms that user scripts are loaded into the instrument runtime environment and can be stored in nonvolatile memory.  
Source: <https://www.tek.com/tw/keithley-source-measure-units/smu-2600b-series-sourcemeter-manual-8>

**Web research consulted:**

- <https://www.tek.com/tw/keithley-source-measure-units/smu-2600b-series-sourcemeter-manual-8>
- <https://download.tek.com/manual/2600AS-900-01_B-Sep2008_User.pdf>

**Proposed fix:** Either remove the unused script and explicitly accept the host-only safety model in deployment docs, or, preferably, make the watchdog script part of the real runtime contract and verify its presence/heartbeat during active sourcing.

### Z. Verified correct (OK items)

#### Z.1 [OK] Frozen entry point calls `multiprocessing.freeze_support()` early enough

**Location:** `src/cryodaq/_frozen_main.py:43`

I checked this against PyInstaller's multiprocessing guidance. The current `_frozen_main.py` calls `freeze_support()` before heavy imports and before PySide6 in the frozen entry path, which is the right pattern for Windows/macOS `spawn` and future POSIX defaults.

#### Z.2 [OK] Logging now redacts Telegram tokens and closes replaced handlers

**Location:** `src/cryodaq/logging_setup.py:32`, `src/cryodaq/logging_setup.py:109`

The token redaction regexes cover both URL-form and bare token form, and `setup_logging()` closes old handlers before removing them, which avoids quiet FD leaks on repeated logger reconfiguration.

#### Z.3 [OK] Telegram services correctly use one `aiohttp.ClientSession` per long-lived service and close it on shutdown

**Location:** `src/cryodaq/notifications/telegram.py:183`, `src/cryodaq/notifications/telegram_commands.py:138`

This matches aiohttp guidance to avoid per-request sessions and to keep a session per application/service for pooling and keepalive reuse.

#### Z.4 [OK] The command bot is now default-deny for remote control commands

**Location:** `src/cryodaq/notifications/telegram_commands.py:87`

Empty `allowed_chat_ids` with commands enabled now raises immediately. That closes the most dangerous “bot accidentally open to any chat” failure mode.

#### Z.5 [OK] Safety/interlock routing now escalates trip-handler failure into a guaranteed `_fault()` path

**Location:** `src/cryodaq/engine.py:886`

This is the right shape for a safety-critical adapter: if the rich interlock action path fails, the fallback is not “log and continue”, it is “latch fault and drive source off”.

#### Z.6 [OK] Fire-and-forget Telegram alarm dispatch tasks are kept strongly referenced

**Location:** `src/cryodaq/engine.py:1030`

This exactly matches Python's documented requirement to keep strong references to background tasks. It avoids the classic weak-ref task disappearance bug.

#### Z.7 [OK] LakeShore 218S ID validation and recovery path are stronger than typical lab code

**Location:** `src/cryodaq/drivers/instruments/lakeshore_218s.py:56`

The driver now validates `*IDN?`, retries once after device clear, and only proceeds on a believable 218 identity. That is materially better than “query succeeded, assume the address is right”.

#### Z.8 [OK] Keithley connect/disconnect paths do force safe-off behavior on takeover and disconnect

**Location:** `src/cryodaq/drivers/instruments/keithley_2604b.py:88`, `src/cryodaq/drivers/instruments/keithley_2604b.py:287`

Even though I still consider M.1 a critical residual issue, the connect/disconnect/emergency-off paths themselves are meaningfully hardened: outputs are driven to zero/off on connect takeover, and emergency-off verifies output-off readback.

## Cross-cutting observations

- Non-atomic sidecar writes recur in multiple subsystems despite the repo already containing an atomic write helper. The pattern appears in experiment state, phase metadata, summary metadata, and calibration indexes.
- The deployment model assumes the bundle directory is both writable and local. That same assumption appears in `paths.py`, SQLite WAL behavior, hot-reloadable plugins, and post-build directory seeding.
- “Timeout” is sometimes treated as if it means “underlying blocking operation stopped”. That is not true for threadpool-backed VISA work and is the most important async misconception still present.
- Wall-clock/sample-time mixing appears in more than one cooldown-related component. Anything derived from historical telemetry should use telemetry timestamps unless the component is explicitly live-only.

## Python 3.12+ deprecation review

- `src/cryodaq/web/server.py:301` and `:310` still use FastAPI `@app.on_event("startup"/"shutdown")`. FastAPI now recommends the lifespan API instead and labels the event form as the obsolete/alternative path. This is not a current bug, but it is technical debt near the web boundary.
- `asyncio.get_event_loop()` is still used inside running coroutines in `src/cryodaq/analytics/plugin_loader.py:243`, `src/cryodaq/storage/sqlite_writer.py:509`, and `src/cryodaq/core/scheduler.py:112`. That usage still works under a running loop, but `get_running_loop()` is the modern clearer form and is the direction the stdlib has been pushing for several releases.
- I did not find `datetime.utcnow()` in scoped runtime code. Time handling is mostly timezone-aware UTC, which is the right baseline.

## Security surface summary

CryoDAQ's remote attack surface is modest but not tiny. The main live surfaces are the unauthenticated FastAPI dashboard and the Telegram command bot; the former is read-only but easy to abuse for information exposure and expensive history scans, while the latter is access-controlled but still vulnerable to stale-update replay on restart. The largest local security/safety surface is the writable executable plugin directory, which allows in-process Python execution in a safety-critical daemon. Secret handling around Telegram tokens is materially improved and I did not find unsafe YAML loaders or pickle-like deserialization in scope.

## Modules skipped / unable to audit

None within the requested scope. I did not audit `tests/`, `docs/`, `graphify-out/`, `build/`, `dist/`, or `src/cryodaq/gui/widgets/` beyond `gui/app.py` and `gui/zmq_client.py`, per the prompt.
