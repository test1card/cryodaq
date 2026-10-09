"""Tests for EtaDisplay widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cryodaq.gui.dashboard.phase_content.eta_display import (
    EtaDisplay,
    _format_duration_ru,
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (45, "45\u0441"),
        (120, "2\u043c\u0438\u043d"),
        (3600, "1\u0447"),
        (3725, "1\u0447 2\u043c\u0438\u043d"),
        (51600, "14\u0447 20\u043c\u0438\u043d"),
    ],
)
def test_eta_display_formats_seconds_to_ru(seconds, expected):
    assert _format_duration_ru(seconds) == expected


def test_eta_display_shows_unavailable_when_none(app):
    w = EtaDisplay()
    w.set_eta(None)
    assert "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e" in w._value_label.text()


def test_eta_display_shows_confidence_range_when_provided(app):
    w = EtaDisplay()
    w.set_eta(3600, confidence_seconds=1800)
    assert "1\u0447" in w._value_label.text()
    assert "\u00b1" in w._confidence_label.text()


def test_eta_display_hides_confidence_when_none(app):
    w = EtaDisplay()
    w.set_eta(3600)
    assert w._confidence_label.isHidden()
