"""A newer report builder must not break on an older loaded contract.

Report builders are imported lazily inside the command handlers that use them,
so in a long-lived engine they load from disk long after ``periodic_input`` was
loaded at startup. Adding a field therefore puts fresh builder code in front of
an older snapshot class until that process restarts. That is exactly how
/report started answering "внутренняя ошибка" — over a purely cosmetic option.
"""

import dataclasses

import pytest

import cryodaq.reporting.render_compat as render_compat
from cryodaq.reporting.render_compat import build_render_snapshot

_BASE = {
    "display_time": "31.08.2026 23:15",
    "include_channels": None,
    "channel_labels": (),
    "max_points_per_channel": 10,
    "max_total_points": 20,
    "max_input_bytes": 1024,
    "history_complete": True,
    "alarm_state_complete": True,
    "dropped_points": 0,
    "bad_points": 0,
    "source_errors": (),
}


@dataclasses.dataclass(frozen=True, slots=True)
class _OldSnapshot:
    display_time: str
    include_channels: object
    channel_labels: tuple
    max_points_per_channel: int
    max_total_points: int
    max_input_bytes: int
    history_complete: bool
    alarm_state_complete: bool
    dropped_points: int
    bad_points: int
    source_errors: tuple


@dataclasses.dataclass(frozen=True, slots=True)
class _RequiredOnlySnapshot:
    display_time: str


def test_current_contract_keeps_the_optional_field() -> None:
    snapshot = build_render_snapshot(**_BASE, focus_cold=True)
    assert snapshot.focus_cold is True


def test_older_contract_drops_the_optional_field_instead_of_raising(monkeypatch) -> None:
    monkeypatch.setattr(render_compat, "PeriodicRenderSnapshot", _OldSnapshot)
    snapshot = build_render_snapshot(**_BASE, focus_cold=True)
    assert isinstance(snapshot, _OldSnapshot)
    assert not hasattr(snapshot, "focus_cold")


def test_dropping_is_reported_so_the_stale_process_is_visible(monkeypatch, caplog) -> None:
    monkeypatch.setattr(render_compat, "PeriodicRenderSnapshot", _OldSnapshot)
    with caplog.at_level("INFO"):
        build_render_snapshot(**_BASE, focus_cold=True)
    assert "focus_cold" in caplog.text


def test_a_missing_required_field_still_fails_loudly(monkeypatch) -> None:
    # Only presentation options are droppable. A builder that cannot supply a
    # required field is a real bug and must not be silently papered over.
    monkeypatch.setattr(render_compat, "PeriodicRenderSnapshot", _RequiredOnlySnapshot)
    with pytest.raises(TypeError):
        build_render_snapshot(**_BASE, focus_cold=True)
