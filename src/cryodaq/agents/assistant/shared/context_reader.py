"""Bounded observational context reads through the engine's query authority."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient
from cryodaq.core.operator_log import OperatorLogEntry

_MAX_LOG_ENTRIES = 100
_MAX_HISTORY_CHANNELS = 64
_MAX_HISTORY_POINTS_PER_CHANNEL = 500


class AssistantContextProtocolError(RuntimeError):
    """The engine context projection was unavailable or malformed."""


_CONTEXT_RECEIPT_SCHEMA = "assistant_context_receipt_v1"
_MAX_CONTEXT_FRESHNESS_S = 3600.0


def _validate_context_receipt(
    receipt: object,
    *,
    expected_scope: str,
    expected_experiment_id: str | None,
    query_start: float | None,
    query_end: float | None,
) -> dict[str, Any]:
    """Validate the identity and age fence carried by one projection."""
    if not isinstance(receipt, dict):
        raise AssistantContextProtocolError("context receipt is missing")
    required = {
        "schema",
        "log_scope",
        "experiment_id",
        "engine_incarnation",
        "experiment_incarnation",
        "revision",
        "order",
        "query_start",
        "query_end",
        "received_at",
        "freshness_s",
    }
    if not required <= set(receipt):
        raise AssistantContextProtocolError("context receipt is incomplete")
    if receipt["schema"] != _CONTEXT_RECEIPT_SCHEMA or receipt["log_scope"] != expected_scope:
        raise AssistantContextProtocolError("context receipt scope mismatch")
    if receipt["experiment_id"] != expected_experiment_id:
        raise AssistantContextProtocolError("context receipt experiment mismatch")
    for name in ("engine_incarnation", "experiment_incarnation"):
        if type(receipt[name]) is not str or not receipt[name]:
            raise AssistantContextProtocolError(f"context receipt {name} is invalid")
    for name in ("revision", "order"):
        if type(receipt[name]) is not int or receipt[name] < 0:
            raise AssistantContextProtocolError(f"context receipt {name} is invalid")
    receipt_start = receipt["query_start"]
    receipt_end = receipt["query_end"]
    for name, value in (("query_start", receipt_start), ("query_end", receipt_end)):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(float(value))):
            raise AssistantContextProtocolError(f"context receipt {name} is invalid")
    if receipt_start != query_start or receipt_end != query_end:
        raise AssistantContextProtocolError("context receipt query interval mismatch")
    received_raw = receipt["received_at"]
    if type(received_raw) is not str:
        raise AssistantContextProtocolError("context receipt receive time is invalid")
    try:
        received_at = datetime.fromisoformat(received_raw)
    except ValueError as exc:
        raise AssistantContextProtocolError("context receipt receive time is invalid") from exc
    if received_at.tzinfo is None:
        raise AssistantContextProtocolError("context receipt receive time lacks timezone")
    freshness_s = receipt["freshness_s"]
    if (
        type(freshness_s) not in (int, float)
        or not math.isfinite(float(freshness_s))
        or not 0 < freshness_s <= _MAX_CONTEXT_FRESHNESS_S
    ):
        raise AssistantContextProtocolError("context receipt freshness is invalid")
    age_s = (datetime.now(UTC) - received_at.astimezone(UTC)).total_seconds()
    if age_s < -5.0 or age_s > float(freshness_s):
        raise AssistantContextProtocolError("context receipt is stale")
    return dict(receipt)


class ContextAuthorityCache:
    """Small explicit cache whose authority is revoked on disconnect."""

    def __init__(self) -> None:
        self._value: object | None = None
        self._receipt: dict[str, Any] | None = None
        self._invalidated = True

    def put(self, value: object, receipt: object) -> None:
        if not isinstance(receipt, dict):
            raise AssistantContextProtocolError("context receipt is missing")
        self._value = value
        self._receipt = dict(receipt)
        self._invalidated = False

    def invalidate(self) -> None:
        self._value = None
        self._receipt = None
        self._invalidated = True

    def get(self, *, now: datetime | None = None) -> object | None:
        if self._invalidated or self._receipt is None:
            return None
        received_raw = self._receipt.get("received_at")
        freshness_s = self._receipt.get("freshness_s")
        if type(received_raw) is not str or type(freshness_s) not in (int, float):
            return None
        try:
            received_at = datetime.fromisoformat(received_raw)
        except ValueError:
            return None
        if received_at.tzinfo is None or not math.isfinite(float(freshness_s)) or freshness_s <= 0:
            return None
        age_s = ((now or datetime.now(UTC)) - received_at.astimezone(UTC)).total_seconds()
        if age_s < -5.0 or age_s > float(freshness_s):
            self.invalidate()
            return None
        return self._value


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
        receipt = reply.get("scope_receipt")
        expected_scope = "experiment" if experiment_id is not None else "all"
        _validate_context_receipt(
            receipt,
            expected_scope=expected_scope,
            expected_experiment_id=experiment_id,
            query_start=None if start_time is None else start_time.timestamp(),
            query_end=None if end_time is None else end_time.timestamp(),
        )
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
        _validate_context_receipt(
            reply.get("history_receipt"),
            expected_scope="history",
            expected_experiment_id=None,
            query_start=from_value,
            query_end=to_value,
        )
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
