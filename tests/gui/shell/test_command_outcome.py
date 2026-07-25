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
