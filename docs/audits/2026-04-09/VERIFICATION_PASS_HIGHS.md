# CryoDAQ Verification Pass — Re-check of 5 HIGH findings

**Date:** 2026-04-09  
**Working tree:** `master`  
**Reference report:** `HARDENING_PASS_CODEX.md` from commit `98a57c5`  
**Scope:** Re-verify only `H.5`, `H.6`, `H.10`, `H.11`, `H.14` from the previous hardening pass. No web research. No new findings outside these five items.

## Method

For each item below I did four things:

1. Opened the exact section in `98a57c5:HARDENING_PASS_CODEX.md` and copied the original cited location.
2. Re-read the live code on `master` with at least 30 lines of context around the cited range.
3. Collected full code snippets, not just file:line references.
4. Re-classified each item as `VERIFIED REAL`, `PARTIALLY VERIFIED`, or `NOT REPRODUCIBLE`.

One important repo-history note: the branch name `feat/ui-phase-1` no longer points at commit `98a57c5`, so the frozen reference for the prior audit had to be read by commit hash, not by branch name.

---

## H.5 Adaptive throttle vs `alarm_v2` stale alarms

**Previous report source:** `98a57c5:HARDENING_PASS_CODEX.md` lines 135-167  
**Previous cited locations:** `src/cryodaq/core/scheduler.py:331-377`, `src/cryodaq/engine.py:1015-1027`, `src/cryodaq/core/housekeeping.py:223-307`, `config/alarms_v3.yaml:128-133`

### Context read

- `src/cryodaq/core/scheduler.py:301-390`
- `src/cryodaq/engine.py:995-1045`
- `src/cryodaq/core/housekeeping.py:216-310`
- `src/cryodaq/core/alarm_v2.py:339-375`
- `src/cryodaq/core/alarm_config.py:136-172`
- `src/cryodaq/core/housekeeping.py:119-205`
- `config/alarms_v3.yaml:1-25`
- `config/alarms_v3.yaml:127-150`
- `config/housekeeping.yaml:1-17`
- `config/instruments.yaml:1-53`

### Code evidence

```python
# src/cryodaq/core/scheduler.py:311-377
async def _process_readings(
    self, state: _InstrumentState, readings: list[Any]
) -> None:
    """Persist, calibrate, and publish readings — shared by both loop types."""
    driver = state.config.driver
    name = driver.name

    if (
        self._sqlite_writer is not None
        and getattr(self._sqlite_writer, "is_disk_full", False)
    ):
        return

    persisted_readings = list(readings)
    if self._adaptive_throttle is not None:
        persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
    state.total_reads += 1
    state.consecutive_errors = 0
    state.backoff_s = INITIAL_BACKOFF_S

    if self._sqlite_writer is not None and persisted_readings:
        try:
            await self._sqlite_writer.write_immediate(persisted_readings)
        except Exception:
            logger.exception(
                "CRITICAL: Ошибка записи '%s' — данные НЕ отправлены подписчикам",
                name,
            )
            state.consecutive_errors += 1
            state.total_errors += 1
            return

        if getattr(self._sqlite_writer, "is_disk_full", False):
            return

    if (
        self._calibration_acquisition is not None
        and self._calibration_acquisition.is_active
        and hasattr(driver, "read_srdg_channels")
    ):
        try:
            srdg = await driver.read_srdg_channels()
            await self._calibration_acquisition.on_readings(readings, srdg)
        except Exception:
            logger.warning(
                "Failed to read SRDG for calibration on '%s'",
                name,
                exc_info=True,
            )

    if persisted_readings:
        await self._broker.publish_batch(persisted_readings)
    if self._safety_broker is not None:
        await self._safety_broker.publish_batch(readings)
```

```python
# src/cryodaq/engine.py:1007-1027
async def _track_runtime_signals() -> None:
    queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
    try:
        while True:
            adaptive_throttle.observe_runtime_signal(await queue.get())
    except asyncio.CancelledError:
        return

async def _alarm_v2_feed_readings() -> None:
    """Подписаться на DataBroker и кормить v2 channel_state + rate_estimator."""
    queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
    try:
        while True:
            reading: Reading = await queue.get()
            _alarm_v2_state_tracker.update(reading)
            _alarm_v2_rate.push(
                reading.channel,
                reading.timestamp.timestamp(),
                reading.value,
            )
    except asyncio.CancelledError:
        return
```

```python
# src/cryodaq/core/housekeeping.py:216-307
class AdaptiveThrottle:
    def __init__(self, config: dict[str, Any] | None = None, *, protected_patterns: list[str] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self._include = [re.compile(str(item)) for item in cfg.get("include_patterns", [])]
        self._exclude = [re.compile(str(item)) for item in cfg.get("exclude_patterns", [])]
        self._protected = [re.compile(str(item)) for item in (protected_patterns or [])]
        self._stable_duration_s = float(cfg.get("stable_duration_s", 120.0))
        self._max_interval_s = float(cfg.get("max_interval_s", 30.0))
        self._transition_holdoff_s = float(cfg.get("transition_holdoff_s", 30.0))
        ...

    def _should_emit(self, reading: Reading) -> bool:
        if self._active_alarm_count > 0:
            return True
        if reading.status is not ChannelStatus.OK:
            return True
        if self._transition_until is not None and reading.timestamp <= self._transition_until:
            return True
        if self._matches_any(reading.channel, self._protected):
            return True
        if self._matches_any(reading.channel, self._exclude):
            return True
        if self._include and not self._matches_any(reading.channel, self._include):
            return True

        state = self._state.get(reading.channel)
        if state is None:
            self._state[reading.channel] = _ThrottleState(
                last_seen_value=reading.value,
                last_emitted_value=reading.value,
                last_emitted_at=reading.timestamp,
                stable_since=reading.timestamp,
            )
            return True
        ...
        stable_for = (now - state.stable_since).total_seconds()
        since_emit = (now - state.last_emitted_at).total_seconds()
        if stable_for < self._stable_duration_s:
            state.last_emitted_value = reading.value
            state.last_emitted_at = now
            return True
        if since_emit >= self._max_interval_s:
            state.last_emitted_value = reading.value
            state.last_emitted_at = now
            return True
        return False
```

```python
# src/cryodaq/core/alarm_v2.py:339-375
def _eval_stale(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
    timeout = cfg.get("timeout_s", 30.0)
    channels = self._resolve_channels(cfg)
    level = cfg.get("level", "WARNING")
    message_tmpl = cfg.get("message", f"Stale data: {{channel}}")
    now = time.time()

    for ch in channels:
        state = self._state.get(ch)
        if state is None:
            continue
        if (now - state.timestamp) > timeout:
            msg = self._format_message(message_tmpl, channel=ch, value=0.0)
            return AlarmEvent(
                alarm_id=alarm_id,
                level=level,
                message=msg,
                triggered_at=now,
                channels=[ch],
                values={ch: now - state.timestamp},
            )
    return None

def _resolve_channels(self, cfg: dict) -> list[str]:
    """Раскрыть каналы из channel / channels / channel_group в config."""
    if "channels" in cfg:
        return list(cfg["channels"])
    if "channel" in cfg:
        ch = cfg["channel"]
        if ch != "phase_elapsed_s":
            return [ch]
    return []
```

```python
# src/cryodaq/core/alarm_config.py:136-172
def _expand_alarm(
    alarm_id: str,
    alarm_raw: Any,
    channel_groups: dict[str, list[str]],
    phase_filter: list[str] | None = None,
) -> AlarmConfig | None:
    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group."""
    if not isinstance(alarm_raw, dict):
        return None

    cfg = copy.deepcopy(alarm_raw)
    notify: list[str] = cfg.pop("notify", []) or []
    for key in ("gui_action", "side_effect"):
        cfg.pop(key, None)

    _expand_channel_group(cfg, channel_groups)

    for cond in cfg.get("conditions", []):
        if isinstance(cond, dict):
            _expand_channel_group(cond, channel_groups)

    return AlarmConfig(
        alarm_id=alarm_id,
        config=cfg,
        phase_filter=phase_filter,
        notify=notify if isinstance(notify, list) else [notify],
    )

def _expand_channel_group(cfg: dict, groups: dict[str, list[str]]) -> None:
    """Заменить channel_group → channels in-place."""
    group_name = cfg.pop("channel_group", None)
    if group_name and group_name in groups:
        cfg["channels"] = list(groups[group_name])
```

```python
# src/cryodaq/core/housekeeping.py:119-160, 168-205
def load_critical_channels_from_alarms_v3(config_path: Path) -> set[str]:
    """Extract channel patterns of critical alarms + all interlocks from alarms_v3.yaml."""
    ...
    global_alarms = data.get("global_alarms") or {}
    if isinstance(global_alarms, dict):
        for _alarm_name, alarm in global_alarms.items():
            if not isinstance(alarm, dict):
                continue
            level = str(alarm.get("level", "")).strip().lower()
            if level not in _CRITICAL_LEVELS:
                continue
            refs.extend(_extract_channel_refs(alarm))
    ...
    for ref in refs:
        if ref.startswith("__group__:"):
            group_name = ref.removeprefix("__group__:")
            channels = groups.get(group_name)
            if not channels:
                logger.warning(...)
                continue
            for ch in channels:
                patterns.add(re.escape(ch))
        else:
            patterns.add(re.escape(ref))

    return patterns
```

```yaml
# config/alarms_v3.yaml:15-18, 128-142
engine:
  poll_interval_s: 0.5
  rate_window_s: 120
  rate_min_points: 60

data_stale_temperature:
  alarm_type: stale
  channel_group: all_temp
  timeout_s: 30
  level: WARNING
  message: "Нет данных от {instrument} > 30с."

data_loss_temperature:
  alarm_type: stale
  channel_group: all_temp
  timeout_s: 120
  level: CRITICAL
```

```yaml
# config/housekeeping.yaml:1-17
adaptive_throttle:
  enabled: true
  include_patterns:
    - "^T(?![1-8] ).*"
    - "pressure"
  exclude_patterns:
    - "^analytics/"
    - "^alarm/"
    - "^system/"
  stable_duration_s: 120.0
  max_interval_s: 30.0
  absolute_delta:
    default: 0.05
    K: 0.02
  transition_holdoff_s: 30.0
```

```yaml
# config/instruments.yaml:1-53
instruments:
  - type: lakeshore_218s
    name: "LS218_1"
    resource: "GPIB0::12::INSTR"
    poll_interval_s: 2.0
  - type: lakeshore_218s
    name: "LS218_2"
    resource: "GPIB0::14::INSTR"
    poll_interval_s: 2.0
  - type: lakeshore_218s
    name: "LS218_3"
    resource: "GPIB0::16::INSTR"
    poll_interval_s: 2.0
  - type: keithley_2604b
    name: "Keithley_1"
    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
    poll_interval_s: 1.0
```

### Verdict

**PARTIALLY VERIFIED.**

### Why partial

The structural part of the old finding is real:

- `alarm_v2` is fed from `DataBroker`, not `SafetyBroker`.
- `DataBroker` receives `persisted_readings`, which are filtered by `AdaptiveThrottle`.
- `data_stale_temperature.timeout_s` is `30`, while `adaptive_throttle.max_interval_s` is also `30.0`.
- The warning stale alarm is not part of `protected_patterns`, because throttle protection is built from critical/high alarms and interlocks only.

But the previous wording was too strong in one specific place: it said the system can effectively self-trigger the 30 s warning by configuration alone. That is not strictly proven from the code. `AlarmEvaluator._eval_stale()` uses `>` rather than `>=`, and with the nominal 2.0 s instrument poll the throttle would ordinarily re-emit on the 30.0 s poll, not after it. A false stale therefore needs normal runtime slippage or poll jitter, not just the static equality of the two numbers.

### Minimal failing scenario

1. `scheduler._process_readings()` filters a stable temperature channel at `src/cryodaq/core/scheduler.py:331-333`.
2. `AdaptiveThrottle._should_emit()` suppresses stable points until `since_emit >= 30.0` at `src/cryodaq/core/housekeeping.py:297-307`.
3. `alarm_v2` tracks only the filtered stream because `_alarm_v2_feed_readings()` consumes `broker.subscribe(...)` at `src/cryodaq/engine.py:1015-1027`.
4. If a nominal 30.0 s re-emit is delayed past 30.0 s by even one late poll or event-loop jitter, `_eval_stale()` trips at `src/cryodaq/core/alarm_v2.py:351`.
5. The resulting warning is about the thinned stream, not about a genuine total absence of raw readings.

### Re-classified statement

The previous HIGH should be narrowed to: the coupling is real and risky, but the report overstated certainty. This is a real edge-condition hazard, not a mathematically guaranteed false alarm on every stable channel.

---

## H.6 Safety faults do not propagate to experiment lifecycle

**Previous report source:** `98a57c5:HARDENING_PASS_CODEX.md` lines 184-207  
**Previous cited locations:** `src/cryodaq/core/safety_manager.py:447-533`, `src/cryodaq/core/experiment.py:682-770`, `src/cryodaq/engine.py:1177-1220`

### Context read

- `src/cryodaq/core/safety_manager.py:430-545`
- `src/cryodaq/core/experiment.py:650-810`
- `src/cryodaq/engine.py:780-880`
- repo-wide `grep -rn "on_state_change" src/cryodaq/`

### Full grep output requested

```text
src/cryodaq/core/safety_manager.py:119:        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []
src/cryodaq/core/safety_manager.py:447:    def on_state_change(self, callback: Callable[[SafetyState, SafetyState, str], Any]) -> None:
src/cryodaq/core/safety_manager.py:448:        self._on_state_change.append(callback)
src/cryodaq/core/safety_manager.py:521:        for callback in self._on_state_change:
Binary file src/cryodaq/core/__pycache__/safety_manager.cpython-314.pyc matches
```

### Code evidence

```python
# src/cryodaq/core/safety_manager.py:447-545
def on_state_change(self, callback: Callable[[SafetyState, SafetyState, str], Any]) -> None:
    self._on_state_change.append(callback)

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
        try:
            callback(old_state, new_state, reason)
        except Exception:
            logger.exception("State change callback failed")
    ...

async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
    self._fault_reason = reason
    self._fault_time = time.monotonic()
    self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)
```

```python
# src/cryodaq/engine.py:806-857
safety_manager = SafetyManager(
    safety_broker,
    keithley_driver=keithley_driver,
    mock=mock,
    data_broker=broker,
)
safety_manager.load_config(safety_cfg)

housekeeping_raw = load_housekeeping_config(housekeeping_cfg)
...
adaptive_throttle = AdaptiveThrottle(
    housekeeping_raw.get("adaptive_throttle", {}),
    protected_patterns=merged_patterns,
)

writer = SQLiteWriter(_DATA_DIR)
await writer.start_immediate()
writer.set_event_loop(asyncio.get_running_loop())
writer.set_persistence_failure_callback(safety_manager.on_persistence_failure)
safety_manager.set_persistence_failure_clear(writer.clear_disk_full)

calibration_acquisition = CalibrationAcquisitionService(writer)

scheduler = Scheduler(
    broker,
    safety_broker=safety_broker,
    sqlite_writer=writer,
    adaptive_throttle=adaptive_throttle,
    calibration_acquisition=calibration_acquisition,
)
```

```python
# src/cryodaq/core/experiment.py:682-770
def finalize_experiment(
    self,
    experiment_id: str | None = None,
    *,
    status: ExperimentStatus = ExperimentStatus.COMPLETED,
    ...
) -> ExperimentInfo:
    self._require_experiment_mode()
    active = self._require_active(experiment_id)

    finished = ExperimentInfo(
        experiment_id=active.experiment_id,
        ...
        end_time=_parse_time(end_time) or datetime.now(timezone.utc),
        status=status,
        ...
    )
    ...
    self._clear_active()
    return finished

def stop_experiment(
    self,
    experiment_id: str | None = None,
    *,
    status: ExperimentStatus = ExperimentStatus.COMPLETED,
) -> None:
    self.finalize_experiment(experiment_id=experiment_id, status=status)

def abort_experiment(
    self,
    experiment_id: str | None = None,
    *,
    ...
) -> ExperimentInfo:
    return self.finalize_experiment(
        experiment_id=experiment_id,
        status=ExperimentStatus.ABORTED,
        ...
    )
```

### Verdict

**VERIFIED REAL.**

### Actual impact statement

When the safety layer latches a fault, the hardware state changes immediately, but the experiment metadata path does not change with it. An active experiment can therefore remain marked as running even after the source has been forced off and the system is faulted. That creates a provenance hole: overnight reports and morning handoff can show a seemingly continuous run while the real physical run was interrupted by a safety event. In a safety-critical lab this is not just UI drift; it undermines the integrity of experiment records and post-mortem reconstruction.

### Minimal failing scenario

1. An interlock or stale channel drives `SafetyManager._fault()` at `src/cryodaq/core/safety_manager.py:538-545`.
2. `_transition()` runs callbacks at `src/cryodaq/core/safety_manager.py:521-525`, but the grep output shows no registration site anywhere under `src/cryodaq/`.
3. `ExperimentManager` status only changes through `finalize_experiment()`, `stop_experiment()`, or `abort_experiment()` at `src/cryodaq/core/experiment.py:682-770`.
4. The engine wiring block that creates `SafetyManager` at `src/cryodaq/engine.py:808-857` does not register any state-change bridge into `ExperimentManager`.
5. Result: safety state becomes `FAULT_LATCHED`, but experiment lifecycle remains untouched until a human or separate command changes it.

---

## H.10 Calibration KRDG/SRDG persistence not atomic

**Previous report source:** `98a57c5:HARDENING_PASS_CODEX.md` lines 294-317  
**Previous cited locations:** `src/cryodaq/core/scheduler.py:338-366`, `src/cryodaq/core/calibration_acquisition.py:95-122`

### Context read

- `src/cryodaq/core/scheduler.py:311-377`
- `src/cryodaq/core/calibration_acquisition.py:71-122`
- `src/cryodaq/storage/sqlite_writer.py:525-568`
- `src/cryodaq/storage/sqlite_writer.py:294-324`

### Code evidence

```python
# src/cryodaq/core/scheduler.py:338-377
if self._sqlite_writer is not None and persisted_readings:
    try:
        await self._sqlite_writer.write_immediate(persisted_readings)
    except Exception:
        logger.exception(
            "CRITICAL: Ошибка записи '%s' — данные НЕ отправлены подписчикам",
            name,
        )
        state.consecutive_errors += 1
        state.total_errors += 1
        return

    if getattr(self._sqlite_writer, "is_disk_full", False):
        return

if (
    self._calibration_acquisition is not None
    and self._calibration_acquisition.is_active
    and hasattr(driver, "read_srdg_channels")
):
    try:
        srdg = await driver.read_srdg_channels()
        await self._calibration_acquisition.on_readings(readings, srdg)
    except Exception:
        logger.warning(
            "Failed to read SRDG for calibration on '%s'",
            name,
            exc_info=True,
        )

if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

```python
# src/cryodaq/core/calibration_acquisition.py:71-122
async def on_readings(
    self,
    krdg: list[Reading],
    srdg: list[Reading],
) -> None:
    """Process one poll cycle of KRDG + SRDG readings."""
    if not self._active:
        return

    for r in krdg:
        if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
            t = r.value
            if not math.isfinite(t) or t < 1.0:
                continue
            if self._t_min is None or t < self._t_min:
                self._t_min = t
            if self._t_max is None or t > self._t_max:
                self._t_max = t

    to_write: list[Reading] = []
    for reading in srdg:
        if reading.channel not in self._target_channels:
            continue
        if reading.status != ChannelStatus.OK:
            continue
        if not math.isfinite(reading.value):
            continue
        to_write.append(
            Reading(
                timestamp=reading.timestamp,
                instrument_id=reading.instrument_id,
                channel=f"{reading.channel}_raw",
                value=reading.value,
                unit="sensor_unit",
                status=ChannelStatus.OK,
                raw=reading.value,
                metadata={
                    "reading_kind": "calibration_srdg",
                    "source_channel": reading.channel,
                },
            )
        )

    if to_write:
        await self._writer.write_immediate(to_write)
        self._point_count += len(to_write)
```

```python
# src/cryodaq/storage/sqlite_writer.py:525-540
async def write_immediate(self, readings: list[Reading]) -> None:
    """Записать пакет синхронно (await до WAL commit)."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(self._executor, self._write_batch, readings)
    except Exception:
        logger.critical(
            "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
            len(readings),
        )
        raise
```

```python
# src/cryodaq/storage/sqlite_writer.py:294-324
def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
    rows = []
    for r in batch:
        ...
        rows.append(
            (
                r.timestamp.timestamp(),
                r.instrument_id or "unknown",
                r.channel,
                r.value,
                r.unit,
                r.status.value,
            )
        )
    if not rows:
        return
    try:
        conn.executemany(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            rows,
        )
        conn.commit()
```

### Verdict

**VERIFIED REAL.**

### Actual impact statement

The calibration path persists one poll cycle in two separate write phases: first the ordinary KRDG readings, then the derived SRDG companion points. If the process dies, is cancelled, or the second step raises after the first commit, the database keeps a half-complete calibration cycle with no marker that it is incomplete. Downstream tooling then sees a valid-looking temperature history with missing raw calibration counterparts, which is a silent data-integrity failure rather than a loud crash. For calibration work this is exactly the kind of corruption that can survive unnoticed until analysis time.

### Minimal failing scenario

1. `Scheduler._process_readings()` commits `persisted_readings` through `write_immediate()` at `src/cryodaq/core/scheduler.py:338-355`.
2. `SQLiteWriter.write_immediate()` performs one executor call to `_write_batch()` at `src/cryodaq/storage/sqlite_writer.py:525-540`.
3. `_write_day_batch()` commits that batch at `src/cryodaq/storage/sqlite_writer.py:319-324`.
4. Only after that commit does the scheduler call `driver.read_srdg_channels()` and then `CalibrationAcquisitionService.on_readings()` at `src/cryodaq/core/scheduler.py:357-366`.
5. `on_readings()` makes a second independent `write_immediate()` call at `src/cryodaq/core/calibration_acquisition.py:120-121`. Any failure or shutdown between steps 3 and 5 leaves KRDG present and SRDG absent for the same poll cycle.

---

## H.11 Cooldown predictor mixes wall-clock and monotonic

**Previous report source:** `98a57c5:HARDENING_PASS_CODEX.md` lines 318-343  
**Previous cited locations:** `src/cryodaq/analytics/cooldown_service.py:96-161`, `src/cryodaq/analytics/cooldown_service.py:297-354`

### Context read

- `src/cryodaq/analytics/cooldown_service.py:90-170`
- `src/cryodaq/analytics/cooldown_service.py:286-372`

### Code evidence

```python
# src/cryodaq/analytics/cooldown_service.py:96-161
def update(self, ts: float, T_cold: float) -> CooldownPhase:
    """Обновить состояние детектора по новому показанию.

    Args:
        ts: монотонное время (time.monotonic()) в секундах
        T_cold: текущая температура холодной ступени, K
    """
    self._recent.append((ts, T_cold))

    dT_dt = self._estimate_rate()

    if self._phase == CooldownPhase.IDLE:
        if dT_dt is not None and dT_dt < self._start_rate_thr:
            if self._confirm_start_ts is None:
                self._confirm_start_ts = ts
            elif ts - self._confirm_start_ts >= self._start_confirm_s:
                self._phase = CooldownPhase.COOLING
                self._cooldown_start_ts = self._confirm_start_ts
                self._confirm_start_ts = None
                logger.info(...)
        else:
            self._confirm_start_ts = None
    ...

def _estimate_rate(self) -> Optional[float]:
    if len(self._recent) < 5:
        return None
    ts_arr = [p[0] for p in self._recent]
    T_arr = [p[1] for p in self._recent]
    dt_s = ts_arr[-1] - ts_arr[0]
    if dt_s < 30.0:
        return None
    dT = T_arr[-1] - T_arr[0]
    return dT / (dt_s / 3600.0)
```

```python
# src/cryodaq/analytics/cooldown_service.py:286-354
async def _consume_loop(self) -> None:
    try:
        while self._running:
            try:
                reading: Reading = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0,
                )
            except asyncio.TimeoutError:
                continue

            reading_ts = reading.timestamp.timestamp()

            if reading.channel == self._channel_cold:
                self._last_T_cold = reading.value
                # Update detector (use reading timestamp for correct dT/dt)
                self._detector.update(reading_ts, reading.value)
            elif reading.channel == self._channel_warm:
                self._last_T_warm = reading.value

            phase = self._detector.phase
            if phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING):
                if self._cooldown_wall_start is None:
                    self._cooldown_wall_start = reading_ts

                t_hours = (reading_ts - self._cooldown_wall_start) / 3600.0
                ...
    except asyncio.CancelledError:
        return

async def _do_predict(self) -> None:
    if self._model is None:
        return
    ...
    if self._cooldown_wall_start is not None and cooldown_active:
        t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
    else:
        t_elapsed = 0.0
```

### Verdict

**VERIFIED REAL.**

### Actual impact statement

The detector contract says it wants monotonic time, but the live pipeline feeds Unix wall-clock timestamps and later subtracts those values from a fresh `time.time()` call. That means clock steps can alter both the phase detector and the elapsed-time input to prediction without any physical change in the cryostat. A backward NTP correction can delay or reset confirmation windows, while a forward jump can suddenly inflate elapsed time and push the forecast into nonsense. These failures are subtle because the service keeps running and produces plausible-looking numbers instead of crashing.

### Minimal failing scenario

1. `CooldownDetector.update()` documents `ts` as monotonic and uses differences such as `ts - self._confirm_start_ts` at `src/cryodaq/analytics/cooldown_service.py:100-117`.
2. The live caller passes `reading.timestamp.timestamp()` at `src/cryodaq/analytics/cooldown_service.py:297-302`.
3. `_estimate_rate()` calculates `dt_s = ts_arr[-1] - ts_arr[0]` at `src/cryodaq/analytics/cooldown_service.py:154-161`, so a backward time step shrinks or inverts the window.
4. `_consume_loop()` also builds buffer time from wall clock at `src/cryodaq/analytics/cooldown_service.py:309-315`.
5. `_do_predict()` mixes the earlier wall-clock start with a fresh `time.time()` at `src/cryodaq/analytics/cooldown_service.py:351-354`, so a clock correction directly changes `t_elapsed` even if no new thermal behavior occurred.

---

## H.14 Stored XSS via operator log

**Previous report source:** `98a57c5:HARDENING_PASS_CODEX.md` lines 418-445  
**Previous cited locations:** `src/cryodaq/notifications/telegram_commands.py:392-406`, `src/cryodaq/core/operator_log.py:30-38`, `src/cryodaq/web/server.py:497-503`

### Context read

- `src/cryodaq/notifications/telegram_commands.py:384-410`
- `src/cryodaq/engine.py:162-202`
- `src/cryodaq/storage/sqlite_writer.py:542-586`
- `src/cryodaq/core/operator_log.py:20-39`
- `src/cryodaq/web/server.py:364-373`
- `src/cryodaq/web/server.py:468-508`
- `rg -n "innerHTML" src/cryodaq/web/server.py`

### Full `innerHTML` grep output requested

```text
484:  document.getElementById('temps').innerHTML=temps||'Нет данных';
503:  document.getElementById('log').innerHTML=html||'Нет записей';
```

### Code evidence

```python
# src/cryodaq/notifications/telegram_commands.py:392-406
async def _cmd_log(self, chat_id: int, text: str, msg: dict) -> None:
    if not text:
        await self._send(chat_id, "❌ Укажите текст: /log &lt;текст&gt;")
        return
    if self._command_handler is None:
        await self._send(chat_id, "❌ Команды недоступны (нет command_handler)")
        return
    from_info = msg.get("from", {})
    username = from_info.get("username") or from_info.get("first_name", "telegram")
    result = await self._command_handler({
        "cmd": "log_entry",
        "message": text,
        "author": username,
        "source": "telegram",
    })
```

```python
# src/cryodaq/engine.py:162-202
async def _run_operator_log_command(
    action: str,
    cmd: dict[str, Any],
    writer: SQLiteWriter,
    experiment_manager: ExperimentManager,
    broker: DataBroker | None = None,
) -> dict[str, Any]:
    if action == "log_entry":
        message = str(cmd.get("message", "")).strip()
        if not message:
            raise ValueError("Operator log message must not be empty.")
        ...
        entry = await writer.append_operator_log(
            message=message,
            author=str(cmd.get("author", "")).strip(),
            source=str(cmd.get("source", "")).strip() or "command",
            experiment_id=str(experiment_id) if experiment_id is not None else None,
            tags=cmd.get("tags"),
            timestamp=_parse_log_time(cmd.get("timestamp")),
        )
        await _publish_operator_log_entry(broker, entry)
        return {"ok": True, "entry": entry.to_payload()}

    if action == "log_get":
        ...
        entries = await writer.get_operator_log(...)
        return {"ok": True, "entries": [entry.to_payload() for entry in entries]}
```

```python
# src/cryodaq/storage/sqlite_writer.py:542-568
async def append_operator_log(
    self,
    *,
    message: str,
    author: str = "",
    source: str = "command",
    ...
) -> OperatorLogEntry:
    text = message.strip()
    if not text:
        raise ValueError("Operator log message must not be empty.")

    normalized_tags = normalize_operator_log_tags(tags)
    entry_time = timestamp or datetime.now(timezone.utc)
    loop = asyncio.get_running_loop()
    task = partial(
        self._write_operator_log_entry,
        timestamp=entry_time,
        experiment_id=experiment_id,
        author=author.strip(),
        source=source.strip() or "command",
        message=text,
        tags=normalized_tags,
    )
    return await loop.run_in_executor(self._executor, task)
```

```python
# src/cryodaq/core/operator_log.py:20-39
@dataclass(frozen=True, slots=True)
class OperatorLogEntry:
    id: int
    timestamp: datetime
    experiment_id: str | None
    author: str
    source: str
    message: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "experiment_id": self.experiment_id,
            "author": self.author,
            "source": self.source,
            "message": self.message,
            "tags": list(self.tags),
        }
```

```python
# src/cryodaq/web/server.py:364-373
@application.get("/api/log")
async def api_log(limit: int = 10) -> dict[str, Any]:
    """Последние записи журнала."""
    try:
        result = await _async_engine_command({"cmd": "log_get", "limit": limit})
        if result.get("ok"):
            return {"ok": True, "entries": result.get("entries", [])}
    except Exception:
        pass
    return {"ok": False, "entries": []}
```

```javascript
// src/cryodaq/web/server.py:472-503
const readings=d.readings||{};
let temps='',pressure='—',kA='ВЫКЛ',kB='ВЫКЛ';
const sorted=Object.entries(readings).sort((a,b)=>a[0].localeCompare(b[0]));
for(const[ch,r]of sorted){
 if(r.unit==='K'&&ch.match(/^\u0422|^T/)){
  const c=tempColor(r.value);
  temps+=`<div class="temp-card"><div class="name">${ch.split(' ')[0]}</div><div class="val ${c}">${r.value.toFixed(2)}</div></div>`;
 }
 if(r.unit==='mbar')pressure=r.value.toExponential(2)+' mbar';
 if(ch.includes('/smua/'))kA=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kA;
 if(ch.includes('/smub/'))kB=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kB;
}
document.getElementById('temps').innerHTML=temps||'Нет данных';
...
const lr=await fetch('/api/log?limit=5');const ld=await lr.json();
let html='';
for(const e of(ld.entries||[])){
 const ts=(e.timestamp||'').split('T')[1]||'';
 html+=`<div class="log-entry"><span class="ts">${ts.substring(0,8)}</span> [${e.author||e.source||'?'}] ${e.message||''}</div>`;
}
document.getElementById('log').innerHTML=html||'Нет записей';
```

### Verdict

**VERIFIED REAL.**

### Actual impact statement

Operator log text goes from Telegram or any other log-entry source into SQLite, back out through `/api/log`, and then straight into `innerHTML` with no escaping. That is a classic stored XSS flow: the payload is persisted once and executes every time someone opens the dashboard. Because the same rendering line also interpolates `author` and `source`, the attack surface is not limited to the message body. In practice this means the monitoring dashboard can become an execution surface for any actor who is allowed to submit operator log entries.

### All `innerHTML` sinks in `src/cryodaq/web/server.py`

1. `src/cryodaq/web/server.py:484`  
   `document.getElementById('temps').innerHTML=temps||'Нет данных';`  
   This is a raw HTML sink. In the current code it is populated from reading channel names and values, not from operator log entries.

2. `src/cryodaq/web/server.py:503`  
   `document.getElementById('log').innerHTML=html||'Нет записей';`  
   This is the verified stored-XSS sink for H.14 because `html` is built from persisted operator-log `author/source/message` fields returned by `/api/log`.

### Minimal failing scenario

1. An allowed operator sends `/log <img src=x onerror=alert(1)>`, which reaches `_cmd_log()` at `src/cryodaq/notifications/telegram_commands.py:392-406`.
2. `_run_operator_log_command()` stores the message unchanged at `src/cryodaq/engine.py:169-187`.
3. `append_operator_log()` strips whitespace but does not escape HTML at `src/cryodaq/storage/sqlite_writer.py:552-568`.
4. `OperatorLogEntry.to_payload()` returns the raw string at `src/cryodaq/core/operator_log.py:30-38`.
5. `/api/log` returns that payload at `src/cryodaq/web/server.py:364-370`, and the dashboard injects it into `innerHTML` at `src/cryodaq/web/server.py:499-503`.

---

## Final classification

- **H.5:** `PARTIALLY VERIFIED`
- **H.6:** `VERIFIED REAL`
- **H.10:** `VERIFIED REAL`
- **H.11:** `VERIFIED REAL`
- **H.14:** `VERIFIED REAL`

## Bottom line

Four of the five previous HIGH findings survive re-verification as real issues in the current code on `master`.

The one correction is `H.5`: the hardening report got the architecture problem right, but overstated how deterministic the stale-warning failure is. The real bug is a risky boundary condition between throttling and stale detection, not a guaranteed false positive from the static configuration alone.
