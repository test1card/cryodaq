"""Tests for F13 leak_rate_start / leak_rate_stop engine ZMQ command handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from cryodaq.analytics.leak_rate import LeakRateEstimator

# ---------------------------------------------------------------------------
# Helpers — simulate the engine command dispatch without a running engine
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 29, 10, 0, 0, tzinfo=UTC)


def _make_estimator(volume: float = 50.0) -> LeakRateEstimator:
    return LeakRateEstimator(chamber_volume_l=volume, sample_window_s=60.0)


async def _dispatch(
    action: str, cmd: dict, estimator: LeakRateEstimator, leak_cfg: dict, event_logger
) -> dict:
    """Call the REAL engine leak_rate handler (no test-side reproduction).

    The extraction (F13) made ``_handle_leak_rate_command`` an importable
    module-level helper, so these tests now exercise the production dispatch
    — including its duration_s validation — instead of a copy that could
    silently drift from it. ``None`` (action not a leak-rate command) maps to
    the same unknown-action error the engine closure would surface.
    """
    from cryodaq.engine import _handle_leak_rate_command

    resp = await _handle_leak_rate_command(action, cmd, estimator, leak_cfg, event_logger)
    if resp is None:
        return {"ok": False, "error": f"unknown action: {action}"}
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leak_rate_start_command_handler() -> None:
    """leak_rate_start returns ok=True and arms the estimator."""
    est = _make_estimator(volume=50.0)
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_start", {}, est, {"enabled": True}, event_logger)

    assert response["ok"] is True
    assert response["action"] == "leak_rate_start"
    assert est.is_active


@pytest.mark.asyncio
async def test_leak_rate_start_with_duration_override() -> None:
    """duration_s parameter is forwarded to the estimator and stored as _window_override."""
    est = _make_estimator()
    response = await _dispatch(
        "leak_rate_start", {"duration_s": 120.0}, est, {}, AsyncMock()
    )
    assert response["ok"] is True
    assert est.is_active
    assert est._window_override == 120.0


@pytest.mark.asyncio
async def test_leak_rate_stop_command_handler() -> None:
    """leak_rate_stop returns measurement dict and logs event."""
    est = _make_estimator(volume=50.0)
    event_logger = AsyncMock()

    # Start and feed samples
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    for i in range(10):
        t = _T0 + timedelta(seconds=i * 10.0)
        est.add_sample(t, 1e-5 + i * 1e-7)

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is True
    assert response["action"] == "leak_rate_stop"
    assert "measurement" in response
    assert "leak_rate_mbar_l_per_s" in response["measurement"]
    event_logger.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_leak_rate_stop_without_start_returns_error() -> None:
    """Calling stop without start (no samples) returns ok=False."""
    est = _make_estimator(volume=50.0)
    response = await _dispatch("leak_rate_stop", {}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert "error" in response


@pytest.mark.asyncio
async def test_leak_rate_disabled_config_returns_error() -> None:
    """enabled=False in config prevents measurement from starting."""
    est = _make_estimator()
    response = await _dispatch(
        "leak_rate_start", {}, est, {"enabled": False}, AsyncMock()
    )
    assert response["ok"] is False
    assert "disabled" in response["error"]


@pytest.mark.asyncio
async def test_leak_rate_start_non_numeric_duration_returns_error() -> None:
    """duration_s that is not numeric is rejected before arming the estimator.

    This branch only exists in the production handler; the previous test-side
    copy silently forwarded the bad value. Now reachable via the real handler.
    """
    est = _make_estimator()
    response = await _dispatch(
        "leak_rate_start", {"duration_s": "soon"}, est, {}, AsyncMock()
    )
    assert response["ok"] is False
    assert "not numeric" in response["error"]
    assert not est.is_active


@pytest.mark.asyncio
async def test_leak_rate_start_negative_duration_returns_error() -> None:
    """duration_s must be positive and finite — negative is rejected."""
    est = _make_estimator()
    response = await _dispatch(
        "leak_rate_start", {"duration_s": -5.0}, est, {}, AsyncMock()
    )
    assert response["ok"] is False
    assert "positive and finite" in response["error"]
    assert not est.is_active


@pytest.mark.asyncio
async def test_leak_rate_unknown_action_falls_through() -> None:
    """A non-leak-rate action returns None from the handler (fall-through)."""
    from cryodaq.engine import _handle_leak_rate_command

    est = _make_estimator()
    resp = await _handle_leak_rate_command("safety_status", {}, est, {}, AsyncMock())
    assert resp is None


@pytest.mark.asyncio
async def test_leak_rate_volume_unset_stop_returns_error() -> None:
    """volume_l=0 → finalize raises ValueError → stop returns error."""
    est = _make_estimator(volume=0.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    for i in range(5):
        t = _T0 + timedelta(seconds=i * 10.0)
        est.add_sample(t, 1e-5 + i * 1e-7)

    response = await _dispatch("leak_rate_stop", {}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert "Chamber volume" in response["error"]
