"""Sweep-A tests for CooldownService cooldown-end wiring.

Covers two loose ends closed in the final sweep:

- A1 (sweep #6): ``_on_cooldown_end`` publishes an engine-level
  ``cooldown_end`` event on the EventBus so downstream consumers (event log,
  assistant, a future GUI badge bridge) learn of completion without polling.
- A2 (sweep #5): the cooldown fingerprint gains ``ultimate_vacuum_mbar`` when
  a read-only history reader is wired and returns a pressure series; a reader
  failure degrades to ``pressures=None`` without breaking cooldown end.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from cryodaq.analytics.cooldown_service import CooldownService
from cryodaq.core.broker import DataBroker


class _StubBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class _StubReader:
    def __init__(self, data: dict | None = None, *, fail: bool = False) -> None:
        self._data = data or {}
        self._fail = fail
        self.calls: list[dict] = []

    async def read_readings_history(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("boom")
        return self._data


def _config() -> dict:
    return {"channel_cold": "T_cold", "channel_warm": "T_warm", "auto_ingest": False}


def _make_service(tmp_path: Path, **kwargs: Any) -> CooldownService:
    svc = CooldownService(
        broker=DataBroker(),
        config=_config(),
        model_dir=tmp_path / "model",
        **kwargs,
    )
    # Prime a completed cooldown trajectory in the ring buffer.
    svc._buffer.extend([(0.0, 300.0, 300.0), (1.0, 100.0, 200.0), (2.0, 4.5, 150.0)])
    svc._detector._cooldown_start_ts = 1000.0
    svc._last_reading_ts = 1000.0 + 2 * 3600
    return svc


def test_a1_cooldown_end_publishes_event(tmp_path: Path) -> None:
    """A1: cooldown end publishes a ``cooldown_end`` EngineEvent on the bus."""
    bus = _StubBus()
    svc = _make_service(tmp_path, event_bus=bus)
    svc._baseline_cfg = {"enabled": False}  # fingerprint tap off; event still fires

    asyncio.run(svc._on_cooldown_end())

    assert len(bus.events) == 1
    ev = bus.events[0]
    assert ev.event_type == "cooldown_end"
    assert ev.payload["duration_h"] == pytest.approx(2.0)
    assert ev.payload["T_cold_final"] == pytest.approx(4.5)


def test_a2_fingerprint_gains_ultimate_vacuum(tmp_path: Path, monkeypatch) -> None:
    """A2: reader pressure series → ``ultimate_vacuum_mbar`` (its minimum)."""
    reader = _StubReader(
        {"VSP63D_1/pressure": [(1000.0, 1.0e-5), (1500.0, 3.0e-6), (2000.0, 8.0e-6)]}
    )
    svc = _make_service(tmp_path, reader=reader)
    svc._baseline_cfg = {"enabled": True, "base_threshold_K": 5.0}

    saved: list = []
    monkeypatch.setattr(
        "cryodaq.analytics.cooldown_fingerprint.save_fingerprint",
        lambda fp, _dir: saved.append(fp),
    )

    asyncio.run(svc._on_cooldown_end())

    assert len(saved) == 1
    assert saved[0].ultimate_vacuum_mbar == pytest.approx(3.0e-6)
    # reader was queried for the default vacuum channel over the cooldown window
    assert reader.calls and reader.calls[0]["channels"] == ["VSP63D_1/pressure"]
    assert reader.calls[0]["from_ts"] == pytest.approx(1000.0)


def test_a2_reader_failure_yields_null_vacuum(tmp_path: Path, monkeypatch) -> None:
    """A2: a reader that raises degrades to null vacuum, never breaks the tap."""
    reader = _StubReader(fail=True)
    svc = _make_service(tmp_path, reader=reader)
    svc._baseline_cfg = {"enabled": True, "base_threshold_K": 5.0}

    saved: list = []
    monkeypatch.setattr(
        "cryodaq.analytics.cooldown_fingerprint.save_fingerprint",
        lambda fp, _dir: saved.append(fp),
    )

    # Must not raise.
    asyncio.run(svc._on_cooldown_end())

    assert len(saved) == 1
    assert saved[0].ultimate_vacuum_mbar is None
