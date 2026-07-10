from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_png import (
    AlarmQueryResult,
    LiveSourceCut,
    PeriodicPngCoordinator,
)
from cryodaq.agents.assistant.periodic_telegram import (
    TelegramDeliveryResult,
    TelegramOutcome,
)
from cryodaq.drivers.base import Reading
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.periodic_state import PeriodicArtifact, load_periodic_state
from cryodaq.report_process import PeriodicRenderResult
from cryodaq.storage.archive_reader import BoundedReadingQueryResult, BoundedReadingRow


def _config() -> PeriodicPngConfig:
    return PeriodicPngConfig(
        enabled=True,
        interval_s=60,
        chart_window_s=120,
        include_channels=None,
        max_points_per_channel=100,
        max_total_points=200,
        max_input_bytes=65_536,
        render_timeout_s=5.0,
        max_render_attempts=2,
        max_delivery_attempts=2,
        backoff_base_s=1.0,
        backoff_cap_s=8.0,
        telegram_token=SecretStr("123456:abcdefghijklmnopqrstuvwxyz"),
        telegram_chat_id=1,
        telegram_timeout_s=2.0,
        telegram_verify_ssl=True,
        config_fingerprint="sha256:" + "c" * 64,
    )


class Clock:
    def __init__(self, wall: float = 119.0) -> None:
        self.wall = wall
        self.mono = 0.0
        self.display_calls = 0

    def wall_time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def display_time(self, epoch: int) -> str:
        self.display_calls += 1
        return datetime.fromtimestamp(epoch).strftime("%d.%m.%Y %H:%M")

    async def sleep(self, _seconds: float) -> None:
        await asyncio.Event().wait()


def _cut(sequence: int, *, revision: int = 1, token: str | None = None) -> LiveSourceCut:
    return LiveSourceCut(
        session_id="a" * 32,
        generation=1,
        sequence=sequence,
        published_at=120.0 + sequence,
        reading_drop_count=0,
        publish_failure_count=0,
        alarm_state_revision=revision,
        alarm_state_token=token or "sha256:" + "d" * 64,
    )


class Live:
    def __init__(self) -> None:
        self.steps: list[str] = []
        self.cuts = [_cut(1), _cut(2), _cut(3), _cut(4)]
        self.on_reading = None
        self.on_event = None
        self.stopped = 0
        self._wait = asyncio.Event()

    async def start(self, on_reading, on_event) -> None:
        self.steps.append("start")
        self.on_reading = on_reading
        self.on_event = on_event

    async def ready(self) -> LiveSourceCut:
        self.steps.append("ready")
        return self.cuts.pop(0) if self.cuts else _cut(10)

    def complete_since(self, _cut_value: LiveSourceCut) -> bool:
        return True

    async def wait(self) -> None:
        await self._wait.wait()

    async def stop(self) -> None:
        self.stopped += 1
        self._wait.set()


class Alarm:
    def __init__(self) -> None:
        self.closed = 0

    async def snapshot(self) -> AlarmQueryResult:
        return AlarmQueryResult(
            ok=True,
            payload={"ok": True, "active": {}},
            state_token="sha256:" + "d" * 64,
            state_revision=1,
            error_code=None,
        )

    async def close(self) -> None:
        self.closed += 1


class Archive:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs) -> BoundedReadingQueryResult:
        self.calls.append(kwargs)
        return BoundedReadingQueryResult(
            rows=(BoundedReadingRow(50.0, "ls", "T", 1.0, "K", "ok"),),
            complete=True,
            truncated=False,
            issues=(),
            issue_overflow=0,
            discovered_channels=("T",),
            rows_examined=1,
            rows_dropped_by_caps=0,
            retained_encoded_bytes=32,
        )


class Runner:
    def recover_periodic(self, *_args, **_kwargs):
        return None

    def generate_periodic(self, *_args, **_kwargs) -> PeriodicRenderResult:
        raise AssertionError("not due in startup test")


class Telegram:
    def __init__(self) -> None:
        self.closed = 0

    async def send_photo(self, _photo: bytes, _caption: str) -> TelegramDeliveryResult:
        return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 1, 200, None, None, "")

    async def close(self) -> None:
        self.closed += 1


class SuccessfulRunner:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.statuses: list[str] = []

    def recover_periodic(self, *_args, **_kwargs):
        return None

    def generate_periodic(self, generation_id: str, **_kwargs) -> PeriodicRenderResult:
        active = load_periodic_state(self.data_dir).payload["active"]
        self.statuses.append(active["status"])
        return PeriodicRenderResult(
            generation_id=generation_id,
            owner_token=active["owner_token"],
            slot_id=active["slot_id"],
            config_fingerprint=active["config_fingerprint"],
            artifact=PeriodicArtifact(
                f"periodic/generations/{generation_id}/periodic.png",
                "sha256:" + "9" * 64,
                100,
                100,
                100,
                "image/png",
            ),
            caption="frozen caption",
        )


@pytest.mark.asyncio
async def test_start_uses_repeatable_barriers_before_hydration_and_alarm_truth(tmp_path: Path) -> None:
    live = Live()
    archive = Archive()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=archive,
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(),
    )

    await coordinator.start()
    try:
        assert live.steps[:4] == ["start", "ready", "ready", "ready"]
        assert archive.calls
        assert load_periodic_state(tmp_path).payload["high_water_slot_end"] is None
    finally:
        await coordinator.stop()


def test_live_cut_and_alarm_result_reject_ambiguous_evidence() -> None:
    with pytest.raises(ValueError):
        _cut(1, token="bad")
    with pytest.raises(ValueError):
        AlarmQueryResult(True, {"ok": True, "active": {}}, None, 1, None)


def test_constructor_requires_every_external_authority(tmp_path: Path) -> None:
    kwargs = dict(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(),
    )
    for field in ("live_sources", "alarm_query", "archive_query", "runner", "telegram"):
        broken = dict(kwargs)
        broken[field] = None
        with pytest.raises((TypeError, ValueError)):
            PeriodicPngCoordinator(**broken)


@pytest.mark.asyncio
async def test_hydration_live_overlap_uses_exact_identity_and_live_priority(tmp_path: Path) -> None:
    live = Live()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(),
    )
    await coordinator.start()
    try:
        assert live.on_reading is not None
        live.on_reading(
            Reading(
                timestamp=datetime.fromtimestamp(50.0, UTC),
                instrument_id="ls",
                channel="T",
                value=99.0,
                unit="mK",
            )
        )
        rows = coordinator.projection_snapshot(window_start=0.0, window_end=100.0).readings
        assert len(rows) == 1
        assert rows[0].value == 99.0
        assert rows[0].unit == "mK"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_success_path_preserves_durable_side_effect_order(tmp_path: Path) -> None:
    clock = Clock(239.0)
    live = Live()
    runner = SuccessfulRunner(tmp_path)
    observed: list[tuple[str, str]] = []

    def artifact_reader(data_dir: Path, _artifact: PeriodicArtifact) -> bytes:
        observed.append(("read", load_periodic_state(data_dir).payload["active"]["status"]))
        return b"authorized-png"

    class SuccessTelegram(Telegram):
        async def send_photo(self, photo: bytes, caption: str) -> TelegramDeliveryResult:
            observed.append(
                ("send", load_periodic_state(tmp_path).payload["active"]["status"])
            )
            assert photo == b"authorized-png"
            assert caption == "frozen caption"
            return TelegramDeliveryResult(
                TelegramOutcome.ACCEPTED, 77, 200, None, None, ""
            )

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=runner,
        telegram=SuccessTelegram(),
        artifact_reader=artifact_reader,
        clock=clock,
        generation_factory=lambda: "4" * 32,
        owner_factory=lambda: "5" * 32,
    )
    await coordinator.start()
    try:
        assert live.on_reading is not None
        live.on_reading(
            Reading(
                timestamp=datetime.fromtimestamp(100.0, UTC),
                instrument_id="ls",
                channel="T",
                value=2.0,
                unit="K",
            )
        )
        await coordinator.reconcile_once()
        for _ in range(20):
            state = load_periodic_state(tmp_path).payload
            if state["last_terminal"] is not None:
                break
            await asyncio.sleep(0.01)
        state = load_periodic_state(tmp_path).payload
        assert state["last_terminal"] is not None, {
            key: state["active"][key]
            for key in (
                "status",
                "failure_phase",
                "error_code",
                "error_text",
                "render_attempt_count",
            )
        }
        assert state["last_terminal"]["status"] == "SUCCEEDED"
        assert runner.statuses == ["RENDERING"]
        assert observed == [("read", "READY"), ("send", "DELIVERING")]
        assert clock.display_calls == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_live_source_normal_return_is_critical(tmp_path: Path) -> None:
    live = Live()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await coordinator.start()
    live._wait.set()
    with pytest.raises(RuntimeError, match="live source|critical task"):
        await coordinator.wait()
    assert load_periodic_state(tmp_path).payload["health"]["status"] == (
        "degraded_source"
    )
    await coordinator.stop()


@pytest.mark.asyncio
async def test_disabled_tls_is_visible_as_degraded_health(tmp_path: Path) -> None:
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=replace(_config(), telegram_verify_ssl=False),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await coordinator.start()
    try:
        assert load_periodic_state(tmp_path).payload["health"] == {
            "status": "degraded_tls",
            "error_code": "periodic_tls_verification_disabled",
            "error_text": "periodic Telegram TLS verification is disabled",
            "updated_at": 1.0,
        }
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_hydration_failure_remains_honestly_incomplete(tmp_path: Path) -> None:
    def failed_archive(**_kwargs):
        raise OSError("archive unavailable")

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=failed_archive,
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await coordinator.start()
    try:
        snapshot = coordinator.projection_snapshot(window_start=-120.0, window_end=0.0)
        assert snapshot.history_complete is False
        assert load_periodic_state(tmp_path).payload["health"] == {
            "status": "degraded_projection",
            "error_code": "periodic_projection_incomplete",
            "error_text": "periodic projection evidence is incomplete",
            "updated_at": 1.0,
        }
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_alarm_revision_mismatch_remains_honestly_incomplete(tmp_path: Path) -> None:
    class NonBlockingClock(Clock):
        async def sleep(self, _seconds: float) -> None:
            await asyncio.sleep(0)

    class MismatchedAlarm(Alarm):
        async def snapshot(self) -> AlarmQueryResult:
            return AlarmQueryResult(
                ok=True,
                payload={"ok": True, "active": {}},
                state_token="sha256:" + "e" * 64,
                state_revision=2,
                error_code=None,
            )

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=MismatchedAlarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=NonBlockingClock(1.0),
    )
    await coordinator.start()
    try:
        snapshot = coordinator.projection_snapshot(window_start=-120.0, window_end=0.0)
        assert snapshot.alarm_state_complete is False
        assert load_periodic_state(tmp_path).payload["health"]["status"] == (
            "degraded_projection"
        )
    finally:
        await coordinator.stop()


class _AlarmRevisionFive(Alarm):
    async def snapshot(self) -> AlarmQueryResult:
        return AlarmQueryResult(
            ok=True,
            payload={"ok": True, "active": {}},
            state_token="sha256:" + "d" * 64,
            state_revision=5,
            error_code=None,
        )


@pytest.mark.asyncio
async def test_alarm_trigger_clear_round_trip_accepts_newer_equal_token_seal(
    tmp_path: Path,
) -> None:
    live = Live()
    live.cuts = [
        _cut(1, revision=5),
        _cut(2, revision=5),
        # A trigger and clear occurred after the snapshot: revision advanced
        # twice while the canonical active-alarm token returned to A.
        _cut(3, revision=7),
    ]
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=_AlarmRevisionFive(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await coordinator.start()
    try:
        snapshot = coordinator.projection_snapshot(window_start=1.0, window_end=121.0)
        assert snapshot.alarm_state_complete is True
        assert load_periodic_state(tmp_path).payload["health"]["status"] == "ready"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_alarm_seal_revision_regression_remains_incomplete(tmp_path: Path) -> None:
    class RetryClock(Clock):
        async def sleep(self, seconds: float) -> None:
            if seconds < 1.0:
                await asyncio.sleep(0)
                return
            await asyncio.Event().wait()

    live = Live()
    live.cuts = [
        _cut(1, revision=5),
        _cut(2, revision=5),
        _cut(3, revision=4),
        _cut(4, revision=4),
        _cut(5, revision=4),
    ]
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=_AlarmRevisionFive(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=RetryClock(1.0),
    )
    await coordinator.start()
    try:
        snapshot = coordinator.projection_snapshot(window_start=1.0, window_end=121.0)
        assert snapshot.alarm_state_complete is False
        assert load_periodic_state(tmp_path).payload["health"]["status"] == (
            "degraded_projection"
        )
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_frozen_wall_health_heartbeat_advances_strictly(tmp_path: Path) -> None:
    clock = Clock(1.0)
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=clock,
    )
    await coordinator.start()
    try:
        before = load_periodic_state(tmp_path).payload["health"]["updated_at"]
        clock.mono = 30.0
        assert coordinator._reconcile_lock is not None
        async with coordinator._reconcile_lock:
            await coordinator._refresh_periodic_authority_if_due()
        after = load_periodic_state(tmp_path).payload["health"]["updated_at"]
        assert after > before
        assert clock.wall == 1.0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_heartbeat_rechecks_existing_cuts_without_minting_new_seal(
    tmp_path: Path,
) -> None:
    class MutableCompletenessLive(Live):
        def __init__(self) -> None:
            super().__init__()
            self.complete = True
            self.ready_calls = 0

        async def ready(self) -> LiveSourceCut:
            self.ready_calls += 1
            return await super().ready()

        def complete_since(self, _cut_value: LiveSourceCut) -> bool:
            return self.complete

    clock = Clock(1.0)
    live = MutableCompletenessLive()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=clock,
    )
    await coordinator.start()
    try:
        ready_calls = live.ready_calls
        live.complete = False
        clock.mono = 30.0
        assert coordinator._reconcile_lock is not None
        async with coordinator._reconcile_lock:
            await coordinator._refresh_periodic_authority_if_due()
        assert live.ready_calls == ready_calls
        assert load_periodic_state(tmp_path).payload["health"]["status"] == (
            "degraded_projection"
        )
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_alarm_authority_resnapshots_only_at_240_seconds(tmp_path: Path) -> None:
    class CountingAlarm(Alarm):
        def __init__(self) -> None:
            super().__init__()
            self.snapshots = 0

        async def snapshot(self) -> AlarmQueryResult:
            self.snapshots += 1
            return await super().snapshot()

    clock = Clock(1.0)
    alarm = CountingAlarm()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=alarm,
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=clock,
    )
    await coordinator.start()
    try:
        assert alarm.snapshots == 1
        clock.mono = 239.0
        assert coordinator._reconcile_lock is not None
        async with coordinator._reconcile_lock:
            await coordinator._refresh_periodic_authority_if_due()
        assert alarm.snapshots == 1
        clock.mono = 240.0
        async with coordinator._reconcile_lock:
            await coordinator._refresh_periodic_authority_if_due()
        assert alarm.snapshots == 2
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_fresh_source_graph_replaces_prior_degraded_source_with_newer_ready(
    tmp_path: Path,
) -> None:
    first_live = Live()
    first = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=first_live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await first.start()
    first_live._wait.set()
    with pytest.raises(RuntimeError):
        await first.wait()
    degraded = load_periodic_state(tmp_path).payload["health"]
    assert degraded["status"] == "degraded_source"
    await first.stop()

    second = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(1.0),
    )
    await second.start()
    try:
        recovered = load_periodic_state(tmp_path).payload["health"]
        assert recovered["status"] == "ready"
        assert recovered["updated_at"] > degraded["updated_at"]
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_stop_attempts_all_cleanup_and_preserves_first_error(tmp_path: Path) -> None:
    class FailingStopLive(Live):
        async def stop(self) -> None:
            self.stopped += 1
            self._wait.set()
            raise RuntimeError("live stop failed")

    class FailingCloseAlarm(Alarm):
        async def close(self) -> None:
            self.closed += 1
            raise ValueError("alarm close failed")

    class FailingCloseTelegram(Telegram):
        async def close(self) -> None:
            self.closed += 1
            raise OSError("telegram close failed")

    live = FailingStopLive()
    alarm = FailingCloseAlarm()
    telegram = FailingCloseTelegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=alarm,
        archive_query=Archive(),
        runner=Runner(),
        telegram=telegram,
        clock=Clock(1.0),
    )
    await coordinator.start()
    with pytest.raises(RuntimeError, match="live stop failed"):
        await coordinator.stop()
    assert live.stopped == 1
    assert alarm.closed == 1
    assert telegram.closed == 1
    with pytest.raises(RuntimeError, match="live stop failed"):
        await coordinator.stop()
    assert (live.stopped, alarm.closed, telegram.closed) == (1, 1, 1)


@pytest.mark.asyncio
async def test_repeated_stop_cancellation_waits_for_shared_cleanup(tmp_path: Path) -> None:
    class BlockingStopLive(Live):
        def __init__(self) -> None:
            super().__init__()
            self.stop_entered = asyncio.Event()
            self.stop_release = asyncio.Event()

        async def stop(self) -> None:
            self.stopped += 1
            self.stop_entered.set()
            await self.stop_release.wait()
            self._wait.set()

    live = BlockingStopLive()
    alarm = Alarm()
    telegram = Telegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=alarm,
        archive_query=Archive(),
        runner=Runner(),
        telegram=telegram,
        clock=Clock(1.0),
    )
    await coordinator.start()
    stop_task = asyncio.create_task(coordinator.stop())
    await live.stop_entered.wait()
    stop_task.cancel()
    await asyncio.sleep(0)
    stop_task.cancel()
    live.stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await stop_task
    assert live.stopped == 1
    assert alarm.closed == 1
    assert telegram.closed == 1


@pytest.mark.asyncio
async def test_repeated_start_cancellation_waits_for_shared_cleanup(tmp_path: Path) -> None:
    class BlockingStartupLive(Live):
        def __init__(self) -> None:
            super().__init__()
            self.ready_entered = asyncio.Event()
            self.stop_entered = asyncio.Event()
            self.stop_release = asyncio.Event()
            self.stop_completed = False
            self.stop_cancelled = False

        async def ready(self) -> LiveSourceCut:
            self.ready_entered.set()
            await asyncio.Event().wait()
            raise AssertionError

        async def stop(self) -> None:
            self.stopped += 1
            self.stop_entered.set()
            try:
                await self.stop_release.wait()
                self.stop_completed = True
                self._wait.set()
            except asyncio.CancelledError:
                self.stop_cancelled = True
                raise

    live = BlockingStartupLive()
    alarm = Alarm()
    telegram = Telegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=alarm,
        archive_query=Archive(),
        runner=Runner(),
        telegram=telegram,
        clock=Clock(1.0),
    )
    task = asyncio.create_task(coordinator.start())
    await live.ready_entered.wait()
    task.cancel()
    await live.stop_entered.wait()
    task.cancel()
    live.stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.stop_completed is True
    assert live.stop_cancelled is False
    assert live.stopped == 1
    assert alarm.closed == 1
    assert telegram.closed == 1


@pytest.mark.asyncio
async def test_ready_health_rechecks_live_failure_after_state_load_pause(
    tmp_path: Path,
) -> None:
    class SleepingClock(Clock):
        def __init__(self) -> None:
            super().__init__(1.0)
            self.sleep_entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.sleep_entered.set()
            await asyncio.Event().wait()

    pause_load = False
    paused_once = False
    load_entered = asyncio.Event()
    load_release = asyncio.Event()

    async def pausing_blocking(fn, *args, **kwargs):
        nonlocal paused_once
        if pause_load and not paused_once and fn.__name__ == "load_periodic_state":
            paused_once = True
            load_entered.set()
            await load_release.wait()
        return await asyncio.to_thread(fn, *args, **kwargs)

    clock = SleepingClock()
    live = Live()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=clock,
        run_blocking=pausing_blocking,
    )
    await coordinator.start()
    await clock.sleep_entered.wait()
    snapshot = coordinator.projection_snapshot(window_start=1.0, window_end=121.0)
    pause_load = True

    async def write_heartbeat() -> None:
        assert coordinator._reconcile_lock is not None
        async with coordinator._reconcile_lock:
            await coordinator._set_projection_health(snapshot)

    heartbeat = asyncio.create_task(write_heartbeat())
    await load_entered.wait()
    live._wait.set()
    for _ in range(100):
        if coordinator._live_source_failed:
            break
        await asyncio.sleep(0.001)
    assert coordinator._live_source_failed is True
    load_release.set()
    await heartbeat
    assert load_periodic_state(tmp_path).payload["health"]["status"] == (
        "degraded_source"
    )
    await coordinator.stop()
