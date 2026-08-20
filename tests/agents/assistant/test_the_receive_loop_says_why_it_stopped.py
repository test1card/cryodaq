"""The loop that actually loses authority must say which class of failure took it.

WHY THIS MODULE EXISTS, SEPARATELY FROM ITS SIBLING. Naming every construction site was
not enough. In a real run the source loses authority inside the receive loop, which
catches whatever the frame handler raised and DISCARDS it, so the reason recorded was
always the generic one and `wait()` reported only that the source was already invalid.
The whole fault class -- a sequence gap, a malformed frame, a counter change, a callback
error -- stayed indistinguishable.

The reason is a CLOSED CATEGORY, never the exception text. Frame content carries values,
identifiers and addresses, and this reason reaches both a log line and a durable health
record.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.agents.assistant import periodic_runtime

_SOURCE = periodic_runtime.SequencedPeriodicLiveSources


def _fresh() -> object:
    """A real source object with no transport, built only far enough to lose authority.

    Constructed without `__init__` on purpose: the constructor allocates a ZeroMQ
    context, and this test is about what the loop RECORDS, not about a socket.
    """

    source = object.__new__(_SOURCE)
    source._running = True
    source._stopping = False
    source._invalid = False
    source._invalidation_reason = "the live generation was invalidated"
    source._provisional = []
    source._provisional_bytes = 0
    source._receive_task = None
    source._monitor_task = None
    source._ready_marker = None
    source._failure = None
    source._connected = None
    source._socket = None
    return source


def test_the_category_names_the_class_not_the_text() -> None:
    """A malformed frame's own message must not become the reason."""

    reason = periodic_runtime._invalidation_category(ValueError("channel Т12 at 10.0.0.7 said 4.21"))

    assert "out of sequence" in reason or "malformed" in reason
    assert "10.0.0.7" not in reason and "Т12" not in reason and "4.21" not in reason


def test_every_mapped_class_has_its_own_sentence() -> None:
    """Four classes, four sentences -- a shared sentence is the defect returning."""

    said = {
        periodic_runtime._invalidation_category(error)
        for error in (ValueError("x"), TypeError("x"), KeyError("x"), OSError("x"))
    }
    assert len(said) == 4, said


def test_an_unmapped_class_still_names_itself() -> None:
    class _Odd(RuntimeError):
        pass

    assert "_Odd" in periodic_runtime._invalidation_category(_Odd("x"))


def test_no_error_is_not_reported_as_an_error() -> None:
    assert periodic_runtime._invalidation_category(None) == "the live generation was invalidated"


def test_the_receive_loop_records_the_class_it_caught(caplog: pytest.LogCaptureFixture) -> None:
    """Driven through `_receive_loop`, which is where a real run loses authority."""

    source = _fresh()

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        # No socket, so the loop raises RuntimeError("subscriber unavailable") -- an
        # unmapped class, which must still name itself rather than fall back.
        asyncio.run(_SOURCE._receive_loop(source))

    assert source._invalid is True
    assert "the receive loop stopped" in source._invalidation_reason
    assert "RuntimeError" in source._invalidation_reason
    assert any("the receive loop stopped" in record.getMessage() for record in caplog.records)


def test_wait_reports_the_reason_rather_than_the_state() -> None:
    """`wait()` said only that the source was invalid, which the caller already knew."""

    source = _fresh()
    source._invalid = True
    source._invalidation_reason = "the receive loop stopped: the subscriber transport failed"
    failure: asyncio.Future[None]

    async def _drive() -> None:
        nonlocal failure
        failure = asyncio.get_running_loop().create_future()
        failure.set_result(None)
        source._failure = failure
        with pytest.raises(periodic_runtime.PeriodicLiveDiscontinuity) as raised:
            await _SOURCE.wait(source)
        assert "the subscriber transport failed" in str(raised.value)

    asyncio.run(_drive())
