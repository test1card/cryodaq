"""Tests for MultiLinePanel (v0.55.6 overlay)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.overlays.multiline_panel import (
    MultiLinePanel,
    _channel_number,
    _env_kind,
    _is_env_channel,
    _is_length_channel,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _length_reading(ch_num: int, value_mm: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        channel=f"MultiLine_1/length_ch{ch_num}",
        value=value_mm,
        unit="мм",
        instrument_id="MultiLine_1",
    )


def _env_reading(kind: str, value: float, unit: str) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        channel=f"MultiLine_1/env_{kind}",
        value=value,
        unit=unit,
        instrument_id="MultiLine_1",
    )


# ---------------------------------------------------------------------------
# Channel parsing helpers
# ---------------------------------------------------------------------------


def test_helpers_classify_channels() -> None:
    assert _is_length_channel("MultiLine_1/length_ch3")
    assert not _is_length_channel("Т11")
    assert _is_env_channel("MultiLine_1/env_temperature")
    assert not _is_env_channel("MultiLine_1/length_ch1")
    assert _channel_number("MultiLine_1/length_ch7") == 7
    assert _channel_number("Т11") is None
    assert _env_kind("MultiLine_1/env_humidity") == "humidity"


# ---------------------------------------------------------------------------
# Panel construction + lifecycle
# ---------------------------------------------------------------------------


def test_panel_constructs_with_empty_state(app: QApplication) -> None:
    panel = MultiLinePanel()
    assert panel._connected is False
    # Pre-allocated 4 readouts, all dashed.
    for ch_num in (1, 2, 3, 4):
        assert "—" in panel._length_value_labels[ch_num].text()
    assert panel._footer_label.text() == "Нет данных."
    panel.deleteLater()


# ---------------------------------------------------------------------------
# on_reading
# ---------------------------------------------------------------------------


def test_length_reading_renders_in_grid(app: QApplication) -> None:
    panel = MultiLinePanel()
    panel.on_reading(_length_reading(2, 1234.56789))
    label = panel._length_value_labels[2].text()
    assert "1234.5679" in label or "1234.5678" in label
    assert "мм" in label
    panel.deleteLater()


def test_environment_readings_render_in_footer_row(app: QApplication) -> None:
    panel = MultiLinePanel()
    panel.on_reading(_env_reading("temperature", 22.5, "°C"))
    panel.on_reading(_env_reading("pressure", 1013.25, "hPa"))
    panel.on_reading(_env_reading("humidity", 45.0, "%"))
    assert "22.50" in panel._env_t_label.text()
    assert "°C" in panel._env_t_label.text()
    assert "1013.25" in panel._env_p_label.text()
    assert "hPa" in panel._env_p_label.text()
    assert "45.0" in panel._env_rh_label.text()
    panel.deleteLater()


def test_filters_non_multiline_readings(app: QApplication) -> None:
    panel = MultiLinePanel()
    foreign = Reading(
        timestamp=datetime.now(UTC),
        channel="Т12",
        value=4.2,
        unit="K",
        instrument_id="LakeShore",
    )
    panel.on_reading(foreign)
    # No buffer created, footer still empty.
    assert not panel._buffers
    assert panel._footer_label.text() == "Нет данных."
    # Length labels untouched.
    assert "—" in panel._length_value_labels[1].text()
    panel.deleteLater()


def test_buffer_grows_on_repeated_readings(app: QApplication) -> None:
    panel = MultiLinePanel()
    for i in range(5):
        panel.on_reading(_length_reading(1, 1000.0 + i * 0.001))
    buf = panel._buffers["MultiLine_1/length_ch1"]
    assert len(buf) == 5
    # Curve created and updated in place.
    assert "MultiLine_1/length_ch1" in panel._curves
    panel.deleteLater()


def test_extra_channel_creates_dynamic_row(app: QApplication) -> None:
    """Channel 5 isn't pre-allocated — panel must synthesise a row."""
    panel = MultiLinePanel()
    panel.on_reading(_length_reading(5, 999.1234))
    assert 5 in panel._length_value_labels
    assert "999.1234" in panel._length_value_labels[5].text()
    panel.deleteLater()


def test_invalid_value_is_ignored(app: QApplication) -> None:
    panel = MultiLinePanel()
    bad = Reading(
        timestamp=datetime.now(UTC),
        channel="MultiLine_1/length_ch1",
        value=float("nan"),  # NaN is float, but ensures float() doesn't bail
        unit="мм",
        instrument_id="MultiLine_1",
    )
    # NaN is a valid float; the panel will render it. Use a non-numeric instead.
    bad_str = Reading(
        timestamp=datetime.now(UTC),
        channel="MultiLine_1/length_ch1",
        value="not-a-number",  # type: ignore[arg-type]
        unit="мм",
        instrument_id="MultiLine_1",
    )
    panel.on_reading(bad_str)
    assert "MultiLine_1/length_ch1" not in panel._buffers
    # NaN still flows through (operator visibility); the panel doesn't crash.
    panel.on_reading(bad)
    panel.deleteLater()


# ---------------------------------------------------------------------------
# set_connected / chip
# ---------------------------------------------------------------------------


def test_connection_status_chip_updates_on_set_connected(app: QApplication) -> None:
    panel = MultiLinePanel()
    assert panel._chip.text() == "Отключён"
    panel.set_connected(True)
    assert panel._chip.text() == "Подключён"
    panel.set_connected(False)
    assert panel._chip.text() == "Отключён"
    panel.deleteLater()


def test_set_mock_chip_state(app: QApplication) -> None:
    panel = MultiLinePanel()
    panel.set_mock(True)
    assert panel._chip.text() == "Mock"
    # Toggle back: connected=True wins → ok
    panel.set_connected(True)
    panel.set_mock(False)
    assert panel._chip.text() == "Подключён"
    panel.deleteLater()


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def test_footer_updates_on_reading(app: QApplication) -> None:
    panel = MultiLinePanel()
    panel.on_reading(_length_reading(1, 1000.5))
    panel.on_reading(_length_reading(2, 1050.5))
    txt = panel._footer_label.text()
    assert "Каналов: 2" in txt
    assert "Последнее обновление" in txt
    panel.deleteLater()
