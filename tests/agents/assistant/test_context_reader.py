"""Observational assistant context projection contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from cryodaq.agents.assistant.shared.context_reader import (
    AssistantContextProtocolError,
    EngineContextReader,
)


class _Client:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def call(self, command: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(command)
        return self.reply


async def test_operator_log_read_uses_explicit_all_scope_and_typed_entries() -> None:
    client = _Client(
        {
            "ok": True,
            "entries": [
                {
                    "id": 17,
                    "timestamp": "2026-07-21T00:00:00+00:00",
                    "experiment_id": None,
                    "author": "operator",
                    "source": "gui",
                    "message": "stable",
                    "tags": ["alarm"],
                }
            ],
            "scope_receipt": {
                "schema": "operator_log_read_scope_v1",
                "log_scope": "all",
                "experiment_id": None,
            },
        }
    )
    reader = EngineContextReader(client)  # type: ignore[arg-type]

    entries = await reader.get_operator_log(
        start_time=datetime(2026, 7, 20, tzinfo=UTC),
        end_time=datetime(2026, 7, 21, tzinfo=UTC),
        limit=50,
    )

    assert entries[0].id == 17
    assert entries[0].tags == ("alarm",)
    assert client.calls == [
        {
            "cmd": "log_get",
            "log_scope": "all",
            "start_time": "2026-07-20T00:00:00+00:00",
            "end_time": "2026-07-21T00:00:00+00:00",
            "limit": 50,
        }
    ]


async def test_operator_log_read_passes_the_experiment_scope_to_the_engine() -> None:
    """Scoping is a QUERY the reader sends, not a claim it audits in the reply."""
    client = _Client(
        {
            "ok": True,
            "entries": [],
            "scope_receipt": {
                "schema": "operator_log_read_scope_v1",
                "log_scope": "experiment",
                "experiment_id": "exp-1",
            },
        }
    )

    assert (
        await EngineContextReader(client).get_operator_log(  # type: ignore[arg-type]
            experiment_id="exp-1"
        )
        == []
    )
    assert client.calls[0]["experiment_id"] == "exp-1"


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": False},
        {"ok": True, "entries": [{"id": True}]},
    ],
)
async def test_operator_log_malformed_projection_fails_closed(reply: dict[str, Any]) -> None:
    with pytest.raises(AssistantContextProtocolError):
        await EngineContextReader(_Client(reply)).get_operator_log()  # type: ignore[arg-type]


async def test_history_read_is_bounded_and_converts_exact_pairs() -> None:
    client = _Client(
        {
            "ok": True,
            "data": {"T11": [[1, 2.5], [2.0, 2.4]]},
        }
    )
    reader = EngineContextReader(client)  # type: ignore[arg-type]

    result = await reader.read_readings_history(
        channels=["T11"],
        from_ts=1.0,
        to_ts=2.0,
        limit_per_channel=20,
    )

    assert result == {"T11": [(1.0, 2.5), (2.0, 2.4)]}
    assert client.calls == [
        {
            "cmd": "readings_history",
            "channels": ["T11"],
            "from_ts": 1.0,
            "to_ts": 2.0,
            "limit_per_channel": 20,
        }
    ]


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": False},
        {"ok": True, "data": []},
        {"ok": True, "data": {"T11": [[1.0, float("nan")]]}},
        {"ok": True, "data": {"unexpected": [[1.0, 2.0]]}},
        {"ok": True, "data": {"T11": [[1.0, 2.0, 3.0]]}},
    ],
)
async def test_history_malformed_projection_fails_closed(reply: dict[str, Any]) -> None:
    reader = EngineContextReader(_Client(reply))  # type: ignore[arg-type]
    with pytest.raises(AssistantContextProtocolError):
        await reader.read_readings_history(channels=["T11"], limit_per_channel=20)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channels": []},
        {"channels": ["T11", "T11"]},
        {"channels": [""]},
        {"from_ts": float("inf")},
        {"limit_per_channel": 0},
        {"limit_per_channel": 501},
    ],
)
async def test_history_hostile_request_rejected_before_engine_call(kwargs: dict[str, Any]) -> None:
    client = _Client({"ok": True, "data": {}})
    with pytest.raises((ValueError, AssistantContextProtocolError)):
        await EngineContextReader(client).read_readings_history(**kwargs)  # type: ignore[arg-type]
    assert client.calls == []


async def test_history_is_returned_from_the_reply_the_engine_actually_sends() -> None:
    """The regression that would have caught the original defect.

    The engine sends `readings_history` with no receipt of any kind — the name
    `history_receipt` existed in exactly one place in the source tree, the line
    that demanded it. Every fake in these tests used to hand itself that
    receipt, so the suite was green while the real reader refused every real
    reply. A fake must answer the way the engine answers.

    Each point carries its own timestamp, which is what freshness is actually
    made of: the agent knows the current time and can subtract.
    """
    client = _Client({"ok": True, "data": {"T11": [[1000.0, 2.5], [1030.0, 2.4]]}})

    result = await EngineContextReader(client).read_readings_history(  # type: ignore[arg-type]
        channels=["T11"],
        from_ts=1000.0,
        limit_per_channel=20,
    )

    assert result == {"T11": [(1000.0, 2.5), (1030.0, 2.4)]}


async def test_the_operator_log_is_returned_from_a_reply_with_no_receipt() -> None:
    """Same contract on the other read: the engine sends three fields, not eleven."""
    client = _Client(
        {
            "ok": True,
            "entries": [],
            "scope_receipt": {
                "schema": "operator_log_read_scope_v1",
                "log_scope": "all",
                "experiment_id": None,
            },
        }
    )

    assert await EngineContextReader(client).get_operator_log() == []  # type: ignore[arg-type]
