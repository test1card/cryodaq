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
import json
import logging

import msgpack
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

    # The channel identifiers in this laboratory are Cyrillic. A redactor exercised only
    # with ASCII passes while leaking the names actually in use.
    for identifier in ("T12", "Т12"):
        reason = periodic_runtime._invalidation_category(ValueError(f"channel {identifier} at 10.0.0.7 said 4.21"))

        assert "out of sequence" in reason or "malformed" in reason
        assert "10.0.0.7" not in reason and identifier not in reason and "4.21" not in reason


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


def test_the_rejection_site_chooses_the_category_not_the_class() -> None:
    """`ValueError` covered six conditions with one sentence.

    A malformed payload, a sequence gap, a changed publisher counter, a provisional
    overflow, an orphan barrier and a synchronous-callback violation implicate different
    components and need different remedies. The rejection site is the only place that
    knows which one it was.
    """

    rejected = periodic_runtime._FrameRejected("the reading sequence has a gap", "stream discontinuity")

    assert isinstance(rejected, ValueError), "existing handlers select on ValueError"
    assert periodic_runtime._invalidation_category(rejected) == "the reading sequence has a gap"
    # The detail stays available to a local handler and never becomes the category.
    assert str(rejected) == "stream discontinuity"


def test_the_receive_path_conditions_are_distinguishable() -> None:
    """Three conditions the week-long run keeps hitting must read differently."""

    said = {
        periodic_runtime._invalidation_category(periodic_runtime._FrameRejected(category, "detail"))
        for category in (
            "a reading frame did not parse",
            "the reading sequence has a gap",
            "the publisher's drop or failure counters changed",
        )
    }
    assert len(said) == 3, said


def test_no_two_rejection_sites_share_a_category_by_accident() -> None:
    """MEASURED, not assumed: one bucket covered eleven different checks.

    On Ubuntu 22.04 the first run at this branch's head reported
    `the receive loop stopped: a frame was malformed` over and over -- a sentence shared
    by the transport envelope, the reading frame, the reading shape, the reading value,
    the raw value, the metadata, the event shape, the event payload, the barrier marker
    and the multipart frame. Ten checks, one diagnosis, and no way to tell which fired.

    So this reads the categories out of the module and requires that a category is either
    used once, or used by sites that genuinely mean the same thing -- which is a decision
    a person makes and records HERE, not a coincidence of drafting.
    """

    import collections
    import re
    from pathlib import Path

    source = Path(periodic_runtime.__file__).read_text(encoding="utf-8")
    categories = re.findall(r"_FrameRejected\(\s*['\"](.+?)['\"]\s*,", source)
    assert len(categories) >= 20, f"only {len(categories)} rejection sites found"

    # Categories deliberately shared, each with the reason it is shared.
    SHARED = {
        "the frame carried an invalid transport envelope": 3,  # three fields of one envelope
        "the provisional buffer overflowed": 2,  # by frame count and by byte count
    }
    counted = collections.Counter(categories)
    unexpected = {category: count for category, count in counted.items() if count > 1 and SHARED.get(category) != count}
    assert not unexpected, (
        "these categories are used by more sites than were deliberately shared, so a "
        f"diagnosis cannot say which check fired: {unexpected}"
    )


def test_a_rejected_frame_reaches_the_loop_reason(caplog: pytest.LogCaptureFixture) -> None:
    """Driven through `_receive_loop`, with the frame handler refusing a real frame."""

    source = _fresh()

    class _Socket:
        async def recv_multipart(self):
            return [b"topic", b"payload"]

    async def _refuse(_parts):
        raise periodic_runtime._FrameRejected(
            "the publisher's drop or failure counters changed", "publisher counters changed"
        )

    source._socket = _Socket()
    source._handle_frame = _refuse

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        asyncio.run(_SOURCE._receive_loop(source))

    assert "counters changed" in source._invalidation_reason
    assert "publisher counters changed" != source._invalidation_reason, (
        "the frame's own detail must not become the reason"
    )


def test_a_named_barrier_failure_survives_to_the_watcher() -> None:
    """Driven through the REAL `ready()` -> `_invalidate` -> `wait()` path.

    `ready()` works out a reason and raises it. The outer handler recorded the CLASS name
    instead, so the immediate caller saw the detail while the watcher released by
    `_invalidate` reported the generic replacement to whoever was waiting.

    An earlier version of this test called `_invalidate` with the reason itself, which
    proved only that a string survives a setter -- reverting the fix left it green.
    """

    source = _fresh()
    source._ready_active = False
    source._ready_task = None
    source._retired_ready_nonces = set()
    source._connected = None  # `ready()` refuses here, with a reason it chose

    async def _drive() -> None:
        with pytest.raises(periodic_runtime.PeriodicLiveDiscontinuity):
            await _SOURCE.ready(source)

        assert source._invalid is True
        assert "connection event" in source._invalidation_reason, (
            f"the barrier's own reason was replaced: {source._invalidation_reason!r}"
        )

        # And the watcher, which is the LATER observer, gets that same reason.
        failure = asyncio.get_running_loop().create_future()
        failure.set_result(None)
        source._failure = failure
        with pytest.raises(periodic_runtime.PeriodicLiveDiscontinuity) as raised:
            await _SOURCE.wait(source)
        assert "connection event" in str(raised.value)

    asyncio.run(_drive())


def test_an_untrusted_barrier_error_code_never_reaches_the_log_or_limiter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The protocol seam must close an arbitrary provider value before recording it."""

    untrusted = "operator-token-and-address-" + "x" * 4096

    class _Reply:
        ok = False
        error_code = untrusted

    class _Query:
        async def barrier(self, _nonce: str) -> object:
            return _Reply()

    async def _drive() -> None:
        source = _SOURCE(_Query())
        source._running = True
        source._failure = asyncio.get_running_loop().create_future()
        source._connected = asyncio.Event()
        source._connected.set()

        periodic_runtime._last_discontinuity_log.clear()
        with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
            with pytest.raises(periodic_runtime.PeriodicLiveDiscontinuity) as raised:
                await source.ready()

        expected = "the engine barrier query returned an unsupported failure code"
        assert raised.value.reason == expected
        assert source._invalidation_reason == expected
        assert set(periodic_runtime._last_discontinuity_log) == {expected}
        assert untrusted not in "\n".join(record.getMessage() for record in caplog.records)
        await source.stop()

    asyncio.run(_drive())


def test_an_invalid_transport_sequence_reaches_the_loop_reason(caplog: pytest.LogCaptureFixture) -> None:
    """A real reading frame must recategorize its helper validator failure."""

    source = _fresh()
    source._state_lock = asyncio.Lock()

    class _Socket:
        async def recv_multipart(self):
            return [
                periodic_runtime.DEFAULT_TOPIC,
                msgpack.packb(
                    {
                        "ts": 1.0,
                        "iid": "instrument",
                        "ch": "channel",
                        "v": 1.0,
                        "u": "K",
                        "st": "ok",
                        "raw": None,
                        "meta": {},
                        "transport": {
                            "schema": periodic_runtime.PERIODIC_STREAM_SCHEMA,
                            "session_id": "0" * 32,
                            "sequence": "not-an-integer",
                            "persistence_authoritative": False,
                        },
                    },
                    use_bin_type=True,
                ),
            ]

    source._socket = _Socket()

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        asyncio.run(_SOURCE._receive_loop(source))

    assert "transport sequence was invalid" in source._invalidation_reason


@pytest.mark.parametrize(
    ("topic", "payload", "expected"),
    [
        (
            periodic_runtime.DEFAULT_TOPIC,
            msgpack.packb(
                {
                    "ts": "not-a-timestamp",
                    "iid": "instrument",
                    "ch": "channel",
                    "v": 1.0,
                    "u": "K",
                    "st": "ok",
                    "raw": None,
                    "meta": {},
                    "transport": {
                        "schema": periodic_runtime.PERIODIC_STREAM_SCHEMA,
                        "session_id": "0" * 32,
                        "sequence": 1,
                        "persistence_authoritative": False,
                    },
                },
                use_bin_type=True,
            ),
            "a reading frame did not validate",
        ),
        (periodic_runtime.EVENTS_TOPIC, b"not-json", "an event frame did not validate"),
    ],
)
def test_parser_failures_reach_the_receive_loop_with_their_own_categories(
    topic: bytes, payload: bytes, expected: str
) -> None:
    """Drive helpers and parsers through the loop instead of classifying their exceptions directly."""

    source = _fresh()
    source._state_lock = asyncio.Lock()

    class _Socket:
        async def recv_multipart(self):
            return [topic, payload]

    source._socket = _Socket()

    asyncio.run(_SOURCE._receive_loop(source))

    assert expected in source._invalidation_reason


def test_an_event_sequence_gap_names_the_global_stream_in_the_receive_loop() -> None:
    """Events and readings share the same transport sequence, so the diagnosis must not blame readings."""

    source = _fresh()
    source._session_id = "0" * 32
    source._last_sequence = 1
    source._state_lock = asyncio.Lock()
    source._on_event = lambda _event: None

    class _Socket:
        async def recv_multipart(self):
            return [
                periodic_runtime.EVENTS_TOPIC,
                json.dumps(
                    {
                        "event_type": "notice",
                        "ts": 1.0,
                        "payload": {},
                        "experiment_id": None,
                        "transport": {
                            "schema": periodic_runtime.PERIODIC_STREAM_SCHEMA,
                            "session_id": "0" * 32,
                            "sequence": 3,
                            "persistence_authoritative": False,
                        },
                    }
                ).encode(),
            ]

    source._socket = _Socket()

    asyncio.run(_SOURCE._receive_loop(source))

    assert "global stream sequence has a gap" in source._invalidation_reason
    assert "reading sequence" not in source._invalidation_reason


@pytest.mark.parametrize("callback_error", [OSError("callback socket error"), ValueError("callback value error")])
def test_a_callback_failure_is_not_mislabeled_as_a_frame_or_transport_failure(
    callback_error: Exception,
) -> None:
    """A valid event through the receive loop must identify the subscriber callback."""

    source = _fresh()
    source._session_id = "0" * 32
    source._last_sequence = 1
    source._state_lock = asyncio.Lock()

    def callback(_event: object) -> None:
        raise callback_error

    class _Socket:
        async def recv_multipart(self):
            return [
                periodic_runtime.EVENTS_TOPIC,
                json.dumps(
                    {
                        "event_type": "notice",
                        "ts": 1.0,
                        "payload": {},
                        "experiment_id": None,
                        "transport": {
                            "schema": periodic_runtime.PERIODIC_STREAM_SCHEMA,
                            "session_id": "0" * 32,
                            "sequence": 2,
                            "persistence_authoritative": False,
                        },
                    }
                ).encode(),
            ]

    source._on_event = callback
    source._socket = _Socket()
    asyncio.run(_SOURCE._receive_loop(source))

    assert "a periodic live callback failed" in source._invalidation_reason
    assert "subscriber transport failed" not in source._invalidation_reason
