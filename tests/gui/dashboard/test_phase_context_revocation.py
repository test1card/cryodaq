"""OC-004 — a dead producer's last analytics value must stop reading as current.

MEASURED, not assumed. `_cached_eta_s`, `_cached_r_thermal` and
`_cached_pressure` were assigned on every matching reading and cleared in
exactly two places: when the experiment ID changes, and when the widget goes
inactive. Neither fires while ONE experiment stays active and its analytics
producer dies -- so the last number kept rendering as current, unmarked, for as
long as the window stayed open.

That is OC-004's stated consequence word for word: "an operator can read a
frozen temperature, pressure or source value after its producer has died."

MARKED, NOT HIDDEN. The stale value stays on screen with a mark rather than
disappearing. A metric that silently vanishes is no better than one that
silently lies -- a vanished readout is what caused revert `0bea0449`.
"""

from __future__ import annotations

import asyncio
import os
import queue
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import msgpack
import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core import zmq_subprocess as subprocess_module
from cryodaq.core.channel_manager import ChannelManager
from cryodaq.core.zmq_bridge import ZMQPublisher, _pack_reading
from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, _decode_reading_frames
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui import zmq_client as client_module
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.dashboard import phase_aware_widget as module
from cryodaq.gui.zmq_client import ZmqBridge

STALE_MARK = "устарело"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _set_clock(monkeypatch, now: float) -> None:
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now), raising=False)


def _configured_dashboard(tmp_path, monkeypatch, *, cadence_s: float, phase: str = "cooldown") -> DashboardView:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cooldown.yaml").write_text(
        f"cooldown:\n  predict_interval_s: {cadence_s}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    view = DashboardView(ChannelManager())
    view._phase_widget.on_status_update(
        {
            "active_experiment": {"experiment_id": "exp-1"},
            "current_phase": phase,
            "phase_started_at": 1.0,
            "phases": [],
        }
    )
    return view


class _PublisherSocket:
    def __init__(self) -> None:
        self.frames: list[list[bytes]] = []

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.frames.append(frames)


def _eta_reading(
    timestamp: datetime,
    value: float = 2.0,
    *,
    cadence_s: float | None = 30.0,
    source_age_s: float | None = 0.0,
) -> Reading:
    source_metadata = {}
    if cadence_s is not None:
        source_metadata["producer_interval_s"] = cadence_s
    if source_age_s is not None:
        source_metadata["source_age_s"] = source_age_s
    source = Reading(
        timestamp=timestamp,
        instrument_id="cooldown_predictor",
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=value,
        unit="h",
        metadata=source_metadata,
    )
    socket = _PublisherSocket()
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._session_id = "test-session"
    publisher._running = True
    asyncio.run(publisher._publish_reading(source))
    payload = msgpack.unpackb(socket.frames[0][1], raw=False)
    if cadence_s is not None:
        assert payload["meta"]["producer_interval_s"] == cadence_s
    if source_age_s is not None:
        assert payload["meta"]["source_age_s"] == source_age_s
    if source_age_s is None:
        payload["meta"].pop("source_age_s", None)
    return Reading(
        timestamp=datetime.fromtimestamp(payload["ts"], tz=UTC),
        instrument_id=payload["iid"],
        channel=payload["ch"],
        value=payload["v"],
        unit=payload["u"],
        status=ChannelStatus(payload["st"]),
        raw=payload.get("raw"),
        metadata=payload["meta"],
    )


def _pressure_reading(
    timestamp: datetime,
    value: float = 2.0,
    *,
    cadence_s: float | None = 1.0,
    source_age_s: float | None = 0.5,
) -> Reading:
    """The shipped physical pressure feed, produced with declared cadence+age."""
    source_metadata = {}
    if cadence_s is not None:
        source_metadata["producer_interval_s"] = cadence_s
    if source_age_s is not None:
        source_metadata["source_age_s"] = source_age_s
    source = Reading(
        timestamp=timestamp,
        instrument_id="thyracont_vsp63d",
        channel="VSP63D_1/pressure",
        value=value,
        unit="mbar",
        metadata=source_metadata,
    )
    socket = _PublisherSocket()
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._session_id = "test-session"
    publisher._running = True
    asyncio.run(publisher._publish_reading(source))
    payload = msgpack.unpackb(socket.frames[0][1], raw=False)
    return Reading(
        timestamp=datetime.fromtimestamp(payload["ts"], tz=UTC),
        instrument_id=payload["iid"],
        channel=payload["ch"],
        value=payload["v"],
        unit=payload["u"],
        status=ChannelStatus(payload["st"]),
        raw=payload.get("raw"),
        metadata=payload["meta"],
    )


def test_a_delayed_source_sample_arrives_already_marked_stale(app, tmp_path, monkeypatch) -> None:
    """A broker/UI backlog must not reset a dead sample's source age."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC), source_age_s=181.0))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK in text, (
        "a source-aged cooldown ETA was blessed as fresh when it arrived through the dashboard route"
    )


def test_stale_metric_uses_canonical_chrome_and_shape(app, tmp_path, monkeypatch) -> None:
    """Stale analytics pair legible text with STATUS_STALE shape/color chrome."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC), source_age_s=181.0))

    text = view._phase_widget._context_label.text()
    assert "2ч" in text, "stale chrome hid the retained cooldown ETA"
    assert "◇ устарело" in text, "stale analytics have no static shape/text cue"
    assert f"border:1px solid {theme.STATUS_STALE}" in text, "stale analytics do not use canonical STATUS_STALE chrome"


def test_configured_slow_healthy_predictor_is_not_marked_before_next_publication(app, tmp_path, monkeypatch) -> None:
    """A healthy 180 s producer remains current 181 s after publication."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=180.0)
    view.on_reading(_eta_reading(datetime.now(UTC), cadence_s=180.0))

    _set_clock(monkeypatch, 1181.0)
    view._phase_widget._duration_timer.timeout.emit()

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK not in text, (
        "a healthy 180 s cooldown predictor was marked stale before its next dashboard publication"
    )


def test_the_mark_is_per_value_not_per_widget(app, tmp_path, monkeypatch) -> None:
    """One dead producer must not make another producer's live value read stale."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="thermal_calculator",
            channel="analytics/thermal_calculator/R_thermal",
            value=4.5,
            unit="K/W",
            metadata={"producer_interval_s": 30.0, "source_age_s": 0.0},
        )
    )

    _set_clock(monkeypatch, 1181.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))

    text = view._phase_widget._context_label.text()
    assert text.count(STALE_MARK) == 1, (
        f"expected exactly the dead feed to be marked, got {text.count(STALE_MARK)} marks in {text!r}"
    )
    assert "ETA" in text and "R" in text, "both metrics must stay visible; marking is not hiding"


def test_each_metric_expires_on_its_own_producer_cadence(app, tmp_path, monkeypatch) -> None:
    """A slow ETA producer must not mask a dead faster thermal feed."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=600.0)
    view.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="thermal_calculator",
            channel="analytics/thermal_calculator/R_thermal",
            value=4.5,
            unit="K/W",
            metadata={"producer_interval_s": 1.0, "source_age_s": 0.0},
        )
    )
    view.on_reading(_eta_reading(datetime.now(UTC), cadence_s=600.0))

    _set_clock(monkeypatch, 1004.0)
    view._phase_widget._duration_timer.timeout.emit()

    text = view._phase_widget._context_label.text()
    assert text.count(STALE_MARK) == 1, f"only the dead 1 s thermal feed should be stale: {text!r}"
    assert text.index(STALE_MARK) > text.index(">R "), f"the stale marker belongs to R_thermal: {text!r}"


def test_engine_wall_clock_skew_does_not_age_a_fresh_value(app, tmp_path, monkeypatch) -> None:
    """A producer-reported age is comparable even when Engine wall time is behind."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC) - timedelta(minutes=2), source_age_s=0.0))

    text = view._phase_widget._context_label.text()
    assert STALE_MARK not in text, f"remote wall-clock offset was misread as source age: {text!r}"


def test_gui_queue_residence_cannot_refresh_an_old_transport_value(app, tmp_path, monkeypatch) -> None:
    """Age accumulated after ZMQ receipt must survive the production GUI queue."""

    _set_clock(monkeypatch, 1004.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=1.0)
    reading = _eta_reading(datetime.now(UTC), cadence_s=1.0, source_age_s=0.5)

    monkeypatch.setattr(subprocess_module, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    queued = _decode_reading_frames([DEFAULT_TOPIC, _pack_reading(reading)])
    bridge = ZmqBridge()
    bridge._bridge_instance_id = "a" * 32
    bridge._data_queue = queue.Queue()
    bridge._data_queue.put_nowait(queued)
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: 1004.0))

    [qualified] = bridge.poll_readings_with_descriptor()
    view.on_reading(qualified.reading)

    text = view._phase_widget._context_label.text()
    assert "ETA" in text and "2ч" in text, f"transport delay hid the retained value: {text!r}"
    assert STALE_MARK in text, f"four seconds of GUI queue residence reset a dead 1 s feed to fresh: {text!r}"


def test_fresh_shipped_pressure_reading_is_not_marked_stale(app, tmp_path, monkeypatch) -> None:
    """A first healthy pressure sample with declared cadence+age renders current.

    RESTORED shape (lab PC). The shipped ``VSP63D_1/pressure`` reaches this
    route with no driver-supplied freshness basis; the engine now declares the
    configured poll cadence on the reading, and the engine bridge derives
    ``source_age_s``. With both present, ``_remember_freshness()`` establishes
    a real horizon instead of ``None``/``None`` and the first healthy sample is
    no longer marked stale immediately.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0, phase="vacuum")
    view.on_reading(_pressure_reading(datetime.now(UTC)))

    text = view._phase_widget._context_label.text()
    assert "mbar" in text, f"the pressure route did not render the shipped feed: {text!r}"
    assert STALE_MARK not in text, f"a value that has just arrived was rendered stale: {text!r}"


def test_pressure_queue_residence_is_aged_by_declared_cadence_not_channel_spelling(app, tmp_path, monkeypatch) -> None:
    """A cadence-declared pressure feed keeps its transport age through the GUI queue.

    The publisher contract classifies a cadence reading by ``producer_interval_s``,
    not by an ``analytics/`` channel spelling. A physical feed that declared its
    poll cadence must therefore still get its multiprocessing-queue residence
    folded into ``source_age_s``; otherwise a four-second queue delay presents
    dead pressure as fresh.
    """

    _set_clock(monkeypatch, 1004.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=1.0, phase="vacuum")
    reading = _pressure_reading(datetime.now(UTC), cadence_s=1.0, source_age_s=0.5)

    monkeypatch.setattr(subprocess_module, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    queued = _decode_reading_frames([DEFAULT_TOPIC, _pack_reading(reading)])
    bridge = ZmqBridge()
    bridge._bridge_instance_id = "a" * 32
    bridge._data_queue = queue.Queue()
    bridge._data_queue.put_nowait(queued)
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: 1004.0))

    [qualified] = bridge.poll_readings_with_descriptor()
    view.on_reading(qualified.reading)

    text = view._phase_widget._context_label.text()
    assert "mbar" in text, f"transport delay hid the retained pressure: {text!r}"
    assert STALE_MARK in text, f"four seconds of GUI queue residence reset a dead 1 s pressure feed to fresh: {text!r}"


def test_overflowed_producer_horizon_fails_closed_to_stale(app, tmp_path, monkeypatch) -> None:
    """A finite cadence whose multiplier overflows must not become forever fresh."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=1e308)
    view.on_reading(_eta_reading(datetime.now(UTC), cadence_s=1e308, source_age_s=0.0))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text and "2ч" in text, f"invalid freshness metadata hid the retained value: {text!r}"
    assert STALE_MARK in text, f"an infinite stale horizon rendered as healthy: {text!r}"


def test_missing_source_age_is_visible_and_not_rendered_healthy(app, tmp_path, monkeypatch) -> None:
    """Unknown provenance retains the value but must fail closed to stale."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC), source_age_s=None))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text and "2ч" in text, f"missing provenance hid the retained value: {text!r}"
    assert STALE_MARK in text, f"missing source age rendered as healthy: {text!r}"


def test_a_fresh_analytics_value_is_not_marked(app, tmp_path, monkeypatch) -> None:
    """RESTORED. A registered guard, deleted while unrelated findings were fixed.

    `STALE-ANALYTICS-RENDERED-AS-CURRENT-344` names this node. Without it the
    mark has no negative case at all, so a change that marked EVERYTHING stale
    would satisfy every remaining node — and a mark that fires on healthy data
    teaches an operator to ignore the mark, which is its own harm.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK not in text, "a value that has just arrived was rendered stale"


def test_a_value_whose_producer_died_is_marked_while_the_experiment_stays_active(app, tmp_path, monkeypatch) -> None:
    """RESTORED, and this one guards OC-004's actual defect.

    `STALE-ANALYTICS-RENDERED-AS-CURRENT-344` names it. The cached value was
    revoked only when the EXPERIMENT changed, so a producer that died inside a
    live experiment left its last number rendering as current for as long as the
    operator's window stayed open. Deleting this node left the defect this PR
    exists to fix with no guard on its own behaviour.

    Time advances past the horizon while the experiment stays active and no
    further reading arrives — the death path, as distinct from the delayed
    arrival path the sibling node covers.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))
    assert STALE_MARK not in view._phase_widget._context_label.text(), "premise: it must start unmarked"

    # The producer stops. Nothing changes except the clock, and the experiment
    # is never switched — which is precisely the case the old code missed.
    _set_clock(monkeypatch, 1000.0 + 3.0 * 30.0 + 1.0)
    view._phase_widget._duration_timer.timeout.emit()

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the retained value vanished instead of being marked"
    assert STALE_MARK in text, (
        "a producer died inside a live experiment and its last value is still presented as current: "
        "this is the frozen readout OC-004 names"
    )


@pytest.mark.parametrize(
    ("value", "status"),
    [(float("nan"), ChannelStatus.OK), (1.0, ChannelStatus.SENSOR_ERROR), (1.0, ChannelStatus.TIMEOUT)],
)
def test_unusable_analytics_reading_does_not_refresh_freshness(
    app, tmp_path, monkeypatch, value: float, status: ChannelStatus
) -> None:
    """The dashboard must use Reading.is_usable as its authoritative gate."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC), value=2.0))
    view.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="cooldown_predictor",
            channel="analytics/cooldown_predictor/cooldown_eta",
            value=value,
            unit="h",
            status=status,
            metadata={"producer_interval_s": 30.0, "source_age_s": 0.0},
        )
    )

    _set_clock(monkeypatch, 1091.0)
    view._phase_widget._duration_timer.timeout.emit()
    text = view._phase_widget._context_label.text()
    assert "2ч" in text, "the last usable ETA should remain visible"
    assert STALE_MARK in text, f"unusable {status.value} reading refreshed a live freshness stamp"


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (float("nan"), ChannelStatus.OK),
        (1.0, ChannelStatus.SENSOR_ERROR),
        (1.0, ChannelStatus.TIMEOUT),
    ],
)
def test_an_unusable_update_invalidates_freshness_immediately(
    app, tmp_path, monkeypatch, value: float, status: ChannelStatus
) -> None:
    """A feed that reports ITSELF broken must not keep reading as current.

    The cadence horizon covers a producer that goes QUIET. It does not cover one
    that publishes `SENSOR_ERROR`/`TIMEOUT` with the NaN sentinel: that update
    used to hit an early `return` which left the previous freshness stamp
    intact, so the last good value kept rendering as current for up to another
    cadence window -- 90 s at the default ETA cadence -- after the backend had
    already declared the feed unusable.

    MARKED, NOT HIDDEN: the last legible value stays on screen with the stale
    chrome. That is the same rule the badge itself exists to enforce.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)

    fresh = _eta_reading(datetime.now(UTC), cadence_s=30.0)
    view.on_reading(fresh)
    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK not in text, "a freshly published ETA was already marked stale"

    # Production shape: a non-OK status always carries a non-finite sentinel.
    broken = replace(fresh, status=ChannelStatus.SENSOR_ERROR, value=float("nan"))
    assert not broken.is_usable(), "the control reading must be unusable, or it proves nothing"
    view.on_reading(broken)

    text = view._phase_widget._context_label.text()
    assert STALE_MARK in text, (
        "an unusable update left the freshness stamp intact, so the previous ETA still reads as current"
    )
    assert "2ч" in text, "the last legible ETA was hidden instead of marked"


def test_unusable_same_suffix_from_another_producer_does_not_revoke_cached_freshness(
    app, tmp_path, monkeypatch
) -> None:
    """A matching suffix is not authority to invalidate another producer."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    fresh = _eta_reading(datetime.now(UTC), cadence_s=30.0)
    view.on_reading(fresh)

    foreign_failure = replace(
        fresh,
        instrument_id="site_predictor",
        channel="analytics/site/cooldown_eta",
        status=ChannelStatus.SENSOR_ERROR,
        value=float("nan"),
    )
    assert not foreign_failure.is_usable(), "the control reading must be unusable"
    view.on_reading(foreign_failure)

    text = view._phase_widget._context_label.text()
    assert STALE_MARK not in text, "a same-suffix foreign producer revoked the cached ETA"
