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


def test_structured_delivery_state_present_alone_short_circuits_prose():
    """If any structured settlement key is present at all, prose matching must
    not run. Here delivery_state=not_dispatched is present with no
    commit_state, and the prose contains a marker ('timed out'). A second
    synthetic shape proving the rule is keyed on key *presence*, not on the
    not_committed/not_dispatched pair specifically."""

    result = {
        "ok": False,
        "error": "Send timed out before the frame left the client",
        "delivery_state": "not_dispatched",
    }
    assert result_outcome_unknown(result) is False


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


def _literal_settlement_values(value: ast.expr) -> set[str]:
    if isinstance(value, ast.Constant) and type(value.value) is str:
        return {value.value}
    if isinstance(value, ast.IfExp):
        return _literal_settlement_values(value.body) | _literal_settlement_values(value.orelse)
    return set()


def _emitted_settlement_values() -> dict[str, set[str]]:
    """Collect statically knowable settlement values from every source reply."""

    emitted: dict[str, set[str]] = defaultdict(set)
    root = Path(__file__).resolve().parents[3] / "src"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value in {"delivery_state", "commit_state"}):
                    continue
                values = _literal_settlement_values(value)
                assert values, f"{path}:{value.lineno} emits a nonliteral {key.value}"
                emitted[key.value].update(values)
    return emitted


def test_all_emitted_settlement_values_are_known_to_command_outcome_classifier():
    """Reject a new emitter value until the shared classifier vocabulary names it."""

    contract = importlib.import_module("cryodaq.core.command_reply_contract")
    vocabulary = {
        "delivery_state": contract.COMMAND_REPLY_DELIVERY_STATES,
        "commit_state": contract.COMMAND_REPLY_COMMIT_STATES,
    }
    for field, values in _emitted_settlement_values().items():
        assert values <= vocabulary[field], f"unrecognised {field}: {sorted(values - vocabulary[field])}"
