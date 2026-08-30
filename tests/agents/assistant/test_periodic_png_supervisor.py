from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_png import (
    PeriodicPngSupervisor,
    PeriodicSourceUnavailable,
)
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.periodic_config import PeriodicPngConfigLoad
from cryodaq.periodic_state import (
    PERIODIC_LEADER_LOCK,
    PeriodicContractError,
    load_periodic_state,
    set_periodic_health,
    write_periodic_state,
)
from tests.agents.assistant.test_periodic_png_coordinator import Clock, _config


def _runnable_load() -> PeriodicPngConfigLoad:
    return PeriodicPngConfigLoad(
        selected_path=None,
        requested=True,
        runnable=True,
        config=_config(),
        error_code=None,
        error_text="",
    )


def _settle_attempts(seconds: float = 30.0) -> Iterator[None]:
    """Yield settle attempts until a wall-clock budget expires.

    See the twin in ``test_periodic_png_recovery.py``: each loop exits as soon
    as its condition holds, so this is a give-up point rather than a latency
    assertion, and the former ``range(100)`` around a 1 ms sleep expired on
    loaded CI runners. The budget is wall-clock because a 1 ms sleep costs
    ~1 ms on Linux and ~15 ms on Windows, so a fixed count is two different
    budgets.
    """

    deadline = time.monotonic() + seconds
    while True:
        yield None
        if time.monotonic() >= deadline:
            return


# Separate and deliberately small: bounds a filesystem inode-fence race, not a
# state transition.
_STABLE_LOAD_RETRIES = 100


async def _load_stable(data_dir: Path):
    last_error: PeriodicContractError | None = None
    for _ in range(_STABLE_LOAD_RETRIES):
        try:
            return load_periodic_state(data_dir)
        except PeriodicContractError as exc:
            last_error = exc
            await asyncio.sleep(0)
    assert last_error is not None
    raise last_error


class Coordinator:
    def __init__(self) -> None:
        self.config = _config()
        self.started = 0
        self.stopped = 0
        self.done = asyncio.Event()

    async def start(self) -> None:
        self.started += 1

    async def wait(self) -> None:
        await self.done.wait()

    async def stop(self) -> None:
        self.stopped += 1
        self.done.set()


@pytest.mark.asyncio
async def test_disallowed_returns_before_config_or_factory(tmp_path: Path) -> None:
    calls: list[str] = []

    def loader(_path: Path):
        calls.append("config")
        raise AssertionError

    def factory(_config):
        calls.append("factory")
        raise AssertionError

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=False,
        coordinator_factory=factory,
        config_loader=loader,
        clock=Clock(),
    )
    await supervisor.run()
    assert calls == []


@pytest.mark.asyncio
async def test_unrequested_creates_no_lock_or_runtime(tmp_path: Path) -> None:
    made = 0
    loaded = asyncio.Event()

    def factory(_config):
        nonlocal made
        made += 1
        raise AssertionError

    def loader(_path: Path) -> PeriodicPngConfigLoad:
        loaded.set()
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=False,
            runnable=False,
            config=None,
            error_code=None,
            error_text="",
        )

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=loader,
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    await loaded.wait()
    assert made == 0
    assert not (tmp_path / ".report-locks").exists()
    assert not (tmp_path / "reporting").exists()
    assert not task.done()
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_standby_without_leadership_constructs_zero_runtime_resources(
    tmp_path: Path,
) -> None:
    incumbent = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert incumbent is not None
    made = 0

    def factory(_config):
        nonlocal made
        made += 1
        raise AssertionError("standby must not construct coordinator resources")

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    try:
        # Negative assertion: this is the one loop here that *wants* to run out.
        # It gives the supervisor a window in which to wrongly finish, so a
        # generous budget buys nothing and costs the whole wait every run.
        for _ in _settle_attempts(0.5):
            if task.done():
                break
            await asyncio.sleep(0.001)
        assert not task.done()
        assert made == 0
        assert not (tmp_path / "reporting").exists()
        await supervisor.stop()
        await task
    finally:
        release_lock(incumbent, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_stop_is_idempotent_before_run(tmp_path: Path) -> None:
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=False,
        coordinator_factory=lambda _config: None,
        clock=Clock(),
    )
    await asyncio.gather(supervisor.stop(), supervisor.stop())


def test_h2_and_h3_kernel_locks_are_independent(tmp_path: Path) -> None:
    h2 = try_acquire_lock(".report-locks/coordinator.lock", lock_dir=tmp_path)
    assert h2 is not None
    try:
        h3 = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        assert h3 is not None
        try:
            assert try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path) is None
        finally:
            release_lock(h3, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    finally:
        release_lock(h2, ".report-locks/coordinator.lock", unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_runnable_leader_starts_one_runtime_and_stop_releases_lock(
    tmp_path: Path,
) -> None:
    coordinator = Coordinator()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        if coordinator.started:
            break
        await asyncio.sleep(0.001)
    assert coordinator.started == 1
    assert try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path) is None
    await supervisor.stop()
    await task
    assert coordinator.stopped == 1
    assert load_periodic_state(tmp_path).payload["health"]["status"] == "stopped"
    fd = None
    for _ in _settle_attempts():
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_stop_after_start_before_monitor_is_orderly_and_single_stop(
    tmp_path: Path,
) -> None:
    class PausedAfterStartSupervisor(PeriodicPngSupervisor):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.after_start = asyncio.Event()
            self.release_start_result = asyncio.Event()
            self.coordinator_cleared = asyncio.Event()

        async def _try_construct_and_start(self, config) -> bool:
            result = await super()._try_construct_and_start(config)
            self.after_start.set()
            await self.release_start_result.wait()
            return result

        async def _stop_coordinator(self) -> None:
            await super()._stop_coordinator()
            self.coordinator_cleared.set()

    coordinator = Coordinator()
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return coordinator

    supervisor = PausedAfterStartSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    run_task = asyncio.create_task(supervisor.run())
    await supervisor.after_start.wait()
    stop_task = asyncio.create_task(supervisor.stop())
    await supervisor.coordinator_cleared.wait()
    assert coordinator.stopped == 1
    assert supervisor._coordinator is None
    supervisor.release_start_result.set()
    await stop_task
    await run_task

    assert factory_calls == 1
    assert coordinator.started == coordinator.stopped == 1
    assert load_periodic_state(tmp_path).payload["health"]["status"] == "stopped"
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_stop_during_refreshed_config_load_is_orderly_and_single_stop(
    tmp_path: Path,
) -> None:
    class TrackingSupervisor(PeriodicPngSupervisor):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.coordinator_cleared = asyncio.Event()

        async def _stop_coordinator(self) -> None:
            await super()._stop_coordinator()
            self.coordinator_cleared.set()

    class OnePollClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.sleeps = 0

        async def sleep(self, _seconds: float) -> None:
            self.sleeps += 1
            if self.sleeps == 1:
                return
            await asyncio.Event().wait()

    coordinator = Coordinator()
    factory_calls = 0
    load_calls = 0
    refresh_entered = asyncio.Event()
    release_refresh = asyncio.Event()

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return coordinator

    def loader(_path: Path) -> PeriodicPngConfigLoad:
        return _runnable_load()

    async def controlled_blocking(fn, *args, **kwargs):
        nonlocal load_calls
        if fn is loader:
            load_calls += 1
            if load_calls == 3:
                refresh_entered.set()
                await release_refresh.wait()
        return fn(*args, **kwargs)

    supervisor = TrackingSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=loader,
        clock=OnePollClock(),
        run_blocking=controlled_blocking,
    )
    run_task = asyncio.create_task(supervisor.run())
    await refresh_entered.wait()
    stop_task = asyncio.create_task(supervisor.stop())
    await supervisor.coordinator_cleared.wait()
    assert coordinator.stopped == 1
    assert supervisor._coordinator is None
    release_refresh.set()
    await stop_task
    await run_task

    assert load_calls == 3
    assert factory_calls == 1
    assert coordinator.started == coordinator.stopped == 1
    assert load_periodic_state(tmp_path).payload["health"]["status"] == "stopped"
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_unexplained_coordinator_disappearance_is_degraded_not_orderly(
    tmp_path: Path,
) -> None:
    class DisappearingSupervisor(PeriodicPngSupervisor):
        async def _monitor_iteration(self) -> str:
            coordinator = self._coordinator
            assert coordinator is not None
            await coordinator.stop()
            self._coordinator = None
            return "poll", None

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    coordinator = Coordinator()
    clock = BackoffClock()
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return coordinator

    supervisor = DisappearingSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    run_task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert health["error_code"] == "periodic_runtime_failed"
    assert factory_calls == 1
    assert coordinator.started == coordinator.stopped == 1
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)

    await supervisor.stop()
    await run_task


@pytest.mark.asyncio
async def test_invalid_requested_config_writes_redacted_health_without_runtime(
    tmp_path: Path,
) -> None:
    made = 0

    def factory(_config):
        nonlocal made
        made += 1
        raise AssertionError

    invalid = PeriodicPngConfigLoad(
        selected_path=tmp_path / "notifications.yaml",
        requested=True,
        runnable=False,
        config=None,
        error_code="invalid_bot_token",
        error_text="must not be copied",
    )
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=lambda _path: invalid,
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        state = load_periodic_state(tmp_path).payload
        if state["health"]["status"] == "degraded_config":
            break
        await asyncio.sleep(0.001)
    state = load_periodic_state(tmp_path).payload
    assert state["health"] == {
        "status": "degraded_config",
        "error_code": "invalid_bot_token",
        "error_text": "periodic configuration is invalid",
        "updated_at": 119.0,
    }
    assert made == 0
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_startup_cancellation_cleans_up_releases_leader_and_propagates(
    tmp_path: Path,
) -> None:
    class BlockingStart(Coordinator):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def start(self) -> None:
            self.started += 1
            self.entered.set()
            await self.release.wait()

        async def stop(self) -> None:
            self.stopped += 1
            self.release.set()
            self.done.set()

    coordinator = BlockingStart()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    await coordinator.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert coordinator.stopped == 1
    fd = None
    for _ in _settle_attempts():
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_process_level_critical_failure_is_not_restarted_or_swallowed(
    tmp_path: Path,
) -> None:
    class ProcessLevelFailure(BaseException):
        pass

    class FatalCoordinator(Coordinator):
        async def wait(self) -> None:
            raise ProcessLevelFailure("fatal critical task")

    coordinator = FatalCoordinator()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    with pytest.raises(ProcessLevelFailure, match="fatal critical task"):
        await supervisor.run()
    assert coordinator.started == 1
    assert coordinator.stopped == 1
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_initial_factory_failure_marks_nonready_before_release_and_backoff(
    tmp_path: Path,
) -> None:
    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: (_ for _ in ()).throw(RuntimeError("factory failed")),
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert load_periodic_state(tmp_path).payload["health"]["status"] == ("degraded_runtime")
    fd = None
    for _ in _settle_attempts():
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_initial_engine_absence_has_exact_allowed_idle_health(
    tmp_path: Path,
) -> None:
    class NoEngine(Coordinator):
        async def start(self) -> None:
            self.started += 1
            raise PeriodicSourceUnavailable("no engine authority")

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    coordinator = NoEngine()
    clock = BackoffClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()

    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_source"
    assert health["error_code"] == "periodic_engine_unavailable"
    assert health["error_text"] == "periodic engine authority is unavailable"
    assert coordinator.stopped == 1
    degraded_updated_at = health["updated_at"]

    await supervisor.stop()
    await task
    stopped = load_periodic_state(tmp_path).payload["health"]
    assert stopped["status"] == "stopped"
    assert stopped["error_code"] == "periodic_stopped"
    assert stopped["error_text"] == "periodic runtime is stopped"
    assert stopped["updated_at"] > degraded_updated_at


@pytest.mark.asyncio
async def test_idle_stop_does_not_overwrite_a_new_active_owner(tmp_path: Path) -> None:
    class NoEngine(Coordinator):
        async def start(self) -> None:
            self.started += 1
            raise PeriodicSourceUnavailable("no engine authority")

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: NoEngine(),
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert load_periodic_state(tmp_path).payload["health"]["status"] == ("degraded_source")

    incumbent = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert incumbent is not None
    try:
        state = load_periodic_state(tmp_path)
        ready = set_periodic_health(
            state,
            status="ready",
            code=None,
            text="",
            now=200.0,
        )
        write_periodic_state(tmp_path, ready)
        await supervisor.stop()
        await task
        assert load_periodic_state(tmp_path).payload["health"] == {
            "status": "ready",
            "error_code": None,
            "error_text": "",
            "updated_at": 200.0,
        }
    finally:
        release_lock(
            incumbent,
            PERIODIC_LEADER_LOCK,
            unlink=False,
            lock_dir=tmp_path,
        )


@pytest.mark.asyncio
async def test_idle_stop_does_not_overwrite_newer_released_owner_health(
    tmp_path: Path,
) -> None:
    class NoEngine(Coordinator):
        async def start(self) -> None:
            self.started += 1
            raise PeriodicSourceUnavailable("no engine authority")

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: NoEngine(),
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert load_periodic_state(tmp_path).payload["health"]["status"] == ("degraded_source")

    newer_owner = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert newer_owner is not None
    state = load_periodic_state(tmp_path)
    ready = set_periodic_health(
        state,
        status="ready",
        code=None,
        text="",
        now=200.0,
    )
    write_periodic_state(tmp_path, ready)
    release_lock(
        newer_owner,
        PERIODIC_LEADER_LOCK,
        unlink=False,
        lock_dir=tmp_path,
    )

    await supervisor.stop()
    await task
    assert load_periodic_state(tmp_path).payload == ready.payload


@pytest.mark.asyncio
async def test_critical_runtime_failure_marks_nonready_before_re_election(
    tmp_path: Path,
) -> None:
    class FailedCoordinator(Coordinator):
        async def wait(self) -> None:
            raise ValueError("sqlite write exploded")

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    coordinator = FailedCoordinator()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        if (await _load_stable(tmp_path)).payload["health"]["status"] == "degraded_runtime":
            break
        await asyncio.sleep(0.001)
    health = (await _load_stable(tmp_path)).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert "ValueError" in health["error_text"]
    assert "sqlite write exploded" in health["error_text"]
    fd = None
    for _ in _settle_attempts():
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_live_source_failure_preserves_health_and_logs_real_cause_before_re_election(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailedLiveSourceCoordinator(Coordinator):
        async def wait(self) -> None:
            state = load_periodic_state(tmp_path)
            write_periodic_state(
                tmp_path,
                set_periodic_health(
                    state,
                    status="degraded_source",
                    code="periodic_live_source_stopped",
                    text="periodic live source stopped unexpectedly",
                    now=1.0,
                ),
            )
            raise ValueError("ZMQ subscription socket died")

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    coordinator = FailedLiveSourceCoordinator()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    with caplog.at_level(logging.ERROR, logger="cryodaq.agents.assistant.periodic_png"):
        task = asyncio.create_task(supervisor.run())
        for _ in _settle_attempts():
            health = (await _load_stable(tmp_path)).payload["health"]
            messages = [record.getMessage() for record in caplog.records]
            if health["error_code"] == "periodic_live_source_stopped" and any(
                "ValueError" in message and "ZMQ subscription socket died" in message for message in messages
            ):
                break
            await asyncio.sleep(0.001)

    health = (await _load_stable(tmp_path)).payload["health"]
    assert health["error_code"] == "periodic_live_source_stopped"
    assert health["error_text"] == "periodic live source stopped unexpectedly"
    assert any("ValueError" in message and "ZMQ subscription socket died" in message for message in messages)
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_cancelled_leader_acquisition_releases_late_fd(tmp_path: Path) -> None:
    acquired = asyncio.Event()
    release_result = asyncio.Event()

    async def paused_blocking(fn, *args, **kwargs):
        value = fn(*args, **kwargs)
        if fn is try_acquire_lock and args[0] == PERIODIC_LEADER_LOCK:
            acquired.set()
            await release_result.wait()
        return value

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: Coordinator(),
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
        run_blocking=paused_blocking,
    )
    task = asyncio.create_task(supervisor.run())
    await acquired.wait()
    task.cancel()
    release_result.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_cancelled_failure_writer_settles_before_leader_release(
    tmp_path: Path,
) -> None:
    first_write_entered = asyncio.Event()
    release_first_write = asyncio.Event()
    detached_writes: list[asyncio.Task[None]] = []
    write_calls = 0

    async def executor_like_blocking(fn, *args, **kwargs):
        nonlocal write_calls
        if fn is write_periodic_state:
            write_calls += 1
            if write_calls == 1:

                async def delayed_side_effect() -> None:
                    first_write_entered.set()
                    await release_first_write.wait()
                    fn(*args, **kwargs)

                worker = asyncio.create_task(delayed_side_effect())
                try:
                    return await asyncio.shield(worker)
                except asyncio.CancelledError:
                    detached_writes.append(worker)
                    raise
        return fn(*args, **kwargs)

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: Coordinator(),
        config_loader=lambda _path: (_ for _ in ()).throw(RuntimeError("loader failed")),
        clock=Clock(),
        run_blocking=executor_like_blocking,
    )
    run_task = asyncio.create_task(supervisor.run())
    await first_write_entered.wait()
    run_task.cancel()
    await asyncio.sleep(0)

    competing_owner = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    escaped_before_settlement = competing_owner is not None
    try:
        assert not run_task.done()
        assert competing_owner is None
    finally:
        release_first_write.set()
        await asyncio.gather(*detached_writes, return_exceptions=True)
        if competing_owner is not None:
            release_lock(
                competing_owner,
                PERIODIC_LEADER_LOCK,
                unlink=False,
                lock_dir=tmp_path,
            )
        with pytest.raises(asyncio.CancelledError):
            await run_task

    assert not escaped_before_settlement
    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "stopped"
    settled_owner = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert settled_owner is not None
    release_lock(settled_owner, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_reload_factory_failure_replaces_prior_ready_with_nonready(
    tmp_path: Path,
) -> None:
    first = _config()
    second = replace(first, telegram_chat_id=2)
    state = load_periodic_state(tmp_path)
    ready = set_periodic_health(state, status="ready", code=None, text="", now=1.0)
    write_periodic_state(tmp_path, ready)
    loads = 0

    def loader(_path: Path):
        nonlocal loads
        loads += 1
        config = first if loads <= 2 else second
        return replace(_runnable_load(), config=config)

    class PollClock(Clock):
        def __init__(self) -> None:
            super().__init__(2.0)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await self.release.wait()
            self.release.clear()

    clock = PollClock()
    original = Coordinator()
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            return original
        raise RuntimeError("replacement factory failed")

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=loader,
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    clock.entered.clear()
    clock.release.set()
    for _ in _settle_attempts():
        if (await _load_stable(tmp_path)).payload["health"]["status"] == "degraded_runtime":
            break
        await asyncio.sleep(0.001)
    assert (await _load_stable(tmp_path)).payload["health"]["status"] == ("degraded_runtime")
    assert original.stopped == 1
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_repeated_supervisor_cancellation_settles_nonready_before_release(
    tmp_path: Path,
) -> None:
    class BlockingStopCoordinator(Coordinator):
        def __init__(self) -> None:
            super().__init__()
            self.stop_entered = asyncio.Event()
            self.stop_release = asyncio.Event()

        async def stop(self) -> None:
            self.stopped += 1
            self.stop_entered.set()
            await self.stop_release.wait()
            self.done.set()

    coordinator = BlockingStopCoordinator()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        if coordinator.started:
            break
        await asyncio.sleep(0.001)
    task.cancel()
    await coordinator.stop_entered.wait()
    task.cancel()
    coordinator.stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert coordinator.stopped == 1
    assert load_periodic_state(tmp_path).payload["health"]["status"] == "stopped"
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_cancelled_initial_config_load_does_not_latch_run_task(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    calls = 0
    blocked_once = False

    def loader(_path: Path):
        nonlocal calls
        calls += 1
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=False,
            runnable=False,
            config=None,
            error_code=None,
            error_text="",
        )

    async def blocking(fn, *args, **kwargs):
        nonlocal blocked_once
        if fn is loader and not blocked_once:
            blocked_once = True
            entered.set()
            await asyncio.Event().wait()
        return fn(*args, **kwargs)

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: Coordinator(),
        config_loader=loader,
        clock=Clock(),
        run_blocking=blocking,
    )
    first = asyncio.create_task(supervisor.run())
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        if calls == 1:
            break
        await asyncio.sleep(0.001)
    assert calls == 1
    assert not (tmp_path / ".report-locks").exists()
    assert not second.done()
    await supervisor.stop()
    await second


@pytest.mark.asyncio
async def test_raising_config_loader_backs_off_then_recovers_to_idle(
    tmp_path: Path,
) -> None:
    calls = 0
    made = 0

    def loader(_path: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("config loader failed")
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=False,
            runnable=False,
            config=None,
            error_code=None,
            error_text="",
        )

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await self.release.wait()
            self.release.clear()

    def factory(_config):
        nonlocal made
        made += 1
        raise AssertionError

    clock = BackoffClock()

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=loader,
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert calls == 1
    assert made == 0
    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "degraded_runtime"
    assert health["error_code"] == "periodic_runtime_failed"
    assert "RuntimeError" in health["error_text"]
    assert "config loader failed" in health["error_text"]
    assert (tmp_path / ".report-locks").exists()
    assert (tmp_path / "reporting").exists()
    fault_receipt_owner = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fault_receipt_owner is not None
    release_lock(fault_receipt_owner, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    assert not task.done()
    clock.entered.clear()
    clock.release.set()
    for _ in _settle_attempts():
        if calls == 2:
            break
        await asyncio.sleep(0.001)
    assert calls == 2
    assert not task.done()
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_loader_failure_then_unrequested_replaces_owned_receipt_with_disabled(
    tmp_path: Path,
) -> None:
    calls = 0

    def loader(_path: Path) -> PeriodicPngConfigLoad:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient loader failure")
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=False,
            runnable=False,
            config=None,
            error_code=None,
            error_text="",
        )

    class FailureThenDisabledClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.sleeps = 0
            self.disabled_sleep = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.sleeps += 1
            if self.sleeps == 1:
                return
            self.disabled_sleep.set()
            await asyncio.Event().wait()

    async def direct_blocking(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    clock = FailureThenDisabledClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: pytest.fail("factory must not run"),
        config_loader=loader,
        clock=clock,
        run_blocking=direct_blocking,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.disabled_sleep.wait()

    assert calls == 2
    health = load_periodic_state(tmp_path).payload["health"]
    assert health["status"] == "disabled"
    assert health["error_code"] == "periodic_disabled"
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)

    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_stop_cleanup_error_still_persists_nonready_before_release(
    tmp_path: Path,
) -> None:
    class StopRaises(Coordinator):
        async def stop(self) -> None:
            self.stopped += 1
            self.done.set()
            raise RuntimeError("close failed after cleanup")

    coordinator = StopRaises()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: coordinator,
        config_loader=lambda _path: _runnable_load(),
        clock=Clock(),
    )
    task = asyncio.create_task(supervisor.run())
    for _ in _settle_attempts():
        if coordinator.started:
            break
        await asyncio.sleep(0.001)
    with pytest.raises(RuntimeError, match="close failed after cleanup"):
        await supervisor.stop()
    await task
    assert load_periodic_state(tmp_path).payload["health"]["status"] == "stopped"
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_invalid_config_with_corrupt_state_releases_leader_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    reporting = tmp_path / "reporting"
    reporting.mkdir()
    path = reporting / "periodic_state.json"
    raw = b'{"schema":1,"broken":true}\n'
    path.write_bytes(raw)
    invalid = PeriodicPngConfigLoad(
        selected_path=tmp_path / "notifications.yaml",
        requested=True,
        runnable=False,
        config=None,
        error_code="invalid_bot_token",
        error_text="redacted",
    )

    class BackoffClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await asyncio.Event().wait()

    clock = BackoffClock()
    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=lambda _config: Coordinator(),
        config_loader=lambda _path: invalid,
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    assert path.read_bytes() == raw
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_unrequested_requested_cycle_stays_alive_without_host_restart(
    tmp_path: Path,
) -> None:
    requested = False

    def loader(_path: Path) -> PeriodicPngConfigLoad:
        if requested:
            return _runnable_load()
        return PeriodicPngConfigLoad(
            selected_path=None,
            requested=False,
            runnable=False,
            config=None,
            error_code=None,
            error_text="",
        )

    class PulseClock(Clock):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.entered.set()
            await self.release.wait()
            self.release.clear()

        def pulse(self) -> None:
            self.entered.clear()
            self.release.set()

    clock = PulseClock()
    coordinators: list[Coordinator] = []

    def factory(_config):
        coordinator = Coordinator()
        coordinators.append(coordinator)
        return coordinator

    supervisor = PeriodicPngSupervisor(
        data_dir=tmp_path,
        config_dir=tmp_path,
        periodic_allowed=True,
        coordinator_factory=factory,
        config_loader=loader,
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert coordinators == []
    assert not (tmp_path / ".report-locks").exists()
    assert not (tmp_path / "reporting").exists()

    requested = True
    clock.pulse()
    for _ in _settle_attempts():
        if len(coordinators) == 1 and coordinators[0].started == 1:
            break
        await asyncio.sleep(0.001)
    assert len(coordinators) == 1
    await clock.entered.wait()

    requested = False
    clock.pulse()
    async with asyncio.timeout(5):
        while True:
            state = await _load_stable(tmp_path)
            if state.payload["health"]["status"] == "disabled":
                break
            await asyncio.sleep(0)
    assert coordinators[0].stopped == 1
    assert state.payload["health"]["status"] == "disabled"
    fd = None
    for _ in _settle_attempts():
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await clock.entered.wait()

    requested = True
    clock.pulse()
    for _ in _settle_attempts():
        if len(coordinators) == 2 and coordinators[1].started == 1:
            break
        await asyncio.sleep(0.001)
    assert len(coordinators) == 2
    assert coordinators[1].started == 1
    assert not task.done()
    await supervisor.stop()
    await task
    assert coordinators[1].stopped == 1
