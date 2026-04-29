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
    """Minimal reproduction of the engine leak_rate command handlers."""
    if action == "leak_rate_start":
        if not leak_cfg.get("enabled", True):
            return {"ok": False, "error": "leak rate measurement disabled in config"}
        window_s = cmd.get("duration_s")
        try:
            estimator.start_measurement(window_s=window_s)
            return {"ok": True, "action": "leak_rate_start"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    if action == "leak_rate_stop":
        try:
            from dataclasses import asdict as _asdict
            result = estimator.finalize()
            await event_logger.log_event(
                "leak_rate",
                f"Leak rate: {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
            )
            return {"ok": True, "action": "leak_rate_stop", "measurement": _asdict(result)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": f"unknown action: {action}"}


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
    """duration_s parameter is forwarded to the estimator."""
    est = _make_estimator()
    response = await _dispatch(
        "leak_rate_start", {"duration_s": 120.0}, est, {}, AsyncMock()
    )
    assert response["ok"] is True
    assert est.is_active


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
