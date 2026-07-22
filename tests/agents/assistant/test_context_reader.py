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


def _receipt(
    *,
    scope: str,
    experiment_id: str | None,
    start: float | None = None,
    end: float | None = None,
    received_at: str | None = None,
    freshness_s: float = 3600.0,
    order: int = 1,
) -> dict[str, Any]:
    return {
        "schema": "assistant_context_receipt_v1",
        "log_scope": scope,
        "experiment_id": experiment_id,
        "engine_incarnation": "engine-1",
        "experiment_incarnation": "experiment-1",
        "revision": 3,
        "order": order,
        "query_start": start,
        "query_end": end,
        "received_at": received_at or datetime.now(UTC).isoformat(),
        "freshness_s": freshness_s,
    }


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
                **_receipt(
                    scope="all",
                    experiment_id=None,
                    start=datetime(2026, 7, 20, tzinfo=UTC).timestamp(),
                    end=datetime(2026, 7, 21, tzinfo=UTC).timestamp(),
                ),
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


async def test_operator_log_read_binds_experiment_scope_receipt() -> None:
    client = _Client(
        {
            "ok": True,
            "entries": [],
            "scope_receipt": {
                **_receipt(scope="experiment", experiment_id="exp-1"),
            },
        }
    )

    assert await EngineContextReader(client).get_operator_log(  # type: ignore[arg-type]
        experiment_id="exp-1"
    ) == []
    assert client.calls[0]["experiment_id"] == "exp-1"


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": False},
        {"ok": True, "entries": [], "scope_receipt": {}},
        {
            "ok": True,
            "entries": [{"id": True}],
            "scope_receipt": {
                "schema": "operator_log_read_scope_v1",
                "log_scope": "all",
                "experiment_id": None,
            },
        },
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
            "history_receipt": _receipt(scope="history", experiment_id=None, start=1.0, end=2.0),
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


async def test_history_receipt_binds_scope_order_and_freshness() -> None:
    client = _Client(
        {
            "ok": True,
            "data": {"T11": [[1.0, 2.0]]},
            "history_receipt": _receipt(
                scope="history",
                experiment_id=None,
                start=1.0,
                end=None,
                received_at="2020-01-01T00:00:00+00:00",
            ),
        }
    )
    with pytest.raises(AssistantContextProtocolError, match="stale"):
        await EngineContextReader(client).read_readings_history(
            channels=["T11"],
            from_ts=1.0,
            limit_per_channel=20,
        )
