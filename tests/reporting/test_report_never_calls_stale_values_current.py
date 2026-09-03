"""A periodic report must not present a stale reading as a current value.

Reproduces the 2026-09-02 23:00 report. The writer had stopped persisting at
22:45:45; the stand kept polling, and the report printed a full table of
temperatures and a pressure as though they described the moment it was sent —
in the same message as three active data-loss alarms. Every value in that table
was the last one seen before the failure, over two hours old.

The renderer was picking the newest *usable* row and never asking how old it
was. Usability and freshness are separate questions, and only the first was
being asked.
"""

from __future__ import annotations

import pytest

from cryodaq.core.reading_freshness import (
    READING_STALE_AFTER_S,
    format_age,
    judge_freshness,
)

_SLOT_END = 1_788_382_800.0  # the moment the report is about


def test_a_reading_from_the_slot_is_current() -> None:
    fresh = judge_freshness(_SLOT_END - 2.0, now_epoch=_SLOT_END)
    assert fresh.is_current is True
    assert fresh.is_stale is False
    assert fresh.reason is None
    assert fresh.age_s == pytest.approx(2.0)


def test_the_incident_reading_is_not_current() -> None:
    """The exact shape of the 23:00 report: a value 2 h 39 min old."""

    incident_age_s = 2 * 3600 + 39 * 60
    verdict = judge_freshness(_SLOT_END - incident_age_s, now_epoch=_SLOT_END)

    assert verdict.is_current is False
    assert verdict.age_s == pytest.approx(incident_age_s)
    assert verdict.reason is not None
    # The age must travel with the value — a bare "stale" tells the operator
    # nothing about whether it is one minute or one night old.
    assert "2 ч" in verdict.reason


def test_the_boundary_is_the_shared_threshold() -> None:
    assert judge_freshness(_SLOT_END - READING_STALE_AFTER_S, now_epoch=_SLOT_END).is_current is True
    assert judge_freshness(_SLOT_END - READING_STALE_AFTER_S - 1, now_epoch=_SLOT_END).is_current is False


@pytest.mark.parametrize(
    ("timestamp", "why"),
    [
        (None, "an unknown measurement time cannot establish currency"),
        (float("nan"), "a non-finite measurement time cannot establish currency"),
        (_SLOT_END + 30.0, "a future-dated reading is not evidence about now"),
    ],
)
def test_unusable_timestamps_fail_closed(timestamp: float | None, why: str) -> None:
    verdict = judge_freshness(timestamp, now_epoch=_SLOT_END)
    assert verdict.is_current is False, why
    assert verdict.reason is not None


def test_age_is_rendered_the_way_an_operator_reads_it() -> None:
    assert format_age(5) == "5 с"
    assert format_age(90) == "1 мин"
    assert format_age(2 * 3600 + 39 * 60) == "2 ч 39 мин"
    assert format_age(50 * 3600) == "2 сут 2 ч"


def test_telegram_and_the_report_share_one_threshold() -> None:
    """The two consumers must not drift apart again.

    Telegram carried a private 60 s rule and the periodic report carried none,
    which is how the report came to contradict the alarms printed beside it.
    """

    from cryodaq.notifications.telegram_commands import _READING_STALE_AFTER_S

    assert _READING_STALE_AFTER_S is READING_STALE_AFTER_S


def _input(*, temperature_age_s: float, pressure_age_s: float):
    """A minimal but real ValidatedPeriodicInput carrying two channels."""

    from cryodaq.reporting.periodic_input import (
        PeriodicReadingSnapshot,
        PeriodicRenderSnapshot,
        PeriodicSlotSnapshot,
        ValidatedPeriodicInput,
    )

    def rows(channel: str, unit: str, value: float, age_s: float):
        # Two rows so the renderer's "newest usable" selection is exercised.
        return [
            PeriodicReadingSnapshot(
                timestamp=_SLOT_END - age_s - 2.0,
                instrument_id="LS218_1",
                channel=channel,
                value=value - 0.1,
                unit=unit,
                status="ok",
            ),
            PeriodicReadingSnapshot(
                timestamp=_SLOT_END - age_s,
                instrument_id="LS218_1",
                channel=channel,
                value=value,
                unit=unit,
                status="ok",
            ),
        ]

    readings = tuple(rows("T1", "K", 295.1, temperature_age_s) + rows("pressure", "mbar", 8.12e-2, pressure_age_s))
    return ValidatedPeriodicInput(
        generation_id="a" * 32,
        owner_token="b" * 32,
        slot=PeriodicSlotSnapshot(
            slot_id="slot",
            slot_start=int(_SLOT_END) - 3600,
            slot_end=int(_SLOT_END),
            window_start=int(_SLOT_END) - 3600,
            window_end=int(_SLOT_END),
            config_fingerprint="c" * 64,
        ),
        render=PeriodicRenderSnapshot(
            display_time="03.09.2026 00:00",
            include_channels=None,
            channel_labels=(("T1", "Т1 Криостат верх"), ("pressure", "pressure")),
            max_points_per_channel=10_000,
            max_total_points=100_000,
            max_input_bytes=1_000_000,
            history_complete=True,
            alarm_state_complete=True,
            dropped_points=0,
            bad_points=0,
            source_errors=(),
        ),
        readings=readings,
        alarms=(),
    )


def test_the_real_caption_marks_stale_values_and_leaves_fresh_ones_clean() -> None:
    """Drive the actual caption builder that produced the 23:00 table.

    Asserts on the operator-visible string, not on a flag and not on the
    renderer's source text.
    """

    from cryodaq.reporting import periodic_renderer

    incident_age_s = 2 * 3600 + 39 * 60
    stale_input = _input(temperature_age_s=incident_age_s, pressure_age_s=incident_age_s)
    caption = periodic_renderer._build_caption(stale_input, periodic_renderer._series(stale_input))

    assert "295.1" in caption, "a stale value is still shown — hiding it is its own lie"
    assert "не актуально" in caption, "but it must never be presented as current"
    assert "2 ч 39 мин" in caption, "and its age must travel with it"

    fresh_input = _input(temperature_age_s=1.0, pressure_age_s=1.0)
    fresh_caption = periodic_renderer._build_caption(fresh_input, periodic_renderer._series(fresh_input))
    assert "295.1" in fresh_caption
    assert "не актуально" not in fresh_caption, "a current reading must not be marked stale"
