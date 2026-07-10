"""Strict, lightweight authority for periodic PNG notification settings.

This module deliberately owns no runtime resources.  Both the launcher probe
and the assistant-side loader use the same whole-file selection and safety
rules so an unsafe local file can never fall through to the tracked template.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cryodaq.notifications._secrets import SecretStr

_MAX_CONFIG_BYTES = 64 * 1024
_MAX_FUTURE_SKEW_S = 300.0
_LOCAL_NAME = "notifications.local.yaml"
_TRACKED_NAME = "notifications.yaml"
_PERIODIC_KEYS = {
    "enabled",
    "report_interval_s",
    "chart_hours",
    "include_channels",
    "max_points_per_channel",
    "max_total_points",
    "max_input_bytes",
    "render_timeout_s",
    "max_render_attempts",
    "max_delivery_attempts",
    "backoff_base_s",
    "backoff_cap_s",
}
_PLACEHOLDER_TOKENS = {
    "your_bot_token_here",
    "insert_bot_token_here",
    "replace_me",
    "changeme",
    "token",
    "вставьте_токен_от_botfather",
}
_CHANNEL_NATURAL_PART = re.compile(r"(\d+)")
_CHANNEL_NAME = re.compile(r"\S")
_CHANNEL_DESTINATION = re.compile(r"@[A-Za-z][A-Za-z0-9_]{0,126}")
_CANONICAL_DECIMAL = re.compile(r"-?[1-9][0-9]*")
_BOT_TOKEN = re.compile(r"[1-9][0-9]{5,19}:[A-Za-z0-9_-]{20,256}")


@dataclass(frozen=True, slots=True)
class PeriodicPngProbe:
    selected_path: Path | None
    requested: bool
    error_code: str | None
    error_text: str


@dataclass(frozen=True, slots=True)
class PeriodicPngConfig:
    enabled: bool
    interval_s: int
    chart_window_s: int
    include_channels: tuple[str, ...] | None
    max_points_per_channel: int
    max_total_points: int
    max_input_bytes: int
    render_timeout_s: float
    max_render_attempts: int
    max_delivery_attempts: int
    backoff_base_s: float
    backoff_cap_s: float
    telegram_token: SecretStr
    telegram_chat_id: int | str
    telegram_timeout_s: float
    telegram_verify_ssl: bool
    config_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or not self.enabled:
            raise ValueError("runnable periodic config must be enabled")
        if not isinstance(self.telegram_token, SecretStr):
            raise TypeError("telegram_token must be SecretStr")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.config_fingerprint):
            raise ValueError("config_fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class PeriodicPngConfigLoad:
    selected_path: Path | None
    requested: bool
    runnable: bool
    config: PeriodicPngConfig | None
    error_code: str | None
    error_text: str


class _ConfigError(ValueError):
    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


class _StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses ambiguous duplicate mapping keys."""

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[object, object]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "expected a mapping node",
                node.start_mark,
            )
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from None
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found a duplicate key",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def select_notifications_path(config_dir: Path) -> Path | None:
    """Select one whole-file authority using lexical existence.

    A dangling or symlinked local file is intentionally selected here and is
    rejected by the reader.  It must not cause fallback to the tracked file.
    """

    root = Path(config_dir)
    local = root / _LOCAL_NAME
    if os.path.lexists(local):
        return local
    tracked = root / _TRACKED_NAME
    if os.path.lexists(tracked):
        return tracked
    return None


def probe_periodic_png(config_dir: Path) -> PeriodicPngProbe:
    """Return the exact periodic-request signal without validating secrets."""

    selected = select_notifications_path(config_dir)
    if selected is None:
        return PeriodicPngProbe(None, False, None, "")
    try:
        payload = _load_selected_mapping(selected)
        periodic = payload.get("periodic_report", {})
        if periodic is None:
            periodic = {}
        if not isinstance(periodic, dict):
            raise _ConfigError("invalid_periodic_section", "periodic_report must be a mapping")
        enabled = periodic.get("enabled", False)
        if type(enabled) is not bool:
            raise _ConfigError("invalid_enabled", "periodic_report.enabled must be a boolean")
        return PeriodicPngProbe(selected, enabled, None, "")
    except _ConfigError as exc:
        return PeriodicPngProbe(selected, False, exc.code, exc.text)


def load_periodic_png_config(config_dir: Path) -> PeriodicPngConfigLoad:
    """Load the selected periodic configuration under a closed strict schema."""

    selected = select_notifications_path(config_dir)
    if selected is None:
        return PeriodicPngConfigLoad(None, False, False, None, None, "")
    requested = False
    try:
        payload = _load_selected_mapping(selected)
        periodic = payload.get("periodic_report", {})
        if periodic is None:
            periodic = {}
        if not isinstance(periodic, dict):
            raise _ConfigError("invalid_periodic_section", "periodic_report must be a mapping")
        enabled = periodic.get("enabled", False)
        if type(enabled) is not bool:
            raise _ConfigError("invalid_enabled", "periodic_report.enabled must be a boolean")
        requested = enabled
        if not enabled:
            return PeriodicPngConfigLoad(selected, False, False, None, None, "")
        config = _validate_enabled_config(payload, periodic)
        return PeriodicPngConfigLoad(selected, True, True, config, None, "")
    except _ConfigError as exc:
        return PeriodicPngConfigLoad(selected, requested, False, None, exc.code, exc.text)


def _load_selected_mapping(path: Path) -> dict[str, Any]:
    try:
        before = path.lstat()
    except OSError:
        raise _ConfigError("unsafe_config", "selected notifications file is unavailable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise _ConfigError("unsafe_config", "selected notifications file must be a regular file")
    if before.st_nlink != 1:
        raise _ConfigError("unsafe_config", "selected notifications file must have one link")
    if before.st_size > _MAX_CONFIG_BYTES:
        raise _ConfigError("config_too_large", "selected notifications file exceeds 64 KiB")
    if before.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
        raise _ConfigError("future_config", "selected notifications file is future-dated")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise _ConfigError("unsafe_config", "selected notifications file is unsafe")
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise _ConfigError("unsafe_config", "selected notifications file changed while reading")
            if opened.st_size > _MAX_CONFIG_BYTES:
                raise _ConfigError("config_too_large", "selected notifications file exceeds 64 KiB")
            if opened.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
                raise _ConfigError("future_config", "selected notifications file is future-dated")
            snapshot = _stat_snapshot(opened)
            raw = _read_bounded(fd, _MAX_CONFIG_BYTES)
            finished = os.fstat(fd)
            if _stat_snapshot(finished) != snapshot:
                raise _ConfigError(
                    "unsafe_config", "selected notifications file changed while reading"
                )
            if finished.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
                raise _ConfigError("future_config", "selected notifications file is future-dated")
        finally:
            os.close(fd)
    except _ConfigError:
        raise
    except OSError:
        raise _ConfigError("unsafe_config", "selected notifications file cannot be read safely") from None
    if len(raw) > _MAX_CONFIG_BYTES:
        raise _ConfigError("config_too_large", "selected notifications file exceeds 64 KiB")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _ConfigError("invalid_encoding", "selected notifications file is not valid UTF-8") from None
    try:
        loaded = yaml.load(text, Loader=_StrictSafeLoader)
    except Exception:
        # YAML diagnostics can echo the secret-bearing source line.  Never
        # include the parser exception in the public result.  PyYAML and
        # Python's integer parser can also raise ValueError/RecursionError for
        # hostile but size-bounded inputs, so the public probe/load boundary is
        # deliberately total over ordinary Exceptions.
        raise _ConfigError("invalid_yaml", "selected notifications file is not valid YAML") from None
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise _ConfigError("invalid_root", "selected notifications file must contain one mapping")
    return loaded


def _validate_enabled_config(
    payload: dict[str, Any], periodic: dict[str, Any]
) -> PeriodicPngConfig:
    unknown = set(periodic) - _PERIODIC_KEYS
    if unknown:
        raise _ConfigError("unknown_periodic_key", "periodic_report contains an unknown field")
    telegram = payload.get("telegram")
    if not isinstance(telegram, dict):
        raise _ConfigError("invalid_telegram_section", "telegram must be a mapping")

    interval_s = _exact_int(periodic, "report_interval_s", 1800, 60, 86_400)
    chart_window_s = _chart_window(periodic.get("chart_hours", 2.0))
    channels = _channels(periodic.get("include_channels"))
    per_channel = _exact_int(periodic, "max_points_per_channel", 20_000, 2, 100_000)
    total = _exact_int(periodic, "max_total_points", 100_000, 2, 500_000)
    if total < per_channel:
        raise _ConfigError("invalid_max_total_points", "max_total_points is below the per-channel cap")
    max_input_bytes = _exact_int(
        periodic, "max_input_bytes", 8 * 1024 * 1024, 65_536, 33_554_432
    )
    render_timeout = _finite_number(periodic, "render_timeout_s", 120.0, 5.0, 600.0)
    max_render_attempts = _exact_int(periodic, "max_render_attempts", 5, 1, 10)
    max_delivery_attempts = _exact_int(periodic, "max_delivery_attempts", 5, 1, 10)
    backoff_base = _finite_number(periodic, "backoff_base_s", 30.0, 1.0, 3600.0)
    backoff_cap = _finite_number(periodic, "backoff_cap_s", 3600.0, backoff_base, 86_400.0)

    raw_token = telegram.get("bot_token")
    if not isinstance(raw_token, str):
        raise _ConfigError("invalid_bot_token", "telegram.bot_token must be a nonempty string")
    token_bytes = _utf8_bytes(raw_token, "invalid_bot_token", "telegram.bot_token is not valid UTF-8")
    if (
        _BOT_TOKEN.fullmatch(raw_token) is None
        or len(token_bytes) > 512
        or raw_token.strip().casefold() in _PLACEHOLDER_TOKENS
    ):
        raise _ConfigError("invalid_bot_token", "telegram.bot_token is empty, oversized, or a placeholder")
    chat_id = _chat_id(telegram.get("chat_id"))
    telegram_timeout = _finite_number(telegram, "timeout_s", 10.0, 1.0, 60.0, prefix="telegram.")
    verify_ssl = telegram.get("verify_ssl", True)
    if type(verify_ssl) is not bool:
        raise _ConfigError("invalid_verify_ssl", "telegram.verify_ssl must be a boolean")

    canonical = {
        "schema": "periodic-png-config/v1",
        "interval_s": interval_s,
        "chart_window_s": chart_window_s,
        "include_channels": channels,
        "max_points_per_channel": per_channel,
        "max_total_points": total,
        "max_input_bytes": max_input_bytes,
        "render_timeout_s": render_timeout,
        "max_render_attempts": max_render_attempts,
        "max_delivery_attempts": max_delivery_attempts,
        "backoff_base_s": backoff_base,
        "backoff_cap_s": backoff_cap,
        "telegram_chat_id": chat_id,
        "telegram_timeout_s": telegram_timeout,
        "telegram_verify_ssl": verify_ssl,
    }
    fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return PeriodicPngConfig(
        enabled=True,
        interval_s=interval_s,
        chart_window_s=chart_window_s,
        include_channels=channels,
        max_points_per_channel=per_channel,
        max_total_points=total,
        max_input_bytes=max_input_bytes,
        render_timeout_s=render_timeout,
        max_render_attempts=max_render_attempts,
        max_delivery_attempts=max_delivery_attempts,
        backoff_base_s=backoff_base,
        backoff_cap_s=backoff_cap,
        telegram_token=SecretStr(raw_token),
        telegram_chat_id=chat_id,
        telegram_timeout_s=telegram_timeout,
        telegram_verify_ssl=verify_ssl,
        config_fingerprint=fingerprint,
    )


def _exact_int(
    mapping: dict[str, Any], field: str, default: int, minimum: int, maximum: int
) -> int:
    value = mapping.get(field, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise _ConfigError(f"invalid_{field}", f"{field} must be an integer in range")
    return value


def _finite_number(
    mapping: dict[str, Any],
    field: str,
    default: float,
    minimum: float,
    maximum: float,
    *,
    prefix: str = "",
) -> float:
    value = mapping.get(field, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ConfigError(f"invalid_{field}", f"{prefix}{field} must be a finite number in range")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise _ConfigError(
            f"invalid_{field}", f"{prefix}{field} must be a finite number in range"
        ) from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise _ConfigError(f"invalid_{field}", f"{prefix}{field} must be a finite number in range")
    return result


def _chart_window(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ConfigError("invalid_chart_hours", "chart_hours must be a finite number in range")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise _ConfigError(
            "invalid_chart_hours", "chart_hours must be a finite number in range"
        ) from None
    if not math.isfinite(number) or not (1 / 60) <= number <= 168:
        raise _ConfigError("invalid_chart_hours", "chart_hours must be a finite number in range")
    seconds = number * 3600.0
    integral = round(seconds)
    if not math.isclose(seconds, integral, rel_tol=0.0, abs_tol=1e-9):
        raise _ConfigError("invalid_chart_hours", "chart_hours must resolve to whole seconds")
    return integral


def _channels(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 64:
        raise _ConfigError("invalid_include_channels", "include_channels must contain 1 to 64 names")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _CHANNEL_NAME.search(item):
            raise _ConfigError("invalid_include_channels", "include_channels contains an invalid name")
        encoded = _utf8_bytes(
            item, "invalid_include_channels", "include_channels contains invalid UTF-8"
        )
        if len(encoded) > 256 or item in seen:
            raise _ConfigError("invalid_include_channels", "include_channels contains a duplicate or oversized name")
        seen.add(item)
        result.append(item)
    return tuple(sorted(result, key=_natural_key))


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    parts: list[tuple[int, object]] = []
    for part in _CHANNEL_NATURAL_PART.split(value):
        parts.append((0, int(part)) if part.isdigit() else (1, part.casefold()))
    return tuple(parts)


def _chat_id(value: object) -> int | str:
    if type(value) is int:
        if value == 0:
            raise _ConfigError("invalid_chat_id", "telegram.chat_id must identify one destination")
        return value
    if not isinstance(value, str) or not value:
        raise _ConfigError("invalid_chat_id", "telegram.chat_id must identify one destination")
    if len(_utf8_bytes(value, "invalid_chat_id", "telegram.chat_id is not valid UTF-8")) > 128:
        raise _ConfigError("invalid_chat_id", "telegram.chat_id must identify one destination")
    if _CANONICAL_DECIMAL.fullmatch(value):
        result = int(value)
        if result == 0:
            raise _ConfigError("invalid_chat_id", "telegram.chat_id must identify one destination")
        return result
    if _CHANNEL_DESTINATION.fullmatch(value):
        return value
    raise _ConfigError("invalid_chat_id", "telegram.chat_id is not canonical")


def _utf8_bytes(value: str, code: str, text: str) -> bytes:
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise _ConfigError(code, text) from None


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


def _stat_snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return identity and mutation-sensitive metadata for one open file."""

    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
