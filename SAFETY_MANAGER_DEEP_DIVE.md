# SafetyManager Deep Dive

**Date:** 2026-04-09  
**Working tree:** `master`  
**Primary file:** `src/cryodaq/core/safety_manager.py`  
**Read confirmation:** full file read, line `1` through line `806` (`wc -l` = `806`)  
**Supplementary reads for contract verification only:** `config/safety.yaml`, `src/cryodaq/core/rate_estimator.py`  
**Scope discipline:** findings below are about `SafetyManager` behavior only.

## Executive summary

I read the entire `SafetyManager` file and rebuilt the FSM from the live code rather than from documentation. The enum has **six** states, not five: `SAFE_OFF`, `READY`, `RUN_PERMITTED`, `RUNNING`, `FAULT_LATCHED`, and `MANUAL_RECOVERY`.

The main result is that the file is internally coherent on ordinary command ordering, but it still has two high-risk edge behaviors:

1. `RUN_PERMITTED` is a real blind state: the monitor loop does not run stale/rate/heartbeat checks there, even though `request_run()` can remain there across a long `await self._keithley.start_source(...)`.
2. `_fault()` latches state before any `await`, which is good, but the actual hardware shutoff is still cancellable because `await self._keithley.emergency_off()` is not shielded. Cancellation at the wrong time can leave `FAULT_LATCHED` set while the physical output shutdown is incomplete.

Everything else below is a line-by-line reconstruction of transitions, lock behavior, cancellation behavior, and time handling.

## State inventory actually present in code

```python
# src/cryodaq/core/safety_manager.py:30-37
class SafetyState(Enum):
    SAFE_OFF = "safe_off"
    READY = "ready"
    RUN_PERMITTED = "run_permitted"
    RUNNING = "running"
    FAULT_LATCHED = "fault_latched"
    MANUAL_RECOVERY = "manual_recovery"
```

The user-provided list omitted `MANUAL_RECOVERY`. The matrix below therefore covers **6 states × 11 events = 66 transition cells**.

## Findings raised in this pass

### F1 [HIGH] `RUN_PERMITTED` disables periodic safety checks while `request_run()` is awaiting driver I/O

```python
# src/cryodaq/core/safety_manager.py:218-267
if self._state != SafetyState.RUNNING:
    self._transition(
        SafetyState.RUN_PERMITTED,
        f"Start requested for {smu_channel}: P={p_target}W",
        channel=smu_channel,
        value=p_target,
    )
...
await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
...
self._active_sources.add(smu_channel)
if self._state != SafetyState.RUNNING:
    self._transition(
        SafetyState.RUNNING,
        f"Source {smu_channel} enabled: P={p_target}W",
        channel=smu_channel,
        value=p_target,
    )
```

```python
# src/cryodaq/core/safety_manager.py:651-667
async def _run_checks(self) -> None:
    now = time.monotonic()

    if self._state == SafetyState.MANUAL_RECOVERY:
        ok, _ = self._check_preconditions()
        if ok:
            self._transition(SafetyState.READY, "Recovery preconditions restored")
        return

    if self._state == SafetyState.SAFE_OFF:
        ok, _ = self._check_preconditions()
        if ok and self._latest:
            self._transition(SafetyState.READY, "All preconditions satisfied")
        return

    if self._state != SafetyState.RUNNING:
        return
```

`RUN_PERMITTED` is not monitored by `_run_checks()` at all. If `start_source()` blocks for a long time, the FSM sits in an intermediate state where stale critical channels, missing Keithley heartbeat, and rate-limit faults are not evaluated. This is not just cosmetic state naming; it creates a real temporary suspension of periodic safety logic.

### F2 [HIGH] `_fault()` latches first, but the physical shutdown path is still cancellable

```python
# src/cryodaq/core/safety_manager.py:538-556
async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
    self._fault_reason = reason
    self._fault_time = time.monotonic()
    self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)

    self._active_sources.clear()

    if self._keithley is not None:
        try:
            await self._keithley.emergency_off()
        except Exception as exc:
            logger.critical("FAULT: emergency_off failed: %s", exc)

    fault_channel = channel if channel in {"smua", "smub"} else None
    await self._publish_keithley_channel_states(reason, fault_channel=fault_channel)
```

```python
# Python asyncio docs consulted for cancellation semantics
# "When a task is cancelled, asyncio.CancelledError will be raised in the task at the next opportunity."
# "if the coroutine containing it is cancelled, the Task running in something() is not cancelled"
# (the latter describing asyncio.shield)
```

The state latch is synchronous and therefore robust against races with `request_run()`, but the hardware shutdown itself is not protected from cancellation. If the coroutine running `_fault()` is cancelled while awaiting `keithley.emergency_off()` or while publishing state, the manager can be left in `FAULT_LATCHED` with `_active_sources` already cleared even though the hardware-off step did not finish.

### F3 [MEDIUM] The `stop_source` interlock escalation path calls `_fault()` while `_cmd_lock` is still held

```python
# src/cryodaq/core/safety_manager.py:749-769
if action == "stop_source":
    logger.warning("INTERLOCK stop_source: %s", reason)
    async with self._cmd_lock:
        if self._keithley is not None:
            try:
                await self._keithley.emergency_off()
            except Exception as exc:
                logger.error(
                    "stop_source interlock: emergency_off failed: %s — "
                    "escalating to full fault", exc,
                )
                # The lock is released when this `async with` block
                # exits via the `return` below. _fault itself is
                # unlocked, so it does not deadlock — but it WILL
                # serialize behind the lock until _fault returns.
                await self._fault(
                    f"{reason} (emergency_off failed: {exc})",
                    channel=channel, value=value,
                )
                return
```

The comment is inaccurate. `_fault()` is awaited **inside** the `async with self._cmd_lock:` block, so the lock is not released before the fault path starts. This does not create an immediate deadlock because `_fault()` itself does not acquire `_cmd_lock`, but it does serialize the entire fault cleanup under the command lock contrary to the comment’s claim.

### F4 [MEDIUM] `SafetyManager` itself does not normalize Cyrillic `Т` and Latin `T`

```python
# src/cryodaq/core/safety_manager.py:132-155
patterns: list[re.Pattern[str]] = []
for pattern in raw.get("critical_channels", []):
    try:
        patterns.append(re.compile(pattern))
    except re.error as exc:
        logger.error("Invalid critical_channels regex %r: %s", pattern, exc)
...
self._keithley_patterns = [
    re.compile(pattern) for pattern in raw.get("keithley_channels", [".*/smu.*"])
]
```

```python
# config/safety.yaml:8-18
critical_channels:
  - "Т1 .*"
  - "Т7 .*"
  - "Т11 .*"
  - "Т12 .*"

stale_timeout_s: 10.0
heartbeat_timeout_s: 15.0
```

`SafetyManager` performs literal regex matching and does not normalize homoglyphs. With the current config it expects Cyrillic `Т`, so whether Latin `T` names are “handled” depends entirely on upstream naming discipline, not on any defense inside this file.

### F5 [LOW] `stop()` is a task shutdown, not a full state reset

```python
# src/cryodaq/core/safety_manager.py:165-177
async def stop(self) -> None:
    if self._active_sources:
        await self._safe_off("system stop", channels=set(self._active_sources))

    for task in (self._collect_task, self._monitor_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    self._collect_task = None
    self._monitor_task = None
```

If `stop()` is called with no active sources, it does not force a final state such as `SAFE_OFF`; it simply cancels the background tasks and leaves the FSM state as-is. That means the object can end “stopped” while still reporting `READY`, `MANUAL_RECOVERY`, or `FAULT_LATCHED`.

## Core code anchors used for all analyses

### Anchor A: startup, config, queue, lock, estimator

```python
# src/cryodaq/core/safety_manager.py:68-123
def __init__(
    self,
    safety_broker: SafetyBroker,
    *,
    keithley_driver: Any | None = None,
    mock: bool = False,
    data_broker: Any | None = None,
) -> None:
    self._broker = safety_broker
    self._keithley = keithley_driver
    self._mock = mock
    self._data_broker = data_broker
    self._state = SafetyState.SAFE_OFF
    self._config = SafetyConfig()
    ...
    self._rate_estimator = RateEstimator(window_s=120.0, min_points=60)
    ...
    self._cmd_lock = asyncio.Lock()
    ...
    self._broker.set_overflow_callback(
        lambda: self._fault("SafetyBroker overflow - data lost")
    )
```

### Anchor B: `request_run()`

```python
# src/cryodaq/core/safety_manager.py:187-273
async def request_run(
    self,
    p_target: float,
    v_comp: float,
    i_comp: float,
    *,
    channel: str | None = None,
) -> dict[str, Any]:
    async with self._cmd_lock:
        smu_channel = normalize_smu_channel(channel)

        if self._state == SafetyState.FAULT_LATCHED:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"FAULT: {self._fault_reason}"}

        if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"Start not allowed from {self._state.value}"}
        ...
        ok, reason = self._check_preconditions()
        if not ok:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": reason}
        ...
        if self._state != SafetyState.RUNNING:
            self._transition(
                SafetyState.RUN_PERMITTED,
                f"Start requested for {smu_channel}: P={p_target}W",
                channel=smu_channel,
                value=p_target,
            )
        ...
        await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
        ...
        if self._state == SafetyState.FAULT_LATCHED:
            await self._keithley.emergency_off()
            return {...}

        self._active_sources.add(smu_channel)
        if self._state != SafetyState.RUNNING:
            self._transition(
                SafetyState.RUNNING,
                f"Source {smu_channel} enabled: P={p_target}W",
                channel=smu_channel,
                value=p_target,
            )
        await self._publish_keithley_channel_states(f"run:{smu_channel}")
        return {...}
```

### Anchor C: `request_stop()`, `emergency_off()`, `acknowledge_fault()`

```python
# src/cryodaq/core/safety_manager.py:275-426
async def request_stop(self, *, channel: str | None = None) -> dict[str, Any]:
    async with self._cmd_lock:
        channels = self._resolve_channels(channel)
        if self._state == SafetyState.FAULT_LATCHED:
            await self._ensure_output_off(channel)
            return {...}

        await self._safe_off("Operator stop", channels=channels)
        await self._publish_keithley_channel_states("stop")
        return {...}

async def emergency_off(self, *, channel: str | None = None) -> dict[str, Any]:
    async with self._cmd_lock:
        channels = self._resolve_channels(channel)
        await self._ensure_output_off(channel)
        self._active_sources.difference_update(channels)
        await self._publish_keithley_channel_states("emergency_off")

        if self._state == SafetyState.FAULT_LATCHED:
            return {...}

        if not self._active_sources:
            self._transition(SafetyState.SAFE_OFF, "Operator emergency off")
        return {...}

async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
    async with self._cmd_lock:
        if self._state != SafetyState.FAULT_LATCHED:
            return {...}
        if self._config.require_reason and not reason.strip():
            return {...}

        elapsed = time.monotonic() - self._fault_time
        if elapsed < self._config.cooldown_before_rearm_s:
            return {...}

        self._recovery_reason = reason.strip()
        if self._persistence_failure_clear is not None:
            try:
                self._persistence_failure_clear()
            except Exception as exc:
                logger.error(...)
        self._transition(SafetyState.MANUAL_RECOVERY, f"Fault acknowledged: {reason}")
        await self._publish_keithley_channel_states("fault_acknowledged")
        return {"ok": True, "state": self._state.value}
```

### Anchor D: `_transition()`, `_fault()`, `_safe_off()`, `_check_preconditions()`

```python
# src/cryodaq/core/safety_manager.py:497-629
def _transition(
    self,
    new_state: SafetyState,
    reason: str,
    *,
    channel: str = "",
    value: float = 0.0,
) -> None:
    old_state = self._state
    self._state = new_state
    self._events.append(
        SafetyEvent(
            timestamp=datetime.now(timezone.utc),
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            channel=channel,
            value=value,
        )
    )
    ...
    for callback in self._on_state_change:
        ...
    task = asyncio.get_running_loop().create_task(self._publish_state(reason), ...)

async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
    self._fault_reason = reason
    self._fault_time = time.monotonic()
    self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)

    self._active_sources.clear()
    if self._keithley is not None:
        try:
            await self._keithley.emergency_off()
        except Exception as exc:
            logger.critical("FAULT: emergency_off failed: %s", exc)
    await self._publish_keithley_channel_states(reason, fault_channel=fault_channel)

async def _safe_off(self, reason: str, *, channels: set[SmuChannel]) -> None:
    if self._state == SafetyState.FAULT_LATCHED:
        await self._ensure_output_off()
        logger.warning("_safe_off rejected while fault latched")
        return
    ...
    self._active_sources.difference_update(channels)
    if self._active_sources:
        self._transition(SafetyState.RUNNING, f"Partial stop: ...")
        return
    self._transition(SafetyState.SAFE_OFF, reason)

def _check_preconditions(self) -> tuple[bool, str]:
    now = time.monotonic()
    for pattern in self._config.critical_channels:
        matched = False
        for ch, (ts, value, status) in self._latest.items():
            if not pattern.match(ch):
                continue
            matched = True
            age = now - ts
            if age > self._config.stale_timeout_s:
                return False, f"Stale data: {ch} ({age:.1f}s)"
            if status != "ok":
                return False, f"Channel {ch} status={status}"
            if math.isnan(value) or math.isinf(value):
                return False, f"Channel {ch} invalid value {value}"
        if not matched and not self._mock:
            return False, f"No data for critical channel: {pattern.pattern}"
    ...
    return True, ""
```

### Anchor E: `_collect_loop()`, `_monitor_loop()`, `_run_checks()`, `_has_fresh_keithley_data()`

```python
# src/cryodaq/core/safety_manager.py:631-717
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            now = time.monotonic()
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, now, reading.value)
    except asyncio.CancelledError:
        return

async def _monitor_loop(self) -> None:
    try:
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_S)
            await self._run_checks()
    except asyncio.CancelledError:
        return

async def _run_checks(self) -> None:
    now = time.monotonic()

    if self._state == SafetyState.MANUAL_RECOVERY:
        ok, _ = self._check_preconditions()
        if ok:
            self._transition(SafetyState.READY, "Recovery preconditions restored")
        return

    if self._state == SafetyState.SAFE_OFF:
        ok, _ = self._check_preconditions()
        if ok and self._latest:
            self._transition(SafetyState.READY, "All preconditions satisfied")
        return

    if self._state != SafetyState.RUNNING:
        return

    for pattern in self._config.critical_channels:
        for ch, (ts, _value, _status) in self._latest.items():
            if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
                await self._fault(f"Устаревшие данные канала {ch}", channel=ch)
                return
    ...
    for ch in self._rate_estimator.channels():
        if not any(pattern.match(ch) for pattern in self._config.critical_channels):
            continue
        rate = self._rate_estimator.get_rate(ch)
        if rate is None:
            continue
        abs_rate = abs(rate)
        if abs_rate > self._config.max_dT_dt_K_per_min:
            await self._fault(...)
            return

def _has_fresh_keithley_data(self, now: float, smu_channel: SmuChannel) -> bool:
    aliases = {smu_channel, smu_channel.replace("smu", "smu_")}
    for channel, (ts, _value, status) in self._latest.items():
        if status != "ok":
            continue
        if not any(pattern.match(channel) for pattern in self._keithley_patterns):
            continue
        if any(f"/{alias}/" in channel for alias in aliases) and now - ts < self._config.heartbeat_timeout_s:
            return True
    return False
```

### Anchor F: interlocks and persistence failure

```python
# src/cryodaq/core/safety_manager.py:719-806
async def on_interlock_trip(
    self,
    interlock_name: str,
    channel: str,
    value: float,
    *,
    action: str = "emergency_off",
) -> None:
    reason = f"Interlock '{interlock_name}' tripped: channel={channel}, value={value:.4g}"

    if action == "emergency_off":
        logger.critical("INTERLOCK emergency_off: %s", reason)
        await self._fault(reason, channel=channel, value=value)
        return

    if action == "stop_source":
        logger.warning("INTERLOCK stop_source: %s", reason)
        async with self._cmd_lock:
            if self._keithley is not None:
                try:
                    await self._keithley.emergency_off()
                except Exception as exc:
                    logger.error(...)
                    await self._fault(...)
                    return
            self._active_sources.clear()
            await self._publish_keithley_channel_states(f"interlock_stop:{interlock_name}")
            if self._state not in (SafetyState.FAULT_LATCHED, SafetyState.MANUAL_RECOVERY):
                self._transition(SafetyState.SAFE_OFF, f"Interlock stop_source: {interlock_name}", ...)
        return

    logger.critical("Unknown interlock action %r for '%s' — escalating to full fault", action, interlock_name)
    await self._fault(f"Unknown interlock action {action!r}: {reason}", channel=channel, value=value)

async def on_persistence_failure(self, reason: str) -> None:
    logger.critical("PERSISTENCE FAILURE: %s — triggering safety fault", reason)
    await self._fault(
        f"Persistence failure: {reason}",
        channel="",
        value=0.0,
    )
```

### Anchor G: `RateEstimator` contract actually applied

```python
# src/cryodaq/core/rate_estimator.py:29-64
def __init__(self, window_s: float = 120.0, min_points: int = 60) -> None:
    self._window_s = window_s
    self._min_points = min_points
    ...

def get_rate(self, channel: str) -> float | None:
    """Вернуть dX/dt в единицах [unit/мин]. None если недостаточно данных."""
    channel = self.resolve_channel(channel)
    buf = self._buffers.get(channel)
    if not buf or len(buf) < self._min_points:
        return None
    return _ols_slope_per_min(list(buf))
```

## Analysis 1: State transition matrix

### `SAFE_OFF`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface; no handler in file | No `request_arm` method exists. |
| `request_run()` | Success: `SAFE_OFF -> RUN_PERMITTED -> RUNNING`; precondition failure: stays `SAFE_OFF`; start failure: `FAULT_LATCHED` | Acquires `_cmd_lock`; checks limits and critical-channel freshness; may call `start_source`; transitions; publishes Keithley states | Explicit in Anchor B | The `RUN_PERMITTED` intermediate state is real. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` | Sets `_fault_reason`, `_fault_time`; clears `_active_sources`; `emergency_off`; publishes fault channel states | Explicit in Anchor F / D | Full fault path. |
| `on_keithley_disconnected(...)` | No direct transition; remains `SAFE_OFF` until another event | None immediate | Implicit/absent | Only affects later `_check_preconditions()` and `request_run()`. |
| `on_keithley_heartbeat()` | No direct transition; may contribute to future readiness via `_latest` | `_collect_loop` updates `_latest`; may push temperature rate if unit is `K` | Implicit in Anchor E | No dedicated heartbeat callback exists. |
| `on_reading(...)` | Usually remains `SAFE_OFF`; next monitor tick may move to `READY` if `_check_preconditions()` passes and `_latest` is non-empty | `_latest[channel]=(monotonic_ts, value, status)`; rate buffer updated for `K` units | Implicit in Anchor E | This is how passive promotion to `READY` happens. |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` | `_fault()` path | Explicit in Anchor F | Even from `SAFE_OFF`, interlock emergency escalates to fault. |
| `on_interlock_trip(action="stop_source")` | `SAFE_OFF` (same-state transition) | Acquires `_cmd_lock`; may `keithley.emergency_off()`; clears active sources; publishes Keithley states; records transition unless in fault/manual recovery | Explicit in Anchor F | Creates a `SAFE_OFF -> SAFE_OFF` event record. |
| `acknowledge_fault(...)` | `REJECTED at lines 403-406` | Acquires `_cmd_lock` only | Explicit in Anchor C | Only valid from `FAULT_LATCHED`. |
| `emergency_off()` | `SAFE_OFF` | Acquires `_cmd_lock`; ensures output off; clears requested channels from `_active_sources`; publishes Keithley states; records `SAFE_OFF` transition if no active channels | Implicit in Anchor C | Same-state transition can be recorded. |
| `shutdown()` (`stop()`) | `SAFE_OFF` | If active sources exist, `_safe_off("system stop")`; then cancels collect/monitor tasks | Implicit in `stop()` | With no active sources, state stays `SAFE_OFF` anyway. |

### `READY`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface | No method. |
| `request_run()` | Success: `READY -> RUN_PERMITTED -> RUNNING`; start failure: `FAULT_LATCHED`; precondition/limit failure: stays `READY` | Same as `SAFE_OFF` run path | Explicit in Anchor B | `READY` is a pre-run state only. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` | Full `_fault()` side effects | Explicit | No special-case handling for `READY`. |
| `on_keithley_disconnected(...)` | No immediate transition; remains `READY` | None immediate | Implicit/absent | Next `request_run()` will reject if Keithley required. |
| `on_keithley_heartbeat()` | Remains `READY` | Updates `_latest` / rate buffer if routed as a reading | Implicit | Only prevents future heartbeat absence if run begins. |
| `on_reading(...)` | Remains `READY` | `_collect_loop` still updates `_latest` and rate buffers | Implicit in Anchor E | `_run_checks()` returns early for non-`RUNNING`, so no stale/rate faulting here. |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` | `_fault()` path | Explicit | Safe default is fault. |
| `on_interlock_trip(action="stop_source")` | `SAFE_OFF` | Lock, optional `keithley.emergency_off()`, clear active sources, publish states, transition to `SAFE_OFF` | Explicit | Soft-stop moves `READY` backwards to `SAFE_OFF`. |
| `acknowledge_fault(...)` | `REJECTED at lines 403-406` | Lock only | Explicit | Not applicable outside fault state. |
| `emergency_off()` | `SAFE_OFF` | Lock, ensure output off, publish states, transition if no active sources | Implicit | Since `READY` should have no active sources, it becomes `SAFE_OFF`. |
| `shutdown()` (`stop()`) | `READY` if no active sources | Cancels background tasks; no forced state reset | Implicit | This is the file’s actual behavior, not a full FSM reset. |

### `RUN_PERMITTED`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface | No method. |
| `request_run()` | `REJECTED at lines 201-202` | Lock only | Explicit in Anchor B | Start not allowed from `run_permitted`. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` | `_fault()` path | Explicit | Works from any state. |
| `on_keithley_disconnected(...)` | No immediate transition | None immediate | Implicit/absent | No direct callback. |
| `on_keithley_heartbeat()` | No direct transition | Updates `_latest` / rate buffers only | Implicit | No dedicated heartbeat state change. |
| `on_reading(...)` | Stays `RUN_PERMITTED` | `_collect_loop` updates `_latest`; `_run_checks()` returns early because state is not `RUNNING` | Implicit in Anchor E | **This is the blind state described in F1.** |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` | `_fault()` path | Explicit | Interlock overrides transitional state. |
| `on_interlock_trip(action="stop_source")` | `SAFE_OFF` | Lock, optional `keithley.emergency_off()`, clear sources, publish, transition to `SAFE_OFF` | Explicit | Soft-stop breaks out of run startup. |
| `acknowledge_fault(...)` | `REJECTED at lines 403-406` | Lock only | Explicit | Not fault-latched. |
| `emergency_off()` | Usually `SAFE_OFF` | Lock, ensure output off, clear source set, publish states, transition if no active sources | Implicit | If the channel had not been added to `_active_sources` yet, this still transitions to `SAFE_OFF`. |
| `shutdown()` (`stop()`) | `RUN_PERMITTED` if `_active_sources` still empty | Cancels tasks; no state normalization | Implicit | Another indication that `stop()` is not a full FSM reset. |

### `RUNNING`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface | No method. |
| `request_run()` | Stays `RUNNING` on success; `FAULT_LATCHED` on start failure/fault during start; reject if same channel already active | Lock; precondition check; second `start_source()` allowed for the other SMU channel; publish channel states | Explicit in Anchor B | Multi-channel run is supported. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` | `_fault()` clears `_active_sources`; `emergency_off`; publish fault states | Explicit | Full safety trip. |
| `on_keithley_disconnected(...)` | No immediate direct transition; later `FAULT_LATCHED` when heartbeat age exceeds timeout | None immediate | Implicit via `_has_fresh_keithley_data()` / `_run_checks()` | Disconnect is detected indirectly, not by callback. |
| `on_keithley_heartbeat()` | Usually remains `RUNNING` | Refreshes `_latest` for matching Keithley channels; prevents heartbeat fault | Implicit in Anchor E | No separate handler. |
| `on_reading(...)` | Fresh/valid: stays `RUNNING`; critical stale/status/nonfinite/rate/heartbeat violation: `FAULT_LATCHED` | Updates `_latest`; pushes rate for temperature readings; `_run_checks()` may call `_fault()` | Explicit/implicit mixed | This is the main periodic safety path. |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` | `_fault()` path | Explicit | Hard trip. |
| `on_interlock_trip(action="stop_source")` | `SAFE_OFF` | Lock; `keithley.emergency_off()`; clear all active sources; publish states; transition to `SAFE_OFF` | Explicit | Soft stop bypasses latch. |
| `acknowledge_fault(...)` | `REJECTED at lines 403-406` | Lock only | Explicit | Only valid once already faulted. |
| `emergency_off()` | `SAFE_OFF` if all active sources are removed; otherwise remains `RUNNING` | Lock; hardware-off; remove channels from `_active_sources`; publish states | Implicit in Anchor C | Partial channel emergency-off keeps state `RUNNING` without a transition record. |
| `shutdown()` (`stop()`) | `SAFE_OFF` | `_safe_off("system stop")` with all active channels; then cancels tasks | Implicit | This is the only state where `stop()` reliably forces `SAFE_OFF`. |

### `FAULT_LATCHED`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface | No method. |
| `request_run()` | `REJECTED at lines 198-200` | Lock only | Explicit | Returns current fault reason. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` (same-state transition) | `_fault_reason` overwritten; `_fault_time` reset; `_transition()` records `FAULT_LATCHED -> FAULT_LATCHED`; `emergency_off` retried; publish states | Implicit side effect of `_fault()` | This is allowed by code and can create repeated same-state fault events. |
| `on_keithley_disconnected(...)` | No immediate direct transition | None immediate | Implicit/absent | Already faulted. |
| `on_keithley_heartbeat()` | Remains `FAULT_LATCHED` | `_latest` and rate buffers still update via `_collect_loop` | Implicit | Data still accumulates during latched fault. |
| `on_reading(...)` | Remains `FAULT_LATCHED` | `_collect_loop` updates `_latest` and rate buffers; `_run_checks()` returns early for non-`RUNNING` | Implicit | Readings still matter later for recovery preconditions. |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` (same-state transition) | `_fault()` re-runs and republishes | Explicit | Safe but noisy. |
| `on_interlock_trip(action="stop_source")` | Remains `FAULT_LATCHED` | Lock; `keithley.emergency_off()`; clear active sources; publish states; no transition because fault-latched is excluded at lines 772-778 | Explicit | Soft-stop does not clear latch. |
| `acknowledge_fault(...)` | `MANUAL_RECOVERY` if cooldown elapsed and reason accepted; otherwise rejected | Lock; optional persistence-clear callback; `_recovery_reason` set; transition; publish states | Explicit in Anchor C | This is the only recovery entry point. |
| `emergency_off()` | `FAULT_LATCHED` | Lock; ensures output off; clears source set; publishes; returns `latched=True` warning | Explicit in Anchor C | Latch intentionally remains. |
| `shutdown()` (`stop()`) | `FAULT_LATCHED` if no active sources | Cancels tasks; no state normalization | Implicit | If sources somehow remain, `_safe_off()` just ensures output off and returns because `_safe_off()` rejects in latched state. |

### `MANUAL_RECOVERY`

| Event | Resulting state | Side effects | Documented or implicit | Notes |
|---|---|---|---|---|
| `request_arm()` | `REJECTED` | None | Absent API surface | There is no separate arm command; recovery is automatic via `_run_checks()`. |
| `request_run()` | `REJECTED at lines 201-202` | Lock only | Explicit | Start not allowed from `manual_recovery`. |
| `on_persistence_failure(...)` | `FAULT_LATCHED` | `_fault()` path | Explicit | Recovery can be interrupted by a new fault. |
| `on_keithley_disconnected(...)` | No immediate direct transition | None immediate | Implicit/absent | Recovery depends on future `_check_preconditions()`. |
| `on_keithley_heartbeat()` | Can contribute to `READY` on next monitor tick | Updates `_latest` only | Implicit | Still no dedicated callback. |
| `on_reading(...)` | Remains `MANUAL_RECOVERY` until `_check_preconditions()` passes, then `READY` | `_latest`/rate buffers update; `_run_checks()` in manual recovery only checks preconditions and transitions to `READY` | Explicit in Anchor E | Recovery is automatic, not operator-driven beyond the acknowledgment itself. |
| `on_interlock_trip(action="emergency_off")` | `FAULT_LATCHED` | `_fault()` path | Explicit | Full re-latch. |
| `on_interlock_trip(action="stop_source")` | Remains `MANUAL_RECOVERY` | Lock; hardware off; clear active sources; publish states; no state transition because manual recovery is excluded at lines 772-778 | Explicit | Soft stop does not leave recovery mode. |
| `acknowledge_fault(...)` | `REJECTED at lines 403-406` | Lock only | Explicit | No nested recovery acknowledgment. |
| `emergency_off()` | `SAFE_OFF` if no active sources | Lock; ensure output off; clear source set; publish; transition to `SAFE_OFF` if none active remain | Implicit | This is one of the few commands that can leave `MANUAL_RECOVERY` without passing through `READY`. |
| `shutdown()` (`stop()`) | `MANUAL_RECOVERY` if no active sources | Cancels tasks; no forced reset | Implicit | Stopped object can remain in recovery state. |

## Analysis 2: Lock ordering and reentrancy

### Locks actually present in the file

There is exactly **one explicit lock** in `SafetyManager`:

```python
# src/cryodaq/core/safety_manager.py:112-119
# Lock that serializes _active_sources mutations across await points.
# Multiple REQ clients (GUI subprocess + web dashboard + future
# operator CLI) can race on request_run / request_stop / emergency_off.
self._cmd_lock = asyncio.Lock()
```

No `threading.Lock`, `RLock`, `Condition`, or second `asyncio.Lock` exists in this file.

### `_cmd_lock` acquisition sites

```python
# src/cryodaq/core/safety_manager.py
195: async with self._cmd_lock:   # request_run
276: async with self._cmd_lock:   # request_stop
297: async with self._cmd_lock:   # emergency_off
325: async with self._cmd_lock:   # update_target
361: async with self._cmd_lock:   # update_limits
402: async with self._cmd_lock:   # acknowledge_fault
752: async with self._cmd_lock:   # on_interlock_trip(stop_source)
```

### Lock interaction table

| Lock | Acquired at | Other locks held simultaneously | Reentrant acquisition possible? | Deadlock risk |
|---|---|---|---|---|
| `_cmd_lock` | Lines `195`, `276`, `297`, `325`, `361`, `402`, `752` | None inside this file | No direct same-task reentrancy path exists in current code | No classic lock-order deadlock inside this file because there is only one lock |

### Reentrancy analysis

- `request_run()`, `request_stop()`, `emergency_off()`, `update_target()`, `update_limits()`, and `acknowledge_fault()` all call helper methods that **do not reacquire** `_cmd_lock`.
- `_fault()` does **not** acquire `_cmd_lock`, which is why direct fault paths from `_run_checks()` and `on_persistence_failure()` do not deadlock command handlers.
- The notable exception is the `stop_source` interlock escalation path: it holds `_cmd_lock` and then `await`s `_fault()` inside the locked block.

### Verification of the “_fault() is intentionally outside _cmd_lock” claim

This is **mostly true**, but not universally true in execution.

```python
# src/cryodaq/core/safety_manager.py:791-800
"""Called by SQLiteWriter when persistent storage fails (disk full etc).

Immediately triggers ``_fault`` with a persistence-failure reason.
``_fault`` is intentionally NOT wrapped in ``_cmd_lock`` so this can
be called from any context ...
"""
```

```python
# src/cryodaq/core/safety_manager.py:752-768
async with self._cmd_lock:
    if self._keithley is not None:
        try:
            await self._keithley.emergency_off()
        except Exception as exc:
            ...
            await self._fault(
                f"{reason} (emergency_off failed: {exc})",
                channel=channel, value=value,
            )
            return
```

So the architecture intent is visible, but one concrete code path still executes `_fault()` while the command lock is held. That is not a deadlock in the current file, but it is a real exception to the stated rule and should be treated as such in future reviews.

## Analysis 3: Async cancellation behavior

### Cancellation reference used

From Python’s `asyncio` documentation (`https://docs.python.org/3/library/asyncio-task.html`):

- cancellation raises `CancelledError` “at the next opportunity”
- `asyncio.shield()` protects the inner awaitable from being cancelled with its caller

That matters here because several methods mutate state *before* awaiting hardware I/O.

### Async function review table

| Async function | Explicit `CancelledError` handling? | Partial mutation before await? | State if cancelled mid-op | `shield()` candidate? |
|---|---|---|---|---|
| `start()` | No | Yes: queue subscribe, broker freeze, background tasks created before publish awaits | Manager may be partially started with tasks running and initial publish skipped | Low |
| `stop()` | Only around waiting cancelled tasks | Yes: may call `_safe_off()` before task cancellation | Could stop some hardware, then itself be cancelled before tasks are cancelled | Medium |
| `request_run()` | No | **Yes**: transitions to `RUN_PERMITTED` before `await start_source()` | Can remain `RUN_PERMITTED`; hardware start may be ambiguous | **High** |
| `request_stop()` | No | No state change before first await, but hardware stop loop happens before `_active_sources` update inside `_safe_off()` | Partial hardware stop with stale `_active_sources` possible | Medium |
| `emergency_off()` | No | No state mutation before `_ensure_output_off()`, but physical off is attempted before set update | Hardware may be off while `_active_sources` remains stale, or vice versa | **High** for intent semantics |
| `update_target()` | No | No await after lock acquisition in current implementation | Cancellation mostly only matters while waiting for the lock | Low |
| `update_limits()` | No | Writes hardware before mutating runtime shadow fields | Can leave one compliance write applied and later writes skipped | Medium |
| `acknowledge_fault()` | No | Yes: `_recovery_reason` set, optional callback executed, state transitioned before publish | Can land in `MANUAL_RECOVERY` with publish skipped | Low |
| `_publish_state()` | No | No | At worst one state-broadcast message is dropped | Low |
| `_publish_keithley_channel_states()` | No | Per-channel publish loop | Can publish one channel state but not the second | Low |
| `_fault()` | No | **Yes**: latches fault, clears active sources, then awaits `emergency_off()` | Can report `FAULT_LATCHED` without guaranteed hardware-off completion | **High** |
| `_ensure_output_off()` | No | No | Inner driver emergency-off may be interrupted | High-adjacent |
| `_safe_off()` | No | No state change until after awaited driver stop loop | Some channels may be stopped while set bookkeeping is incomplete | Medium |
| `_collect_loop()` | Yes, clean `return` | No cross-await partial mutation | Safe; one reading may be dropped only at cancellation boundary | OK |
| `_monitor_loop()` | Yes, clean `return` | No, but delegates to `_run_checks()` | Cancellation during `_run_checks()` can interrupt a fault path | Medium |
| `_run_checks()` | No | No state mutation before first await, but fault paths await `_fault()` | Can cancel fault cleanup after decision to fault | Medium/High |
| `on_interlock_trip()` | No | In `stop_source` branch, lock held and emergency-off awaited before transition | Can interrupt soft-stop or hard-fault escalation mid-cleanup | Medium |
| `on_persistence_failure()` | No | No local mutation before awaiting `_fault()` | Same risk as `_fault()` | Medium/High |

### Most important cancellation paths

#### 1. `request_run()`

```python
# src/cryodaq/core/safety_manager.py:218-245
if self._state != SafetyState.RUNNING:
    self._transition(
        SafetyState.RUN_PERMITTED,
        f"Start requested for {smu_channel}: P={p_target}W",
        channel=smu_channel,
        value=p_target,
    )
...
await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
...
if self._state == SafetyState.FAULT_LATCHED:
    await self._keithley.emergency_off()
    return {...}
```

This is the cleanest example of a partially mutated state before an await. Cancellation after the transition but before the await completes leaves `RUN_PERMITTED` behind. Because this call is safety-critical and touches real hardware, this is a strong candidate for a `try/finally` reconciliation or a shielded inner start/stop sequence.

#### 2. `_fault()`

```python
# src/cryodaq/core/safety_manager.py:538-556
self._fault_reason = reason
self._fault_time = time.monotonic()
self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)

self._active_sources.clear()

if self._keithley is not None:
    try:
        await self._keithley.emergency_off()
    except Exception as exc:
        logger.critical("FAULT: emergency_off failed: %s", exc)
...
await self._publish_keithley_channel_states(reason, fault_channel=fault_channel)
```

The latch-first design is good for race visibility, but the actual safety actuation is still cancellable. If the caller can be cancelled, this is the clearest place in the file where `asyncio.shield()` is plausibly justified.

#### 3. `_monitor_loop()` -> `_run_checks()` -> `_fault()`

```python
# src/cryodaq/core/safety_manager.py:643-649
async def _monitor_loop(self) -> None:
    try:
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_S)
            await self._run_checks()
    except asyncio.CancelledError:
        return
```

If the monitor task is cancelled while `_run_checks()` is inside a fault branch, cancellation propagates into `_run_checks()` and then into `_fault()`. The current code does not protect the inner emergency-off from that propagation.

### Places where `shield()` is most defensible

1. Around the inner `keithley.emergency_off()` inside `_fault()`
2. Potentially around the inner driver shutdown call inside `_ensure_output_off()` when invoked from emergency paths
3. Less strongly, around the start/rollback window in `request_run()` if the design requires “start attempt must always conclude with either fully-on or fully-off”

I would **not** recommend scattering `shield()` widely. The strongest case is the fault path because cancellation there directly competes with the safety goal.

## Analysis 4: Time and rate calculations

### Time arithmetic sites

```python
# src/cryodaq/core/safety_manager.py:408-411, 509, 543, 602, 636, 652, 671, 715
elapsed = time.monotonic() - self._fault_time
timestamp=datetime.now(timezone.utc)
self._fault_time = time.monotonic()
now = time.monotonic()
...
self._latest[reading.channel] = (now, reading.value, reading.status.value)
...
if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
...
if any(f"/{alias}/" in channel for alias in aliases) and now - ts < self._config.heartbeat_timeout_s:
    return True
```

### Time/rate audit table

| Location | Clock type | Calculation | Zero / negative / huge delta behavior | Startup behavior |
|---|---|---|---|---|
| `_fault_time` set in `_fault()` | `time.monotonic()` | Stores fault origin for cooldown | Monotonic avoids backward jumps; zero delta just means immediate reject in `acknowledge_fault()` | Safe from first fault onward |
| `acknowledge_fault()` | `time.monotonic()` | `elapsed = now - _fault_time` | If `_fault_time` were still `0.0`, elapsed would be huge; but this method rejects unless already fault-latched | Fine once faulted |
| `_check_preconditions()` | `time.monotonic()` | `age = now - ts` for critical channels | Negative delta should not occur because both values are local monotonic captures; huge delta blocks run | If no matching critical channel exists, run is rejected (unless mock) |
| `_collect_loop()` timestamps | `time.monotonic()` | Stores `now` per reading, not sensor timestamp | No wall-clock sensitivity | First readings create `_latest` entries immediately |
| `_run_checks()` stale check | `time.monotonic()` | `now - ts > stale_timeout_s` | No division; equality does not fault; huge delta faults | Only active in `RUNNING` |
| `_has_fresh_keithley_data()` | `time.monotonic()` | `now - ts < heartbeat_timeout_s` | Equality at exactly timeout is treated as stale (`<`, not `<=`) | Only relevant when active sources exist |
| Rate path | `time.monotonic()` in `SafetyManager`; OLS in `RateEstimator` | `push(channel, now, value)` then `get_rate(channel)` | If insufficient points, `get_rate()` returns `None`; OLS returns `None` on zero denominator | First 59 points are ignored for rate faults |
| Event audit timestamp | `datetime.now(timezone.utc)` | Event log only | Wall-clock jump affects event timestamps, not logic | Cosmetic/provenance only |

### Verification that `min_points=60` is actually applied

```python
# src/cryodaq/core/safety_manager.py:88-96
self._latest: dict[str, tuple[float, float, str]] = {}
...
self._rate_estimator = RateEstimator(window_s=120.0, min_points=60)
```

```python
# src/cryodaq/core/safety_manager.py:637-639, 693-699
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)
...
rate = self._rate_estimator.get_rate(ch)
if rate is None:
    continue
```

```python
# src/cryodaq/core/rate_estimator.py:58-64
def get_rate(self, channel: str) -> float | None:
    channel = self.resolve_channel(channel)
    buf = self._buffers.get(channel)
    if not buf or len(buf) < self._min_points:
        return None
    return _ols_slope_per_min(list(buf))
```

So the previous “min_points=60” fix is not just a constructor comment; it is actually consumed by `get_rate()` and therefore suppresses rate faults until at least 60 temperature points exist for that channel.

### First-N-readings behavior

- Critical stale/status/finite-value checks do **not** wait for N points. They use the latest sample immediately.
- Rate-limit faults do wait because `get_rate()` returns `None` until the buffer has at least `60` samples.
- That means the first safety minutes are governed by freshness/status, not by dT/dt.

### Zero-denominator and negative-time risk

Within `SafetyManager` itself, there is **no direct division by time**. The only division is in `RateEstimator`, and its OLS helper explicitly returns `None` if the denominator is zero or NaN:

```python
# src/cryodaq/core/rate_estimator.py:114-120
num = sum((t - t_mean) * (v - v_mean) for t, v in zip(ts, vs))
den = sum((t - t_mean) ** 2 for t in ts)

if den == 0.0 or math.isnan(den) or math.isnan(num):
    return None

slope_per_sec = num / den
```

That contract is compatible with the SafetyManager use site, which already treats `None` as “not enough usable data yet.”

## Analysis 5: Critical channel handling

### Where critical channels are loaded

```python
# src/cryodaq/core/safety_manager.py:124-155
def load_config(self, path: Path) -> None:
    ...
    patterns: list[re.Pattern[str]] = []
    for pattern in raw.get("critical_channels", []):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            logger.error("Invalid critical_channels regex %r: %s", pattern, exc)
    ...
    self._config = SafetyConfig(
        critical_channels=patterns,
        stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
        heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
        ...
        max_dT_dt_K_per_min=float(raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)),
```

### Actual configured patterns and thresholds

```yaml
# config/safety.yaml:8-18, 28-34, 43-44
critical_channels:
  - "Т1 .*"
  - "Т7 .*"
  - "Т11 .*"
  - "Т12 .*"

stale_timeout_s: 10.0
heartbeat_timeout_s: 15.0

rate_limits:
  max_dT_dt_K_per_min: 5.0

keithley_channels:
  - ".*/smu.*"
```

### Where critical channels are checked before a run

```python
# src/cryodaq/core/safety_manager.py:601-629
def _check_preconditions(self) -> tuple[bool, str]:
    now = time.monotonic()

    for pattern in self._config.critical_channels:
        matched = False
        for ch, (ts, value, status) in self._latest.items():
            if not pattern.match(ch):
                continue
            matched = True
            age = now - ts
            if age > self._config.stale_timeout_s:
                return False, f"Stale data: {ch} ({age:.1f}s)"
            if status != "ok":
                return False, f"Channel {ch} status={status}"
            if math.isnan(value) or math.isinf(value):
                return False, f"Channel {ch} invalid value {value}"
        if not matched and not self._mock:
            return False, f"No data for critical channel: {pattern.pattern}"
```

### Where critical channels are checked during `RUNNING`

```python
# src/cryodaq/core/safety_manager.py:669-706
for pattern in self._config.critical_channels:
    for ch, (ts, _value, _status) in self._latest.items():
        if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
            await self._fault(f"Устаревшие данные канала {ch}", channel=ch)
            return

for ch, (_ts, value, status) in self._latest.items():
    if any(pattern.match(ch) for pattern in self._config.critical_channels):
        if status != "ok":
            await self._fault(f"Channel {ch} status={status}", channel=ch, value=value)
            return
        if math.isnan(value) or math.isinf(value):
            await self._fault(f"Channel {ch}: NaN/Inf", channel=ch, value=value)
            return
...
if abs_rate > self._config.max_dT_dt_K_per_min:
    await self._fault(
        f"Rate limit exceeded {ch}: {abs_rate:.2f} K/min > {self._config.max_dT_dt_K_per_min}",
        channel=ch,
        value=abs_rate,
    )
```

### Behavior by failure class

| Condition on a critical channel | Before run (`_check_preconditions`) | During run (`_run_checks`) | Notes |
|---|---|---|---|
| Channel missing entirely | Run rejected with `No data for critical channel: <pattern>` | No new transition if already `RUNNING` and the channel was never seen; stale checks only iterate `_latest` entries | The pre-run path is stricter than the in-run stale path for never-seen channels. |
| Channel delayed / stale | Run rejected if `age > stale_timeout_s` | Fault-latched if `age > stale_timeout_s` | Uses monotonic age in both paths. |
| Channel status not `"ok"` | Run rejected | Fault-latched | Depends entirely on upstream `reading.status.value`. |
| Value `NaN` / `Inf` | Run rejected | Fault-latched | Explicit finite-value guard exists. |
| Large but finite numeric value with status `"ok"` | **Accepted** | **No direct fault here** unless rate limit trips | `SafetyManager` does not implement absolute temperature bounds in this file. |
| Excessive dT/dt | Not checked in preconditions | Fault-latched once rate estimator returns a numeric rate | Requires 60 K-readings before activation. |

### Cyrillic `Т` vs Latin `T`

Within this file, there is **no homoglyph handling at all**. Matching is purely regex-vs-channel-string.

```python
# src/cryodaq/core/safety_manager.py:604-618
for pattern in self._config.critical_channels:
    matched = False
    for ch, (ts, value, status) in self._latest.items():
        if not pattern.match(ch):
            continue
        matched = True
        ...
    if not matched and not self._mock:
        return False, f"No data for critical channel: {pattern.pattern}"
```

Because the live config contains only Cyrillic `Т` patterns, this file by itself does **not** verify that Latin `T` aliases are equivalent. If the system-wide Phase 1 homoglyph fix exists, it exists outside this file. `SafetyManager` itself remains literal.

## Suspect lines for human review

These are not all separate findings, but they are the places most worth re-reading by a human:

1. `src/cryodaq/core/safety_manager.py:218-232`  
   `RUN_PERMITTED` is entered before awaiting `start_source()`.

2. `src/cryodaq/core/safety_manager.py:654-667`  
   `_run_checks()` returns early for every state except `SAFE_OFF`, `MANUAL_RECOVERY`, and `RUNNING`.

3. `src/cryodaq/core/safety_manager.py:538-556`  
   `_fault()` clears logical source state before awaited hardware shutdown.

4. `src/cryodaq/core/safety_manager.py:752-768`  
   Interlock escalation comment does not match actual lock lifetime.

5. `src/cryodaq/core/safety_manager.py:165-177`  
   `stop()` stops tasks but does not normalize final FSM state unless active sources existed.

6. `src/cryodaq/core/safety_manager.py:601-618`  
   Critical-channel matching is literal regex matching with no homoglyph normalization.

7. `src/cryodaq/core/safety_manager.py:669-706`  
   During run, “missing forever” critical channels are not rechecked the same way as pre-run “never seen” channels.

## Bottom line

The core FSM logic is understandable and mostly internally consistent:

- there is one authoritative state enum
- `_fault()` latches synchronously before awaits
- command mutations are mostly serialized by a single `_cmd_lock`
- time-based safety logic uses monotonic time, not wall clock
- the rate estimator fix to `min_points=60` is actually wired through

But the file is **not** exhaustively safe under cancellation and long-start concurrency. The two strongest issues are the `RUN_PERMITTED` monitoring blind spot and the lack of cancellation shielding in the actual hardware-off path.

## Summary counts

- **Total transitions analyzed:** 66
- **Locks identified:** 1 explicit lock (`_cmd_lock`)
- **Async functions reviewed:** 18
- **New findings in this pass:** 2 HIGH, 2 MEDIUM, 1 LOW
- **Suspect line ranges flagged for human review:** 7
