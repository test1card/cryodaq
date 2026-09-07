"""`cooldown_eta_get` was dead for hours and nothing could complain.

The reply encoder uses `json.dumps(allow_nan=False)` — correct, since NaN is not
JSON — and ONE non-finite float anywhere fails the WHOLE reply. On a warm,
static stand the cooldown fit has nothing to extrapolate from and returns
infinity or NaN for the remaining time, so every call to the command failed to
serialise from at least 14:02 on 2026-09-07. The log said only
`exception=ValueError`, and nothing that used the command was able to report
that it never got an answer.

The fix is not to make the encoder tolerant. It is that a value which cannot be
expressed must cost its own field, not the whole prediction.
"""

from __future__ import annotations

import json
import math

from cryodaq.analytics.cooldown_service import _finite_or_none


def test_the_things_json_refuses_become_none() -> None:
    assert _finite_or_none(float("inf")) is None
    assert _finite_or_none(float("-inf")) is None
    assert _finite_or_none(float("nan")) is None


def test_ordinary_numbers_pass_through() -> None:
    assert _finite_or_none(3.5) == 3.5
    assert _finite_or_none(0.0) == 0.0
    assert _finite_or_none(-2) == -2.0


def test_something_that_is_not_a_number_is_absent_rather_than_raising() -> None:
    """It runs while building a reply; raising here would cost the reply too."""
    assert _finite_or_none(None) is None
    assert _finite_or_none("не число") is None
    assert _finite_or_none(object()) is None


def test_a_prediction_built_from_a_warm_stand_serialises() -> None:
    """The end of the actual failure: the reply must encode."""
    metadata = {
        "t_remaining_hours": _finite_or_none(float("inf")),
        "t_remaining_ci68": (_finite_or_none(float("nan")), _finite_or_none(float("inf"))),
        "progress": _finite_or_none(0.0),
        "phase": "WARM",
        "n_references": 0,
        "cooldown_active": False,
        "cooldown_start_ts": 0,
        "T_cold": _finite_or_none(294.5),
        "T_warm": _finite_or_none(296.5),
    }

    encoded = json.dumps({"ok": True, "prediction": metadata}, allow_nan=False)

    assert '"t_remaining_hours": null' in encoded
    assert '"phase": "WARM"' in encoded, "the fields that DO have values must survive"
    assert '"T_cold": 294.5' in encoded


def test_without_the_guard_the_whole_reply_dies() -> None:
    """The property under test, stated as the failure it prevents."""
    metadata = {"t_remaining_hours": math.inf, "phase": "WARM"}
    try:
        json.dumps({"ok": True, "prediction": metadata}, allow_nan=False)
    except ValueError:
        return
    raise AssertionError("json.dumps(allow_nan=False) accepted an infinity")


async def test_a_null_estimate_is_an_absence_with_a_reason_not_a_malformed_reply() -> None:
    """Telling the operator the reply was malformed sends them hunting a fault
    that is not there. The estimate is simply not computable on a warm stand."""
    from unittest.mock import AsyncMock

    from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter

    client = AsyncMock()
    client.call = AsyncMock(
        return_value={
            "ok": True,
            "prediction": {
                "t_remaining_hours": None,
                "t_remaining_ci68": (None, None),
                "progress": None,
                "phase": "WARM",
                "n_references": 0,
                "cooldown_active": False,
                "T_cold": 294.5,
                "T_warm": 296.5,
            },
        }
    )

    eta = await CooldownAdapter(client).eta()

    assert eta is not None
    assert eta.available is False
    assert eta.stale is True
    assert eta.reason, "the availability contract requires a non-empty reason"
    assert "malformed" not in eta.reason.lower()
    assert "не рассчитана" in eta.reason


async def test_a_real_estimate_still_parses() -> None:
    from unittest.mock import AsyncMock

    from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter

    client = AsyncMock()
    client.call = AsyncMock(
        return_value={
            "ok": True,
            "prediction": {
                "t_remaining_hours": 4.5,
                "t_remaining_ci68": (4.0, 5.0),
                "progress": 0.4,
                "phase": "COOLING",
                "n_references": 3,
                "cooldown_active": True,
                "T_cold": 80.0,
                "T_warm": 200.0,
            },
        }
    )

    eta = await CooldownAdapter(client).eta()

    assert eta is not None
    assert eta.available is True
    assert eta.t_remaining_hours == 4.5


def test_every_numeric_field_of_the_prediction_is_actually_sanitised() -> None:
    """The helper is worthless if the metadata does not use it.

    Written after a negative control failed to fail for the SECOND time tonight:
    reverting one field to `pred.t_remaining_hours` left every other test in this
    file green, because they exercise `_finite_or_none` directly. The defect was
    never in the helper — it was in the dict that has to call it.

    Parsed rather than grepped, so a field added later without the wrapper is
    caught instead of quietly slipping past a substring check.
    """
    import ast
    import inspect

    from cryodaq.analytics import cooldown_service

    source = inspect.getsource(cooldown_service.CooldownService)
    tree = ast.parse("class _S:\n" + "\n".join("    " + line for line in source.splitlines()))

    numeric = {"t_remaining_hours", "progress", "T_cold", "T_warm"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "t_remaining_ci68" not in keys:
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or key.value not in numeric:
                continue
            seen.add(key.value)
            assert isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_finite_or_none", (
                f'"{key.value}" reaches the reply unsanitised; one infinity there '
                "kills the whole cooldown_eta_get reply"
            )
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "t_remaining_ci68":
                assert isinstance(value, ast.Tuple)
                for element in value.elts:
                    assert isinstance(element, ast.Call) and getattr(element.func, "id", "") == "_finite_or_none", (
                        "a confidence bound reaches the reply unsanitised"
                    )
    assert seen == numeric, f"the prediction metadata was not found intact: saw {seen}"
