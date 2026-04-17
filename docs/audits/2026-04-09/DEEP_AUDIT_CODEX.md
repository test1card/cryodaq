# CryoDAQ — Deep Audit (Codex)

Date: 2026-04-08
Duration: 35m
Areas checked: 15
Web sources consulted: 18

## Executive summary

40 findings total: 10 HIGH, 23 MEDIUM, 1 LOW, 6 OK.

Top concerns before deployment:

1. The codebase is still documented and implemented around `pip install -e .`, while the target deployment is now a PyInstaller `onedir` bundle. The frozen-path, data-file, restart, and packaging story is incomplete.
2. SQLite WAL use is generally reasonable, but Ubuntu 22.04 ships SQLite `3.37.2`, which is inside the range affected by SQLite's March 2026 WAL-reset corruption bug. CryoDAQ uses WAL with multiple connections across threads/processes.
3. Several safety and UI paths still have sharp edges: fire-and-forget `QThread` lifetime, blocking GUI round-trips, and interlock actions collapsing into the same latched-fault behavior.

## Findings

### A. Asyncio correctness

#### A.1 [MEDIUM] Deprecated global event-loop policy is still hard-coded

**What I checked:** `src/cryodaq/launcher.py:23-25`, `src/cryodaq/engine.py:23-25`, `CLAUDE.md:207-211`.
**Current implementation:** Both launcher and engine call `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` on Windows and treat the warning as a known limitation.
**Web research:** Python 3.14 deprecates the asyncio policy system and specifically deprecates `WindowsSelectorEventLoopPolicy`; docs recommend `asyncio.run(..., loop_factory=...)` instead. Sources: [Python 3.14 deprecations](https://docs.python.org/3.14/deprecations/index.html), [What's New in Python 3.14](https://docs.python.org/ja/3.15/whatsnew/3.14.html).
**Reasoning chain:** This is not an immediate correctness bug on the target Ubuntu deployment, but it is technical debt in operator entry points and contradicts the stated goal of imminent packaging. The current pattern will become a removal issue on future Python upgrades rather than a mere warning.
**Verdict:** Real maintenance risk; not a blocker for Ubuntu 22.04, but should be retired before freezing a long-lived runtime image.
**Recommendation:** Move Windows-specific loop selection into `asyncio.run(..., loop_factory=...)` wrappers or a small compatibility layer instead of policy mutation at import time.

#### A.2 [OK] Blocking hardware I/O is kept off the engine event loop

**What I checked:** `src/cryodaq/drivers/transport/gpib.py:94-96,193-253`, `src/cryodaq/drivers/transport/usbtmc.py:54-67,172-210`, `src/cryodaq/drivers/transport/serial.py:61-67,163-167`.
**Current implementation:** VISA calls are pushed into executors; serial uses `serial_asyncio`; driver contract says core I/O must never block the loop.
**Web research:** Python's asyncio guidance says blocking code "should not be called directly" and should use an executor or thread helper. Sources: [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html), [asyncio.to_thread() docs](https://docs.python.org/3/library/asyncio-task.html).
**Reasoning chain:** The code follows mainstream asyncio practice for the real blocking surfaces: VISA open/query/write/close are not run on the event-loop thread, and RS-232 is stream-based.
**Verdict:** This part is sound.
**Recommendation:** Keep new hardware paths aligned with this pattern; do not add direct pyvisa/pyserial calls in engine tasks.

### B. PySide6 threading model

#### B.1 [HIGH] Emergency-off worker threads are not retained, parented, or joined

**What I checked:** `src/cryodaq/gui/main_window.py:259-264`, `src/cryodaq/gui/zmq_client.py:251-262`.
**Current implementation:** Emergency-off creates two `ZmqCommandWorker(QThread)` instances in a loop, connects `finished` to `lambda r: None`, and immediately loses all references.
**Web research:** Qt recommends connecting `finished()` to `deleteLater()` and using `wait()` when synchronization matters; Qt also notes that queued cross-thread work needs proper object lifetime management. Sources: [QThread docs](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QThread.html), [QObject docs](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QObject.html), [Threads and QObjects overview](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html).
**Reasoning chain:** In Qt, "fire and forget" is not free. Losing the Python references means lifetime falls back to QObject ownership rules and GC timing. That is exactly the class of bug that shows up as `QThread: Destroyed while thread is still running` or silent dropped completion.
**Verdict:** High-risk GUI/threading defect in a safety-critical action path.
**Recommendation:** Store these workers in an owned collection, parent them to the window, connect `finished` to cleanup, and do not let them die untracked.

#### B.2 [MEDIUM] Autosweep still performs blocking ZMQ round-trips on the UI thread

**What I checked:** `src/cryodaq/gui/widgets/autosweep_panel.py:383-388,410-417,423-427,638-677`, `src/cryodaq/gui/zmq_client.py:238-242`.
**Current implementation:** Autosweep start/stop and experiment attach use synchronous `send_command(...)`, which blocks until the bridge reply arrives or times out.
**Web research:** Qt expects responsive UI/event-loop ownership; asyncio guidance likewise says blocking code delays all other work in the same thread. Sources: [QThread docs](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QThread.html), [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html).
**Reasoning chain:** These calls are operator-facing and can happen exactly when the system is under load or the engine is degraded. A five-second stall in the GUI during a sweep or stop request is an operational bug even if it eventually recovers.
**Verdict:** Real responsiveness risk, especially during degraded engine conditions.
**Recommendation:** Move these commands onto `ZmqCommandWorker` or a single dedicated async command helper, matching the newer non-blocking panels.

#### B.3 [MEDIUM] Experiment workspace refresh still blocks the UI thread

**What I checked:** `src/cryodaq/gui/widgets/experiment_workspace.py:81-99`, `tests/gui/test_experiment_workspace.py:129`.
**Current implementation:** `refresh_state()` calls blocking `send_command({"cmd": "experiment_status"})` directly; tests explicitly patch that blocking path.
**Web research:** Qt's event-driven threading guidance and Python's blocking-code guidance both warn that direct blocking work in the main thread stalls all UI processing. Sources: [Threads and QObjects overview](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html), [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html).
**Reasoning chain:** This is less dangerous than autosweep because it is not a control loop, but it still hurts operator trust: the workspace can hang during refresh exactly when the engine is slow.
**Verdict:** Medium UI latency bug.
**Recommendation:** Make `refresh_state()` asynchronous-by-worker like `_update_phase_display()`.

#### B.4 [OK] Some high-frequency GUI paths are explicitly guarded against blocking calls

**What I checked:** `tests/gui/test_keithley_debounce.py:6-35`, `tests/gui/test_conductivity_nonblocking.py:8-30`, `src/cryodaq/gui/widgets/keithley_panel.py`, `src/cryodaq/gui/widgets/conductivity_panel.py`.
**Current implementation:** AST-based tests fail if live-update and auto-sweep methods in the Keithley and conductivity panels call blocking `send_command`.
**Web research:** Qt documents queued cross-thread work as the safe model; blocking UI-thread work is what should be avoided. Sources: [QThread docs](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QThread.html), [Threads and QObjects overview](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html).
**Reasoning chain:** This is the right direction: the repo has begun encoding GUI non-blocking expectations as regression tests rather than relying on reviewer memory.
**Verdict:** Good practice already in place for the hottest GUI paths.
**Recommendation:** Extend the same AST/contract-test pattern to autosweep and workspace refresh.

### C. ZMQ patterns

#### C.1 [MEDIUM] Heartbeats share the same bounded queue as data and can be delayed behind backlog

**What I checked:** `src/cryodaq/core/zmq_subprocess.py:97-109,140-147`, `src/cryodaq/gui/zmq_client.py:118-146`, `tests/core/test_zmq_subprocess.py:113-127`.
**Current implementation:** The bridge puts readings, warnings, and heartbeats into one `multiprocessing.Queue`; if the queue is full, heartbeats are dropped.
**Web research:** The ZeroMQ Guide warns that high data volume and delayed heartbeats produce "false timeouts" and that subscribers that cannot keep up will overflow queues and lose data. Sources: [ØMQ Guide, chapter 4](https://zguide.zeromq.org/docs/chapter4/), [ØMQ Guide, chapter 5](https://zguide.zeromq.org/docs/chapter5/).
**Reasoning chain:** CryoDAQ's health model uses heartbeat age, not merely process liveness. Because heartbeats ride the same queue as telemetry, a busy queue can look like a dead bridge even when the subprocess is alive and still ingesting ZMQ.
**Verdict:** Plausible false-restart path under burst load.
**Recommendation:** Treat any data dequeue as liveness, or move heartbeats to a separate queue/channel.

#### C.2 [MEDIUM] Initial safety state is published before the PUB path is started

**What I checked:** `src/cryodaq/core/safety_manager.py:134-140`, `src/cryodaq/engine.py:1314-1319`.
**Current implementation:** `SafetyManager.start()` publishes initial safety and Keithley channel state before `zmq_pub.start(...)` is called.
**Web research:** ZeroMQ PUB/SUB has slow-joiner behavior: subscribers miss messages sent before they are connected, and publishers cannot know when subscribers are ready. Source: [ØMQ Guide, chapter 5](https://zguide.zeromq.org/docs/chapter5/).
**Reasoning chain:** The code does have synchronous command fallbacks for some state, so this is not catastrophic. But live consumers depending on the initial publication can start "unknown" until the next relevant event arrives.
**Verdict:** Boot-time state propagation gap.
**Recommendation:** Start PUB earlier or replay a last-value snapshot after transport startup.

#### C.3 [OK] REQ recovery options are configured the right way

**What I checked:** `src/cryodaq/core/zmq_subprocess.py:80-85`.
**Current implementation:** The REQ socket sets both `REQ_RELAXED` and `REQ_CORRELATE`.
**Web research:** libzmq documents that `ZMQ_REQ_RELAXED` allows a new request after timeout but may discard prior replies, and recommends `ZMQ_REQ_CORRELATE` so mismatched replies are ignored safely. Source: [libzmq socket options](https://libzmq.readthedocs.io/en/latest/zmq_setsockopt.html).
**Reasoning chain:** This is exactly the right pair for a proxy bridge that may retry or recover after timeouts.
**Verdict:** Good defensive REQ/REP configuration.
**Recommendation:** Keep this pair together; do not remove `REQ_CORRELATE` while keeping `REQ_RELAXED`.

### D. SQLite persistence

#### D.1 [HIGH] Target Ubuntu 22.04 SQLite is inside the affected WAL-reset bug range

**What I checked:** `src/cryodaq/storage/sqlite_writer.py:133-145`, `src/cryodaq/reporting/data.py:130-189`, `src/cryodaq/web/server.py:265-266`, `src/cryodaq/core/experiment.py:982-983,1382-1401`.
**Current implementation:** CryoDAQ uses SQLite WAL with multiple connections from writer, readers, reporting, experiment logic, and web paths. Target OS is Ubuntu 22.04.
**Web research:** SQLite's own WAL page now documents a March 2026 "WAL-reset bug" affecting versions `3.7.0` through `3.51.2` when multiple connections in separate threads/processes write or checkpoint "at the same instant." Ubuntu 22.04 packages `libsqlite3-0 (3.37.2-2ubuntu0.5)`. Sources: [SQLite WAL docs](https://sqlite.org/wal.html), [Ubuntu jammy-updates libsqlite3-0](https://packages.ubuntu.com/jammy-updates/libsqlite3-0).
**Reasoning chain:** This is not hypothetical for CryoDAQ's architecture: multi-connection WAL is exactly the deployed pattern, and the target distro ships a vulnerable version. Even if the race is rare, safety-critical scientific runs are long enough for "rare" to stop being comforting.
**Verdict:** Deployment blocker unless the bundled/runtime SQLite version is controlled.
**Recommendation:** Freeze or vendor a fixed SQLite (`>=3.51.3` or documented backport) as part of the deployment plan, or switch durability strategy for the RC.

#### D.2 [MEDIUM] `synchronous=NORMAL` in WAL mode knowingly trades away durability on OS/power failure

**What I checked:** `src/cryodaq/storage/sqlite_writer.py:133-136`.
**Current implementation:** Writer sets `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;`.
**Web research:** SQLite states that WAL with `synchronous=NORMAL` remains consistent but "does lose durability"; recent commits may roll back after OS crash or power loss. Sources: [SQLite forum explanation by Richard Hipp](https://www.sqlite.org/forum/forumpost/9d6f13e346231916), [How To Corrupt An SQLite Database File](https://sqlite.org/howtocorrupt.html).
**Reasoning chain:** For many apps this is a good trade. For CryoDAQ, the user explicitly framed weeks of experiment loss as a relevant failure mode. That pushes the acceptable tradeoff boundary toward `FULL`, or toward a very explicit justification for keeping `NORMAL`.
**Verdict:** Probably intentional, but under-justified for this safety/data-loss profile.
**Recommendation:** Re-evaluate `FULL` for production, or document why losing the last few seconds of committed data is acceptable.

#### D.3 [MEDIUM] No explicit checkpoint/backup policy is visible for long-running WAL databases

**What I checked:** `src/cryodaq/storage/sqlite_writer.py`, repo-wide search for `wal_checkpoint`, `backup`, `VACUUM INTO`.
**Current implementation:** WAL is enabled and left on default autocheckpoint behavior; I found no explicit checkpoint orchestration and no live-backup path via SQLite backup API or `VACUUM INTO`.
**Web research:** SQLite docs say checkpointing is the third WAL primitive, default autocheckpoint is 1000 pages, and applications may need application-initiated checkpoints; the corruption guide recommends safe backup mechanisms such as `VACUUM INTO` or the backup API. Sources: [SQLite WAL docs](https://sqlite.org/wal.html), [How To Corrupt An SQLite Database File](https://sqlite.org/howtocorrupt.html).
**Reasoning chain:** Default autocheckpoint is fine for simple apps, but CryoDAQ is a long-running, multi-reader, daily-DB system with archival/reporting side paths. The absence of an explicit policy means WAL size, checkpoint timing, and live copy safety are left to defaults.
**Verdict:** Operational gap rather than immediate bug.
**Recommendation:** Define a production checkpoint/backup policy explicitly and test it against long-run workloads.

#### D.4 [MEDIUM] Experiment metadata/state writes are non-atomic

**What I checked:** `src/cryodaq/core/experiment.py:874-881,1118,1150,1355-1356`.
**Current implementation:** Important JSON state files are written directly with `Path.write_text(...)`.
**Web research:** Python documents `os.replace()` as atomic on success, which is the standard final step for crash-safe temp-file writes. Source: [Python `os.replace`](https://docs.python.org/3/library/os.html).
**Reasoning chain:** Direct overwrite is fine until power loss, kill, or partial write lands between truncate and full write. These files drive active experiment state and archive metadata, so a torn write is a real operator-facing failure.
**Verdict:** Medium integrity bug outside SQLite's protected path.
**Recommendation:** Write to a temp file in the same directory, flush/fsync, then `os.replace()`.

### E. Multiprocessing + PyInstaller

#### E.1 [HIGH] There is no PyInstaller spec, hook, or data-file manifest in the repo

**What I checked:** Repo-wide `find` for `*.spec`, hooks, lockfiles, constraints; `pyproject.toml`; `README.md:71-89`; `docs/deployment.md:24-51`; `CLAUDE.md:210-211`.
**Current implementation:** The repository has no PyInstaller build asset. Documentation still declares editable install from repo root as the supported deployment path.
**Web research:** PyInstaller requires explicit data-file placement and documents `--add-data` / spec-file configuration for bundled resources. Sources: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html), [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html).
**Reasoning chain:** A safety-critical RC with imminent frozen deployment should already have a reproducible bundle recipe. Right now it does not.
**Verdict:** Major deployment-readiness gap.
**Recommendation:** Add a checked-in `.spec` file, explicit data-file mapping, and a frozen-build smoke test before release.

#### E.2 [HIGH] Launcher restart/subprocess logic is not frozen-app safe

**What I checked:** `src/cryodaq/launcher.py:255-280,503-513`.
**Current implementation:** Launcher starts engine and standalone GUI using `[sys.executable, "-m", "cryodaq.engine"]` and `[sys.executable, "-m", "cryodaq.gui"]`.
**Web research:** PyInstaller warns that `sys.executable` inside a frozen app points to the bundled executable and that subprocesses expected to outlive the current process need `PYINSTALLER_RESET_ENVIRONMENT=1`. Sources: [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html), [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** In an unfrozen dev install, `python -m` is fine. In a frozen app, this becomes self-spawning semantics that depend on bootloader behavior and environment-reset rules, especially ugly for restart flows and sibling process launch.
**Verdict:** High-risk frozen deployment bug.
**Recommendation:** Implement frozen-aware subprocess launch paths explicitly; do not rely on `-m` module launches from inside the bundle.

#### E.3 [HIGH] The current root-path model conflicts with a self-contained `onedir` bundle

**What I checked:** `src/cryodaq/paths.py:6-17`, `CLAUDE.md:210-211`, `README.md:89`, `docs/deployment.md:51`.
**Current implementation:** Runtime root is the repo root unless `CRYODAQ_ROOT` is set; configs, plugins, and data are all expected outside the package tree.
**Web research:** PyInstaller runtime docs distinguish bundled files, files placed next to the app, and the current working directory; bundled apps need deliberate resource lookup rules. Sources: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html), [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
**Reasoning chain:** This design is valid for source installs. It is not the same thing as a frozen, self-contained operator bundle. Right now the project invariant and the deployment target disagree.
**Verdict:** High-risk architectural mismatch for the target packaging mode.
**Recommendation:** Decide whether the RC is truly self-contained or explicitly external-rooted. Then implement one model, not both.

#### E.4 [MEDIUM] POSIX `onedir` symlink handling is not documented for deployment copying

**What I checked:** `docs/deployment.md`, repo packaging assets.
**Current implementation:** Deployment docs do not mention symlink preservation when moving/copying a PyInstaller `onedir` build.
**Web research:** PyInstaller 6 documents that POSIX `onedir` bundles use symbolic links and must be copied/distributed in ways that preserve them. Source: [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
**Reasoning chain:** Ubuntu 22.04 is the target. If lab staff or admins copy the built directory with the wrong tool/archive options, the bundle can break in subtle ways unrelated to CryoDAQ code.
**Verdict:** Medium deployment-procedure risk.
**Recommendation:** Document the exact copy/archive procedure for Linux `onedir` artifacts.

#### E.5 [OK] `freeze_support()` is present where it should be

**What I checked:** `src/cryodaq/gui/app.py:27-30`, `src/cryodaq/launcher.py:660-663`.
**Current implementation:** GUI and launcher both call `multiprocessing.freeze_support()`.
**Web research:** Python and PyInstaller both say frozen multiprocessing needs `freeze_support()` immediately under `if __name__ == "__main__"`. Sources: [Python multiprocessing docs](https://docs.python.org/zh-cn/3/library/multiprocessing.html), [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
**Reasoning chain:** This is one of the frozen-app basics, and the code already does it.
**Verdict:** Correct.
**Recommendation:** Keep this in place for every frozen entry point that can spawn processes.

### F. PyVISA / GPIB / Serial

#### F.1 [MEDIUM] LakeShore 218S connection can succeed without any identity validation

**What I checked:** `src/cryodaq/drivers/instruments/lakeshore_218s.py:51-76`.
**Current implementation:** If `*IDN?` fails with a non-`RuntimeError`, the driver logs a warning and proceeds "without validation".
**Web research:** PyVISA's basic guidance uses `*IDN?` as the standard first communication/identity check and recommends verifying communication parameters from the manual before proceeding. Source: [PyVISA communication guide](https://pyvisa.readthedocs.io/en/latest/introduction/communication.html).
**Reasoning chain:** The repo rationale is that some 218 units may fail a first `*IDN?`. That is plausible. But falling through to `_connected = True` without any alternate identity check widens the chance of silently talking to the wrong resource or a garbled session.
**Verdict:** Acceptable in a lab hack; weak for a safety-critical replacement.
**Recommendation:** Require a successful alternate probe before marking connected, even if `*IDN?` remains best-effort.

#### F.2 [MEDIUM] Thyracont checksum validation is disabled by default

**What I checked:** `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:68-85`.
**Current implementation:** `validate_checksum` defaults to `False`.
**Web research:** The Thyracont protocol includes an explicit `CS` checksum field in request/response frames, not optional framing noise. Source: [Thyracont Communication Protocol PDF](https://thyracont-vacuum.com/download/243369).
**Reasoning chain:** In a noisy RS-232/USB-serial environment, checksums exist for a reason. Making them opt-in, rather than opt-out with a justified exception, is the wrong default for laboratory hardware.
**Verdict:** Medium integrity risk on the serial path.
**Recommendation:** Flip the default to checksum validation on, and disable it only for verified incompatible firmware.

#### F.3 [OK] GPIB transport recovery strategy is aligned with upstream communication guidance

**What I checked:** `src/cryodaq/drivers/transport/gpib.py:1-13,193-279`.
**Current implementation:** Persistent sessions, explicit `clear()`, unaddressing enablement, `write -> 100 ms wait -> read`, and escalation from device clear to IFC.
**Web research:** PyVISA explicitly notes that some instruments are slow and may require a delay between write and read; it recommends getting these values from the manual rather than guessing. Source: [PyVISA communication guide](https://pyvisa.readthedocs.io/en/latest/introduction/communication.html).
**Reasoning chain:** The 100 ms pause is not obviously over-engineered; it is consistent with conservative instrument I/O practice and safer than aggressive read timing on cryogenic hardware.
**Verdict:** Defensible and probably correct.
**Recommendation:** Keep the delay configurable only if you can re-verify on real bus hardware.

#### F.4 [OK] Instrument access is serialized at driver/transport boundaries

**What I checked:** `src/cryodaq/drivers/base.py:62-87`, `src/cryodaq/drivers/transport/usbtmc.py:37,54,71,105,134,172`.
**Current implementation:** Drivers use `safe_read()` under an `asyncio.Lock`; USBTMC transport also serializes all resource operations with its own lock.
**Web research:** Python's asyncio docs recommend moving blocking I/O off the event loop and using proper synchronization for cross-task work. Source: [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html).
**Reasoning chain:** This reduces the classic "two coroutines touching one instrument session" class of bug.
**Verdict:** Good baseline discipline.
**Recommendation:** Preserve this invariant for any future instrument or calibration path.

### G. Keithley TSP/Lua

#### G.1 [MEDIUM] `emergency_off()` does not verify the output is actually off

**What I checked:** `src/cryodaq/drivers/instruments/keithley_2604b.py:228-245,263-281`.
**Current implementation:** Normal `stop_source()` writes level/output and calls `_verify_output_off(...)`; `emergency_off()` writes off commands but never verifies.
**Web research:** PyVISA guidance emphasizes separating write-side success from read-back confirmation when debugging or validating instrument state. Source: [PyVISA communication guide](https://pyvisa.readthedocs.io/en/latest/introduction/communication.html).
**Reasoning chain:** The emergency path is precisely where silent failure is least acceptable. If the bus write is lost or the instrument is partially wedged, the code currently reports an emergency action path without post-condition confirmation.
**Verdict:** Medium safety gap.
**Recommendation:** Add a best-effort verify/read-back path after emergency off, even if it only affects fault logging and operator messaging.

#### G.2 [MEDIUM] SafetyManager bypasses the Keithley driver contract and mutates internals directly

**What I checked:** `src/cryodaq/core/safety_manager.py:323-343`, Keithley public API in `src/cryodaq/drivers/instruments/keithley_2604b.py`.
**Current implementation:** Live limit updates write directly to `self._keithley._transport` and mutate `self._keithley._channels`.
**Web research:** Python import/reload docs are a reminder that references to old objects and hidden internal state are fragile; hot swapping or refactoring internals will not automatically update external references. Source: [Python `importlib` docs](https://docs.python.org/3/library/importlib.html).
**Reasoning chain:** This is not an importlib problem per se; it is the same structural lesson. Safety code is now coupled to a driver's private fields rather than its public contract, which makes future driver changes easier to break silently.
**Verdict:** Medium maintainability-to-safety risk.
**Recommendation:** Move live limit updates behind a public Keithley method and keep private transport details private.

### H. Data integrity under adversarial conditions

#### H.1 [MEDIUM] Adaptive-throttle protection does not consume `alarms_v3.yaml`

**What I checked:** `src/cryodaq/core/housekeeping.py:28-40`, `src/cryodaq/engine.py:779-782,818`, `config/housekeeping.yaml:1-17`, `config/alarms_v3.yaml:153-162,289-312`.
**Current implementation:** Protected channel patterns are loaded only from legacy top-level `alarms` / `interlocks` lists, while the active richer config lives in `alarms_v3.yaml`.
**Web research:** SQLite and ZeroMQ documentation both stress that reliability features only work when the system's real runtime paths match the assumptions the developer encoded; defaults and side channels do not magically inherit higher-level intent. Sources: [SQLite WAL docs](https://sqlite.org/wal.html), [ØMQ Guide, chapter 5](https://zguide.zeromq.org/docs/chapter5/).
**Reasoning chain:** The local bug is simple: operators may believe "critical channels are protected from thinning" because the richer alarm config says so, but the throttle only sees the older config shape.
**Verdict:** Medium data-loss expectation mismatch.
**Recommendation:** Make housekeeping protection derive from the actually deployed alarm/interlock configuration, not the legacy schema only.

### I. Safety FSM correctness

#### I.1 [HIGH] `stop_source` and `emergency_off` interlocks collapse into the same latched-fault path

**What I checked:** `src/cryodaq/engine.py:850-859`, `src/cryodaq/core/interlock.py:367-418`, `src/cryodaq/core/safety_manager.py:647-652`.
**Current implementation:** Both interlock actions call `safety_manager.on_interlock_trip("interlock", "", 0)`, which immediately enters the fault path.
**Web research:** The ZeroMQ and Qt docs are not directly about safety state machines, but they reinforce the same architectural principle: transport/action semantics should not be collapsed if the caller depends on behavioral distinctions. Sources: [ØMQ Guide, chapter 4](https://zguide.zeromq.org/docs/chapter4/), [QThread docs](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QThread.html).
**Reasoning chain:** Locally, this is decisive: `InterlockEngine` carries the real `condition.action`, channel, and value. The engine wrapper discards them and maps both to the same latched fault. That defeats the configured distinction between "soft source stop" and full emergency-off behavior.
**Verdict:** High-severity semantic bug in safety behavior.
**Recommendation:** Pass the actual action, interlock name, channel, and value through; implement distinct SafetyManager paths for `stop_source` vs full fault latch.

#### I.2 [LOW] Telegram `/phase` accepts names that do not exist in the actual experiment state machine

**What I checked:** `src/cryodaq/notifications/telegram_commands.py:36,228-230`, `src/cryodaq/core/experiment.py:53-59`, `src/cryodaq/gui/widgets/experiment_workspace.py:840-848`.
**Current implementation:** Telegram accepts `cooling` / `warming`, while the real enum and GUI use `cooldown` / `warmup`, plus the Telegram list omits `vacuum`.
**Web research:** Telegram documents bot commands as a real operator-facing interface whose command set is discoverable and should reflect actual supported behavior. Sources: [Telegram Commands](https://core.telegram.org/api/bots/commands), [Telegram Bot API](https://core.telegram.org/bots/api).
**Reasoning chain:** This is not just cosmetic documentation drift; it is a control path for remote operators. A mismatched phase vocabulary means remote operations can fail or become misleading while local GUI succeeds.
**Verdict:** Low severity individually, but it is the sort of mismatch that erodes trust in emergency or off-hours use.
**Recommendation:** Make Telegram phase values derive from `ExperimentPhase`, not from a hard-coded divergent list.

### J. Plugin loader / hot reload

#### J.1 [MEDIUM] Hot reload unloads modules without any teardown contract

**What I checked:** `src/cryodaq/analytics/plugin_loader.py:212-224,289-336`.
**Current implementation:** `_unload_plugin()` just drops the object from `_plugins`; there is no `close()`, `shutdown()`, or teardown hook.
**Web research:** Python's `importlib.reload()` docs warn that reload leaves old objects alive until references drop to zero and that reloaded modules do not magically update external references or existing instances. Source: [Python `importlib` docs](https://docs.python.org/3/library/importlib.html).
**Reasoning chain:** The loader is not calling `reload()`, but it is playing the same game: replacing code objects at runtime. Without teardown semantics, any background resources, cached state, or external references remain whatever they were before the "reload".
**Verdict:** Medium hot-reload correctness risk.
**Recommendation:** Add an optional plugin teardown hook and call it before unload/reload.

#### J.2 [MEDIUM] Hot reload behavior is untested beyond initial load and failure isolation

**What I checked:** `tests/analytics/test_plugins.py:79-200`, `src/cryodaq/analytics/plugin_loader.py:289-336`.
**Current implementation:** Tests cover loading, YAML config application, failure isolation, and metric publication, but not file modification/delete during watch-loop reload.
**Web research:** Python's importlib docs emphasize that runtime import/reload has caveats around old references and new objects; this is exactly the kind of behavior that needs focused regression tests. Source: [Python `importlib` docs](https://docs.python.org/3/library/importlib.html).
**Reasoning chain:** The code path exists and is non-trivial. The test suite does not currently pin its behavior during actual reload scenarios.
**Verdict:** Medium coverage gap for a dynamic feature.
**Recommendation:** Add watch-loop tests for modify, delete, and repeated reload of a plugin that retains state.

### K. Configuration and secrets

#### K.1 [MEDIUM] `allowed_chat_ids: []` means command bot access defaults to "allow all"

**What I checked:** `src/cryodaq/notifications/telegram_commands.py:61,68,197-200`, `config/notifications.local.yaml.example:6-21`.
**Current implementation:** Empty `allowed_chat_ids` becomes an empty set, and the security check is only enforced if that set is non-empty.
**Web research:** Telegram's bot API makes commands a real interactive surface available in private chats and chats, with scoped command menus. Sources: [Telegram Commands](https://core.telegram.org/api/bots/commands), [Telegram Bot API](https://core.telegram.org/bots/api).
**Reasoning chain:** In CryoDAQ, `/phase` and `/log` are not read-only. If commands are enabled and the token is exposed or the bot is reachable from an unintended chat, "empty means allow all" is the wrong default for a safety-sensitive control surface.
**Verdict:** Medium security/configuration risk.
**Recommendation:** Make `allowed_chat_ids` mandatory when `commands.enabled` is true, or default-deny instead of default-allow.

### L. Cross-platform path handling

#### L.1 [HIGH] `get_data_dir()` points into the project/bundle root instead of a stable user-data location

**What I checked:** `src/cryodaq/paths.py:6-17`, `src/cryodaq/engine.py:1492`, `src/cryodaq/instance_lock.py:29`, repo-wide writes under `get_data_dir()`.
**Current implementation:** Data, lock files, DBs, and runtime JSON all live under `get_project_root()/data`.
**Web research:** PyInstaller distinguishes bundle contents from runtime environment and user-placed files; frozen apps need explicit handling of where writable data lives. Source: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** This is fine in a developer checkout. In a frozen lab deployment, bundle root may be copied, replaced, readonly, or wiped during updates. Writing live state there is brittle.
**Verdict:** High-severity packaging/path design issue.
**Recommendation:** Separate immutable app resources from mutable runtime state; use an OS-appropriate user/app data directory for writable files.

#### L.2 [MEDIUM] Several modules bypass the central path helpers and hard-code repo-relative traversal

**What I checked:** `src/cryodaq/gui/widgets/shift_handover.py:40`, `src/cryodaq/gui/widgets/calibration_panel.py:44`, `src/cryodaq/gui/widgets/connection_settings.py:34-37`, `src/cryodaq/core/channel_manager.py:18-20`.
**Current implementation:** Multiple modules compute `parents[4] / "config"` directly instead of going through `cryodaq.paths`.
**Web research:** PyInstaller resource lookup guidance assumes you choose one consistent model for locating bundled and adjacent data files. Source: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** Even if `get_project_root()` were fixed tomorrow, these modules would still be broken because they bypass it.
**Verdict:** Medium maintainability and frozen-path risk.
**Recommendation:** Route all runtime path resolution through one tested helper layer.

#### L.3 [MEDIUM] Web static/resource lookup assumes package layout but there is no bundle data mapping

**What I checked:** `src/cryodaq/web/server.py:49,322-323`, repo packaging assets.
**Current implementation:** Web server serves `Path(__file__).parent / "static"` if it exists, but no PyInstaller data-file mapping exists in the repo.
**Web research:** PyInstaller says bundled data files must be explicitly added and placed where code expects them. Sources: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html), [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html).
**Reasoning chain:** The code itself is fine for a package install. The missing piece is the build recipe. Without it, the dashboard is likely to disappear in the frozen artifact.
**Verdict:** Medium frozen-web readiness gap.
**Recommendation:** Add the static directory explicitly to the bundle and smoke-test `/` from the frozen app.

### M. Dependency pinning and supply chain

#### M.1 [MEDIUM] Runtime dependencies are lower-bound only; deployment is not reproducible

**What I checked:** `pyproject.toml:9-39`, repo-wide search showing no `requirements*.txt`, `constraints*.txt`, lockfile, or hashes.
**Current implementation:** All runtime dependencies are declared as `>=` minimums.
**Web research:** pip documents `--require-hashes` for repeatable installs and generally requires exact pinned artifacts if you want reproducible environments. Source: [pip install docs](https://pip.pypa.io/en/stable/cli/pip_install/).
**Reasoning chain:** In a scientific lab deployment, "whatever newest compatible PySide6/pyzmq/aiohttp was available that day" is not a deployment strategy.
**Verdict:** Medium supply-chain / reproducibility gap.
**Recommendation:** Add a fully pinned deployment constraints/lock artifact for the RC build.

#### M.2 [MEDIUM] The frozen-build toolchain itself is also unpinned

**What I checked:** `pyproject.toml`, repo-wide search for packaging/build locks and PyInstaller manifests.
**Current implementation:** There is no pinned PyInstaller version, no frozen-build manifest, and no build-environment lock.
**Web research:** PyInstaller explicitly documents version-sensitive behavior around subprocess handling and POSIX symlink usage. Sources: [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html), [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** When the packaging tool has behavior shifts across versions, an unpinned build chain turns deployment into a moving target.
**Verdict:** Medium build reproducibility risk.
**Recommendation:** Pin the build toolchain separately from runtime deps and record the exact bundle recipe.

### N. Test coverage gaps

#### N.1 [HIGH] There is no frozen-bundle smoke test at all

**What I checked:** repo-wide test listing, packaging assets, deployment docs.
**Current implementation:** The test suite is broad for source installs, but there is no test that launches a frozen artifact and checks config/static/data discovery.
**Web research:** PyInstaller's own docs describe multiple frozen-only pitfalls: resource lookup, symlink handling, multiprocessing, and subprocess behavior. Sources: [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html), [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** Given the deployment target shift, the missing test is not academic. The frozen app is effectively a separate product surface from the source install.
**Verdict:** High-severity release-process gap.
**Recommendation:** Add a CI or pre-release smoke that builds `onedir`, starts launcher/engine/web, and verifies critical resources are found.

#### N.2 [MEDIUM] There is no test for backlog-induced heartbeat starvation / false unhealthy restarts

**What I checked:** `tests/core/test_zmq_subprocess.py:113-140`, `src/cryodaq/core/zmq_subprocess.py:97-109,140-147`, `src/cryodaq/gui/zmq_client.py:140-146`.
**Current implementation:** Tests assert constant values (`HEARTBEAT_INTERVAL = 5.0`, healthy threshold `30.0`) but do not simulate a full queue delaying or dropping heartbeats.
**Web research:** The ZeroMQ Guide explicitly warns that heartbeats can be delayed behind real data and cause false timeouts under congestion. Source: [ØMQ Guide, chapter 4](https://zguide.zeromq.org/docs/chapter4/).
**Reasoning chain:** This is exactly the failure mode the current architecture invites, and the current tests do not hit it.
**Verdict:** Medium coverage gap for a subtle operational bug.
**Recommendation:** Add a bridge test that fills `data_queue` and verifies liveness logic still behaves as intended.

### O. Deployment readiness

#### O.1 [HIGH] The documented supported deployment does not match the target deployment

**What I checked:** `README.md:73-89`, `docs/deployment.md:24-51`, `CLAUDE.md:210-211`.
**Current implementation:** Documentation says supported deployment is editable install from repo root; wheel install is explicitly "not self-contained."
**Web research:** PyInstaller's frozen-runtime guidance assumes you make an explicit bundle model for resources and subprocess behavior. Sources: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html), [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
**Reasoning chain:** Right now the codebase is honest about what it supports, but that supported mode is not the user's stated release target.
**Verdict:** High deployment-readiness gap.
**Recommendation:** Either change the release target back to source install, or finish the frozen deployment work before deployment.

#### O.2 [HIGH] Ubuntu 22.04 plus `requires-python >=3.12` implies a custom runtime story that is not documented

**What I checked:** `pyproject.toml:9`, deployment docs, packaging assets.
**Current implementation:** Project requires Python 3.12+, while Ubuntu 22.04 system Python is older; docs do not specify whether Python is bundled, vendor-installed, or managed externally in production.
**Web research:** PyInstaller is specifically the common answer when you need to ship a self-contained Python runtime, and its docs emphasize frozen-app-specific behavior and constraints. Sources: [PyInstaller common issues and pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html), [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html).
**Reasoning chain:** For deployment, "what Python are we actually running on the target box?" is not optional. It also interacts with the SQLite version problem above.
**Verdict:** High deployment ambiguity.
**Recommendation:** Document the exact runtime packaging choice for Ubuntu 22.04, including bundled Python and bundled SQLite versions.

#### O.3 [MEDIUM] There is no frozen-path acceptance checklist for config/plugins/static data

**What I checked:** repo docs, `src/cryodaq/paths.py`, `src/cryodaq/web/server.py`, plugin/static/config usage across runtime.
**Current implementation:** Many runtime resources exist, but there is no release checklist for verifying them in the frozen artifact.
**Web research:** PyInstaller requires explicit placement of data files and documents that resource lookup depends on where bundled files are placed. Sources: [PyInstaller run-time information](https://pyinstaller.org/en/stable/runtime-information.html), [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html).
**Reasoning chain:** Without a checklist, frozen deployment failures will be discovered manually in the lab, not in release prep.
**Verdict:** Medium process gap.
**Recommendation:** Add a deployment acceptance checklist covering config overrides, plugins, calibration data, web static files, and writable data directories.

## Areas confirmed OK

- Async driver transports generally respect the "no blocking I/O on the engine event loop" invariant.
- GUI isolation from direct libzmq usage is conceptually sound; the bridge subprocess remains a good design choice.
- REQ/REP bridge configuration uses the correct `REQ_RELAXED` + `REQ_CORRELATE` pairing.
- GPIB communication is conservative in a good way: persistent sessions, bus-clear escalation, and post-write delay are all defensible for real hardware.
- Multiprocessing entry points already include `freeze_support()`, which avoids one common class of frozen-app breakage.
- The repo has started encoding non-blocking GUI expectations as tests instead of relying purely on review discipline.

## Meta-notes

- `AGENTS.md` is not present in the repository.
- `PROJECT_STATUS.md` is also not present. To avoid repeating already-closed findings, I used `CHANGELOG.md`, `RELEASE_CHECKLIST.md`, and the focused regression suites `tests/core/test_p0_fixes.py`, `tests/core/test_p1_fixes.py`, and `tests/core/test_audit_fixes.py` as substitutes.
- I deliberately did not spend time re-litigating already-fixed P0/P1 items unless the current code introduced a new variant.
- The strongest findings here are the ones where local code shape and current upstream/vendor guidance point in the same direction: PyInstaller readiness, Qt thread lifetime, and SQLite/WAL deployment risk.

## Disagreements I expect with Claude Code

1. **"Supported deployment is editable install, so PyInstaller gaps are out of scope."**
   My view: that is not defensible given the user's stated target. The code and docs are honest about current support, but the audit target is imminent `onedir` deployment. The gap is therefore central, not out of scope.

2. **"The SQLite WAL-reset bug is too rare to matter."**
   My view: SQLite itself says the bug affects WAL mode with separate threads/processes and multiple connections. CryoDAQ is exactly that architecture, and the target distro ships an affected version. In a long-running scientific control system, low probability is not a free pass.

3. **"The emergency-off `QThread` fire-and-forget pattern is probably fine in practice."**
   My view: Qt's own guidance pushes explicit lifetime management. Safety-critical emergency actions are the wrong place to depend on benign GC timing or accidental QObject ownership.

4. **"Collapsing `stop_source` and `emergency_off` into the same safety fault is acceptable because it is conservative."**
   My view: conservative is not the same as semantically correct. The interlock config encodes distinct actions; discarding that distinction silently is a logic bug, not a harmless simplification.
