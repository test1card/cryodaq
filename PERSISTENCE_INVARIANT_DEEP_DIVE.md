# Persistence-First Invariant Deep Dive

**Date:** 2026-04-09  
**Working tree:** `master`  
**Primary files read completely:**

- `src/cryodaq/core/scheduler.py` (`483` lines)
- `src/cryodaq/storage/sqlite_writer.py` (`728` lines)
- `src/cryodaq/core/broker.py` (`120` lines)
- `src/cryodaq/core/safety_broker.py` (`126` lines)

**Supplementary targeted reads used only to answer the requested trace questions:**

- `src/cryodaq/drivers/base.py` for the `safe_read() -> read_channels()` call chain
- `src/cryodaq/core/housekeeping.py` for `adaptive_throttle.filter_for_archive(...)`
- selected `subscribe(...)` call sites to enumerate `DataBroker` / `SafetyBroker` consumers
- `src/cryodaq/core/safety_manager.py` only to answer what ordering its consumer side actually assumes

## Executive summary

The core invariant is **implemented in the intended direction**:

1. Scheduler reads from the driver.
2. Scheduler writes `persisted_readings` through `SQLiteWriter.write_immediate()`.
3. Only after that `await` returns does it publish to `DataBroker`.
4. Only after `DataBroker.publish_batch(...)` returns does it publish to `SafetyBroker`.

That means the narrow statement “publish never happens before persist” is true on the ordinary path.

But the exhaustive trace shows four important edge behaviors around that invariant:

1. **[HIGH] Shutdown cancellation can leave the last batch committed in SQLite but never delivered to either broker.**
2. **[MEDIUM] Any exception escaping `DataBroker.publish_batch(...)` prevents `SafetyBroker.publish_batch(...)`, so a DataBroker-side failure can block SafetyManager delivery after persistence has already succeeded.**
3. **[MEDIUM] `SQLiteWriter._write_batch()` splits one logical scheduler batch into separate per-day transactions, so a midnight-spanning batch can be partially committed before scheduler aborts downstream publish.**
4. **[LOW] `SafetyBroker.publish()` returns early on the first full subscriber queue, so with multiple safety subscribers it can produce partial fan-out within one reading.**

The invariant is therefore one-way and strong in the intended direction, but it is **not** a full end-to-end atomicity guarantee between SQLite and the two broker trees.

## Findings

### P1 [HIGH] `Scheduler.stop()` can cancel an in-flight batch after SQLite commit but before broker delivery

```python
# src/cryodaq/core/scheduler.py:338-377, 446-470
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
...
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
...
async def stop(self) -> None:
    self._running = False
    ...
    for task in all_tasks:
        task.cancel()
    await asyncio.gather(*all_tasks, return_exceptions=True)
```

```python
# src/cryodaq/storage/sqlite_writer.py:525-540, 604-623
async def write_immediate(self, readings: list[Reading]) -> None:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(self._executor, self._write_batch, readings)
    except Exception:
        logger.critical(
            "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
            len(readings),
        )
        raise
...
async def stop(self) -> None:
    self._running = False
    ...
    if self._executor is not None:
        self._executor.shutdown(wait=True)
```

`write_immediate()` waits on a thread-pool future. Cancellation of the scheduler task does not stop the executor thread’s SQLite work, but it does stop the coroutine from continuing to broker publish. So the last batch can reach disk and never reach either broker tree.

### P2 [MEDIUM] `DataBroker.publish_batch()` is not isolated from `SafetyBroker.publish_batch()`

```python
# src/cryodaq/core/scheduler.py:373-377
# Step 2: Publish to brokers
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

```python
# src/cryodaq/core/broker.py:85-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    for sub in tuple(self._subscribers.values()):
        if sub.filter_fn and not sub.filter_fn(reading):
            continue
        if sub.queue.full():
            ...
        try:
            sub.queue.put_nowait(reading)
        except asyncio.QueueFull:
            sub.dropped += 1

async def publish_batch(self, readings: list[Reading]) -> None:
    for reading in readings:
        await self.publish(reading)
```

If `DataBroker.publish_batch(...)` raises, scheduler never reaches `SafetyBroker.publish_batch(...)`. `DataBroker.publish()` itself does not guard `filter_fn`, so any subscriber filter exception escapes through the scheduler and blocks safety delivery after persistence already succeeded.

### P3 [MEDIUM] One scheduler batch is not one SQLite transaction across day boundaries

```python
# src/cryodaq/storage/sqlite_writer.py:274-324
def _write_batch(self, batch: list[Reading]) -> None:
    if not batch:
        return
    by_day: dict[date, list[Reading]] = {}
    for r in batch:
        day = r.timestamp.date()
        by_day.setdefault(day, []).append(r)
    for day, day_readings in sorted(by_day.items()):
        conn = self._ensure_connection(day)
        self._write_day_batch(conn, day_readings)

def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
    ...
    conn.executemany(...)
    conn.commit()
```

One logical `persisted_readings` batch is split into separate per-day commits. If day 1 commits and day 2 then raises, scheduler sees the write as failed and publishes nothing, but part of the batch is already durable.

### P4 [LOW] `SafetyBroker` overflow semantics are all-or-stop, not all-or-none

```python
# src/cryodaq/core/safety_broker.py:77-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    self._last_update[reading.channel] = time.monotonic()

    for sub in self._subscribers.values():
        if sub.queue.full():
            logger.critical(...)
            if self._overflow_callback:
                try:
                    result = self._overflow_callback()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Ошибка в overflow_callback")
            return  # Не пытаемся положить в полную очередь

        try:
            sub.queue.put_nowait(reading)
        except asyncio.QueueFull:
            pass
```

With the current wiring there is one safety subscriber, so this does not create a current partial-view bug. But the code does not enforce “one subscriber only”; if more are added later, one already-full queue ends distribution for the rest of that reading.

## Analysis 1: Exhaustive trace from `driver.read_channels()` to final consumers

## A. Standalone instrument path

### Step A1. Driver call

```python
# src/cryodaq/drivers/base.py:80-87
@abstractmethod
async def read_channels(self) -> list[Reading]:
    """Опросить все каналы. Вернуть список показаний."""

async def safe_read(self) -> list[Reading]:
    """Потокобезопасный опрос с блокировкой (один запрос за раз)."""
    async with self._lock:
        return await self.read_channels()
```

```python
# src/cryodaq/core/scheduler.py:107-133
async def _poll_loop(self, state: _InstrumentState) -> None:
    cfg = state.config
    driver = cfg.driver
    name = driver.name
    ...
    while self._running:
        if not driver.connected:
            try:
                await driver.connect()
                ...
            except Exception:
                logger.exception("Не удалось подключить '%s'", name)
                await self._backoff(state)
                continue

        try:
            readings = await asyncio.wait_for(
                driver.safe_read(), timeout=cfg.read_timeout_s
            )
            ...
            await self._process_readings(state, readings)
```

**Trace result:** standalone polling goes through `driver.safe_read()`, which serializes the real `read_channels()` behind the driver’s own lock, then hands the list to `_process_readings(...)`.

### Step A2. Result handling and split into persisted/full streams

```python
# src/cryodaq/core/scheduler.py:311-337
async def _process_readings(
    self, state: _InstrumentState, readings: list[Any]
) -> None:
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
```

```python
# src/cryodaq/core/housekeeping.py:251-307
def filter_for_archive(self, readings: list[Reading]) -> list[Reading]:
    if not self.enabled:
        return list(readings)
    filtered: list[Reading] = []
    for reading in readings:
        if self._should_emit(reading):
            filtered.append(reading)
        else:
            self._suppressed_count += 1
    return filtered

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
    ...
    if since_emit >= self._max_interval_s:
        ...
        return True
    return False
```

**Trace result:** scheduler immediately forks the batch into:

- `persisted_readings`: possibly throttled archive/publish stream
- `readings`: original full stream for safety-side publication and calibration side branch

### Step A3. SQLite write

```python
# src/cryodaq/core/scheduler.py:338-355
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
# src/cryodaq/storage/sqlite_writer.py:274-324
def _write_batch(self, batch: list[Reading]) -> None:
    if not batch:
        return
    by_day: dict[date, list[Reading]] = {}
    for r in batch:
        day = r.timestamp.date()
        by_day.setdefault(day, []).append(r)
    for day, day_readings in sorted(by_day.items()):
        conn = self._ensure_connection(day)
        self._write_day_batch(conn, day_readings)

def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
    ...
    conn.executemany(...)
    conn.commit()
```

**Does it block?** Yes, from scheduler’s point of view this is a blocking await until the single-thread executor finishes `_write_batch(...)`.  
**If it raises?** `_process_readings()` logs and returns before any broker publish.

### Step A4. Calibration side branch

```python
# src/cryodaq/core/scheduler.py:357-371
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
```

**Trace result:** calibration is an after-persist, before-publish side branch. Failure here does **not** stop either broker path.

### Step A5. `DataBroker` publish

```python
# src/cryodaq/core/scheduler.py:373-377
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

```python
# src/cryodaq/core/broker.py:85-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    for sub in tuple(self._subscribers.values()):
        if sub.filter_fn and not sub.filter_fn(reading):
            continue
        if sub.queue.full():
            if sub.policy == OverflowPolicy.DROP_OLDEST:
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                sub.dropped += 1
            elif sub.policy == OverflowPolicy.DROP_NEWEST:
                sub.dropped += 1
                continue
        try:
            sub.queue.put_nowait(reading)
        except asyncio.QueueFull:
            sub.dropped += 1

async def publish_batch(self, readings: list[Reading]) -> None:
    for reading in readings:
        await self.publish(reading)
```

**Does it block?** Not on I/O. It is `async`, but normal path is `put_nowait(...)` into subscriber queues.  
**If it raises?** Only if a subscriber `filter_fn` raises or some unexpected subscriber object misbehaves. There is no guard in scheduler; if it raises, SafetyBroker publication never happens.

### Step A6. `SafetyBroker` publish

```python
# src/cryodaq/core/scheduler.py:375-377
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

```python
# src/cryodaq/core/safety_broker.py:77-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    self._last_update[reading.channel] = time.monotonic()

    for sub in self._subscribers.values():
        if sub.queue.full():
            logger.critical(...)
            if self._overflow_callback:
                try:
                    result = self._overflow_callback()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Ошибка в overflow_callback")
            return

        try:
            sub.queue.put_nowait(reading)
        except asyncio.QueueFull:
            pass

async def publish_batch(self, readings: list[Reading]) -> None:
    for reading in readings:
        await self.publish(reading)
```

**Does it block?** Normally no, except if overflow callback returns a coroutine.  
**If it raises?** In current code the method itself does not re-raise on queue-full; it logs, runs callback, and returns.

## B. GPIB grouped path

The GPIB path differs only in how the batch is acquired and error-recovered. Once a `readings` list exists, it re-enters the same `_process_readings(...)` function and therefore the same invariant path.

### Step B1. Driver call in grouped bus loop

```python
# src/cryodaq/core/scheduler.py:178-246
async def _gpib_poll_loop(self, bus_prefix: str, states: list[_InstrumentState]) -> None:
    ...
    while self._running:
        now = loop.time()

        for state in states:
            driver = state.config.driver
            name = driver.name
            ...
            try:
                readings = await asyncio.wait_for(
                    driver.safe_read(), timeout=_POLL_TIMEOUT_S
                )
                await self._process_readings(state, readings)
                bus_error_count = 0  # reset on success
            except Exception as exc:
                state.consecutive_errors += 1
                state.total_errors += 1
                bus_error_count += 1
                logger.warning(
                    "Ошибка опроса '%s': %s (device: %d, bus: %d)",
                    name, exc, state.consecutive_errors, bus_error_count,
                )
```

### Step B2. GPIB-specific recovery side effects before retry

```python
# src/cryodaq/core/scheduler.py:257-303
transport = getattr(driver, '_transport', None)

if bus_error_count <= 2:
    if transport is not None and hasattr(transport, 'clear_bus'):
        try:
            await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
        except Exception:
            logger.warning("SDC failed after '%s' error", name)
elif bus_error_count <= 5:
    if transport is not None and hasattr(transport, 'send_ifc'):
        try:
            await asyncio.wait_for(transport.send_ifc(), timeout=3.0)
        except Exception:
            logger.warning("IFC failed on bus %s", bus_prefix)
        await asyncio.sleep(_IFC_COOLDOWN_S)
        for s in states:
            try:
                await s.config.driver.disconnect()
            except Exception:
                pass
            s.config.driver._connected = False
        break
else:
    logger.error(
        "GPIB bus %s: %d consecutive errors, resetting ResourceManager",
        bus_prefix, bus_error_count,
    )
    from cryodaq.drivers.transport.gpib import GPIBTransport
    GPIBTransport.close_all_managers()
    for s in states:
        s.config.driver._connected = False
    bus_error_count = 0
    break
```

**Trace result:** grouped GPIB changes failure handling and sequencing across devices on the same bus, but **does not** change the persist/publish ordering once a batch enters `_process_readings(...)`.

## Analysis 2: Exception handling matrix

The table below is the practical “what happens if this step raises?” matrix for the pipeline.

| Step | Code location | Example exception path | Does next step execute? | Batch result | Logging | Partial view possible? |
|---|---|---|---|---|---|---|
| Driver `connect()` (standalone) | `scheduler.py:116-125` | Any `Exception` | No read, no write, no publish | Batch absent | `logger.exception` | No |
| Driver `safe_read()` timeout (standalone) | `scheduler.py:127-152` | `TimeoutError` | No | Batch absent | `logger.warning` | No |
| Driver `safe_read()` generic error (standalone) | `scheduler.py:153-168` | Any `Exception` | No | Batch absent | `logger.warning` | No |
| Driver `safe_read()` error (GPIB) | `scheduler.py:242-303` | Any `Exception` | No | Batch absent | `logger.warning` / `logger.error` | No |
| Adaptive throttle | `scheduler.py:331-333` | Any exception from `filter_for_archive(...)` | No write, no publish | Whole batch dropped for that poll | Caller catches as poll error | No persisted/published data |
| SQLite write immediate | `scheduler.py:338-349`, `sqlite_writer.py:525-540` | Any raised exception from `_write_batch(...)` | **No** broker publish | Batch not published | `logger.critical` in writer + `logger.exception` in scheduler | Possible partial persistence if failure happened after an earlier day commit |
| SQLite disk-full silent branch | `scheduler.py:351-355`, `sqlite_writer.py:325-352` | `sqlite3.OperationalError` matching disk-full phrases | **No** broker publish | Batch stops after setting `_disk_full` and scheduling persistence-failure callback | `logger.critical` in writer | Possible already-written earlier day if batch spanned days |
| Calibration SRDG read / write | `scheduler.py:357-371` | Any `Exception` | **Yes**, both broker publishes still execute | Main batch continues | `logger.warning` | Main batch view intact; calibration side data may be missing |
| `DataBroker.publish_batch(...)` | `scheduler.py:373-375`, `broker.py:85-109` | Filter function raises | **No** `SafetyBroker.publish_batch(...)` | Main batch persisted; DataBroker fanout may be partial | No scheduler catch here; bubbles to poll-loop generic exception path | **Yes**: some DataBroker subscribers may have earlier readings, SafetyBroker gets none |
| `SafetyBroker.publish_batch(...)` | `scheduler.py:376-377`, `safety_broker.py:77-109` | Normal queue-full does not raise; overflow callback exceptions are caught | N/A, last step | Main batch already persisted and DataBroker-published | `logger.critical` / `logger.exception` inside SafetyBroker | Yes on queue-full: safety subscriber may miss readings |
| Scheduler task cancellation after SQLite write | `scheduler.py:446-461` + `sqlite_writer.py:525-540` | `task.cancel()` during `_process_readings(...)` | No further broker publish in cancelled task | SQLite may commit, brokers may miss batch | No dedicated log in scheduler | **Yes**, persisted-only batch |
| Per-day split inside `_write_batch(...)` | `sqlite_writer.py:285-292`, `294-324` | Day 2 write raises after day 1 commit | Scheduler sees write failure and skips publish | Partially persisted logical batch | Writer + scheduler logs if exception propagates | **Yes**, persisted-only subset |

### Why `DataBroker.publish_batch(...)` can escape

```python
# src/cryodaq/core/broker.py:85-103
for sub in tuple(self._subscribers.values()):
    if sub.filter_fn and not sub.filter_fn(reading):
        continue
    ...
    try:
        sub.queue.put_nowait(reading)
    except asyncio.QueueFull:
        sub.dropped += 1
```

`filter_fn` is an arbitrary callable. `DataBroker` does not wrap it. So one subscriber bug in a filter function is enough to abort the publish phase and therefore suppress SafetyBroker delivery in scheduler.

### Why disk-full is special

```python
# src/cryodaq/storage/sqlite_writer.py:325-352
except sqlite3.OperationalError as exc:
    msg = str(exc).lower()
    disk_full_phrases = (
        "database or disk is full",
        "database is full",
        "no space left on device",
        "not enough space on the disk",
        "disk quota exceeded",
    )
    if any(phrase in msg for phrase in disk_full_phrases):
        ...
        self._disk_full = True
        self._signal_persistence_failure(f"disk full: {exc}")
        return
    raise
```

This branch intentionally does **not** re-raise. Scheduler therefore relies on the explicit `is_disk_full` check immediately after `write_immediate(...)` to preserve the invariant.

## Analysis 3: Concurrent batches

## C1. Can two batches be in flight simultaneously?

Yes, at the scheduler level.

```python
# src/cryodaq/core/scheduler.py:397-444
async def start(self) -> None:
    self._running = True
    ...
    for bus_prefix, states in gpib_groups.items():
        task = asyncio.create_task(
            self._gpib_poll_loop(bus_prefix, states),
            name=f"gpib_poll_{bus_prefix}",
        )
        self._gpib_tasks[bus_prefix] = task
        for state in states:
            state.task = task

    for state in standalone:
        state.task = asyncio.create_task(
            self._poll_loop(state), name=f"poll_{state.config.driver.name}"
        )
```

- All standalone instruments run in separate tasks.
- Each GPIB bus runs one shared task.
- Therefore multiple tasks can reach `_process_readings(...)` concurrently.

## C2. Can SQLite writes interleave?

Not at the actual write-thread level. `SQLiteWriter` uses a single write executor.

```python
# src/cryodaq/storage/sqlite_writer.py:144-150, 525-540
self._conn: sqlite3.Connection | None = None
...
self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
...
async def write_immediate(self, readings: list[Reading]) -> None:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(self._executor, self._write_batch, readings)
```

So multiple scheduler tasks can **submit** writes concurrently, but actual `_write_batch(...)` executions are serialized in one thread. SQLite commit order is therefore the executor submission order, not necessarily wall-clock sensor order.

## C3. Can broker publishes interleave?

Normal publish code itself is non-blocking and queue-based:

```python
# src/cryodaq/core/broker.py:85-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    for sub in tuple(self._subscribers.values()):
        ...
        sub.queue.put_nowait(reading)

async def publish_batch(self, readings: list[Reading]) -> None:
    for reading in readings:
        await self.publish(reading)
```

```python
# src/cryodaq/core/safety_broker.py:77-109
async def publish(self, reading: Reading) -> None:
    self._total_published += 1
    self._last_update[reading.channel] = time.monotonic()
    for sub in self._subscribers.values():
        ...
        sub.queue.put_nowait(reading)

async def publish_batch(self, readings: list[Reading]) -> None:
    for reading in readings:
        await self.publish(reading)
```

Under normal conditions these methods do not suspend on queue operations. That means once a task has reached broker publication, its own batch is effectively emitted contiguously. Interleaving becomes possible only:

- between different scheduler tasks before they enter publish,
- if `SafetyBroker` overflow callback returns a coroutine,
- or if task cancellation interrupts one publish path.

## C4. Can a slower batch publish after a faster batch was already consumed by SafetyManager?

Yes.

```python
# src/cryodaq/core/scheduler.py:127-133, 243-246
readings = await asyncio.wait_for(
    driver.safe_read(), timeout=cfg.read_timeout_s
)
...
await self._process_readings(state, readings)
```

```python
# src/cryodaq/core/safety_manager.py:631-639
async def _collect_loop(self) -> None:
    ...
    while True:
        reading = await self._queue.get()
        now = time.monotonic()
        self._latest[reading.channel] = (now, reading.value, reading.status.value)
        if reading.unit == "K":
            self._rate_estimator.push(reading.channel, now, reading.value)
```

The four target files guarantee only **arrival order into the brokers**, not timestamp order across instruments. SafetyManager’s consumer side uses its own `time.monotonic()` on dequeue, so its freshness/rate logic is explicitly arrival-ordered, not sensor-timestamp-ordered.

## C5. What ordering does the invariant actually guarantee?

From these files alone, the guaranteed order is:

1. Within one `_process_readings(...)` call: SQLite write before DataBroker before SafetyBroker.
2. Across different scheduler tasks: no global timestamp order guarantee.
3. Across batches submitted to SQLiteWriter: one-at-a-time executor serialization, but submission order can vary by task scheduling.

That means the invariant is **ordering-by-stage**, not **ordering-by-time**.

## Analysis 4: Shutdown semantics

## D1. What does `Scheduler.stop()` actually do?

```python
# src/cryodaq/core/scheduler.py:446-470
async def stop(self) -> None:
    """Остановить все циклы, отключить приборы."""
    self._running = False

    all_tasks: set[asyncio.Task[None]] = set()
    for state in self._instruments.values():
        if state.task and not state.task.done():
            all_tasks.add(state.task)
    for task in self._gpib_tasks.values():
        if not task.done():
            all_tasks.add(task)

    for task in all_tasks:
        task.cancel()
    await asyncio.gather(*all_tasks, return_exceptions=True)

    for state in self._instruments.values():
        state.task = None
        try:
            await state.config.driver.disconnect()
        except Exception:
            logger.exception("Ошибка отключения '%s' при остановке", state.config.driver.name)
```

`Scheduler.stop()`:

- stops new loop iterations by setting `_running = False`
- cancels every polling task immediately
- does **not** drain `_process_readings(...)`
- does **not** wait for broker queues to empty
- does **not** coordinate with `DataBroker` / `SafetyBroker` on delivery completion

## D2. What does `SQLiteWriter.stop()` actually do?

```python
# src/cryodaq/storage/sqlite_writer.py:604-623
async def stop(self) -> None:
    self._running = False
    if self._task:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
    # Shutdown executor FIRST — waits for any in-flight write_batch to finish.
    # Then close connection — no race with executor thread.
    if self._executor is not None:
        self._executor.shutdown(wait=True)
    if self._read_executor is not None:
        self._read_executor.shutdown(wait=True)
    if self._conn:
        self._conn.close()
        self._conn = None
```

If `SQLiteWriter.stop()` is invoked, it **does** wait for in-flight executor writes to finish. But that is a writer-local guarantee. There is no corresponding broker flush/drain primitive in `Scheduler.stop()`, `DataBroker`, or `SafetyBroker`.

## D3. Are in-flight reads cancelled?

Yes.

```python
# src/cryodaq/core/scheduler.py:459-461
for task in all_tasks:
    task.cancel()
await asyncio.gather(*all_tasks, return_exceptions=True)
```

This cancellation can strike:

- while blocked on `driver.safe_read()`
- while blocked on `write_immediate()`
- while blocked on calibration SRDG side branch
- between SQLite completion and broker publication

## D4. Are pending broker publishes flushed?

No broker flush API exists in either broker.

```python
# src/cryodaq/core/broker.py:52-55
def __init__(self) -> None:
    self._subscribers: dict[str, Subscription] = {}
    self._lock = asyncio.Lock()
    self._total_published: int = 0
```

```python
# src/cryodaq/core/safety_broker.py:45-50
def __init__(self) -> None:
    self._subscribers: dict[str, _SafetySubscription] = {}
    self._frozen = False
    self._last_update: dict[str, float] = {}
    self._total_published: int = 0
```

They maintain subscriber queues, but provide no “drain all subscribers before shutdown” method.

## D5. Is there a window where SQLite has data that broker subscribers never saw?

Yes, definitively.

The two clearest windows are:

1. scheduler-task cancellation after `write_immediate()` returns or while the executor write continues
2. per-day partial commit in `_write_batch(...)` before scheduler aborts downstream publish

The reverse window, “brokers saw data that SQLite definitely did not”, is prevented on the normal path because publication comes only after `write_immediate(...)` and after the explicit `is_disk_full` re-check.

## Analysis 5: Adaptive throttle interaction and exact consumer split

## E1. Exact split point

```python
# src/cryodaq/core/scheduler.py:331-377
persisted_readings = list(readings)
if self._adaptive_throttle is not None:
    persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
...
if self._sqlite_writer is not None and persisted_readings:
    await self._sqlite_writer.write_immediate(persisted_readings)
...
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

This is the exact split:

- `DataBroker` gets `persisted_readings`
- `SafetyBroker` gets original `readings`

So throttle affects both persistence and the main broker tree, but **not** the safety broker tree.

## E2. Exact filter applied

```python
# src/cryodaq/core/housekeeping.py:251-307
def filter_for_archive(self, readings: list[Reading]) -> list[Reading]:
    if not self.enabled:
        return list(readings)
    filtered: list[Reading] = []
    for reading in readings:
        if self._should_emit(reading):
            filtered.append(reading)
        else:
            self._suppressed_count += 1
    return filtered

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
    ...
    if delta > threshold:
        ...
        return True
    ...
    if stable_for < self._stable_duration_s:
        ...
        return True
    if since_emit >= self._max_interval_s:
        ...
        return True
    return False
```

So filtering is value/age/status based, with unconditional pass-through for:

- active alarms
- non-OK status
- transition holdoff period
- protected patterns
- excluded patterns
- readings outside the include set

Everything else can be thinned.

## E3. Every `DataBroker` consumer found

### Engine-attached consumers

```python
# src/cryodaq/engine.py:862-863, 1007-1018, 1066-1072, 1096-1102
zmq_queue = await broker.subscribe("zmq_publisher")
zmq_pub = ZMQPublisher()
...
async def _track_runtime_signals() -> None:
    queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
...
async def _alarm_v2_feed_readings() -> None:
    queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
...
async def _sensor_diag_feed() -> None:
    ...
    queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
...
async def _vacuum_trend_feed() -> None:
    ...
    queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
```

### Alarm / interlock / notifications / analytics consumers

```python
# src/cryodaq/core/alarm.py:329-342
self._queue = await self._broker.subscribe(
    _SUBSCRIPTION_NAME,
    maxsize=10_000,
    filter_fn=lambda r: not r.channel.startswith(("alarm/", "analytics/", "system/")),
)
self._task = asyncio.create_task(
    self._check_loop(), name="alarm_check_loop"
)
...
await self._publish_alarm_count()
```

```python
# src/cryodaq/core/interlock.py:305-315
self._queue = await self._broker.subscribe(
    _SUBSCRIPTION_NAME,
    maxsize=10_000,
)
self._task = asyncio.create_task(
    self._check_loop(), name="interlock_check_loop"
)
logger.info(
    "InterlockEngine запущен. Активных блокировок: %d.",
    len(self._interlocks),
)
```

```python
# src/cryodaq/notifications/telegram_commands.py:128-136
async def start(self) -> None:
    self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME, maxsize=5000)
    self._collect_task = asyncio.create_task(self._collect_loop(), name="tg_cmd_collect")
    self._poll_task = asyncio.create_task(self._poll_loop(), name="tg_cmd_poll")
    logger.info(
        "TelegramCommandBot запущен | collect_task=%s poll_task=%s",
        self._collect_task.get_name(),
        self._poll_task.get_name(),
    )
```

```python
# src/cryodaq/notifications/periodic_report.py:111-123
async def start(self) -> None:
    """Подписаться на DataBroker и запустить задачи сбора и отправки."""
    self._queue = await self._broker.subscribe(
        _SUBSCRIPTION_NAME,
        maxsize=20_000,
    )
    self._collect_task = asyncio.create_task(
        self._collect_loop(), name="periodic_reporter_collect"
    )
    self._report_task = asyncio.create_task(
        self._report_loop(), name="periodic_reporter_report"
    )
```

```python
# src/cryodaq/analytics/cooldown_service.py:229-238
channels = {self._channel_cold, self._channel_warm}

def _filter(reading: Reading) -> bool:
    return reading.channel in channels

self._queue = await self._broker.subscribe(
    "cooldown_service",
    maxsize=5000,
    filter_fn=_filter,
)
```

```python
# src/cryodaq/analytics/plugin_loader.py:81-99
if self._running:
    logger.warning("Пайплайн уже запущен — повторный вызов start() проигнорирован")
    return

self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME)
logger.info("Пайплайн подписан на брокер как '%s'", _SUBSCRIBE_NAME)

self._plugins_dir.mkdir(parents=True, exist_ok=True)
for path in sorted(self._plugins_dir.glob("*.py")):
    self._load_plugin(path)
```

### Filtering impact by `DataBroker` consumer

| Consumer | Stream source | Does throttling matter? | Why |
|---|---|---|---|
| `zmq_publisher` | `DataBroker` | **Yes** | Remote GUI/web subscribers see the throttled archive stream, not full raw cadence. |
| `adaptive_throttle_runtime` | `DataBroker` | Low/indirect | It mainly consumes analytics/safety runtime signals published elsewhere, not raw sensor cadence. |
| `alarm_v2_state_feed` | `DataBroker` | **Yes** | It derives state/rate/staleness from the throttled stream. |
| `sensor_diag_feed` | `DataBroker` | **Yes** | Diagnostics buffers receive thinned data. |
| `vacuum_trend_feed` | `DataBroker` | **Yes** | Pressure trend sees throttled pressure points. |
| `AlarmEngine` | `DataBroker` with `filter_fn` | **Yes** | It excludes analytics/system/alarm channels but still sees only the throttled physical reading stream. |
| `InterlockEngine` | `DataBroker` | **Yes** | It consumes the same throttled physical readings, not the full safety stream. |
| `TelegramCommandBot` | `DataBroker` | Usually low | It is mostly command/log oriented; raw-reading cadence is not its primary concern. |
| `PeriodicReporter` | `DataBroker` | **Yes** | Reports are built from the throttled stream. |
| `CooldownService` | `DataBroker` with channel filter | **Yes** | It receives only selected channels, but still from the throttled stream. |
| `PluginAnalyticsPipeline` | `DataBroker` | **Yes** | Plugin analytics ingest the throttled main stream. |

## E4. Every `SafetyBroker` consumer found

Only one live consumer was found:

```python
# src/cryodaq/core/safety_manager.py:157-163
async def start(self) -> None:
    self._queue = self._broker.subscribe("safety_manager", maxsize=self._config.max_safety_backlog)
    self._broker.freeze()
    self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
    self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
    await self._publish_state("initial")
    await self._publish_keithley_channel_states("initial")
```

**Filtering impact:** none. `SafetyBroker` receives the original unthrottled `readings` list from scheduler.

## E5. Is there any consumer between the two branches that can be inconsistent?

Yes. The split is not just “archive vs safety”; it is “main broker ecosystem vs safety-only ecosystem”.

The exact inconsistency point is:

```python
# src/cryodaq/core/scheduler.py:331-377
persisted_readings = list(readings)
if self._adaptive_throttle is not None:
    persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
...
await self._sqlite_writer.write_immediate(persisted_readings)
...
await self._broker.publish_batch(persisted_readings)
...
await self._safety_broker.publish_batch(readings)
```

That means any `DataBroker`-based consumer can disagree with `SafetyManager` simply because they are not consuming the same batch object:

- `DataBroker` consumers see `persisted_readings`
- `SafetyManager` sees `readings`

The split is deliberate in code, but it is materially observable.

## Bottom line

The four target files do uphold the narrow invariant that **scheduler does not intentionally publish before persistence succeeds**. The normal path is structurally correct.

However, the exhaustive trace shows that this is **not** an atomic “persist + notify” transaction. The places where the model breaks down are:

- task cancellation during shutdown
- `DataBroker` exceptions preventing `SafetyBroker`
- multi-transaction per-day writes
- branch split between throttled `DataBroker` and full `SafetyBroker`

So the correct statement of the invariant is:

> `Scheduler` persists `persisted_readings` before publishing them to `DataBroker`, and only later publishes full `readings` to `SafetyBroker`.

That is true.

The stronger statement:

> one poll cycle is atomically either invisible everywhere or visible in SQLite + DataBroker + SafetyBroker consistently

is **not** true in the current implementation.

## Summary counts

- **Paths traced:** 3 (`_poll_loop`, `_gpib_poll_loop`, common `_process_readings` path including calibration side branch)
- **Exception cells analyzed:** 11
- **Concurrent scenarios examined:** 5
- **New findings by severity:** 1 HIGH, 2 MEDIUM, 1 LOW
