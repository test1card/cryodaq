"""Lifecycle contract for the ordinary + dedicated-safe command ingress pair."""

from __future__ import annotations

import asyncio
import socket

import pytest

from cryodaq.core.zmq_bridge import ZMQCommandServerTerminalFailure


def _free_tcp_addresses() -> tuple[str, str]:
    sockets = (socket.socket(socket.AF_INET, socket.SOCK_STREAM), socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        ordinary_port = sockets[0].getsockname()[1]
        safe_port = sockets[1].getsockname()[1]
        return f"tcp://127.0.0.1:{ordinary_port}", f"tcp://127.0.0.1:{safe_port}"
    finally:
        for listener in sockets:
            listener.close()


class _Owner:
    def __init__(
        self,
        label: str,
        events: list[str],
        *,
        start_release: asyncio.Event | None = None,
        start_failure: BaseException | None = None,
        stop_release: asyncio.Event | None = None,
        stop_failures: int = 0,
    ) -> None:
        self.label = label
        self.events = events
        self.start_release = start_release
        self.start_failure = start_failure
        self.stop_release = stop_release
        self.stop_failures = stop_failures
        self.start_entered = asyncio.Event()
        self.stop_entered = asyncio.Event()
        self.start_calls = 0
        self.freeze_calls = 0
        self.stop_calls = 0
        self.stop_cancelled = False
        self.terminal = False
        self.terminal_notifier = None

    async def start(self) -> None:
        self.start_calls += 1
        self.events.append(f"{self.label}.start")
        self.start_entered.set()
        if self.start_release is not None:
            await self.start_release.wait()
        if self.start_failure is not None:
            raise self.start_failure

    def bind_terminal_failure_notifier(self, notifier) -> None:
        assert self.terminal_notifier is None
        self.terminal_notifier = notifier

    def terminal_failure_notifier_state_is_pristine(self) -> bool:
        return self.terminal_notifier is None

    def unbind_terminal_failure_notifier(self, expected_notifier) -> None:
        if self.terminal_notifier is not expected_notifier:
            raise RuntimeError(f"{self.label} terminal notifier owner mismatch")
        self.terminal_notifier = None

    def emit_terminal_failure(
        self,
        *,
        stage: str = "recovery_exhausted",
        failure_type: str = "RuntimeError",
    ) -> None:
        assert self.terminal_notifier is not None
        self.terminal_notifier(
            ZMQCommandServerTerminalFailure(
                stage=stage,  # type: ignore[arg-type]
                failure_type=failure_type,
            )
        )

    def freeze_admission(self) -> None:
        self.freeze_calls += 1
        self.events.append(f"{self.label}.freeze")

    async def stop(self) -> None:
        self.stop_calls += 1
        self.events.append(f"{self.label}.stop:{self.stop_calls}")
        self.stop_entered.set()
        try:
            if self.stop_release is not None:
                await self.stop_release.wait()
        except asyncio.CancelledError:
            self.stop_cancelled = True
            raise
        if self.stop_calls <= self.stop_failures:
            raise RuntimeError(f"{self.label} stop failed")
        self.terminal = True


@pytest.mark.asyncio
async def test_pair_starts_safe_to_completion_before_opening_ordinary_admission() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    release_safe = asyncio.Event()
    safe = _Owner("safe", events, start_release=release_safe)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    start = asyncio.create_task(pair.start())
    await asyncio.wait_for(safe.start_entered.wait(), timeout=1.0)
    assert ordinary.start_calls == 0
    assert events == ["safe.start"]

    release_safe.set()
    await asyncio.wait_for(start, timeout=1.0)

    assert events == ["safe.start", "ordinary.start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_owner", ["safe", "ordinary"])
async def test_pair_start_failure_rolls_back_every_possibly_acquired_owner(failing_owner: str) -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    safe = _Owner(
        "safe",
        events,
        start_failure=RuntimeError("safe start failed") if failing_owner == "safe" else None,
    )
    ordinary = _Owner(
        "ordinary",
        events,
        start_failure=RuntimeError("ordinary start failed") if failing_owner == "ordinary" else None,
    )
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    with pytest.raises(RuntimeError):
        await pair.start()

    assert safe.stop_calls == 1
    assert safe.terminal is True
    if failing_owner == "safe":
        assert ordinary.start_calls == 0
        assert ordinary.stop_calls == 0
    else:
        assert ordinary.start_calls == 1
        assert ordinary.stop_calls == 1
        assert ordinary.terminal is True


def test_pair_freeze_is_synchronous_and_covers_both_endpoints() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    safe = _Owner("safe", events)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    result = pair.freeze_admission()

    assert result is None
    assert safe.freeze_calls == 1
    assert ordinary.freeze_calls == 1
    assert events == ["safe.freeze", "ordinary.freeze"]


def test_pair_freeze_attempts_both_endpoints_and_preserves_first_failure() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []

    class _FailingFreezeOwner(_Owner):
        def freeze_admission(self) -> None:
            super().freeze_admission()
            raise RuntimeError("safe freeze failed")

    safe = _FailingFreezeOwner("safe", events)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    with pytest.raises(RuntimeError, match="safe freeze failed"):
        pair.freeze_admission()

    assert safe.freeze_calls == 1
    assert ordinary.freeze_calls == 1
    assert events == ["safe.freeze", "ordinary.freeze"]


@pytest.mark.asyncio
async def test_pair_start_cancellation_settles_every_possibly_acquired_owner() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    never_release = asyncio.Event()
    safe = _Owner("safe", events, start_release=never_release)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    start = asyncio.create_task(pair.start())
    await asyncio.wait_for(safe.start_entered.wait(), timeout=1.0)
    start.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(start, timeout=1.0)

    assert safe.freeze_calls == 1
    assert safe.stop_calls == 1
    assert safe.terminal is True
    assert ordinary.start_calls == 0
    assert ordinary.freeze_calls == 0
    assert ordinary.stop_calls == 0


@pytest.mark.parametrize("foreign_label", ["safe", "ordinary"])
def test_pair_rejects_foreign_production_owner_before_mutating_either_notifier(
    foreign_label: str,
) -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
        ZMQCommandServerOwnershipConflict,
    )

    registry = CommandAuthorityRegistry()
    ordinary_address, safe_address = _free_tcp_addresses()
    ordinary = ZMQCommandServer(ordinary_address, authority_registry=registry)
    safe = ZMQCommandServer(safe_address, authority_registry=registry)
    foreign_owner = safe if foreign_label == "safe" else ordinary
    clean_peer = ordinary if foreign_label == "safe" else safe
    foreign_context = object()
    foreign_owner._ctx = foreign_context

    with pytest.raises(ZMQCommandServerOwnershipConflict, match="already owned outside this pair"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert foreign_owner._ctx is foreign_context
    assert foreign_owner._shutdown_requested is False
    assert clean_peer.startup_state_is_pristine() is True
    assert ordinary._terminal_failure_notifier is None
    assert safe._terminal_failure_notifier is None


def test_pair_constructor_preflights_both_notifiers_before_binding_either() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
        ZMQCommandServerOwnershipConflict,
    )

    registry = CommandAuthorityRegistry()
    ordinary_address, safe_address = _free_tcp_addresses()
    ordinary = ZMQCommandServer(ordinary_address, authority_registry=registry)
    safe = ZMQCommandServer(safe_address, authority_registry=registry)
    foreign_notifications: list[ZMQCommandServerTerminalFailure] = []
    ordinary.bind_terminal_failure_notifier(foreign_notifications.append)
    foreign_notifier = ordinary._terminal_failure_notifier

    with pytest.raises(ZMQCommandServerOwnershipConflict, match="notifier"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert ordinary._terminal_failure_notifier is foreign_notifier
    assert safe._terminal_failure_notifier is None
    replacement = ZMQCommandServer(ordinary_address, authority_registry=registry)
    pair = ZMQCommandIngressPair(ordinary=replacement, safe=safe)
    assert replacement._terminal_failure_notifier is not None
    assert safe._terminal_failure_notifier is not None
    assert pair.terminal_failure is None


def test_pair_notifier_binding_failure_rolls_back_both_children_exactly() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
    )

    class MutateThenFailServer(ZMQCommandServer):
        fail_binding = True

        def bind_terminal_failure_notifier(self, notifier) -> None:  # noqa: ANN001
            super().bind_terminal_failure_notifier(notifier)
            if self.fail_binding:
                raise RuntimeError("synthetic post-mutation notifier bind failure")

    registry = CommandAuthorityRegistry()
    ordinary_address, safe_address = _free_tcp_addresses()
    ordinary = MutateThenFailServer(ordinary_address, authority_registry=registry)
    safe = ZMQCommandServer(safe_address, authority_registry=registry)

    with pytest.raises(RuntimeError, match="post-mutation notifier bind failure"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert ordinary._terminal_failure_notifier is None
    assert safe._terminal_failure_notifier is None
    ordinary.fail_binding = False
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    assert ordinary._terminal_failure_notifier is not None
    assert safe._terminal_failure_notifier is not None
    assert pair.terminal_failure is None


@pytest.mark.parametrize("failing_label", ["safe", "ordinary"])
def test_structural_owner_mutate_then_raise_unbinds_every_attempted_slot_and_retries(
    failing_label: str,
) -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    class MutateThenFailOwner(_Owner):
        fail_binding = True

        def bind_terminal_failure_notifier(self, notifier) -> None:  # noqa: ANN001
            super().bind_terminal_failure_notifier(notifier)
            if self.fail_binding:
                raise RuntimeError(f"{self.label} mutated then failed")

    events: list[str] = []
    safe = MutateThenFailOwner("safe", events) if failing_label == "safe" else _Owner("safe", events)
    ordinary = MutateThenFailOwner("ordinary", events) if failing_label == "ordinary" else _Owner("ordinary", events)

    with pytest.raises(RuntimeError, match="mutated then failed"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert safe.terminal_notifier is None
    assert ordinary.terminal_notifier is None
    failing_owner = safe if failing_label == "safe" else ordinary
    failing_owner.fail_binding = False
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    assert safe.terminal_notifier is not None
    assert ordinary.terminal_notifier is not None
    assert pair.terminal_failure is None


def test_structural_owner_rollback_attempts_every_slot_and_reports_hold() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    rollback_events: list[str] = []

    class RollbackOwner(_Owner):
        fail_bind = False
        fail_unbind = False

        def bind_terminal_failure_notifier(self, notifier) -> None:  # noqa: ANN001
            super().bind_terminal_failure_notifier(notifier)
            if self.fail_bind:
                raise RuntimeError(f"{self.label} bind failed after mutation")

        def unbind_terminal_failure_notifier(self, expected_notifier) -> None:  # noqa: ANN001
            rollback_events.append(self.label)
            if self.fail_unbind:
                raise RuntimeError(f"{self.label} unbind failed")
            super().unbind_terminal_failure_notifier(expected_notifier)

    events: list[str] = []
    safe = RollbackOwner("safe", events)
    ordinary = RollbackOwner("ordinary", events)
    ordinary.fail_bind = True
    ordinary.fail_unbind = True

    with pytest.raises(RuntimeError, match="ownership remains in HOLD") as raised:
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert raised.value.__cause__ is not None
    assert str(raised.value.__cause__) == "ordinary unbind failed"
    assert rollback_events == ["ordinary", "safe"]
    assert ordinary.terminal_notifier is not None
    assert safe.terminal_notifier is None


@pytest.mark.asyncio
async def test_failed_pair_can_be_discarded_then_clean_peer_can_start_and_restart() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
        ZMQCommandServerOwnershipConflict,
    )

    registry = CommandAuthorityRegistry()
    ordinary_address, safe_address = _free_tcp_addresses()
    foreign_ordinary = ZMQCommandServer(ordinary_address, authority_registry=registry)
    safe = ZMQCommandServer(safe_address, authority_registry=registry)
    foreign_context = object()
    foreign_ordinary._ctx = foreign_context

    with pytest.raises(ZMQCommandServerOwnershipConflict, match="already owned outside this pair"):
        ZMQCommandIngressPair(ordinary=foreign_ordinary, safe=safe)

    ordinary = ZMQCommandServer(ordinary_address, authority_registry=registry)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    ordinary_notifier = ordinary._terminal_failure_notifier
    safe_notifier = safe._terminal_failure_notifier
    await pair.start()
    await pair.stop()
    await pair.start()
    try:
        assert ordinary._terminal_failure_notifier is ordinary_notifier
        assert safe._terminal_failure_notifier is safe_notifier
        assert pair.terminal_failure is None
    finally:
        await pair.stop()


def test_real_ingress_pair_requires_one_exact_shared_authority_registry() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
    )

    ordinary = ZMQCommandServer(authority_registry=CommandAuthorityRegistry())
    safe = ZMQCommandServer(
        "tcp://127.0.0.1:5558",
        authority_registry=CommandAuthorityRegistry(),
    )

    with pytest.raises(ValueError, match="share one authority registry"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)


@pytest.mark.parametrize(
    ("ordinary_addr", "safe_addr", "error"),
    [
        pytest.param(
            "tcp://127.0.0.1:5556",
            "tcp://127.0.0.1:5556",
            "safe_command endpoint aliases",
            id="exact-duplicate",
        ),
        pytest.param(
            "tcp://localhost:5556",
            "tcp://127.0.0.1:5556",
            "ordinary_command endpoint must be a canonical loopback TCP address",
            id="noncanonical-localhost-alias",
        ),
    ],
)
def test_real_ingress_pair_rejects_endpoint_identity_overlap_before_start(
    ordinary_addr: str,
    safe_addr: str,
    error: str,
) -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
    )

    registry = CommandAuthorityRegistry()
    ordinary = ZMQCommandServer(ordinary_addr, authority_registry=registry)
    safe = ZMQCommandServer(safe_addr, authority_registry=registry)

    with pytest.raises(ValueError, match=error):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert ordinary.startup_state_is_pristine() is True
    assert safe.startup_state_is_pristine() is True


def test_real_servers_bind_pair_terminal_notifier_and_freeze_safe_then_ordinary() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
    )

    registry = CommandAuthorityRegistry()
    ordinary = ZMQCommandServer("tcp://127.0.0.1:5556", authority_registry=registry)
    safe = ZMQCommandServer("tcp://127.0.0.1:5558", authority_registry=registry)
    events: list[str] = []
    ordinary_freeze = ordinary.freeze_admission
    safe_freeze = safe.freeze_admission

    def freeze_ordinary() -> None:
        events.append("ordinary")
        ordinary_freeze()

    def freeze_safe() -> None:
        events.append("safe")
        safe_freeze()

    ordinary.freeze_admission = freeze_ordinary  # type: ignore[method-assign]
    safe.freeze_admission = freeze_safe  # type: ignore[method-assign]
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    pair._owned_labels.update({"safe", "ordinary"})
    ordinary._running = True
    safe._running = True

    safe._latch_terminal_failure(stage="recovery_exhausted", failure_type="RuntimeError")

    assert events == ["safe", "ordinary"]
    assert pair.terminal_failure is not None
    assert pair.terminal_failure.endpoint == "safe"
    assert safe._running is False
    assert ordinary._running is False


def test_pair_rejects_preterminal_child_without_freezing_unowned_peer() -> None:
    from cryodaq.core.zmq_bridge import (
        CommandAuthorityRegistry,
        ZMQCommandIngressPair,
        ZMQCommandServer,
        ZMQCommandServerOwnershipConflict,
    )

    registry = CommandAuthorityRegistry()
    ordinary = ZMQCommandServer("tcp://127.0.0.1:5556", authority_registry=registry)
    safe = ZMQCommandServer("tcp://127.0.0.1:5558", authority_registry=registry)
    ordinary._running = True
    safe._running = True
    safe._latch_terminal_failure(stage="recovery_exhausted", failure_type="RuntimeError")

    with pytest.raises(ZMQCommandServerOwnershipConflict, match="terminal before pair ownership"):
        ZMQCommandIngressPair(ordinary=ordinary, safe=safe)

    assert safe._running is False
    assert ordinary._running is True
    assert ordinary._shutdown_requested is False


@pytest.mark.asyncio
async def test_pair_stop_settles_both_peers_despite_repeated_caller_cancellation() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    release_stop = asyncio.Event()
    safe = _Owner("safe", events, stop_release=release_stop)
    ordinary = _Owner("ordinary", events, stop_release=release_stop)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    await pair.start()

    stop = asyncio.create_task(pair.stop())
    await asyncio.wait_for(safe.stop_entered.wait(), timeout=1.0)
    await asyncio.wait_for(ordinary.stop_entered.wait(), timeout=1.0)
    stop.cancel()
    await asyncio.sleep(0)
    stop.cancel()
    await asyncio.sleep(0)

    assert stop.done() is False
    assert safe.stop_cancelled is False
    assert ordinary.stop_cancelled is False

    release_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stop, timeout=1.0)

    assert safe.terminal is True
    assert ordinary.terminal is True
    assert safe.stop_cancelled is False
    assert ordinary.stop_cancelled is False

    await pair.stop()
    assert safe.stop_calls == 1
    assert ordinary.stop_calls == 1


@pytest.mark.asyncio
async def test_pair_stop_retains_only_failed_owner_for_explicit_retry() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    safe = _Owner("safe", events, stop_failures=1)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    await pair.start()

    with pytest.raises(RuntimeError):
        await pair.stop()

    assert safe.stop_calls == 1
    assert safe.terminal is False
    assert ordinary.stop_calls == 1
    assert ordinary.terminal is True

    await pair.stop()

    assert safe.stop_calls == 2
    assert safe.terminal is True
    assert ordinary.stop_calls == 1


@pytest.mark.asyncio
async def test_pair_terminal_latch_freezes_both_retains_owners_and_survives_cancelled_waiter() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []

    class FailingFreezeOwner(_Owner):
        def freeze_admission(self) -> None:
            super().freeze_admission()
            raise RuntimeError("freeze-secret-must-not-replace-provenance")

    safe = FailingFreezeOwner("safe", events)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    assert safe.terminal_notifier is not None
    assert ordinary.terminal_notifier is not None
    await pair.start()

    cancelled_waiter = asyncio.create_task(pair.wait_terminal_failure())
    await asyncio.sleep(0)
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter

    safe.emit_terminal_failure()
    failure = await pair.wait_terminal_failure()

    assert failure.endpoint == "safe"
    assert failure.stage == "recovery_exhausted"
    assert failure.failure_type == "RuntimeError"
    assert pair._owned_labels == {"safe", "ordinary"}
    assert events == [
        "safe.start",
        "ordinary.start",
        "safe.freeze",
        "ordinary.freeze",
    ]

    ordinary.emit_terminal_failure(stage="loop_closed", failure_type="OSError")
    assert pair.terminal_failure is failure
    assert safe.freeze_calls == 1
    assert ordinary.freeze_calls == 1

    with pytest.raises(RuntimeError, match="freeze-secret"):
        await pair.stop()
    assert pair._owned_labels == set()
    with pytest.raises(RuntimeError, match="requires pristine ownership"):
        await pair.start()


@pytest.mark.asyncio
async def test_pair_concurrent_terminal_notifications_retain_exactly_first_provenance() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    release = asyncio.Event()
    notification_order: list[str] = []
    safe = _Owner("safe", events)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    await pair.start()

    async def notify(label: str, owner: _Owner) -> None:
        await release.wait()
        notification_order.append(label)
        owner.emit_terminal_failure(
            stage="recovery_exhausted" if label == "safe" else "loop_closed",
            failure_type="RuntimeError" if label == "safe" else "OSError",
        )

    notifications = (
        asyncio.create_task(notify("safe", safe)),
        asyncio.create_task(notify("ordinary", ordinary)),
    )
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(*notifications)

    failure = await pair.wait_terminal_failure()
    assert failure.endpoint == notification_order[0]
    assert safe.freeze_calls == 1
    assert ordinary.freeze_calls == 1
    assert pair._owned_labels == {"safe", "ordinary"}
    await pair.stop()


@pytest.mark.asyncio
async def test_pair_clean_stop_never_signals_terminal_failure() -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandIngressPair

    events: list[str] = []
    safe = _Owner("safe", events)
    ordinary = _Owner("ordinary", events)
    pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
    await pair.start()
    waiter = asyncio.create_task(pair.wait_terminal_failure())

    await pair.stop()
    await asyncio.sleep(0)

    assert pair.terminal_failure is None
    assert waiter.done() is False
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
