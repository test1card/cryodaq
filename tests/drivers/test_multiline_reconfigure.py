"""v0.55.16.0.1 (smoke hotfix) — driver + engine reconfigure tests.

Covers:
- MultiLineDriver.reconfigure_channels validates + atomically replaces
  the channel set (averaged mode takes effect on next poll).
- _handle_multiline_set_channels_command validates input and surfaces
  errors as `{"ok": False, "error": ...}` rather than raising.
- _persist_multiline_channels_to_local_yaml writes the merged config
  back to instruments.local.yaml without clobbering other entries.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from cryodaq.drivers.instruments.etalon_multiline import MultiLineDriver
from cryodaq.engine import (
    _handle_multiline_set_channels_command,
    _persist_multiline_channels_to_local_yaml,
)


def _run(coro):
    return asyncio.run(coro)


def _driver(channels=None, mode="averaged") -> MultiLineDriver:
    return MultiLineDriver(
        host="127.0.0.1",
        port=2001,
        name="MultiLine_test",
        channel_numbers=channels or [1, 2, 3, 4],
        mock=False,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Driver — reconfigure_channels
# ---------------------------------------------------------------------------


def test_reconfigure_validates_empty_channel_list() -> None:
    driver = _driver()
    with pytest.raises(ValueError):
        _run(driver.reconfigure_channels([]))
    # Original channel set retained on failure
    assert driver._channel_numbers == [1, 2, 3, 4]


def test_reconfigure_validates_above_max() -> None:
    driver = _driver()
    with pytest.raises(ValueError):
        _run(driver.reconfigure_channels([1, 33]))


def test_reconfigure_validates_duplicate() -> None:
    driver = _driver()
    with pytest.raises(ValueError):
        _run(driver.reconfigure_channels([1, 1, 2]))


def test_reconfigure_replaces_channel_set_atomically() -> None:
    driver = _driver()
    new_channels = [5, 10, 15, 20, 25, 30]
    result = _run(driver.reconfigure_channels(new_channels))
    assert result == new_channels
    assert driver._channel_numbers == new_channels


def test_reconfigure_refreshes_mock_nominals() -> None:
    driver = _driver()
    _run(driver.reconfigure_channels([7, 14]))
    # Nominals match the standard formula 1000 + ch * 50 for each channel
    assert 7 in driver._mock_nominal_lengths_mm
    assert 14 in driver._mock_nominal_lengths_mm
    assert 1 not in driver._mock_nominal_lengths_mm


def test_reconfigure_takes_effect_next_poll_in_averaged_mode() -> None:
    """Averaged mode just reads off `self._channel_numbers` on each
    poll, so the change is visible the moment reconfigure returns."""
    driver = _driver(channels=[1, 2], mode="averaged")
    _run(driver.reconfigure_channels([5, 6, 7]))
    assert driver._channel_numbers == [5, 6, 7]
    # Mock readings reflect the new set
    readings = driver._mock_readings()
    length_channels = sorted(
        int(r.channel.split("_ch")[-1])
        for r in readings
        if "/length_ch" in r.channel
    )
    assert length_channels == [5, 6, 7]


def test_reconfigure_continuous_restarts_listener_when_connected() -> None:
    """Continuous-mode reconfigure must cancel the active listener task
    and spawn a fresh one so the Etalon `startmeasnogui` filter matches
    the new channel selection."""
    driver = _driver(channels=[1, 2], mode="continuous")

    # Simulate a running listener.
    fake_task = MagicMock()
    fake_task.done.return_value = False
    fake_task.cancel = MagicMock()

    cancelled = {"called": False}

    async def fake_wait_for(awaitable, timeout):
        cancelled["called"] = True

    driver._listener_task = fake_task
    driver._connected = True
    driver._transport = MagicMock()

    # Patch asyncio.wait_for so we don't actually wait on the MagicMock.

    original_wait_for = asyncio.wait_for
    asyncio.wait_for = fake_wait_for  # type: ignore[assignment]
    spawned = {"called": False}

    def fake_create_task(coro, name=None):
        spawned["called"] = True
        # Close the coroutine to suppress "coroutine was never awaited"
        coro.close()
        return MagicMock()

    original_create_task = asyncio.create_task
    asyncio.create_task = fake_create_task  # type: ignore[assignment]
    try:
        _run(driver.reconfigure_channels([5, 6, 7]))
    finally:
        asyncio.wait_for = original_wait_for  # type: ignore[assignment]
        asyncio.create_task = original_create_task  # type: ignore[assignment]
    assert fake_task.cancel.called
    assert cancelled["called"]
    assert spawned["called"]


# ---------------------------------------------------------------------------
# Engine — set_channels command
# ---------------------------------------------------------------------------


def _drivers_dict_with_one(driver) -> dict:
    return {driver.name: driver}


def test_set_channels_command_rejects_non_list() -> None:
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": "not a list"},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=Path("/tmp/nonexistent_for_test"),
        )
    )
    assert out["ok"] is False


def test_set_channels_command_rejects_empty_list() -> None:
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": []},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=Path("/tmp/nonexistent_for_test"),
        )
    )
    assert out["ok"] is False
    assert "at least one channel" in out["error"]


def test_set_channels_command_rejects_out_of_range() -> None:
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": [0, 1, 33]},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=Path("/tmp/nonexistent_for_test"),
        )
    )
    assert out["ok"] is False
    assert "1..32" in out["error"]


def test_set_channels_command_rejects_non_int() -> None:
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": [1, "two"]},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=Path("/tmp/nonexistent_for_test"),
        )
    )
    assert out["ok"] is False


def test_set_channels_command_returns_unknown_driver_error() -> None:
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": [1, 2], "name": "nonexistent"},
            drivers_by_name={},
            config_dir=Path("/tmp/nonexistent_for_test"),
        )
    )
    assert out["ok"] is False
    assert "not found" in out["error"]


def test_set_channels_command_default_name_when_one_driver(tmp_path: Path) -> None:
    """If only one MultiLine driver is configured, omitting `name` is OK."""
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": [10, 20]},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["current_channels"] == [10, 20]


def test_set_channels_command_persists_to_local_yaml(tmp_path: Path) -> None:
    driver = _driver()
    out = _run(
        _handle_multiline_set_channels_command(
            {"channels": [3, 7, 11]},
            drivers_by_name=_drivers_dict_with_one(driver),
            config_dir=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["persist_warning"] is None
    local_path = tmp_path / "instruments.local.yaml"
    assert local_path.exists()
    raw = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    instruments = raw["instruments"]
    matched = [
        e
        for e in instruments
        if isinstance(e, dict)
        and e.get("type") == "etalon_multiline"
        and e.get("name") == "MultiLine_test"
    ]
    assert len(matched) == 1
    assert matched[0]["channels"] == [3, 7, 11]


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------


def test_persist_creates_local_yaml_if_absent(tmp_path: Path) -> None:
    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[1, 2, 5],
    )
    local_path = tmp_path / "instruments.local.yaml"
    assert local_path.exists()


def test_persist_seeds_from_base_yaml_if_local_absent(tmp_path: Path) -> None:
    """If only the base instruments.yaml exists, the seeded local should
    inherit other entries unchanged."""
    base = tmp_path / "instruments.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "instruments": [
                    {"type": "lakeshore_218s", "name": "LS_1", "channels": [1, 2]},
                    {"type": "etalon_multiline", "name": "MultiLine_1", "channels": [1, 2, 3, 4]},
                ]
            }
        ),
        encoding="utf-8",
    )

    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[10, 20, 30],
    )
    local_path = tmp_path / "instruments.local.yaml"
    raw = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    instruments = raw["instruments"]
    assert any(e.get("type") == "lakeshore_218s" for e in instruments)
    ml = next(e for e in instruments if e.get("type") == "etalon_multiline")
    assert ml["channels"] == [10, 20, 30]


def test_persist_appends_stub_when_no_existing_match(tmp_path: Path) -> None:
    """If neither base nor local has the named MultiLine entry, persist
    appends a minimal stub so the channel list survives restart."""
    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_42",
        channels=[5, 10],
    )
    raw = yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))
    matched = [
        e for e in raw["instruments"]
        if isinstance(e, dict) and e.get("name") == "MultiLine_42"
    ]
    assert len(matched) == 1
    assert matched[0]["channels"] == [5, 10]


def test_persist_overwrites_existing_local_entry(tmp_path: Path) -> None:
    """Subsequent persists update in place rather than appending duplicates."""
    local = tmp_path / "instruments.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "instruments": [
                    {"type": "etalon_multiline", "name": "MultiLine_1", "channels": [1, 2]},
                ]
            }
        ),
        encoding="utf-8",
    )
    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[5, 6, 7],
    )
    raw = yaml.safe_load(local.read_text(encoding="utf-8"))
    matched = [
        e for e in raw["instruments"]
        if isinstance(e, dict) and e.get("name") == "MultiLine_1"
    ]
    assert len(matched) == 1
    assert matched[0]["channels"] == [5, 6, 7]


def test_persist_carries_top_level_chamber_from_base_to_local(tmp_path: Path) -> None:
    """Codex audit cycle 2 amend — engine reads instruments.local.yaml
    wholesale (top-level keys are NOT inherited from base). The persist
    helper must therefore copy ``chamber`` (and any other top-level
    keys) from base into local; otherwise a MultiLine channel-set
    change would silently drop the leak-rate config on next restart."""
    base = tmp_path / "instruments.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "chamber": {"volume_l": 12.5, "leak_rate": {"default_sample_window_s": 300}},
                "instruments": [
                    {
                        "type": "etalon_multiline",
                        "name": "MultiLine_1",
                        "host": "192.168.1.50",
                        "port": 2001,
                        "channels": [1, 2, 3, 4],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[5, 6],
    )

    raw = yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))
    # chamber config carried forward
    assert "chamber" in raw
    assert raw["chamber"]["volume_l"] == 12.5
    assert raw["chamber"]["leak_rate"]["default_sample_window_s"] == 300


def test_persist_local_top_level_overrides_base(tmp_path: Path) -> None:
    """If local already overrides chamber, the persist must NOT clobber
    that override with the base value."""
    base = tmp_path / "instruments.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "chamber": {"volume_l": 12.5},
                "instruments": [{"type": "etalon_multiline", "name": "MultiLine_1", "channels": [1]}],
            }
        ),
        encoding="utf-8",
    )
    local = tmp_path / "instruments.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "chamber": {"volume_l": 99.9},  # operator-override
                "instruments": [],
            }
        ),
        encoding="utf-8",
    )

    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[5],
    )

    raw = yaml.safe_load(local.read_text(encoding="utf-8"))
    # Local override wins
    assert raw["chamber"]["volume_l"] == 99.9


def test_persist_merges_base_when_local_has_only_other_instruments(tmp_path: Path) -> None:
    """Codex audit cycle 1 amend — if instruments.local.yaml exists but
    only contains a Lakeshore entry (e.g. operator edited via
    connection_settings), persisting a MultiLine change must merge the
    base etalon_multiline entry's full config (host/port/mode) rather
    than appending a minimal stub that loses base-only fields."""
    base = tmp_path / "instruments.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "instruments": [
                    {"type": "lakeshore_218s", "name": "LS_1", "channels": [1, 2]},
                    {
                        "type": "etalon_multiline",
                        "name": "MultiLine_1",
                        "host": "192.168.1.50",
                        "port": 2001,
                        "channels": [1, 2, 3, 4],
                        "mode": "averaged",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    local = tmp_path / "instruments.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "instruments": [
                    {"type": "lakeshore_218s", "name": "LS_1", "channels": [1, 2, 3]},
                ]
            }
        ),
        encoding="utf-8",
    )

    _persist_multiline_channels_to_local_yaml(
        config_dir=tmp_path,
        instrument_name="MultiLine_1",
        channels=[10, 11, 12],
    )

    raw = yaml.safe_load(local.read_text(encoding="utf-8"))
    instruments = {
        (e["type"], e["name"]): e
        for e in raw["instruments"]
        if isinstance(e, dict)
    }
    # Lakeshore local override preserved
    assert instruments[("lakeshore_218s", "LS_1")]["channels"] == [1, 2, 3]
    # MultiLine entry is the BASE merged in, not a minimal stub —
    # critical fields like host/port/mode survive.
    ml = instruments[("etalon_multiline", "MultiLine_1")]
    assert ml["host"] == "192.168.1.50"
    assert ml["port"] == 2001
    assert ml["mode"] == "averaged"
    assert ml["channels"] == [10, 11, 12]


def test_reconfigure_continuous_refuses_spawn_on_listener_cancel_timeout() -> None:
    """Codex audit cycle 1 amend — if the old listener doesn't cancel
    within the 2s grace window, the driver must NOT spawn a new
    listener (would race the still-unwinding old task for the read
    stream)."""
    driver = _driver(channels=[1, 2], mode="continuous")

    fake_task = MagicMock()
    fake_task.done.return_value = False
    fake_task.cancel = MagicMock()

    async def fake_wait_for(awaitable, timeout):
        raise TimeoutError()

    driver._listener_task = fake_task
    driver._connected = True
    driver._transport = MagicMock()

    spawned = {"called": False}

    def fake_create_task(coro, name=None):
        spawned["called"] = True
        coro.close()
        return MagicMock()

    original_wait_for = asyncio.wait_for
    original_create_task = asyncio.create_task
    asyncio.wait_for = fake_wait_for  # type: ignore[assignment]
    asyncio.create_task = fake_create_task  # type: ignore[assignment]
    try:
        _run(driver.reconfigure_channels([5, 6, 7]))
    finally:
        asyncio.wait_for = original_wait_for  # type: ignore[assignment]
        asyncio.create_task = original_create_task  # type: ignore[assignment]
    # Cancel was attempted, but no new listener was spawned because
    # the old one didn't cancel cleanly within the grace window.
    assert fake_task.cancel.called
    assert spawned["called"] is False
    assert driver._listener_task is None
    # Channel set still updated (the runtime data structure is the source
    # of truth even when the listener can't restart cleanly)
    assert driver._channel_numbers == [5, 6, 7]
