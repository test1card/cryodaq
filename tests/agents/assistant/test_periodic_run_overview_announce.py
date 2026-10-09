"""The coordinator announces a delivered slot; the wiring layer adds the chart.

The whole-run companion photo is deliberately outside the fenced report state
machine. That machine owns exactly one artifact per slot, with a receipt and a
retry ladder, and the operator's report must not become less reliable because a
supplementary chart failed to build or send.
"""

from typing import Any

import pytest

from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator
from cryodaq.periodic_state import PeriodicStatus


class _StubCoordinator:
    """Exercises _announce_delivered_slot against a scripted state document."""

    def __init__(self, terminal: dict[str, Any] | None, listener) -> None:
        self._terminal = terminal
        self._on_report_delivered = listener
        self._run_overview_slot_end: int | None = None
        self._stopping = False

    async def _load_state(self):
        class _Doc:
            payload = {"last_terminal": self._terminal}

        return _Doc()

    _announce_delivered_slot = PeriodicPngCoordinator._announce_delivered_slot
    _adopt_announced_slot = PeriodicPngCoordinator._adopt_announced_slot


def _terminal(status: str, slot_end: int) -> dict[str, Any]:
    return {"status": status, "slot_end": slot_end}


@pytest.mark.asyncio
async def test_delivered_slot_is_announced_exactly_once() -> None:
    seen: list[int] = []

    async def listener(slot_end: int) -> None:
        seen.append(slot_end)

    coordinator = _StubCoordinator(_terminal(PeriodicStatus.SUCCEEDED.value, 1788199200), listener)
    await coordinator._announce_delivered_slot()
    await coordinator._announce_delivered_slot()
    await coordinator._announce_delivered_slot()
    assert seen == [1788199200]


@pytest.mark.asyncio
async def test_a_new_slot_is_announced_again() -> None:
    seen: list[int] = []

    async def listener(slot_end: int) -> None:
        seen.append(slot_end)

    coordinator = _StubCoordinator(_terminal(PeriodicStatus.SUCCEEDED.value, 1788199200), listener)
    await coordinator._announce_delivered_slot()
    coordinator._terminal = _terminal(PeriodicStatus.SUCCEEDED.value, 1788202800)
    await coordinator._announce_delivered_slot()
    assert seen == [1788199200, 1788202800]


@pytest.mark.asyncio
async def test_a_report_that_did_not_reach_the_operator_is_not_announced() -> None:
    seen: list[int] = []

    async def listener(slot_end: int) -> None:
        seen.append(slot_end)

    coordinator = _StubCoordinator(_terminal("FAILED", 1788199200), listener)
    await coordinator._announce_delivered_slot()
    assert seen == []


@pytest.mark.asyncio
async def test_listener_failure_cannot_disturb_the_report_machine() -> None:
    calls = 0

    async def listener(slot_end: int) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("chart could not be built")

    coordinator = _StubCoordinator(_terminal(PeriodicStatus.SUCCEEDED.value, 1788199200), listener)
    await coordinator._announce_delivered_slot()
    # And it is not retried: the slot was claimed before the call, so a broken
    # listener cannot resend on every reconcile pass.
    await coordinator._announce_delivered_slot()
    assert calls == 1


@pytest.mark.asyncio
async def test_no_listener_is_a_valid_configuration() -> None:
    coordinator = _StubCoordinator(_terminal(PeriodicStatus.SUCCEEDED.value, 1788199200), None)
    await coordinator._announce_delivered_slot()


@pytest.mark.asyncio
async def test_nothing_delivered_yet_is_not_announced() -> None:
    seen: list[int] = []

    async def listener(slot_end: int) -> None:
        seen.append(slot_end)

    coordinator = _StubCoordinator(None, listener)
    await coordinator._announce_delivered_slot()
    assert seen == []


@pytest.mark.asyncio
async def test_restart_does_not_resend_an_already_delivered_slot() -> None:
    """A restart must not re-announce the report delivered before it started.

    The announcement memory lives in the coordinator object, so a process that
    comes up to find a SUCCEEDED terminal would otherwise announce it again and
    the operator would get a duplicate companion chart on every restart — and
    the assistant restarts on config changes and on its supervisor's backoff.
    """
    seen: list[int] = []

    async def listener(slot_end: int) -> None:
        seen.append(slot_end)

    coordinator = _StubCoordinator(_terminal(PeriodicStatus.SUCCEEDED.value, 1788199200), listener)
    await coordinator._adopt_announced_slot()
    await coordinator._announce_delivered_slot()
    assert seen == []

    # The next report still announces normally.
    coordinator._terminal = _terminal(PeriodicStatus.SUCCEEDED.value, 1788202800)
    await coordinator._announce_delivered_slot()
    assert seen == [1788202800]
