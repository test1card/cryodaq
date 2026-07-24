"""Fail-closed command-ingress recovery authority guards."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

import pytest

import cryodaq.engine as engine

_ENGINE_INSTANCE_ID = "a" * 32


class _Writer:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self._events = events
        self._fail = fail

    async def initialize_operator_log_idempotency(self) -> None:
        self._events.append("writer.initialize")
        if self._fail:
            raise RuntimeError("writer initialization failed")


class _CommandServer:
    def __init__(self) -> None:
        self.start_calls = 0

    async def start(self) -> None:
        self.start_calls += 1


def _install_recovery_fakes(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    fail_at: str | None = None,
) -> None:
    async def reconcile_operator_log(_writer: Any, _broker: Any) -> None:
        events.append("operator_log.reconcile")
        if fail_at == "operator_log":
            raise RuntimeError("operator-log recovery failed")

    async def settle_alarm_ack(
        _writer: Any,
        _broker: Any,
        engine_instance_id: str,
    ) -> tuple[Any, ...]:
        assert engine_instance_id == _ENGINE_INSTANCE_ID
        events.append("alarm_ack.settle")
        if fail_at == "alarm_ack":
            raise RuntimeError("alarm ACK recovery failed")
        return ()

    monkeypatch.setattr(engine, "_reconcile_operator_log_publication_outbox", reconcile_operator_log)
    monkeypatch.setattr(engine, "_settle_alarm_ack_outbox_startup", settle_alarm_ack)


def _authority(
    events: list[str],
    *,
    writer_fails: bool = False,
    engine_instance_id: str = _ENGINE_INSTANCE_ID,
) -> engine._CommandIngressRecoveryAuthority:
    return engine._CommandIngressRecoveryAuthority(
        writer=_Writer(events, fail=writer_fails),
        broker=object(),
        engine_instance_id=engine_instance_id,
    )


@pytest.mark.asyncio
async def test_start_before_settlement_refuses_without_acquiring_rep() -> None:
    authority = _authority([])
    command_server = _CommandServer()

    with pytest.raises(RuntimeError, match="recovery proof is unavailable"):
        await authority.start(command_server)

    assert command_server.start_calls == 0
    with pytest.raises(RuntimeError, match="command ingress start is one-use"):
        await authority.start(command_server)
    assert command_server.start_calls == 0


@pytest.mark.asyncio
async def test_settlement_order_is_exact_and_proof_and_start_are_one_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_recovery_fakes(monkeypatch, events)
    authority = _authority(events)
    command_server = _CommandServer()

    proof = await authority.settle()

    assert events == [
        "writer.initialize",
        "operator_log.reconcile",
        "alarm_ack.settle",
    ]
    assert type(proof) is engine._CommandIngressRecoveryProof
    assert authority.proof is proof
    assert proof == engine._CommandIngressRecoveryProof(
        engine_instance_id=_ENGINE_INSTANCE_ID,
        operator_log_initialized=True,
        operator_log_reconciled=True,
        alarm_ack_dispositions=(),
    )

    with pytest.raises(RuntimeError, match="recovery settlement is one-use"):
        await authority.settle()

    await authority.start(command_server)
    assert command_server.start_calls == 1
    with pytest.raises(RuntimeError, match="command ingress start is one-use"):
        await authority.start(command_server)
    assert command_server.start_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail_at", "expected_events", "message"),
    [
        ("writer", ["writer.initialize"], "writer initialization failed"),
        (
            "operator_log",
            ["writer.initialize", "operator_log.reconcile"],
            "operator-log recovery failed",
        ),
        (
            "alarm_ack",
            ["writer.initialize", "operator_log.reconcile", "alarm_ack.settle"],
            "alarm ACK recovery failed",
        ),
    ],
)
async def test_every_settlement_failure_keeps_rep_closed_and_cannot_be_retried(
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
    expected_events: list[str],
    message: str,
) -> None:
    events: list[str] = []
    _install_recovery_fakes(monkeypatch, events, fail_at=fail_at)
    authority = _authority(events, writer_fails=fail_at == "writer")
    command_server = _CommandServer()

    with pytest.raises(RuntimeError, match=message):
        await authority.settle()

    assert events == expected_events
    assert authority.proof is None
    with pytest.raises(RuntimeError, match="recovery proof is unavailable"):
        await authority.start(command_server)
    assert command_server.start_calls == 0
    with pytest.raises(RuntimeError, match="recovery settlement is one-use"):
        await authority.settle()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_engine_instance_id", [_ENGINE_INSTANCE_ID, "b" * 32])
async def test_proof_from_another_authority_cannot_authorize_rep(
    monkeypatch: pytest.MonkeyPatch,
    foreign_engine_instance_id: str,
) -> None:
    events: list[str] = []
    _install_recovery_fakes(monkeypatch, events)
    source = _authority(events)
    foreign = _authority([], engine_instance_id=foreign_engine_instance_id)
    command_server = _CommandServer()

    proof = await source.settle()
    foreign._proof = proof

    with pytest.raises(RuntimeError, match="recovery proof is unavailable"):
        await foreign.start(command_server)

    assert command_server.start_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proof",
    [
        object(),
        engine._CommandIngressRecoveryProof(
            engine_instance_id=_ENGINE_INSTANCE_ID,
            operator_log_initialized=False,
            operator_log_reconciled=True,
            alarm_ack_dispositions=(),
        ),
        engine._CommandIngressRecoveryProof(
            engine_instance_id=_ENGINE_INSTANCE_ID,
            operator_log_initialized=True,
            operator_log_reconciled=False,
            alarm_ack_dispositions=(),
        ),
        engine._CommandIngressRecoveryProof(
            engine_instance_id=_ENGINE_INSTANCE_ID,
            operator_log_initialized=True,
            operator_log_reconciled=True,
            alarm_ack_dispositions=[],
        ),
        engine._CommandIngressRecoveryProof(
            engine_instance_id=_ENGINE_INSTANCE_ID,
            operator_log_initialized=True,
            operator_log_reconciled=True,
            alarm_ack_dispositions=(),
        ),
        engine._CommandIngressRecoveryProof(
            engine_instance_id=_ENGINE_INSTANCE_ID,
            operator_log_initialized=True,
            operator_log_reconciled=True,
            alarm_ack_dispositions=(object(),),
        ),
    ],
    ids=[
        "foreign-type",
        "writer-unsettled",
        "operator-log-unsettled",
        "mutable-dispositions",
        "fully-forged",
        "invalid-disposition-member",
    ],
)
async def test_forged_or_incomplete_proof_cannot_authorize_rep(proof: Any) -> None:
    authority = _authority([])
    command_server = _CommandServer()
    authority._proof = proof

    with pytest.raises(RuntimeError, match="recovery proof is unavailable"):
        await authority.start(command_server)

    assert command_server.start_calls == 0


def _call_signature(call: ast.Call) -> tuple[str, str] | None:
    if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
        return None
    return call.func.value.id, call.func.attr


def _calls_matching(
    function: ast.AsyncFunctionDef,
    predicate: Callable[[ast.Call], bool],
) -> list[ast.Call]:
    return [node for node in ast.walk(function) if isinstance(node, ast.Call) and predicate(node)]


def _first_positional_call(call: ast.Call) -> ast.Call | None:
    if not call.args or not isinstance(call.args[0], ast.Call):
        return None
    return call.args[0]


def _direct_awaited_call(statement: ast.stmt) -> ast.Call | None:
    if (
        not isinstance(statement, ast.Expr)
        or not isinstance(statement.value, ast.Await)
        or not isinstance(statement.value.value, ast.Call)
    ):
        return None
    return statement.value.value


def test_run_engine_binds_recovery_authority_to_final_rep_acquisition() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(engine._run_engine)))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef))

    constructors = [
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "command_ingress_recovery"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_CommandIngressRecoveryAuthority"
    ]
    direct_calls = [call for statement in function.body if (call := _direct_awaited_call(statement)) is not None]
    settlements = [
        call
        for call in direct_calls
        if (
            _call_signature(call) == ("startup", "guard")
            and (
                (inner := _first_positional_call(call)) is not None
                and _call_signature(inner) == ("command_ingress_recovery", "settle")
                and not inner.args
                and not inner.keywords
            )
        )
    ]
    starts = [
        call
        for call in direct_calls
        if (
            _call_signature(call) == ("startup", "acquire")
            and (
                (inner := _first_positional_call(call)) is not None
                and _call_signature(inner) == ("command_ingress_recovery", "start")
                and len(inner.args) == 1
                and isinstance(inner.args[0], ast.Name)
                and inner.args[0].id == "command_ingress"
                and not inner.keywords
            )
        )
    ]
    direct_rep_starts = _calls_matching(
        function,
        lambda call: _call_signature(call) == ("command_ingress", "start"),
    )

    assert len(constructors) == 1
    assert len(settlements) == 1
    assert len(starts) == 1
    assert direct_rep_starts == []
    assert (
        function.body.index(constructors[0])
        < next(
            index for index, statement in enumerate(function.body) if _direct_awaited_call(statement) is settlements[0]
        )
        < next(index for index, statement in enumerate(function.body) if _direct_awaited_call(statement) is starts[0])
    )

    all_settlements = _calls_matching(
        function,
        lambda call: (
            _call_signature(call) == ("startup", "guard")
            and (
                (inner := _first_positional_call(call)) is not None
                and _call_signature(inner) == ("command_ingress_recovery", "settle")
            )
        ),
    )
    all_starts = _calls_matching(
        function,
        lambda call: (
            _call_signature(call) == ("startup", "acquire")
            and (
                (inner := _first_positional_call(call)) is not None
                and _call_signature(inner) == ("command_ingress_recovery", "start")
            )
        ),
    )
    assert all_settlements == settlements
    assert all_starts == starts

    start_labels = [
        keyword.value.value
        for keyword in starts[0].keywords
        if keyword.arg == "label" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
    ]
    assert start_labels == ["command_ingress"]

    acquisition_lines = [
        node.lineno for node in _calls_matching(function, lambda call: _call_signature(call) == ("startup", "acquire"))
    ]
    assert starts[0].lineno == max(acquisition_lines)
