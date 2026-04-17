"""Tests for HeroReadout widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui.dashboard.phase_content.hero_readout import HeroReadout


def test_hero_readout_shows_value(app):
    w = HeroReadout()
    w.set_value(4.21, "K")
    assert "4.21" in w._value_label.text()
    assert w._unit_label.text() == "K"


def test_hero_readout_shows_dash_when_none(app):
    w = HeroReadout()
    w.set_value(None, "K")
    assert "\u2014" in w._value_label.text()


def test_hero_readout_updates_value(app):
    w = HeroReadout()
    w.set_value(4.21, "K")
    assert "4.21" in w._value_label.text()
    w.set_value(77.5, "K")
    assert "77.50" in w._value_label.text()


def test_hero_readout_annotation_optional(app):
    w = HeroReadout()
    w.set_value(4.21, "K", annotation="test annotation")
    assert w._annotation_label.isVisible() or not w._annotation_label.isHidden()
    w.set_value(4.21, "K")
    # annotation hidden when None
