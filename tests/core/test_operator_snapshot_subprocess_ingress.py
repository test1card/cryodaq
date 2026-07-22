from __future__ import annotations

import ast
import multiprocessing as mp
import queue
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cryodaq.core.operator_snapshot_ingress import (
    OperatorSnapshotQueueIngress,
    SnapshotIngressOrderingError,
    SnapshotIngressQueueError,
)
from cryodaq.core.zmq_subprocess import (
    DEFAULT_ASSISTANT_CMD_ADDR,
    DEFAULT_TOPIC,
    OPERATOR_SNAPSHOT_MAX_WIRE_BYTES,
    OPERATOR_SNAPSHOT_TOPIC,
    READING_MAX_WIRE_BYTES,
    ReadingFrameError,
    _decode_reading_frames,
    _increment_shared_counter,
    _new_sub_socket,
    zmq_bridge_main,
)
from cryodaq.gui.zmq_client import ZmqBridge
from cryodaq.operator_snapshot import (
    MAX_WIRE_BYTES,
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
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
)
from cryodaq.operator_snapshot_transport import (
    OperatorSnapshotTransportError,
    encode_operator_snapshot_frames,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
SOURCE = "engine/operator-snapshot-v1/0123456789abcdef0123456789abcdef"


def _snapshot(
    revision: int,
    *,
    received_at: datetime | None = None,
) -> OperatorSnapshot:
    received = NOW + timedelta(seconds=revision) if received_at is None else received_at
    cut = SnapshotCut(revision, NOW, received, SOURCE, SnapshotMode.LIVE, "experiment-1", SOURCE)
    status = SummaryStatus(
        OperatorPresentationState.CAUTION,
        float(revision),
        0.0,
        ("authority_pending",),
        "Backend authority",
    )
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, ReadinessTruth.UNKNOWN, (), SafetyLifecycle.UNKNOWN),
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


def _spawn_decode_once(frames: tuple[bytes, bytes], output: Any) -> None:
    OperatorSnapshotQueueIngress(output).accept_frames(frames)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def test_capacity_two_coalesces_to_newest_complete_cuts_and_balances_task_done() -> None:
    output: queue.Queue[OperatorSnapshot] = queue.Queue(maxsize=2)
    ingress = OperatorSnapshotQueueIngress(output)

    assert ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(1))).dropped_oldest == 0
    assert ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(2))).dropped_oldest == 0
    assert ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(3))).dropped_oldest == 1

    retained = [output.get_nowait(), output.get_nowait()]
    for _item in retained:
        output.task_done()
    assert [snapshot.cut.revision for snapshot in retained] == [2, 3]
    assert output.unfinished_tasks == 0


def test_shared_counter_lock_cannot_block_gui_or_subprocess_evidence() -> None:
    bridge = ZmqBridge()
    counter = bridge._snapshot_malformed_count
    entered = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with counter.get_lock():
            entered.set()
            assert release.wait(2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert entered.wait(1.0)
    started = time.monotonic()
    try:
        assert bridge.snapshot_malformed_count == 0
        assert _increment_shared_counter(counter) is False
        assert time.monotonic() - started < 0.1
    finally:
        release.set()
        holder.join(timeout=1.0)


def test_subprocess_snapshot_topic_and_cap_match_neutral_transport_contract() -> None:
    from cryodaq.core.zmq_bridge import MAX_DATA_MSG_SIZE
    from cryodaq.operator_snapshot_transport import OPERATOR_SNAPSHOT_TOPIC as WIRE_TOPIC

    assert OPERATOR_SNAPSHOT_TOPIC == WIRE_TOPIC
    assert OPERATOR_SNAPSHOT_MAX_WIRE_BYTES == MAX_WIRE_BYTES == 8 * 1024 * 1024
    assert READING_MAX_WIRE_BYTES == MAX_DATA_MSG_SIZE == 2 * 1024 * 1024


@pytest.mark.parametrize(
    "topic",
    [b"readings.evil", b"readings/extra", b"reading", b"", OPERATOR_SNAPSHOT_TOPIC],
)
def test_reading_prefix_subscription_requires_exact_topic_before_msgpack(
    topic: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cryodaq.core.zmq_subprocess._unpack_reading_dict",
        lambda _payload: pytest.fail("non-exact topic reached msgpack"),
    )
    with pytest.raises(ReadingFrameError, match="wrong reading topic"):
        _decode_reading_frames([topic, b"valid-looking"])


def test_exact_reading_topic_decodes_without_mutating_snapshot_health() -> None:
    import msgpack

    payload = msgpack.packb(
        {
            "ts": NOW.timestamp(),
            "iid": "mock",
            "ch": "T1",
            "v": 4.2,
            "u": "K",
            "st": "ok",
        },
        use_bin_type=True,
    )
    reading = _decode_reading_frames([DEFAULT_TOPIC, payload])
    assert reading["channel"] == "T1"


def test_broken_full_queue_fails_bounded_without_advancing_order_authority() -> None:
    class BrokenQueue:
        puts = 0

        def put_nowait(self, _item: object) -> None:
            self.puts += 1
            raise queue.Full

        def get_nowait(self) -> object:
            raise queue.Empty

        def task_done(self) -> None:
            pytest.fail("nothing was removed")

    broken = BrokenQueue()
    ingress = OperatorSnapshotQueueIngress(broken)
    with pytest.raises(SnapshotIngressQueueError, match="did not settle"):
        ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(1)))
    assert broken.puts == 8
    assert ingress._last_revision == 0
    assert ingress._last_received_at is None
    with pytest.raises(SnapshotIngressQueueError, match="did not settle"):
        ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(1)))
    assert broken.puts == 16


@pytest.mark.parametrize(
    "frames",
    [
        (b"wrong.topic", b"{}"),
        (OPERATOR_SNAPSHOT_TOPIC,),
        (OPERATOR_SNAPSHOT_TOPIC, b"{}", b"extra"),
        (OPERATOR_SNAPSHOT_TOPIC, b"\xff"),
    ],
)
def test_malformed_wrong_topic_and_noncanonical_frames_never_enter_queue(frames: tuple[bytes, ...]) -> None:
    output: queue.Queue[OperatorSnapshot] = queue.Queue(maxsize=2)
    ingress = OperatorSnapshotQueueIngress(output)

    with pytest.raises(OperatorSnapshotTransportError):
        ingress.accept_frames(frames)
    assert output.empty()
    assert output.unfinished_tasks == 0


def test_out_of_order_duplicate_and_received_at_regression_never_replace_newest() -> None:
    output: queue.Queue[OperatorSnapshot] = queue.Queue(maxsize=2)
    ingress = OperatorSnapshotQueueIngress(output)
    newest = _snapshot(2, received_at=NOW + timedelta(seconds=10))
    ingress.accept_frames(encode_operator_snapshot_frames(newest))

    with pytest.raises(SnapshotIngressOrderingError, match="revision"):
        ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(2)))
    with pytest.raises(SnapshotIngressOrderingError, match="received_at"):
        ingress.accept_frames(encode_operator_snapshot_frames(_snapshot(3, received_at=NOW + timedelta(seconds=5))))

    assert output.get_nowait() == newest
    output.task_done()
    assert output.unfinished_tasks == 0


def test_real_spawn_roundtrips_strict_decoded_snapshot_through_joinable_queue() -> None:
    context = mp.get_context("spawn")
    output = context.JoinableQueue(maxsize=2)
    expected = _snapshot(7)
    process = context.Process(
        target=_spawn_decode_once,
        args=(encode_operator_snapshot_frames(expected), output),
    )
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)
    assert process.exitcode == 0
    assert output.get(timeout=2) == expected
    output.task_done()
    output.join()
    output.close()
    output.join_thread()


def test_real_spawn_two_sub_sockets_keep_readings_and_newest_snapshot_independent() -> None:
    import msgpack
    import zmq

    context = mp.get_context("spawn")
    pub_addr = f"tcp://127.0.0.1:{_free_port()}"
    cmd_addr = f"tcp://127.0.0.1:{_free_port()}"
    data_queue = context.Queue(maxsize=100)
    command_queue = context.Queue(maxsize=10)
    reply_queue = context.Queue(maxsize=10)
    snapshot_queue = context.JoinableQueue(maxsize=2)
    shutdown = context.Event()
    malformed = context.Value("Q", 0, lock=True)
    dropped = context.Value("Q", 0, lock=True)

    zmq_context = zmq.Context()
    publisher = zmq_context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.bind(pub_addr)
    process = context.Process(
        target=zmq_bridge_main,
        args=(
            pub_addr,
            cmd_addr,
            data_queue,
            command_queue,
            reply_queue,
            shutdown,
            DEFAULT_ASSISTANT_CMD_ADDR,
            snapshot_queue,
            malformed,
            dropped,
        ),
    )
    process.start()
    try:
        # Slow joiner allowance, then repeat each lane so startup loss is harmless.
        time.sleep(0.5)
        for revision in range(1, 21):
            reading = msgpack.packb(
                {
                    "ts": time.time(),
                    "iid": "mock",
                    "ch": "T1",
                    "v": float(revision),
                    "u": "K",
                    "st": "ok",
                },
                use_bin_type=True,
            )
            publisher.send_multipart([DEFAULT_TOPIC, reading])
            publisher.send_multipart(list(encode_operator_snapshot_frames(_snapshot(revision))))
            time.sleep(0.02)

        deadline = time.monotonic() + 3.0
        readings: list[dict[str, Any]] = []
        while time.monotonic() < deadline and not readings:
            try:
                item = data_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(item, dict) and "__type" not in item:
                readings.append(item)

        retained: list[OperatorSnapshot] = []
        while time.monotonic() < deadline:
            try:
                item = snapshot_queue.get(timeout=0.1)
            except queue.Empty:
                if retained:
                    break
                continue
            retained.append(item)
            snapshot_queue.task_done()
            if len(retained) == 2:
                break

        assert readings and readings[-1]["channel"] == "T1"
        assert retained
        assert retained[-1].cut.revision == 20
        assert [item.cut.revision for item in retained] == sorted(item.cut.revision for item in retained)
        assert malformed.value == 0
        assert dropped.value >= 1
    finally:
        shutdown.set()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        publisher.close(linger=0)
        zmq_context.term()
        for ipc_queue in (
            data_queue,
            command_queue,
            reply_queue,
            snapshot_queue,
        ):
            ipc_queue.close()
            ipc_queue.join_thread()
    assert process.exitcode == 0


class _FakeSocket:
    def __init__(self) -> None:
        self.options: list[tuple[int, int]] = []
        self.actions: list[tuple[str, object]] = []

    def setsockopt(self, option: int, value: int) -> None:
        self.options.append((option, value))

    def connect(self, address: str) -> None:
        self.actions.append(("connect", address))

    def subscribe(self, topic: bytes) -> None:
        self.actions.append(("subscribe", topic))


class _FakeContext:
    def __init__(self) -> None:
        self.sockets: list[_FakeSocket] = []

    def socket(self, _kind: int) -> _FakeSocket:
        socket = _FakeSocket()
        self.sockets.append(socket)
        return socket


class _FakeZmq:
    SUB = 1
    LINGER = 2
    RCVTIMEO = 3
    MAXMSGSIZE = 4
    TCP_KEEPALIVE = 5
    TCP_KEEPALIVE_IDLE = 6
    TCP_KEEPALIVE_INTVL = 7
    TCP_KEEPALIVE_CNT = 8


def test_readings_and_snapshots_use_distinct_sub_sockets_topics_and_caps() -> None:
    context = _FakeContext()
    reading = _new_sub_socket(
        context,
        _FakeZmq,
        "tcp://127.0.0.1:5555",
        topic=DEFAULT_TOPIC,
        max_wire_bytes=READING_MAX_WIRE_BYTES,
    )
    snapshot = _new_sub_socket(
        context,
        _FakeZmq,
        "tcp://127.0.0.1:5555",
        topic=OPERATOR_SNAPSHOT_TOPIC,
        max_wire_bytes=OPERATOR_SNAPSHOT_MAX_WIRE_BYTES,
    )

    assert reading is not snapshot
    assert reading.options.count((_FakeZmq.MAXMSGSIZE, 2 * 1024 * 1024)) == 1
    assert snapshot.options.count((_FakeZmq.MAXMSGSIZE, 8 * 1024 * 1024)) == 1
    assert reading.actions == [
        ("connect", "tcp://127.0.0.1:5555"),
        ("subscribe", b"readings"),
    ]
    assert snapshot.actions == [
        ("connect", "tcp://127.0.0.1:5555"),
        ("subscribe", b"operator.snapshot"),
    ]


def test_gui_poll_accepts_only_decoded_snapshot_and_tracks_independent_age(monkeypatch) -> None:
    bridge = ZmqBridge()
    bridge._snapshot_queue = queue.Queue(maxsize=2)
    bridge._snapshot_queue.put_nowait(_snapshot(1))
    bridge._snapshot_queue.put_nowait({"optimistic": "ready"})
    bridge._last_heartbeat = 123.0
    bridge._last_reading_time = 456.0
    ticks = iter((1000.0, 1004.0, 1011.0))
    monkeypatch.setattr("cryodaq.gui.zmq_client.time.monotonic", lambda: next(ticks))

    snapshots = bridge.poll_operator_snapshots()

    assert [snapshot.cut.revision for snapshot in snapshots] == [1]
    assert bridge._last_heartbeat == 123.0
    assert bridge._last_reading_time == 456.0
    assert bridge.snapshot_flow_age_s() == 4.0
    assert bridge.snapshot_flow_stalled(timeout_s=10.0) is True
    assert bridge.snapshot_malformed_count == 1
    assert bridge._snapshot_queue.unfinished_tasks == 0


def test_snapshot_cold_start_and_stall_never_change_bridge_restart_health(monkeypatch) -> None:
    bridge = ZmqBridge()
    bridge._process = type("Alive", (), {"is_alive": lambda self: True})()
    bridge._last_heartbeat = 100.0
    monkeypatch.setattr("cryodaq.gui.zmq_client.time.monotonic", lambda: 120.0)

    assert bridge.snapshot_flow_age_s() is None
    assert bridge.snapshot_flow_stalled(timeout_s=1.0) is False
    assert bridge.snapshot_flow_healthy(timeout_s=1.0) is False
    assert bridge.is_healthy() is True

    bridge._last_snapshot_time = 119.5
    assert bridge.snapshot_flow_stalled(timeout_s=1.0) is False
    assert bridge.snapshot_flow_healthy(timeout_s=1.0) is True
    assert bridge.is_healthy() is True

    bridge._last_snapshot_time = 1.0
    assert bridge.snapshot_flow_stalled(timeout_s=1.0) is True
    assert bridge.snapshot_flow_healthy(timeout_s=1.0) is False
    assert bridge.is_healthy() is True


def test_bridge_restart_replaces_snapshot_queue_and_invalidates_old_cut(monkeypatch) -> None:
    class FakeProcess:
        pid = 123

        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

    class FakeThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self._alive = False

    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", FakeProcess)
    monkeypatch.setattr("cryodaq.gui.zmq_client.threading.Thread", FakeThread)
    bridge = ZmqBridge()
    bridge.start()
    old_queue = bridge._snapshot_queue
    old_queue.put(_snapshot(1), timeout=1)
    bridge._process._alive = False
    bridge.start()

    assert bridge._snapshot_queue is not old_queue
    assert bridge.poll_operator_snapshots() == []
    assert bridge.snapshot_flow_age_s() is None


def test_spawn_failure_invalidates_snapshot_age_and_queued_cut_before_attempt(monkeypatch) -> None:
    class FailingProcess:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def is_alive(self) -> bool:
            return False

        def start(self) -> None:
            raise RuntimeError("spawn failed")

    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", FailingProcess)
    bridge = ZmqBridge()
    old_queue = bridge._snapshot_queue
    old_queue.put(_snapshot(9), timeout=1)
    bridge._last_snapshot_time = time.monotonic()
    bridge._last_heartbeat = 111.0
    bridge._last_reading_time = 222.0

    with pytest.raises(RuntimeError, match="spawn failed"):
        bridge.start()

    assert bridge._snapshot_queue is not old_queue
    assert bridge.poll_operator_snapshots() == []
    assert bridge.snapshot_flow_age_s() is None
    assert bridge.snapshot_flow_healthy() is False
    assert bridge._last_heartbeat == 111.0
    assert bridge._last_reading_time == 222.0


def test_restart_cleanup_failure_keeps_drained_old_queue_and_refuses_new_generation(monkeypatch) -> None:
    class BrokenReplyThread:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            raise RuntimeError("reply cleanup failed")

    bridge = ZmqBridge()
    old_queue = queue.Queue(maxsize=2)
    bridge._snapshot_queue = old_queue
    old_queue.put_nowait(_snapshot(4))
    bridge._last_snapshot_time = time.monotonic()
    broken = BrokenReplyThread()
    bridge._reply_consumer = broken
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.mp.JoinableQueue",
        lambda *args, **kwargs: pytest.fail("cleanup failure must not allocate a replacement snapshot queue"),
    )

    with pytest.raises(RuntimeError, match="reply cleanup failed"):
        bridge.start()

    assert bridge._snapshot_queue is old_queue
    assert old_queue.empty()
    assert old_queue.unfinished_tasks == 0
    assert bridge.poll_operator_snapshots() == []
    assert bridge._reply_consumer is broken
    assert bridge._reply_stop.is_set()
    assert bridge._bridge_instance_id is None
    assert bridge._generation == 0
    assert bridge.restart_count() == 0
    assert bridge._last_snapshot_time == 0.0
    assert bridge.snapshot_flow_age_s() is None


def test_shutdown_invalidates_snapshot_flow_without_touching_bridge_health_policy() -> None:
    bridge = ZmqBridge()
    bridge._last_snapshot_time = 123.0
    bridge.shutdown()

    assert bridge._last_snapshot_time == 0.0
    assert bridge.snapshot_flow_age_s() is None


def test_ingress_foundation_has_no_control_remediation_shell_or_store_authority() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "src/cryodaq/core/operator_snapshot_ingress.py",
        root / "src/cryodaq/core/zmq_subprocess.py",
    ]
    imports: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports.update(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)

    assert not any(
        name.startswith(
            (
                "cryodaq.gui.state",
                "cryodaq.gui.shell",
                "cryodaq.safety",
                "cryodaq.drivers",
            )
        )
        for name in imports
    )
