"""A persistence probe that answers no must say why it answered no.

`_persistence_can_write` is the predicate the SafetyManager consults before
clearing a persistence latch. Every path through it can answer False, and every
one of them used to do so in SILENCE -- so the operator saw a refused Start with
no reason, which is exactly the defect the launcher's construction failure had.

The answers are unchanged. Fail-closed is the point of this predicate: "cannot
tell" is not "recovered". What changed is that each refusal now names its
condition, and the two that carry an exception name it with the message rather
than the class -- because the writer latches on "database is full", "disk quota
exceeded" and a sustained "database is locked", and those three need DIFFERENT
actions from the operator. A class name cannot tell them apart.

Not a sweep: see tests/core/test_safety_failures_say_why.py for why
`engine.py`'s and `zmq_bridge.py`'s other class-only sites are deliberate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from cryodaq.engine import _persistence_can_write

_CONDITION = "database or disk is full"


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


async def test_a_writer_that_cannot_be_asked_says_so(caplog: pytest.LogCaptureFixture) -> None:
    class _Unaskable:
        pass

    with caplog.at_level(logging.WARNING, logger="cryodaq.engine"):
        assert await _persistence_can_write(_Unaskable()) is False

    assert "Persistence probe unavailable" in _logged(caplog)
    assert "_Unaskable" in _logged(caplog), "the operator needs to know WHICH writer could not answer"


async def test_a_probe_that_raises_immediately_names_the_condition(caplog: pytest.LogCaptureFixture) -> None:
    class _RaisesSync:
        def probe_can_commit(self) -> bool:
            raise RuntimeError(_CONDITION)

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        assert await _persistence_can_write(_RaisesSync()) is False

    logged = _logged(caplog)
    assert "RuntimeError" in logged, "the class is still the quick read"
    assert _CONDITION in logged, "the condition the operator has to act on was discarded"


async def test_a_probe_that_raises_in_its_task_names_the_condition(caplog: pytest.LogCaptureFixture) -> None:
    """The awaitable path: the same silence lived here separately."""

    class _RaisesAsync:
        async def probe_can_commit(self) -> bool:
            raise RuntimeError(_CONDITION)

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        assert await _persistence_can_write(_RaisesAsync()) is False

    assert _CONDITION in _logged(caplog)


async def test_a_probe_that_raises_keeps_a_traceback(caplog: pytest.LogCaptureFixture) -> None:
    class _RaisesAsync:
        async def probe_can_commit(self) -> bool:
            raise RuntimeError(_CONDITION)

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        await _persistence_can_write(_RaisesAsync())

    assert any(record.exc_info is not None for record in caplog.records)


async def test_a_probe_that_never_answers_says_it_timed_out(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead mount must not look the same as a failed transaction."""
    import cryodaq.engine as module

    monkeypatch.setattr(module, "_PERSISTENCE_PROBE_BOUND_S", 0.01)

    class _NeverAnswers:
        async def probe_can_commit(self) -> bool:
            await asyncio.sleep(30)
            return True

    with caplog.at_level(logging.WARNING, logger="cryodaq.engine"):
        assert await _persistence_can_write(_NeverAnswers()) is False

    logged = _logged(caplog)
    assert "did not answer within" in logged
    assert "latch stays" in logged


async def test_a_probe_that_answers_yes_says_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """The predicate must stay quiet on the path the operator takes every day."""

    class _Answers:
        async def probe_can_commit(self) -> bool:
            return True

    with caplog.at_level(logging.WARNING, logger="cryodaq.engine"):
        assert await _persistence_can_write(_Answers()) is True

    assert _logged(caplog) == ""


class _Unaskable:
    pass


class _RaisesSync:
    def probe_can_commit(self) -> bool:
        raise RuntimeError(_CONDITION)


class _RaisesAsyncWriter:
    async def probe_can_commit(self) -> bool:
        raise RuntimeError(_CONDITION)


class _NeverAnswersWriter:
    async def probe_can_commit(self) -> bool:
        await asyncio.sleep(30)
        return True


@pytest.mark.parametrize(
    "writer_type",
    [_Unaskable, _RaisesSync, _RaisesAsyncWriter, _NeverAnswersWriter],
    ids=["unaskable", "raises-sync", "raises-async", "never-answers"],
)
async def test_every_refusal_names_the_consequence(
    writer_type: type, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal must name its consequence, not only its cause.

    All FOUR paths, because a reviewer showed that covering two of them let the
    consequence be deleted from a third with every test still green. A refusal
    that says only what failed leaves the operator to work out that Start will
    keep being refused.
    """
    import cryodaq.engine as module

    monkeypatch.setattr(module, "_PERSISTENCE_PROBE_BOUND_S", 0.01)

    with caplog.at_level(logging.WARNING, logger="cryodaq.engine"):
        assert await _persistence_can_write(writer_type()) is False

    assert "latch stays" in _logged(caplog), f"{writer_type.__name__} refused without naming the consequence"


@pytest.mark.parametrize(
    "writer_type",
    [_RaisesSync, _RaisesAsyncWriter],
    ids=["raises-sync", "raises-async"],
)
async def test_every_exception_path_keeps_a_traceback(writer_type: type, caplog: pytest.LogCaptureFixture) -> None:
    """Both of them, not just the asynchronous one.

    The single traceback assertion this file started with covered the async path
    only, so removing exc_info from the synchronous one changed nothing.
    """
    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        assert await _persistence_can_write(writer_type()) is False

    assert any(record.exc_info is not None for record in caplog.records), f"{writer_type.__name__} logged no traceback"


# ---------------------------------------------------------------------------
# The writer's own three paths, where the condition actually has a name
# ---------------------------------------------------------------------------
#
# Each is driven through the real `probe_can_commit` with ONE seam replaced,
# because the conditions cannot be produced from outside: a data directory the
# writer cannot use makes `start_immediate` refuse before the probe is reached,
# and an unstarted writer answers True.


async def _probe_with(
    tmp_path, monkeypatch: pytest.MonkeyPatch, attribute: str, failure: Exception
) -> list[logging.LogRecord]:
    """Return the records the writer logged when `attribute` raises."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    def _raise(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(type(writer), attribute, _raise, raising=True)
    try:
        with caplog_at_writer_level() as records:
            assert await writer.probe_can_commit() is False
    finally:
        with contextlib.suppress(Exception):
            await writer.stop()
    return records


@contextlib.contextmanager
def caplog_at_writer_level():
    """Collect the writer's RECORDS, not only their text.

    Storing `getMessage()` threw away `LogRecord.exc_info`, so the traceback
    assertions could not see it and removing exc_info from either writer site
    left the tests green -- found in review.
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("cryodaq.storage.sqlite_writer")
    handler = _Collect()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


async def test_the_writer_names_why_it_could_not_reach_the_database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The message, not the class: `OperationalError` covers too much.

    That message is the difference between a permissions problem and a full
    disk, and the class name covers both.
    """
    records = await _probe_with(
        tmp_path, monkeypatch, "_ensure_connection", OSError("unable to open database file: /data/x.db")
    )
    logged = "\n".join(record.getMessage() for record in records)

    assert "could not reach the database" in logged
    assert "unable to open database file: /data/x.db" in logged
    assert any(record.exc_info is not None for record in records), "no traceback for an unreachable database"


async def test_the_writer_names_why_the_probe_failed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The condition the operator must act on: full, quota, or locked."""
    records = await _probe_with(tmp_path, monkeypatch, "_await_owned_task", RuntimeError("database or disk is full"))
    logged = "\n".join(record.getMessage() for record in records)

    assert "persistence recovery probe failed" in logged
    assert "database or disk is full" in logged
    assert any(record.exc_info is not None for record in records), "no traceback for a failed probe"


async def test_the_writer_says_when_scheduling_the_probe_failed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """This path returned False in complete silence."""
    records = await _probe_with(tmp_path, monkeypatch, "_owned_executor_task", RuntimeError("write executor is gone"))
    logged = "\n".join(record.getMessage() for record in records)

    assert "could not be scheduled" in logged
    assert "write executor is gone" in logged
