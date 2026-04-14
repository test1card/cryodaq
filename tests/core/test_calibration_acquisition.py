"""Tests for CalibrationAcquisitionService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.calibration_acquisition import (
    CalibrationAcquisitionService,
    CalibrationCommandError,
)
from cryodaq.core.channel_manager import ChannelConfigError
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


def test_prepare_srdg_readings_returns_tuple_without_writing():
    """H.10: prepare_srdg_readings must return (readings, pending_state)."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т2", 1234.5)]

    result, pending = service.prepare_srdg_readings(krdg, srdg)

    assert len(result) == 1
    assert result[0].channel == "Т2_raw"
    assert pending is not None
    mock_writer.write_immediate.assert_not_called()


def test_on_srdg_persisted_updates_counter_and_state():
    """H.10+Jules R2: on_srdg_persisted applies counter AND pending state."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])
    assert service.stats["point_count"] == 0

    service.on_srdg_persisted(5, {"t_min": 77.0, "t_max": 77.0})
    assert service.stats["point_count"] == 5
    assert service.stats["t_min"] == 77.0
    assert service.stats["t_max"] == 77.0


def test_prepare_does_not_mutate_state():
    """Jules R2 Q3: prepare must NOT mutate t_min/t_max."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])

    krdg = [_reading("Т1", 77.0)]
    srdg = [_srdg_reading("Т2", 1234.5)]

    service.prepare_srdg_readings(krdg, srdg)

    assert service.stats["t_min"] is None, "prepare mutated t_min"
    assert service.stats["t_max"] is None, "prepare mutated t_max"


def test_prepare_then_discard_leaves_state_clean():
    """Jules R2 Q3: if write fails, not calling on_srdg_persisted
    leaves state unchanged."""
    mock_writer = AsyncMock()
    service = CalibrationAcquisitionService(mock_writer)
    service.activate(reference_channel="Т1", target_channels=["Т2"])

    service.prepare_srdg_readings([_reading("Т1", 77.0)], [_srdg_reading("Т2", 1234.5)])
    # Simulate write failure — on_srdg_persisted NOT called

    assert service.stats["t_min"] is None
    assert service.stats["t_max"] is None
    assert service.stats["point_count"] == 0


# ---------------------------------------------------------------------------
# Tier 1 Fix A: Channel canonicalization tests
# ---------------------------------------------------------------------------


class _MockChannelManager:
    """Mock ChannelManager with resolve_channel_reference for tests."""

    _channels = {
        "Т1": {"name": "Криостат верх"},
        "Т2": {"name": "Криостат низ"},
        "Т3": {"name": "Радиатор 1"},
        "Т5": {"name": "Экран 77К"},
    }

    def resolve_channel_reference(self, reference: str) -> str:
        reference = reference.strip()
        if not reference:
            raise ChannelConfigError("empty channel reference")
        short_id = reference.split(" ")[0] if " " in reference else reference
        info = self._channels.get(short_id)
        if info is None:
            known = sorted(self._channels.keys())
            raise ChannelConfigError(
                f"unknown channel reference '{reference}' — "
                f"known channels: {', '.join(known)}"
            )
        name = info.get("name", "")
        return f"{short_id} {name}" if name else short_id


def test_activate_canonicalizes_short_reference_id():
    """Short ID like 'Т1' resolves to full label 'Т1 Криостат верх'."""
    writer = AsyncMock()
    service = CalibrationAcquisitionService(writer, channel_manager=_MockChannelManager())
    service.activate("Т1", ["Т2"])
    assert service.stats["reference_channel"] == "Т1 Криостат верх"
    assert service.stats["target_channels"] == ["Т2 Криостат низ"]


def test_activate_accepts_full_label_passthrough():
    """Full label passes through unchanged."""
    writer = AsyncMock()
    service = CalibrationAcquisitionService(writer, channel_manager=_MockChannelManager())
    service.activate("Т1 Криостат верх", ["Т2 Криостат низ"])
    assert service.stats["reference_channel"] == "Т1 Криостат верх"
    assert service.stats["target_channels"] == ["Т2 Криостат низ"]


def test_activate_rejects_unknown_reference():
    """Unknown reference raises CalibrationCommandError with known channels."""
    writer = AsyncMock()
    service = CalibrationAcquisitionService(writer, channel_manager=_MockChannelManager())
    with pytest.raises(CalibrationCommandError, match="unknown channel"):
        service.activate("Т99", ["Т2"])


def test_activate_rejects_unknown_target():
    """Unknown target raises CalibrationCommandError."""
    writer = AsyncMock()
    service = CalibrationAcquisitionService(writer, channel_manager=_MockChannelManager())
    with pytest.raises(CalibrationCommandError, match="unknown channel"):
        service.activate("Т1", ["Т99"])


def test_activate_rejects_empty_reference():
    """Empty reference raises CalibrationCommandError."""
    writer = AsyncMock()
    service = CalibrationAcquisitionService(writer, channel_manager=_MockChannelManager())
    with pytest.raises(CalibrationCommandError, match="empty"):
        service.activate("", ["Т2"])
