"""A desynchronized GPIB query must be recoverable per device, never per bus.

On 2026-09-01 a single desynchronized query quarantined LS218_2's session at
02:39 and nothing released it: close/open does not, and clear_bus() sends the
SDC but leaves the flag set. Every later query failed with "GPIB session is
quarantined" until the process restarted at 09:25 -- 6.8 hours, plus 2.0 more
that afternoon, during which the scheduler kept writing timeout rows so the row
count stayed at 100%.

The quarantine itself is correct: a stale reply left in the output buffer would
be read as the answer to the NEXT query and published as a reading for the
wrong request. So recovery is only safe under a contract, and these tests are
that contract.

Recovery is SDC-scoped on purpose. ``GPIBTransport.recover()`` sends IFC, which
is interface-wide; three LakeShore sessions share one physical GPIB0 here, so
recovering one device that way would interrupt healthy peers mid-transaction.
"""

import asyncio

import pytest

from cryodaq.drivers.transport.gpib import GPIBTransport


class _NotATimeout(OSError):
    """An adapter/session failure. Proves nothing about a pending response."""


class _FakeResource:
    """A VISA resource that can hold a stale reply and refuse to go quiet."""

    def __init__(
        self,
        *,
        stale: list[str] | None = None,
        clear_fails: bool = False,
        babbles: bool = False,
        read_error: BaseException | None = None,
        restore_fails: bool = False,
    ):
        self._timeout = 3000
        self._stale = list(stale or [])
        self._clear_fails = clear_fails
        self._babbles = babbles
        self._read_error = read_error
        self._restore_fails = restore_fails
        self.clears = 0
        self.reads: list[str] = []
        self.written: list[str] = []

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        # Restoring the original value is what a broken adapter refuses.
        if self._restore_fails and value == 3000 and self._timeout != 3000:
            raise OSError("cannot restore timeout")
        self._timeout = value

    def clear(self):
        self.clears += 1
        if self._clear_fails:
            raise OSError("SDC refused")

    def read(self):
        if self._read_error is not None:
            raise self._read_error
        if self._babbles:
            return "noise"
        if self._stale:
            value = self._stale.pop(0)
            self.reads.append(value)
            return value
        raise TimeoutError("VI_ERROR_TMO")  # quiet

    def write(self, cmd):
        self.written.append(cmd)

    def close(self):
        pass


def _quarantined_transport(resource: _FakeResource) -> GPIBTransport:
    transport = GPIBTransport(mock=False)
    transport._resource = resource
    transport._resource_str = "GPIB0::11::INSTR"
    transport._bus_prefix = "GPIB0"
    transport._session_open = True
    transport._query_desynchronized = True
    return transport


# ---------------------------------------------------------------------------
# The stale reply is discarded, and only then is the quarantine released
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_delayed_stale_reply_is_drained_and_never_returned():
    """The failed query's late answer must not become anyone's reading."""
    resource = _FakeResource(stale=["+294.56,+294.43,+294.46"])
    transport = _quarantined_transport(resource)

    await transport.recover_device()

    assert resource.clears == 1, "recovery must send exactly one SDC"
    assert resource.reads == ["+294.56,+294.43,+294.46"], "the stale reply was not drained"
    assert transport.query_desynchronized is False
    # Nothing the drain read is reachable by a caller: recover_device returns None.


@pytest.mark.asyncio
async def test_recovery_releases_the_quarantine_only_after_a_quiet_observation():
    resource = _FakeResource(stale=["stale-1", "stale-2"])
    transport = _quarantined_transport(resource)
    await transport.recover_device()
    assert len(resource.reads) == 2
    assert transport.query_desynchronized is False


@pytest.mark.asyncio
async def test_recovery_bumps_the_generation_so_old_work_is_stale():
    transport = _quarantined_transport(_FakeResource())
    before = transport._open_generation
    await transport.recover_device()
    assert transport._open_generation > before


# ---------------------------------------------------------------------------
# Every failure leaves the session quarantined, and raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_clear_preserves_the_quarantine():
    resource = _FakeResource(clear_fails=True)
    transport = _quarantined_transport(resource)
    with pytest.raises(Exception):
        await transport.recover_device()
    assert transport.query_desynchronized is True, "a failed SDC must not release the quarantine"


@pytest.mark.asyncio
async def test_a_device_that_keeps_talking_is_not_a_transport_failure():
    """Silence is not achievable on this hardware, so it is not the criterion.

    Measured against a real LS218 on GPIB0 (2026-09-02): after a
    mid-transaction timeout the instrument returned its last response again on
    every read -- 4,096 bytes of the identical 65-byte reply across 64 reads --
    and never went quiet, even after a successful SDC. It re-sends whenever
    addressed to talk with no new command pending.

    What the quarantine protects against is a stale reply being attributed to
    the NEXT query, and the sound proof of that is CORRESPONDENCE. On the same
    instrument, `*IDN?` after SDC returned the identity on the first read. So
    the transport clears and discards, and the caller -- which knows what a
    valid reply looks like -- proves correspondence and re-quarantines if it
    fails. See test_lakeshore_quarantine_recovery.py.
    """
    transport = _quarantined_transport(_FakeResource(babbles=True))
    await transport.recover_device()
    assert transport.query_desynchronized is False


@pytest.mark.asyncio
async def test_recovery_is_refused_while_a_previous_operation_is_unsettled():
    """The failed query may still be inside a VISA read."""
    transport = _quarantined_transport(_FakeResource())
    transport._terminal_unsettled = True
    with pytest.raises(RuntimeError, match="settled"):
        await transport.recover_device()
    assert transport.query_desynchronized is True


@pytest.mark.asyncio
async def test_recovery_is_refused_on_a_closed_session():
    transport = _quarantined_transport(_FakeResource())
    transport._session_open = False
    with pytest.raises(RuntimeError, match="not open"):
        await transport.recover_device()
    assert transport.query_desynchronized is True


@pytest.mark.asyncio
async def test_a_reopen_during_recovery_cannot_unquarantine_the_new_generation():
    """The resource was replaced while the drain was running."""
    resource = _FakeResource()
    transport = _quarantined_transport(resource)
    original = transport._blocking_clear_and_drain

    def _swap_then_drain():
        # Simulate a concurrent reopen: new generation, new resource.
        transport._open_generation += 1
        transport._resource = _FakeResource()
        return original()

    transport._blocking_clear_and_drain = _swap_then_drain
    with pytest.raises(RuntimeError, match="changed during recovery"):
        await transport.recover_device()
    assert transport.query_desynchronized is True


@pytest.mark.asyncio
async def test_recovery_never_reports_failure_by_return_value():
    """The scheduler reads normal completion as success, so failure must raise."""
    transport = _quarantined_transport(_FakeResource(clear_fails=True))
    with pytest.raises(Exception):
        result = await transport.recover_device()
        assert result is not False, "returning False would be read as recovered"


@pytest.mark.asyncio
async def test_a_healthy_session_is_a_no_op():
    transport = _quarantined_transport(_FakeResource())
    transport._query_desynchronized = False
    await transport.recover_device()
    assert transport.query_desynchronized is False


# ---------------------------------------------------------------------------
# Scope: one device, never the interface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_never_touches_the_interface():
    """IFC would reset every device on GPIB0, including healthy peers."""
    transport = _quarantined_transport(_FakeResource())
    ifc_calls: list[str] = []
    transport.send_ifc = lambda: ifc_calls.append("ifc")  # type: ignore[method-assign]
    transport._blocking_ifc = lambda: ifc_calls.append("blocking-ifc")  # type: ignore[method-assign]

    await transport.recover_device()
    assert ifc_calls == [], "device recovery sent an interface-wide IFC"


@pytest.mark.asyncio
async def test_recovering_one_device_leaves_its_peers_untouched():
    """Three sessions share GPIB0; only the quarantined one is acted on."""
    broken_resource = _FakeResource(stale=["stale"])
    broken = _quarantined_transport(broken_resource)

    peers = []
    for address in ("GPIB0::12::INSTR", "GPIB0::13::INSTR"):
        peer_resource = _FakeResource()
        peer = _quarantined_transport(peer_resource)
        peer._resource_str = address
        peer._query_desynchronized = False  # healthy
        peers.append((peer, peer_resource))

    await broken.recover_device()

    assert broken.query_desynchronized is False
    for peer, peer_resource in peers:
        assert peer_resource.clears == 0, f"{peer._resource_str} was cleared by a peer's recovery"
        assert peer.query_desynchronized is False
        assert peer._open_generation == 0, "a peer's generation was invalidated"


def test_the_serial_pressure_transport_is_a_different_class():
    """The Thyracont is on serial and shares nothing with the GPIB stack."""
    from cryodaq.drivers.instruments import thyracont_vsp63d

    source = thyracont_vsp63d.__file__
    assert "gpib" not in open(source, encoding="utf-8").read().lower(), (
        "the serial pressure driver must not depend on the GPIB transport"
    )


# ---------------------------------------------------------------------------
# Only a genuine timeout proves the device is quiet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_read_error_during_the_discard_ends_it_without_failing_recovery():
    """There is nothing more to take; correspondence is proven upstream."""
    transport = _quarantined_transport(_FakeResource(read_error=_NotATimeout("libgpib: invalid descriptor")))
    await transport.recover_device()
    assert transport.query_desynchronized is False


@pytest.mark.asyncio
async def test_a_visa_timeout_also_ends_the_discard():
    from pyvisa import constants
    from pyvisa.errors import VisaIOError

    transport = _quarantined_transport(_FakeResource(read_error=VisaIOError(constants.StatusCode.error_timeout)))
    await transport.recover_device()
    assert transport.query_desynchronized is False


# ---------------------------------------------------------------------------
# A session whose timeout is unknown is not recovered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_timeout_restoration_fails_the_recovery():
    """The drain timeout must never be inherited by *IDN? or a data query.

    A query only overrides res.timeout when it differs from the value the
    session was opened with, and *IDN? is issued with exactly that value. A
    250 ms drain timeout left in place is therefore inherited silently, times
    out, desynchronizes the session again, and loops recovery forever.
    """
    transport = _quarantined_transport(_FakeResource(restore_fails=True))
    with pytest.raises(RuntimeError, match="timeout could not be restored"):
        await transport.recover_device()
    assert transport.query_desynchronized is True


@pytest.mark.asyncio
async def test_a_failed_recovery_closes_the_session_for_a_clean_reopen():
    """open() refuses while a resource is held, so a failure must release it."""
    transport = _quarantined_transport(_FakeResource(clear_fails=True))
    closed: list[str] = []

    async def _close():
        closed.append("closed")
        transport._resource = None
        transport._session_open = False

    transport.close = _close  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await transport.recover_device()
    assert closed == ["closed"], "a failed recovery left the session open and unopenable"
    assert transport.query_desynchronized is True


@pytest.mark.asyncio
async def test_a_successful_recovery_restores_the_original_timeout():
    resource = _FakeResource(stale=["stale"])
    transport = _quarantined_transport(resource)
    await transport.recover_device()
    assert resource.timeout == 3000, "the drain timeout was inherited by later queries"


# ---------------------------------------------------------------------------
# abort_open must invalidate a partial open, not a clean one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aborting_a_clean_transport_does_not_block_reopening():
    """There is no partial open to invalidate, so there is nothing to abort.

    abort_open() set terminal-close intent unconditionally, and open() refuses
    while it is set. A clean close followed by abort_open therefore left the
    transport permanently unopenable -- the same class of defect as the sticky
    query quarantine, reached by a different route.
    """
    transport = GPIBTransport(mock=True)
    await transport.open("GPIB0::11::INSTR", timeout_ms=3000)
    await transport.close()
    await transport.abort_open()
    await transport.open("GPIB0::11::INSTR", timeout_ms=3000)  # must not raise


@pytest.mark.asyncio
async def test_aborting_a_genuinely_open_transport_still_fails_closed():
    """The real purpose survives: a partial open stays invalidated."""
    transport = GPIBTransport(mock=True)
    await transport.open("GPIB0::11::INSTR", timeout_ms=3000)
    await transport.abort_open()
    with pytest.raises(RuntimeError, match="has not settled"):
        await transport.open("GPIB0::11::INSTR", timeout_ms=3000)


@pytest.mark.asyncio
async def test_aborting_a_never_opened_transport_is_a_no_op():
    transport = GPIBTransport(mock=True)
    await transport.abort_open()
    await transport.open("GPIB0::11::INSTR", timeout_ms=3000)  # must not raise
