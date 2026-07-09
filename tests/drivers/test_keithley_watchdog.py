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

    def __init__(
        self, *, fail_on: str | None = None, query_raises_on: str | None = None
    ) -> None:
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
        # Post-upload integrity readbacks (A8). Defaults model a healthy arm:
        # version matches the driver constant, and cryodaq_wdog_run() has set
        # active=1 / tripped=0. write() below mutates these to mirror the
        # firmware state transitions so latch-then-arm tests stay realistic.
        self.wdog_version_raw = "2"
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
            return "Keithley Instruments Inc., Model 2604B"
        if "cryodaq_wdog_version" in c:
            return self.wdog_version_raw
        if "cryodaq_wdog_active" in c:
            return self.wdog_active_raw
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
        # Mirror firmware state transitions so the post-run readbacks (A8) see
        # the same state a real 2604B would: run() clears the latch and arms;
        # disarm() clears active.
        if cmd == "cryodaq_wdog_run()":
            self.wdog_active_raw = "1"
            self.wdog_tripped_raw = "0"
        elif cmd == "cryodaq_wdog_disarm()":
            self.wdog_active_raw = "0"


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


async def test_off_and_default_command_streams_byte_identical() -> None:
    """True byte-identity: a driver built with ``watchdog_mode='off'`` and one
    built with NO watchdog kwargs must issue the exact same chronological
    command stream (writes AND queries, in order) across connect + poll +
    disconnect — proves the feature is inert, not merely wdog-write-free."""
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


async def test_latch_read_transport_fail_required_raises_and_closes(caplog) -> None:
    """HIGH: a TRANSPORT failure on the pre-upload latch read (state UNKNOWN,
    not "no latch") must abort connect in required mode AND close the transport.
    The script must NOT be uploaded — a re-upload would run
    ``cryodaq_wdog_tripped = 0`` and erase a possible past firmware kill."""
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


async def test_latch_read_unparseable_response_is_untripped() -> None:
    """A SUCCESSFUL query returning an unparseable value (fresh instrument
    prints ``nil``) is genuinely "no latch to read" → arm proceeds normally."""
    drv = _mode_driver("required")
    t = _RecordingTransport()
    t.wdog_tripped_raw = "nil"
    drv._transport = t
    await drv.connect()  # must NOT raise
    assert drv._connected is True
    assert drv._wdog_armed is True
    assert "cryodaq_wdog_run()" in t.writes


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


# ---------------------------------------------------------------------------
# (k) A8 integrity checks: version stamp + post-run state readback
# ---------------------------------------------------------------------------


async def test_version_stamp_readback_matches_and_arms() -> None:
    """Happy path: firmware version equals the driver constant → arm proceeds
    and the version query is issued AFTER the script upload."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()  # wdog_version_raw defaults to the matching "2"
    drv._transport = t
    await drv.connect()
    assert drv._wdog_armed is True
    upload_idx = next(
        i for i, (kind, cmd) in enumerate(t.calls)
        if kind == "write" and "function cryodaq_wdog_pet" in cmd
    )
    ver_idx = next(
        i for i, (kind, cmd) in enumerate(t.calls)
        if kind == "query" and "CRYODAQ_WDOG_VERSION" in cmd
    )
    assert upload_idx < ver_idx


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


async def test_arm_state_readback_active_false_best_effort_degrades(caplog) -> None:
    """Post-run readback shows the firmware did NOT arm (active=0): best_effort
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


# ---------------------------------------------------------------------------
# F4 (Phase A gate, MEDIUM): readback failure AFTER cryodaq_wdog_run() must
# attempt a best-effort disarm write — otherwise firmware may actually be
# armed while the host believes it is not, and a later un-petted firmware
# timer kills outputs by surprise.
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
    assert "cryodaq_wdog_disarm()" in t.writes, (
        "a best-effort disarm write must follow a readback failure after run()"
    )


async def test_arm_readback_timeout_after_run_sends_disarm_required(caplog) -> None:
    drv = _mode_driver("required")
    # "cryodaq_wdog_active" is unique to the POST-run readback (line ~626) —
    # unlike "cryodaq_wdog_tripped", which is also queried pre-upload (the
    # latch check) and would fail before run() is ever issued.
    t = _RecordingTransport(query_raises_on="cryodaq_wdog_active")
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
    NOT attempt a disarm write — the firmware timer was never armed."""
    drv = _mode_driver("best_effort")
    t = _RecordingTransport()
    t.wdog_version_raw = "1"  # mismatch -> raises before cryodaq_wdog_run()
    drv._transport = t
    await drv.connect()
    assert drv._wdog_armed is False
    assert "cryodaq_wdog_run()" not in t.writes
    assert "cryodaq_wdog_disarm()" not in t.writes


async def test_arm_readback_timeout_disarm_write_also_fails_logs_critical(caplog) -> None:
    """If the best-effort disarm write ALSO fails, firmware arm state is truly
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
    assert "unknown" in msg, "disarm-write failure must log that firmware state is UNKNOWN"


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
