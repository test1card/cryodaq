"""TSP software late-pet watchdog plumbing for the Keithley 2604B.

All behaviour is gated behind ``_wdog_enabled`` (default False). The default-OFF
path MUST emit a command stream byte-identical to today (zero ``cryodaq_wdog``
strings). Tests drive a fake TSP transport and assert exact command strings.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import pytest

from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


class _RecordingTransport:
    """Fake TSP transport that records every write and answers the queries the
    driver issues on connect/poll. ``fail_on`` marks a substring whose write
    raises, to exercise the upload-failure path."""

    def __init__(self, *, fail_on: str | None = None, query_raises_on: str | None = None) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        # Combined chronological log of ("query"|"write", cmd) so tests can
        # assert cross-kind ordering (e.g. latch read BEFORE script upload).
        self.calls: list[tuple[str, str]] = []
        self._fail_on = fail_on
        # Substring whose *query* raises a transport error (I/O timeout), to
        # exercise the "latch state UNKNOWN" path distinct from an unparseable
        # (but successful) response.
        self._query_raises_on = query_raises_on
        self._opened = False
        self.wdog_tripped_raw = "0"
        # Post-upload integrity readbacks (A8). Version 3 is intentionally
        # non-autonomous; required mode must refuse it while best_effort may
        # activate the software late-pet check.
        self.wdog_version_raw = "3"
        self.wdog_autonomous_raw = "0"
        self.wdog_active_raw = "0"

    async def open(self, resource: str) -> None:
        self._opened = True

    async def close(self) -> None:
        self._opened = False

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        if self._query_raises_on is not None and self._query_raises_on in cmd:
            raise RuntimeError("simulated transport failure")
        self.queries.append(cmd)
        self.calls.append(("query", cmd))
        c = cmd.lower()
        if "*idn?" in c:
            return "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
        if "cryodaq_wdog_version" in c:
            return self.wdog_version_raw
        if "cryodaq_wdog_autonomous" in c:
            return self.wdog_autonomous_raw
        if "cryodaq_wdog_active" in c:
            return self.wdog_active_raw
        if "cryodaq_wdog_tripped" in c:
            return self.wdog_tripped_raw
        if "source.output" in c:
            if "cryodaq_off_v1" in c:
                match = re.search(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g", cmd)
                assert match is not None
                return f"CRYODAQ_OFF_V1|{match.group(1)}|0\n"
            return "0"
        if "errorqueue.count" in c:
            return "0"
        return "0"

    async def write(self, cmd: str) -> None:
        if self._fail_on is not None and self._fail_on in cmd:
            raise RuntimeError("simulated upload failure")
        self.writes.append(cmd)
        self.calls.append(("write", cmd))
        # Mirror firmware state transitions so the post-run readbacks (A8) see
        # the same state a real 2604B would: run() clears the latch and arms;
        # disarm() clears active.
        if cmd == "cryodaq_wdog_run()":
            self.wdog_active_raw = "1"
            self.wdog_tripped_raw = "0"
        elif cmd == "cryodaq_wdog_acknowledge()":
            self.wdog_active_raw = "1"
            self.wdog_tripped_raw = "0"
        elif cmd == "cryodaq_wdog_disarm()":
            self.wdog_active_raw = "0"


def _wdog_writes(transport: _RecordingTransport) -> list[str]:
    return [w for w in transport.writes if "cryodaq_wdog" in w or "CRYODAQ_WDOG" in w]


def _lua_script() -> str:
    return (Path(__file__).resolve().parents[2] / "tsp" / "cryodaq_wdog.lua").read_text(encoding="utf-8")


def test_lua_v3_is_explicitly_non_autonomous() -> None:
    script = _lua_script()
    assert "CRYODAQ_WDOG_VERSION = 3" in script
    assert "cryodaq_wdog_autonomous = 0" in script
    assert "cryodaq_wdog_timer_armed = 0" in script
    assert "function cryodaq_wdog_shutdown()" in script
    assert "local function cryodaq_wdog_shutdown()" not in script
    assert "function cryodaq_wdog_acknowledge()" in script


def test_lua_v3_has_no_invalid_timer_or_source_action_contract() -> None:
    script = _lua_script()
    assert ".enable" not in script
    assert "trigger.timer" not in script
    assert "trigger.source.action" not in script
    assert "SOURCE_IDLE" not in script
    assert "cryodaq_wdog_arm_timer" not in script
    assert "cryodaq_wdog_kick_timer" not in script


def test_lua_v3_documents_integer_second_strict_boundary() -> None:
    script = _lua_script()
    assert "os.time()" in script
    assert "one-second granularity" in script
    assert "Strict `>`" in script


def _driver(*, enabled: bool, mock: bool = False, timeout_s: float = 5.0):
    return Keithley2604B(
        "k2604",
        "USB0::FAKE",
        mock=mock,
        watchdog_enabled=enabled,
        watchdog_timeout_s=timeout_s,
    )


# ---------------------------------------------------------------------------
# (a) flag ON: arm-on-connect emits upload + timeout global + run
# ---------------------------------------------------------------------------


async def test_arm_on_connect_emits_upload_timeout_run() -> None:
    drv = _driver(enabled=True)
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()

    assert drv._wdog_armed is True
    # Upload of the actual Lua (contains the pet function) must precede the
    # timeout set and the run call.
    upload = next(w for w in t.writes if "function cryodaq_wdog_pet" in w)
    idx_upload = t.writes.index(upload)
    idx_timeout = t.writes.index("CRYODAQ_WDOG_TIMEOUT_S = 5.0")
    idx_run = t.writes.index("cryodaq_wdog_run()")
    assert idx_upload < idx_timeout < idx_run


async def test_watchdog_script_file_load_runs_off_event_loop(monkeypatch) -> None:
    import cryodaq.drivers.instruments.keithley_2604b as keithley_module

    calls: list[object] = []

    def _load() -> str:
        return "CRYODAQ_WDOG_VERSION = 3\nfunction cryodaq_wdog_pet() end"

    async def _to_thread(function, /, *args, **kwargs):
        calls.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(keithley_module, "_load_wdog_script", _load)
    monkeypatch.setattr(asyncio, "to_thread", _to_thread)
    driver = _driver(enabled=True)
    transport = _RecordingTransport()
    driver._transport = transport

    await driver.connect()

    assert calls == [_load]


async def test_watchdog_ack_recovery_script_load_runs_off_event_loop(monkeypatch) -> None:
    import cryodaq.drivers.instruments.keithley_2604b as keithley_module

    driver = _mode_driver("best_effort")
    transport = _RecordingTransport()
    driver._transport = transport
    await driver.connect()
    driver._wdog_trip_pending = True
    transport.wdog_tripped_raw = "nil"

    calls: list[object] = []

    def _load() -> str:
        return "CRYODAQ_WDOG_VERSION = 3\nfunction cryodaq_wdog_pet() end"

    async def _to_thread(function, /, *args, **kwargs):
        calls.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(keithley_module, "_load_wdog_script", _load)
    monkeypatch.setattr(asyncio, "to_thread", _to_thread)

    assert await driver.acknowledge_wdog_trip() is True
    assert calls == [_load]


async def test_arm_timeout_reflects_config() -> None:
    drv = _driver(enabled=True, timeout_s=12.5)
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    assert "CRYODAQ_WDOG_TIMEOUT_S = 12.5" in t.writes


# ---------------------------------------------------------------------------
# (b) pet-on-poll: N reads -> N pets
# ---------------------------------------------------------------------------


async def test_pet_on_each_poll() -> None:
    drv = _driver(enabled=True)
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.writes.clear()

    for _ in range(4):
        await drv.read_channels()

    pets = [w for w in t.writes if w == "cryodaq_wdog_pet()"]
    assert len(pets) == 4


# ---------------------------------------------------------------------------
# (c) disarm-on-stop (driver disconnect)
# ---------------------------------------------------------------------------


async def test_disarm_on_disconnect() -> None:
    drv = _driver(enabled=True)
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.writes.clear()

    await drv.disconnect()

    assert "cryodaq_wdog_disarm()" in t.writes
    assert drv._wdog_armed is False


async def test_operator_ack_consumes_trip_only_after_verified_off() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.wdog_tripped_raw = "1"
    t.wdog_active_raw = "0"
    t.writes.clear()

    assert await drv.acknowledge_wdog_trip() is True

    ack_idx = t.writes.index("cryodaq_wdog_acknowledge()")
    assert t.writes.index("smua.source.output = smua.OUTPUT_OFF") < ack_idx
    assert t.writes.index("smub.source.output = smub.OUTPUT_OFF") < ack_idx
    assert t.wdog_tripped_raw == "0"
    assert t.wdog_active_raw == "1"
    assert drv._wdog_armed is True
    assert drv._wdog_autonomous is False
    assert drv.watchdog_trip_pending is False


async def test_operator_ack_refuses_to_clear_trip_when_off_unverified() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.wdog_tripped_raw = "1"
    t.wdog_active_raw = "0"
    original_query = t.query

    async def _query_output_still_on(cmd: str, timeout_ms: int | None = None) -> str:
        if "source.output" in cmd:
            return "1"
        return await original_query(cmd, timeout_ms)

    t.query = _query_output_still_on  # type: ignore[assignment]
    assert await drv.acknowledge_wdog_trip() is False
    assert "cryodaq_wdog_acknowledge()" not in t.writes
    assert t.wdog_tripped_raw == "1"
    assert drv.watchdog_trip_pending is True


async def test_disconnected_ack_cannot_consume_pending_trip_evidence(caplog) -> None:
    drv = _mode_driver("best_effort")
    transport = _RecordingTransport()
    drv._transport = transport
    drv._wdog_trip_pending = True
    drv._connected = False

    with caplog.at_level(logging.CRITICAL):
        assert await drv.acknowledge_wdog_trip() is False

    assert drv.watchdog_trip_pending is True
    assert transport.writes == []
    assert "while disconnected" in caplog.text


async def test_operator_ack_bad_readback_disarms_and_stays_failed() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.wdog_tripped_raw = "1"
    t.wdog_active_raw = "0"
    original_write = t.write

    async def _write_bad_ack_state(cmd: str) -> None:
        await original_write(cmd)
        if cmd == "cryodaq_wdog_acknowledge()":
            t.wdog_active_raw = "nan"

    t.write = _write_bad_ack_state  # type: ignore[assignment]
    assert await drv.acknowledge_wdog_trip() is False
    assert "cryodaq_wdog_disarm()" in t.writes
    assert drv._wdog_armed is False
    assert drv.watchdog_trip_pending is True


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "2", "0.5", "true", ""])
async def test_runtime_trip_readback_rejects_non_exact_flag(raw) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.wdog_tripped_raw = raw

    with pytest.raises(ValueError):
        await drv.wdog_tripped()
    assert drv.watchdog_trip_pending is False


async def test_runtime_exact_trip_sets_host_pending_evidence() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    t.wdog_tripped_raw = "1"

    assert await drv.wdog_tripped() is True
    assert drv.watchdog_trip_pending is True


async def test_preexisting_v3_latch_connect_then_explicit_ack_recovers() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"
    drv._transport = t
    await drv.connect()
    assert drv.watchdog_trip_pending is True
    assert drv._wdog_armed is False

    assert await drv.acknowledge_wdog_trip() is True
    assert "cryodaq_wdog_acknowledge()" in t.writes
    assert drv.watchdog_trip_pending is False
    assert drv._wdog_armed is True


async def test_power_cycle_nil_after_host_pending_allows_explicit_v3_reactivation() -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    drv._wdog_trip_pending = True
    drv._wdog_armed = False
    t.wdog_tripped_raw = "nil"
    t.wdog_version_raw = "nil"
    original_write = t.write

    async def _write_models_fresh_upload(cmd: str) -> None:
        await original_write(cmd)
        if "CRYODAQ_WDOG_VERSION = 3" in cmd:
            t.wdog_version_raw = "3"
            t.wdog_autonomous_raw = "0"
            t.wdog_active_raw = "0"
            t.wdog_tripped_raw = "0"

    t.write = _write_models_fresh_upload  # type: ignore[assignment]
    t.writes.clear()

    assert await drv.acknowledge_wdog_trip() is True
    assert any("CRYODAQ_WDOG_VERSION = 3" in w for w in t.writes)
    assert "cryodaq_wdog_run()" in t.writes
    assert drv.watchdog_trip_pending is False
    assert drv._wdog_armed is True


# ---------------------------------------------------------------------------
# (d) upload failure -> connect succeeds, _wdog_armed False, CRITICAL log
# ---------------------------------------------------------------------------


async def test_upload_failure_is_non_fatal(caplog) -> None:
    drv = _driver(enabled=True)
    t = _RecordingTransport(fail_on="function cryodaq_wdog_pet")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise

    assert drv._connected is True
    assert drv._wdog_armed is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    # A failed arm must not leave a running/timeout write behind.
    assert "cryodaq_wdog_run()" not in t.writes
    # A poll after a failed arm must not pet a non-existent watchdog.
    await drv.read_channels()
    assert "cryodaq_wdog_pet()" not in t.writes


# ---------------------------------------------------------------------------
# (e) mock mode -> zero wdog writes
# ---------------------------------------------------------------------------


async def test_mock_mode_zero_wdog_writes() -> None:
    drv = _driver(enabled=True, mock=True)
    await drv.connect()
    await drv.read_channels()
    await drv.disconnect()
    # Mock transport records nothing on the bus; the driver must also never
    # attempt a wdog write in mock mode.
    assert drv._wdog_armed is False


# ---------------------------------------------------------------------------
# (f) flag OFF (default) -> command stream identical to today (zero wdog)
# ---------------------------------------------------------------------------


async def test_flag_off_default_is_byte_identical() -> None:
    # Default construction (no watchdog kwargs) must behave as flag OFF.
    drv = Keithley2604B("k2604", "USB0::FAKE", mock=False)
    assert drv._wdog_enabled is False
    off = _RecordingTransport()
    drv._transport = off
    await drv.connect()
    for _ in range(3):
        await drv.read_channels()
    await drv.disconnect()

    assert _wdog_writes(off) == []


async def test_off_and_default_command_streams_byte_identical(monkeypatch) -> None:
    """True byte-identity: a driver built with ``watchdog_mode='off'`` and one
    built with NO watchdog kwargs must issue the exact same chronological
    command stream (writes AND queries, in order) across connect + poll +
    disconnect — proves the feature is inert, not merely wdog-write-free."""
    monkeypatch.setattr(
        "cryodaq.drivers.instruments.keithley_2604b.secrets.token_hex",
        lambda _size: "a" * 32,
    )
    d_off = _mode_driver("off")
    d_default = Keithley2604B("k2604", "USB0::FAKE", mock=False)
    t_off = _RecordingTransport()
    t_default = _RecordingTransport()
    d_off._transport = t_off
    d_default._transport = t_default
    for d in (d_off, d_default):
        await d.connect()
        await d.read_channels()
        await d.disconnect()

    assert t_off.calls  # non-empty: the bus was actually exercised
    assert t_off.calls == t_default.calls


async def test_flag_on_off_streams_differ_only_by_wdog() -> None:
    """The ON stream minus wdog strings equals the OFF stream — proves the flag
    adds only watchdog commands and changes nothing else."""
    off = _RecordingTransport()
    on = _RecordingTransport()
    d_off = _driver(enabled=False)
    d_on = _driver(enabled=True)
    d_off._transport = off
    d_on._transport = on
    for d in (d_off, d_on):
        await d.connect()
        for _ in range(2):
            await d.read_channels()
        await d.disconnect()

    on_without_wdog = [w for w in on.writes if "cryodaq_wdog" not in w and "CRYODAQ_WDOG" not in w]
    assert on_without_wdog == off.writes


# ---------------------------------------------------------------------------
# wdog_tripped read-back
# ---------------------------------------------------------------------------


async def test_wdog_tripped_reads_firmware_flag() -> None:
    drv = _driver(enabled=True)
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()

    assert await drv.wdog_tripped() is False
    t.wdog_tripped_raw = "1"
    assert await drv.wdog_tripped() is True


async def test_wdog_tripped_false_when_disabled() -> None:
    drv = _driver(enabled=False)
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"  # firmware would say tripped, but flag is OFF
    drv._transport = t
    await drv.connect()
    assert await drv.wdog_tripped() is False
    # And it must not have issued the trip query on the bus.
    assert not any("cryodaq_wdog_tripped" in q for q in t.queries)


# ---------------------------------------------------------------------------
# (h) pure-Python algorithm-contract test mirroring the Lua deadline arithmetic
# ---------------------------------------------------------------------------


def _wdog_model(last_pet: float, now: float, timeout: float) -> bool:
    """Reference model of cryodaq_wdog_run()'s deadline test:
    ``(os.time() - last_pet) > timeout`` -> trip."""
    return (now - last_pet) > timeout


def test_deadline_arithmetic_contract() -> None:
    timeout = 5.0
    # Within the deadline: no trip.
    assert _wdog_model(last_pet=100.0, now=104.0, timeout=timeout) is False
    # Exactly at the deadline: strict '>' means NOT tripped.
    assert _wdog_model(last_pet=100.0, now=105.0, timeout=timeout) is False
    # Past the deadline: trip.
    assert _wdog_model(last_pet=100.0, now=105.001, timeout=timeout) is True
    # A pet resets the reference so the same 'now' no longer trips.
    assert _wdog_model(last_pet=104.0, now=105.001, timeout=timeout) is False


def test_default_timeout_is_five_seconds() -> None:
    drv = _driver(enabled=True)
    assert drv._wdog_timeout_s == pytest.approx(5.0)


@pytest.mark.parametrize(
    "value",
    [True, False, "5", None, float("nan"), float("inf"), float("-inf"), 0, -1, 300.1],
)
def test_watchdog_timeout_rejects_invalid_or_unsafe_values(value) -> None:
    with pytest.raises(ValueError, match="watchdog_timeout_s"):
        Keithley2604B("k2604", "USB0::FAKE", watchdog_timeout_s=value)


@pytest.mark.parametrize("value", [1, 1.0, 5, 300, 300.0])
def test_watchdog_timeout_accepts_finite_supported_range(value) -> None:
    drv = Keithley2604B("k2604", "USB0::FAKE", watchdog_timeout_s=value)
    assert drv._wdog_timeout_s == pytest.approx(float(value))


# ---------------------------------------------------------------------------
# (i) config parse is strict-bool: a quoted YAML string must fail closed
# ---------------------------------------------------------------------------


def _load_keithley_driver(tmp_path, enabled_literal: str):
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        f"    enabled: {enabled_literal}\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n",
        encoding="utf-8",
    )
    return _load_drivers(cfg, mock=True).instrument_configs[0].driver


@pytest.mark.parametrize("literal", ['"false"', '"true"', '"0"'])
def test_config_wdog_enabled_requires_real_bool(tmp_path, literal) -> None:
    """A quoted/truthy-string ``enabled`` is a fatal typed config error."""
    from cryodaq.drivers.registry import DriverRegistryError

    with pytest.raises(DriverRegistryError, match=r"keithley\.watchdog\.enabled"):
        _load_keithley_driver(tmp_path, literal)


def test_config_wdog_enabled_true_bool_arms(tmp_path) -> None:
    """Only the literal YAML boolean ``true`` enables the watchdog."""
    drv = _load_keithley_driver(tmp_path, "true")
    assert drv._wdog_enabled is True


# ---------------------------------------------------------------------------
# (j) operator-selected mode: off | best_effort | required
# ---------------------------------------------------------------------------


def _mode_driver(mode: str, *, mock: bool = False, timeout_s: float = 5.0):
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    return Keithley2604B(
        "k2604",
        "USB0::FAKE",
        mock=mock,
        watchdog_mode=mode,
        watchdog_timeout_s=timeout_s,
    )


async def test_mode_off_is_byte_identical() -> None:
    """Explicit ``mode='off'`` emits zero wdog writes — same as the default."""
    from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode

    drv = _mode_driver("off")
    assert drv._wdog_mode is WatchdogMode.OFF
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    for _ in range(3):
        await drv.read_channels()
    await drv.disconnect()
    assert _wdog_writes(t) == []


async def test_mode_best_effort_happy_arms() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode

    drv = _mode_driver("best_effort")
    assert drv._wdog_mode is WatchdogMode.BEST_EFFORT
    t = _RecordingTransport()
    drv._transport = t
    await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is True
    assert drv._wdog_autonomous is False
    assert "cryodaq_wdog_run()" in t.writes


async def test_mode_best_effort_arm_fail_is_non_fatal(caplog) -> None:
    drv = _mode_driver("best_effort")
    # NOTE: fail_on is a substring match against every write, and the
    # uploaded Lua script itself defines "function cryodaq_wdog_run()" — a
    # naive fail_on="cryodaq_wdog_run" would (wrongly) fail the script
    # upload, never reaching the explicit run() call this test targets. Fail
    # only the EXACT run() command (same technique used elsewhere in this
    # file for the disarm-only and readback-only failure cases).
    t = _RecordingTransport()
    original_write = t.write

    async def _write_fail_run_only(cmd: str) -> None:
        if cmd == "cryodaq_wdog_run()":
            raise RuntimeError("simulated run-write failure")
        await original_write(cmd)

    t.write = _write_fail_run_only  # type: ignore[assignment]
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise (fail-OPEN on watchdog layer)
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    # R2 (Phase A recheck, MEDIUM): the run write itself raising is ambiguous
    # (the instrument may have accepted the command before the write failed)
    # — a best-effort disarm must be attempted regardless.
    assert "cryodaq_wdog_disarm()" in t.writes


async def test_mode_required_arm_fail_raises_and_closes(caplog) -> None:
    """required is fail-CLOSED: an arm FAILURE (backstop cannot be established)
    must abort connect() AND clean up the transport."""
    drv = _mode_driver("required")
    t = _RecordingTransport(fail_on="function cryodaq_wdog_pet")  # upload write fails
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert t._opened is False  # DELTA 4: transport closed on fail-closed abort


async def test_mode_required_run_fail_raises() -> None:
    drv = _mode_driver("required")
    # See test_mode_best_effort_arm_fail_is_non_fatal above: fail only the
    # EXACT run() command, not the script upload (which also contains the
    # substring "cryodaq_wdog_run" as part of the function definition).
    t = _RecordingTransport()
    # Reach the downstream ambiguous-run path by modelling a future script
    # that has separately established the autonomous contract.
    t.wdog_autonomous_raw = "1"
    original_write = t.write

    async def _write_fail_run_only(cmd: str) -> None:
        if cmd == "cryodaq_wdog_run()":
            raise RuntimeError("simulated run-write failure")
        await original_write(cmd)

    t.write = _write_fail_run_only  # type: ignore[assignment]
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False
    # R2 (Phase A recheck, MEDIUM): required mode still fails closed, but the
    # ambiguous run-write failure must attempt a best-effort disarm first.
    assert "cryodaq_wdog_disarm()" in t.writes


async def test_latch_read_before_upload_is_preserved_for_operator_ack(caplog) -> None:
    """A prior trip is exposed without the upload resetting its evidence."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"  # prior late-pet check latched a trip
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()

    assert drv._connected is True
    assert drv._wdog_armed is False
    assert drv.watchdog_trip_pending is True
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    assert not any("function cryodaq_wdog_pet" in w for w in t.writes)
    assert "operator acknowledgment" in " ".join(r.getMessage() for r in caplog.records).lower()


async def test_latch_read_before_upload_best_effort_too() -> None:
    """Evidence preservation applies in best_effort as well."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"
    drv._transport = t
    await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert drv.watchdog_trip_pending is True
    assert not any("function cryodaq_wdog_pet" in w for w in t.writes)


async def test_latch_read_transport_fail_required_raises_and_closes(caplog) -> None:
    """HIGH: a TRANSPORT failure on the pre-upload latch read (state UNKNOWN,
    not "no latch") must abort connect in required mode AND close the transport.
    The script must NOT be uploaded — a re-upload would run
    ``cryodaq_wdog_tripped = 0`` and erase a possible prior trip."""
    drv = _mode_driver("required")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_tripped")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(Exception):
            await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert t._opened is False  # transport closed on fail-closed abort
    # Latch preserved: no script upload wrote the reset.
    assert not any("function cryodaq_wdog_pet" in w for w in t.writes)
    assert "cryodaq_wdog_run()" not in t.writes


async def test_latch_read_transport_fail_best_effort_degrades(caplog) -> None:
    """HIGH: a TRANSPORT failure on the latch read in best_effort logs CRITICAL
    (latch state unknown, watchdog NOT armed to avoid erasing it), leaves
    _wdog_armed False, uploads NOTHING, and connect still succeeds host-only."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_tripped")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is False
    # No arming happened — latch preserved for the next connect.
    assert not any("function cryodaq_wdog_pet" in w for w in t.writes)
    assert "cryodaq_wdog_run()" not in t.writes
    crits = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert crits
    msg = " ".join(r.getMessage() for r in crits).lower()
    assert "unknown" in msg
    # A poll after must not pet a watchdog that was never armed.
    await drv.read_channels()
    assert "cryodaq_wdog_pet()" not in t.writes


@pytest.mark.parametrize("sentinel", ["nil", " nil \r\n"])
async def test_latch_read_explicit_fresh_sentinel_is_untripped(sentinel) -> None:
    """Only explicit fresh-instrument sentinels permit the first upload."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_tripped_raw = sentinel
    t.wdog_autonomous_raw = "1"  # isolate latch parsing from the v3 gate
    drv._transport = t
    await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is True
    assert "cryodaq_wdog_run()" in t.writes


@pytest.mark.parametrize(
    "raw",
    ["garbage", "undefined", "NIL", "nan", "inf", "-inf", "2", "-1", "0.5", "", "true"],
)
@pytest.mark.parametrize("mode", ["best_effort", "required"])
async def test_latch_malformed_preserves_evidence_without_upload(raw, mode, caplog) -> None:
    drv = _mode_driver(mode)
    t = _RecordingTransport()
    t.wdog_tripped_raw = raw
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        if mode == "required":
            with pytest.raises(Exception):
                await drv.connect()
        else:
            await drv.connect()
    assert not any("function cryodaq_wdog_pet" in w for w in t.writes)
    assert "cryodaq_wdog_run()" not in t.writes
    assert drv._wdog_armed is False
    assert "unknown" in " ".join(r.getMessage() for r in caplog.records).lower()


async def test_mode_required_refuses_non_autonomous_v3(caplog) -> None:
    drv = _mode_driver("required")
    t = _RecordingTransport()  # v3 reports cryodaq_wdog_autonomous=0
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(Exception):
            await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert drv._wdog_autonomous is False
    assert t._opened is False
    assert "cryodaq_wdog_run()" not in t.writes
    assert "required" in " ".join(r.getMessage() for r in caplog.records).lower()


@pytest.mark.parametrize("raw", ["0", "2", "true", "nil", ""])
async def test_required_accepts_only_literal_numeric_one(raw) -> None:
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_autonomous_raw = raw
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._wdog_autonomous is False
    assert "cryodaq_wdog_run()" not in t.writes


async def test_best_effort_non_autonomous_warning_is_bounded(caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()
        await drv.read_channels()
        await drv.read_channels()
    degraded = [
        r for r in caplog.records if r.levelno == logging.CRITICAL and "non-autonomous" in r.getMessage().lower()
    ]
    assert len(degraded) == 1
    assert "zero full-host-death coverage" in degraded[0].getMessage().lower()
    assert drv._wdog_armed is True
    assert drv._wdog_autonomous is False


async def test_best_effort_autonomous_readback_failure_still_runs_late_pet(caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_autonomous")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is True
    assert drv._wdog_autonomous is False
    assert "cryodaq_wdog_run()" in t.writes
    assert "zero full-host-death coverage" in " ".join(r.getMessage() for r in caplog.records).lower()


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "2", "-1", "0.5", "true", ""])
async def test_best_effort_invalid_autonomous_flag_is_rejected_but_late_pet_runs(raw, caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_autonomous_raw = raw
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is True
    assert drv._wdog_autonomous is False
    assert "cryodaq_wdog_run()" in t.writes
    assert "readback failed" in " ".join(r.getMessage() for r in caplog.records).lower()


def test_alias_enabled_true_maps_to_best_effort() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B, WatchdogMode

    drv = Keithley2604B("k2604", "USB0::FAKE", watchdog_enabled=True)
    assert drv._wdog_mode is WatchdogMode.BEST_EFFORT
    assert drv._wdog_enabled is True


def test_alias_enabled_false_maps_to_off() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B, WatchdogMode

    drv = Keithley2604B("k2604", "USB0::FAKE", watchdog_enabled=False)
    assert drv._wdog_mode is WatchdogMode.OFF
    assert drv._wdog_enabled is False


def test_explicit_mode_wins_over_alias() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B, WatchdogMode

    # alias says off, explicit mode says required — mode wins.
    drv = Keithley2604B("k2604", "USB0::FAKE", watchdog_mode="required", watchdog_enabled=False)
    assert drv._wdog_mode is WatchdogMode.REQUIRED


def test_invalid_mode_string_raises() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    with pytest.raises(ValueError):
        Keithley2604B("k2604", "USB0::FAKE", watchdog_mode="bogus")


def _load_keithley_driver_mode(tmp_path, mode_literal: str):
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        f"    mode: {mode_literal}\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n",
        encoding="utf-8",
    )
    return _load_drivers(cfg, mock=True).instrument_configs[0].driver


def test_config_mode_required_builds_required(tmp_path) -> None:
    from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode

    drv = _load_keithley_driver_mode(tmp_path, "required")
    assert drv._wdog_mode is WatchdogMode.REQUIRED


def test_config_mode_invalid_fails_engine_load(tmp_path) -> None:
    """An unknown mode string must fail the engine config load (fail-closed)."""
    with pytest.raises(ValueError):
        _load_keithley_driver_mode(tmp_path, "bogus")


# ---------------------------------------------------------------------------
# (k) A8 integrity checks: version stamp + post-run state readback
# ---------------------------------------------------------------------------


async def test_version_stamp_readback_matches_and_arms() -> None:
    """Happy path: firmware version equals the driver constant → arm proceeds
    and the version query is issued AFTER the script upload."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()  # wdog_version_raw defaults to matching v3
    drv._transport = t
    await drv.connect()
    assert drv._wdog_armed is True
    upload_idx = next(
        i for i, (kind, cmd) in enumerate(t.calls) if kind == "write" and "function cryodaq_wdog_pet" in cmd
    )
    ver_idx = next(i for i, (kind, cmd) in enumerate(t.calls) if kind == "query" and "CRYODAQ_WDOG_VERSION" in cmd)
    autonomous_idx = next(
        i for i, (kind, cmd) in enumerate(t.calls) if kind == "query" and "cryodaq_wdog_autonomous" in cmd
    )
    run_idx = next(i for i, (kind, cmd) in enumerate(t.calls) if kind == "write" and cmd == "cryodaq_wdog_run()")
    assert upload_idx < ver_idx < autonomous_idx < run_idx


async def test_autonomous_readback_failure_required_refuses_before_run() -> None:
    drv = _mode_driver("required")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_autonomous")
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert drv._wdog_autonomous is False
    assert "cryodaq_wdog_run()" not in t.writes


async def test_version_mismatch_best_effort_degrades(caplog) -> None:
    """A wrong version stamp (truncated/stale upload) in best_effort logs
    CRITICAL, leaves _wdog_armed False, and does NOT block connect."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_version_raw = "1"  # firmware is an older/partial script
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    # A poll after a refused arm must not pet a watchdog it never armed.
    await drv.read_channels()
    assert "cryodaq_wdog_pet()" not in t.writes


async def test_version_mismatch_required_raises_and_closes() -> None:
    """A wrong version stamp in required is fail-CLOSED: connect() aborts and
    the transport is closed."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_version_raw = "999"
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert t._opened is False


async def test_version_unparseable_required_raises() -> None:
    """A ``nil`` version (global missing → upload never defined it) must NOT be
    treated as a match: required fails closed."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_version_raw = "nil"
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False


@pytest.mark.parametrize("raw", ["3.9", "2", "nan", "inf", "-inf", "true", "", "  "])
async def test_version_readback_requires_exact_finite_v3(raw, caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_version_raw = raw
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_run()" not in t.writes
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


async def test_arm_state_readback_active_false_best_effort_degrades(caplog) -> None:
    """Post-run readback shows the script did not activate (active=0): best_effort
    refuses to set _wdog_armed and continues host-only."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    drv._transport = t
    # Undo the write()-driven active=1 transition so the readback sees a failed
    # arm even though run() was written (models a truncated function body).
    original_write = t.write

    async def _write_swallow_run(cmd: str) -> None:
        await original_write(cmd)
        if cmd == "cryodaq_wdog_run()":
            t.wdog_active_raw = "0"

    t.write = _write_swallow_run  # type: ignore[assignment]
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


async def test_arm_state_readback_active_false_required_raises() -> None:
    """Post-run active=0 in required is fail-CLOSED."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_autonomous_raw = "1"  # reach downstream active readback
    original_write = t.write

    async def _write_swallow_run(cmd: str) -> None:
        await original_write(cmd)
        if cmd == "cryodaq_wdog_run()":
            t.wdog_active_raw = "0"

    t.write = _write_swallow_run  # type: ignore[assignment]
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("active", "nan"),
        ("active", "inf"),
        ("active", "-inf"),
        ("active", "2"),
        ("active", "0.5"),
        ("active", "true"),
        ("active", ""),
        ("tripped", "nan"),
        ("tripped", "inf"),
        ("tripped", "-inf"),
        ("tripped", "2"),
        ("tripped", "0.5"),
        ("tripped", "true"),
        ("tripped", ""),
    ],
)
async def test_post_run_state_requires_exact_zero_one(field, raw, caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    original_write = t.write

    async def _write_bad_state(cmd: str) -> None:
        await original_write(cmd)
        if cmd == "cryodaq_wdog_run()":
            if field == "active":
                t.wdog_active_raw = raw
            else:
                t.wdog_tripped_raw = raw

    t.write = _write_bad_state  # type: ignore[assignment]
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_disarm()" in t.writes
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


# ---------------------------------------------------------------------------
# F4 (Phase A gate, MEDIUM): readback failure AFTER cryodaq_wdog_run() must
# attempt a best-effort disarm write — the command may have been accepted even
# though the host cannot confirm the script state.
# ---------------------------------------------------------------------------


async def test_arm_readback_timeout_after_run_sends_disarm_best_effort(caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_active")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_run()" in t.writes, "run() must have been issued before the readback failed"
    assert "cryodaq_wdog_disarm()" in t.writes, "a best-effort disarm write must follow a readback failure after run()"


async def test_arm_readback_timeout_after_run_sends_disarm_required(caplog) -> None:
    drv = _mode_driver("required")
    # "cryodaq_wdog_active" is unique to the POST-run readback (line ~626) —
    # unlike "cryodaq_wdog_tripped", which is also queried pre-upload (the
    # latch check) and would fail before run() is ever issued.
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_active")
    t.wdog_autonomous_raw = "1"  # reach downstream active readback
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(Exception):
            await drv.connect()
    assert drv._connected is False
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_run()" in t.writes
    assert "cryodaq_wdog_disarm()" in t.writes


async def test_arm_readback_failure_before_run_does_not_send_disarm() -> None:
    """A failure BEFORE cryodaq_wdog_run() (e.g. version-stamp mismatch) must
    NOT attempt a disarm write — the activation command was never issued."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_version_raw = "1"  # mismatch -> raises before cryodaq_wdog_run()
    drv._transport = t
    await drv.connect()
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_run()" not in t.writes
    assert "cryodaq_wdog_disarm()" not in t.writes


async def test_arm_readback_timeout_disarm_write_also_fails_logs_critical(caplog) -> None:
    """If the best-effort disarm write ALSO fails, TSP activation state is
    unknown — must log CRITICAL and still route per mode (best_effort
    degrades host-only, connect still succeeds)."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_active")
    # _RecordingTransport's fail_on is a substring match, and the uploaded
    # script text itself contains "cryodaq_wdog_disarm()" as part of the
    # function definition — a substring fail_on would (wrongly) fail the
    # initial script upload instead of the disarm command. Override write()
    # to fail only the EXACT disarm command (same technique as
    # test_arm_state_readback_active_false_best_effort_degrades above).
    original_write = t.write

    async def _write_fail_disarm_only(cmd: str) -> None:
        if cmd == "cryodaq_wdog_disarm()":
            raise RuntimeError("simulated disarm failure")
        await original_write(cmd)

    t.write = _write_fail_disarm_only  # type: ignore[assignment]
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is False
    crits = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    msg = " ".join(r.getMessage() for r in crits).lower()
    assert "unknown" in msg, "disarm-write failure must log that TSP state is UNKNOWN"


def test_config_short_timeout_warns(tmp_path, caplog) -> None:
    """DELTA 5: timeout_s shorter than 2×poll_interval_s warns (no fail)."""
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        "    mode: best_effort\n"
        "    timeout_s: 1.0\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n"
        "    poll_interval_s: 2.0\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        drivers = _load_drivers(cfg, mock=True)
    assert drivers.instrument_configs  # still loads
    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING and "poll_interval_s" in record.message
    ]
    assert len(warnings) == 1


@pytest.mark.parametrize(
    ("mode", "timeout_s"),
    [("off", 1.0), ("best_effort", 4.0)],
)
def test_config_watchdog_does_not_warn_when_off_or_at_two_poll_intervals(tmp_path, caplog, mode, timeout_s) -> None:
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        f'    mode: "{mode}"\n'
        f"    timeout_s: {timeout_s}\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n"
        "    poll_interval_s: 2.0\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        _load_drivers(cfg, mock=True)

    assert not [record for record in caplog.records if "poll_interval_s" in record.message]


def test_config_watchdog_mode_wins_over_real_boolean_alias(tmp_path) -> None:
    from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        '    mode: "off"\n'
        "    enabled: true\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n",
        encoding="utf-8",
    )

    driver = _load_drivers(cfg, mock=True).instrument_configs[0].driver

    assert driver._wdog_mode is WatchdogMode.OFF


@pytest.mark.parametrize("literal", ["true", '"5"', ".nan", ".inf", "0", "-1", "301"])
def test_config_watchdog_timeout_invalid_fails_load(tmp_path, literal) -> None:
    from cryodaq.engine import _load_drivers

    cfg = tmp_path / "instruments.yaml"
    cfg.write_text(
        "keithley:\n"
        "  watchdog:\n"
        "    mode: best_effort\n"
        f"    timeout_s: {literal}\n"
        "instruments:\n"
        "  - type: keithley_2604b\n"
        "    name: k2604\n"
        "    resource: USB0::FAKE\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"keithley\.watchdog\.timeout_s"):
        _load_drivers(cfg, mock=True)
