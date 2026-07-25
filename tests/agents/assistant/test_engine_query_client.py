"""Capability-boundary tests for the assistant's read-only engine client."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from cryodaq.agents.assistant.shared import engine_client
from cryodaq.agents.assistant.shared.engine_client import (
    ENGINE_QUERY_ACTIONS,
    EngineQueryClient,
    EngineQueryRejectedError,
)

_REPO_ROOT = Path(__file__).parents[3]
_AGENTS_DIR = _REPO_ROOT / "src/cryodaq/agents"


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.connected_to: str | None = None
        self.closed = False
        self.options: list[tuple[int, int]] = []

    def setsockopt(self, option: int, value: int) -> None:
        self.options.append((option, value))

    def connect(self, address: str) -> None:
        self.connected_to = address

    async def send_string(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv_string(self) -> str:
        return '{"ok": true}'

    def close(self, *, linger: int) -> None:
        assert linger == 0
        self.closed = True


class _FakeContext:
    instance_calls = 0
    socket_calls = 0
    last_socket: _FakeSocket | None = None

    @classmethod
    def instance(cls) -> _FakeContext:
        cls.instance_calls += 1
        return cls()

    def socket(self, _socket_type: int) -> _FakeSocket:
        type(self).socket_calls += 1
        sock = _FakeSocket()
        type(self).last_socket = sock
        return sock


class _ForbiddenContext:
    @classmethod
    def instance(cls) -> None:
        raise AssertionError("ZeroMQ context created before command rejection")


def _annotation_names_engine_client(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(
        (isinstance(node, ast.Name) and node.id == "EngineQueryClient")
        or (isinstance(node, ast.Constant) and node.value == "EngineQueryClient")
        for node in ast.walk(annotation)
    )


def _is_engine_query_constructor(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == "EngineQueryClient"
    )


def _engine_query_owners(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Find local names and ``self`` attributes carrying EngineQueryClient."""

    local_names = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if _annotation_names_engine_client(argument.annotation)
    }
    self_attributes: set[str] = set()

    def add_target(target: ast.expr) -> bool:
        if isinstance(target, ast.Name):
            before = len(local_names)
            local_names.add(target.id)
            return len(local_names) != before
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            before = len(self_attributes)
            self_attributes.add(target.attr)
            return len(self_attributes) != before
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            carries_client = (
                isinstance(value, ast.Name) and value.id in local_names or _is_engine_query_constructor(value)
            )
            if carries_client:
                changed = any(add_target(target) for target in targets) or changed
    return local_names, self_attributes


def _literal_engine_query_actions() -> frozenset[str]:
    actions: set[str] = set()
    for path in sorted(_AGENTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        local_names, self_attributes = _engine_query_owners(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            is_query_owner = isinstance(owner, ast.Name) and owner.id in local_names
            is_query_owner = is_query_owner or (
                isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "self"
                and owner.attr in self_attributes
            )
            is_query_owner = is_query_owner or _is_engine_query_constructor(owner)
            if node.func.attr != "call":
                continue
            assert is_query_owner, (
                f"{path.name}:{node.lineno} .call() must use an explicitly tracked EngineQueryClient owner"
            )
            assert node.args and isinstance(node.args[0], ast.Dict), (
                f"{path.name}:{node.lineno} must use a literal query payload"
            )
            found_action = False
            for key, value in zip(node.args[0].keys, node.args[0].values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "cmd"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    actions.add(value.value)
                    found_action = True
            assert found_action, f"{path.name}:{node.lineno} must use a literal query action"
    return frozenset(actions)


def test_allowlist_exactly_matches_all_literal_assistant_queries() -> None:
    assert isinstance(ENGINE_QUERY_ACTIONS, frozenset)
    assert ENGINE_QUERY_ACTIONS == _literal_engine_query_actions()


def test_inline_engine_query_client_is_recognized_as_an_owner() -> None:
    tree = ast.parse('EngineQueryClient("tcp://example").call({"cmd": dynamic_action})')
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute))

    assert _is_engine_query_constructor(call.func.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", sorted(ENGINE_QUERY_ACTIONS))
async def test_allowlisted_adapter_query_preserves_payload(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    _FakeContext.instance_calls = 0
    _FakeContext.socket_calls = 0
    _FakeContext.last_socket = None
    monkeypatch.setattr(engine_client.zmq.asyncio, "Context", _FakeContext)
    payload: dict[str, Any] = {
        "cmd": action,
        "marker": {"text": "preserved", "limit": 17},
    }

    reply = await EngineQueryClient("tcp://127.0.0.1:5999").call(payload)

    assert reply == {"ok": True}
    assert _FakeContext.instance_calls == 1
    assert _FakeContext.socket_calls == 1
    sock = _FakeContext.last_socket
    assert sock is not None
    assert json.loads(sock.sent[0]) == payload
    assert sock.connected_to == "tcp://127.0.0.1:5999"
    assert sock.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="payload-none"),
        pytest.param([], id="payload-list"),
        pytest.param({}, id="missing"),
        pytest.param({"cmd": None}, id="none"),
        pytest.param({"cmd": 7}, id="non-string"),
        pytest.param({"cmd": ""}, id="empty"),
        pytest.param({"cmd": "unknown_query"}, id="unknown"),
        pytest.param({"cmd": "keithley_start"}, id="source-control"),
        pytest.param({"cmd": "safety_acknowledge"}, id="safety-ack"),
        pytest.param({"cmd": "alarm_acknowledge"}, id="alarm-v1-ack"),
        pytest.param({"cmd": "alarm_v2_ack"}, id="alarm-v2-ack"),
        pytest.param({"cmd": "log_entry"}, id="write"),
        pytest.param({"cmd": "experiment_create"}, id="experiment-create"),
        pytest.param({"cmd": "experiment_start"}, id="experiment-start"),
        pytest.param({"cmd": "experiment_finalize"}, id="experiment-finalize"),
        pytest.param({"cmd": "experiment_advance_phase"}, id="experiment-phase"),
        pytest.param({"cmd": "command"}, id="generic-command"),
    ],
)
async def test_invalid_or_mutating_action_rejected_before_zmq(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(engine_client.zmq.asyncio, "Context", _ForbiddenContext)

    with pytest.raises(EngineQueryRejectedError, match=r"engine query (?:action|payload)"):
        await EngineQueryClient().call(payload)  # type: ignore[arg-type]
