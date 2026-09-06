"""A restatement must not move the alarm's start time (PI-11 follow-up).

`AlarmProjection._apply` REPLACES its active-alarm record with whatever the
latest `alarm_fired` carries, and `_alarm` reads `triggered_at` from the
payload, defaulting to the event's own timestamp when the key is absent. That
default is right for a genuine trigger and wrong for a restatement: the engine
now republishes an alarm that has been active for hours, and without an explicit
activation time the periodic report would say an eleven-hour CRITICAL started an
hour ago — misstating the single fact the restatement exists to convey.
"""

from __future__ import annotations

import time

from cryodaq.agents.assistant.periodic_projection import AlarmProjection


def _fired(alarm_id: str, ts: float, *, triggered_at: float | None, reasserted: bool) -> dict:
    payload: dict[str, object] = {
        "alarm_id": alarm_id,
        "level": "CRITICAL",
        "message": "давление выше порога",
        "channels": ["VSP63D_1"],
        "values": {"VSP63D_1": 6.0e-2},
        "reasserted": reasserted,
    }
    if triggered_at is not None:
        payload["triggered_at"] = triggered_at
    return {"event_type": "alarm_fired", "ts": ts, "payload": payload}


def _install_empty(projection: AlarmProjection, now: float) -> None:
    """Start from a fresh, complete, empty snapshot so events apply directly."""
    cut = projection.capture_receive_cut()
    projection.install_snapshot({"ok": True, "active": {}}, captured_at=now, receive_cut=cut)


def _one_active(projection: AlarmProjection, now: float):
    alarms, complete = projection.freeze(now=now)
    assert complete, "the projection must remain complete across restatements"
    assert len(alarms) == 1, f"expected exactly one active alarm, got {[a.alarm_id for a in alarms]}"
    return alarms[0]


def test_a_restatement_keeps_the_original_activation_time() -> None:
    now = time.time()
    activation = now - 39_600.0  # eleven hours ago

    projection = AlarmProjection()
    _install_empty(projection, now)
    projection.buffer_event(_fired("vacuum_loss_cold", activation, triggered_at=activation, reasserted=False))
    projection.buffer_event(_fired("vacuum_loss_cold", now, triggered_at=activation, reasserted=True))

    alarm = _one_active(projection, now)
    assert alarm.triggered_at == activation, (
        "the restatement must preserve when the alarm STARTED; reporting it as "
        f"having begun at the restatement ({now}) is the defect this pins"
    )


def test_without_an_explicit_activation_the_start_time_moves() -> None:
    """The negative: this is exactly what the payload key prevents.

    Pinning it makes the reason for the key visible — remove it upstream and
    the projection silently re-dates the alarm.
    """
    now = time.time()
    activation = now - 39_600.0

    projection = AlarmProjection()
    _install_empty(projection, now)
    projection.buffer_event(_fired("vacuum_loss_cold", activation, triggered_at=activation, reasserted=False))
    projection.buffer_event(_fired("vacuum_loss_cold", now, triggered_at=None, reasserted=True))

    alarm = _one_active(projection, now)
    assert alarm.triggered_at != activation
    assert abs(alarm.triggered_at - now) < 1.0


def test_a_restatement_does_not_duplicate_the_alarm() -> None:
    now = time.time()
    activation = now - 39_600.0
    projection = AlarmProjection()
    _install_empty(projection, now)
    projection.buffer_event(_fired("vacuum_loss_cold", activation, triggered_at=activation, reasserted=False))
    for offset in (3_600.0, 7_200.0, 10_800.0):
        projection.buffer_event(
            _fired("vacuum_loss_cold", activation + offset, triggered_at=activation, reasserted=True)
        )
    alarm = _one_active(projection, now)
    assert alarm.alarm_id == "vacuum_loss_cold"
    assert alarm.triggered_at == activation
