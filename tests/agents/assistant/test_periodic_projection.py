from __future__ import annotations

import math
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cryodaq.agents.assistant.periodic_projection import (
    AlarmProjection,
    BoundedReadingProjection,
)
from cryodaq.core.zmq_bridge import _pack_event, _unpack_event
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.storage.archive_reader import (
    BoundedReadingQueryResult,
    BoundedReadingRow,
    BoundedReadIssue,
    BoundedReadIssueCode,
)


def _config() -> PeriodicPngConfig:
    return PeriodicPngConfig(
        enabled=True,
        interval_s=1800,
        chart_window_s=7200,
        include_channels=None,
        max_points_per_channel=3,
        max_total_points=4,
        max_input_bytes=65_536,
        render_timeout_s=30.0,
        max_render_attempts=2,
        max_delivery_attempts=2,
        backoff_base_s=1.0,
        backoff_cap_s=10.0,
        telegram_token=SecretStr("test"),
        telegram_chat_id=1,
        telegram_timeout_s=10.0,
        telegram_verify_ssl=True,
        config_fingerprint="sha256:" + "f" * 64,
    )


def _hydration(rows: tuple[BoundedReadingRow, ...], *, complete: bool = True):
    return BoundedReadingQueryResult(
        rows=rows,
        complete=complete,
        truncated=False,
        issues=() if complete else (BoundedReadIssue(BoundedReadIssueCode.DEADLINE, "2026-07-10:sqlite"),),
        issue_overflow=0,
        discovered_channels=("T",),
        rows_examined=len(rows),
        rows_dropped_by_caps=0,
        retained_encoded_bytes=100,
    )


def _reading(at: float, channel: str, value: float = 1.0) -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(at, UTC),
        instrument_id="ls",
        channel=channel,
        value=value,
        unit="K",
    )


def test_subscribe_before_hydrate_merge_has_no_gap_or_duplicate() -> None:
    now = time.time() - 10
    cut = now + 2
    projection = BoundedReadingProjection(_config())
    projection.append_live(_reading(cut, "T", 20.0))
    projection.append_live(_reading(cut + 1, "T", 21.0))
    projection.merge_hydration(
        _hydration(
            (
                BoundedReadingRow(now, "ls", "T", 10.0, "K", "ok"),
                BoundedReadingRow(cut, "ls", "T", 99.0, "K", "ok"),
            )
        ),
        cut=cut,
    )
    frozen = projection.freeze(window_start=now - 1, window_end=cut + 2)
    assert [row.timestamp for row in frozen] == pytest.approx([now, cut, cut + 1])
    assert [row.value for row in frozen] == [10.0, 20.0, 21.0]
    assert projection.snapshot(window_start=now - 1, window_end=cut + 2).history_complete


def test_partial_hydration_is_never_claimed_complete() -> None:
    now = time.time() - 10
    projection = BoundedReadingProjection(_config())
    projection.merge_hydration(
        _hydration((BoundedReadingRow(now, "ls", "T", 1.0, "K", "ok"),), complete=False),
        cut=now + 1,
    )
    snapshot = projection.snapshot(window_start=now - 1, window_end=now + 1)
    assert snapshot.history_complete is False
    assert snapshot.source_errors == ("deadline:2026-07-10:sqlite",)


def test_live_validation_and_caps_are_bounded_and_deterministic() -> None:
    now = time.time() - 20
    projection = BoundedReadingProjection(_config())
    for index in range(6):
        projection.append_live(_reading(now + index, "T", float(index)))
    for index in range(3):
        projection.append_live(_reading(now + 10 + index, "P", float(index)))
    projection.append_live(
        Reading(
            timestamp=datetime.fromtimestamp(now + 20, UTC),
            instrument_id="ls",
            channel="P",
            value=math.nan,
            unit="K",
            status=ChannelStatus.SENSOR_ERROR,
        )
    )
    snapshot = projection.snapshot(window_start=now - 1, window_end=now + 30)
    assert len(snapshot.readings) <= 4
    assert sum(row.channel == "T" for row in snapshot.readings) <= 3
    assert snapshot.readings[-1].value is None
    assert snapshot.bad_points == 1
    assert snapshot.dropped_points > 0


def test_out_of_order_and_future_live_rows_are_rejected_visibly() -> None:
    now = time.time() - 10
    projection = BoundedReadingProjection(_config())
    projection.append_live(_reading(now + 1, "T"))
    projection.append_live(_reading(now, "T"))
    projection.append_live(_reading(time.time() + 1000, "T"))
    snapshot = projection.snapshot(window_start=now - 1, window_end=time.time() + 2000)
    assert len(snapshot.readings) == 1
    assert snapshot.bad_points == 2


def _alarm_payload(triggered: float, message: str = "warm") -> dict[str, object]:
    return {
        "level": "WARNING",
        "message": message,
        "triggered_at": triggered,
        "channels": ["T"],
        "acknowledged": False,
        "acknowledged_at": 0.0,
        "acknowledged_by": "",
    }


def test_alarm_snapshot_then_buffered_events_converge() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.buffer_event(
        {
            "event_type": "alarm_cleared",
            "ts": now + 1,
            "payload": {"alarm_id": "a"},
        }
    )
    projection.buffer_event(
        {
            "event_type": "alarm_fired",
            "ts": now + 2,
            "payload": {"alarm_id": "b", **_alarm_payload(now + 2)},
        }
    )
    projection.install_snapshot(
        {"ok": True, "active": {"a": _alarm_payload(now - 1)}},
        captured_at=now,
        receive_cut=receive_cut,
    )
    alarms, complete = projection.freeze(now=now + 3)
    assert complete is True
    assert [alarm.alarm_id for alarm in alarms] == ["b"]


def test_real_zmq_alarm_payload_and_manager_snapshot_shapes_are_consumed() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now - 1,
        receive_cut=receive_cut,
    )

    fired = _unpack_event(
        _pack_event(
            "alarm_fired",
            datetime.fromtimestamp(now, UTC),
            {
                "alarm_id": "real",
                "level": "WARNING",
                "message": "warm",
                "channels": ["T"],
                "values": {"T": 5.0},
            },
            None,
        )
    )
    assert set(fired) == {"event_type", "ts", "payload", "experiment_id"}
    projection.buffer_event(fired)
    alarms, complete = projection.freeze(now=now + 1)
    assert complete is True
    assert [(alarm.alarm_id, alarm.acknowledged_at) for alarm in alarms] == [("real", None)]

    cleared = _unpack_event(
        _pack_event(
            "alarm_cleared",
            datetime.fromtimestamp(now + 2, UTC),
            {"alarm_id": "real"},
            None,
        )
    )
    projection.buffer_event(cleared)
    assert projection.freeze(now=now + 3) == ((), True)


def test_alarm_acknowledgement_relations_match_manager_defaults_and_fail_closed() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {"a": _alarm_payload(now)}},
        captured_at=now,
        receive_cut=receive_cut,
    )
    alarms, complete = projection.freeze(now=now + 1)
    assert complete is True
    assert alarms[0].acknowledged is False
    assert alarms[0].acknowledged_at is None

    inconsistent = _alarm_payload(now)
    inconsistent["acknowledged_at"] = now
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {"a": inconsistent}},
        captured_at=now + 2,
        receive_cut=receive_cut,
    )
    assert projection.freeze(now=now + 3)[1] is False

    acknowledged = _alarm_payload(now)
    acknowledged.update({"acknowledged": True, "acknowledged_at": now + 3, "acknowledged_by": ""})
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {"a": acknowledged}},
        captured_at=now + 3,
        receive_cut=receive_cut,
    )
    alarms, complete = projection.freeze(now=now + 4)
    assert complete is True
    assert alarms[0].acknowledged_at == now + 3


def test_lost_alarm_event_is_repaired_by_resnapshot() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {"a": _alarm_payload(now)}},
        captured_at=now,
        receive_cut=receive_cut,
    )
    assert [alarm.alarm_id for alarm in projection.freeze(now=now + 1)[0]] == ["a"]
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now + 2,
        receive_cut=receive_cut,
    )
    assert projection.freeze(now=now + 3) == ((), True)


def test_unavailable_or_stale_alarm_snapshot_is_not_no_alarms() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot({"ok": False}, captured_at=now, receive_cut=receive_cut)
    assert projection.freeze(now=now) == ((), False)
    receive_cut = projection.capture_receive_cut()
    projection.install_snapshot({"ok": True, "active": {}}, captured_at=now, receive_cut=receive_cut)
    assert projection.freeze(now=now + 301) == ((), False)


def test_alarm_buffer_overflow_after_receive_cut_never_restores_completeness() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.buffer_event(
        {
            "event_type": "alarm_fired",
            "ts": now,
            "payload": {"alarm_id": "x", **_alarm_payload(now)},
        }
    )
    for index in range(256):
        projection.buffer_event(
            {
                "event_type": "alarm_cleared",
                "ts": now + index / 10,
                "payload": {"alarm_id": f"unrelated-{index}"},
            }
        )
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now,
        receive_cut=receive_cut,
    )
    assert projection.freeze(now=now + 30)[1] is False


def test_receive_sequence_replays_clock_regressed_post_cut_event() -> None:
    now = time.time()
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.buffer_event(
        {
            "event_type": "alarm_fired",
            "ts": now - 100,
            "payload": {"alarm_id": "x", **_alarm_payload(now - 100)},
        }
    )
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now,
        receive_cut=receive_cut,
    )
    alarms, complete = projection.freeze(now=now + 1)
    assert complete is True
    assert [alarm.alarm_id for alarm in alarms] == ["x"]


def test_snapshot_cut_is_unique_and_rejects_overlap_and_stale_response() -> None:
    now = time.time()
    projection = AlarmProjection()
    first = projection.capture_receive_cut()
    with pytest.raises(RuntimeError):
        projection.capture_receive_cut()
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now,
        receive_cut=first,
    )

    second = projection.capture_receive_cut()
    assert second.generation > first.generation
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now + 1,
        receive_cut=first,
    )
    projection.install_snapshot(
        {"ok": True, "active": {"a": _alarm_payload(now)}},
        captured_at=now + 1,
        receive_cut=second,
    )
    alarms, complete = projection.freeze(now=now + 2)
    assert complete is True
    assert [alarm.alarm_id for alarm in alarms] == ["a"]


def test_snapshot_strict_bool_and_source_error_cap() -> None:
    now = time.time() - 10
    projection = BoundedReadingProjection(_config())
    issues = tuple(BoundedReadIssue(BoundedReadIssueCode.INVALID_ROW, f"source-{index}") for index in range(32))
    projection.merge_hydration(
        BoundedReadingQueryResult(
            rows=(),
            complete=False,
            truncated=False,
            issues=issues,
            issue_overflow=4,
            discovered_channels=(),
            rows_examined=0,
            rows_dropped_by_caps=0,
            retained_encoded_bytes=0,
        ),
        cut=now,
    )
    snapshot = projection.snapshot(window_start=now - 1, window_end=now + 1)
    assert len(snapshot.source_errors) == 32
    assert snapshot.source_errors[-1] == "issue_overflow:4"
    with pytest.raises(TypeError):
        projection.snapshot(
            window_start=now - 1,
            window_end=now + 1,
            alarm_state_complete=1,  # type: ignore[arg-type]
        )


def test_include_channel_filter_is_applied_before_retention() -> None:
    now = time.time() - 10
    projection = BoundedReadingProjection(replace(_config(), include_channels=("T",)))
    projection.append_live(_reading(now, "P"))
    projection.append_live(_reading(now, "T"))
    assert [row.channel for row in projection.freeze(window_start=now - 1, window_end=now + 1)] == ["T"]


def test_unique_channel_churn_keeps_all_live_bookkeeping_structurally_bounded() -> None:
    now = time.time() - 20_000
    projection = BoundedReadingProjection(replace(_config(), max_points_per_channel=2, max_total_points=2))
    for index in range(10_000):
        projection.append_live(_reading(now + index, f"C{index}"))
    assert len(projection._entries) == 2
    assert len(projection._channel_counts) == 2
    assert len(projection._channel_heaps) == 2
    assert len(projection._latest_live_by_channel) == 64
    assert len(projection._known_channels) == 64
    assert len(projection._global_heap) <= 2 * len(projection._entries) + 64
    assert sum(map(len, projection._channel_heaps.values())) <= 2 * len(projection._entries) + 2 * 64


def test_large_budget_unique_channel_churn_fails_visible_at_hard_64() -> None:
    now = time.time() - 20_000
    projection = BoundedReadingProjection(
        replace(
            _config(),
            max_points_per_channel=100_000,
            max_total_points=100_000,
            max_input_bytes=32 * 1024 * 1024,
        )
    )
    projection.merge_hydration(
        replace(_hydration(()), discovered_channels=()),
        cut=now,
    )
    for index in range(10_000):
        projection.append_live(_reading(now + index, f"C{index}"))
    snapshot = projection.snapshot(
        window_start=now - 1,
        window_end=now + 10_001,
    )
    assert len(snapshot.readings) == 64
    assert {row.channel for row in snapshot.readings} == {f"C{index}" for index in range(64)}
    assert snapshot.history_complete is False
    assert snapshot.source_errors == ("live_channel_limit",)
    assert snapshot.dropped_points == 10_000 - 64
    assert len(projection._entries) == 64
    assert len(projection._known_channels) == 64
    assert len(projection._channel_counts) == 64
    assert len(projection._channel_heaps) == 64
    assert len(projection._latest_live_by_channel) == 64
    assert len(projection._global_heap) <= 2 * 64 + 64
    assert sum(map(len, projection._channel_heaps.values())) <= 64 * 3


def test_projection_clean_import_excludes_storage_writer_and_heavy_modules() -> None:
    code = """
import sys
import cryodaq.agents.assistant.periodic_projection
for name in (
    'cryodaq.storage.sqlite_writer',
    'cryodaq.storage.archive_reader',
    'yaml', 'matplotlib', 'aiohttp', 'numpy',
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
