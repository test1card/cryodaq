"""When the interlock re-arm hook fails, the operator must be told WHY.

`SafetyManager` logged `type(exc).__name__` and threw the rest away on the
re-arm path -- after which NAMED GUARDS MAY BE BLIND, and `RuntimeError` as the
entire diagnosis does not say whether that is a wiring fault, a config fault or
a transient one. That is the defect the launcher's construction failure had, in
the subsystem where it matters most.

ONE site, not three, and the narrowing was forced by review. Two other
candidates -- the persistence-recovery query and the persistence-failure clear
-- look identical and are NOT enriched: the engine's `_persistence_can_write`
converts every probe failure to False before those handlers can run, so anything
richer written there is decoration on a branch production never takes. The
diagnosis is lost at that boundary, which is where it has to be recovered; a
test below pins that fact so the next reader does not repeat the mistake.

Nor is this a sweep. 149 sites match the pattern repo-wide (15 already carry a
traceback, 15 the message, 119 bare), and the two largest concentrations are
DELIBERATE: `engine.py` and `core/zmq_bridge.py` handle capability tokens, and
tests/core/test_zmq_bridge.py proves it -- it drives a handler failure with a
token in the payload and asserts even the KEY NAME never reaches the log, which
`KeyError('capability_token')` would print.

The traceback is accepted here rather than assumed safe: the root logger's
redaction applies only to handlers hardened by `logging_setup`, so it is not an
invariant of this logger. The engine hardens its handlers before this code can
run, the re-arm hook receives no command payload, and a blind interlock is worth
more than the local source paths a traceback exposes.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.safety_manager import SafetyState

from .test_safety_manager import (  # noqa: PLC2701 - the harness lives with the suite it serves
    _engine_command_context,
    _ExactRunSource,
    _handle_gui_command,
    _make_manager,
    _start_command,
)

_SECRET_FREE_DETAIL = "GPIB board 0 not responding at address 26"


async def _start_with_broken_rearm(caplog: pytest.LogCaptureFixture) -> dict:
    """Through the production Start path, not the hook in isolation."""
    source = _ExactRunSource()
    manager, _broker = await _make_manager(mock=False, keithley=source)
    manager._config.critical_channels = []
    await manager.on_interlock_trip(
        "heater_overtemperature",
        "Т1 Криостат верх",
        380.0,
        action="stop_source",
    )

    def broken_rearm() -> list[str]:
        raise RuntimeError(_SECRET_FREE_DETAIL)

    manager.set_interlock_rearm(broken_rearm)
    context = _engine_command_context(manager, AsyncMock())
    try:
        with caplog.at_level(logging.ERROR, logger="cryodaq.core.safety_manager"):
            result = await _handle_gui_command(_start_command(warning=""), context=context)
        assert result["ok"] is True, result
        assert manager.state is SafetyState.RUNNING
        return result
    finally:
        await manager.stop()


async def test_a_failed_rearm_names_the_reason_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    await _start_with_broken_rearm(caplog)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged, "the class is still useful and must stay"
    assert _SECRET_FREE_DETAIL in logged, "the reason was thrown away"


async def test_a_failed_rearm_keeps_a_traceback(caplog: pytest.LogCaptureFixture) -> None:
    """Where it failed, not only that it failed."""
    await _start_with_broken_rearm(caplog)

    rearm_records = [record for record in caplog.records if "interlock re-arm hook failed" in record.getMessage()]
    assert rearm_records, "the re-arm failure was not logged at all"
    assert any(record.exc_info is not None for record in rearm_records)


async def test_the_operator_record_carries_the_reason(caplog: pytest.LogCaptureFixture) -> None:
    """The warning the operator reads, not only the log nobody opens mid-run."""
    result = await _start_with_broken_rearm(caplog)

    warning = result["operator_warnings"][0]
    assert warning["code"] == "interlock_rearm_unconfirmed"
    assert _SECRET_FREE_DETAIL in warning["reason"]
    assert "heater_overtemperature" in warning["reason"], "the possibly blind guard must still be named"


async def test_the_operator_record_bounds_a_runaway_message(caplog: pytest.LogCaptureFixture) -> None:
    """A driver exception can be arbitrarily long; this record is read on a screen."""
    source = _ExactRunSource()
    manager, _broker = await _make_manager(mock=False, keithley=source)
    manager._config.critical_channels = []
    await manager.on_interlock_trip("heater_overtemperature", "Т1", 380.0, action="stop_source")
    flood = "x" * 5_000

    def broken_rearm() -> list[str]:
        raise RuntimeError(flood)

    manager.set_interlock_rearm(broken_rearm)
    context = _engine_command_context(manager, AsyncMock())
    try:
        with caplog.at_level(logging.ERROR, logger="cryodaq.core.safety_manager"):
            result = await _handle_gui_command(_start_command(warning=""), context=context)
    finally:
        await manager.stop()

    reason = result["operator_warnings"][0]["reason"]
    assert flood not in reason
    assert reason.count("x") <= 200


async def test_the_reason_survives_the_real_reply_encoder(caplog: pytest.LogCaptureFixture) -> None:
    """Slicing was not enough, and a reviewer proved it with one exception.

    The warning is serialized into the command reply, and `encode_command_reply`
    requires valid UTF-8. An exception whose text holds a lone UTF-16 surrogate
    made the encoder raise AFTER the Start had proceeded -- so a run that
    actually succeeded came back to the operator as an unknown outcome. This
    drives the REAL encoder rather than asserting on the string.
    """
    from cryodaq.core.zmq_bridge import encode_command_reply

    source = _ExactRunSource()
    manager, _broker = await _make_manager(mock=False, keithley=source)
    manager._config.critical_channels = []
    await manager.on_interlock_trip("heater_overtemperature", "Т1", 380.0, action="stop_source")

    def broken_rearm() -> list[str]:
        raise RuntimeError("\ud800 lost the reply")  # a lone surrogate

    manager.set_interlock_rearm(broken_rearm)
    context = _engine_command_context(manager, AsyncMock())
    try:
        with caplog.at_level(logging.ERROR, logger="cryodaq.core.safety_manager"):
            result = await _handle_gui_command(_start_command(warning=""), context=context)
    finally:
        await manager.stop()

    assert result["ok"] is True
    encode_command_reply(result)


async def test_a_control_character_does_not_reach_the_operator_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Not whitespace, so collapsing whitespace does not remove it.

    U+0007 in an operator-facing string is a terminal bell, and U+001B starts an
    escape sequence. The printable filter is what stops them; this is the case
    that makes it individually necessary rather than redundant.
    """
    source = _ExactRunSource()
    manager, _broker = await _make_manager(mock=False, keithley=source)
    manager._config.critical_channels = []
    await manager.on_interlock_trip("heater_overtemperature", "Т1", 380.0, action="stop_source")

    def broken_rearm() -> list[str]:
        raise RuntimeError("bell\x07 and escape\x1b[31m")

    manager.set_interlock_rearm(broken_rearm)
    context = _engine_command_context(manager, AsyncMock())
    try:
        with caplog.at_level(logging.ERROR, logger="cryodaq.core.safety_manager"):
            result = await _handle_gui_command(_start_command(warning=""), context=context)
    finally:
        await manager.stop()

    reason = result["operator_warnings"][0]["reason"]
    assert "\x07" not in reason
    assert "\x1b" not in reason
    assert "bell" in reason and "escape" in reason, "the readable part must survive"


async def test_the_persistence_probe_swallows_its_own_diagnosis() -> None:
    """Why the two neighbouring sites are deliberately class-only.

    They look like the same defect and are not fixable there: the engine's
    probe wrapper converts every failure to False, so the exception never
    reaches the handler that would log it. Pinned as a fact so the next reader
    enriching those lines finds out here instead of in review.
    """
    from cryodaq.engine import _persistence_can_write

    class _Writer:
        def probe_can_commit(self) -> bool:
            raise RuntimeError("the probe itself failed")

    assert await _persistence_can_write(_Writer()) is False
