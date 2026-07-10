"""Closed canonical alarm authority for the periodic PNG runtime."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace

import pytest

from cryodaq.core.alarm_v2 import (
    AlarmEvent,
    AlarmSnapshotUnavailableError,
    AlarmStateManager,
)


def _event(
    alarm_id: str,
    *,
    level: str = "WARNING",
    triggered_at: float = 100.0,
    channels: list[str] | None = None,
) -> AlarmEvent:
    return AlarmEvent(
        alarm_id=alarm_id,
        level=level,
        message="operator-only detail",
        triggered_at=triggered_at,
        channels=list(channels or ["T1"]),
        values={"T1": 4.2},
    )


def _activate(manager: AlarmStateManager, event: AlarmEvent) -> None:
    assert manager.process(event.alarm_id, event, {}) == "TRIGGERED"


def test_revision_covers_every_active_mutation_and_skips_noops() -> None:
    manager = AlarmStateManager()
    assert manager.state_revision == 0

    event = _event("normal")
    _activate(manager, event)
    assert manager.state_revision == 1
    assert manager.process("normal", event, {}) is None
    assert manager.state_revision == 1

    assert manager.acknowledge("normal", operator="op", reason="private") is not None
    assert manager.state_revision == 2
    assert manager.acknowledge("normal") is None
    assert manager.acknowledge("missing") is None
    assert manager.state_revision == 2

    assert manager.process("normal", None, {}) == "CLEARED"
    assert manager.state_revision == 3
    assert manager.process("normal", None, {}) is None
    assert manager.state_revision == 3

    assert manager.publish_diagnostic_alarm("T2", "warning", 300.0) is not None
    assert manager.state_revision == 4
    assert manager.publish_diagnostic_alarm("T2", "warning", 301.0) is None
    assert manager.state_revision == 4

    assert manager.publish_diagnostic_alarm("T2", "critical", 900.0) is not None
    assert manager.state_revision == 5
    assert manager.publish_diagnostic_alarm("T2", "critical", 901.0) is None
    assert manager.publish_diagnostic_alarm("T2", "warning", 901.0) is None
    assert manager.state_revision == 5

    manager.clear_diagnostic_alarm("T2")
    assert manager.state_revision == 6
    manager.clear_diagnostic_alarm("T2")
    assert manager.state_revision == 6


def test_sustained_tracking_is_not_an_active_state_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AlarmStateManager()
    monkeypatch.setattr("cryodaq.core.alarm_v2.time.time", lambda: 10.0)
    assert manager.process("slow", _event("slow"), {"sustained_s": 30.0}) is None
    assert manager.state_revision == 0
    assert manager.process("slow", None, {"sustained_s": 30.0}) is None
    assert manager.state_revision == 0


def test_trigger_then_clear_restores_token_but_advances_revision() -> None:
    manager = AlarmStateManager()
    before = manager.snapshot_active_canonical()
    _activate(manager, _event("roundtrip"))
    assert manager.process("roundtrip", None, {}) == "CLEARED"
    after = manager.snapshot_active_canonical()

    assert before.active == after.active == {}
    assert before.state_token == after.state_token
    assert before.state_revision == 0
    assert after.state_revision == 2


def test_canonical_token_is_order_independent_and_mapping_is_exact() -> None:
    left = AlarmStateManager()
    right = AlarmStateManager()
    _activate(left, _event("z", level="CRITICAL", channels=["T2", "T1", "T1"]))
    _activate(left, _event("a", channels=["P1"]))
    _activate(right, _event("a", channels=["P1"]))
    _activate(right, _event("z", level="CRITICAL", channels=["T1", "T2"]))

    left_snapshot = left.snapshot_active_canonical()
    right_snapshot = right.snapshot_active_canonical()
    assert left_snapshot.state_token == right_snapshot.state_token
    assert list(left_snapshot.active) == ["a", "z"]
    assert left_snapshot.active["z"] == {
        "level": "CRITICAL",
        "triggered_at": 100.0,
        "channels": ["T1", "T2"],
        "acknowledged": False,
        "acknowledged_at": None,
    }
    canonical = json.dumps(
        left_snapshot.active,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert left_snapshot.state_token == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert len(left_snapshot.state_token) == 71


def test_acknowledged_snapshot_has_only_minimal_public_fields() -> None:
    manager = AlarmStateManager()
    event = _event("private")
    event.message = "secret message"
    event.values = {"password": 123.0}
    _activate(manager, event)
    assert manager.acknowledge("private", operator="alice", reason="secret reason")

    snapshot = manager.snapshot_active_canonical()
    public = snapshot.active["private"]
    assert set(public) == {
        "level",
        "triggered_at",
        "channels",
        "acknowledged",
        "acknowledged_at",
    }
    assert public["acknowledged"] is True
    assert isinstance(public["acknowledged_at"], float)
    encoded = repr(snapshot.active)
    for forbidden in ("secret message", "password", "alice", "secret reason", "values"):
        assert forbidden not in encoded


def test_excluded_hostile_message_and_values_are_never_walked_or_serialized() -> None:
    manager = AlarmStateManager()
    event = _event("hostile-private")
    event.message = object()  # type: ignore[assignment]
    event.values = {"recursive": None}  # type: ignore[dict-item]
    event.values["recursive"] = event.values  # type: ignore[assignment]
    event.destination = "https://secret.invalid/token"  # type: ignore[attr-defined]
    manager._active[event.alarm_id] = event

    snapshot = manager.snapshot_active_canonical()
    assert snapshot.active[event.alarm_id]["channels"] == ["T1"]
    assert "recursive" not in repr(snapshot.active)
    assert "secret.invalid" not in repr(snapshot.active)


def test_get_active_and_snapshot_returns_cannot_mutate_authority() -> None:
    manager = AlarmStateManager()
    original = _event("detached", channels=["T1", "T2"])
    _activate(manager, original)
    before = manager.snapshot_active_canonical()

    returned = manager.get_active()
    returned["detached"].level = "CRITICAL"
    returned["detached"].channels.append("EVIL")
    returned["detached"].values["EVIL"] = 999.0
    returned.clear()
    before.active["detached"]["channels"].append("EVIL")
    before.active.clear()

    after = manager.snapshot_active_canonical()
    assert after.state_revision == 1
    assert after.active["detached"]["level"] == "WARNING"
    assert after.active["detached"]["channels"] == ["T1", "T2"]
    assert after.state_token == before.state_token
    assert after.state_token == manager.snapshot_active_canonical().state_token


def test_trigger_input_and_diagnostic_return_do_not_leak_internal_identity() -> None:
    manager = AlarmStateManager()
    submitted = _event("submitted")
    _activate(manager, submitted)
    submitted.level = "CRITICAL"
    submitted.channels.append("EVIL")
    assert manager.get_active()["submitted"].level == "WARNING"
    assert manager.get_active()["submitted"].channels == ["T1"]

    returned = manager.publish_diagnostic_alarm("T2", "warning", 300.0)
    assert returned is not None
    returned.level = "CRITICAL"
    returned.channels.append("EVIL")
    assert manager.get_active()["diag:T2"].level == "WARNING"
    assert manager.get_active()["diag:T2"].channels == ["T2"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("level", 1),
        ("level", "EMERGENCY"),
        ("triggered_at", True),
        ("triggered_at", -1.0),
        ("triggered_at", math.nan),
        ("triggered_at", math.inf),
        ("channels", [1]),
        ("channels", [f"T{index}" for index in range(65)]),
        ("channels", ["T1"] * 65),
        ("acknowledged", 1),
        ("acknowledged_at", math.nan),
        ("acknowledged_at", -1.0),
    ],
)
def test_invalid_active_schema_fails_with_fixed_domain_exception(field: str, value: object) -> None:
    manager = AlarmStateManager()
    event = _event("hostile")
    if field == "acknowledged_at":
        event.acknowledged = True
    setattr(event, field, value)
    manager._active["hostile"] = event

    with pytest.raises(AlarmSnapshotUnavailableError, match="^alarm snapshot unavailable$"):
        manager.snapshot_active_canonical()


@pytest.mark.parametrize(
    ("alarm_id", "channel"),
    [
        ("a" * 257, "T1"),
        ("alarm", "T" * 257),
        ("é" * 127 + "abc", "T1"),
        ("alarm", "é" * 127 + "abc"),
        ("alarm\x00", "T1"),
        ("alarm", "T1\x00"),
        ("alarm", "\ud800"),
    ],
)
def test_excessive_or_control_text_is_rejected(alarm_id: str, channel: str) -> None:
    manager = AlarmStateManager()
    event = _event(alarm_id, channels=[channel])
    manager._active[alarm_id] = event
    with pytest.raises(AlarmSnapshotUnavailableError):
        manager.snapshot_active_canonical()


def test_multibyte_text_exact_256_utf8_bytes_is_allowed() -> None:
    manager = AlarmStateManager()
    alarm_id = "é" * 128
    manager._active[alarm_id] = _event(alarm_id, channels=["Т" * 128])
    snapshot = manager.snapshot_active_canonical()
    assert list(snapshot.active) == [alarm_id]


def test_fixed_domain_exception_suppresses_hostile_cause_chain() -> None:
    manager = AlarmStateManager()
    manager._active["hostile"] = _event("hostile", channels=["\ud800"])
    with pytest.raises(AlarmSnapshotUnavailableError) as caught:
        manager.snapshot_active_canonical()
    assert caught.value.__cause__ is None


def test_alarm_mapping_key_must_match_event_id() -> None:
    manager = AlarmStateManager()
    manager._active["outer"] = _event("inner")
    with pytest.raises(AlarmSnapshotUnavailableError):
        manager.snapshot_active_canonical()


def test_128_active_is_allowed_and_129_is_rejected() -> None:
    manager = AlarmStateManager()
    for index in range(128):
        _activate(manager, _event(f"a-{index:03d}"))
    assert len(manager.snapshot_active_canonical().active) == 128

    _activate(manager, _event("overflow"))
    with pytest.raises(AlarmSnapshotUnavailableError):
        manager.snapshot_active_canonical()


def _manager_with_exact_canonical_size(extra_channel_chars: int) -> AlarmStateManager:
    """128 alarms × 16 channels: 895 extra chars makes exactly 60 KiB."""
    manager = AlarmStateManager()
    ordinal = 0
    for alarm_index in range(128):
        channels = []
        for channel_index in range(16):
            extra = "y" if ordinal < extra_channel_chars else ""
            channels.append(f"{channel_index:02d}-" + "x" * 17 + extra)
            ordinal += 1
        alarm_id = f"a{alarm_index:03d}"
        manager._active[alarm_id] = _event(alarm_id, channels=channels)
    return manager


def test_canonical_json_exact_60_kib_allowed_and_larger_rejected() -> None:
    at_limit = _manager_with_exact_canonical_size(895)
    assert at_limit.snapshot_active_canonical().state_token.startswith("sha256:")

    over_limit = _manager_with_exact_canonical_size(896)
    with pytest.raises(AlarmSnapshotUnavailableError):
        over_limit.snapshot_active_canonical()


def test_snapshot_dataclass_is_frozen() -> None:
    snapshot = AlarmStateManager().snapshot_active_canonical()
    with pytest.raises(AttributeError):
        replace(snapshot, state_revision=1).state_revision = 2  # type: ignore[misc]
