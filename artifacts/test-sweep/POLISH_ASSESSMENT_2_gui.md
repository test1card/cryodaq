# POLISH_ASSESSMENT_2_gui.md — GUI / launcher / IPC production-logic pass (2026-06-24)

Read-only architect pass (reported inline, parent transcribed). Scope: launcher.py,
gui/zmq_client.py, core/zmq_subprocess.py, gui/shell/main_window_v2.py,
bottom_status_bar.py, top_watch_bar.py, instance_lock.py, logging_setup.py, paths.py,
+ sweep of shell/overlays + widgets for QThread lifecycle. Every finding verified at
the cited line. Does NOT re-report POLISH_ASSESSMENT.md.

**Headline:** IPC timeout layering (55<60<65), ephemeral-REQ-per-command, Future-per-
request routing, watchdogs, restart backoff, re-exec port-drain, flock single-instance
are all correct. One safety-relevant GUI defect: the bottom safety strip goes stale on
engine death.

## DO FIRST
1. **[HIGH] F1 — bottom-bar safety strip goes stale when the engine dies.**
   `main_window_v2.py:512-517` updates `_last_safety_state` + `_bottom_bar.set_safety_state`
   ONLY when an `analytics/safety_state` reading arrives. On engine death/disconnect no
   such reading arrives; `_tick_status` (`:662-708`) flips engine/connection labels to
   "Engine потерян" but never re-evaluates the safety strip → top bar shows "нет связи"
   while the bottom strip shows a stale green "● running". Violates CLAUDE.md "GUI must
   not be source of truth for runtime state." Fix: when the engine is declared lost,
   blank the safety strip (`set_safety_state(None)`/unknown) AND push
   `set_safety_ready(False, ...)` to the Keithley overlay.
2. **[MED] F2 — no closeEvent/worker-join teardown** in MainWindowV2/LauncherWindow.
   `_status_timer` not stopped; `ZmqCommandWorker` threads (`:791` `_create_exp_worker` +
   panel `_workers`) and launcher `_safety_worker` not joined at shutdown. Not a hang
   (`bridge.shutdown()` cancels pending futures so workers unblock fast) but yields
   "QThread: Destroyed while thread is still running" noise/possible teardown abort. Add
   a closeEvent that stops timers + `wait()`s live workers.
3. **[LOW-MED] F5 — engine-restart thrash path missing cooldown.** `launcher.py:1066-1078`
   heartbeat/data-stall restart has no 60s cooldown like its command-channel sibling
   (`:1084-1097`) → restart storm risk on a flapping bridge.
4. **[LOW] F3 — silent `except Exception: pass` on the asyncio pump** `launcher.py:1371-1376`
   (every 10ms). A persistent loop fault is invisible. Log once at DEBUG / narrow catch.
5. **[LOW] F4 — module-level blocking `send_command`** (`zmq_client.py:213-232/310-314`)
   `future.result(timeout=65)` is main-thread-blockable if ever called directly (GUI
   correctly routes via ZmqCommandWorker today). Latent.

## SOUND (verified, leave alone)
IPC timeout nesting 55<60<65; ephemeral-REQ-per-command; Future-per-request routing;
engine restart backoff + `_restart_pending` guard; re-exec port drain; flock single-
instance; stderr-pump handler close; token redaction in logs.

## REJECTED (verified false)
worker-list "leak" (bounded, pruned next completion); 65s shutdown block (bridge.shutdown
cancels futures); launcher-tray staleness (gated on `alive` first, MWV2-specific);
ping ctx leak; execv orphan.
