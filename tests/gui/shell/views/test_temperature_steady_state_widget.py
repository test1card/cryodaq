"""v0.55.6.1 PART D — TemperatureSteadyStateWidget tests.

Architect 2026-05-07: «в фазе измерения до сих пор R, а не прогноз
по температуре (пусть и асимптотический)». The widget pairs Т11 +
Т12 with their own SteadyStatePredictor and renders the asymptote
+ ±σ band on a single plot during the measurement phase.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views.analytics_widgets import (
    WIDGET_TEMPERATURE_STEADY_STATE,
    TemperatureSteadyStateWidget,
    create,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(channel: str, value: float, ts: float) -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(ts, tz=UTC),
        channel=channel,
        value=value,
        unit="K",
        instrument_id="lakeshore_218s",
    )


# ---------------------------------------------------------------------------
# Construction + registry
# ---------------------------------------------------------------------------


def test_widget_constructs(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    # Two predictor channels by construction (Т11 + Т12).
    assert set(w._predictors) == {"T11", "T12"}
    # Hero readout shows stabilisation placeholder for both rows.
    for label in w._hero_labels.values():
        assert "стабилизация" in label.text().lower()
    w.deleteLater()


def test_widget_registered_in_factory(app: QApplication) -> None:
    """Phase III.C contract: ID is creatable through the registry."""
    w = create(WIDGET_TEMPERATURE_STEADY_STATE)
    assert isinstance(w, TemperatureSteadyStateWidget)
    w.deleteLater()


# ---------------------------------------------------------------------------
# set_temperature_readings — landmark filter
# ---------------------------------------------------------------------------


def test_routes_t12_reading_to_predictor(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({"Т12": _reading("Т12", 4.2, ts=0.0)})
    assert w._buffers["T12"] == [(0.0, 4.2)]
    assert w._buffers["T11"] == []
    w.deleteLater()


def test_routes_t11_reading_to_predictor(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({"Т11": _reading("Т11", 6.1, ts=0.0)})
    assert w._buffers["T11"] == [(0.0, 6.1)]
    assert w._buffers["T12"] == []
    w.deleteLater()


def test_short_id_split_handles_full_channel_names(app: QApplication) -> None:
    """Drivers emit ``"Т12 Криостат верх"``; the split-on-space heuristic
    must reduce that to ``Т12`` before predictor routing.
    """
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings(
        {"Т12 Криостат верх": _reading("Т12 Криостат верх", 4.5, ts=1.0)}
    )
    assert w._buffers["T12"] == [(1.0, 4.5)]
    w.deleteLater()


def test_ignores_non_landmark_channels(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({"Т7": _reading("Т7", 50.0, ts=0.0)})
    assert w._buffers["T11"] == []
    assert w._buffers["T12"] == []
    w.deleteLater()


def test_empty_dict_is_a_noop(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({})  # must not raise
    w.deleteLater()


def test_invalid_value_skipped(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    bad = Reading(
        timestamp=datetime.now(UTC),
        channel="Т12",
        value="garbage",  # type: ignore[arg-type]
        unit="K",
        instrument_id="lakeshore_218s",
    )
    w.set_temperature_readings({"Т12": bad})
    assert w._buffers["T12"] == []
    w.deleteLater()


def test_buffer_truncates_at_max_pts(app: QApplication) -> None:
    w = TemperatureSteadyStateWidget()
    cap = TemperatureSteadyStateWidget._MAX_RAW_PTS
    for i in range(cap + 50):
        w.set_temperature_readings({"Т12": _reading("Т12", 4.0, ts=float(i))})
    assert len(w._buffers["T12"]) == cap
    # The last reading must be the most recent one.
    assert w._buffers["T12"][-1][0] == float(cap + 50 - 1)
    w.deleteLater()


def test_predictor_only_fed_on_new_timestamps(app: QApplication) -> None:
    """Replay/idempotent push: same ts must not double-feed the predictor."""
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({"Т12": _reading("Т12", 4.2, ts=10.0)})
    w.set_temperature_readings({"Т12": _reading("Т12", 4.2, ts=10.0)})
    assert w._last_ts["T12"] == 10.0
    # Fresh timestamp moves the cursor.
    w.set_temperature_readings({"Т12": _reading("Т12", 4.3, ts=11.0)})
    assert w._last_ts["T12"] == 11.0
    w.deleteLater()


# ---------------------------------------------------------------------------
# Hero readout
# ---------------------------------------------------------------------------


def test_hero_readout_shows_last_value_when_not_settled(app: QApplication) -> None:
    """While the predictor is still gathering data, the hero label
    falls back to the last reading + a 'стабилизация' suffix instead
    of staying blank.
    """
    w = TemperatureSteadyStateWidget()
    w.set_temperature_readings({"Т12": _reading("Т12", 4.21, ts=0.0)})
    text = w._hero_labels["T12"].text()
    assert "4.21" in text
    assert "стабилизация" in text.lower()
    w.deleteLater()


# ---------------------------------------------------------------------------
# YAML config wiring
# ---------------------------------------------------------------------------


def test_analytics_layout_measurement_phase_uses_temperature_steady_state() -> None:
    cfg_path = (
        Path(__file__).resolve().parents[4] / "config" / "analytics_layout.yaml"
    )
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    measurement = raw["phases"]["measurement"]
    assert measurement["main"] == "temperature_steady_state"
    # R_thermal demoted but still surfaced in the same phase.
    assert measurement["top_right"] == "r_thermal_live"
