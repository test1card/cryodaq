from __future__ import annotations

import asyncio
import inspect
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import cryodaq.engine as engine
from cryodaq.drivers.base import Reading
from cryodaq.engine import DriverLoadResult
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    load_live_channel_descriptor_catalog,
)


def _driver_load(*names: str) -> DriverLoadResult:
    configs = tuple(SimpleNamespace(name=name) for name in names)
    return DriverLoadResult((), configs, None, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("instruments_name", "expected_local"),
    [
        ("instruments.yaml", None),
        ("instruments.local.yaml", "channel_descriptors.local.yaml"),
    ],
)
async def test_descriptor_authority_selection_and_parse_run_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instruments_name: str,
    expected_local: str | None,
) -> None:
    event_thread = threading.get_ident()
    observed: dict[str, object] = {}

    class _Owner:
        def require_exact_instruments(self, instrument_ids: object) -> None:
            observed["instruments"] = instrument_ids

    def _load(base: Path, *, local_path: Path | None = None) -> _Owner:
        observed["thread"] = threading.get_ident()
        observed["base"] = base
        observed["local"] = local_path
        return _Owner()

    monkeypatch.setattr(engine, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(engine, "load_live_channel_descriptor_catalog", _load)

    owner = await engine._load_live_descriptor_authority(
        tmp_path / instruments_name,
        _driver_load("probe", "source"),
    )

    assert type(owner) is _Owner
    assert observed["thread"] != event_thread
    assert observed["base"] == tmp_path / "channel_descriptors.yaml"
    assert observed["local"] == (tmp_path / expected_local if expected_local else None)
    assert observed["instruments"] == ("probe", "source")


async def test_missing_local_descriptor_replacement_fails_startup_without_base_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, Path | None]] = []

    def _load(base: Path, *, local_path: Path | None = None):
        calls.append((base, local_path))
        raise ChannelDescriptorStorageError("live descriptor manifest is unavailable")

    monkeypatch.setattr(engine, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(engine, "load_live_channel_descriptor_catalog", _load)

    with pytest.raises(ChannelDescriptorStorageError, match="unavailable"):
        await engine._load_live_descriptor_authority(
            tmp_path / "instruments.local.yaml",
            _driver_load("probe"),
        )

    assert calls == [
        (
            tmp_path / "channel_descriptors.yaml",
            tmp_path / "channel_descriptors.local.yaml",
        )
    ]


def test_production_writer_receives_non_null_live_descriptor_owner() -> None:
    source = inspect.getsource(engine._run_engine)

    assert "live_descriptor_catalog = await _load_live_descriptor_authority" in source
    assert "SQLiteWriter(_DATA_DIR, channel_catalog=live_descriptor_catalog)" in source
    assert "SQLiteWriter(_DATA_DIR)" not in source


async def test_descriptor_loader_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    heartbeat = asyncio.Event()

    class _Owner:
        def require_exact_instruments(self, _instrument_ids: object) -> None:
            return None

    def _load(_base: Path, *, local_path: Path | None = None) -> _Owner:
        del local_path
        entered.set()
        assert release.wait(5)
        return _Owner()

    async def _heartbeat() -> None:
        assert await asyncio.to_thread(entered.wait, 5)
        heartbeat.set()
        release.set()

    monkeypatch.setattr(engine, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(engine, "load_live_channel_descriptor_catalog", _load)
    load_task = asyncio.create_task(
        engine._load_live_descriptor_authority(
            tmp_path / "instruments.yaml",
            _driver_load("probe"),
        )
    )
    beat_task = asyncio.create_task(_heartbeat())

    await asyncio.wait_for(heartbeat.wait(), timeout=5)
    await load_task
    await beat_task


def test_local_manifest_example_is_complete_for_ignored_eight_channel_multiline_config() -> None:
    root = Path(__file__).parents[2]
    owner = load_live_channel_descriptor_catalog(
        root / "config" / "channel_descriptors.yaml",
        local_path=root / "config" / "channel_descriptors.local.yaml.example",
    )

    owner.require_exact_instruments(("LS218_1", "LS218_2", "LS218_3", "Keithley_1", "VSP63D_1", "MultiLine_1"))
    bound = owner.bind(
        Reading(
            timestamp=datetime(2026, 7, 12, tzinfo=UTC),
            instrument_id="MultiLine_1",
            channel="MultiLine_1/length_ch8",
            value=1.0,
            unit="mm",
        )
    )
    assert bound.descriptor.channel_id == "MultiLine_1/length_ch8"
    assert len(owner._bindings) == 68
