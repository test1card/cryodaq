"""Regression guards for warning-permissive RUN admission and OFF ordering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.safety_manager import SafetyState
from cryodaq.drivers.contracts import SourceOffResult
from cryodaq.engine import _handle_gui_command
from tests.core.test_safety_manager import (
    _engine_command_context,
    _ExactRunSource,
    _make_manager,
)


def _start_command(channel: str = "smua") -> dict[str, object]:
    return {
        "cmd": "keithley_start",
        "channel": channel,
        "p_target": 0.1,
        "v_comp": 1.0,
        "i_comp": 0.1,
        "protocol_major": 1,
        "mutation_capability": "cryodaq_mutation_v1",
        "capability_token": "test-mutation-token-1",
    }


def _committed_warning_receipt() -> dict[str, object]:
    return {
        "schema": "cryodaq.keithley_warning_choice_receipt.v1",
        "request_id": "b" * 32,
        "committed": True,
        "operator_log_id": 17,
        "replayed": False,
        "error_code": None,
    }


class _SequencedRunSource(_ExactRunSource):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_comp: float,
        i_comp: float,
    ) -> None:
        self.commands.append(f"on:{channel}")
        await super().start_source(channel, p_target, v_comp, i_comp)

    async def emergency_off(self, channel: str | None = None) -> SourceOffResult:
        self.commands.append(f"off:{channel}")
        return await super().emergency_off(channel)


async def _warning_manager(source: _ExactRunSource):
    manager, _broker = await _make_manager(mock=False, keithley=source)
    manager._config.critical_channels = []
    manager._cooldown_predictor_available = False
    manager._cooldown_predictor_unavailable_reason = "injected unavailable predictor"
    manager._refresh_operator_safety_snapshot()
    if isinstance(source, _SequencedRunSource):
        source.commands.clear()
    return manager


async def test_stalled_committer_is_bounded_and_operator_requested_start_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 1: the production committer timeout cannot hold RUN forever."""

    persistence_entered = asyncio.Event()
    persistence_cancelled = asyncio.Event()

    async def stalled_append(**_kwargs: object) -> object:
        persistence_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            persistence_cancelled.set()

    source = _ExactRunSource()
    manager = await _warning_manager(source)
    context = _engine_command_context(
        manager,
        AsyncMock(),
        writer=SimpleNamespace(append_operator_log=stalled_append),
    )
    monkeypatch.setattr(
        "cryodaq.engine._KEITHLEY_WARNING_PERSISTENCE_TIMEOUT_S",
        0.01,
        raising=False,
    )

    try:
        result = await asyncio.wait_for(
            _handle_gui_command(_start_command(), context=context),
            timeout=1.0,
        )

        assert persistence_entered.is_set()
        await asyncio.wait_for(persistence_cancelled.wait(), timeout=1.0)
        assert result["ok"] is True
        assert result["operator_warning_receipt"]["committed"] is False
        assert result["operator_warning_receipt"]["error_code"] == "persistence_timeout"
        assert "не подтверждена" in result["warning"]
        assert source.active_channels == ["smua"]
        assert manager.state is SafetyState.RUNNING
    finally:
        await manager.stop()


async def test_missing_committer_persistence_is_receipted_without_refusing_start() -> None:
    """Property 2: absence is a visible unconfirmed receipt, not a refusal."""

    source = _ExactRunSource()
    manager = await _warning_manager(source)
    context = _engine_command_context(manager, AsyncMock(), writer=None)

    try:
        result = await _handle_gui_command(_start_command(), context=context)

        assert result["ok"] is True
        assert result["operator_warning_receipt"]["committed"] is False
        assert result["operator_warning_receipt"]["error_code"] == "persistence_unavailable"
        assert result["operator_warnings"][0]["code"] == "cooldown_predictor_unavailable"
        assert "не подтверждена" in result["warning"]
        assert source.active_channels == ["smua"]
        assert manager.state is SafetyState.RUNNING
    finally:
        await manager.stop()


async def test_emergency_off_epoch_prevents_on_after_inflight_warning_receipt() -> None:
    """Property 3: OFF overtakes an in-flight receipt and forbids later ON."""

    commit_entered = asyncio.Event()
    release_commit = asyncio.Event()

    async def blocked_commit(_warnings: list[dict[str, str]]) -> dict[str, object]:
        commit_entered.set()
        await release_commit.wait()
        return _committed_warning_receipt()

    source = _SequencedRunSource()
    manager = await _warning_manager(source)
    run_task = asyncio.create_task(
        manager.request_run(
            0.1,
            1.0,
            0.1,
            channel="smua",
            warning_choice_committer=blocked_commit,
        )
    )
    off_task: asyncio.Task[dict[str, object]] | None = None

    try:
        await asyncio.wait_for(commit_entered.wait(), timeout=1.0)
        off_task = asyncio.create_task(manager.emergency_off(channel=None))
        off_result = await asyncio.wait_for(off_task, timeout=1.0)
        assert off_result["ok"] is True
        assert source.commands == ["off:None"]

        release_commit.set()
        run_result = await asyncio.wait_for(run_task, timeout=1.0)

        assert run_result["ok"] is False
        assert source.commands == ["off:None"]
        assert manager._active_sources == set()
    finally:
        release_commit.set()
        for task in (run_task, off_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (run_task, off_task) if task is not None), return_exceptions=True)
        await manager.stop()


async def test_run_queued_before_emergency_captures_abort_epoch_at_admission() -> None:
    """Property 4: a RUN waiting for RUN admission retains its pre-OFF epoch."""

    first_commit_entered = asyncio.Event()
    release_first_commit = asyncio.Event()
    second_commit_calls = 0

    async def blocked_first_commit(_warnings: list[dict[str, str]]) -> dict[str, object]:
        first_commit_entered.set()
        await release_first_commit.wait()
        return _committed_warning_receipt()

    async def second_commit(_warnings: list[dict[str, str]]) -> dict[str, object]:
        nonlocal second_commit_calls
        second_commit_calls += 1
        return _committed_warning_receipt()

    source = _SequencedRunSource()
    manager = await _warning_manager(source)
    first_run = asyncio.create_task(
        manager.request_run(
            0.1,
            1.0,
            0.1,
            channel="smua",
            warning_choice_committer=blocked_first_commit,
        )
    )
    second_run: asyncio.Task[dict[str, object]] | None = None
    off_task: asyncio.Task[dict[str, object]] | None = None

    try:
        await asyncio.wait_for(first_commit_entered.wait(), timeout=1.0)
        second_run = asyncio.create_task(
            manager.request_run(
                0.1,
                1.0,
                0.1,
                channel="smub",
                warning_choice_committer=second_commit,
            )
        )
        for _ in range(100):
            waiters = getattr(manager._run_request_lock, "_waiters", None)
            if waiters:
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("second RUN did not queue at the admission lock")

        off_task = asyncio.create_task(manager.emergency_off(channel=None))
        off_result = await asyncio.wait_for(off_task, timeout=1.0)
        assert off_result["ok"] is True
        assert source.commands == ["off:None"]

        release_first_commit.set()
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first_run, second_run),
            timeout=1.0,
        )

        assert first_result["ok"] is False
        assert second_result["ok"] is False
        assert second_commit_calls == 0
        assert source.commands == ["off:None"]
        assert manager._active_sources == set()
    finally:
        release_first_commit.set()
        for task in (first_run, second_run, off_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first_run, second_run, off_task) if task is not None),
            return_exceptions=True,
        )
        await manager.stop()
