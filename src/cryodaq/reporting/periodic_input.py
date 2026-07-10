"""Standard-library-only closed protocol for periodic PNG rendering.

This module is safe to import in long-lived parent and child preflight
processes.  It deliberately owns no renderer, storage, assistant, network, or
configuration imports.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PERIODIC_INPUT_SCHEMA = 1
PERIODIC_RESULT_SCHEMA = 1
MIN_INPUT_BYTES = 65_536
MAX_INPUT_BYTES = 33_554_432
MAX_RESULT_BYTES = 65_536
MAX_CAPTION_CODEPOINTS = 1_024
MAX_CAPTION_BYTES = 4_096
MAX_PNG_BYTES = 10 * 1024 * 1024

_TOKEN = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_SOURCE_EVIDENCE = re.compile(r"[a-z0-9_.:-]{1,192}")
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_TOP_KEYS = {"schema", "generation_id", "owner_token", "slot", "render", "readings", "alarms"}
_SLOT_KEYS = {
    "slot_id",
    "slot_start",
    "slot_end",
    "window_start",
    "window_end",
    "config_fingerprint",
}
_RENDER_KEYS = {
    "display_time",
    "include_channels",
    "max_points_per_channel",
    "max_total_points",
    "max_input_bytes",
    "history_complete",
    "alarm_state_complete",
    "dropped_points",
    "bad_points",
    "source_errors",
}
_READING_KEYS = {"ts", "iid", "ch", "v", "u", "st"}
_ALARM_KEYS = {"id", "level", "channels", "triggered_at", "acknowledged"}
_RESULT_KEYS = {
    "schema",
    "ok",
    "generation_id",
    "owner_token",
    "slot_id",
    "config_fingerprint",
    "artifact",
    "caption",
    "error_code",
    "error_text",
}
_ARTIFACT_KEYS = {"path", "sha256", "size", "width", "height", "mime"}


class PeriodicInputError(ValueError):
    """Frozen periodic input or result violates the closed protocol."""


@dataclass(frozen=True, slots=True)
class PeriodicSlotSnapshot:
    slot_id: str
    slot_start: int
    slot_end: int
    window_start: int
    window_end: int
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class PeriodicRenderSnapshot:
    display_time: str
    include_channels: tuple[str, ...] | None
    max_points_per_channel: int
    max_total_points: int
    max_input_bytes: int
    history_complete: bool
    alarm_state_complete: bool
    dropped_points: int
    bad_points: int
    source_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PeriodicReadingSnapshot:
    timestamp: float
    instrument_id: str
    channel: str
    value: float | None
    unit: str
    status: str


@dataclass(frozen=True, slots=True)
class PeriodicAlarmSnapshot:
    alarm_id: str
    level: str
    channels: tuple[str, ...]
    triggered_at: float
    acknowledged: bool


@dataclass(frozen=True, slots=True)
class ValidatedPeriodicInput:
    generation_id: str
    owner_token: str
    slot: PeriodicSlotSnapshot
    render: PeriodicRenderSnapshot
    readings: tuple[PeriodicReadingSnapshot, ...]
    alarms: tuple[PeriodicAlarmSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PeriodicFileFence:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int


def validate_generation_token(value: object, field: str = "generation_id") -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise PeriodicInputError(f"{field} is invalid")
    return value


def validate_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise PeriodicInputError(f"{field} is invalid")
    return value


def validate_input_byte_cap(value: object) -> int:
    if type(value) is not int or not MIN_INPUT_BYTES <= value <= MAX_INPUT_BYTES:
        raise PeriodicInputError("max_input_bytes is outside its allowed range")
    return value


def read_periodic_input_file(path: Path, *, expected_max_input_bytes: int) -> ValidatedPeriodicInput:
    """Read one input through a bounded no-follow descriptor and validate it."""

    snapshot, _fence = read_periodic_input_file_fenced(
        path, expected_max_input_bytes=expected_max_input_bytes
    )
    return snapshot


def read_periodic_input_file_fenced(
    path: Path, *, expected_max_input_bytes: int
) -> tuple[ValidatedPeriodicInput, PeriodicFileFence]:
    cap = validate_input_byte_cap(expected_max_input_bytes)
    raw, fence = _read_regular_file_fenced(
        Path(path), maximum=cap, label="periodic input"
    )
    return parse_periodic_input_bytes(raw, expected_max_input_bytes=cap), fence


def verify_periodic_file_fence(
    path: Path, expected: PeriodicFileFence, *, label: str = "periodic input"
) -> None:
    try:
        current = Path(path).lstat()
    except OSError as exc:
        raise PeriodicInputError(f"{label} path changed after reading") from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or _periodic_file_fence(current) != expected
    ):
        raise PeriodicInputError(f"{label} path changed after reading")


def parse_periodic_input_bytes(
    raw: bytes, *, expected_max_input_bytes: int
) -> ValidatedPeriodicInput:
    cap = validate_input_byte_cap(expected_max_input_bytes)
    if not isinstance(raw, bytes) or len(raw) > cap:
        raise PeriodicInputError("periodic input exceeds the trusted byte cap")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError, OverflowError, PeriodicInputError):
        raise PeriodicInputError("periodic input is not valid closed JSON") from None
    _require_depth(payload, depth=0)
    if not isinstance(payload, dict) or set(payload) != _TOP_KEYS:
        raise PeriodicInputError("periodic input has an invalid top-level schema")
    if type(payload["schema"]) is not int or payload["schema"] != PERIODIC_INPUT_SCHEMA:
        raise PeriodicInputError("unsupported periodic input schema")
    generation = validate_generation_token(payload["generation_id"])
    owner = validate_generation_token(payload["owner_token"], "owner_token")
    slot = _validate_slot(payload["slot"])
    render = _validate_render(payload["render"], expected_cap=cap)
    readings = _validate_readings(payload["readings"], slot=slot, render=render)
    alarms = _validate_alarms(payload["alarms"])
    return ValidatedPeriodicInput(generation, owner, slot, render, readings, alarms)


def serialize_periodic_input(
    payload: Mapping[str, object], *, expected_max_input_bytes: int
) -> tuple[bytes, ValidatedPeriodicInput]:
    """Canonicalize and validate parent-created frozen input before publish."""

    cap = validate_input_byte_cap(expected_max_input_bytes)
    try:
        raw = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise PeriodicInputError("periodic input is not serializable") from None
    if len(raw) > cap:
        raise PeriodicInputError("periodic input exceeds the trusted byte cap")
    return raw, parse_periodic_input_bytes(raw, expected_max_input_bytes=cap)


def validate_caption_html(value: object) -> str:
    """Validate the exact renderer-owned Telegram HTML subset and bounds."""

    if not isinstance(value, str):
        raise PeriodicInputError("periodic caption must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PeriodicInputError("periodic caption contains invalid Unicode") from None
    if len(value) > MAX_CAPTION_CODEPOINTS or len(encoded) > MAX_CAPTION_BYTES:
        raise PeriodicInputError("periodic caption exceeds transport bounds")
    open_bold = False
    index = 0
    while index < len(value):
        char = value[index]
        if (ord(char) < 32 and char != "\n") or ord(char) == 127:
            raise PeriodicInputError("periodic caption contains control characters")
        if char == "<":
            token = "<b>" if value.startswith("<b>", index) else "</b>" if value.startswith("</b>", index) else None
            if token is None or (token == "<b>" and open_bold) or (token == "</b>" and not open_bold):
                raise PeriodicInputError("periodic caption contains invalid markup")
            if "\n" in token:
                raise PeriodicInputError("periodic caption tag spans a line")
            open_bold = token == "<b>"
            index += len(token)
            continue
        if char == ">":
            raise PeriodicInputError("periodic caption contains raw markup")
        if char == "&":
            entity = next(
                (item for item in ("&amp;", "&lt;", "&gt;") if value.startswith(item, index)),
                None,
            )
            if entity is None:
                raise PeriodicInputError("periodic caption contains an invalid entity")
            index += len(entity)
            continue
        if char == "\n" and open_bold:
            raise PeriodicInputError("periodic caption tag spans a line")
        index += 1
    if open_bold:
        raise PeriodicInputError("periodic caption contains an unclosed tag")
    return value


def validate_result_payload(payload: object, *, require_success: bool | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _RESULT_KEYS:
        raise PeriodicInputError("periodic result has an invalid schema")
    result = dict(payload)
    if type(result["schema"]) is not int or result["schema"] != PERIODIC_RESULT_SCHEMA:
        raise PeriodicInputError("unsupported periodic result schema")
    if type(result["ok"]) is not bool:
        raise PeriodicInputError("periodic result ok must be a boolean")
    if require_success is not None and result["ok"] is not require_success:
        raise PeriodicInputError("periodic result has the wrong authority class")
    result["generation_id"] = validate_generation_token(result["generation_id"])
    result["owner_token"] = validate_generation_token(result["owner_token"], "owner_token")
    result["slot_id"] = validate_hash(result["slot_id"], "slot_id")
    result["config_fingerprint"] = validate_hash(
        result["config_fingerprint"], "config_fingerprint"
    )
    if result["ok"]:
        if result["error_code"] is not None or result["error_text"] != "":
            raise PeriodicInputError("successful periodic result contains failure evidence")
        result["artifact"] = _validate_artifact_mapping(
            result["artifact"], generation_id=result["generation_id"]
        )
        result["caption"] = validate_caption_html(result["caption"])
        if not result["caption"]:
            raise PeriodicInputError("successful periodic result caption is empty")
    else:
        if result["artifact"] is not None or result["caption"] != "":
            raise PeriodicInputError("failure side result contains success evidence")
        if not isinstance(result["error_code"], str) or _ERROR_CODE.fullmatch(result["error_code"]) is None:
            raise PeriodicInputError("failure side result has an invalid error code")
        result["error_text"] = _text(result["error_text"], minimum=1, maximum=2_048, field="error_text")
    return result


def _validate_slot(value: object) -> PeriodicSlotSnapshot:
    if not isinstance(value, dict) or set(value) != _SLOT_KEYS:
        raise PeriodicInputError("periodic slot has an invalid schema")
    start = _integer(value["slot_start"], minimum=0, field="slot_start")
    end = _integer(value["slot_end"], minimum=1, field="slot_end")
    window_start = _integer(value["window_start"], minimum=0, field="window_start")
    window_end = _integer(value["window_end"], minimum=1, field="window_end")
    if not start < end or window_end != end or not window_start < window_end:
        raise PeriodicInputError("periodic slot boundaries are inconsistent")
    slot_id = validate_hash(value["slot_id"], "slot_id")
    import hashlib

    expected = "sha256:" + hashlib.sha256(f"periodic-png/v1:{end}".encode("ascii")).hexdigest()
    if slot_id != expected:
        raise PeriodicInputError("periodic slot identity is inconsistent")
    return PeriodicSlotSnapshot(
        slot_id,
        start,
        end,
        window_start,
        window_end,
        validate_hash(value["config_fingerprint"], "config_fingerprint"),
    )


def _validate_render(value: object, *, expected_cap: int) -> PeriodicRenderSnapshot:
    if not isinstance(value, dict) or set(value) != _RENDER_KEYS:
        raise PeriodicInputError("periodic render options have an invalid schema")
    display = _text(value["display_time"], minimum=16, maximum=16, field="display_time")
    try:
        datetime.strptime(display, "%d.%m.%Y %H:%M")
    except ValueError:
        raise PeriodicInputError("display_time is not a real calendar value") from None
    channels = _string_tuple(
        value["include_channels"],
        nullable=True,
        minimum_count=1,
        maximum_count=64,
        maximum_bytes=256,
        field="include_channels",
    )
    per_channel = _integer(
        value["max_points_per_channel"], minimum=2, maximum=100_000, field="max_points_per_channel"
    )
    total = _integer(value["max_total_points"], minimum=2, maximum=500_000, field="max_total_points")
    if total < per_channel:
        raise PeriodicInputError("max_total_points is below the per-channel cap")
    declared = validate_input_byte_cap(value["max_input_bytes"])
    if declared != expected_cap:
        raise PeriodicInputError("periodic input cap does not match trusted argv")
    history = _boolean(value["history_complete"], "history_complete")
    alarms = _boolean(value["alarm_state_complete"], "alarm_state_complete")
    dropped = _integer(value["dropped_points"], minimum=0, maximum=2**31 - 1, field="dropped_points")
    bad = _integer(value["bad_points"], minimum=0, maximum=2**31 - 1, field="bad_points")
    raw_errors = value["source_errors"]
    if not isinstance(raw_errors, list) or len(raw_errors) > 32:
        raise PeriodicInputError("source_errors has an invalid count")
    errors: list[str] = []
    for item in raw_errors:
        if not isinstance(item, str) or _SOURCE_EVIDENCE.fullmatch(item) is None:
            raise PeriodicInputError("source_errors contains invalid evidence")
        if item in errors:
            raise PeriodicInputError("source_errors contains duplicate evidence")
        errors.append(item)
    return PeriodicRenderSnapshot(
        display,
        channels,
        per_channel,
        total,
        declared,
        history,
        alarms,
        dropped,
        bad,
        tuple(errors),
    )


def _validate_readings(
    value: object, *, slot: PeriodicSlotSnapshot, render: PeriodicRenderSnapshot
) -> tuple[PeriodicReadingSnapshot, ...]:
    if not isinstance(value, list) or len(value) > render.max_total_points:
        raise PeriodicInputError("periodic readings exceed the total cap")
    result: list[PeriodicReadingSnapshot] = []
    previous: tuple[float, str, str] | None = None
    instruments: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for item in value:
        if not isinstance(item, dict) or set(item) != _READING_KEYS:
            raise PeriodicInputError("periodic reading has an invalid schema")
        timestamp = _number(item["ts"], "reading timestamp")
        iid = _text(item["iid"], minimum=1, maximum=256, field="instrument_id")
        channel = _text(item["ch"], minimum=1, maximum=256, field="channel")
        raw_value = item["v"]
        reading_value = None if raw_value is None else _number(raw_value, "reading value")
        unit = _text(item["u"], minimum=0, maximum=64, field="unit")
        status = _text(item["st"], minimum=0, maximum=64, field="status")
        if not slot.window_start <= timestamp < slot.window_end:
            raise PeriodicInputError("reading timestamp is outside the frozen window")
        key = (timestamp, iid, channel)
        if previous is not None and key <= previous:
            raise PeriodicInputError("periodic readings are not strictly canonical")
        previous = key
        if channel in instruments and instruments[channel] != iid:
            raise PeriodicInputError("one channel has multiple instruments")
        instruments[channel] = iid
        if render.include_channels is not None and channel not in render.include_channels:
            raise PeriodicInputError("reading channel is outside include_channels")
        counts[channel] += 1
        if counts[channel] > render.max_points_per_channel:
            raise PeriodicInputError("periodic readings exceed a per-channel cap")
        result.append(PeriodicReadingSnapshot(timestamp, iid, channel, reading_value, unit, status))
    if len(instruments) > 64:
        raise PeriodicInputError("periodic readings exceed the channel cap")
    return tuple(result)


def _validate_alarms(value: object) -> tuple[PeriodicAlarmSnapshot, ...]:
    if not isinstance(value, list) or len(value) > 128:
        raise PeriodicInputError("periodic alarms exceed the active-alarm cap")
    result: list[PeriodicAlarmSnapshot] = []
    previous = ""
    for item in value:
        if not isinstance(item, dict) or set(item) != _ALARM_KEYS:
            raise PeriodicInputError("periodic alarm has an invalid schema")
        alarm_id = _text(item["id"], minimum=1, maximum=256, field="alarm id")
        if previous and alarm_id <= previous:
            raise PeriodicInputError("periodic alarms are not in unique lexical order")
        previous = alarm_id
        level = item["level"]
        if not isinstance(level, str) or level not in {"INFO", "WARNING", "CRITICAL"}:
            raise PeriodicInputError("periodic alarm level is invalid")
        channels = _string_tuple(
            item["channels"],
            nullable=False,
            minimum_count=0,
            maximum_count=64,
            maximum_bytes=256,
            field="alarm channels",
        )
        assert channels is not None
        triggered = _number(item["triggered_at"], "alarm triggered_at")
        if triggered < 0:
            raise PeriodicInputError("alarm triggered_at is negative")
        acknowledged = _boolean(item["acknowledged"], "acknowledged")
        result.append(PeriodicAlarmSnapshot(alarm_id, level, channels, triggered, acknowledged))
    return tuple(result)


def _validate_artifact_mapping(value: object, *, generation_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ARTIFACT_KEYS:
        raise PeriodicInputError("periodic result artifact has an invalid schema")
    artifact = dict(value)
    if artifact["path"] != f"periodic/generations/{generation_id}/periodic.png":
        raise PeriodicInputError("periodic result artifact path is invalid")
    artifact["sha256"] = validate_hash(artifact["sha256"], "artifact sha256")
    artifact["size"] = _integer(artifact["size"], minimum=1, maximum=MAX_PNG_BYTES, field="artifact size")
    artifact["width"] = _integer(artifact["width"], minimum=100, maximum=10_000, field="artifact width")
    artifact["height"] = _integer(artifact["height"], minimum=100, maximum=10_000, field="artifact height")
    if artifact["width"] + artifact["height"] > 10_000 or artifact["width"] * artifact["height"] > 50_000_000:
        raise PeriodicInputError("periodic result artifact dimensions are invalid")
    if artifact["mime"] != "image/png":
        raise PeriodicInputError("periodic result artifact MIME is invalid")
    return artifact


def _read_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    raw, _fence = _read_regular_file_fenced(path, maximum=maximum, label=label)
    return raw


def _read_regular_file_fenced(
    path: Path, *, maximum: int, label: str
) -> tuple[bytes, PeriodicFileFence]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise PeriodicInputError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PeriodicInputError(f"{label} is not a regular single-link file")
    if before.st_size > maximum:
        raise PeriodicInputError(f"{label} exceeds its byte cap")
    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0))
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise PeriodicInputError(f"{label} changed while opening")
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise PeriodicInputError(f"{label} changed while opening")
            raw = _read_bounded(fd, maximum)
            finished = os.fstat(fd)
            if _periodic_file_fence(opened) != _periodic_file_fence(finished):
                raise PeriodicInputError(f"{label} changed while reading")
            try:
                after_path = path.lstat()
            except OSError:
                raise PeriodicInputError(f"{label} path changed while reading") from None
            if _periodic_file_fence(after_path) != _periodic_file_fence(finished):
                raise PeriodicInputError(f"{label} path changed while reading")
        finally:
            os.close(fd)
    except PeriodicInputError:
        raise
    except OSError as exc:
        raise PeriodicInputError(f"{label} could not be read safely") from exc
    if len(raw) > maximum:
        raise PeriodicInputError(f"{label} exceeds its byte cap")
    return raw, _periodic_file_fence(finished)


def _read_bounded(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _periodic_file_fence(info: os.stat_result) -> PeriodicFileFence:
    return PeriodicFileFence(
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PeriodicInputError("periodic JSON contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise PeriodicInputError("periodic JSON contains a non-finite number")


def _require_depth(value: object, *, depth: int) -> None:
    if depth > 24:
        raise PeriodicInputError("periodic JSON exceeds the nesting limit")
    if isinstance(value, dict):
        for key, item in value.items():
            _require_depth(key, depth=depth + 1)
            _require_depth(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _require_depth(item, depth=depth + 1)


def _integer(value: object, *, minimum: int, field: str, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise PeriodicInputError(f"{field} is outside its integer bounds")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PeriodicInputError(f"{field} is not numeric")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise PeriodicInputError(f"{field} is not finite") from None
    if not math.isfinite(result):
        raise PeriodicInputError(f"{field} is not finite")
    return result


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise PeriodicInputError(f"{field} must be a boolean")
    return value


def _text(value: object, *, minimum: int, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise PeriodicInputError(f"{field} is not text")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PeriodicInputError(f"{field} contains control characters")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeError:
        raise PeriodicInputError(f"{field} contains invalid Unicode") from None
    if not minimum <= size <= maximum:
        raise PeriodicInputError(f"{field} is outside its text bounds")
    return value


def _string_tuple(
    value: object,
    *,
    nullable: bool,
    minimum_count: int,
    maximum_count: int,
    maximum_bytes: int,
    field: str,
) -> tuple[str, ...] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, list) or not minimum_count <= len(value) <= maximum_count:
        raise PeriodicInputError(f"{field} has an invalid count")
    result = tuple(_text(item, minimum=1, maximum=maximum_bytes, field=field) for item in value)
    if len(result) != len(set(result)):
        raise PeriodicInputError(f"{field} contains duplicates")
    return result
