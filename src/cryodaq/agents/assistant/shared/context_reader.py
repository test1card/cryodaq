"""Bounded observational context reads through the engine's query authority.

NO CONTEXT RECEIPTS. Removed 2026-09-07 by the operator's decision, and the
reasoning is worth keeping because the machinery was persuasive.

Every read here used to demand an eleven-field receipt — schema, scope,
experiment id, engine and experiment incarnation, revision, order, query
bounds, receive time, freshness — and refuse the data without it. The engine
never emitted one. `history_receipt` appeared exactly once in the whole source
tree: in the line that asked for it. Zero producers. So both context paths had
failed since the day they were written, the assistant answered "I have no live
readings" while the stand was fine, and the hourly report went out empty 26
times on 2026-09-07 alone. The tests were green because the fake client in them
handed itself the receipt the real engine does not write.

The receipts were meant to prove freshness and identity. But a reading already
carries its own timestamp, and the agent knows what time it is — the age is a
subtraction, not a protocol. And the threat the identity fields defended
against, someone attaching to this machine and injecting false temperatures,
is not a threat this stand has. What remained was ceremony that turned a
working instrument into a silent one.

What is still checked is what parsing actually requires: that the engine said
ok, that the shape is what it claims, and that sizes stay inside their caps.
Those are not gates on the operator's data; they are how you read a reply
without crashing.

This is the settled philosophy applied to the assistant: CryoDAQ INFORMS, the
operator DECIDES. Software that withholds a reading because it lacks a
signature has decided something.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient
from cryodaq.core.operator_log import OperatorLogEntry

_MAX_LOG_ENTRIES = 100
_MAX_HISTORY_CHANNELS = 64
_MAX_HISTORY_POINTS_PER_CHANNEL = 500


class AssistantContextProtocolError(RuntimeError):
    """The engine context projection was unavailable or malformed."""


def _bounded_positive_int(value: object, *, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _finite_number(value: object, *, name: str) -> float:
    if type(value) not in (int, float):
        raise AssistantContextProtocolError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AssistantContextProtocolError(f"{name} must be finite")
    return result


def _parse_log_entry(payload: object) -> OperatorLogEntry:
    if not isinstance(payload, dict):
        raise AssistantContextProtocolError("operator-log entry must be an object")
    entry_id = payload.get("id")
    if type(entry_id) is not int or entry_id < 0:
        raise AssistantContextProtocolError("operator-log id must be a non-negative integer")
    timestamp_raw = payload.get("timestamp")
    if type(timestamp_raw) is not str:
        raise AssistantContextProtocolError("operator-log timestamp must be a string")
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError as exc:
        raise AssistantContextProtocolError("operator-log timestamp is invalid") from exc
    if timestamp.tzinfo is None:
        raise AssistantContextProtocolError("operator-log timestamp must include a timezone")
    experiment_id = payload.get("experiment_id")
    if experiment_id is not None and type(experiment_id) is not str:
        raise AssistantContextProtocolError("operator-log experiment_id must be a string or null")
    author = payload.get("author")
    source = payload.get("source")
    message = payload.get("message")
    if any(type(value) is not str for value in (author, source, message)):
        raise AssistantContextProtocolError("operator-log text fields must be strings")
    tags_raw = payload.get("tags")
    if not isinstance(tags_raw, list) or any(type(tag) is not str for tag in tags_raw):
        raise AssistantContextProtocolError("operator-log tags must be a string list")
    return OperatorLogEntry(
        id=entry_id,
        timestamp=timestamp.astimezone(UTC),
        experiment_id=experiment_id,
        author=author,
        source=source,
        message=message,
        tags=tuple(tags_raw),
    )


class EngineContextReader:
    """Expose only the two bounded read methods used by ``ContextBuilder``."""

    def __init__(self, client: EngineQueryClient) -> None:
        self._client = client

    async def get_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
    ) -> list[OperatorLogEntry]:
        bounded_limit = _bounded_positive_int(limit, name="limit", maximum=_MAX_LOG_ENTRIES)
        if experiment_id is not None and (type(experiment_id) is not str or not experiment_id):
            raise ValueError("experiment_id must be a non-empty string or null")
        for name, value in (("start_time", start_time), ("end_time", end_time)):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ValueError(f"{name} must be a timezone-aware datetime or null")
        reply = await self._client.call(
            {
                "cmd": "log_get",
                "log_scope": "experiment" if experiment_id is not None else "all",
                **({"experiment_id": experiment_id} if experiment_id is not None else {}),
                **({"start_time": start_time.isoformat()} if start_time is not None else {}),
                **({"end_time": end_time.isoformat()} if end_time is not None else {}),
                "limit": bounded_limit,
            }
        )
        if reply.get("ok") is not True:
            raise AssistantContextProtocolError("operator-log projection unavailable")
        entries = reply.get("entries")
        if not isinstance(entries, list) or len(entries) > bounded_limit:
            raise AssistantContextProtocolError("operator-log entries are malformed or oversized")
        return [_parse_log_entry(entry) for entry in entries]

    async def read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 100,
    ) -> dict[str, list[tuple[float, float]]]:
        limit = _bounded_positive_int(
            limit_per_channel,
            name="limit_per_channel",
            maximum=_MAX_HISTORY_POINTS_PER_CHANNEL,
        )
        normalized_channels: list[str] | None = None
        if channels is not None:
            if (
                not isinstance(channels, list)
                or not 1 <= len(channels) <= _MAX_HISTORY_CHANNELS
                or any(type(channel) is not str or not channel for channel in channels)
                or len(set(channels)) != len(channels)
            ):
                raise ValueError("channels must be 1..64 unique non-empty strings or null")
            normalized_channels = list(channels)
        from_value = None if from_ts is None else _finite_number(from_ts, name="from_ts")
        to_value = None if to_ts is None else _finite_number(to_ts, name="to_ts")
        reply = await self._client.call(
            {
                "cmd": "readings_history",
                **({"channels": normalized_channels} if normalized_channels is not None else {}),
                **({"from_ts": from_value} if from_value is not None else {}),
                **({"to_ts": to_value} if to_value is not None else {}),
                "limit_per_channel": limit,
            }
        )
        if reply.get("ok") is not True:
            raise AssistantContextProtocolError("readings-history projection unavailable")
        data = reply.get("data")
        if not isinstance(data, dict) or len(data) > _MAX_HISTORY_CHANNELS:
            raise AssistantContextProtocolError("readings-history projection is malformed or oversized")
        requested = None if normalized_channels is None else set(normalized_channels)
        result: dict[str, list[tuple[float, float]]] = {}
        for channel, points in data.items():
            if type(channel) is not str or not channel or (requested is not None and channel not in requested):
                raise AssistantContextProtocolError("readings-history returned an invalid channel")
            if not isinstance(points, list) or len(points) > limit:
                raise AssistantContextProtocolError("readings-history channel is malformed or oversized")
            parsed: list[tuple[float, float]] = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise AssistantContextProtocolError("readings-history point must be a pair")
                parsed.append(
                    (
                        _finite_number(point[0], name="reading timestamp"),
                        _finite_number(point[1], name="reading value"),
                    )
                )
            result[channel] = parsed
        return result
