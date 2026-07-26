"""Regression coverage for the shared command-outcome classifier.

``cryodaq.gui.shell.command_outcome.result_outcome_unknown`` is the canonical
entry classifier consulted by ``experiment_overlay.py`` and
``keithley_panel.py`` (see
``docs/design-system/patterns/command-outcome-unknown.md``). Its documented
contract is: structured settlement evidence decides outright, and error-prose
matching is a fallback only for reply shapes that carry none of the structured
keys at all.

These tests target the shared function directly rather than either delegate
surface, because the defect under test lives in the shared function and both
delegates are thin pass-throughs to it.
"""

from __future__ import annotations

import ast
import importlib
from collections import defaultdict
from pathlib import Path

import pytest

from cryodaq.gui.shell.command_outcome import result_outcome_unknown

# -- Structured evidence must decide outright (the defect) --------------------


def test_structured_not_committed_with_timeout_prose_is_resolved_refusal():
    """delivery_state=not_dispatched + commit_state=not_committed are truthful
    *resolved* refusals. The reply also carries timeout-shaped prose
    ('Admission timed out before dispatch'), which under the old code reached
    the prose fallback and returned True -- classifying a command that never
    left the client as outcome-unknown. That latches the Keithley channel's
    Start/Stop until two fresh observations arrive and tells the operator not
    to retry a command that never happened.

    This is a SYNTHETIC reply shape. A full audit of every
    not_dispatched/not_committed emitter (zmq_client.py, engine.py,
    core/zmq_bridge.py, core/zmq_subprocess.py, web/server.py,
    assistant_main.py) found NO current transport path that combines those
    structured values with timeout prose. This test does NOT reproduce a live
    transport failure; it pins the classifier's contract so a future emitter
    that does combine them is classified correctly. Expected to FAIL (return
    True) before the fix and PASS (return False) after."""

    result = {
        "ok": False,
        "error_code": "command_admission_timeout",
        "error": "Admission timed out before dispatch",
        "delivery_state": "not_dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
    }
    assert result_outcome_unknown(result) is False


def test_structured_delivery_state_without_terminal_commit_is_unknown():
    """A delivery state alone does not prove a mutation reached a terminal state."""

    result = {
        "ok": False,
        "error": "Send timed out before the frame left the client",
        "delivery_state": "not_dispatched",
    }
    assert result_outcome_unknown(result) is True


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False, "delivery_state": "dispatched"},
        {"ok": False, "delivery_state": "dispatched", "commit_state": "not_applicable"},
        {"ok": False, "delivery_state": "intent_persisted"},
        {"ok": False, "delivery_state": "not_confirmed"},
    ],
    ids=("dispatched-alone", "dispatched-read-commit", "assistant-audit", "read-failure"),
)
def test_nonterminal_or_nonmutation_settlement_values_are_unknown(result: dict[str, object]):
    """Only a coherent mutation settlement tuple can release the safety latch."""

    assert result_outcome_unknown(result) is True


def test_quarantined_refusal_plain_prose_is_not_unknown():
    """Probe row 2: a quarantined refusal carried as plain prose with no
    structured settlement keys. Prose names none of the six markers, so the
    fallback correctly returns False. Behaviour is identical before and after
    the fix; this pins the no-regression contract for plain-prose refusals."""

    result = {
        "ok": False,
        "error_code": "command_authority_quarantined",
        "error": "Mutation is quarantined pending a prior settlement.",
    }
    assert result_outcome_unknown(result) is False


def test_legacy_visa_timeout_no_structured_keys_is_unknown():
    """Probe row 3: a legacy handler-local driver error returned as a raw dict
    with no structured settlement vocabulary at all. The instrument may have
    executed the command, so this MUST classify as unknown via the prose
    fallback. Deleting or gating the fallback would regress this path. Correct
    before and after the fix; MUST KEEP."""

    result = {"ok": False, "error": "VISA read timed out"}
    assert result_outcome_unknown(result) is True


def test_prose_fallback_fires_for_no_structured_key_reply():
    """Explicit proof that the prose fallback still fires for a reply carrying
    none of _handler_timeout / outcome_unknown / commit_state / delivery_state.
    Uses the Russian marker to also cover the i18n fallback path. Correct
    before and after the fix."""

    result = {"ok": False, "error": "Инструмент исход неизвестен."}
    assert result_outcome_unknown(result) is True


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False, "error": "VISA read timed out", "commit_state": "bogus"},
        {"ok": False, "error": "VISA read timed out", "outcome_unknown": "yes"},
        {"ok": False, "error": "VISA read timed out", "_handler_timeout": None},
        {"ok": False, "error": "VISA read timed out", "delivery_state": "typo"},
    ],
    ids=("bogus-commit", "non-boolean-outcome", "none-handler-timeout", "bogus-delivery"),
)
def test_malformed_structured_settlement_evidence_is_unknown(result: dict[str, object]):
    """Malformed settlement evidence cannot suppress the safety latch."""

    assert result_outcome_unknown(result) is True


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"ok": False, "error": "VISA read timed out"}, True),
        ({"ok": False, "commit_state": "unknown"}, True),
        ({"ok": False, "commit_state": "not_committed", "error": "quarantined"}, False),
        (
            {
                "ok": False,
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "error": "admission timed out",
            },
            False,
        ),
    ],
    ids=("legacy-prose", "unknown-commit", "not-committed", "not-dispatched-and-not-committed"),
)
def test_required_command_outcome_regressions(result: dict[str, object], expected: bool):
    """Pin the required legacy, unknown, and provably-unsent reply shapes."""

    assert result_outcome_unknown(result) is expected


def _literal_settlement_values(value: ast.expr, bindings: dict[str, set[str]]) -> set[str]:
    if isinstance(value, ast.Constant) and type(value.value) is str:
        return {value.value}
    if isinstance(value, ast.Name):
        return bindings.get(value.id, set())
    if isinstance(value, ast.IfExp):
        return _literal_settlement_values(value.body, bindings) | _literal_settlement_values(value.orelse, bindings)
    return set()


def _literal_settlement_key(value: ast.expr, bindings: dict[str, set[str]]) -> str | None:
    values = _literal_settlement_values(value, bindings)
    if len(values) == 1:
        return next(iter(values))
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        left = _literal_settlement_key(value.left, bindings)
        right = _literal_settlement_key(value.right, bindings)
        return None if left is None or right is None else left + right
    return None


def _settlement_mapping(node: ast.expr, bindings: dict[str, set[str]]) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {}
    if isinstance(node, ast.Dict):
        pairs = zip(node.keys, node.values)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        pairs = ((ast.Constant(keyword.arg), keyword.value) for keyword in node.keywords if keyword.arg is not None)
    else:
        return fields
    for key, value in pairs:
        if key is None:
            continue
        field = _literal_settlement_key(key, bindings)
        if field not in {"delivery_state", "commit_state"}:
            continue
        values = _literal_settlement_values(value, bindings)
        assert values, f"{value.lineno} emits a nonliteral {field}"
        fields[field] = values
    return fields


def _emitted_settlement_values() -> dict[str, set[str]]:
    """Collect supported literal settlement spellings from source construction forms."""

    emitted: dict[str, set[str]] = defaultdict(set)
    root = Path(__file__).resolve().parents[3] / "src"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bindings: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                values = _literal_settlement_values(node.value, bindings)
                if values:
                    bindings[node.targets[0].id] = values
        for node in ast.walk(tree):
            fields = _settlement_mapping(node, bindings)
            if fields:
                for field, values in fields.items():
                    emitted[field].update(values)
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
                field = _literal_settlement_key(node.targets[0].slice, bindings)
                if field in {"delivery_state", "commit_state"}:
                    values = _literal_settlement_values(node.value, bindings)
                    assert values, f"{path}:{node.value.lineno} emits a nonliteral {field}"
                    emitted[field].update(values)
                continue
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update"):
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"delivery_state", "commit_state"}:
                    continue
                values = _literal_settlement_values(keyword.value, bindings)
                assert values, f"{path}:{keyword.value.lineno} emits a nonliteral {keyword.arg}"
                emitted[keyword.arg].update(values)
    return emitted


def test_all_emitted_settlement_values_have_a_separate_domain_vocabulary():
    """Reject a new state spelling until its command/read/audit domain is named.

    This lexical source scan recognizes direct dicts, ``dict(...)`` calls,
    subscript assignment, ``update()``, and joined literal keys.
    It cannot prove that a reply reaches a mutation command, trace a value built
    across functions, or infer a runtime-computed key; tuple coherence is
    enforced separately by the classifier's exhaustive input tests.
    """

    contract = importlib.import_module("cryodaq.core.command_reply_contract")
    vocabulary = {
        "delivery_state": (
            contract.MUTATION_COMMAND_SETTLED_REPLY_TUPLES
            | {(state, None) for state in contract.MUTATION_COMMAND_DELIVERY_STATES}
            | {(state, None) for state in contract.READ_COMMAND_DELIVERY_STATES}
            | {(state, None) for state in contract.ASSISTANT_AUDIT_DELIVERY_STATES}
        ),
        "commit_state": (
            contract.MUTATION_COMMAND_SETTLED_REPLY_TUPLES
            | {(None, state) for state in contract.MUTATION_COMMAND_COMMIT_STATES}
            | {(None, state) for state in contract.READ_COMMAND_COMMIT_STATES}
        ),
    }
    for field, values in _emitted_settlement_values().items():
        known = {pair[0] if field == "delivery_state" else pair[1] for pair in vocabulary[field]}
        assert values <= known, f"unrecognised {field}: {sorted(values - known)}"


def test_drift_guard_recognizes_common_reply_construction_forms():
    """The lexical guard sees dict(), assignment, update(), and joined keys.

    It deliberately does not claim interprocedural or runtime-key coverage;
    mutation settlement itself is fail-closed unless the runtime tuple is in
    ``MUTATION_COMMAND_SETTLED_REPLY_TUPLES``.
    """

    source = """
state = "dispatched"
from_dict = dict(delivery_state=state, commit_state="not_applicable")
from_assignment = {}
from_assignment["delivery_" + "state"] = state
from_assignment.update(commit_state="not_applicable")
"""
    tree = ast.parse(source)
    bindings = {"state": {"dispatched"}}
    mappings: list[dict[str, set[str]]] = []
    reply = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            reply = _settlement_mapping(node.value, bindings)
            mappings.append(reply)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            mapping = _settlement_mapping(node.value, bindings)
            if mapping:
                mappings.append(mapping)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript):
            target = node.targets[0]
            field = _literal_settlement_key(target.slice, bindings)
            if field in {"delivery_state", "commit_state"}:
                reply[field] = _literal_settlement_values(node.value, bindings)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "update":
                for keyword in call.keywords:
                    if keyword.arg in {"delivery_state", "commit_state"}:
                        reply[keyword.arg] = _literal_settlement_values(keyword.value, bindings)
    mappings.append(reply)
    assert {("dispatched", "not_applicable")} <= {
        (next(iter(mapping.get("delivery_state", {None}))), next(iter(mapping.get("commit_state", {None}))))
        for mapping in mappings
    }
