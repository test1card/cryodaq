"""TSP dead-man watchdog plumbing for the Keithley 2604B.

All behaviour is gated behind ``_wdog_enabled`` (default False). The default-OFF
path MUST emit a command stream byte-identical to today (zero ``cryodaq_wdog``
strings). Tests drive a fake TSP transport and assert exact command strings.
"""

from __future__ import annotations

import logging

import pytest

from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


class _RecordingTransport:
    """Fake TSP transport that records every write and answers the queries the
    driver issues on connect/poll. ``fail_on`` marks a substring whose write
    raises, to exercise the upload-failure path."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        # Combined chronological log of ("query"|"write", cmd) so tests can
        # assert cross-kind ordering (e.g. latch read BEFORE script upload).
        self.calls: list[tuple[str, str]] = []
        self._fail_on = fail_on
        self._opened = False
        self.wdog_tripped_raw = "0"

    async def open(self, resource: str) -> None:
        self._opened = True

    async def close(self) -> None:
        self._opened = False

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        self.queries.append(cmd)
        self.calls.append(("query", cmd))
        c = cmd.lower()
        if "*idn?" in c:
            return "Keithley Instruments Inc., Model 2604B"
        if "cryodaq_wdog_tripped" in c:
            return self.wdog_tripped_raw
        if "source.output" in c:
            return "0"
        if "errorqueue.count" in c:
            return "0"
        return "0"

    async def write(self, cmd: str) -> None:
        if self._fail_on is not None and self._fail_on in cmd:
            raise RuntimeError("simulated upload failure")
        self.writes.append(cmd)
        self.calls.append(("write", cmd))


def _wdog_writes(transport: _RecordingTransport) -> list[str]:
    return [w for w in transport.writes if "cryodaq_wdog" in w or "CRYODAQ_WDOG" in w]


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

    on_without_wdog = [
        w for w in on.writes if "cryodaq_wdog" not in w and "CRYODAQ_WDOG" not in w
    ]
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
    return _load_drivers(cfg, mock=True)[0].driver


@pytest.mark.parametrize("literal", ['"false"', '"true"', '"0"'])
def test_config_wdog_enabled_requires_real_bool(tmp_path, literal) -> None:
    """A quoted/truthy-string ``enabled`` must fail closed (watchdog OFF)."""
    drv = _load_keithley_driver(tmp_path, literal)
    assert drv._wdog_enabled is False


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
    assert "cryodaq_wdog_run()" in t.writes


async def test_mode_best_effort_arm_fail_is_non_fatal(caplog) -> None:
    drv = _mode_driver("best_effort")
    t = _RecordingTransport(fail_on="cryodaq_wdog_run")
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise (fail-OPEN on watchdog layer)
    assert drv._connected is True
    assert drv._wdog_armed is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


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
    t = _RecordingTransport(fail_on="cryodaq_wdog_run")
    drv._transport = t
    with pytest.raises(Exception):
        await drv.connect()
    assert drv._connected is False


async def test_latch_read_before_upload_and_proceeds(caplog) -> None:
    """DELTA 1/2: a latched past-trip is read BEFORE the upload wipes it, logs
    CRITICAL, and arming PROCEEDS in armed modes (no operator lockout)."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"  # firmware latched a kill while host was away
    drv._transport = t
    with caplog.at_level(logging.CRITICAL):
        await drv.connect()  # must NOT raise — pre-existing latch is not a failure

    assert drv._connected is True
    assert drv._wdog_armed is True
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    # The latch query must appear BEFORE the script upload in the call log.
    kinds = t.calls
    latch_idx = next(
        i for i, (kind, cmd) in enumerate(kinds)
        if kind == "query" and "cryodaq_wdog_tripped" in cmd
    )
    upload_idx = next(
        i for i, (kind, cmd) in enumerate(kinds)
        if kind == "write" and "function cryodaq_wdog_pet" in cmd
    )
    assert latch_idx < upload_idx


async def test_latch_read_before_upload_best_effort_too() -> None:
    """Latch read + CRITICAL proceed applies in best_effort as well."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "1"
    drv._transport = t
    await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is True


async def test_mode_required_happy_arms() -> None:
    drv = _mode_driver("required")
    t = _RecordingTransport()  # tripped_raw defaults to "0"
    drv._transport = t
    await drv.connect()
    assert drv._connected is True
    assert drv._wdog_armed is True


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
    drv = Keithley2604B(
        "k2604", "USB0::FAKE", watchdog_mode="required", watchdog_enabled=False
    )
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
    return _load_drivers(cfg, mock=True)[0].driver


def test_config_mode_required_builds_required(tmp_path) -> None:
    from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode

    drv = _load_keithley_driver_mode(tmp_path, "required")
    assert drv._wdog_mode is WatchdogMode.REQUIRED


def test_config_mode_invalid_fails_engine_load(tmp_path) -> None:
    """An unknown mode string must fail the engine config load (fail-closed)."""
    with pytest.raises(ValueError):
        _load_keithley_driver_mode(tmp_path, "bogus")


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
    assert drivers  # still loads
    assert any(
        "spurious-trip" in r.message or "poll_interval_s" in r.message
        for r in caplog.records
        if r.levelno == logging.WARNING
    )
