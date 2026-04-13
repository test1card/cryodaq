"""Tests for CalibrationAcquisitionService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.calibration_acquisition import CalibrationAcquisitionService
from cryodaq.drivers.base import ChannelStatus, Reading


def _reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="ls218",
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
        raw=value,
        metadata={},
    )


def _srdg_reading(channel: str, value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="ls218",
        channel=channel,
        value=value,
        unit="sensor_unit",
        status=ChannelStatus.OK,
        raw=value,
        metadata={"reading_kind": "raw_sensor"},
    )


@pytest.fixture()
def mock_writer():
    writer = AsyncMock()
    writer.write_immediate = AsyncMock()
    return writer


@pytest.fixture()
def service(mock_writer):
    return CalibrationAcquisitionService(mock_writer)


async def test_service_inactive_by_default(service, mock_writer) -> None:
    assert not service.is_active
    assert service.stats["active"] is False
    assert service.stats["point_count"] == 0

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т1", 82.5)]
    await service.on_readings(krdg, srdg)

    mock_writer.write_immediate.assert_not_called()


async def test_activate_starts_recording(service, mock_writer) -> None:
    service.activate("Т1", ["Т2", "Т3"])
    assert service.is_active

    krdg = [_reading("Т1", 77.0), _reading("Т2", 78.0)]
    srdg = [_srdg_reading("Т2", 82.5), _srdg_reading("Т3", 90.1)]
    await service.on_readings(krdg, srdg)

    mock_writer.write_immediate.assert_called_once()
    written = mock_writer.write_immediate.call_args[0][0]
    assert len(written) == 2
    assert written[0].channel == "Т2_raw"
    assert written[0].unit == "sensor_unit"
    assert written[0].metadata["reading_kind"] == "calibration_srdg"
    assert written[1].channel == "Т3_raw"


async def test_deactivate_stops_recording(service, mock_writer) -> None:
    service.activate("Т1", ["Т2"])
    service.deactivate()
    assert not service.is_active

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т2", 82.5)]
    await service.on_readings(krdg, srdg)

    mock_writer.write_immediate.assert_not_called()


async def test_stats_tracking(service, mock_writer) -> None:
    service.activate("Т1", ["Т2"])

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т2", 82.5)]
    await service.on_readings(krdg, srdg)

    stats = service.stats
    assert stats["point_count"] == 1
    assert stats["t_min"] == 77.0
    assert stats["t_max"] == 77.0
    assert stats["reference_channel"] == "Т1"
    assert stats["target_channels"] == ["Т2"]

    krdg2 = [_reading("Т1", 50.0)]
    srdg2 = [_srdg_reading("Т2", 100.0)]
    await service.on_readings(krdg2, srdg2)

    stats = service.stats
    assert stats["point_count"] == 2
    assert stats["t_min"] == 50.0
    assert stats["t_max"] == 77.0


async def test_only_target_channels_recorded(service, mock_writer) -> None:
    service.activate("Т1", ["Т3"])

    krdg = [_reading("Т1", 77.0)]
    srdg = [
        _srdg_reading("Т2", 82.5),  # not a target
        _srdg_reading("Т3", 90.1),  # target
        _srdg_reading("Т4", 70.0),  # not a target
    ]
    await service.on_readings(krdg, srdg)

    written = mock_writer.write_immediate.call_args[0][0]
    assert len(written) == 1
    assert written[0].channel == "Т3_raw"


async def test_reference_updates_temp_range(service, mock_writer) -> None:
    service.activate("Т1", ["Т2"])

    await service.on_readings([_reading("Т1", 300.0)], [_srdg_reading("Т2", 5.0)])
    assert service.stats["t_min"] == 300.0
    assert service.stats["t_max"] == 300.0

    await service.on_readings([_reading("Т1", 4.2)], [_srdg_reading("Т2", 80.0)])
    assert service.stats["t_min"] == 4.2
    assert service.stats["t_max"] == 300.0

    # Non-reference channel doesn't update range
    await service.on_readings([_reading("Т5", 1000.0)], [_srdg_reading("Т2", 50.0)])
    assert service.stats["t_max"] == 300.0


# ---------------------------------------------------------------------------
# Phase 2d B-2.2: H.10 — atomic KRDG+SRDG persistence
# ---------------------------------------------------------------------------


def test_prepare_srdg_readings_returns_list_without_writing():
    """H.10: prepare_srdg_readings must return readings, not write them."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т2", 1234.5)]

    result = service.prepare_srdg_readings(krdg, srdg)

    assert len(result) == 1
    assert result[0].channel == "Т2_raw"
    # Writer must NOT have been called — scheduler does the write
    mock_writer.write_immediate.assert_not_called()


def test_on_srdg_persisted_updates_counter():
    """H.10: on_srdg_persisted must update point count."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])
    assert service.stats["point_count"] == 0

    service.on_srdg_persisted(5)
    assert service.stats["point_count"] == 5
