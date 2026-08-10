"""Tests for Scheduler — registration, polling, stats, and graceful stop."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cryodaq.core.broker import PERSISTENCE_AUTHORITATIVE_METADATA_KEY, DataBroker
from cryodaq.core.interlock import InterlockCondition, InterlockConfigError, InterlockEngine
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusDescriptor,
    DriverRuntimeBinding,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Concrete mock driver for use in all scheduler tests
# ---------------------------------------------------------------------------


class MockDriver(InstrumentDriver):
    """Minimal concrete driver: connect sets flag, read returns one reading."""

    def __init__(self, name: str = "mock_instrument") -> None:
        super().__init__(name, mock=True)
        self.connect_calls: int = 0
        self.disconnect_calls: int = 0
        self.read_calls: int = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        self.read_calls += 1
        return [Reading.now("CH1", 4.2, "K", instrument_id="test")]


def _bus_binding(driver: InstrumentDriver, bus_id: str, poll_interval_s: float) -> DriverRuntimeBinding:
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, poll_interval_s),
        registry_provenance="test:explicit-bus",
        trust_class=DriverTrustClass.PASSIVE_EXTENSION,
        bus_descriptor=BusDescriptor(bus_id),
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_LS218_1_LABELS = {
    1: "Т1 Криостат верх",
    2: "Т2 Криостат низ",
    3: "Т3 Радиатор 1",
    4: "Т4 Радиатор 2",
    5: "Т5 Экран 77К",
    6: "Т6 Экран 4К",
    7: "Т7 Детектор",
    8: "Т8 Калибровка",
}
_LS218_2_LABELS = {
    1: "Т9 Компрессор вход",
    2: "Т10 Компрессор выход",
    3: "Т11 Теплообменник 1",
    4: "Т12 Теплообменник 2",
    5: "Т13 Труба подачи",
    6: "Т14 Труба возврата",
    7: "Т15 Вакуумный кожух",
    8: "Т16 Фланец",
}


def _write_oc041_interlock_config(
    tmp_path: Path,
    *,
    poll_interval_s: float,
    min_samples: int = 5,
    min_duration_s: float | None = None,
    filename: str = "interlocks.yaml",
) -> tuple[Path, float]:
    duration_s = poll_interval_s * (min_samples - 1) if min_duration_s is None else min_duration_s
    config_path = tmp_path / filename
    config_path.write_text(
        f"""interlocks:
  - name: overheat_cryostat
    description: Cryostat overheat
    channel_bindings:
      - instrument_id: LS218_1
        source_key: input.1.temperature
    threshold: 350.0
    comparison: \">\"
    action: emergency_off
nonusable_escalation:
  min_duration_s: {duration_s!r}
  min_samples: {min_samples}
""",
        encoding="utf-8",
    )
    return config_path, duration_s


async def _wait_for_safety_state(manager: SafetyManager, state: SafetyState) -> None:
    if manager.state is state:
        return
    reached = asyncio.Event()

    def observe_state(_old: SafetyState, new: SafetyState, _reason: str) -> None:
        if new is state:
            reached.set()

    manager.on_state_change(observe_state)
    if manager.state is state:
        reached.set()
    await reached.wait()


async def _take_readings(queue: asyncio.Queue[Reading], count: int) -> list[Reading]:
    return [await queue.get() for _ in range(count)]


async def _wait_for_channel_count(
    queue: asyncio.Queue[Reading],
    channel: str,
    count: int,
) -> None:
    observed = 0
    while observed < count:
        reading = await queue.get()
        if reading.channel == channel:
            observed += 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def broker() -> DataBroker:
    return DataBroker()


@pytest.fixture()
def scheduler(broker: DataBroker) -> Scheduler:
    return Scheduler(broker)


# ---------------------------------------------------------------------------
# 1. add() registers the instrument by driver name
# ---------------------------------------------------------------------------


async def test_add_instrument(scheduler: Scheduler) -> None:
    driver = MockDriver("ls218s")
    config = InstrumentConfig(driver=driver, poll_interval_s=1.0)
    scheduler.add(config)

    assert "ls218s" in scheduler.stats


# ---------------------------------------------------------------------------
# 2. Mock driver is polled and readings reach the broker
# ---------------------------------------------------------------------------


async def test_mock_driver_polled(broker: DataBroker) -> None:
    queue = await broker.subscribe("test_consumer", maxsize=100)

    driver = MockDriver("poller")
    sched = Scheduler(broker, publish_unpersisted_readings=True)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    # Wait deterministically for the first reading to arrive (no fixed sleep)
    reading = await asyncio.wait_for(queue.get(), timeout=2.0)
    await sched.stop()

    assert reading.channel == "CH1"
    assert abs(reading.value - 4.2) < 1e-9
    assert PERSISTENCE_AUTHORITATIVE_METADATA_KEY not in reading.metadata


async def test_successful_sqlite_commit_marks_published_reading_authoritative(
    broker: DataBroker,
) -> None:
    class _Writer:
        is_disk_full = False

        async def write_immediate(self, readings: list[Reading]) -> bool:
            assert readings
            return True

    queue = await broker.subscribe("authority_consumer", maxsize=10)
    driver = MockDriver("authority")
    sched = Scheduler(broker, sqlite_writer=_Writer())
    sched.add(InstrumentConfig(driver=driver))
    state = sched._instruments[driver.name]

    await sched._process_readings(state, await driver.read_channels())

    reading = queue.get_nowait()
    queue.task_done()
    assert reading.metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] is True


# ---------------------------------------------------------------------------
# 3. Registering the same driver name twice raises ValueError
# ---------------------------------------------------------------------------


async def test_duplicate_driver_rejected(scheduler: Scheduler) -> None:
    driver_a = MockDriver("duplicate")
    driver_b = MockDriver("duplicate")

    scheduler.add(InstrumentConfig(driver=driver_a))

    with pytest.raises(ValueError, match="duplicate"):
        scheduler.add(InstrumentConfig(driver=driver_b))


# ---------------------------------------------------------------------------
# 4. stats.total_reads increases after polling
# ---------------------------------------------------------------------------


async def test_stats_track_reads(broker: DataBroker) -> None:
    await broker.subscribe("stats_consumer", maxsize=1000)

    driver = MockDriver("stats_driver")
    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    await asyncio.sleep(0.15)
    await sched.stop()

    assert sched.stats["stats_driver"]["total_reads"] > 0


# ---------------------------------------------------------------------------
# 5. stop() cancels tasks and disconnects drivers
# ---------------------------------------------------------------------------


async def test_graceful_stop(broker: DataBroker) -> None:
    await broker.subscribe("stop_consumer", maxsize=100)

    driver = MockDriver("stoppable")
    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()

    # Driver must have been disconnected by stop()
    assert not driver.connected
    assert driver.disconnect_calls >= 1

    # All tasks must be cancelled/done — no lingering tasks in the scheduler
    states = list(sched._instruments.values())
    for state in states:
        assert state.task is None or state.task.done()


# ---------------------------------------------------------------------------
# 6. GPIB instruments on same bus share one task; non-GPIB get their own
# ---------------------------------------------------------------------------


async def test_gpib_bus_grouping(broker: DataBroker) -> None:
    await broker.subscribe("gpib_consumer", maxsize=1000)

    ls1 = MockDriver("ls218_1")
    ls2 = MockDriver("ls218_2")
    usb_driver = MockDriver("keithley")

    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=ls1, runtime_binding=_bus_binding(ls1, "GPIB0", 0.01)))
    sched.add(InstrumentConfig(driver=ls2, runtime_binding=_bus_binding(ls2, "GPIB0", 0.01)))
    sched.add(InstrumentConfig(driver=usb_driver, poll_interval_s=0.01, resource_str="USB0::MOCK"))

    await sched.start()

    # Both GPIB instruments must share the same task
    ls1_task = sched._instruments["ls218_1"].task
    ls2_task = sched._instruments["ls218_2"].task
    usb_task = sched._instruments["keithley"].task

    assert ls1_task is ls2_task, "GPIB instruments on same bus must share one task"
    assert usb_task is not ls1_task, "Non-GPIB instrument must have its own task"

    await asyncio.sleep(0.1)
    await sched.stop()

    # Both GPIB instruments must have been polled
    assert ls1.read_calls > 0
    assert ls2.read_calls > 0
    assert usb_driver.read_calls > 0


async def test_gpib_sequential_connect(broker: DataBroker) -> None:
    """GPIB instruments must connect sequentially in one task, not in parallel.

    Asserts max concurrent connects == 1 (overlap counter), which catches a
    parallel-connect regression that the original order-only check would miss.
    """
    await broker.subscribe("seq_consumer", maxsize=1000)

    connect_order: list[str] = []
    concurrent_count = 0
    max_concurrent = 0

    class OrderedDriver(MockDriver):
        async def connect(self) -> None:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            connect_order.append(self.name)
            await asyncio.sleep(0.02)  # small delay so overlap is detectable
            await super().connect()
            concurrent_count -= 1

    # Each driver signals its own event when connect() finishes.
    d1_connected = asyncio.Event()
    d2_connected = asyncio.Event()

    _orig_OrderedDriver_connect = OrderedDriver.connect

    async def _patched_connect_d1(self) -> None:
        await _orig_OrderedDriver_connect(self)
        d1_connected.set()

    async def _patched_connect_d2(self) -> None:
        await _orig_OrderedDriver_connect(self)
        d2_connected.set()

    d1 = OrderedDriver("gpib_first")
    d2 = OrderedDriver("gpib_second")
    d1.connect = lambda: _patched_connect_d1(d1)  # type: ignore[method-assign]
    d2.connect = lambda: _patched_connect_d2(d2)  # type: ignore[method-assign]

    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=d1, runtime_binding=_bus_binding(d1, "GPIB0", 0.05)))
    sched.add(InstrumentConfig(driver=d2, runtime_binding=_bus_binding(d2, "GPIB0", 0.05)))

    await sched.start()
    # Wait until both connects complete — no fixed sleep.
    await asyncio.wait_for(
        asyncio.gather(d1_connected.wait(), d2_connected.wait()),
        timeout=5.0,
    )
    await sched.stop()

    # Both must have connected
    assert "gpib_first" in connect_order, f"gpib_first never connected; order={connect_order}"
    assert "gpib_second" in connect_order, f"gpib_second never connected; order={connect_order}"
    # Sequential invariant: at no point were two connects in-flight simultaneously
    assert max_concurrent == 1, (
        f"GPIB connects must be sequential (max concurrent=1), got {max_concurrent}. connect_order={connect_order}"
    )


# ---------------------------------------------------------------------------
# OC-041: shared-bus silence must remain persistence-first and fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("persistence_outcome", ("rejection", "exception"))
async def test_failed_poll_persistence_failure_latches_safety(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persistence_outcome: str,
) -> None:
    """Rejected or failed commits cannot turn instrument silence back into silence."""

    class FailingTemperatureDriver(LakeShore218S):
        def __init__(self) -> None:
            super().__init__(
                "LS218_1",
                "GPIB0::12::INSTR",
                channel_labels=_LS218_1_LABELS,
                mock=True,
            )
            self.read_calls = 0
            self.failure_reading_calls = 0

        async def read_channels(self) -> list[Reading]:
            self.read_calls += 1
            raise OSError("simulated GPIB read failure")

        def failure_readings(self) -> list[Reading]:
            self.failure_reading_calls += 1
            return super().failure_readings()

    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    writer = SQLiteWriter(tmp_path / "writer", channel_catalog=catalog)
    await writer.start_immediate()

    def persistence_failure(_batch: object) -> None:
        if persistence_outcome == "rejection":
            return None
        raise RuntimeError("synthetic non-disk persistence failure")

    monkeypatch.setattr(writer, "_write_live_batch", persistence_failure)

    broker = DataBroker()
    data_probe = await broker.subscribe("oc041_persistence_probe", maxsize=32)
    safety_broker = SafetyBroker()
    safety_probe = safety_broker.subscribe("oc041_safety_probe", maxsize=32)
    safety = SafetyManager(safety_broker, keithley_driver=None, mock=True)
    safety._config.require_keithley_for_run = False
    safety._config.critical_channels = []
    safety._config.cooldown_before_rearm_s = 0.0
    await safety.start()

    failure_report_count = 0
    allow_reassertion = asyncio.Event()
    second_failure_reported = asyncio.Event()

    async def handle_failed_poll_persistence(reason: str) -> None:
        nonlocal failure_report_count
        failure_report_count += 1
        if failure_report_count > 1:
            await allow_reassertion.wait()
        await safety.on_persistence_failure(reason)
        if failure_report_count > 1:
            second_failure_reported.set()

    driver = FailingTemperatureDriver()
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=writer,
        failed_poll_persistence_handler=handle_failed_poll_persistence,
    )
    scheduler.add(
        InstrumentConfig(
            driver=driver,
            runtime_binding=_bus_binding(driver, "GPIB0", 0.01),
        )
    )
    try:
        await scheduler.start()
        await asyncio.wait_for(
            _wait_for_safety_state(safety, SafetyState.FAULT_LATCHED),
            timeout=2.0,
        )

        assert driver.failure_reading_calls >= 1
        assert data_probe.empty(), "rejected failed-poll evidence must not bypass persistence into DataBroker"
        assert safety_probe.empty(), "rejected failed-poll evidence must not bypass persistence into SafetyBroker"
        assert "failed-poll" in safety.fault_reason

        acknowledged = await safety.acknowledge_fault("persistent failed-poll persistence failure")
        assert acknowledged == {"ok": True, "state": SafetyState.MANUAL_RECOVERY.value}
        allow_reassertion.set()
        await asyncio.wait_for(second_failure_reported.wait(), timeout=2.0)
        await asyncio.wait_for(
            _wait_for_safety_state(safety, SafetyState.FAULT_LATCHED),
            timeout=2.0,
        )

        blocked = await safety.request_run(0.5, 40.0, 1.0)
        assert blocked["ok"] is False
        assert blocked["state"] == SafetyState.FAULT_LATCHED.value
        assert failure_report_count >= 2
        assert driver.failure_reading_calls >= 2
        assert data_probe.empty()
        assert safety_probe.empty()
    finally:
        await scheduler.stop()
        await safety.stop()
        await writer.stop()


async def test_descriptor_dual_broker_requires_failed_poll_persistence_handler(tmp_path: Path) -> None:
    """A production-shaped dual-broker scheduler cannot omit the latch route."""
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    writer = SQLiteWriter(tmp_path / "writer", channel_catalog=catalog)
    scheduler = Scheduler(DataBroker(), safety_broker=SafetyBroker(), sqlite_writer=writer)
    try:
        with pytest.raises(RuntimeError, match="failed-poll persistence safety handler"):
            await scheduler.start()
    finally:
        await writer.stop()


async def test_shared_bus_read_failure_faults_interlock_protected_zone(tmp_path: Path) -> None:
    """A mature idle failure blocks RUN, recovery clears it, and recurrence faults."""

    class FailingTemperatureDriver(LakeShore218S):
        def __init__(self) -> None:
            super().__init__(
                "LS218_1",
                "GPIB0::12::INSTR",
                channel_labels=_LS218_1_LABELS,
                mock=True,
            )
            self.read_calls = 0
            self._mode = "failing"
            self.recovery_read_returned = asyncio.Event()
            self.resume_failures = asyncio.Event()

        def recover_once(self) -> None:
            self._mode = "recover_once"

        async def read_channels(self) -> list[Reading]:
            self.read_calls += 1
            if self._mode == "recover_once":
                self._mode = "wait_for_recurrence"
                readings = await super().read_channels()
                self.recovery_read_returned.set()
                return readings
            if self._mode == "wait_for_recurrence":
                await self.resume_failures.wait()
                self._mode = "failing"
            raise OSError("simulated GPIB read failure")

    poll_interval_s = 0.01
    config_path, _min_duration_s = _write_oc041_interlock_config(
        tmp_path,
        poll_interval_s=poll_interval_s,
    )
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    broker = DataBroker()
    safety_broker = SafetyBroker()
    safety = SafetyManager(safety_broker, keithley_driver=None, mock=True)
    safety._config.require_keithley_for_run = False
    safety._config.critical_channels = []
    await safety.start()

    mature_dead_window = asyncio.Event()
    recovered_channel = asyncio.Event()
    fault_latched = asyncio.Event()

    async def dead_channel_handler(condition: InterlockCondition, reading: Reading) -> bool:
        latched = await safety.on_interlock_dead_channel(condition.name, reading.channel, value=reading.value)
        mature_dead_window.set()
        if latched:
            fault_latched.set()
        return latched

    async def recovery_handler(condition: InterlockCondition, reading: Reading) -> None:
        safety.on_interlock_channel_recovered(condition.name, reading.channel)
        recovered_channel.set()

    async def no_op() -> None:
        return None

    interlocks = InterlockEngine(
        broker,
        actions={"emergency_off": no_op},
        dead_channel_handler=dead_channel_handler,
        dead_channel_recovery_handler=recovery_handler,
    )
    interlocks.load_config(
        config_path,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument={"LS218_1": poll_interval_s},
    )
    await interlocks.start()

    writer = SQLiteWriter(tmp_path / "writer", channel_catalog=catalog)
    writer.set_event_loop(asyncio.get_running_loop())
    writer.set_persistence_failure_callback(safety.on_persistence_failure)
    await writer.start_immediate()
    driver = FailingTemperatureDriver()
    scheduler = Scheduler(broker, sqlite_writer=writer)
    scheduler.add(
        InstrumentConfig(
            driver=driver,
            runtime_binding=_bus_binding(driver, "GPIB0", poll_interval_s),
        )
    )
    try:
        await scheduler.start()

        await asyncio.wait_for(mature_dead_window.wait(), timeout=8.0)
        assert safety.state is not SafetyState.FAULT_LATCHED
        blocked = await safety.request_run(0.5, 40.0, 1.0)
        assert blocked["ok"] is False
        assert "Persistently unusable interlock channel" in blocked["error"]

        driver.recover_once()
        await asyncio.wait_for(driver.recovery_read_returned.wait(), timeout=8.0)
        await asyncio.wait_for(recovered_channel.wait(), timeout=8.0)
        run_result = await safety.request_run(0.5, 40.0, 1.0)
        assert run_result["ok"] is True
        assert safety.state is SafetyState.RUNNING

        driver.resume_failures.set()
        await asyncio.wait_for(fault_latched.wait(), timeout=8.0)
        assert safety.state is SafetyState.FAULT_LATCHED
    finally:
        driver.resume_failures.set()
        await scheduler.stop()
        await interlocks.stop()
        await safety.stop()
        await writer.stop()


async def test_shared_bus_healthy_slow_poll_does_not_escalate(tmp_path: Path) -> None:
    """A healthy slow poll uses its configured cadence and never looks silent."""
    poll_interval_s = 0.06
    min_samples = 5
    config_path, min_duration_s = _write_oc041_interlock_config(
        tmp_path,
        poll_interval_s=poll_interval_s,
        filename="slow-interlocks.yaml",
    )
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    broker = DataBroker()
    healthy_probe = await broker.subscribe("oc041_slow_probe", maxsize=128)
    escalated = asyncio.Event()

    async def dead_channel_handler(_condition: InterlockCondition, _reading: Reading) -> bool:
        escalated.set()
        return True

    async def no_op() -> None:
        return None

    interlocks = InterlockEngine(
        broker,
        actions={"emergency_off": no_op},
        dead_channel_handler=dead_channel_handler,
    )
    interlocks.load_config(
        config_path,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument={"LS218_1": poll_interval_s},
    )
    await interlocks.start()

    class SlowHealthyDriver(LakeShore218S):
        def __init__(self) -> None:
            super().__init__(
                "LS218_1",
                "GPIB0::12::INSTR",
                channel_labels=_LS218_1_LABELS,
                mock=True,
            )
            self.read_calls = 0

        async def read_channels(self) -> list[Reading]:
            self.read_calls += 1
            return await super().read_channels()

    writer = SQLiteWriter(tmp_path / "writer", channel_catalog=catalog)
    await writer.start_immediate()
    driver = SlowHealthyDriver()
    scheduler = Scheduler(broker, sqlite_writer=writer)
    scheduler.add(
        InstrumentConfig(
            driver=driver,
            runtime_binding=_bus_binding(driver, "GPIB0", poll_interval_s),
        )
    )
    try:
        await scheduler.start()
        await asyncio.wait_for(
            _wait_for_channel_count(healthy_probe, "Т1", min_samples),
            timeout=8.0,
        )
        assert driver.read_calls >= min_samples
        assert not escalated.is_set(), "healthy configured slow polls must not be treated as instrument silence"
        assert min_duration_s == poll_interval_s * (min_samples - 1)
    finally:
        await scheduler.stop()
        await interlocks.stop()
        await writer.stop()


def test_selected_nonusable_escalation_is_cadence_bounded() -> None:
    """The shipped 10 s / 5-sample policy is accepted against its 2 s polls."""
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    engine = InterlockEngine(
        DataBroker(),
        actions={"emergency_off": lambda: None, "stop_source": lambda: None},
    )
    engine.load_config(
        _CONFIG_DIR / "interlocks.yaml",
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument={"LS218_1": 2.0, "LS218_2": 2.0},
    )


@pytest.mark.parametrize(
    ("min_duration_s", "min_samples", "message"),
    (
        (10.01, 5, "cadence bound"),
        (10.0, 6, "reviewed maximum"),
    ),
)
def test_nonusable_escalation_rejects_windows_beyond_configured_cadence(
    tmp_path: Path,
    min_duration_s: float,
    min_samples: int,
    message: str,
) -> None:
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    config_path, _duration = _write_oc041_interlock_config(
        tmp_path,
        poll_interval_s=2.0,
        min_duration_s=min_duration_s,
        min_samples=min_samples,
    )
    engine = InterlockEngine(DataBroker(), actions={"emergency_off": lambda: None})
    with pytest.raises(InterlockConfigError, match=message):
        engine.load_config(
            config_path,
            descriptor_catalog=catalog,
            poll_intervals_s_by_instrument={"LS218_1": 2.0},
        )


def test_nonusable_escalation_requires_protected_instrument_cadence(tmp_path: Path) -> None:
    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    config_path, _duration = _write_oc041_interlock_config(tmp_path, poll_interval_s=2.0)
    engine = InterlockEngine(DataBroker(), actions={"emergency_off": lambda: None})
    with pytest.raises(InterlockConfigError, match="requires configured poll intervals"):
        engine.load_config(config_path, descriptor_catalog=catalog)


async def test_ls218_2_single_failed_poll_faults_mandatory_critical_inputs(tmp_path: Path) -> None:
    """One LS218_2 timeout remains stronger than the interlock debounce policy."""

    class SingleFailureDriver(LakeShore218S):
        def __init__(self) -> None:
            super().__init__(
                "LS218_2",
                "GPIB0::14::INSTR",
                channel_labels=_LS218_2_LABELS,
                mock=True,
            )
            self.read_calls = 0
            self.failure_reading_calls = 0
            self.allow_failure = asyncio.Event()
            self.hold_after_failure = asyncio.Event()

        async def read_channels(self) -> list[Reading]:
            self.read_calls += 1
            if self.read_calls == 1:
                return await super().read_channels()
            if self.failure_reading_calls == 0:
                await self.allow_failure.wait()
                raise OSError("one LS218_2 whole-poll failure")
            await self.hold_after_failure.wait()
            return []

        def failure_readings(self) -> list[Reading]:
            self.failure_reading_calls += 1
            return super().failure_readings()

    catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    broker = DataBroker()
    safety_broker = SafetyBroker()
    safety_probe = safety_broker.subscribe("oc041_critical_probe", maxsize=32)
    safety = SafetyManager(safety_broker, keithley_driver=None, mock=True)
    safety.load_config(_CONFIG_DIR / "safety.yaml")
    safety._config.require_keithley_for_run = False
    await safety.start()

    writer = SQLiteWriter(tmp_path / "writer", channel_catalog=catalog)
    writer.set_event_loop(asyncio.get_running_loop())
    writer.set_persistence_failure_callback(safety.on_persistence_failure)
    await writer.start_immediate()
    driver = SingleFailureDriver()
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=writer,
        failed_poll_persistence_handler=safety.on_persistence_failure,
    )
    scheduler.add(
        InstrumentConfig(
            driver=driver,
            runtime_binding=_bus_binding(driver, "GPIB0", 0.01),
        )
    )
    try:
        await scheduler.start()
        healthy = await asyncio.wait_for(_take_readings(safety_probe, 8), timeout=8.0)
        assert all(reading.status is ChannelStatus.OK for reading in healthy)
        assert {reading.channel for reading in healthy} >= {
            _LS218_2_LABELS[3],
            _LS218_2_LABELS[4],
        }

        run_result = await safety.request_run(0.5, 40.0, 1.0)
        assert run_result["ok"] is True
        assert safety.state is SafetyState.RUNNING

        driver.allow_failure.set()
        failed = await asyncio.wait_for(_take_readings(safety_probe, 8), timeout=8.0)
        assert driver.failure_reading_calls == 1
        critical_failed = [reading for reading in failed if reading.channel in {_LS218_2_LABELS[3], _LS218_2_LABELS[4]}]
        assert len(critical_failed) == 2
        assert all(reading.status is ChannelStatus.TIMEOUT for reading in critical_failed)

        await asyncio.wait_for(
            _wait_for_safety_state(safety, SafetyState.FAULT_LATCHED),
            timeout=2.0,
        )
        assert driver.failure_reading_calls == 1, "critical-input policy must fault before five failed polls"
    finally:
        driver.hold_after_failure.set()
        await scheduler.stop()
        await safety.stop()
        await writer.stop()


# ---------------------------------------------------------------------------
# Phase 2d B-2.3: P1 — graceful drain
# ---------------------------------------------------------------------------


async def test_stop_graceful_drain_completes_inflight():
    """P1: stop() graceful drain must let in-flight polls finish.

    The driver's read_channels signals that it has started (read_started event),
    then blocks on a release_event. stop() is called while the read is blocked.
    The test releases the block before the drain timeout, then verifies:
    - the poll completed (read completed without CancelledError)
    - disconnect was called (clean teardown, not forced cancel)
    This is distinct from test_stop_drain_timeout_forces_cancel (:235) which
    tests the force-cancel path — do NOT weaken that test.
    """
    read_started = asyncio.Event()
    release_read = asyncio.Event()
    read_completed = False

    class BlockingUntilReleased(MockDriver):
        async def read_channels(self) -> list[Reading]:
            nonlocal read_completed
            read_started.set()
            await release_read.wait()
            read_completed = True
            return [Reading.now("CH1", 4.2, "K", instrument_id="test")]

    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None, drain_timeout_s=2.0)
    driver = BlockingUntilReleased("drainer")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.05, resource_str="mock"))

    await sched.start()

    # Wait until the driver is actually in the middle of a read
    await asyncio.wait_for(read_started.wait(), timeout=2.0)
    assert not read_completed, "Read must be in-flight (blocked) when stop() is called"

    # Call stop() — drain should wait for the in-flight read to finish
    stop_task = asyncio.create_task(sched.stop())

    # Release the blocked read so drain can complete within its timeout
    release_read.set()
    await asyncio.wait_for(stop_task, timeout=3.0)

    # Drain completed: read finished naturally (not force-cancelled)
    assert read_completed, "In-flight read must complete during graceful drain"
    assert driver._connected is False, "Driver must be disconnected after stop()"
    assert driver.disconnect_calls >= 1, "disconnect() must be called during stop()"


async def test_stop_drain_timeout_forces_cancel():
    """P1: if a poll is stuck mid-read past the drain timeout, stop() must escalate
    to a forced cancel. Uses the REAL drain_timeout_s ctor param (production reads
    self._drain_timeout_s, not the _DRAIN_TIMEOUT_S a prior test set) and a driver
    whose read blocks, so the timeout→cancel path actually executes."""

    class BlockingDriver(MockDriver):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.read_started = False
            self.cancelled = False

        async def read_channels(self) -> list[Reading]:
            self.read_started = True
            try:
                await asyncio.sleep(30)  # block well past the drain timeout
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return [Reading.now("CH1", 4.2, "K", instrument_id="test")]

    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None, drain_timeout_s=0.05)

    driver = BlockingDriver("slow")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01, resource_str="mock"))

    await sched.start()
    await asyncio.sleep(0.1)  # let the poll enter the blocking read
    assert driver.read_started, "poll must be in-flight for the drain path to matter"

    await sched.stop()  # drain times out → forced cancel

    # The stuck poll was force-cancelled, and the instrument was disconnected.
    assert driver.cancelled, "drain timeout must escalate to task.cancel()"
    assert driver.disconnect_calls >= 1
    assert driver._connected is False
