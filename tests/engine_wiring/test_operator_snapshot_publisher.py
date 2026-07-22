from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.engine_wiring.operator_snapshot_publisher import (
    OperatorSnapshotPublicationService,
    SnapshotPublicationErrorCode,
)
from cryodaq.operator_snapshot import (
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
)
from cryodaq.operator_snapshot_transport import (
    OPERATOR_SNAPSHOT_TOPIC,
    encode_operator_snapshot_frames,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
SOURCE = "engine/operator-snapshot-v1/0123456789abcdef0123456789abcdef"


def _snapshot(
    revision: int,
    *,
    source: str = SOURCE,
    received_at: datetime | None = None,
) -> OperatorSnapshot:
    received = NOW + timedelta(seconds=revision) if received_at is None else received_at
    cut = SnapshotCut(revision, NOW, received, source, SnapshotMode.LIVE, "experiment-1", source)
    status = SummaryStatus(
        OperatorPresentationState.CAUTION,
        float(revision),
        0.0,
        ("authority_pending",),
        "Backend authority",
    )
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, ReadinessTruth.UNKNOWN, ()),
        PlantHealthSummary(cut, status, ()),
        InfrastructureNodeHealth(cut, status, ()),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            "experiment-1",
            "Cooldown",
            "cooldown",
            RecordingTruth.UNKNOWN,
            None,
        ),
        DataIntegritySummary(cut, status, revision, revision, 0, 0, AvailabilityTruth.UNKNOWN),
        CooldownHistorySummary(cut, status, (), None, ()),
        SupportBundleSummary(cut, status, AvailabilityTruth.UNKNOWN, None),
    )


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Composer:
    def __init__(self, results: list[OperatorSnapshot | BaseException]) -> None:
        self.results = results
        self.calls = 0

    async def compose(self, observed_at: datetime) -> OperatorSnapshot:
        assert observed_at == NOW
        result = self.results[self.calls]
        self.calls += 1
        if isinstance(result, BaseException):
            raise result
        return result


class _Publisher:
    def __init__(self, results: list[bool | BaseException] | None = None) -> None:
        self.results = [True] if results is None else results
        self.snapshots: list[OperatorSnapshot] = []
        self.published = asyncio.Event()

    async def publish_operator_snapshot(self, snapshot: OperatorSnapshot) -> bool:
        self.snapshots.append(snapshot)
        self.published.set()
        result = self.results[len(self.snapshots) - 1]
        if isinstance(result, BaseException):
            raise result
        return result


class _Socket:
    def __init__(self) -> None:
        self.messages: list[list[bytes]] = []

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.messages.append(frames)


class _BlockingSocket(_Socket):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.entered.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_zmq_publisher_uses_sole_socket_lock_and_exact_two_frames() -> None:
    snapshot = _snapshot(1)
    socket = _Socket()
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True

    assert await publisher.publish_operator_snapshot(snapshot) is True

    assert socket.messages == [list(encode_operator_snapshot_frames(snapshot))]
    assert socket.messages[0][0] == OPERATOR_SNAPSHOT_TOPIC
    assert len(socket.messages[0]) == 2
    assert publisher.publish_failure_count == 0
    assert publisher.sequence == 0  # the observational lane does not mint reading/barrier authority


@pytest.mark.asyncio
async def test_zmq_publisher_encode_or_socket_failure_sends_no_partial_or_duplicate_message() -> None:
    socket = _Socket()
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True

    assert await publisher.publish_operator_snapshot(object()) is False  # type: ignore[arg-type]
    publisher._running = False
    assert await publisher.publish_operator_snapshot(_snapshot(1)) is False

    assert socket.messages == []
    assert publisher.publish_failure_count == 2


@pytest.mark.asyncio
async def test_zmq_publisher_cancellation_propagates_without_retry_or_partial_fake_send() -> None:
    socket = _BlockingSocket()
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True

    task = asyncio.create_task(publisher.publish_operator_snapshot(_snapshot(1)))
    await socket.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert socket.messages == []
    assert publisher.publish_failure_count == 1


@pytest.mark.asyncio
async def test_service_publishes_complete_monotonic_snapshot_and_coalesces_early_trigger() -> None:
    monotonic = _Clock()
    composer = _Composer([_snapshot(1), _snapshot(2)])
    publisher = _Publisher([True, True])
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        cadence_hz=2,
        clock=lambda: NOW,
        monotonic=monotonic,
    )

    assert await service._publish_if_due() is True
    assert await service._publish_if_due() is False
    monotonic.value = 0.49
    assert await service._publish_if_due() is False
    monotonic.value = 0.5
    assert await service._publish_if_due() is True

    assert [item.cut.revision for item in publisher.snapshots] == [1, 2]
    assert all(len(item.summaries()) == 8 for item in publisher.snapshots)
    assert service.coalesced_count == 2
    assert service.last_published_revision == 2
    assert service.last_error_code is None


@pytest.mark.asyncio
async def test_slow_composition_has_one_owner_and_missed_ticks_do_not_burst() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowComposer:
        def __init__(self) -> None:
            self.calls = 0

        async def compose(self, _observed_at: datetime) -> OperatorSnapshot:
            self.calls += 1
            entered.set()
            await release.wait()
            return _snapshot(self.calls)

    monotonic = _Clock()
    composer = SlowComposer()
    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        cadence_hz=2,
        clock=lambda: NOW,
        monotonic=monotonic,
    )

    first = asyncio.create_task(service._publish_if_due())
    await entered.wait()
    monotonic.value = 10.0
    overlapping = asyncio.create_task(service._publish_if_due())
    release.set()
    assert await first is True
    assert await overlapping is False

    assert composer.calls == 1
    assert len(publisher.snapshots) == 1
    assert service.coalesced_count == 1


@pytest.mark.asyncio
async def test_compose_encode_and_publish_failures_emit_nothing_and_only_degrade_presentation() -> None:
    monotonic = _Clock()
    composer = _Composer([RuntimeError("compose"), _snapshot(1), _snapshot(2)])
    publisher = _Publisher([False, RuntimeError("transport")])
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        cadence_hz=1,
        clock=lambda: NOW,
        monotonic=monotonic,
    )

    assert await service._publish_if_due() is False
    assert publisher.snapshots == []
    assert service.last_error_code is SnapshotPublicationErrorCode.COMPOSITION_FAILED
    monotonic.value = 1
    assert await service._publish_if_due() is False
    monotonic.value = 2
    assert await service._publish_if_due() is False

    assert service.composition_failure_count == 1
    assert service.publication_failure_count == 2
    assert service.last_published_revision == 0
    assert [item.cut.revision for item in publisher.snapshots] == [1, 2]


@pytest.mark.asyncio
async def test_leadership_revision_and_received_at_regressions_fail_closed() -> None:
    monotonic = _Clock()
    snapshots = [
        _snapshot(2),
        _snapshot(3, source="engine/operator-snapshot-v1/ffffffffffffffffffffffffffffffff"),
        _snapshot(2),
        _snapshot(4, received_at=NOW),
    ]
    composer = _Composer(snapshots)
    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        clock=lambda: NOW,
        monotonic=monotonic,
    )

    assert await service._publish_if_due() is True
    for tick in (1, 2, 3):
        monotonic.value = tick
        assert await service._publish_if_due() is False
        assert service.last_error_code is SnapshotPublicationErrorCode.INVALID_SNAPSHOT_SEQUENCE

    assert [item.cut.revision for item in publisher.snapshots] == [2]
    assert service.composition_failure_count == 3


@pytest.mark.asyncio
async def test_cancellation_during_composition_settles_without_send_or_orphan_owner() -> None:
    entered = asyncio.Event()

    class BlockingComposer:
        async def compose(self, _observed_at: datetime) -> OperatorSnapshot:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=BlockingComposer(),
        publisher=publisher,
        clock=lambda: NOW,
    )
    task = asyncio.create_task(service.run(), name="test_operator_snapshot_publication")
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert service.running is False
    assert publisher.snapshots == []


@pytest.mark.asyncio
async def test_cancellation_during_publish_does_not_retry_or_reuse_composed_revision() -> None:
    entered = asyncio.Event()

    class BlockingFirstPublisher:
        def __init__(self) -> None:
            self.snapshots: list[OperatorSnapshot] = []

        async def publish_operator_snapshot(self, snapshot: OperatorSnapshot) -> bool:
            self.snapshots.append(snapshot)
            if len(self.snapshots) == 1:
                entered.set()
                await asyncio.Event().wait()
            return True

    monotonic = _Clock()
    publisher = BlockingFirstPublisher()
    service = OperatorSnapshotPublicationService(
        composer=_Composer([_snapshot(1), _snapshot(2)]),
        publisher=publisher,
        cadence_hz=2,
        clock=lambda: NOW,
        monotonic=monotonic,
    )
    first = asyncio.create_task(service._publish_if_due())
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    monotonic.value = 0.5
    assert await service._publish_if_due() is True
    assert [snapshot.cut.revision for snapshot in publisher.snapshots] == [1, 2]
    assert service.last_published_revision == 2


@pytest.mark.asyncio
async def test_requested_shutdown_interrupts_cadence_wait_and_second_owner_is_rejected() -> None:
    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=_Composer([_snapshot(1)]),
        publisher=publisher,
        cadence_hz=0.01,
        clock=lambda: NOW,
    )
    owner = asyncio.create_task(service.run())
    await publisher.published.wait()

    with pytest.raises(RuntimeError, match="already has an owner"):
        await service.run()
    service.request_stop()
    await asyncio.wait_for(owner, timeout=0.2)

    assert service.running is False
    assert len(publisher.snapshots) == 1


@pytest.mark.parametrize("cadence", [True, 0, -1, 2.0001, float("inf"), float("nan")])
def test_cadence_contract_rejects_invalid_or_faster_than_two_hz(cadence: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        OperatorSnapshotPublicationService(
            composer=_Composer([_snapshot(1)]),
            publisher=_Publisher(),
            cadence_hz=cadence,
        )


def test_subnormal_cadence_with_infinite_reciprocal_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite positive interval"):
        OperatorSnapshotPublicationService(
            composer=_Composer([_snapshot(1)]),
            publisher=_Publisher(),
            cadence_hz=5e-324,
        )


@pytest.mark.parametrize(
    "invalid",
    [float("nan"), float("inf"), float("-inf"), True, "0", object()],
)
@pytest.mark.asyncio
async def test_invalid_initial_monotonic_fails_before_composition_or_send(invalid: object) -> None:
    composer = _Composer([_snapshot(1)])
    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        clock=lambda: NOW,
        monotonic=lambda: invalid,  # type: ignore[arg-type,return-value]
    )

    with pytest.raises((TypeError, ValueError)):
        await service._publish_if_due()
    assert composer.calls == 0
    assert publisher.snapshots == []


@pytest.mark.asyncio
async def test_invalid_run_clock_releases_lifecycle_owner_without_send_or_spin() -> None:
    composer = _Composer([_snapshot(1)])
    publisher = _Publisher()
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        monotonic=lambda: float("nan"),
    )

    with pytest.raises(ValueError, match="finite"):
        await service.run()
    assert service.running is False
    assert composer.calls == 0
    assert publisher.snapshots == []


@pytest.mark.asyncio
async def test_raising_monotonic_fails_before_composition_or_send() -> None:
    composer = _Composer([_snapshot(1)])
    publisher = _Publisher()

    def broken_clock() -> float:
        raise RuntimeError("clock unavailable")

    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        monotonic=broken_clock,
    )
    with pytest.raises(RuntimeError, match="clock unavailable"):
        await service._publish_if_due()
    assert composer.calls == 0
    assert publisher.snapshots == []


@pytest.mark.asyncio
async def test_monotonic_regression_fails_closed_without_second_send() -> None:
    values = iter((1.0, 1.0, 0.5))
    composer = _Composer([_snapshot(1), _snapshot(2)])
    publisher = _Publisher([True, True])
    service = OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        clock=lambda: NOW,
        monotonic=lambda: next(values),
    )

    assert await service._publish_if_due() is True
    with pytest.raises(ValueError, match="regressed"):
        await service._publish_if_due()
    assert [snapshot.cut.revision for snapshot in publisher.snapshots] == [1]


@pytest.mark.asyncio
async def test_clock_exception_during_cancelled_attempt_never_masks_cancellation() -> None:
    entered = asyncio.Event()
    calls = 0

    def monotonic() -> float:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("must not mask cancellation")
        return 0.0

    class BlockingComposer:
        async def compose(self, _observed_at: datetime) -> OperatorSnapshot:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    service = OperatorSnapshotPublicationService(
        composer=BlockingComposer(),
        publisher=_Publisher(),
        clock=lambda: NOW,
        monotonic=monotonic,
    )
    task = asyncio.create_task(service._publish_if_due())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 1


def test_dark_service_has_no_command_control_gui_socket_or_driver_authority() -> None:
    path = Path(__file__).resolve().parents[2] / "src/cryodaq/engine_wiring/operator_snapshot_publisher.py"
    tree = ast.parse(path.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    text = path.read_text().lower()

    assert not any(name.startswith(("cryodaq.gui", "cryodaq.drivers", "zmq", "cryodaq.safety")) for name in imports)
    for forbidden in ("command", "actuator", "credential", "token", "remediation", "restart"):
        assert forbidden not in text
