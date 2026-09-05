"""Unticking a sensor in Настройки must remove it from the formal report too.

The operator, 2026-09-05: "checkbox should account for everything — plots,
reports, and so on."

Almost everything already asked. A survey of `is_visible`/`get_all_visible`
callers found the GUI grid and plots, the Telegram hourly report, the hourly
PNG, the on-demand report, the run overview, Telegram alarm suppression,
`alarm_v2`, sensor diagnostics and the assistant's intent classifier all
consulting ChannelManager. `reporting/sections.py::_visible_quantity` was the
single holdout, deciding from `descriptor.visible_by_default` alone — so a
sensor switched off vanished everywhere except the one artefact the operator
opens to reconstruct a run.

The rule is BOTH conditions, and the second test here is why. 24 `.raw`
calibration descriptors are absent from `channels.yaml`, and
`ChannelManager.is_visible()` defaults an unknown channel to True, so consulting
the operator alone would pull every raw channel into the formal report. The
switch can always hide; the descriptor still decides what is eligible at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryodaq.reporting.data import HistoricalReading
from cryodaq.reporting.sections import _visible_quantity
from cryodaq.storage.descriptor_archive import ResolvedStorageDescriptor


def _reading(channel: str, *, visible_by_default: bool) -> HistoricalReading:
    descriptor = ResolvedStorageDescriptor(
        descriptor_hash="sha256:test",
        channel_id=channel,
        instrument_id="LS218_1",
        source_key="input.1.temperature",
        descriptor_revision=1,
        quantity="temperature",
        unit="K",
        role="primary_measurement",
        safety_class="observational",
        display_group="криостат",
        display_name=channel,
        visible_by_default=visible_by_default,
        display_order=1,
        envelope_json=None,
        legacy=False,
    )
    return HistoricalReading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel=channel,
        value=290.0,
        unit="K",
        status="ok",
        descriptor=descriptor,
        legacy=False,
    )


class _Manager:
    def __init__(self, hidden: set[str]) -> None:
        self._hidden = hidden

    def is_visible(self, channel_id: str) -> bool:
        short = channel_id.split(" ")[0] if " " in channel_id else channel_id
        return short not in self._hidden


@pytest.fixture
def operator(monkeypatch):
    def _install(hidden: set[str]) -> None:
        monkeypatch.setattr(
            "cryodaq.core.channel_manager.get_channel_manager",
            lambda: _Manager(hidden),
        )

    return _install


def test_a_sensor_the_operator_switched_off_leaves_the_formal_report(operator) -> None:
    operator({"Т5"})
    assert _visible_quantity(_reading("Т5", visible_by_default=True), "temperature") is False


def test_a_sensor_the_operator_left_on_stays_in_the_formal_report(operator) -> None:
    operator({"Т5"})
    assert _visible_quantity(_reading("Т12", visible_by_default=True), "temperature") is True


def test_a_raw_channel_stays_out_even_though_the_operator_never_saw_it(operator) -> None:
    """The reason this is AND rather than a replacement.

    `.raw` channels are not in channels.yaml, so the manager defaults them to
    visible. Only the descriptor keeps them out of a formal plot.
    """

    operator(set())
    assert _visible_quantity(_reading("Т5.raw", visible_by_default=False), "temperature") is False


def test_the_quantity_still_has_to_match(operator) -> None:
    operator(set())
    assert _visible_quantity(_reading("Т12", visible_by_default=True), "pressure") is False


def test_a_lookup_failure_keeps_the_channel_rather_than_dropping_data(monkeypatch) -> None:
    """Fail-open, matching operator_channels.is_visible.

    A broken configuration must not silently remove measurements from a report
    the operator is using to reconstruct a run.
    """

    def _explode():
        raise RuntimeError("channels.yaml unreadable")

    monkeypatch.setattr("cryodaq.core.channel_manager.get_channel_manager", _explode)
    assert _visible_quantity(_reading("Т12", visible_by_default=True), "temperature") is True
