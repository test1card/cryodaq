# CryoDAQ Driver / Transport Fault Injection Deep Dive

Date: 2026-04-09  
Branch audited: `master`  
Scope: `src/cryodaq/drivers/base.py`, `src/cryodaq/drivers/transport/{gpib,usbtmc,serial}.py`, `src/cryodaq/drivers/instruments/{lakeshore_218s,keithley_2604b,thyracont_vsp63d}.py`

## Scope notes

- `src/cryodaq/drivers/transport/base.py` does not exist in this tree. I verified `src/cryodaq/drivers/transport/` contains only `__init__.py`, `gpib.py`, `serial.py`, `usbtmc.py`.
- I read all listed driver and transport files completely.
- Two downstream questions from the prompt require narrow scheduler/storage traces:
  - "what does scheduler do after timeout / transport error?"
  - "does sqlite_writer drop `+OVL` / `+inf`?"
  Those code paths are included only to answer the prompt; new findings are still limited to driver/transport/instrument behavior.

## External contracts checked

### PyVISA timeout / session behavior

Source: PyVISA resources docs  
https://pyvisa.readthedocs.io/en/latest/introduction/resources.html

> "Most VISA I/O operations may be performed with a timeout. If a timeout is set, every operation that takes longer than the timeout is aborted and an exception is raised."

> "If the resource is closed, an exception will be raised: ... `pyvisa.errors.InvalidSession`"

### VISA Clear semantics

Source: NI VISA Clear docs  
https://www.ni.com/docs/en-US/bundle/labview-api-ref/page/functions/visa-clear.html

> "Clears the input and output buffers of the device."

> "GPIB—VISA sends the Selected Device Clear command."

> "USB—VISA sends the INITIATE_CLEAR and CHECK_CLEAR_STATUS commands on the control pipe."

### pyserial-asyncio stream contract

Source: pyserial-asyncio API docs / project source docs  
https://pyserial-asyncio.readthedocs.io/en/latest/api.html  
https://github.com/pyserial/pyserial-asyncio/blob/master/documentation/api.rst

> "`open_serial_connection(... )` ... awaited returns an `asyncio.StreamReader` and a `asyncio.StreamWriter`."

This matters because CryoDAQ builds its own `query()` from raw `write()` + `read_line()` on those stream objects. The library does not add request/response serialization for concurrent coroutines.

## Shared driver contract

All instrument `read_channels()` calls are serialized only when the caller goes through `InstrumentDriver.safe_read()`.

```python
# src/cryodaq/drivers/base.py:52-87
class InstrumentDriver(ABC):
    def __init__(self, name: str, *, mock: bool = False) -> None:
        self.name = name
        self.mock = mock
        self._connected = False
        self._lock = asyncio.Lock()

    @abstractmethod
    async def read_channels(self) -> list[Reading]:
        """Опросить все каналы. Вернуть список показаний."""

    async def safe_read(self) -> list[Reading]:
        """Потокобезопасный опрос с блокировкой (один запрос за раз)."""
        async with self._lock:
            return await self.read_channels()
```

Implication:

- scheduler-driven poll cycles are serialized per driver
- control-plane methods such as `start_source()`, `stop_source()`, `emergency_off()`, `connect()`, `disconnect()` are **not** covered by that lock unless they implement their own locking

## LakeShore 218S

### Core parse / fallback path

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:150-174
async def _read_krdg_channels(self) -> list[Reading]:
    if self.mock:
        return self._mock_readings()

    if self._use_per_channel_krdg:
        return await self._read_krdg_per_channel()

    raw_response = await self._transport.query("KRDG?")
    log.debug("%s: KRDG? -> %s", self.name, raw_response)
    readings = self._parse_response(raw_response, unit="K", reading_kind="temperature")
    if len(readings) < 8:
        self._krdg0_fail_count += 1
        log.warning(
            "%s: KRDG? returned %d values (expected 8), fallback #%d",
            self.name, len(readings), self._krdg0_fail_count,
        )
        if self._krdg0_fail_count >= 3:
            self._use_per_channel_krdg = True
            log.warning(
                "%s: KRDG? failed %d times, switching to per-channel mode permanently",
                self.name, self._krdg0_fail_count,
            )
        return await self._read_krdg_per_channel()
    self._krdg0_fail_count = 0
    return readings
```

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:356-405
def _parse_response(self, response: str, *, unit: str, reading_kind: str) -> list[Reading]:
    tokens = [token.strip() for token in response.split(",")]
    readings: list[Reading] = []
    for index, token in enumerate(tokens[:8], start=1):
        channel_name = self._channel_labels.get(index, f"CH{index}")
        metadata = {
            "raw_channel": index,
            "reading_kind": reading_kind,
        }
        token_upper = token.upper().lstrip("+")
        if token_upper in {"OVL", "+OVL"}:
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=float("inf"),
                    unit=unit,
                    instrument_id=self.name,
                    status=ChannelStatus.OVERRANGE,
                    raw=None,
                    metadata=metadata,
                )
            )
            continue
        try:
            value = float(token)
        except ValueError:
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=float("nan"),
                    unit=unit,
                    instrument_id=self.name,
                    status=ChannelStatus.SENSOR_ERROR,
                    raw=None,
                    metadata=metadata,
                )
            )
            continue
        readings.append(
            Reading.now(
                channel=channel_name,
                value=value,
                unit=unit,
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=value,
                metadata=metadata,
            )
        )
    return readings
```

### 1. GPIB returns empty string

- `GPIBTransport.query("KRDG?")` returns `""`
- `_parse_response("")` splits into one token `[""]`
- the lone token raises `ValueError` in `float(token)`
- parser emits one `SENSOR_ERROR` reading with `NaN`
- `_read_krdg_channels()` sees `len(readings) < 8` and immediately falls back to per-channel `KRDG? 1..8`

Minimal code path:

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:157-172 and 379-392
raw_response = await self._transport.query("KRDG?")
readings = self._parse_response(raw_response, unit="K", reading_kind="temperature")
if len(readings) < 8:
    self._krdg0_fail_count += 1
    ...
    return await self._read_krdg_per_channel()

...
try:
    value = float(token)
except ValueError:
    readings.append(
        Reading.now(
            channel=channel_name,
            value=float("nan"),
            unit=unit,
            instrument_id=self.name,
            status=ChannelStatus.SENSOR_ERROR,
            raw=None,
            metadata=metadata,
        )
    )
```

Verdict: handled defensively. Batch mode does not trust the partial parse and retries channel-by-channel.

### 2. GPIB returns garbled / non-numeric data

- each bad token becomes a `SENSOR_ERROR` reading with `NaN`
- if all 8 tokens are present, the driver returns 8 readings and does **not** fallback
- if token count is short, fallback triggers exactly as above

Impact detail:

- garbled-but-8-field responses are treated as valid batch framing and propagated as per-channel sensor errors
- garbled framing shorter than 8 fields triggers per-channel retry

### 3. GPIB returns `+OVL`

The driver explicitly maps `OVL` / `+OVL` to `value=+inf`, `status=OVERRANGE`.

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:365-378
token_upper = token.upper().lstrip("+")
if token_upper in {"OVL", "+OVL"}:
    readings.append(
        Reading.now(
            channel=channel_name,
            value=float("inf"),
            unit=unit,
            instrument_id=self.name,
            status=ChannelStatus.OVERRANGE,
            raw=None,
            metadata=metadata,
        )
    )
    continue
```

Downstream archive behavior:

```python
# src/cryodaq/storage/sqlite_writer.py:294-324
def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
    rows = []
    skipped = 0
    for r in batch:
        if r.value is None or (isinstance(r.value, float) and not math.isfinite(r.value)):
            skipped += 1
            continue
        rows.append(...)
    if skipped:
        logger.warning(
            "Пропущено %d readings с value=None/NaN (из батча %d)", skipped, len(batch),
        )
```

Result:

- driver marks `+OVL` correctly as `OVERRANGE`
- archive layer drops that non-finite value on persistence

### 4. GPIB returns `-OVL`

There is **no symmetric branch** for `-OVL`.

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:365-393
token_upper = token.upper().lstrip("+")
if token_upper in {"OVL", "+OVL"}:
    ...
    continue
try:
    value = float(token)
except ValueError:
    readings.append(
        Reading.now(
            channel=channel_name,
            value=float("nan"),
            unit=unit,
            instrument_id=self.name,
            status=ChannelStatus.SENSOR_ERROR,
            raw=None,
            metadata=metadata,
        )
    )
    continue
```

Verdict: `-OVL` degrades to `SENSOR_ERROR`, not to a symmetric over/under-range representation. This is a real asymmetry in the parser.

### 5. GPIB returns wrong number of channels

- short batch (`7` values, `1`, etc.) increments `self._krdg0_fail_count`
- immediate fallback to per-channel mode for that poll
- after 3 such failures, driver permanently switches to per-channel mode until a periodic batch retry succeeds

Recovery path:

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:182-197
now = _time.monotonic()
if now - self._krdg_last_batch_retry >= self._krdg_batch_retry_interval_s:
    self._krdg_last_batch_retry = now
    try:
        raw = await self._transport.query("KRDG?")
        readings = self._parse_response(raw, unit="K", reading_kind="temperature")
        if len(readings) >= 8:
            log.info(
                "%s: KRDG? batch mode recovered — switching back from per-channel",
                self.name,
            )
            self._use_per_channel_krdg = False
            self._krdg0_fail_count = 0
            return readings
    except Exception:
        pass  # Stay in per-channel mode
```

Verdict: good defensive recovery. A malformed batch does not poison future reads permanently.

### 6. GPIB read times out at PyVISA level

Transport side:

```python
# src/cryodaq/drivers/transport/gpib.py:168-193 and 258-293
async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
    ...
    response: str = await loop.run_in_executor(
        self._get_executor(), self._blocking_query, cmd, timeout_ms
    )
    ...

def _blocking_query(self, cmd: str, timeout_ms: int | None = None) -> str:
    res = self._resource
    ...
    try:
        res.write(cmd)
        time.sleep(_WRITE_READ_DELAY_S)
        return res.read().strip()
    except Exception:
        try:
            res.clear()
            log.info("GPIB: auto-clear after error on %s", self._resource_str)
        ...
        raise
```

Scheduler side:

```python
# src/cryodaq/core/scheduler.py:127-152
try:
    readings = await asyncio.wait_for(
        driver.safe_read(), timeout=cfg.read_timeout_s
    )
    ...
except TimeoutError:
    state.consecutive_errors += 1
    state.total_errors += 1
    logger.warning(
        "Таймаут опроса '%s' (%.1fs), ошибок подряд: %d",
        name, cfg.read_timeout_s, state.consecutive_errors,
    )
    if state.consecutive_errors >= 3:
        ...
        await driver.disconnect()
```

What actually happens:

1. `res.read()` blocks inside the transport's single-worker executor thread.
2. If VISA timeout fires first, executor returns an exception and `_blocking_query()` tries `res.clear()` before re-raising.
3. If scheduler `wait_for()` fires first, the coroutine is cancelled, but the executor thread keeps running until the underlying PyVISA call returns.
4. Because the executor has `max_workers=1`, one wedged operation monopolizes that transport until it exits.

This is the same executor-liveness gap as previous audits, but here it is directly visible in the transport implementation.

### 7. Bus error during query (`VisaIOError` variants)

`GPIBTransport` does not special-case error subclasses. Any exception in write/read path triggers:

1. best-effort `res.clear()`
2. best-effort drain `res.read()` with a 200 ms timeout
3. re-raise to caller

```python
# src/cryodaq/drivers/transport/gpib.py:267-289
try:
    res.write(cmd)
    time.sleep(_WRITE_READ_DELAY_S)
    return res.read().strip()
except Exception:
    try:
        res.clear()
        log.info("GPIB: auto-clear after error on %s", self._resource_str)
    except Exception:
        log.warning("GPIB: auto-clear failed on %s", self._resource_str)
    try:
        saved = res.timeout
        res.timeout = 200
        try:
            res.read()
        except Exception:
            pass
        res.timeout = saved
    except Exception:
        pass
    raise
```

Verdict: the immediate device-level recovery step is sensible. The limitation is that a permanently bad session is still left to upper layers to disconnect/reconnect.

### 8. Cable physically disconnected mid-query

At driver level there is no special disconnect logic in `LakeShore218S.read_channels()`. The exception propagates out of `_transport.query(...)` and the scheduler owns reconnect/backoff behavior.

Per-channel fallback path shows the same pattern:

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:199-233
readings: list[Reading] = []
for ch in range(1, 9):
    try:
        raw = await self._transport.query(f"KRDG? {ch}")
        parsed = self._parse_response(raw, unit="K", reading_kind="temperature")
        if parsed:
            ...
    except Exception as exc:
        log.error("%s: KRDG? %d failed: %s", self.name, ch, exc)
        channel_name = self._channel_labels.get(ch, f"CH{ch}")
        readings.append(
            Reading.now(
                channel=channel_name,
                value=float("nan"),
                unit="K",
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"raw_channel": ch, "reading_kind": "temperature"},
            )
        )
return readings
```

Effect:

- batch-mode disconnect becomes an exception to scheduler
- per-channel mode degrades each failed channel to `SENSOR_ERROR` instead of failing the entire instrument read

### 9. Two LakeShores on same bus, one fails

Scheduler behavior on shared GPIB bus:

```python
# src/cryodaq/core/scheduler.py:178-183 and 241-301
async def _gpib_poll_loop(self, bus_prefix: str, states: list[_InstrumentState]) -> None:
    """Последовательный опрос всех приборов на одной GPIB шине в одном task.

    Гарантирует: ни в какой момент два run_in_executor вызова к одной GPIB
    шине не выполняются параллельно. Один сбойный прибор не блокирует остальные.
    """
    ...
    for state in states:
        ...
        try:
            readings = await asyncio.wait_for(
                driver.safe_read(), timeout=_POLL_TIMEOUT_S
            )
            await self._process_readings(state, readings)
            bus_error_count = 0  # reset on success
        except Exception as exc:
            ...
            if bus_error_count <= 2:
                ...
            elif bus_error_count <= 5:
                ...
                for s in states:
                    ...
                    s.config.driver._connected = False
                break
```

Actual behavior:

- one device failure does **not** immediately block polling of the other device
- after repeated bus-level failures, scheduler escalates to IFC and disconnects all devices on that bus
- so "one fails, other still polled" is true only at low error counts; prolonged failures become a whole-bus recovery action

### 10. `*IDN?` returns wrong identity

Connect path explicitly rejects mismatches:

```python
# src/cryodaq/drivers/instruments/lakeshore_218s.py:61-103
for attempt in range(2):  # initial + one retry after device clear
    try:
        idn_raw = (await self._transport.query("*IDN?")).strip()
    except Exception as exc:
        ...
        idn_raw = ""

    upper = idn_raw.upper()
    if idn_raw and "LSCI" in upper and "218" in upper:
        idn_valid = True
        self._instrument_id = idn_raw
        ...
        break

    if attempt == 0:
        ...
        await self._transport.clear_bus()
        await asyncio.sleep(0.2)

if not idn_valid:
    await self._transport.close()
    raise RuntimeError(
        f"{self.name}: LakeShore 218S IDN validation failed. "
        f"Expected 'LSCI,MODEL218...', got {idn_raw!r}. "
        f"Check GPIB address and cabling."
    )
```

Verdict: verified. Wrong instrument identity is rejected after one clear-and-retry cycle.

## Keithley 2604B

### Core runtime paths

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:214-250
async def start_source(
    self,
    channel: str,
    p_target: float,
    v_compliance: float,
    i_compliance: float,
) -> None:
    smu_channel = normalize_smu_channel(channel)
    runtime = self._channels[smu_channel]

    if not self._connected:
        raise RuntimeError(f"{self.name}: instrument not connected")
    if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
        raise ValueError("P/V/I must be > 0")
    if runtime.active:
        raise RuntimeError(f"Channel {smu_channel} already active")

    runtime.p_target = p_target
    runtime.v_comp = v_compliance
    runtime.i_comp = i_compliance

    if self.mock:
        runtime.active = True
        return

    await self._transport.write(f"{smu_channel}.reset()")
    await self._transport.write(f"{smu_channel}.source.func = {smu_channel}.OUTPUT_DCVOLTS")
    await self._transport.write(f"{smu_channel}.source.autorangev = {smu_channel}.AUTORANGE_ON")
    await self._transport.write(f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON")
    await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
    await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
    await self._transport.write(f"{smu_channel}.source.levelv = 0")
    await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
    self._last_v[smu_channel] = 0.0
    self._compliance_count[smu_channel] = 0
    runtime.active = True
```

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:124-212
async def read_channels(self) -> list[Reading]:
    if not self._connected:
        raise RuntimeError(f"{self.name}: instrument not connected")

    if self.mock:
        return self._mock_readings()

    readings: list[Reading] = []
    for smu_channel in SMU_CHANNELS:
        runtime = self._channels[smu_channel]
        try:
            if not runtime.active:
                output_raw = await self._transport.query(
                    f"print({smu_channel}.source.output)", timeout_ms=3000
                )
                try:
                    output_on = float(output_raw.strip()) > 0.5
                except ValueError:
                    output_on = False
                ...
            raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
            current, voltage = self._parse_iv_response(raw, smu_channel)
            ...
        except OSError as exc:
            log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
            self._connected = False
            raise
        except Exception as exc:
            log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
            readings.extend(self._error_readings_for_channel(smu_channel))
    return readings
```

### 1. TSP write succeeds but readback fails

The driver has no transaction or rollback around multi-step source configuration. If an early write succeeds and a later query or write fails, instrument state can already be mutated.

Example:

- `start_source()` may complete `reset`, `source.func`, compliance limit writes
- later `output = OUTPUT_ON` or future `measure.iv()` readback may fail
- no compensating `OUTPUT_OFF` is issued automatically in `start_source()`

Verdict: partial hardware state is possible. The runtime struct is also pre-populated before the transport sequence starts.

### 2. TSP returns non-numeric value

IV parser is strict:

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:367-371
def _parse_iv_response(self, raw: str, channel: SmuChannel) -> tuple[float, float]:
    parts = raw.strip().split("\t")
    if len(parts) != 2:
        raise ValueError(f"{channel}: expected 2 values, got {raw!r}")
    return float(parts[0]), float(parts[1])
```

Read path handling:

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:203-212 and 498-510
except OSError as exc:
    ...
    self._connected = False
    raise
except Exception as exc:
    log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
    readings.extend(self._error_readings_for_channel(smu_channel))

...
def _error_readings_for_channel(self, channel: SmuChannel) -> list[Reading]:
    return [
        Reading.now(
            channel=f"{self.name}/{channel}/{field}",
            value=float("nan"),
            unit=unit,
            instrument_id=self.name,
            status=ChannelStatus.SENSOR_ERROR,
            raw=None,
            metadata=metadata,
        )
        for field, unit in _IV_FIELDS
    ]
```

Verdict: non-numeric TSP output degrades to four `SENSOR_ERROR` readings for that channel, but does **not** mark the instrument disconnected.

### 3. `emergency_off()` called while disconnected

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:287-318
async def emergency_off(self, channel: str | None = None) -> None:
    channels = [normalize_smu_channel(channel)] if channel is not None else list(SMU_CHANNELS)
    for smu_channel in channels:
        runtime = self._channels[smu_channel]
        runtime.active = False
        runtime.p_target = 0.0
        self._last_v[smu_channel] = 0.0
        self._compliance_count[smu_channel] = 0

    if self.mock or not self._connected:
        return

    for smu_channel in channels:
        try:
            await self._transport.write(f"{smu_channel}.source.levelv = 0")
            await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
        except Exception as exc:
            log.critical("%s: emergency_off failed on %s: %s", self.name, smu_channel, exc)
        ...
```

Actual result:

- software runtime is reset first
- if `_connected` is already `False`, the method exits without any hardware I/O attempt

This is intentional in code, but it means the logical "off" state can diverge from the physical instrument if connectivity status is wrong or stale.

### 4. `smua` succeeds, `smub` fails during dual-channel start

Channels are controlled independently. There is no "all channels or none" orchestration in the driver itself.

Relevant state model:

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:66-75
self._channels: dict[SmuChannel, ChannelRuntime] = {
    "smua": ChannelRuntime(channel="smua"),
    "smub": ChannelRuntime(channel="smub"),
}
self._last_v: dict[SmuChannel, float] = {"smua": 0.0, "smub": 0.0}
self._compliance_count: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
```

Because `start_source()` acts on exactly one normalized channel, a failure on `smub` does not roll back `smua`, and vice versa.

Verdict: dual-channel start is not atomic across channels.

### 5. TSP script lockup / hung instrument

Transport query path:

```python
# src/cryodaq/drivers/transport/usbtmc.py:169-205 and 225-228
async def query(self, cmd: str, timeout_ms: int = 5000) -> str:
    ...
    async with self._lock:
        loop = asyncio.get_running_loop()
        try:
            response: str = await loop.run_in_executor(
                self._get_executor(), self._blocking_query, cmd, timeout_ms
            )
            ...
            return response
        except Exception as exc:
            log.error(
                "USBTMC: ошибка запроса '%s' к %s — %s",
                cmd,
                self._resource_str,
                exc,
            )
            raise

def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
    self._resource.timeout = timeout_ms
    return self._resource.query(cmd).strip()
```

What happens:

- the driver detects the lockup only when query/write returns or times out
- there is no USBTMC-side `clear()`/abort step after timeout
- because `_executor` is single-worker and `close()` uses `shutdown(wait=True)`, a truly stuck lower-level call can pin that transport indefinitely

### 6. VISA session timeout during long-running command

Same transport path as above. If the backend obeys VISA timeout, `_resource.query()` raises and the exception bubbles to caller. There is no automatic reconnect or session reset inside `USBTMCTransport`.

Driver consequences:

- in `read_channels()`, non-`OSError` timeouts become per-channel error readings
- in `start_source()` / `stop_source()` / `emergency_off()`, the exception propagates to caller unless explicitly caught

### 7. Partial command write

There is no post-write verification in `start_source()`. The code assumes each `write()` is all-or-nothing.

```python
# src/cryodaq/drivers/transport/usbtmc.py:110-135
async def write(self, cmd: str) -> None:
    ...
    async with self._lock:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._get_executor(), self._resource.write, cmd)
            log.debug("USBTMC write → %s: %s", self._resource_str, cmd)
        except Exception as exc:
            log.error(
                "USBTMC: ошибка записи команды '%s' в %s — %s",
                cmd,
                self._resource_str,
                exc,
            )
            raise
```

Verdict: if the bus or backend acknowledges a write that the instrument only partially acted on, the driver has no readback fence except in a few safety-specific paths like `_verify_output_off()`.

### 8. Two simultaneous `start_source()` calls

There is **no driver-level lock** around `start_source()`. The only serialization is inside each individual `USBTMCTransport.write()` call.

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:221-233
smu_channel = normalize_smu_channel(channel)
runtime = self._channels[smu_channel]

if not self._connected:
    raise RuntimeError(f"{self.name}: instrument not connected")
if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
    raise ValueError("P/V/I must be > 0")
if runtime.active:
    raise RuntimeError(f"Channel {smu_channel} already active")

runtime.p_target = p_target
runtime.v_comp = v_compliance
runtime.i_comp = i_compliance
```

```python
# src/cryodaq/drivers/transport/usbtmc.py:123-135
async with self._lock:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(self._get_executor(), self._resource.write, cmd)
        ...
```

Actual race:

- two coroutines can both pass `if runtime.active` before either reaches the final `runtime.active = True`
- transport lock will serialize individual writes, but the two multi-step sequences can still interleave at command granularity

Verdict: real race.

### 9. Power cycle of instrument while connected

Read path disconnect logic is narrow:

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:203-212
except OSError as exc:
    log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
    self._connected = False
    raise
except Exception as exc:
    log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
    readings.extend(self._error_readings_for_channel(smu_channel))
```

If the power-cycle manifests as `OSError`, driver marks disconnected and scheduler reconnects. If it manifests as another PyVISA exception class, the driver stays logically connected and only emits `SENSOR_ERROR` readings.

Verdict: recovery quality depends on backend exception type, not solely on physical failure.

### 10. Heartbeat timeout trigger

Within this file there is **no heartbeat state machine**. The driver exposes reads, diagnostics, compliance persistence, and emergency-off paths, but no heartbeat deadline.

Relevant exported surface:

```python
# src/cryodaq/drivers/instruments/keithley_2604b.py:320-354
async def check_error(self) -> str | None:
    ...

@property
def any_active(self) -> bool:
    return any(runtime.active for runtime in self._channels.values())

@property
def active_channels(self) -> list[str]:
    return [channel for channel, runtime in self._channels.items() if runtime.active]

def compliance_persistent(self, channel: SmuChannel) -> bool:
    return self._compliance_count.get(channel, 0) >= _COMPLIANCE_NOTIFY_THRESHOLD

async def diagnostics(self) -> dict[str, Any]:
    ...
```

Answer to the prompt's question: heartbeat timeout is not detected in the driver layer. It must be enforced by `SafetyManager` / engine code above this module.

## Thyracont VSP63D

### Core protocol-detection and parse paths

```python
# src/cryodaq/drivers/instruments/thyracont_vsp63d.py:104-150
baudrates_to_try = [self._baudrate]
fallback = _FALLBACK_BAUDRATES.get(self._baudrate)
if fallback is not None:
    baudrates_to_try.append(fallback)

last_error = ""
for baud in baudrates_to_try:
    ...
    await self._transport.open(self._resource_str, baudrate=baud)
    ...
    if await self._try_v1_probe():
        self._protocol_v1 = True
        ...
        return

    if await self._try_mv00_probe():
        self._protocol_v1 = False
        ...
        return

    await self._transport.close()
    last_error = f"neither V1 nor MV00 responded @ {baud} baud"

raise RuntimeError(f"{self.name}: {last_error}")
```

```python
# src/cryodaq/drivers/instruments/thyracont_vsp63d.py:241-287
response_stripped = response.strip()
channel = f"{self.name}/pressure"

try:
    parts = response_stripped.split(",", 1)
    if len(parts) != 2:
        raise ValueError(f"Неверный формат ответа: '{response_stripped}'")

    status_code = int(parts[0].strip())
    value = float(parts[1].strip())
except (ValueError, IndexError) as exc:
    ...
    return Reading.now(... status=ChannelStatus.SENSOR_ERROR, raw=None, ...)

ch_status = _STATUS_MAP.get(status_code, ChannelStatus.SENSOR_ERROR)
...
return Reading.now(
    channel=channel,
    value=value,
    unit="mbar",
    instrument_id=self.name,
    status=ch_status,
    raw=value,
    metadata={"status_code": status_code},
)
```

```python
# src/cryodaq/drivers/instruments/thyracont_vsp63d.py:338-396
if self._validate_checksum and len(response_stripped) >= 2:
    if not self._verify_v1_checksum(response_stripped):
        ...
        return Reading.now(... status=ChannelStatus.SENSOR_ERROR, raw=None, ...)

try:
    if not response_stripped.startswith(self._address):
        raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")
    payload = response_stripped[len(self._address) + 1:]
    if len(payload) < 6:
        raise ValueError(f"Слишком короткий payload: '{payload}'")
    value_str = payload[:6]
    mantissa = int(value_str[:4])
    exponent = int(value_str[4:6])
    pressure_mbar = (mantissa / 1000.0) * (10.0 ** (exponent - 20))
except (ValueError, IndexError) as exc:
    ...
    return Reading.now(... status=ChannelStatus.SENSOR_ERROR, raw=None, ...)

return Reading.now(
    channel=channel,
    value=pressure_mbar,
    unit="mbar",
    instrument_id=self.name,
    status=ChannelStatus.OK,
    raw=pressure_mbar,
    metadata={"raw_response": response_stripped, "protocol": "v1"},
)
```

### 1. Checksum mismatch

Verified: default is `validate_checksum=True`, and V1 checksum mismatch returns `SENSOR_ERROR` instead of a numeric value.

```python
# src/cryodaq/drivers/instruments/thyracont_vsp63d.py:76-81 and 338-353
validate_checksum: bool = True,
...
if self._validate_checksum and len(response_stripped) >= 2:
    if not self._verify_v1_checksum(response_stripped):
        log.warning(
            "%s: V1 checksum mismatch in '%s' — possible RS-232 corruption",
            self.name, response_stripped,
        )
        return Reading.now(
            channel=channel,
            value=float("nan"),
            unit="mbar",
            instrument_id=self.name,
            status=ChannelStatus.SENSOR_ERROR,
            raw=None,
            metadata={"raw_response": response_stripped, "error": "checksum_mismatch"},
        )
```

### 2. Unknown response prefix

Probe selection is very literal:

- V1 succeeds only if `resp.strip().startswith(expected_prefix)`
- MV00 succeeds only if response contains `","`
- if neither matches, connect closes port and eventually raises

Verdict: unknown prefixes are rejected during connect. There is no "best effort parse anyway" path.

### 3. Truncated response

- MV00 truncated frame without comma or without parseable float becomes `SENSOR_ERROR`
- V1 payload shorter than 6 digits becomes `SENSOR_ERROR`

This is a clean failure mode, not silent acceptance.

### 4. Extra bytes after valid response

MV00 parser does `float(parts[1].strip())`. That accepts trailing whitespace but rejects extra junk.

V1 parser uses checksum validation first; extra bytes usually break checksum and become `SENSOR_ERROR`. If checksum validation is disabled and extra bytes come after the first 6 digits + checksum, the parser still ignores everything after `payload[:6]`.

Verdict: with default checksum validation on, extra bytes are usually rejected.

### 5. Pressure value exactly zero

Zero is accepted without special handling.

```python
# src/cryodaq/drivers/instruments/thyracont_vsp63d.py:249-287
status_code = int(parts[0].strip())
value = float(parts[1].strip())
...
return Reading.now(
    channel=channel,
    value=value,
    unit="mbar",
    instrument_id=self.name,
    status=ch_status,
    raw=value,
    metadata={"status_code": status_code},
)
```

Verdict: `0.0` survives unchanged. Whether that is physically meaningful depends on instrument protocol, but code does not reject it.

### 6. Pressure value `"inf"` or scientific-notation edge cases

`float(parts[1].strip())` accepts both scientific notation and `"inf"`.

Actual consequence:

- `"1.2E-7"` parses normally
- `"inf"` parses to positive infinity
- if status code is `0`, the driver returns `status=OK`, `value=inf`, `raw=inf`

There is no finite-value check in this driver.

### 7. CH340 USB-Serial adapter drops bytes

At this layer, dropped bytes map to either:

- truncated frame -> parse failure / timeout
- checksum mismatch for V1 -> `SENSOR_ERROR`

There is no driver-side byte-level reassembly beyond `readuntil("\r")`.

Relevant transport contract:

```python
# src/cryodaq/drivers/transport/serial.py:162-167
effective_timeout = timeout if timeout is not None else self._read_timeout_s
data = await asyncio.wait_for(
    self._reader.readuntil(terminator.encode()),
    timeout=effective_timeout,
)
return data.decode(errors="replace")
```

Verdict: corruption is detected if it changes framing or checksum. There is no retransmit or low-level recovery.

### 8. Cable disconnected mid-frame

There is no per-driver catch in `read_channels()`. Any exception from `SerialTransport.query()` propagates to caller.

Transport query is composed, not atomic:

```python
# src/cryodaq/drivers/transport/serial.py:91-112
async def query(self, command: str, *, terminator: str = "\r") -> str:
    if self.mock:
        ...
    await self.write(command, terminator=terminator)
    return await self.read_line(terminator=terminator)
```

If disconnect happens:

- during `write()` -> `drain()` raises
- during `read_line()` -> `wait_for(readuntil(...))` raises

The driver does not convert that to `SENSOR_ERROR`; it bubbles out.

### 9. Baud rate mismatch

Verified: connect tries the configured baudrate, then the known fallback pair `9600 <-> 115200`.

If both fail, connect closes transport and raises.

This is robust for the two known device families, but nothing wider than that pair.

### 10. Two writes overlap

`SerialTransport` has no lock.

```python
# src/cryodaq/drivers/transport/serial.py:31-37 and 114-134
def __init__(self, *, mock: bool = False) -> None:
    self.mock = mock
    self._reader = None
    self._writer = None
    self._resource_str: str = ""
    self._read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S

async def write(self, data: str, *, terminator: str = "\r") -> None:
    ...
    payload = (data + terminator).encode()
    self._writer.write(payload)
    await self._writer.drain()
```

```python
# src/cryodaq/drivers/transport/serial.py:91-112
async def query(self, command: str, *, terminator: str = "\r") -> str:
    ...
    await self.write(command, terminator=terminator)
    return await self.read_line(terminator=terminator)
```

Because two coroutines can both execute `write()`/`query()` concurrently on the same `StreamWriter`, byte streams and responses can interleave. Unlike `USBTMCTransport`, there is no `asyncio.Lock` here.

Verdict: real serialization gap at transport level.

## Transport executor lifetime

## GPIBTransport

### Creation

```python
# src/cryodaq/drivers/transport/gpib.py:100-108
def _get_executor(self) -> ThreadPoolExecutor:
    """Lazily create the per-transport executor on first use."""
    if self._executor is None:
        label = self._resource_str or self._bus_prefix or "gpib"
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"visa_gpib_{label}",
        )
    return self._executor
```

- created lazily on first `open()`, `write()`, `query()`, `clear_bus()`, or `send_ifc()`
- one worker per transport

### Destruction

```python
# src/cryodaq/drivers/transport/gpib.py:132-150
async def close(self) -> None:
    ...
    if self._resource is not None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._get_executor(), self._resource.close)
        ...
        self._resource = None
    if self._executor is not None:
        self._executor.shutdown(wait=True)
        self._executor = None
```

- resource close is queued onto the same single-worker executor
- `shutdown(wait=True)` waits for running and queued work to finish

### If a task is queued after destroy

- `_get_executor()` creates a new executor
- but `self._resource` may already be `None`
- `query()` explicitly checks and raises `RuntimeError("GPIB resource not connected")`
- `write()` is worse: `self._resource.write` is dereferenced before scheduling and will raise `AttributeError` immediately if resource is `None`

### If destroy is called while task is running

- close waits for the in-flight worker operation to finish, then queues `resource.close`, then `shutdown(wait=True)` waits again
- this means close cannot preempt a hung PyVISA call

### Rapid disconnect/reconnect cycles

- executor threads do not accumulate because `close()` resets `_executor = None`
- however `GPIBTransport` has no async lock around `open()/close()/write()/query()`, so rapid control-plane races are not internally serialized

## USBTMCTransport

### Creation

```python
# src/cryodaq/drivers/transport/usbtmc.py:44-52
def _get_executor(self) -> ThreadPoolExecutor:
    """Lazily create the per-transport executor on first use."""
    if self._executor is None:
        label = self._resource_str or "usbtmc"
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"visa_usbtmc_{label}",
        )
    return self._executor
```

### Destruction

```python
# src/cryodaq/drivers/transport/usbtmc.py:82-108
async def close(self) -> None:
    async with self._lock:
        ...
        try:
            await loop.run_in_executor(self._get_executor(), self._blocking_close)
            ...
        finally:
            self._resource = None
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
```

- unlike GPIB, `close()` is protected by `_lock`
- same limitation: `shutdown(wait=True)` cannot abort hung I/O

### If task is queued after destroy

- executor is recreated on next use
- if `_resource` is still `None`, `write()` will fail on `self._resource.write` attribute access and `query()` will fail inside `_blocking_query` on `self._resource.timeout`

### Rapid disconnect/reconnect cycles

- control-plane operations are serialized by `_lock`
- thread accumulation is prevented
- but a single wedged PyVISA call still blocks the whole transport because the executor has one worker and close waits for completion

## SerialTransport

There is no executor. Lifetime is the lifecycle of `StreamReader` / `StreamWriter`.

```python
# src/cryodaq/drivers/transport/serial.py:61-89
import serial_asyncio  # type: ignore[import]

self._reader, self._writer = await serial_asyncio.open_serial_connection(
    url=port, baudrate=baudrate
)
...
self._writer.close()
await self._writer.wait_closed()
...
self._reader = None
self._writer = None
```

Main issue here is not executor lifetime but missing serialization around concurrent read/write/query users.

## Findings

### [HIGH] LakeShore parser handles `+OVL` but not `-OVL`

Location: `src/cryodaq/drivers/instruments/lakeshore_218s.py:365-393`

- `OVL` / `+OVL` become `OVERRANGE`
- `-OVL` falls through to `ValueError` and is emitted as `SENSOR_ERROR`

Why it matters:

- over/under-range semantics become asymmetric purely because of string spelling
- downstream safety logic and operator UI will see "sensor error" instead of a directional out-of-range condition

### [HIGH] GPIB timeout/cable-fault path is not cancellable at transport level

Location: `src/cryodaq/drivers/transport/gpib.py:189-193`, `src/cryodaq/drivers/transport/gpib.py:267-289`

- once `res.read()` is inside the executor thread, outer coroutine cancellation does not stop it
- the single-worker executor stays occupied until VISA returns

Why it matters:

- the transport cannot be forcefully drained by `close()`
- repeated timeouts can leave a whole GPIB device path effectively wedged until the backend call exits

### [HIGH] Keithley `start_source()` is non-atomic and has no rollback

Location: `src/cryodaq/drivers/instruments/keithley_2604b.py:231-250`

- runtime state is populated before hardware writes start
- multiple writes can succeed before a later write fails
- no compensating `OUTPUT_OFF` or reset is attempted

Why it matters:

- instrument state can be partially reconfigured while software still treats startup as failed
- this is exactly the class of fault that leaves a power source in an ambiguous state after a bus glitch

### [HIGH] Keithley has a real multi-call race on `start_source()`

Location: `src/cryodaq/drivers/instruments/keithley_2604b.py:221-250`, `src/cryodaq/drivers/transport/usbtmc.py:123-135`

- `runtime.active` is only checked once, before the multi-step write sequence
- per-command USBTMC locking serializes individual writes but does not make the whole start sequence atomic

Why it matters:

- two callers can both pass the inactive check and interleave configuration
- the resulting source state depends on command ordering, not on explicit arbitration

### [MEDIUM] Keithley disconnect detection depends on exception class

Location: `src/cryodaq/drivers/instruments/keithley_2604b.py:203-212`

- only `OSError` flips `_connected=False`
- other transport/backend exceptions degrade to channel error readings and keep driver logically connected

### [MEDIUM] `emergency_off()` on a logically disconnected Keithley does not attempt hardware I/O

Location: `src/cryodaq/drivers/instruments/keithley_2604b.py:287-318`

- software runtime resets first
- `if self.mock or not self._connected: return`

### [HIGH] Serial transport has no request/response serialization

Location: `src/cryodaq/drivers/transport/serial.py:91-167`

- `query()` is plain `write()` + `read_line()`
- there is no `asyncio.Lock`

Why it matters:

- overlapping coroutines can interleave command bytes and steal each other's responses
- Thyracont protocol correctness implicitly depends on single-caller discipline outside the transport

### [MEDIUM] Thyracont MV00 parser accepts `inf` as status `OK`

Location: `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:244-287`

- `float(parts[1].strip())` accepts infinity
- there is no finite-value validation before returning `ChannelStatus.OK`

### [LOW] GPIB and USBTMC post-close behavior raises generic attribute errors on some APIs

Locations:

- `src/cryodaq/drivers/transport/gpib.py:164-166`
- `src/cryodaq/drivers/transport/usbtmc.py:123-135`

- `write()` dereferences `self._resource.write` before any explicit connected-state guard
- after close that becomes `AttributeError`, not a domain-specific "not connected" error

## Recovery gaps

- LakeShore batch parsing is generally defensive, but negative overrange is misclassified.
- GPIB recovery does attempt `SDC` and buffer drain, but cannot interrupt an executor thread already blocked in VISA.
- Keithley startup and stop paths are safety-conscious in intent, but control operations are still not transactional.
- Thyracont parser is robust against truncation/corruption, but the serial transport beneath it assumes only one in-flight caller.

## Summary table

| Layer | Scenarios analyzed |
|---|---:|
| LakeShore 218S | 10 |
| Keithley 2604B | 10 |
| Thyracont VSP63D | 10 |
| Transport executor lifetime | 3 transports |

## Severity count

- HIGH: 5
- MEDIUM: 3
- LOW: 1

