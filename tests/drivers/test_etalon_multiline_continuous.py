"""F-MultiLineContinuous (v0.55.11) — continuous mode + burst capture tests.

Covers PART B of the spec: mode toggle validation, listener spawn /
cancel lifecycle, decimation correctness, burst-buffer accumulation,
and Parquet persistence with experiment-routed and default-dir paths.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.instruments.etalon_multiline import (
    CycleSnapshot,
    MultiLineDriver,
    _ChannelData,
    _parse_channeldata_response,
)


def _channel_data(idx: int = 1, length: float = 1234.5678) -> _ChannelData:
    return _ChannelData(
        channel_number=idx,
        length_mm=length,
        intensity_min=10,
        intensity_max=20,
        temperature_c=22.5,
        pressure_hpa=1013.25,
        humidity_pct=45.0,
        analysis_error=0,
        beam_break=0,
        temp_error=0,
        motion_tolerance_error=0,
        intensity_error=0,
        usb_error=0,
        dll_error=0,
        laser_speed_error=0,
        laser_temp_error=0,
        daq_error=0,
    )


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------


def test_default_mode_is_averaged() -> None:
    driver = MultiLineDriver("ML1", "localhost", mock=True)
    assert driver._mode == "averaged"


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValueError, match="averaged"):
        MultiLineDriver("ML1", "localhost", mode="raw_50mhz", mock=True)


def test_invalid_target_rate_rejected() -> None:
    with pytest.raises(ValueError, match="target_rate_hz"):
        MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=0.0, mock=True)
    with pytest.raises(ValueError, match="target_rate_hz"):
        MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=-1.0, mock=True)


def test_continuous_mode_decimation_interval() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=4.0, mock=True)
    assert driver._target_interval_s == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Averaged-mode regression — listener must NOT spawn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_averaged_mode_no_listener_spawned() -> None:
    """Existing averaged-mode behaviour preserved — no background task."""
    driver = MultiLineDriver("ML1", "localhost", mock=True)
    await driver.connect()
    assert driver._listener_task is None
    assert driver._mode == "averaged"
    await driver.disconnect()


# ---------------------------------------------------------------------------
# Decimation gate
# ---------------------------------------------------------------------------


def test_read_channels_continuous_returns_empty_without_cycle() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=1.0, mock=False)
    # No cycle yet — decimation gate returns nothing.
    assert driver._read_channels_continuous() == []


def test_read_channels_continuous_emits_first_cycle() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=1.0, mock=False)
    # Deterministic timestamp so regressions to Reading.now() are caught.
    ts = 1_700_000_000.0
    expected_ts = datetime.fromtimestamp(ts, tz=UTC)
    cycle = CycleSnapshot(timestamp=ts, channels=(_channel_data(1), _channel_data(2)))
    driver._last_cycle = cycle
    out = driver._read_channels_continuous()
    # 2 channels × length + env triplet (T/P/RH) from first channel.
    assert len(out) == 5
    length_channels = [r for r in out if "/length_ch" in r.channel]
    assert len(length_channels) == 2
    # Assert actual length values match what was seeded (1234.5678 mm).
    for r in length_channels:
        assert r.value == pytest.approx(1234.5678), f"{r.channel}: expected 1234.5678, got {r.value}"
    assert any(r.channel == "ML1/env_temperature" for r in out)
    assert any(r.channel == "ML1/env_pressure" for r in out)
    assert any(r.channel == "ML1/env_humidity" for r in out)
    # Assert actual env values match _channel_data defaults.
    env_by_channel = {r.channel: r.value for r in out}
    assert env_by_channel["ML1/env_temperature"] == pytest.approx(22.5)
    assert env_by_channel["ML1/env_pressure"] == pytest.approx(1013.25)
    assert env_by_channel["ML1/env_humidity"] == pytest.approx(45.0)
    # Assert timestamp propagated from CycleSnapshot — regression to Reading.now()
    # would produce a different (wall-clock) datetime and fail.
    for r in out:
        assert r.timestamp == expected_ts, f"{r.channel}: timestamp {r.timestamp!r} != {expected_ts!r}"


def test_decimation_drops_cycles_inside_target_interval() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=2.0, mock=False)
    driver._last_cycle = CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),))
    # First call passes the gate (no prior emit).
    first = driver._read_channels_continuous()
    assert first
    # A genuinely new cycle arriving inside the 0.5s window is retained but
    # not emitted early.
    pending = CycleSnapshot(timestamp=time.time() + 1.0, channels=(_channel_data(1),))
    driver._last_cycle = pending
    second = driver._read_channels_continuous()
    assert second == []
    assert driver._last_cycle is pending


def test_decimation_emits_after_interval(monkeypatch) -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=2.0, mock=False)
    driver._last_cycle = CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),))

    fake_now = [100.0]

    def _now() -> float:
        return fake_now[0]

    monkeypatch.setattr("cryodaq.drivers.instruments.etalon_multiline.time.monotonic", _now)
    out1 = driver._read_channels_continuous()
    assert out1
    next_cycle = CycleSnapshot(timestamp=time.time() + 1.0, channels=(_channel_data(1),))
    driver._last_cycle = next_cycle
    fake_now[0] += 0.6  # > 0.5 s → gate opens
    out2 = driver._read_channels_continuous()
    assert out2
    assert all(reading.timestamp == datetime.fromtimestamp(next_cycle.timestamp, tz=UTC) for reading in out2)


# ---------------------------------------------------------------------------
# Listener parses pushed lines into _last_cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_handles_pushed_channeldata() -> None:
    """Drive the listener with a fake transport and assert the snapshot."""

    class _FakeTransport:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)
            self.commands: list[str] = []

        async def write_command(self, cmd: str) -> None:
            self.commands.append(cmd)

        async def read_lines_async(self):
            for line in self._lines:
                yield line

    push = [
        "measstarted",
        "channeldata_1,1234.5678,10,20,22.5,1013.25,45.0,0,0,0,0,0,0,0,0,0,0_2,2345.6789,11,21,22.6,1013.30,45.1,0,0,0,0,0,0,0,0,0,0_0",
    ]
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", channel_count=2, mock=False)
    driver._transport = _FakeTransport(push)  # type: ignore[assignment]
    driver._listener_started_mono = time.monotonic()
    await driver._continuous_listener()
    assert driver._last_cycle is not None
    assert len(driver._last_cycle.channels) == 2
    assert driver._last_cycle.channels[0].channel_number == 1
    assert driver._last_cycle.channels[1].channel_number == 2
    assert driver._transport.commands == ["startmeasnogui"]


@pytest.mark.asyncio
async def test_listener_logs_first_cycle_latency(caplog) -> None:
    class _FakeTransport:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)
            self.commands: list[str] = []

        async def write_command(self, cmd: str) -> None:
            self.commands.append(cmd)

        async def read_lines_async(self):
            for line in self._lines:
                yield line

    driver = MultiLineDriver("ML1", "localhost", mode="continuous", channel_count=1, mock=False)
    driver._transport = _FakeTransport(  # type: ignore[assignment]
        ["channeldata_1,1.0,0,0,22.0,1013.0,45.0,0,0,0,0,0,0,0,0,0,0_0"]
    )
    driver._listener_started_mono = time.monotonic()
    with caplog.at_level("INFO", logger="cryodaq.drivers.instruments.etalon_multiline"):
        await driver._continuous_listener()
    assert any("first cycle received" in record.message for record in caplog.records), (
        "Empirical cycle latency must be logged at INFO on first cycle"
    )


@pytest.mark.asyncio
async def test_listener_skips_malformed_channeldata(caplog) -> None:
    """A single garbage line must NOT kill the listener."""

    class _FakeTransport:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)

        async def write_command(self, cmd: str) -> None:
            pass

        async def read_lines_async(self):
            for line in self._lines:
                yield line

    push = [
        "channeldata_garbage_line",
        "channeldata_1,1234.5678,10,20,22.0,1013.0,45.0,0,0,0,0,0,0,0,0,0,0_0",
    ]
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", channel_count=1, mock=False)
    driver._transport = _FakeTransport(push)  # type: ignore[assignment]
    driver._listener_started_mono = time.monotonic()
    with caplog.at_level("WARNING"):
        await driver._continuous_listener()
    # Last good cycle landed despite the earlier garbage.
    assert driver._last_cycle is not None
    assert driver._last_cycle.channels[0].length_mm == 1234.5678


@pytest.mark.asyncio
async def test_listener_appends_to_burst_buffer_when_active() -> None:
    class _FakeTransport:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)

        async def write_command(self, cmd: str) -> None:
            pass

        async def read_lines_async(self):
            for line in self._lines:
                yield line

    driver = MultiLineDriver("ML1", "localhost", mode="continuous", channel_count=1, mock=False)
    driver._transport = _FakeTransport(  # type: ignore[assignment]
        [
            "channeldata_1,1.0,0,0,22.0,1013.0,45.0,0,0,0,0,0,0,0,0,0,0_0",
            "channeldata_1,1.1,0,0,22.0,1013.0,45.0,0,0,0,0,0,0,0,0,0,0_0",
        ]
    )
    driver._listener_started_mono = time.monotonic()
    await driver.burst_start()
    await driver._continuous_listener()
    assert len(driver._burst_buffer) == 2
    # Assert both cycles were actually parsed with distinct values — a count-only
    # check would pass even if the same cycle were appended twice or the
    # buffer were pre-populated.
    lengths = [snap.channels[0].length_mm for snap in driver._burst_buffer]
    assert lengths[0] == pytest.approx(1.0), f"first cycle length_mm wrong: {lengths[0]}"
    assert lengths[1] == pytest.approx(1.1), f"second cycle length_mm wrong: {lengths[1]}"
    assert lengths[0] != lengths[1], "distinct input lines must produce distinct cycle snapshots"


# ---------------------------------------------------------------------------
# Burst API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_burst_start_requires_continuous_mode() -> None:
    driver = MultiLineDriver("ML1", "localhost", mock=True)
    with pytest.raises(RuntimeError, match="continuous"):
        await driver.burst_start()


@pytest.mark.asyncio
async def test_burst_start_double_call_rejected() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=1.0, mock=False)
    await driver.burst_start()
    with pytest.raises(RuntimeError, match="already active"):
        await driver.burst_start()


@pytest.mark.asyncio
async def test_burst_status_reports_active_state() -> None:
    driver = MultiLineDriver("ML1", "localhost", mode="continuous", target_rate_hz=1.0, mock=False)
    status_before = driver.burst_status()
    assert status_before["active"] is False
    assert status_before["cycle_count"] == 0
    await driver.burst_start()
    cycle = CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),))
    driver._burst_buffer.append(cycle)
    status_during = driver.burst_status()
    assert status_during["active"] is True
    assert status_during["cycle_count"] == 1
    assert status_during["elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_burst_stop_returns_none_when_empty(tmp_path: Path) -> None:
    driver = MultiLineDriver(
        "ML1",
        "localhost",
        mode="continuous",
        target_rate_hz=1.0,
        mock=False,
        burst_dir=tmp_path,
    )
    await driver.burst_start()
    out = await driver.burst_stop()
    assert out is None
    assert driver._burst_active is False


@pytest.mark.asyncio
async def test_burst_stop_persists_parquet_with_full_schema(tmp_path: Path) -> None:
    import pyarrow.parquet as pq  # noqa: PLC0415

    driver = MultiLineDriver(
        "ML1",
        "localhost",
        mode="continuous",
        target_rate_hz=1.0,
        mock=False,
        burst_dir=tmp_path,
    )
    # Deterministic per-cycle timestamps so cycle_ts regression is caught.
    ts_base = 1_700_000_000.0
    cycle_timestamps = [ts_base + k * 1.0 for k in range(3)]
    await driver.burst_start()
    for k in range(3):
        driver._burst_buffer.append(
            CycleSnapshot(
                timestamp=cycle_timestamps[k],
                channels=(_channel_data(1), _channel_data(2)),
            )
        )
    out = await driver.burst_stop()
    assert out is not None
    assert out.exists()
    table = pq.read_table(out)
    expected_cols = {
        "cycle_ts",
        "channel_index",
        "length_mm",
        "intensity_min",
        "intensity_max",
        "temperature_c",
        "pressure_hpa",
        "humidity_pct",
        "analysis_error",
        "beam_break",
        "temp_error",
        "motion_tolerance_error",
        "intensity_error",
        "usb_error",
        "dll_error",
        "laser_speed_error",
        "laser_temp_error",
        "daq_error",
    }
    assert set(table.column_names) == expected_cols
    # 3 cycles × 2 channels = 6 rows.
    assert table.num_rows == 6
    # Assert actual cell values match what was seeded — schema/count alone would
    # pass even if all cells were NULL or the wrong dtype.
    length_vals = table.column("length_mm").to_pylist()
    assert all(v == pytest.approx(1234.5678) for v in length_vals), f"length_mm cells wrong: {length_vals}"
    temp_vals = table.column("temperature_c").to_pylist()
    assert all(v == pytest.approx(22.5) for v in temp_vals), f"temperature_c cells wrong: {temp_vals}"
    pressure_vals = table.column("pressure_hpa").to_pylist()
    assert all(v == pytest.approx(1013.25) for v in pressure_vals), f"pressure_hpa cells wrong: {pressure_vals}"
    channel_idx_vals = set(table.column("channel_index").to_pylist())
    assert channel_idx_vals == {1, 2}, f"channel_index must contain both channels 1 and 2, got {channel_idx_vals}"
    # Assert cycle_ts propagated from CycleSnapshot.timestamp (raw float).
    # Each cycle timestamp appears once per channel (2 channels), in cycle order.
    expected_cycle_ts = [ts for ts in cycle_timestamps for _ in range(2)]
    actual_cycle_ts = table.column("cycle_ts").to_pylist()
    assert actual_cycle_ts == pytest.approx(expected_cycle_ts), (
        f"cycle_ts mismatch: {actual_cycle_ts!r} != {expected_cycle_ts!r}"
    )


@pytest.mark.asyncio
async def test_burst_routes_to_experiment_dir_when_active(tmp_path: Path) -> None:
    driver = MultiLineDriver(
        "ML1",
        "localhost",
        mode="continuous",
        target_rate_hz=1.0,
        mock=False,
    )
    await driver.burst_start(experiment_id="exp-2026-05-07-001")
    driver._burst_buffer.append(CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),)))
    experiments_root = tmp_path / "experiments"
    out = await driver.burst_stop(experiments_root=experiments_root)
    assert out is not None
    assert out.parent == experiments_root / "exp-2026-05-07-001"
    assert out.suffix == ".parquet"


@pytest.mark.asyncio
async def test_burst_experiment_id_path_traversal_sanitised(tmp_path: Path) -> None:
    """A malicious experiment id must not escape experiments_root."""
    driver = MultiLineDriver(
        "ML1",
        "localhost",
        mode="continuous",
        target_rate_hz=1.0,
        mock=False,
    )
    await driver.burst_start(experiment_id="../../etc/passwd")
    driver._burst_buffer.append(CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),)))
    experiments_root = tmp_path / "experiments"
    out = await driver.burst_stop(experiments_root=experiments_root)
    assert out is not None
    # Sanitised id replaces "..", "/", "\\" with underscores → still
    # writes inside the resolved experiments_root.
    assert experiments_root in out.parents
    assert "passwd" in str(out) and ".." not in str(out)


@pytest.mark.asyncio
async def test_burst_routes_to_default_dir_when_no_experiment(tmp_path: Path) -> None:
    driver = MultiLineDriver(
        "ML1",
        "localhost",
        mode="continuous",
        target_rate_hz=1.0,
        mock=False,
        burst_dir=tmp_path / "fallback",
    )
    await driver.burst_start()  # no experiment_id
    driver._burst_buffer.append(CycleSnapshot(timestamp=time.time(), channels=(_channel_data(1),)))
    out = await driver.burst_stop()
    assert out is not None
    assert out.parent == tmp_path / "fallback"


# ---------------------------------------------------------------------------
# Disconnect cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_cancels_listener_and_clears_burst() -> None:
    class _FakeTransport:
        def __init__(self) -> None:
            self.commands: list[str] = []
            self.closed = False
            # Signals that read_lines_async has started — replaces the
            # fixed sleep(0.05) which is flaky on loaded CI boxes.
            self.listening = asyncio.Event()

        async def write_command(self, cmd: str) -> None:
            self.commands.append(cmd)

        async def read_lines_async(self):
            # Signal that we are now inside the read loop, then hang
            # until cancelled — lets CancelledError propagate so the
            # listener's except handler issues the stopmeasnogui handshake.
            self.listening.set()
            while True:
                await asyncio.sleep(10)
                yield ""  # pragma: no cover

        async def close(self) -> None:
            self.closed = True

    driver = MultiLineDriver("ML1", "localhost", mode="continuous", channel_count=1, mock=False)
    transport = _FakeTransport()
    driver._transport = transport  # type: ignore[assignment]
    driver._connected = True
    driver._listener_started_mono = time.monotonic()
    driver._listener_task = asyncio.create_task(driver._continuous_listener())
    # Wait until listener is actually blocked in read_lines_async — Event-based,
    # no arbitrary sleep that can fail on slow CI.
    await asyncio.wait_for(transport.listening.wait(), timeout=5.0)
    # Pretend a burst was in flight — disconnect must drop it cleanly.
    await driver.burst_start()
    await driver.disconnect()
    assert driver._listener_task is None
    assert transport.closed
    assert driver._burst_active is False
    # stopmeasnogui sent during cancellation.
    assert "stopmeasnogui" in transport.commands


# ---------------------------------------------------------------------------
# Channeldata parser regression — the new parse path uses the same helper.
# ---------------------------------------------------------------------------


def test_channeldata_parser_accepts_two_channels() -> None:
    line = (
        "channeldata_"
        "1,1234.5678,10,20,22.5,1013.25,45.0,0,0,0,0,0,0,0,0,0,0_"
        "2,2345.6789,11,21,22.6,1013.30,45.1,0,0,0,0,0,0,0,0,0,0_"
        "0"
    )
    channels, se = _parse_channeldata_response(line)
    assert se == 0
    assert len(channels) == 2
    assert channels[0].channel_number == 1
    assert channels[1].length_mm == pytest.approx(2345.6789)
