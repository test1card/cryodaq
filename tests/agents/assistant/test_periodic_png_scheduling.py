from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator, retry_delay
from cryodaq.periodic_state import (
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_rendering,
    mark_retryable_failure,
    write_periodic_state,
)
from tests.agents.assistant.test_periodic_png_coordinator import (
    Alarm,
    Archive,
    Clock,
    Live,
    Runner,
    Telegram,
    _config,
)


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 2.0), (2, 4.0), (3, 8.0), (20, 8.0)],
)
def test_retry_delay_is_exact_and_capped(attempt: int, expected: float) -> None:
    assert retry_delay(2.0, 8.0, attempt) == expected


def test_render_retry_reuses_durable_display_time_without_clock_format(tmp_path: Path) -> None:
    config = _config()
    clock = Clock(121.0)
    state = load_periodic_state(tmp_path)
    slot = latest_completed_slot(clock.wall_time(), config.interval_s)
    display = clock.display_time(slot.slot_end)
    first = allocate_pending(
        state,
        slot,
        config,
        generation_id="a" * 32,
        owner_token="b" * 32,
        display_time=display,
        now=clock.wall_time(),
    )
    assert first.payload["active"]["display_time"] == display
    assert clock.display_calls == 1


def test_latest_slot_is_epoch_aligned_and_ignores_timezone() -> None:
    assert latest_completed_slot(181.9, 60).slot_end == 180
    assert latest_completed_slot(239.9, 60).slot_end == 180


def test_state_enforces_durable_display_time_on_retry(tmp_path: Path) -> None:
    config = _config()
    slot = latest_completed_slot(121.0, 60)
    state = load_periodic_state(tmp_path)
    pending = allocate_pending(
        state,
        slot,
        config,
        generation_id="1" * 32,
        owner_token="2" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(tmp_path, pending)
    rendering = mark_rendering(
        pending,
        slot_id=slot.slot_id,
        owner_token="2" * 32,
        now=122.0,
    )
    write_periodic_state(
        tmp_path,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token="2" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    failed = mark_retryable_failure(
        rendering,
        phase="render",
        certainty="not_applicable",
        code="render_failed",
        text="failed",
        not_before=124.0,
        slot_id=slot.slot_id,
        owner_token="2" * 32,
        now=123.0,
    )
    with pytest.raises(ValueError, match="display_time"):
        allocate_pending(
            failed,
            slot,
            config,
            generation_id="3" * 32,
            owner_token="4" * 32,
            display_time="01.01.1970 00:03",
            now=124.0,
        )


def test_retry_deadline_cache_is_bounded_to_one_active_key(tmp_path: Path) -> None:
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        telegram=Telegram(),
        clock=Clock(0.0),
    )
    for index in range(1_000):
        assert coordinator._retry_due(
            {
                "slot_id": f"slot-{index}",
                "status": "FAILED",
                "not_before": float(index + 1),
            }
        ) is False
        assert len(coordinator._retry_deadlines) == 1
