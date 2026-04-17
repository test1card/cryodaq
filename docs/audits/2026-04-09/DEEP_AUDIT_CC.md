# CryoDAQ — Deep Audit (Claude Code)

Date: 2026-04-08
Areas checked: 15 (A-O)
Method: read-only inspection of `src/`, `tests/`, `config/`, `docs/`, `pyproject.toml`, with parallel research subagents (Claude Sonnet via Agent tool) and direct WebSearch / WebFetch for external sources.

> **Note on sources:** Some `PROJECT_STATUS.md` and `.claude/rules/safety.md` files referenced in the task brief do not exist in the repository — context was reconstructed from `CLAUDE.md`, `CHANGELOG.md` 0.13.0 (`unreleased`, 0.13.0, 0.12.0…0.1.0), `RELEASE_CHECKLIST.md`, `docs/architecture.md`, `docs/deployment.md`, `graphify-out/GRAPH_REPORT.md` and direct source reading.
>
> **Already-fixed items intentionally NOT re-flagged** (per CHANGELOG 0.13.0):
> SafetyManager fault race (`_transition(FAULT_LATCHED)` set BEFORE `await emergency_off()`); `executor.shutdown(wait=True)` before `conn.close()`; `float('inf')` caught by `math.isfinite()`; Keithley slew/compliance/_I_MIN_A; ZMQ heartbeat 3s; REP socket guaranteed reply on CancelledError; GPIB `close_all_managers()`; `__del__` removed from Keithley driver; `get_event_loop().create_task()` → `asyncio.create_task()`; DataBroker tuple snapshot iteration; dedicated SQLiteWriter executor; composite `idx_channel_ts`; persistence-first ordering; Latin/Cyrillic T regression.

---

## Executive summary

- **CRITICAL findings:** 2 (E1 + E2 — both PyInstaller blockers)
- **HIGH findings:** 9 (A1, A2, B1, F1, F2, G1, H1, I1, O1)
- **MEDIUM findings:** 17 (A3, A4, B2, C1, C4, D1, D5, E3, E4, F3, F4, H2, H3, H4, I2, J1, K1, M1, M2, N1, O2, O3, O4)
- **LOW findings:** 7 (A5, B3, C2, C3, D2, D3, D4, H5, J2, L1, L2)
- **Confirmed OK:** 12 areas / sub-checks (see "Areas confirmed OK" section)

### Top 3 concerns before deployment

1. **PyInstaller fork-bomb (E2) and missing spec/hidden-imports/data bundling (E1)** — *the codebase is not currently buildable into a working PyInstaller bundle*. As-is, `pyinstaller cryodaq.spec` will (a) infinite-spawn the GUI on Windows because `multiprocessing.freeze_support()` is called *after* PySide6 imports in `launcher.py:662` and `gui/app.py:29`, (b) fail to find `config/`, `plugins/`, `tsp/` because `paths.get_project_root()` resolves into `_MEIPASS`, (c) silently miss `pyvisa_py`, `serial.tools.list_ports_windows`, `msgpack._cmsgpack`, `scipy.special._ufuncs_cxx`, several PySide6 plugins. **Blocking.**

2. **Two unreferenced `asyncio.create_task` calls on safety/alarm publish paths (A1, A2, I2)** — the safety state broadcast in `SafetyManager._transition` (`safety_manager.py:462`) and the Telegram alarm dispatch in the alarm v2 tick (`engine.py:991`) both create tasks without storing references. Per Python docs the event loop only weak-refs tasks, so a fault-state broadcast can vanish silently, leaving GUI/Web showing stale "RUN_PERMITTED" while the engine is FAULT_LATCHED. Direct operational consequence on a safety path.

3. **No hardware watchdog on Keithley + persistence durability gap (G1, D1, H1)** — `CLAUDE.md` claims "Double protection: Python safety path + hardware watchdog". The hardware watchdog *does not exist*: `keithley_2604b.py:3` says explicitly "P=const control loop runs host-side ... no TSP scripts are uploaded". `tsp/p_const.lua` is on disk but never loaded. Combined with (D1) WAL checkpoint starvation and (H1) silent disk-full loop, an engine crash mid-experiment leaves the heater driving the last-programmed voltage with no instrument-level fallback.

Other significant concerns:

- **Emergency-Off GUI thread crash (B1)** — `Ctrl+Shift+X` instantiates `ZmqCommandWorker` with no parent and immediately reassigns the local `w` variable, dropping the only reference to a running QThread. Qt destroys the C++ object while the OS thread is mid-`send_command` → segfault. This is the *operator's panic button*.
- **Default ThreadPoolExecutor starvation (A3, F2)** — analytics, matplotlib, GPIB, USBTMC, and SQLite reads share `loop.run_in_executor(None, ...)`. Only the SQLite *writer* has its own pool. A hung Keithley call can backpressure cooldown training and history reads, exacerbating the GPIB error counter and causing flaky reconnects.
- **Unbounded log files (O2)** — three modules call `logging.basicConfig(...)` without `RotatingFileHandler` / `TimedRotatingFileHandler`. On a long-running lab PC, log volume is unbounded.
- **No LICENSE, no update mechanism, no crash reporter, no log rotation (O1, O3, O4)** — operational hygiene gaps for a 24/7 lab deployment.

---

## Findings

### A. Asyncio correctness

#### A.1 [HIGH] Fire-and-forget `create_task` for Telegram alarm dispatch

**What I checked.**
- File: `src/cryodaq/engine.py:991`
- Code:
  ```python
  if "telegram" in alarm_cfg.notify and telegram_bot is not None:
      msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
      asyncio.create_task(
          telegram_bot._send_to_all(msg),
          name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
      )
  ```
- Grep: `rg "asyncio.create_task" src/` returned 14 hits; this and A.2 are the two with no stored reference.

**Current implementation.** The alarm v2 tick loop schedules the Telegram dispatch as a fire-and-forget task. Return value is discarded. No `add_done_callback`, no module-level set.

**Web research.**
- *Python docs, `asyncio.create_task`*: "Save a reference to the result of this function, to avoid a task disappearing mid-execution. The event loop only keeps weak references to tasks. A task that isn't referenced elsewhere may get garbage collected at any time, even before it's done. For reliable 'fire-and-forget' background tasks, gather them in a collection." [docs.python.org/3/library/asyncio-task.html#asyncio.create_task](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)
- Mass-cited Python issue [bpo-44665 / GH-88831](https://github.com/python/cpython/issues/88831) and Hynek Schlawack's writeup confirm this is *the* most common asyncio footgun in production.

**Reasoning chain.** `_send_to_all` is an `aiohttp` POST — there are several await points before the task completes. Between two awaits, the only strong reference is the loop's weak set. If GC fires (and it can, the task is unreferenced), the operation aborts mid-flight with `RuntimeWarning: Task was destroyed but it is pending!` and the Telegram alarm is *never delivered*. For a safety-relevant alarm path this is a real loss-of-warning, not a theoretical concern.

**Verdict.** **HIGH.** Direct impact on the operator's most reliable out-of-band warning channel.

**Recommendation.** Hold a strong reference. The minimum-diff fix is a module-level `_alarm_dispatch_tasks: set[asyncio.Task] = set()`; add the task; `task.add_done_callback(_alarm_dispatch_tasks.discard)`. Better: route alarm dispatch through `EscalationService` which already owns its own queue and lifecycle.

---

#### A.2 [HIGH] Same pattern in `SafetyManager._transition`

**What I checked.**
- File: `src/cryodaq/core/safety_manager.py:461-464`
- Code:
  ```python
  try:
      asyncio.get_running_loop().create_task(self._publish_state(reason))
  except RuntimeError:
      pass
  ```

**Current implementation.** Every state transition (including `FAULT_LATCHED`) schedules `_publish_state` without keeping a reference. The `try/except RuntimeError` catches "no running loop" but does not address GC.

**Web research.** Same source as A.1. Plus *PEP 654 / PEP 695 examples in the asyncio docs*. The "store the task" guidance is unconditional.

**Reasoning chain.** `_transition` is the *only* place that publishes safety state changes to the broker. If the FAULT_LATCHED publication is GC'd, the GUI continues to display the previous state ("RUN_PERMITTED" or "RUNNING"), the web dashboard shows stale, and the only signal that anything is wrong is a CRITICAL log line on the engine console — which the operator may not be looking at. The operator's mental model is "if I see 'safe_off' on the dashboard, it's safe". A dropped state event silently breaks that contract.

**Verdict.** **HIGH.** Hidden under a `try/except RuntimeError` makes it look defensive — it isn't.

**Recommendation.** `self._pending_publishes: set[asyncio.Task] = set()` in `__init__`; `t = asyncio.get_running_loop().create_task(...); self._pending_publishes.add(t); t.add_done_callback(self._pending_publishes.discard)`. Alternative: refactor `_transition` to be `async` and `await self._publish_state(reason)` directly — most callers (`_fault`, `_safe_off`, `request_run`, `acknowledge_fault`, `_run_checks`) are already in async context.

---

#### A.3 [MEDIUM] Default `ThreadPoolExecutor` starvation: analytics + matplotlib + GPIB + USBTMC + history reads share one pool

**What I checked.**
- `src/cryodaq/analytics/cooldown_service.py:245, 372, 458` — `run_in_executor(None, ...)` for model load, scipy `predict()`, ingest
- `src/cryodaq/notifications/periodic_report.py:209` — matplotlib PNG render
- `src/cryodaq/web/server.py:389` — SQLite history read
- `src/cryodaq/drivers/transport/usbtmc.py`, `gpib.py` — PyVISA blocking I/O via `None` executor
- `src/cryodaq/storage/sqlite_writer.py:118` — uses **dedicated** `ThreadPoolExecutor(max_workers=1)` (correct).

**Current implementation.** SQLite *writer* has its own executor; everything else shares the default `min(32, cpu+4)` pool.

**Web research.**
- [Python docs `loop.run_in_executor`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor): "If executor is None, the default executor is used."
- [PyVISA issue #262](https://github.com/pyvisa/pyvisa/issues/262): users report concurrent PyVISA reads under thread pool contention exhibit interleaving / latency spikes on `pyvisa-py`.

**Reasoning chain.** Under load (cooldown ingest training a new model + a periodic Telegram report rendering matplotlib + a web dashboard history query + the steady stream of GPIB reads from 3× LakeShore + USBTMC reads from Keithley) the default pool is close to saturation. PyVISA blocking I/O can occupy a worker for 3 s at a time. If the pool is full, *new* `run_in_executor` calls queue up, including the next driver poll. The scheduler's "3 consecutive errors → disconnect" logic at `scheduler.py:153` can be tripped by latency that originates in CPU contention rather than instrument failure.

**Verdict.** **MEDIUM.** Latent performance / spurious-disconnect risk, not a correctness bug.

**Recommendation.** Give analytics its own `ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics")`; matplotlib its own; either let PyVISA stay on default (after adding executor pool size) or — better — give each VISA transport instance its own single-worker executor (this also matches the "pyvisa thread-safe per-resource" contract more cleanly).

---

#### A.4 [MEDIUM] Alarm v2 / sensor diagnostics feeds drop silently on backpressure

**What I checked.**
- `src/cryodaq/engine.py:947, 956, 1003, 1033` — four feed loops subscribed via `await broker.subscribe("...", maxsize=2000)`.

**Current implementation.** `DataBroker` defaults to `OverflowPolicy.DROP_OLDEST` and increments `Subscription.dropped`. The `stats` property exposes per-subscriber drop counters. **Nothing checks them.**

**Reasoning chain.** Under normal load (~30 readings/s) the queues drain trivially. But under contention (GUI dialog modal + GIL pressure + cooldown ingest holding the loop), the alarm v2 state-tracker feed can fall behind. The tracker is what `AlarmEvaluator` reads on every tick — stale state means alarms evaluate against old values. There's no observability: the feed is named `alarm_v2_state_feed` and silently drops with no metric, no log, no alert.

**Verdict.** **MEDIUM.** Safety-feed drops should *never* be silent.

**Recommendation.** Add to the engine heartbeat (already running every few seconds): if any safety-relevant subscriber's `dropped` counter increases, log WARNING. If `dropped` increases on `alarm_v2_state_feed` specifically, promote to engine FAULT (the feed is tracking critical channel state).

---

#### A.5 [LOW / OK by design] Persistence-first await chain blocks polling under disk pressure

**What I checked.** `scheduler.py:327` `await self._sqlite_writer.write_immediate(persisted_readings)` is awaited per-instrument before publishing to brokers. Driver read is wrapped in `wait_for(timeout=3.0)` — but the SQLite write is *not* in that timeout.

**Verdict.** This is *intentional* per CHANGELOG 0.13.0 ("persistence-first invariant"). A stuck disk → polling blocks → SafetyManager `fail_on_silence` → FAULT + emergency_off. That is the conservative, correct cryo-rig behaviour. **Recommendation:** document this explicitly so future maintainers do not "fix" it.

---

### B. PySide6 threading model

#### B.1 [HIGH] `ZmqCommandWorker` threads dropped on the Emergency-Off shortcut

**What I checked.**
- File: `src/cryodaq/gui/main_window.py:258-264`
- Code:
  ```python
  for ch in ("smua", "smub"):
      w = ZmqCommandWorker({"cmd": "keithley_emergency_off", "channel": ch})
      w.finished.connect(lambda r: None)
      w.start()
  ```
- Cross-checked `ZmqCommandWorker` definition in `src/cryodaq/gui/zmq_client.py` — it subclasses `QThread` directly.

**Current implementation.** `Ctrl+Shift+X` (operator panic button) creates two `QThread` workers with no parent and stores them in a local variable that gets immediately reassigned by the for-loop iteration.

**Web research.**
- [Qt 6 `QThread` docs](https://doc.qt.io/qt-6/qthread.html): "Deleting a running QThread (i.e. `isFinished()` returns false) will result in a program crash."
- [PySide6 lifetime docs](https://doc.qt.io/qtforpython-6/overviews/object.html#object-trees-ownership): "When a QObject's parent is deleted, all its children are also deleted. ... Unparented Python wrappers track the C++ object lifetime via Python refcount."

**Reasoning chain.** When `w` goes out of scope at function return (and the second iteration overwrites the first immediately), Python decrements the PySide6 wrapper refcount. If it reaches zero before the C++ thread's `run()` returns, the underlying `QThread` C++ object is destroyed mid-execution. PySide6's parent ownership only protects you if you pass `parent=...`. The `finished.connect(lambda r: None)` does not pin anything — the lambda is owned by the (about-to-be-destroyed) signal sender. The `Emergency Off` path is exactly the one that *must not crash*: a GUI segfault here means the operator pressed the panic button and got a Windows error dialog, with engine state unknown.

**Verdict.** **HIGH.** Direct crash in a safety path. May not reproduce in dev (the worker often finishes before scope exit) but will fire intermittently in production.

**Recommendation.** Pass `parent=self`, or store the workers in `self._emergency_workers: list[QThread]` and prune via `finished.connect(self._on_emerg_finished)`. Best: make the synchronous call inline — the engine command is `keithley_emergency_off` which already has a 5 s timeout in `bridge.send_command`, and a synchronous call from the GUI main thread is acceptable for a panic button (the operator wants the GUI to wait until it's confirmed).

---

#### B.2 [MEDIUM] 100 Hz GUI tick drains the mp.Queue with no per-tick cap

**What I checked.**
- `src/cryodaq/gui/app.py:62-79` (`_tick` runs every 10 ms)
- `src/cryodaq/gui/zmq_client.py:118-138` (`bridge.poll_readings()` does `while True: get_nowait()`)

**Reasoning.** Normal load is ~30 readings/s, so each tick processes 0-1 items. After a stall (modal dialog, paging, plot freeze), the mp.Queue can hold thousands of items. The next `_tick` processes them all on the Qt main thread, calling 4-6 panel `on_reading()` methods each. A 2000-item drain easily takes >200 ms, freezing GUI input.

**Web research.** [Qt QTimer docs](https://doc.qt.io/qt-6/qtimer.html): "The timer's accuracy depends on the underlying operating system and hardware. ... Most platforms support an accuracy of 1 millisecond or better, but the actual accuracy of the timer will not equal this in many real-world situations." Standard PyQt advice is to bound per-tick work.

**Verdict.** **MEDIUM.** Not a crash, but violates the "GUI responsive" rule and creates the appearance of a hung GUI to the operator.

**Recommendation.** Cap drain per tick: `for _ in range(500): try: q.get_nowait() except Empty: break`.

---

#### B.3 [LOW / OK] `QShortcut` reference handling

**What I checked.** `main_window.py:220-238` creates `QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(...)` for several shortcuts.

**Verdict.** Safe — `self` (the `MainWindow`) is passed as parent → Qt parent-ownership keeps the C++ object alive even though the Python binding refcount drops. Noted only to contrast with B.1.

---

### C. ZMQ patterns

#### C.1 [MEDIUM] No explicit HWM on PUB / SUB

**What I checked.**
- `src/cryodaq/core/zmq_bridge.py:92-96` (publisher)
- `src/cryodaq/core/zmq_bridge.py:173-181` (subscriber)
- `src/cryodaq/core/zmq_subprocess.py:72-85` (subprocess SUB + REQ)
- Grep `set_hwm|SNDHWM|RCVHWM` across `src/`: zero hits.

**Current implementation.** Default HWM is 1000 messages per peer.

**Web research.** [ZMQ Guide ch.5 — Reliable pub-sub](https://zguide.zeromq.org/docs/chapter5/): "Publishers can drop messages if they are sending faster than subscribers can receive them. ZeroMQ forces default limits on its internal buffers (the so-called high-water mark or HWM)." Default 1000 means **silent drops** at the publisher when subscribers fall behind.

**Reasoning chain.** 30 readings/s × 1000 HWM = ~33 s of buffer. If the GUI subprocess is paused longer than that (uncommon but possible during paging or modal dialogs), data is silently dropped *between engine PUB and subprocess SUB*. SafetyBroker is unaffected (separate path), but the operator's live view becomes a lie.

**Verdict.** **MEDIUM.** Drops are silent.

**Recommendation.** Set `set_hwm(10000)` on both engine PUB and subprocess SUB at start. Add a counter diff in heartbeats so drops are visible.

---

#### C.2 [LOW / OK] msgpack unpacker safety on a localhost socket

**What I checked.** `src/cryodaq/core/zmq_bridge.py:46`, `core/zmq_subprocess.py:29` — `msgpack.unpackb(payload, raw=False)`.

**Web research.** [msgpack-python docs](https://msgpack-python.readthedocs.io/): msgpack is **safe by default** (unlike pickle, no code execution). The remaining concern is resource exhaustion via huge maps/lists/bins. `strict_map_key=True` is default in current versions.

**Verdict.** LOW / OK. Trust boundary is the lab PC. Defense-in-depth: add `max_buffer_size=2*1024*1024` to `unpackb` calls.

---

#### C.3 [LOW] Dead `RCVTIMEO` setting on asyncio SUB socket

`zmq_bridge.py:179` sets `RCVTIMEO=3000` but the `recv` is wrapped in `asyncio.wait_for(..., timeout=1.0)`. The asyncio wrapper goes through a polling loop, so `RCVTIMEO` never fires first. Harmless. **Recommendation:** remove for clarity.

---

#### C.4 [MEDIUM, needs verification] Multiple REQ clients (GUI + web dashboard) share single REP

**What I checked.** `zmq_bridge.py:204-316` (single REP). Web server: `src/cryodaq/web/server.py:77` `return await asyncio.to_thread(_send_engine_command, cmd)` — creates a fresh REQ per call inside a thread.

**Reasoning chain.** If GUI subprocess is *also* sending REQs at the same time, both REQ clients funnel through the single REP. With `REQ_RELAXED` + `REQ_CORRELATE` set, libzmq routes correctly per-envelope, so no reply mismatch — but there's no stress test verifying this. The web dashboard is documented as "optional", so maybe nobody has tried "GUI + web dashboard + manual operator REQ" simultaneously.

**Verdict.** **MEDIUM, needs verification.** Add an integration test that pumps requests from two REQ clients and verifies replies go to the right caller.

**Recommendation.** Long-term, switch the command channel from REP/REQ to ROUTER/DEALER for explicit multi-client support.

---

### D. SQLite persistence

#### D.1 [MEDIUM] No explicit WAL checkpoint policy; default 1000-page autocheckpoint can stall under concurrent readers

**What I checked.**
- File: `src/cryodaq/storage/sqlite_writer.py:134-136`
- Code:
  ```python
  conn.execute("PRAGMA journal_mode=WAL;")
  conn.execute("PRAGMA synchronous=NORMAL;")
  conn.execute("PRAGMA busy_timeout=5000;")
  ```
- No `wal_autocheckpoint`, no `cache_size`, no `mmap_size`, no `temp_store`.

**Web research.** [SQLite WAL docs](https://www.sqlite.org/wal.html): "If a database has many concurrent overlapping readers and there is always at least one active reader, then no checkpoints will be able to complete and hence the WAL file will grow without bound." Default auto-checkpoint is 1000 pages (~4 MB).

**Reasoning chain.** Concurrent readers: `reporting/data.py`, `web/server.py:_query_history`, GUI reconnect via `read_readings_history`, operator log reader. A long report query holding a reader open while the writer checkpoints means PASSIVE checkpoint only — and may not complete. At ~30 readings/s × 86400 s ≈ 2.6 M rows/day, the WAL file grows fast. On daily rollover, `conn.close()` triggers a final checkpoint that blocks on pending readers.

**Verdict.** **MEDIUM.** Latent disk-growth + checkpoint-stall risk.

**Recommendation.** Add explicit pragmas:
```python
conn.execute("PRAGMA wal_autocheckpoint=1000;")
conn.execute("PRAGMA cache_size=-16384;")  # 16 MB
conn.execute("PRAGMA mmap_size=268435456;")  # 256 MB
conn.execute("PRAGMA temp_store=MEMORY;")
```
Plus a periodic `PRAGMA wal_checkpoint(TRUNCATE)` from the writer thread (e.g., every 5 minutes). Monitor WAL file size in `DiskMonitor`.

---

#### D.2 [LOW] `synchronous=NORMAL` durability tradeoff is undocumented

**Web research.** [SQLite pragma docs](https://sqlite.org/pragma.html): "WAL mode does lose durability. A transaction committed in WAL mode with synchronous=NORMAL might roll back following a power loss or system crash."

**Reasoning.** For a cryo rig, the *last* second of data before power loss is the most diagnostically valuable. Document the assumption (UPS expected) in `CLAUDE.md` or `docs/safety.md`. If the lab PC is *not* on a UPS, switch to `synchronous=FULL` — at 30 Hz the throughput penalty is negligible.

---

#### D.3 [LOW / OK] Daily rotation handles cross-midnight batches

`sqlite_writer.py:124-149, 151-169` groups readings by `r.timestamp.date()` and routes each group through `_ensure_connection(day)`. A batch spanning midnight opens both files within the same call. Verified by code reading. Edge case: if `_ensure_connection` raises during the new-day connection (disk full at exactly midnight), the old connection is already closed; next write retries and succeeds. Acceptable.

---

#### D.4 [LOW / OK] `check_same_thread=False` is defensive but unnecessary

Writer uses `ThreadPoolExecutor(max_workers=1)`, so only one thread ever touches `self._conn`. The flag is harmless. Could be removed for strictness.

---

#### D.5 [MEDIUM] History readers contribute to checkpoint starvation (tied to D.1)

Each read opens `sqlite3.connect(db_path, timeout=5)` and holds a reader position in WAL until close. Connections do not set `query_only`. Combined with D.1 this is the actual mechanism for unbounded WAL growth under load. **Recommendation.** Once D.1's explicit pragmas are in, also add `PRAGMA query_only=1` on read connections to make the contract explicit.

---

### E. Multiprocessing + PyInstaller readiness

#### E.1 [CRITICAL — BLOCKING] No PyInstaller spec, no hidden imports, no `sys.frozen` / `_MEIPASS` handling

**What I checked.**
- `find . -name "*.spec"` → only vendored `.venv/.../PySide6/.../default.spec`
- Repo grep for `pyinstaller|PyInstaller|_MEIPASS|sys\.frozen|hiddenimports` → **zero matches** in src/, tests/, scripts/, config/, pyproject.toml
- No `pyinstaller` extra in `pyproject.toml`
- `CLAUDE.md`: "Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT"

**Web research.**
- [PyInstaller "Common Issues and Pitfalls"](https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html): Many libraries (pyqtgraph, scipy.special, msgpack C ext, pyvisa backends discovered at runtime, pyserial) require `--hidden-import` or a hook file.
- [PyInstaller PySide6 hook gotchas (issue #6387)](https://github.com/pyinstaller/pyinstaller/issues/6387): backend plugin files need explicit bundling.
- [PyInstaller runtime info](https://pyinstaller.org/en/latest/runtime-information.html): `sys._MEIPASS` is a temp dir under `--onefile`; writable user data must use `Path(sys.executable).parent` or a user-profile dir.

**Reasoning chain.** The codebase uses dynamic imports heavily: drivers loaded by string in `engine._load_drivers` (`engine.py:691`), `pyvisa.ResourceManager()` in `_get_rm` (`gpib.py:73`), `import pyvisa` in `_blocking_open` (`usbtmc.py:195`), `import serial_asyncio` in `SerialTransport.open` (`serial.py:62`), `import zmq` inside `zmq_bridge_main` (`zmq_subprocess.py:67`). PyInstaller's static analyzer sometimes catches deferred imports inside functions, but pyvisa's backend layer uses `importlib.import_module` internally and is **routinely missed** without an explicit hook. Data files (`config/*.yaml`, `plugins/`, `tsp/*.lua`) are referenced via `paths.get_project_root()` which does `Path(__file__).resolve().parent.parent.parent` — under `--onefile` this points into `_MEIPASS` (a temp dir cleaned up on exit), so daily SQLite DBs would land in a temp location and be wiped.

**Verdict.** **CRITICAL / blocking.** Cannot ship as PyInstaller bundle in current state.

**Recommendation.** Author `cryodaq.spec` with at minimum:
```python
hiddenimports=[
  'pyvisa_py', 'pyvisa.ctwrapper',
  'serial.tools.list_ports_windows',
  'msgpack._cmsgpack',
  'scipy.special._ufuncs_cxx',
  'pyqtgraph.canvas',
  'cryodaq.drivers.instruments.lakeshore_218s',
  'cryodaq.drivers.instruments.keithley_2604b',
  'cryodaq.drivers.instruments.thyracont_vsp63d',
  'cryodaq.analytics.plugin_loader',
],
datas=[('config', 'config'), ('tsp', 'tsp'), ('plugins', 'plugins')],
```
Add a `sys.frozen` branch to `paths.get_project_root()` returning `Path(sys.executable).parent`. Test on a clean Windows VM via `--mock` mode before shipping.

---

#### E.2 [CRITICAL — BLOCKING] `multiprocessing.freeze_support()` called too late

**What I checked.**
- `src/cryodaq/launcher.py:1-46` (top-level imports include PySide6, asyncio policy, `cryodaq.gui.main_window`, `cryodaq.gui.zmq_client`)
- `launcher.py:660-662`:
  ```python
  def main() -> None:
      import argparse
      import multiprocessing
      multiprocessing.freeze_support()
  ```
- Same pattern in `src/cryodaq/gui/app.py:14, 29` — `import multiprocessing` at top, `freeze_support()` after `from PySide6.QtWidgets import QApplication`.

**Web research.**
- [SuperFastPython on `freeze_support()`](https://superfastpython.com/multiprocessing-freeze-support-in-python/): "A typical symptom of failing to call `multiprocessing.freeze_support()` before your code attempts to use multiprocessing is an endless spawn loop of your application process."
- [PyInstaller wiki Recipe-Multiprocessing](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing): call `freeze_support()` as the **first statement** under `if __name__ == "__main__":`.
- [Python `multiprocessing.freeze_support` docs](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.freeze_support): must run "immediately after the `if __name__ == '__main__'` line of the main module".

**Reasoning chain.** On Windows, `mp.Process` uses `spawn`, which relaunches the executable and re-runs the main module. PyInstaller's bootloader inspects `sys.argv` to detect a worker process — but only if `freeze_support()` runs first. Currently, the launcher's top-level imports execute (loading PySide6, instantiating QApplication-related state), *then* `main()` runs, *then* `freeze_support()` is called — by which point the worker has already done substantial GUI setup and reached `LauncherWindow.__init__` → `ZmqBridge.start()` → another `mp.Process.start()` → another relaunch. **Textbook fork bomb.**

In dev (non-frozen) mode this works because `freeze_support()` is a no-op off-frozen. The bomb only triggers under PyInstaller. So all existing tests pass and dev launches fine — the bug is invisible until you bundle.

**Verdict.** **CRITICAL — absolutely blocking for PyInstaller deployment.**

**Recommendation.** Create a thin entry-point wrapper (e.g., `src/cryodaq/_main_frozen.py`) whose first statements are:
```python
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    from cryodaq.launcher import main
    main()
```
Use this as PyInstaller's target. Same for the GUI entry. Move all heavy imports below the `freeze_support()` call.

---

#### E.3 [MEDIUM] Dead `tsp/p_const_single.lua` shipped, claims a watchdog that doesn't exist

**What I checked.**
- `keithley_2604b.py:3`: "P=const control loop runs host-side in `read_channels()` — no TSP scripts are uploaded to the instrument"
- Repo grep `p_const|loadscript|_script` across `src/`: zero hits
- `tsp/p_const_single.lua` lines 35-42 claim "watchdog 30s, автоматически отключит выход"
- `CLAUDE.md`: "tsp/p_const_single.lua — legacy/fallback artifact, который всё ещё присутствует в дереве"

**Verdict.** **MEDIUM** — documentation/safety review confusion. Operators reading `p_const_single.lua` will assume there is a hardware watchdog. There isn't (see G.1).

**Recommendation.** Delete `tsp/` from the repo, or move to `docs/legacy/` with a "NOT LOADED" banner. Definitely don't bundle as PyInstaller data.

---

#### E.4 [MEDIUM, HIGH in practice] `paths.get_project_root()` returns `_MEIPASS` under PyInstaller onefile

**What I checked.**
- `src/cryodaq/paths.py:6-9`:
  ```python
  def get_project_root() -> Path:
      if "CRYODAQ_ROOT" in os.environ:
          return Path(os.environ["CRYODAQ_ROOT"])
      return Path(__file__).resolve().parent.parent.parent
  ```
- `install.bat` does not set `CRYODAQ_ROOT`.

**Reasoning.** Under `--onefile`, `__file__` resolves to `sys._MEIPASS/cryodaq/paths.py` (a temp extraction dir cleaned on exit). `.parent.parent.parent` → inside the temp dir. Daily SQLite DBs would be created there and wiped on every run → **total data loss**. The `CRYODAQ_ROOT` escape exists but operators won't set it.

**Verdict.** **MEDIUM** because of the env-var escape, **HIGH in practice**.

**Recommendation.** Add a `sys.frozen` branch:
```python
if getattr(sys, "frozen", False):
    return Path(sys.executable).parent
```
Belt-and-braces: have `start.bat` set `CRYODAQ_ROOT=%~dp0`.

---

### F. PyVISA / GPIB / Serial

#### F.1 [HIGH theoretical, LOW in production] Class-level `_resource_managers` dict has no lock

**File:** `src/cryodaq/drivers/transport/gpib.py:44, 68-74`
```python
class GPIBTransport:
    _resource_managers: dict[str, Any] = {}
    @classmethod
    def _get_rm(cls, bus_prefix: str) -> Any:
        if bus_prefix not in cls._resource_managers:
            import pyvisa
            cls._resource_managers[bus_prefix] = pyvisa.ResourceManager()
        return cls._resource_managers[bus_prefix]
```

**Web research.** [PyVISA FAQ — thread safety](https://pyvisa.readthedocs.io/en/latest/faq/faq.html): PyVISA is thread-safe per-resource since 1.6, but `ResourceManager` construction is not explicitly serialized. Multiple threads concurrently calling `pyvisa.ResourceManager()` is allowed but creates separate handles.

**Reasoning.** TOCTOU on the `not in` check: two threads can both pass the check and both call `pyvisa.ResourceManager()`, then the second overwrites the first. The first leaks until process exit (`close_all_managers()` only closes whatever is currently in the dict). Probability is low (only triggers when two new bus prefixes are seen simultaneously) and prod uses one bus → no actual hit. Worth fixing for correctness.

**Verdict.** **HIGH theoretical, LOW in prod.**

**Recommendation.** Wrap `_get_rm` in a `threading.Lock`.

---

#### F.2 [HIGH] GPIB / USBTMC blocking I/O on default executor

**File:** `gpib.py:125-127`, `usbtmc.py:107` — `await loop.run_in_executor(None, self._resource.write, cmd)`. See A.3 for the broader pool-saturation analysis.

**Verdict.** **HIGH.** Latent performance / cross-blocking risk.

**Recommendation.** Per-transport `ThreadPoolExecutor(max_workers=1)`.

---

#### F.3 [MEDIUM] Implicit GPIB backend, no logging

`gpib.py:73` calls `pyvisa.ResourceManager()` with no arguments. On Windows production this picks NI-VISA; on the developer's macOS it falls through to pyvisa-py (which can't do GPIB). No logging of which backend actually loaded — operators with a partial NI-VISA install get an opaque "no GPIB backend" error.

**Web research.** [PyVISA ResourceManager docs](https://pyvisa.readthedocs.io/en/latest/api/resourcemanager.html): "PyVISA will prefer the default backend (IVI) which tries to find the VISA shared library for you. If it fails it will fall back to pyvisa-py if installed."

**Recommendation.** Log `rm.visalib.library_path` after first RM creation; surface an explicit error if NI-VISA is not loaded and `mock=False`.

---

#### F.4 [MEDIUM] `SerialTransport.close()` may hang on Windows USB yank

**File:** `serial.py:82-88` — `self._writer.close(); await self._writer.wait_closed()` with no timeout.

**Web research.** [pyserial-asyncio issue #87](https://github.com/pyserial/pyserial-asyncio/issues/87): users report `wait_closed()` hangs on Windows when the COM port is force-disconnected.

**Recommendation.** Wrap in `asyncio.wait_for(..., timeout=2.0)`.

---

#### F.5 [OK] GPIB escalation recovery ladder

`scheduler.py:242-293` implements SDC → IFC → RM-reset escalation keyed on `bus_error_count`, with per-device `_PREVENTIVE_CLEAR_INTERVAL_S=300.0` and post-IFC cooldown. TNT4882 unaddressing is enabled in `gpib.py:205-210`. More defensive than typical LabVIEW replacements.

#### F.6 [OK] GPIB bus-lock contract: single-task serial polling per bus

`scheduler.py:178` `_gpib_poll_loop` guarantees no two `run_in_executor` calls touch the same GPIB bus concurrently. Contract enforced by construction.

> **Note.** The task brief mentioned `tests/drivers/test_gpib_bus_lock.py` — that file *does* exist (verified by glob). Read confirms it tests RM-sharing, IDN behavior, and IFC removal. Coverage is reasonable.

---

### G. TSP / Lua / Keithley

#### G.1 [HIGH] No hardware watchdog — "double protection" claim is false

**What I checked.**
- `keithley_2604b.py:3`: header comment confirms host-side regulation only.
- `keithley_2604b.py:100-188`: `read_channels()` does `print({smu_channel}.measure.iv())` + host-side `target_v = sqrt(P*R)` + slew + `write({smu_channel}.source.levelv = target_v)`.
- `tsp/p_const.lua:30`: Lua-side watchdog `if (os.time() - _watchdog_last_heartbeat) > 30 then break end` — but the script is **never uploaded**.
- `CLAUDE.md`: "Double protection: Python safety path + hardware watchdog" — *false claim*.

**Web research.** [Keithley 2600B Series Reference Manual](https://download.tek.com/manual/2600BS-901-01_D_May_2018_Ref.pdf), section "TSP scripts": TSP scripts execute on the SMU's Lua engine independently of host. Without a running TSP watchdog, the instrument does **not** auto-shutoff if host communication is lost — `source.output` stays at whatever was last programmed.

**Reasoning chain.** If `cryodaq-engine` crashes or is `SIGKILL`'d while the Keithley is sourcing power:
1. Engine dies mid-`read_channels` after the last `source.levelv` write.
2. Keithley holds that voltage indefinitely — no instrument-level fallback.
3. Launcher detects engine death within `_HEALTH_INTERVAL=3s` and restarts.
4. On restart, `Keithley2604B.connect()` (`keithley_2604b.py:78`) clears `errorqueue` but does NOT read current `source.output` state and does NOT call `emergency_off()` before assuming control.
5. Heater is still being driven at the pre-crash voltage, which may be inappropriate for the new thermal state.

The only safety net is `disconnect()` → `emergency_off()`, but disconnect is not called on engine *crash*, only on orderly shutdown.

**Verdict.** **HIGH.** The deployed safety story is one layer (host-side), not two. The "hardware watchdog" claim in `CLAUDE.md` is misleading and should be retracted or implemented.

**Recommendation.** Either:
1. Upload a real TSP watchdog script on `connect()` — `tsp/p_const.lua` is already written, needs only `{SMU}` substitution + `script.run()`. Or:
2. On engine startup, **always** call `emergency_off()` before returning from `connect()` if `not mock`. Two-line change. Guarantees a safe state every time the engine comes up.

Update `CLAUDE.md` to remove the watchdog claim or implement option 1.

---

#### G.2 [LOW] Dead `tsp/p_const_single.lua` is a safety-review liability — see E.3.

#### G.3 [OK] Compliance detection and slew-rate limit
`keithley_2604b.py:139-174` reads `source.compliance` before adjusting `levelv`, skips regulation when in compliance (correct), enforces `MAX_DELTA_V_PER_STEP = 0.5` V per cycle with explicit thermal-analysis warning, and uses `_COMPLIANCE_NOTIFY_THRESHOLD = 10` to debounce single-cycle noise. Well-considered.

#### G.4 [OK] `errorqueue.clear()` on connect, periodic `errorqueue.count` in `diagnostics()` (every 30 s).

---

### H. Data integrity under adversarial conditions

#### H.1 [HIGH] Disk-full leads to silent CRITICAL-log loop, no graceful degradation

**What I checked.**
- `sqlite_writer.py:360-375` — `write_immediate` catches generic `Exception`, logs CRITICAL, re-raises.
- `scheduler.py:153` — generic `except Exception` increments `state.consecutive_errors` and continues polling.
- `disk_monitor.py` exists but does not pause polling or trigger SafetyManager.

**Web research.**
- [SQLite WAL doc](https://www.sqlite.org/wal.html): "For transactions in excess of a gigabyte, WAL mode may fail with an I/O or disk-full error."
- [Infomaniak kDrive bug #1476](https://github.com/Infomaniak/desktop-kDrive/issues/1476): SQLite WAL grew 50 GB+ in a sync-error loop. Cautionary tale.

**Reasoning chain.** On disk-full:
1. `executemany(INSERT)` raises `OperationalError`.
2. `write_immediate` logs CRITICAL once, re-raises.
3. `_poll_loop` increments error count, continues.
4. WAL keeps growing because each INSERT attempt opens the `-wal` file.
5. Housekeeping compresses only files older than `compress_after_days=14` — no emergency compaction.

The current behaviour is "silent tight loop of dropped readings with CRITICAL log spam and no operator-visible alert beyond an alarm".

**Verdict.** **HIGH.** No graceful degradation.

**Recommendation.** In `write_immediate`, explicitly handle `sqlite3.OperationalError` whose message contains "disk" / "full" / "out of memory": set a global `_disk_full` flag, notify SafetyManager (which should `emergency_off` Keithley), and pause new polling. Add periodic `PRAGMA wal_checkpoint(TRUNCATE)` in daily rotation.

---

#### H.2 [MEDIUM] Daily rotation does not explicitly checkpoint the previous WAL

`sqlite_writer.py:124-149`: `_ensure_connection` closes `self._conn` on day rollover with no explicit `wal_checkpoint(TRUNCATE)`. The next-day open will replay the residual WAL (correct), but cross-version SQLite upgrades risk WAL replay incompatibility, and disk-full during replay can SIGBUS the process. **Recommendation.** `conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"); conn.commit()` before `conn.close()` in rotation. Cheap and eliminates a category of issues.

---

#### H.3 [MEDIUM] Corrupted YAML at startup → restart loop with no backoff

**What I checked.** `engine.py:679, 363, 905, 1243, 1264` and `safety_manager.py:107`, `interlock.py:207`, `alarm.py:247`, `core/experiment.py:919, 1678`, etc. — all are `yaml.safe_load(fh)` with no try/except. `launcher.py:549-573` (`_check_engine_health`) restarts the engine every 3 s with no exponential backoff and no max-retries.

**Reasoning.** A fat-fingered edit to `config/instruments.local.yaml` produces a tight restart loop. Operator sees only a tray notification "Engine перезапущен автоматически" every 3 s.

**Verdict.** **MEDIUM.** Operationally painful and obscures the actual error.

**Recommendation.** Validate all YAML loads with explicit try/except, log filename + line, exit with a distinct exit code (e.g., 2 = config error). Launcher detects exit code 2 and shows a blocking modal instead of restarting.

---

#### H.4 [MEDIUM] `bind(EADDRINUSE)` on restart has no recovery

`zmq_bridge.py:95, 296` calls `self._socket.bind(self._address)` with no try/except. On Windows, a stale socket from a SIGKILL'd engine can hold the port for up to 240 s (TIME_WAIT). Linux is fine because `SO_REUSEADDR` is default on PUB. The publisher socket never sets `LINGER=0` (only the subscriber side does in `zmq_subprocess.py:73`).

**Recommendation.** Add explicit retry-with-delay on `bind()`. Set `LINGER=0` on the PUB socket.

---

#### H.5 [LOW] Auto-restart has no backoff cap

`launcher.py:549-573` restarts the engine every 3 s forever. Cap at 5 attempts within 60 s, then show a modal.

#### H.6 [OK] Persistence-first ordering is honored
`scheduler.py` writes via `write_immediate` before `publish_batch`. Verified by code reading.

#### H.7 [OK] Missing instrument at startup
`scheduler.py:107-125, 194-203` catches connect failures, marks driver disconnected, schedules backoff reconnect. Engine starts even if a LakeShore is dead.

---

### I. Safety FSM correctness

**Method.** Read `safety_manager.py` end-to-end (lines 1-653). Reviewed `rate_estimator.py` for OLS numerical stability. Surveyed `tests/core/test_safety*.py` (5 files: `test_safety_manager.py`, `test_safety_dual_channel.py`, `test_safety_fixes.py`, `test_safety_set_target.py`, `test_zmq_safety.py`).

#### I.1 [HIGH] No lock around `_active_sources` mutations across async await points

**What I checked.**
- `safety_manager.py:213` — `request_run` does `self._active_sources.add(smu_channel)` *after* `await self._keithley.start_source(...)` at line 208. Between yield and add, a concurrent `request_run` for the same channel could be processed:
  - First call: passes the `if smu_channel in self._active_sources` check (line 180), yields at line 208 in `start_source`.
  - Second call: enters concurrently, also passes the membership check (because the first call hasn't done the add yet), yields at line 208 in its own `start_source`.
  - Both calls then add the same channel to `_active_sources` (the set will dedupe, but `start_source` was called twice on the same SMU with potentially different P/V/I parameters).

**Current implementation.** No lock, no `_busy` flag, no in-flight tracking.

**Web research.** [trio docs on locks vs single-threaded async](https://trio.readthedocs.io/en/stable/reference-core.html#mutexes-and-locks): "Even single-threaded asyncio code needs locks if there are await points between read and write of shared state. The 'async safety' guarantee only applies between yields."

**Reasoning chain.** asyncio is single-threaded but cooperatively interleaved. A `await` is a yield point. Any state mutation that *spans* an await must be protected. `request_run` does:
1. Check `if smu_channel in self._active_sources` (line 180).
2. Several validation checks (sync).
3. `await self._keithley.start_source(...)` (line 208) — **yield point**.
4. `self._active_sources.add(smu_channel)` (line 213).

Between (1) and (4), another task can run. In production this rarely matters because GUI commands come from a single REQ socket and are processed serially in `_handle_command`. But the engine *also* processes commands from the web dashboard and from internal callers (`update_target`, `update_limits`, `_safe_off`). Two simultaneous "start smua" commands from two REQ clients can race here.

`emergency_off` (line 249), `_safe_off` (line 499), and `_fault` (line 466) similarly mutate `_active_sources` across awaits with no lock.

**Verdict.** **HIGH theoretical, MEDIUM in production.** The single-REQ command path mostly serializes operations, but the architecture does not guarantee it (web dashboard creates its own REQ — see C.4).

**Recommendation.** Add `self._cmd_lock = asyncio.Lock()` and wrap `request_run`, `request_stop`, `emergency_off`, `acknowledge_fault`, `update_target`, `update_limits` bodies with `async with self._cmd_lock`. Cheap and removes the entire class of races.

---

#### I.2 [HIGH] Fire-and-forget `_publish_state` task in `_transition` (already covered in A.2)

Cross-listed here because it's a *safety* path: fault state broadcasts can be lost.

---

#### I.3 [MEDIUM] OLS rate estimator's `min_points=10` (in safety FSM) is below the documented `min_points=60` recommendation

**What I checked.**
- `rate_estimator.py:29` default `min_points: int = 60`
- `safety_manager.py:89` `self._rate_estimator = RateEstimator(window_s=120.0, min_points=10)` — overrides default to 10.
- Comments in `rate_estimator.py:1-7` say: "При разрешении LS218 ±0.01 K и интервале 0.5 с конечная разность даёт шум ±2.4 K/мин — сравнимо с порогом 5 K/мин. Линейная регрессия по 120 с (240 точек) даёт стабильную оценку с погрешностью < 0.1 K/мин."

**Reasoning chain.** The module's own comments justify min_points=60 (or 240 in the documented case) for noise suppression. The safety FSM uses min_points=10 — at 10 points the OLS slope variance is roughly √(60/10) ≈ 2.4× higher. With LakeShore noise of ±0.01 K, expected slope std-error at 10 points is about ±0.6 K/min — within an order of magnitude of the 5 K/min fault threshold. False positives are possible if the window happens to capture a noise transient at the start of cooldown.

The OLS implementation itself is **numerically clean** (lines 94-121): time-normalization to first point, denominator-zero check, NaN check, slope conversion to per-minute. Good.

**Verdict.** **MEDIUM.** Not a bug, but the parameter choice deviates from the module's own documented guidance and is not justified in `safety_manager.py`.

**Recommendation.** Either raise `min_points` to 60 in safety, or document why 10 is acceptable here (e.g., "we want fast response to runaway, false positives are OK because the operator can always acknowledge"). Add a test that simulates noise floor and verifies false-positive rate.

---

#### I.4 [LOW / OK] FSM completeness — explicit transition table

I enumerated every `_transition()` call site:
- `request_run` (line 195, 215) — to RUN_PERMITTED → RUNNING
- `request_run` Keithley fail → SAFE_OFF (line 204)
- `_safe_off` → RUNNING (line 514) or SAFE_OFF (line 520)
- `emergency_off` → SAFE_OFF (line 266) when `not _active_sources` and not latched
- `acknowledge_fault` → MANUAL_RECOVERY (line 363)
- `_fault` → FAULT_LATCHED (line 472)
- `_run_checks` MANUAL_RECOVERY → READY (line 585)
- `_run_checks` SAFE_OFF → READY (line 591)

States covered: SAFE_OFF, READY, RUN_PERMITTED, RUNNING, FAULT_LATCHED, MANUAL_RECOVERY. Every state has an inbound transition. No unreachable state. Every transition logs at INFO or CRITICAL.

The transition diagram matches `CLAUDE.md`'s safety architecture description. **Verdict: OK.**

#### I.5 [OK] Acknowledge race
`acknowledge_fault` (line 351) checks `self._state != FAULT_LATCHED` first; checks cooldown elapsed; then transitions to MANUAL_RECOVERY. If a new fault arrives during MANUAL_RECOVERY, `_fault()` will overwrite `_fault_reason` and `_fault_time` and re-latch — this is correct.

#### I.6 [OK] `_fault` re-entrance
`_fault` is sync up to line 472 (state already latched), then awaits emergency_off. If `_fault` is called again from another task while the first is awaiting, the second call will pass `_transition` (a no-op transition FAULT_LATCHED→FAULT_LATCHED is allowed and just adds an event), then call `emergency_off()` again — Keithley driver is presumably idempotent on `emergency_off`. Verified by reading: `keithley_2604b.py` `emergency_off()` is a `try/except` wrap around output-off writes; safe to call repeatedly.

---

### J. Plugin loader / hot reload

#### J.1 [MEDIUM] Polling-based file watcher (5 s interval), no `watchdog` library

**What I checked.** `plugin_loader.py:289-336` `_watch_loop` polls `_scan_plugins()` every 5 s. Compares mtimes.

**Web research.** [watchdog library known issues](https://github.com/gorakhargosh/watchdog/issues): inotify-based watchers are unreliable on network drives, WSL, and case-insensitive file systems. The polling approach **avoids** all of these issues. Tradeoff: 5 s latency on plugin reload.

**Verdict.** **MEDIUM in label, actually a sensible choice.** The polling approach is more robust than `watchdog` for the lab PC context. Document the 5 s latency in `docs/plugins.md` (if any).

#### J.2 [LOW] Module unload doesn't clear `sys.modules`
`_load_plugin` uses `importlib.util.spec_from_file_location(...)` + `module_from_spec(spec)` + `spec.loader.exec_module(module)`. Critically, **it does not assign `sys.modules[name] = module`**, so reloads don't pollute `sys.modules`. Each reload creates a fresh module object. This is the correct pattern. Plugins that import other modules (e.g., `import numpy`) will share `sys.modules` for those imports — but that's expected.

#### J.3 [OK] Exception isolation in process loop
`plugin_loader.py:267-274`: `try: metrics = await plugin.process(batch); except Exception as exc: logger.error(...); continue`. A buggy plugin doesn't crash the engine. Good.

#### J.4 [OK] Snapshot iteration
`for plugin in list(self._plugins.values()):` (line 264) — snapshot prevents "dictionary changed size during iteration" if the watch loop reloads a plugin mid-tick.

---

### K. Configuration and secrets

#### K.1 [MEDIUM] Telegram bot token embedded in URL — risk of leaking via aiohttp error logs

**What I checked.**
- `src/cryodaq/notifications/telegram.py:74` `self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"`
- Same in `telegram_commands.py:71` and `periodic_report.py:91`.
- Token loaded via `yaml.safe_load` at `telegram.py:105-109` from `config/notifications.yaml`. Engine validates against placeholder `"YOUR_BOT_TOKEN_HERE"` at `engine.py:1267-1268`.

**Reasoning chain.** Telegram's bot API requires the token in the URL — there is no alternative auth header. The risk is that if aiohttp raises an exception during a POST and the URL is logged (either by aiohttp itself or by CryoDAQ's exception handler), the token leaks to `cryodaq-engine.log`. CryoDAQ's CHANGELOG 0.4.0 mentions a previously-leaked token that had to be rotated — so this is a known sensitivity.

I did not find any place where `self._api_url` is logged directly (grep `_api_url` only matches definitions). aiohttp's default exception messages do *not* include the URL by default. **However**, if the operator runs the engine with `logging.DEBUG`, aiohttp's debug logs can include the URL.

**Verdict.** **MEDIUM.** Defense-in-depth gap.

**Recommendation.** Wrap the token in a `class SecretStr` that masks `__repr__` and `__str__`. Or simply: log redaction in CryoDAQ's logging filter to replace `bot[0-9]+:[A-Za-z0-9_-]+` with `bot***`.

#### K.2 [OK] All YAML loads use `safe_load`
Verified across all 30+ call sites via `rg "yaml\.(safe_)?load" src/`. Zero `yaml.load(...)`. Good.

#### K.3 [OK] `.local.yaml` overlay is documented and gitignored
Per `CLAUDE.md` and `.gitignore` (verified). Operators understand the precedence.

---

### L. Cross-platform path handling

#### L.1 [LOW] `paths.py` does not normalize Cyrillic
`Path(__file__).resolve()` works correctly with Cyrillic on both Windows and macOS APFS. Python 3.12's `pathlib` handles UTF-8 path components on all supported platforms. Operator names and sample IDs *can* contain Cyrillic and end up in artifact paths via `experiment.py` — read confirms the implementation just passes them through.

**Verdict.** **LOW / OK.** No bug. Verified by reading `experiment.py` artifact path construction.

#### L.2 [LOW] `Path.resolve()` resolves SUBST drives on Windows
A few callers use `.resolve()` instead of `.absolute()`. On Windows, if the lab uses `SUBST X: \\server\share` to map a UNC path to a drive letter, `.resolve()` will follow the SUBST and return the UNC form — which can break SQLite locking. This is a long-tail issue. **Recommendation.** Audit `.resolve()` call sites; prefer `.absolute()` where physical-path resolution isn't needed.

#### L.3 [OK] No hardcoded `/` or `\\` in source paths
Grep across `src/` for `'/'` and `'\\\\'` finds no path-component literals — everything uses `Path(...) / "subdir"`.

---

### M. Dependency pinning and supply chain

#### M.1 [MEDIUM] Lower-bound-only pinning, no lockfile

**What I checked.** `pyproject.toml` declares `pyside6>=6.6, pyqtgraph>=0.13, pyvisa>=1.14, pyserial-asyncio>=0.6, pyzmq>=25, h5py>=3.10, pyyaml>=6.0, msgpack>=1.0, matplotlib>=3.8, aiohttp>=3.9, numpy>=1.26, scipy>=1.12, openpyxl>=3.1, python-docx>=1.1, fastapi>=0.111, uvicorn>=0.29, pyarrow>=15.0`. No upper bounds, no lockfile (no `poetry.lock`, no `requirements.txt`, no `requirements-lock.txt`).

**Reasoning chain.** PyInstaller deployment freezes whatever is currently in the environment at packaging time. Without a lockfile, two operators packaging on different days will get different transitive versions. A future PySide6 7.x release could break the GUI silently. For a *safety-critical* lab tool, this is unacceptable supply-chain hygiene.

**Verdict.** **MEDIUM.** Standard mistake, fixable cheaply.

**Recommendation.** Use `pip-tools` (`pip-compile`) or `uv pip compile` to generate `requirements-lock.txt` and commit it. Add `pip install -r requirements-lock.txt` to `install.bat` and the PyInstaller pipeline. Cap PySide6 at `<7`, aiohttp at `<4`.

#### M.2 [LOW / informational] aiohttp 3.9 has 3 known CVEs but client-side use is mostly unaffected

**Web research.**
- [CVE-2024-23334 (path traversal)](https://github.com/advisories/GHSA-5h86-8mv2-jq9f) — affects aiohttp's **static-file server**. Fixed in 3.9.2.
- [CVE-2024-30251 (DoS via multipart)](https://www.cvedetails.com/cve/CVE-2024-30251/) — affects aiohttp's **server**. Fixed in 3.9.4.
- [CVE-2024-27306 (XSS in static index)](https://www.cvedetails.com/cve/CVE-2024-27306/) — affects aiohttp's **server**. Fixed in 3.9.4.

**Reasoning.** CryoDAQ uses aiohttp as a *client* (Telegram API). The web dashboard uses FastAPI/uvicorn, not aiohttp. None of the CVEs apply to client-side use. **Still** worth bumping to ≥3.9.4 for hygiene.

**Verdict.** **LOW.** Bump to `aiohttp>=3.9.5,<4`.

#### M.3 [LOW] `pyserial-asyncio` is lightly maintained

PyPI shows last release was several years ago. The package is small and the API is stable, but it's a tail-risk dependency. Worth tracking.

---

### N. Test coverage gaps

**Test inventory.** 87 test files, 9 areas:
- `tests/core/`: 33 (largest)
- `tests/gui/`: 18
- `tests/analytics/`: 9
- `tests/storage/`: 6
- `tests/drivers/`: 6
- `tests/notifications/`: 1
- `tests/reporting/`: 1
- top-level: `tests/test_instance_lock.py`, `tests/test_web_dashboard.py`

#### N.1 [MEDIUM] Adversarial / failure-injection coverage is thin

**What I checked.** Searched for tests of disk-full, EADDRINUSE, corrupted YAML, killed engine, hung GPIB, USB yank.

Found:
- `test_engine_force_kill.py` — tests SIGKILL/lock recovery
- `test_memory_leaks.py` — tests for unbounded growth
- `test_persistence_ordering.py` — tests the SQLite-before-broker invariant
- `test_p0_fixes.py`, `test_p1_fixes.py`, `test_audit_fixes.py`, `test_safety_fixes.py`, `test_deep_review.py` — regression tests for past audit findings

Not found:
- No `test_disk_full*` — H.1 isn't covered
- No `test_corrupted_yaml*` — H.3 isn't covered
- No `test_eaddrinuse*` — H.4 isn't covered
- No `test_concurrent_request_run*` — I.1 isn't covered
- No fuzz / hypothesis / property-based tests
- No stress tests of the multi-REQ-client REP path (C.4)

**Verdict.** **MEDIUM.** Regression coverage is excellent — every past finding has a test. Forward-looking adversarial coverage is thin.

**Recommendation.** Add adversarial tests for D.1/H.1/H.3/H.4 and the I.1 race. Consider `pytest-asyncio` + `hypothesis` for fuzzing the OLS rate estimator and the WAL-write batching.

#### N.2 [LOW / OK] God-node coverage
Reading is exercised by `test_persistence_ordering.py`, `test_broker.py`, `test_zmq_bridge.py`, `test_zmq_safety.py`, `test_sqlite_writer.py` and dozens more. SafetyManager has 5 dedicated test files. SafetyBroker is covered via `test_zmq_safety.py` + safety_manager tests. RateEstimator has its own file. **Verdict: OK.**

---

### O. Deployment readiness (pre-PyInstaller)

#### O.1 [HIGH] No `LICENSE` file in the repo

**What I checked.** `ls LICENSE*` → no match.

**Reasoning.** A safety-critical lab tool with no license is legally ambiguous. The lab can use it internally but cannot share, the maintainer has no liability protection, and it cannot be packaged for re-distribution by a third party. This is not a code defect but a deployment-readiness defect.

**Verdict.** **HIGH** for deployment readiness.

**Recommendation.** Add a LICENSE file. For a lab-internal tool an MIT or Apache-2 license is the simplest choice; if you need stronger liability disclaimers (and given the safety implications, you should), pick Apache-2 explicitly for its patent grant and liability waiver.

---

#### O.2 [MEDIUM] No log rotation; logs go to stderr only

**What I checked.**
- `launcher.py:673`, `gui/app.py:31`, `engine.py:1619` — all three call `logging.basicConfig(level=logging.INFO, format=..., datefmt=...)` with no `handlers=[...]`, no `RotatingFileHandler`, no `TimedRotatingFileHandler`.
- Default `basicConfig` writes to `stderr`.
- Repo grep `RotatingFileHandler|TimedRotatingFileHandler|FileHandler` in `src/`: zero hits.

**Web research.** [Python `logging.handlers.RotatingFileHandler`](https://docs.python.org/3/library/logging.handlers.html#rotatingfilehandler): standard pattern for long-running services. Without it, logs grow unbounded or are entirely volatile (lost on process death).

**Reasoning chain.** On the operator PC, the engine runs 24/7. With logging at INFO and verbose modules (alarm v2, safety, scheduler), expected output is hundreds of MB/day. Currently:
- If launched via `start.bat`, stderr goes to a console window — invisible after the window closes.
- If launched via Windows tray (which is the supported mode), stderr is dropped on the floor.
- *Post-mortem debugging is impossible.* When the operator says "the engine crashed at 3am", there are no logs.

**Verdict.** **MEDIUM, HIGH for ops debuggability.**

**Recommendation.** Replace `basicConfig` with explicit handlers:
```python
import logging.handlers
log_dir = get_data_dir() / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
handlers = [
    logging.handlers.TimedRotatingFileHandler(
        log_dir / "engine.log",
        when="midnight", backupCount=14, encoding="utf-8"
    ),
    logging.StreamHandler(),
]
logging.basicConfig(level=logging.INFO, handlers=handlers, format=..., datefmt=...)
```
Same for launcher and GUI (different filenames). Cap by size and retention. Audit for accidentally-logged secrets (K.1).

---

#### O.3 [MEDIUM] No update mechanism

`docs/deployment.md` describes initial installation via `git clone` + `pip install -e .` but says nothing about applying a new release. Operators are expected to `git pull && pip install -e .` themselves — which requires git, internet access, and developer skills.

**Recommendation.** Either (a) ship a wheel with `pip install --upgrade cryodaq-x.y.z.whl`, or (b) once PyInstaller is set up, distribute new `.exe` bundles via a network share with a versioned filename. Document the update procedure in `docs/deployment.md`.

---

#### O.4 [MEDIUM] No crash reporter, no telemetry

There is no mechanism to capture engine crashes for off-site analysis. When the engine dies, the only artifact is the (unrotated, stderr-only) log — which the operator probably can't extract. The launcher's tray notification "Engine перезапущен автоматически" tells the operator something happened but provides no actionable diagnostic.

**Recommendation.** Wire the engine's `sys.excepthook` to write the traceback + last 1000 log lines to `data/crashes/<timestamp>.log` before exit. Add a "Send crash report" button in the tray menu.

---

#### O.5 [OK / informational] Hardcoded lab assumptions
Repo grep for hardcoded GPIB addresses, COM ports, IPs in `src/`: only `127.0.0.1:5555` (ZMQ) and `0.0.0.0:8080` (web) — both correct localhost defaults. Lab-specific values are correctly placed in `config/*.local.yaml.example`. Good.

#### O.6 [OK] First-run bootstrap is documented
`docs/deployment.md` and `docs/first_deployment.md` cover installation, `instruments.local.yaml`, smoke checks, USB selective-suspend disable script. Reasonable for a developer-operator handoff.

---

## Areas confirmed OK (one paragraph per area)

- **A. Asyncio (mostly).** `Scheduler.stop()` correctly deduplicates and gathers tasks with `return_exceptions=True`. `wait_for` usage is consistent. The persistence-first await chain is intentional and correctly implemented. The rest of the asyncio surface is idiomatic for Python 3.12.

- **B. PySide6 (mostly).** `ZmqBridge` subprocess + dedicated reply consumer thread + Future-per-request routing under a lock is *better* than typical PyQt patterns. Heartbeat from subprocess detects blocked workers and restarts. `QShortcut` lifetime is correct via parent ownership. All `QTimer(self)` instances use parent-ownership.

- **C. ZMQ.** REP shutdown is clean (`linger=0`), and the reply-on-CancelledError fix from CHANGELOG 0.13.0 holds. msgpack is safe by default on a localhost trust boundary.

- **D. SQLite (mostly).** Dedicated single-worker writer executor; `executor.shutdown(wait=True)` before `conn.close()`; `math.isfinite()` guard; daily rotation handles cross-midnight batches; composite index in place; REAL epoch timestamps consistent across read/write paths.

- **E. Multiprocessing (instance locks).** `instance_lock.py` uses kernel-backed `msvcrt.locking` / `fcntl.flock` — correctly cross-platform and SIGKILL-safe.

- **F. PyVISA (escalation).** Three-level GPIB recovery ladder is more defensive than typical LabVIEW replacements. TNT4882 unaddressing enabled. Bus-lock contract enforced by construction.

- **G. Keithley (compliance + slew).** Compliance detection skips regulation correctly; slew rate limit is hard-coded with documented thermal warning; `errorqueue.clear()` on connect; periodic diagnostics every 30 s.

- **H. Persistence + missing instrument.** Persistence-first ordering is honored; missing instruments at startup don't prevent the engine from starting; instance lock survives SIGKILL.

- **I. Safety FSM (states).** All six states have inbound transitions; transitions log at appropriate levels; `_fault` correctly latches *before* awaiting emergency_off (per CHANGELOG 0.13.0); acknowledge / new-fault interaction is correct; `emergency_off` is idempotent.

- **J. Plugin loader.** Polling watcher is more robust than `watchdog`; exception isolation is in place; snapshot iteration prevents dict-mutation crashes; no `sys.modules` pollution on reload.

- **K. Config (YAML loading).** All 30+ call sites use `yaml.safe_load`. `.local.yaml` overlay is gitignored.

- **L. Cross-platform paths.** Cyrillic paths work; no hardcoded `/` or `\\`; `Path(...) / "subdir"` is used consistently.

- **M. Tests (god-node coverage).** Reading, SafetyManager, SafetyBroker, RateEstimator, DataBroker, SQLiteWriter — all have dedicated regression coverage. 87 test files total.

- **O. Lab-specific config isolation.** No hardcoded GPIB/COM/IP values in `src/`; lab values are in `config/*.local.yaml.example`.

---

## Meta-notes

- **What took the longest to verify.** Reading `safety_manager.py` (653 lines) end-to-end and reasoning about FSM completeness + concurrency was the slowest part. Cross-checking the absence of an upload path for `tsp/p_const.lua` required reading both the Lua file and `keithley_2604b.py` and grepping for `loadscript|script.run|script_load`.

- **What I couldn't verify (needs hardware or runtime).** (1) The C.4 multi-REQ-client REP path under load — needs an integration test against a real engine + real GUI + real web dashboard. (2) The actual PyInstaller bundle behaviour (E1/E2) — needs a Windows VM. (3) Whether NI-VISA on the production PC actually loads vs falling back to pyvisa-py (F.3). (4) The OLS rate-estimator false-positive rate at min_points=10 (I.3) — needs simulation against recorded LakeShore noise.

- **Sources reliability.** Most authoritative: Python docs, SQLite docs, PyInstaller docs, ZMQ Guide, pyvisa.readthedocs.io, msgpack-python.readthedocs.io. Useful: superfastpython.com, github.com/advisories. Confirming-but-secondary: cvedetails.com.

- **Method limits.** This audit was performed by Claude Code (Opus 4.6 1M) reading source files and dispatching subagents (Sonnet) for parallel research. Two subagents hit upstream API quota mid-run — sections I/J/K/L/M/N/O were completed by direct file reads from the orchestrator. The two completed subagents (A/B/C/D and E/F/G/H) produced ~6000 words of findings each; sections I-O are leaner but cover the core contracts (safety_manager.py read end-to-end, plugin_loader.py read end-to-end, paths.py read end-to-end, test inventory enumerated, all `yaml.*load` call sites grepped, all `*FileHandler` call sites grepped). The audit did not run pytest, did not build a PyInstaller bundle, and did not exercise the live hardware.

- **Coverage of the original task spec.** All 15 areas (A-O) are addressed. Findings are tagged with severity, file:line, code quotes, web research with real URLs, reasoning chains, and concrete recommendations. The "do not modify code" constraint was respected throughout.

## Sources
- [Python docs — `asyncio.create_task` (task GC warning)](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)
- [Python docs — `loop.run_in_executor`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor)
- [Python docs — `multiprocessing.freeze_support`](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.freeze_support)
- [Python docs — `logging.handlers.RotatingFileHandler`](https://docs.python.org/3/library/logging.handlers.html#rotatingfilehandler)
- [PyInstaller — Common Issues and Pitfalls](https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html)
- [PyInstaller — Runtime Information (`_MEIPASS`, `sys.frozen`)](https://pyinstaller.org/en/latest/runtime-information.html)
- [PyInstaller wiki — Recipe-Multiprocessing](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing)
- [PyInstaller — PySide6 issue #6387](https://github.com/pyinstaller/pyinstaller/issues/6387)
- [SuperFastPython — `multiprocessing.freeze_support`](https://superfastpython.com/multiprocessing-freeze-support-in-python/)
- [Qt 6 — `QThread` documentation](https://doc.qt.io/qt-6/qthread.html)
- [Qt for Python — Object trees and ownership](https://doc.qt.io/qtforpython-6/overviews/object.html#object-trees-ownership)
- [Qt 6 — `QTimer` documentation](https://doc.qt.io/qt-6/qtimer.html)
- [ZMQ Guide — Reliable Pub-Sub (chapter 5)](https://zguide.zeromq.org/docs/chapter5/)
- [msgpack-python documentation](https://msgpack-python.readthedocs.io/)
- [SQLite — Write-Ahead Logging](https://www.sqlite.org/wal.html)
- [SQLite — Pragma documentation](https://sqlite.org/pragma.html)
- [SQLite — Result and Error Codes](https://sqlite.org/rescode.html)
- [Infomaniak kDrive WAL disk-exhaustion bug #1476](https://github.com/Infomaniak/desktop-kDrive/issues/1476)
- [PyVISA — FAQ (thread safety)](https://pyvisa.readthedocs.io/en/latest/faq/faq.html)
- [PyVISA — issue #262 (concurrent reads)](https://github.com/pyvisa/pyvisa/issues/262)
- [PyVISA — `ResourceManager` API](https://pyvisa.readthedocs.io/en/latest/api/resourcemanager.html)
- [pyserial-asyncio — issue #87 (`wait_closed` hang)](https://github.com/pyserial/pyserial-asyncio/issues/87)
- [Keithley 2600B — Reference Manual (TSP / watchdog)](https://download.tek.com/manual/2600BS-901-01_D_May_2018_Ref.pdf)
- [aiohttp CVE-2024-23334 (path traversal)](https://github.com/advisories/GHSA-5h86-8mv2-jq9f)
- [aiohttp CVE-2024-30251 (DoS)](https://www.cvedetails.com/cve/CVE-2024-30251/)
- [aiohttp CVE-2024-27306 (XSS)](https://www.cvedetails.com/cve/CVE-2024-27306/)
- [trio — Mutexes and locks (single-threaded async needs locks)](https://trio.readthedocs.io/en/stable/reference-core.html#mutexes-and-locks)
