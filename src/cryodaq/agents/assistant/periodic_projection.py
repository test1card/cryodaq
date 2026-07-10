"""Bounded, lightweight live projections for periodic PNG reports.

Callbacks perform only validation and bounded in-memory bookkeeping.  Archive
I/O, snapshot RPC, rendering, hashing, and delivery belong to the coordinator.
"""

from __future__ import annotations

import heapq
import json
import math
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryodaq.drivers.base import Reading

if TYPE_CHECKING:
    from cryodaq.periodic_config import PeriodicPngConfig
    from cryodaq.storage.archive_reader import BoundedReadingQueryResult

_MAX_FUTURE_SKEW_S = 300.0
_MAX_ALARM_SNAPSHOT_AGE_S = 300.0
_MAX_SOURCE_ERRORS = 32
_MAX_READING_CHANNELS = 64
_MAX_ACTIVE_ALARMS = 128
_MAX_ALARM_EVENTS = 256


@dataclass(frozen=True, slots=True)
class PeriodicInputReading:
    timestamp: float
    instrument_id: str
    channel: str
    value: float | None
    unit: str
    status: str


@dataclass(frozen=True, slots=True)
class PeriodicInputAlarm:
    alarm_id: str
    level: str
    message: str
    triggered_at: float
    channels: tuple[str, ...]
    acknowledged: bool
    acknowledged_at: float | None
    acknowledged_by: str


@dataclass(frozen=True, slots=True)
class ProjectionSnapshot:
    window_start: float
    window_end: float
    readings: tuple[PeriodicInputReading, ...]
    active_alarms: tuple[PeriodicInputAlarm, ...]
    history_complete: bool
    alarm_state_complete: bool
    dropped_points: int
    bad_points: int
    source_errors: tuple[str, ...]


@dataclass(slots=True)
class _ProjectionEntry:
    row: PeriodicInputReading
    priority: int
    token: int
    encoded_size: int

    @property
    def key(self) -> tuple[float, str, str]:
        return (self.row.timestamp, self.row.instrument_id, self.row.channel)


def _text(raw: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(raw, str):
        raise ValueError("not text")
    if not minimum <= len(raw.encode("utf-8")) <= maximum:
        raise ValueError("text outside bounds")
    return raw


def _number(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("not numeric")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("not finite")
    return value


def _row_size(row: PeriodicInputReading) -> int:
    return len(
        json.dumps(
            [
                row.timestamp,
                row.instrument_id,
                row.channel,
                row.value,
                row.unit,
                row.status,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


class BoundedReadingProjection:
    """Merge live readings with bounded hydration without a startup gap."""

    def __init__(self, config: PeriodicPngConfig) -> None:
        self._config = config
        self._byte_cap = max(32_768, config.max_input_bytes * 3 // 4)
        self._entries: dict[tuple[float, str, str], _ProjectionEntry] = {}
        self._global_heap: list[tuple[float, str, str, int]] = []
        self._channel_heaps: dict[str, list[tuple[float, str, str, int]]] = {}
        self._channel_counts: dict[str, int] = {}
        self._latest_live_by_channel: dict[str, float] = {}
        self._known_channels: set[str] = set(config.include_channels or ())
        self._encoded_bytes = 0
        self._next_token = 0
        self._history_complete = False
        self._live_channel_complete = True
        self._source_errors: tuple[str, ...] = ()
        self._live_errors: tuple[str, ...] = ()
        self._dropped_points = 0
        self._bad_points = 0

    def _is_live(self, item: tuple[float, str, str, int]) -> bool:
        entry = self._entries.get((item[0], item[1], item[2]))
        return entry is not None and entry.token == item[3]

    def _pop_live(self, heap: list[tuple[float, str, str, int]]) -> _ProjectionEntry | None:
        while heap:
            item = heapq.heappop(heap)
            if self._is_live(item):
                return self._entries[(item[0], item[1], item[2])]
        return None

    def _compact_channel(self, channel: str) -> None:
        count = self._channel_counts.get(channel, 0)
        heap = self._channel_heaps.get(channel)
        if heap is None:
            return
        if count == 0:
            self._channel_heaps.pop(channel, None)
            return
        if len(heap) > 2 * count + 64:
            rebuilt = [(*entry.key, entry.token) for entry in self._entries.values() if entry.row.channel == channel]
            heapq.heapify(rebuilt)
            self._channel_heaps[channel] = rebuilt

    def _evict(self, entry: _ProjectionEntry) -> None:
        current = self._entries.get(entry.key)
        if current is None or current.token != entry.token:
            return
        del self._entries[entry.key]
        channel = entry.row.channel
        self._channel_counts[channel] -= 1
        if self._channel_counts[channel] == 0:
            del self._channel_counts[channel]
        self._encoded_bytes -= entry.encoded_size
        self._dropped_points += 1
        self._compact_channel(channel)

    def _compact(self, channel: str) -> None:
        if len(self._global_heap) > 2 * len(self._entries) + 64:
            self._global_heap = [(*entry.key, entry.token) for entry in self._entries.values()]
            heapq.heapify(self._global_heap)
        self._compact_channel(channel)

    def _offer(self, row: PeriodicInputReading, *, priority: int) -> None:
        size = _row_size(row)
        if size > self._byte_cap:
            self._dropped_points += 1
            return
        key = (row.timestamp, row.instrument_id, row.channel)
        previous = self._entries.get(key)
        if previous is not None and priority < previous.priority:
            return
        if previous is not None and priority == previous.priority and row == previous.row:
            return
        if previous is None:
            self._channel_counts[row.channel] = self._channel_counts.get(row.channel, 0) + 1
        else:
            self._encoded_bytes -= previous.encoded_size
        self._next_token += 1
        entry = _ProjectionEntry(row, priority, self._next_token, size)
        self._entries[key] = entry
        self._encoded_bytes += size
        heap_item = (*key, entry.token)
        heapq.heappush(self._global_heap, heap_item)
        channel_heap = self._channel_heaps.setdefault(row.channel, [])
        heapq.heappush(channel_heap, heap_item)
        while self._channel_counts.get(row.channel, 0) > self._config.max_points_per_channel:
            victim = self._pop_live(channel_heap)
            if victim is not None:
                self._evict(victim)
        while len(self._entries) > self._config.max_total_points:
            victim = self._pop_live(self._global_heap)
            if victim is not None:
                self._evict(victim)
        while self._encoded_bytes > self._byte_cap:
            victim = self._pop_live(self._global_heap)
            if victim is not None:
                self._evict(victim)
        self._compact(row.channel)

    def append_live(self, reading: Reading) -> None:
        """Validate and append one live callback without blocking I/O."""

        try:
            if not isinstance(reading, Reading):
                raise ValueError("not a Reading")
            if reading.timestamp.tzinfo is None or reading.timestamp.utcoffset() is None:
                raise ValueError("naive timestamp")
            timestamp = reading.timestamp.astimezone(UTC).timestamp()
            if not math.isfinite(timestamp) or timestamp > time.time() + _MAX_FUTURE_SKEW_S:
                raise ValueError("future timestamp")
            instrument = _text(reading.instrument_id, minimum=1, maximum=256)
            channel = _text(reading.channel, minimum=1, maximum=256)
            if self._config.include_channels is not None and channel not in self._config.include_channels:
                return
            if channel not in self._known_channels:
                if len(self._known_channels) >= _MAX_READING_CHANNELS:
                    self._live_channel_complete = False
                    self._history_complete = False
                    if "live_channel_limit" not in self._live_errors:
                        self._live_errors = (*self._live_errors, "live_channel_limit")
                    self._dropped_points += 1
                    return
                self._known_channels.add(channel)
            unit = _text(reading.unit, minimum=0, maximum=64)
            status = _text(reading.status.value, minimum=1, maximum=64)
            latest = self._latest_live_by_channel.get(channel)
            if latest is not None and timestamp < latest:
                raise ValueError("out-of-order live reading")
            value = float(reading.value)
            if reading.is_usable() and math.isfinite(value):
                normalized_value: float | None = value
            else:
                normalized_value = None
                self._bad_points += 1
            row = PeriodicInputReading(timestamp, instrument, channel, normalized_value, unit, status)
        except (AttributeError, TypeError, ValueError, OSError, OverflowError):
            self._bad_points += 1
            return
        self._offer(row, priority=2)
        if channel in self._channel_counts:
            self._latest_live_by_channel[channel] = timestamp

    def merge_hydration(self, result: BoundedReadingQueryResult, *, cut: float) -> None:
        """Merge persisted history below the subscribe cut; live rows win ties."""

        cut_value = _number(cut)
        merge_valid = True
        for channel in result.discovered_channels:
            try:
                bounded_channel = _text(channel, minimum=1, maximum=256)
            except (TypeError, ValueError, OSError, OverflowError):
                merge_valid = False
                continue
            if bounded_channel not in self._known_channels:
                if len(self._known_channels) >= _MAX_READING_CHANNELS:
                    self._live_channel_complete = False
                    merge_valid = False
                    if "live_channel_limit" not in self._live_errors:
                        self._live_errors = (*self._live_errors, "live_channel_limit")
                    continue
                self._known_channels.add(bounded_channel)
        for raw in result.rows:
            if raw.timestamp >= cut_value:
                continue
            try:
                row = PeriodicInputReading(
                    timestamp=_number(raw.timestamp),
                    instrument_id=_text(raw.instrument_id, minimum=1, maximum=256),
                    channel=_text(raw.channel, minimum=1, maximum=256),
                    value=None if raw.value is None else _number(raw.value),
                    unit=_text(raw.unit, minimum=0, maximum=64),
                    status=_text(raw.status, minimum=0, maximum=64),
                )
            except (TypeError, ValueError, OSError, OverflowError):
                self._bad_points += 1
                merge_valid = False
                continue
            if row.channel not in self._known_channels:
                merge_valid = False
                self._dropped_points += 1
                continue
            if self._config.include_channels is None or row.channel in self._config.include_channels:
                self._offer(row, priority=1)
        self._dropped_points += result.rows_dropped_by_caps
        self._history_complete = result.complete and merge_valid and self._live_channel_complete
        self._source_errors = tuple(
            f"{issue.code.value}:{issue.source}"
            for issue in result.issues[: _MAX_SOURCE_ERRORS - (1 if result.issue_overflow else 0)]
        )
        if result.issue_overflow:
            self._source_errors += (f"issue_overflow:{result.issue_overflow}",)

    def freeze(self, *, window_start: float, window_end: float) -> tuple[PeriodicInputReading, ...]:
        """Return an immutable, deterministic window ending at the slot boundary."""

        start = _number(window_start)
        end = _number(window_end)
        if not start < end:
            raise ValueError("window_start must be before window_end")
        return tuple(
            entry.row
            for entry in sorted(self._entries.values(), key=lambda item: item.key)
            if start <= entry.row.timestamp < end
        )

    def snapshot(
        self,
        *,
        window_start: float,
        window_end: float,
        alarms: tuple[PeriodicInputAlarm, ...] = (),
        alarm_state_complete: bool = False,
    ) -> ProjectionSnapshot:
        if type(alarm_state_complete) is not bool:
            raise TypeError("alarm_state_complete must be a boolean")
        return ProjectionSnapshot(
            window_start=_number(window_start),
            window_end=_number(window_end),
            readings=self.freeze(window_start=window_start, window_end=window_end),
            active_alarms=tuple(alarms),
            history_complete=self._history_complete,
            alarm_state_complete=alarm_state_complete,
            dropped_points=self._dropped_points,
            bad_points=self._bad_points,
            source_errors=tuple(
                (
                    *self._source_errors[: _MAX_SOURCE_ERRORS - len(self._live_errors)],
                    *self._live_errors,
                )
            ),
        )

    def mark_history_incomplete(self, code: str) -> None:
        self._history_complete = False
        safe = _text(code, minimum=1, maximum=96)
        self._source_errors = (*self._source_errors[-(_MAX_SOURCE_ERRORS - 1) :], safe)

    def clear(self) -> None:
        self._entries.clear()
        self._global_heap.clear()
        self._channel_heaps.clear()
        self._channel_counts.clear()
        self._latest_live_by_channel.clear()
        self._known_channels = set(self._config.include_channels or ())
        self._encoded_bytes = 0
        self._next_token = 0
        self._history_complete = False
        self._live_channel_complete = True
        self._source_errors = ()
        self._live_errors = ()
        self._dropped_points = 0
        self._bad_points = 0


@dataclass(frozen=True, slots=True)
class _BufferedAlarmEvent:
    sequence: int
    event_type: str
    timestamp: float
    alarm_id: str
    alarm: PeriodicInputAlarm | None


@dataclass(frozen=True, slots=True)
class AlarmSnapshotCut:
    """Opaque generation plus receive sequence for exactly one snapshot RPC."""

    generation: int
    sequence: int


class AlarmProjection:
    """Convergent alarm snapshot plus receive-ordered event projection."""

    def __init__(self) -> None:
        self._active: dict[str, PeriodicInputAlarm] = {}
        self._buffer: deque[_BufferedAlarmEvent] = deque()
        self._complete = False
        self._captured_at = 0.0
        self._receive_sequence = 0
        self._snapshot_generation = 0
        self._pending_snapshot_cut: AlarmSnapshotCut | None = None
        self._uncertain_min: int | None = None
        self._uncertain_max: int | None = None

    def _mark_uncertain(self, sequence: int) -> None:
        self._uncertain_min = sequence if self._uncertain_min is None else min(self._uncertain_min, sequence)
        self._uncertain_max = sequence if self._uncertain_max is None else max(self._uncertain_max, sequence)
        self._complete = False

    def capture_receive_cut(self) -> AlarmSnapshotCut:
        """Mark the local event sequence immediately before snapshot RPC."""

        if self._pending_snapshot_cut is not None:
            raise RuntimeError("an alarm snapshot request is already in flight")
        self._snapshot_generation += 1
        cut = AlarmSnapshotCut(self._snapshot_generation, self._receive_sequence)
        self._pending_snapshot_cut = cut
        while self._buffer and self._buffer[0].sequence <= cut.sequence:
            self._buffer.popleft()
        return cut

    @staticmethod
    def _event_timestamp(raw: object) -> float:
        if isinstance(raw, str):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("naive event timestamp")
            return _number(parsed.astimezone(UTC).timestamp())
        return _number(raw)

    @classmethod
    def _alarm(cls, alarm_id: str, payload: Mapping[str, object]) -> PeriodicInputAlarm:
        channels_raw = payload.get("channels", ())
        if not isinstance(channels_raw, (list, tuple)) or len(channels_raw) > 64:
            raise ValueError("invalid alarm channels")
        channels = tuple(_text(item, minimum=1, maximum=256) for item in channels_raw)
        acknowledged = payload.get("acknowledged", False)
        if type(acknowledged) is not bool:
            raise ValueError("invalid acknowledged")
        acknowledged_at_raw = payload.get("acknowledged_at")
        level = _text(payload.get("level", "UNKNOWN"), minimum=1, maximum=32)
        if level not in {"INFO", "WARNING", "CRITICAL"}:
            raise ValueError("invalid alarm level")
        acknowledged_by = _text(payload.get("acknowledged_by", ""), minimum=0, maximum=256)
        if acknowledged:
            acknowledged_at = _number(acknowledged_at_raw)
            if acknowledged_at <= 0:
                raise ValueError("invalid acknowledgement timestamp")
        else:
            if acknowledged_at_raw is not None and _number(acknowledged_at_raw) != 0.0:
                raise ValueError("unexpected acknowledgement timestamp")
            if acknowledged_by:
                raise ValueError("unexpected acknowledgement operator")
            acknowledged_at = None
        return PeriodicInputAlarm(
            alarm_id=_text(alarm_id, minimum=1, maximum=256),
            level=level,
            message=_text(payload.get("message", ""), minimum=0, maximum=2_048),
            triggered_at=_number(payload.get("triggered_at", payload.get("timestamp"))),
            channels=channels,
            acknowledged=acknowledged,
            acknowledged_at=acknowledged_at,
            acknowledged_by=acknowledged_by,
        )

    def _apply(self, event: _BufferedAlarmEvent) -> None:
        if event.event_type == "alarm_cleared":
            self._active.pop(event.alarm_id, None)
        elif event.alarm is not None:
            if event.alarm_id in self._active or len(self._active) < _MAX_ACTIVE_ALARMS:
                self._active[event.alarm_id] = event.alarm
            else:
                self._complete = False

    def buffer_event(self, event: Mapping[str, object]) -> None:
        self._receive_sequence += 1
        sequence = self._receive_sequence
        try:
            event_type = _text(event.get("event_type"), minimum=1, maximum=64)
            if event_type not in {"alarm_fired", "alarm_cleared"}:
                return
            timestamp = self._event_timestamp(event.get("ts"))
            if timestamp > time.time() + _MAX_FUTURE_SKEW_S:
                raise ValueError("future alarm event")
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError("invalid alarm payload")
            alarm_id = _text(payload.get("alarm_id"), minimum=1, maximum=256)
            alarm = None
            if event_type == "alarm_fired":
                merged = dict(payload)
                merged.setdefault("triggered_at", timestamp)
                alarm = self._alarm(alarm_id, merged)
            parsed = _BufferedAlarmEvent(sequence, event_type, timestamp, alarm_id, alarm)
        except (TypeError, ValueError, OSError, OverflowError):
            self._mark_uncertain(sequence)
            return
        if len(self._buffer) >= _MAX_ALARM_EVENTS:
            lost = self._buffer.popleft()
            if self._pending_snapshot_cut is not None and lost.sequence > self._pending_snapshot_cut.sequence:
                self._mark_uncertain(lost.sequence)
        self._buffer.append(parsed)
        if self._complete:
            self._apply(parsed)

    def install_snapshot(
        self,
        reply: Mapping[str, object],
        *,
        captured_at: float,
        receive_cut: AlarmSnapshotCut,
    ) -> None:
        try:
            cut = _number(captured_at)
            if (
                not isinstance(receive_cut, AlarmSnapshotCut)
                or receive_cut.sequence < 0
                or receive_cut.sequence > self._receive_sequence
                or receive_cut != self._pending_snapshot_cut
            ):
                raise ValueError("invalid snapshot receive cut")
            if reply.get("ok") is not True:
                raise ValueError("snapshot unavailable")
            active = reply.get("active")
            if not isinstance(active, Mapping) or len(active) > _MAX_ACTIVE_ALARMS:
                raise ValueError("invalid active alarms")
            replacement: dict[str, PeriodicInputAlarm] = {}
            for raw_id, raw_payload in active.items():
                alarm_id = _text(raw_id, minimum=1, maximum=256)
                if not isinstance(raw_payload, Mapping):
                    raise ValueError("invalid alarm snapshot entry")
                replacement[alarm_id] = self._alarm(alarm_id, raw_payload)
        except (TypeError, ValueError, OSError, OverflowError):
            self._complete = False
            if receive_cut == self._pending_snapshot_cut:
                self._pending_snapshot_cut = None
            return
        self._active = replacement
        self._captured_at = cut
        self._complete = not (self._uncertain_max is not None and self._uncertain_max > receive_cut.sequence)
        for event in self._buffer:
            if event.sequence > receive_cut.sequence:
                self._apply(event)
        self._buffer = deque(event for event in self._buffer if event.sequence > receive_cut.sequence)
        if self._uncertain_max is not None and self._uncertain_max <= receive_cut.sequence:
            self._uncertain_min = None
            self._uncertain_max = None
        self._pending_snapshot_cut = None

    def freeze(self, *, now: float) -> tuple[tuple[PeriodicInputAlarm, ...], bool]:
        current = _number(now)
        if self._captured_at > current + _MAX_FUTURE_SKEW_S or current - self._captured_at > _MAX_ALARM_SNAPSHOT_AGE_S:
            self._complete = False
        alarms = tuple(self._active[key] for key in sorted(self._active))
        return alarms, self._complete

    def clear(self) -> None:
        self._active.clear()
        self._buffer.clear()
        self._complete = False
        self._captured_at = 0.0
        self._receive_sequence = 0
        self._pending_snapshot_cut = None
        self._uncertain_min = None
        self._uncertain_max = None
