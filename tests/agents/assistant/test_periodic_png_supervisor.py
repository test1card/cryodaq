from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_png import PeriodicPngSupervisor
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


async def _load_stable(data_dir: Path):
    last_error: PeriodicContractError | None = None
    for _ in range(100):
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
        for _ in range(100):
            if task.done():
                break
            await asyncio.sleep(0.001)
        assert not task.done()
        assert made == 0
        assert not (tmp_path / "reporting").exists()
        await supervisor.stop()
        await task
    finally:
        release_lock(
            incumbent, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path
        )


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
        release_lock(
            h2, ".report-locks/coordinator.lock", unlink=False, lock_dir=tmp_path
        )


@pytest.mark.asyncio
async def test_runnable_leader_starts_one_runtime_and_stop_releases_lock(tmp_path: Path) -> None:
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
    for _ in range(100):
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
    for _ in range(100):
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)


@pytest.mark.asyncio
async def test_invalid_requested_config_writes_redacted_health_without_runtime(tmp_path: Path) -> None:
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
    for _ in range(100):
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
    for _ in range(100):
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
        coordinator_factory=lambda _config: (_ for _ in ()).throw(
            RuntimeError("factory failed")
        ),
        config_loader=lambda _path: _runnable_load(),
        clock=clock,
    )
    task = asyncio.create_task(supervisor.run())
    await clock.entered.wait()
    assert load_periodic_state(tmp_path).payload["health"]["status"] == (
        "degraded_runtime"
    )
    fd = None
    for _ in range(100):
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await supervisor.stop()
    await task


@pytest.mark.asyncio
async def test_critical_runtime_failure_marks_nonready_before_re_election(
    tmp_path: Path,
) -> None:
    class FailedCoordinator(Coordinator):
        async def wait(self) -> None:
            raise RuntimeError("critical loop failed")

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
    for _ in range(100):
        if (
            (await _load_stable(tmp_path)).payload["health"]["status"]
            == "degraded_runtime"
        ):
            break
        await asyncio.sleep(0.001)
    assert (await _load_stable(tmp_path)).payload["health"]["status"] == (
        "degraded_runtime"
    )
    fd = None
    for _ in range(100):
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
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
async def test_reload_factory_failure_replaces_prior_ready_with_nonready(
    tmp_path: Path,
) -> None:
    first = _config()
    second = replace(first, telegram_chat_id=2)
    state = load_periodic_state(tmp_path)
    ready = set_periodic_health(
        state, status="ready", code=None, text="", now=1.0
    )
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
    for _ in range(100):
        if (
            (await _load_stable(tmp_path)).payload["health"]["status"]
            == "degraded_runtime"
        ):
            break
        await asyncio.sleep(0.001)
    assert (await _load_stable(tmp_path)).payload["health"]["status"] == (
        "degraded_runtime"
    )
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
    for _ in range(100):
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
    for _ in range(100):
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
    assert not (tmp_path / ".report-locks").exists()
    assert not (tmp_path / "reporting").exists()
    assert not task.done()
    clock.entered.clear()
    clock.release.set()
    for _ in range(100):
        if calls == 2:
            break
        await asyncio.sleep(0.001)
    assert calls == 2
    assert not task.done()
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
    for _ in range(100):
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
    for _ in range(100):
        if len(coordinators) == 1 and coordinators[0].started == 1:
            break
        await asyncio.sleep(0.001)
    assert len(coordinators) == 1
    await clock.entered.wait()

    requested = False
    clock.pulse()
    for _ in range(100):
        if coordinators[0].stopped == 1:
            break
        await asyncio.sleep(0.001)
    assert coordinators[0].stopped == 1
    assert (await _load_stable(tmp_path)).payload["health"]["status"] == "disabled"
    fd = None
    for _ in range(100):
        fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=tmp_path)
        if fd is not None:
            break
        await asyncio.sleep(0.001)
    assert fd is not None
    release_lock(fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=tmp_path)
    await clock.entered.wait()

    requested = True
    clock.pulse()
    for _ in range(100):
        if len(coordinators) == 2 and coordinators[1].started == 1:
            break
        await asyncio.sleep(0.001)
    assert len(coordinators) == 2
    assert coordinators[1].started == 1
    assert not task.done()
    await supervisor.stop()
    await task
    assert coordinators[1].stopped == 1
