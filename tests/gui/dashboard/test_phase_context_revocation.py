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


def _configured_dashboard(tmp_path, monkeypatch, *, cadence_s: float) -> DashboardView:
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
            "current_phase": "cooldown",
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


def test_usable_foreign_same_suffix_does_not_take_over_the_slot(app, tmp_path, monkeypatch) -> None:
    """A usable same-suffix reading must not transfer slot ownership.

    A foreign producer that merely reuses the recognized suffix must not replace
    the shipped predictor's value and identity; otherwise the shipped producer's
    later failures become invisible (its unusable update no longer matches the
    slot's producer).
    """
    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    shipped = _eta_reading(datetime.now(UTC), cadence_s=30.0)
    view.on_reading(shipped)
    assert STALE_MARK not in view._phase_widget._context_label.text(), "premise: shipped value starts fresh"

    foreign = replace(
        shipped,
        instrument_id="site_predictor",
        channel="analytics/site/cooldown_eta",
        value=99.0,
    )
    view.on_reading(foreign)

    widget = view._phase_widget
    assert widget._cached_producer["eta"] == (shipped.instrument_id, shipped.channel), (
        "a usable foreign producer took over the eta slot"
    )
    assert widget._cached_eta_s == pytest.approx(2.0 * 3600), "a usable foreign value replaced the shipped value"

    # The shipped producer fails after the foreign takeover attempt — its
    # failure must still invalidate the slot.
    broken = replace(shipped, status=ChannelStatus.SENSOR_ERROR, value=float("nan"))
    view.on_reading(broken)
    assert STALE_MARK in view._phase_widget._context_label.text(), (
        "the shipped producer's failure became invisible after a foreign takeover attempt"
    )


def test_foreign_producer_cannot_claim_a_slot_before_the_declared_producer_arrives(app, tmp_path, monkeypatch) -> None:
    """A first-arriving foreign producer must not own the eta slot.

    First-arrival binding gave a site analytics plugin permanent ownership of a
    slot it reached first (its one-second output arriving before the shipped
    predictor's first 30 s prediction) and ignored every later shipped value.
    The slot is bound to its declared producer before any reading is accepted.
    """
    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    widget = view._phase_widget

    foreign = replace(
        _eta_reading(datetime.now(UTC), cadence_s=1.0),
        instrument_id="site_predictor",
        channel="analytics/site/cooldown_eta",
        value=99.0,
    )
    view.on_reading(foreign)

    assert widget._cached_producer.get("eta") is None, "a first-arriving foreign producer claimed the unbound eta slot"
    assert "ETA" not in widget._context_label.text(), "a foreign value rendered in the eta slot"

    shipped = _eta_reading(datetime.now(UTC), cadence_s=30.0)
    view.on_reading(shipped)

    assert widget._cached_producer["eta"] == (shipped.instrument_id, shipped.channel), (
        "the declared producer could not claim its own slot after a foreign arrival"
    )
    assert widget._cached_eta_s == pytest.approx(2.0 * 3600), (
        "the shipped value was ignored after the foreign producer arrived first"
    )


def test_analytics_pressure_cannot_claim_the_physical_pressure_slot(app, tmp_path, monkeypatch) -> None:
    """An analytics value can never own the pressure slot, even when first."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    widget = view._phase_widget

    analytics_pressure = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="site_predictor",
        channel="analytics/site/pressure",
        value=2.0,
        unit="mbar",
        status=ChannelStatus.OK,
        metadata={"source": "analytics", "producer_interval_s": 1.0, "source_age_s": 0.0},
    )
    view.on_reading(analytics_pressure)
    assert widget._cached_producer.get("pressure") is None, "an analytics value claimed the pressure slot"

    gauge = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=1.5e-6,
        unit="mbar",
        status=ChannelStatus.OK,
        metadata={"producer_interval_s": 2.0, "source_age_s": 0.0},
    )
    view.on_reading(gauge)
    assert widget._cached_producer["pressure"] == ("VSP63D_1", "VSP63D_1/pressure"), (
        "the physical gauge feed could not claim the pressure slot"
    )
    assert widget._cached_pressure == pytest.approx(1.5e-6)


def test_gui_queue_age_follows_declared_cadence_not_channel_spelling(monkeypatch) -> None:
    """GUI queue residence must age a cadence-declared reading regardless of spelling.

    The engine-side publisher classifies transport age by the declared
    ``producer_interval_s`` (see ``test_source_age_follows_declared_producer_cadence_not_channel_spelling``),
    not by an ``analytics/`` prefix. The GUI-side reconstruction must classify
    the same way: a renamed derived channel must not lose its queue residence,
    and a channel that merely looks derived without declaring a cadence must
    not be awarded one.
    """
    received_key = subprocess_module.READING_RECEIVED_MONOTONIC_KEY
    monkeypatch.setattr(client_module, "time", SimpleNamespace(monotonic=lambda: 1004.0))

    declared = {
        "timestamp": datetime(2026, 7, 10, tzinfo=UTC).timestamp(),
        "instrument_id": "thermal_calculator",
        "channel": "renamed-derived/thermal/R_thermal",
        "value": 4.2,
        "unit": "K/W",
        "status": ChannelStatus.OK.value,
        "raw": None,
        "metadata": {"producer_interval_s": 1.0, "source_age_s": 0.5},
        received_key: 1000.0,
    }
    spelling_only = dict(declared)
    spelling_only.update(
        {
            "instrument_id": "unclassified_source",
            "channel": "analytics/looks-derived-but-is-not-declared",
            "metadata": {},
        }
    )

    declared_reading = client_module._reading_from_dict(declared)
    spelling_reading = client_module._reading_from_dict(spelling_only)

    assert declared_reading.metadata["source_age_s"] == pytest.approx(4.5), (
        "four seconds of GUI queue residence was not added to the declared cadence reading"
    )
    assert "source_age_s" not in spelling_reading.metadata, "a cadence-less channel spelling was awarded a source age"
