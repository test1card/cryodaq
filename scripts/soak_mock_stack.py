"""Fail-closed source-mode CryoDAQ mock-stack qualification contracts.

The reviewed Linux source path activates only the exact-clean-SHA ``short``
profile with the locked observer, non-network artifact capability, bounded
process ownership, and joined periodic-delivery receipts. Longer 12/72-hour
profiles, Windows/frozen execution, production alarm topology, and physical
hardware evidence remain separate open gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import wraps
from pathlib import Path
from statistics import median
from typing import Any, Protocol

if __name__ == "__main__":
    # Keep the runbook's ``python -m`` entry point and the runner's defensive
    # exact-type checks bound to one module instance.
    existing = sys.modules.get("scripts.soak_mock_stack")
    if existing is not None and existing is not sys.modules[__name__]:
        raise RuntimeError("canonical soak module is already loaded")
    sys.modules["scripts.soak_mock_stack"] = sys.modules[__name__]

SCHEMA = "cryodaq-mock-stack-soak/v1"
SAMPLE_INTERVAL_S = 5.0
MAX_CADENCE_GAP_S = 7.5
MAX_SLOPE_POINTS = 257
MAX_SLOPE_PAIRS = MAX_SLOPE_POINTS * (MAX_SLOPE_POINTS - 1) // 2
RECOVERY_CEILING_S = 60.0
SHUTDOWN_CEILING_S = 20.0
RSS_GROWTH_LIMIT_BYTES = 50 * 1024 * 1024
THREAD_DELTA_PER_ROLE = 4
ROLES = ("launcher", "engine", "bridge", "assistant")
EXACT_SIX_COMMAND = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
    "-q",
    "tests/integration/test_periodic_png_multiprocess.py",
)
EXACT_SIX_RESULT_SCHEMA = "cryodaq-exact-six-result/v1"
SOURCE_COMMAND_TAIL = ("-m", "cryodaq.launcher", "--mock", "--tray")
FAULT_SIGNAL = "SIGTERM"
FAULT_INJECTION_METHOD = "observer.signal_exact_identity/v1"
SUMMARY_RESERVED = frozenset({"schema", "status", "reason", "finished_at", "manifest_sha256"})
MANIFEST_RESERVED = frozenset({"schema"})


@dataclass(frozen=True, slots=True, order=True)
class ProcessIdentity:
    pid: int
    started_ns: int

    def __post_init__(self) -> None:
        if self.pid <= 0 or self.started_ns <= 0:
            raise ValueError("process identity values must be positive")


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    identity: ProcessIdentity
    parent_pid: int | None
    argv: tuple[str, ...]
    name: str
    rss_bytes: int
    threads: int
    descriptors: int | None
    running: bool = True

    def __post_init__(self) -> None:
        if self.parent_pid is not None and self.parent_pid <= 0:
            raise ValueError("parent_pid must be positive or None")
        if min(self.rss_bytes, self.threads) < 0:
            raise ValueError("resource counters must be non-negative")
        if self.descriptors is not None and self.descriptors < 0:
            raise ValueError("descriptor count must be non-negative")


@dataclass(frozen=True, slots=True)
class FaultEvent:
    target: str
    at_s: float

    def __post_init__(self) -> None:
        if self.target not in {"engine", "assistant"} or self.at_s <= 0:
            raise ValueError("invalid fault event")


@dataclass(frozen=True, slots=True)
class SoakProfile:
    name: str
    duration_s: float
    warmup_s: float
    events: tuple[FaultEvent, ...]
    rss_slope_limit_bytes_per_hour: float | None
    descriptor_slope_limit_per_hour: float | None
    recovery_descriptor_delta_per_process: int
    final_descriptor_delta_per_process: int
    recovery_descriptor_delta_aggregate: int
    thread_delta_per_role: int = THREAD_DELTA_PER_ROLE
    rss_growth_limit_bytes_per_role: int = RSS_GROWTH_LIMIT_BYTES


PROFILES: Mapping[str, SoakProfile] = {
    "short": SoakProfile(
        name="short",
        duration_s=15 * 60,
        warmup_s=3 * 60,
        # Sampling precedes injection.  180 s is the explicit healthy
        # baseline, and the first fault is one cadence later.
        events=(FaultEvent("engine", 185), FaultEvent("assistant", 300)),
        rss_slope_limit_bytes_per_hour=None,
        descriptor_slope_limit_per_hour=None,
        recovery_descriptor_delta_per_process=8,
        final_descriptor_delta_per_process=8,
        recovery_descriptor_delta_aggregate=16,
    ),
    "12h": SoakProfile(
        name="12h",
        duration_s=12 * 3600,
        warmup_s=10 * 60,
        events=tuple(
            FaultEvent(target, hour * 3600)
            for target, hour in (
                ("engine", 1),
                ("assistant", 2),
                ("engine", 4),
                ("assistant", 6),
                ("engine", 8),
                ("assistant", 10),
            )
        ),
        rss_slope_limit_bytes_per_hour=4 * 1024 * 1024,
        descriptor_slope_limit_per_hour=1.0,
        recovery_descriptor_delta_per_process=16,
        final_descriptor_delta_per_process=16,
        recovery_descriptor_delta_aggregate=64,
    ),
    "72h": SoakProfile(
        name="72h",
        duration_s=72 * 3600,
        warmup_s=10 * 60,
        events=tuple(
            FaultEvent(target, hour * 3600)
            for target, hour in (
                ("engine", 1),
                ("assistant", 2),
                ("engine", 12),
                ("assistant", 18),
                ("engine", 24),
                ("assistant", 36),
                ("engine", 48),
                ("assistant", 54),
                ("engine", 60),
                ("assistant", 66),
            )
        ),
        rss_slope_limit_bytes_per_hour=1 * 1024 * 1024,
        descriptor_slope_limit_per_hour=0.25,
        recovery_descriptor_delta_per_process=16,
        final_descriptor_delta_per_process=16,
        recovery_descriptor_delta_aggregate=64,
    ),
}


class ProcessObserver(Protocol):
    def snapshot(self) -> Sequence[ProcessSnapshot]: ...

    def signal(self, identity: ProcessIdentity, sig: int) -> None: ...


def profile(name: str) -> SoakProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile: {name}") from None


def descendants(snapshots: Sequence[ProcessSnapshot], root: ProcessIdentity) -> dict[ProcessIdentity, ProcessSnapshot]:
    """Return a live ancestry tree, requiring the root's exact start identity."""

    by_pid = {item.identity.pid: item for item in snapshots if item.running}
    root_snapshot = by_pid.get(root.pid)
    if root_snapshot is None or root_snapshot.identity != root:
        return {}
    owned = {root: root_snapshot}
    frontier = {root.pid}
    while frontier:
        next_frontier: set[int] = set()
        for item in by_pid.values():
            if item.identity in owned or item.parent_pid not in frontier:
                continue
            owned[item.identity] = item
            next_frontier.add(item.identity.pid)
        frontier = next_frontier
    return owned


def _module_after_dash_m(argv: tuple[str, ...]) -> str | None:
    try:
        index = argv.index("-m")
    except ValueError:
        return None
    return argv[index + 1] if index + 1 < len(argv) else None


def exact_process_role(argv: tuple[str, ...]) -> str | None:
    """Recognize only production source/frozen engine and assistant argv forms."""

    module = _module_after_dash_m(argv)
    modes = [arg.split("=", 1)[1] for arg in argv[1:] if arg.startswith("--mode=")]
    if (module == "cryodaq.engine" and not modes) or (module is None and modes == ["engine"]):
        return "engine"
    if (module == "cryodaq.agents.assistant_bootstrap" and not modes) or (module is None and modes == ["assistant"]):
        return "assistant"
    return None


def classify_tree(
    tree: Mapping[ProcessIdentity, ProcessSnapshot],
    root: ProcessIdentity,
    *,
    bridge_identity: ProcessIdentity | None,
) -> dict[str, ProcessIdentity]:
    """Classify the exact stack using a positive launcher-provided bridge identity.

    The current launcher exposes no bridge identity seam, so production runtime
    remains blocked.  Bridge-by-elimination is explicitly forbidden.
    """

    if root not in tree:
        raise ValueError("launcher identity is absent from observed tree")
    if bridge_identity is None:
        raise ValueError("positive bridge identity is unavailable")
    bridge = tree.get(bridge_identity)
    if bridge is None or bridge.parent_pid != root.pid:
        raise ValueError("positive bridge identity is not a direct launcher child")
    if exact_process_role(bridge.argv) is not None:
        raise ValueError("positive bridge identity collides with an engine/assistant role")
    result = {"launcher": root, "bridge": bridge_identity}
    for identity, item in tree.items():
        if identity in {root, bridge_identity}:
            continue
        role = exact_process_role(item.argv)
        if role is None:
            raise ValueError("unclassified descendant process")
        if role in result:
            raise ValueError(f"duplicate live {role} process")
        result[role] = identity
    missing = set(ROLES) - result.keys()
    if missing:
        raise ValueError(f"missing required process roles: {sorted(missing)}")
    return result


def identity_is_live(snapshots: Sequence[ProcessSnapshot], identity: ProcessIdentity) -> bool:
    return any(item.running and item.identity == identity for item in snapshots)


def surviving_recorded_identities(
    snapshots: Sequence[ProcessSnapshot], observed: set[ProcessIdentity]
) -> set[ProcessIdentity]:
    """Check exact identities globally after root exit, catching reparenting."""

    live = {item.identity for item in snapshots if item.running}
    return observed & live


def assert_replacement(
    old: ProcessIdentity,
    current: ProcessIdentity,
    *,
    ready: bool,
    newer_health: bool = True,
) -> None:
    if old == current:
        raise AssertionError("recovery reused the old PID/start identity")
    if not ready:
        raise AssertionError("replacement process is not ready")
    if not newer_health:
        raise AssertionError("assistant recovery lacks a newer H3 health heartbeat")


def stack_sample(
    elapsed_s: float,
    role_snapshots: Mapping[str, tuple[int, ProcessSnapshot]],
    *,
    wall_time: str = "2026-01-01T00:00:00+00:00",
) -> dict[str, Any]:
    if set(role_snapshots) != set(ROLES):
        raise ValueError("sample must contain the exact four stack roles")
    roles: dict[str, Any] = {}
    for role in ROLES:
        epoch, item = role_snapshots[role]
        roles[role] = {
            "pid": item.identity.pid,
            "started_ns": item.identity.started_ns,
            "epoch": epoch,
            "rss_bytes": item.rss_bytes,
            "threads": item.threads,
            "descriptors": item.descriptors,
        }
    return {"elapsed_s": elapsed_s, "wall_time": wall_time, "roles": roles}


def aggregate_sample(sample: Mapping[str, Any]) -> dict[str, Any]:
    roles = sample["roles"]
    descriptors = [roles[role]["descriptors"] for role in ROLES]
    return {
        "elapsed_s": sample["elapsed_s"],
        "process_count": len(roles),
        "rss_bytes": sum(roles[role]["rss_bytes"] for role in ROLES),
        "threads": sum(roles[role]["threads"] for role in ROLES),
        "descriptors": None if any(value is None for value in descriptors) else sum(descriptors),
    }


def bounded_slope_points(
    points: Sequence[tuple[float, float]], max_points: int = MAX_SLOPE_POINTS
) -> list[tuple[float, float]]:
    """Deterministically retain evenly spaced points, including both ends."""

    if max_points < 2:
        raise ValueError("max_points must be at least two")
    if len(points) <= max_points:
        return list(points)
    last = len(points) - 1
    indices = [(index * last) // (max_points - 1) for index in range(max_points)]
    return [points[index] for index in indices]


def robust_slope(points: Sequence[tuple[float, float]]) -> float:
    """Bounded deterministic median-pairwise slope in units per hour."""

    bounded = bounded_slope_points(points)
    slopes = [
        (value_b - value_a) / (time_b - time_a) * 3600.0
        for index, (time_a, value_a) in enumerate(bounded)
        for time_b, value_b in bounded[index + 1 :]
        if time_b > time_a
    ]
    if not slopes:
        return 0.0
    return float(median(slopes))


def fitted_growth(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return robust_slope(points) * (points[-1][0] - points[0][0]) / 3600.0


def _finite_nonnegative(value: Any) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(normalized) and normalized >= 0


def _exact_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _exact_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def validate_sample_series(samples: Sequence[Mapping[str, Any]], soak_profile: SoakProfile) -> list[str]:
    errors: list[str] = []
    if len(samples) < 2:
        return ["insufficient samples"]
    previous: float | None = None
    epoch_identities: dict[tuple[str, int], tuple[int, int]] = {}
    identity_epochs: dict[tuple[str, tuple[int, int]], set[int]] = {}
    prior_epochs: dict[str, int] = {}
    for index, sample in enumerate(samples):
        if set(sample) != {"elapsed_s", "wall_time", "roles"}:
            errors.append(f"sample {index} fields are not exact")
        elapsed = sample.get("elapsed_s")
        if not _finite_nonnegative(elapsed):
            errors.append(f"sample {index} has invalid elapsed_s")
            continue
        elapsed = float(elapsed)
        if previous is not None:
            if elapsed <= previous:
                errors.append(f"sample {index} is not strictly monotonic")
            elif elapsed - previous > MAX_CADENCE_GAP_S:
                errors.append(f"sample {index} exceeds cadence gap")
        previous = elapsed
        roles = sample.get("roles")
        if not isinstance(roles, Mapping) or set(roles) != set(ROLES):
            errors.append(f"sample {index} lacks exact stack roles")
            continue
        for role in ROLES:
            record = roles[role]
            required = {"pid", "started_ns", "epoch", "rss_bytes", "threads", "descriptors"}
            if not isinstance(record, Mapping) or set(record) != required:
                errors.append(f"sample {index} {role} schema is incomplete")
                continue
            for field in ("pid", "started_ns", "epoch", "rss_bytes", "threads", "descriptors"):
                if not _finite_nonnegative(record[field]):
                    errors.append(f"sample {index} {role} has invalid {field}")
                if not _exact_nonnegative_int(record[field]):
                    errors.append(f"sample {index} {role} has non-integer {field}")
            if _finite_nonnegative(record["pid"]) and int(record["pid"]) == 0:
                errors.append(f"sample {index} {role} has invalid pid")
            if _finite_nonnegative(record["started_ns"]) and int(record["started_ns"]) == 0:
                errors.append(f"sample {index} {role} has invalid started_ns")
            if all(_finite_nonnegative(record[field]) for field in ("pid", "started_ns", "epoch")):
                epoch = int(record["epoch"])
                identity = (int(record["pid"]), int(record["started_ns"]))
                prior = epoch_identities.setdefault((role, epoch), identity)
                if prior != identity:
                    errors.append(f"sample {index} {role} identity changed within epoch")
                identity_epochs.setdefault((role, identity), set()).add(epoch)
                prior_epoch = prior_epochs.setdefault(role, epoch)
                if epoch < prior_epoch or epoch > prior_epoch + 1:
                    errors.append(f"sample {index} {role} epoch transition is invalid")
                prior_epochs[role] = epoch
        wall_time = sample.get("wall_time")
        try:
            parsed_wall = datetime.fromisoformat(str(wall_time))
            if parsed_wall.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append(f"sample {index} has invalid wall_time")
    first = samples[0].get("elapsed_s")
    last = samples[-1].get("elapsed_s")
    if _finite_nonnegative(first) and float(first) > SAMPLE_INTERVAL_S:
        errors.append("series does not cover startup")
    if _finite_nonnegative(last) and float(last) < soak_profile.duration_s - SAMPLE_INTERVAL_S:
        errors.append("series does not cover profile duration")
    for (role, _identity), epochs in identity_epochs.items():
        if len(epochs) > 1:
            errors.append(f"{role} reused one identity across restart epochs")
    return errors


def evaluate_resources(samples: Sequence[Mapping[str, Any]], soak_profile: SoakProfile) -> list[str]:
    errors = validate_sample_series(samples, soak_profile)
    if errors:
        return errors
    post = [item for item in samples if float(item["elapsed_s"]) >= soak_profile.warmup_s]
    if len(post) < 2:
        return ["insufficient post-warm-up samples"]
    aggregates = [aggregate_sample(item) for item in post]
    rss_points = [(float(item["elapsed_s"]), float(item["rss_bytes"])) for item in aggregates]
    if fitted_growth(rss_points) >= RSS_GROWTH_LIMIT_BYTES:
        errors.append("aggregate RSS fitted growth reached 50 MiB")
    if (
        soak_profile.rss_slope_limit_bytes_per_hour is not None
        and robust_slope(rss_points) >= soak_profile.rss_slope_limit_bytes_per_hour
    ):
        errors.append("aggregate RSS slope exceeded profile limit")
    descriptor_points = [(float(item["elapsed_s"]), float(item["descriptors"])) for item in aggregates]
    if (
        soak_profile.descriptor_slope_limit_per_hour is not None
        and robust_slope(descriptor_points) > soak_profile.descriptor_slope_limit_per_hour
    ):
        errors.append("aggregate descriptor slope exceeded profile limit")
    if descriptor_points[-1][1] > (descriptor_points[0][1] + soak_profile.recovery_descriptor_delta_aggregate):
        errors.append("aggregate final descriptor count exceeded profile envelope")
    if max(value for _, value in descriptor_points) > (
        descriptor_points[0][1] + soak_profile.recovery_descriptor_delta_aggregate
    ):
        errors.append("aggregate recovery descriptor count exceeded profile envelope")

    for role in ROLES:
        by_epoch: dict[int, list[tuple[float, Mapping[str, Any]]]] = {}
        for item in post:
            record = item["roles"][role]
            by_epoch.setdefault(int(record["epoch"]), []).append((float(item["elapsed_s"]), record))
        epochs = sorted(by_epoch)
        if epochs != list(range(epochs[-1] + 1)):
            errors.append(f"{role} epoch sequence is not contiguous from zero")
        first_record = by_epoch[epochs[0]][0][1]
        final_record = by_epoch[epochs[-1]][-1][1]
        full_descriptor_points = [
            (float(item["elapsed_s"]), float(item["roles"][role]["descriptors"])) for item in post
        ]
        if (
            soak_profile.descriptor_slope_limit_per_hour is not None
            and robust_slope(full_descriptor_points) > soak_profile.descriptor_slope_limit_per_hour
        ):
            errors.append(f"{role} descriptor slope exceeded profile limit")
        if int(final_record["descriptors"]) > (
            int(first_record["descriptors"]) + soak_profile.final_descriptor_delta_per_process
        ):
            errors.append(f"{role} final descriptor count exceeded envelope")
        if int(final_record["threads"]) > (int(first_record["threads"]) + soak_profile.thread_delta_per_role):
            errors.append(f"{role} final thread count exceeded envelope")
        if float(final_record["rss_bytes"]) - float(first_record["rss_bytes"]) >= (
            soak_profile.rss_growth_limit_bytes_per_role
        ):
            errors.append(f"{role} final RSS growth reached 50 MiB")
        for epoch, rows in by_epoch.items():
            start = rows[0][1]
            end = rows[-1][1]
            if int(end["descriptors"]) > (
                int(start["descriptors"]) + soak_profile.recovery_descriptor_delta_per_process
            ):
                errors.append(f"{role} epoch {epoch} descriptor count exceeded envelope")
            if int(end["threads"]) > int(start["threads"]) + soak_profile.thread_delta_per_role:
                errors.append(f"{role} epoch {epoch} thread count exceeded envelope")
            role_rss = [(elapsed, float(record["rss_bytes"])) for elapsed, record in rows]
            role_descriptors = [(elapsed, float(record["descriptors"])) for elapsed, record in rows]
            if (
                soak_profile.descriptor_slope_limit_per_hour is not None
                and robust_slope(role_descriptors) > soak_profile.descriptor_slope_limit_per_hour
            ):
                errors.append(f"{role} epoch {epoch} descriptor slope exceeded profile limit")
            if (
                fitted_growth(role_rss) >= soak_profile.rss_growth_limit_bytes_per_role
                or role_rss[-1][1] - role_rss[0][1] >= soak_profile.rss_growth_limit_bytes_per_role
            ):
                errors.append(f"{role} epoch {epoch} RSS growth reached 50 MiB")
            if (
                soak_profile.rss_slope_limit_bytes_per_hour is not None
                and robust_slope(role_rss) >= soak_profile.rss_slope_limit_bytes_per_hour
            ):
                errors.append(f"{role} epoch {epoch} RSS slope exceeded profile limit")
        for previous_epoch, current_epoch in zip(epochs, epochs[1:]):
            previous_baseline = by_epoch[previous_epoch][0][1]
            recovered = by_epoch[current_epoch][0][1]
            if int(recovered["descriptors"]) > (
                int(previous_baseline["descriptors"]) + soak_profile.recovery_descriptor_delta_per_process
            ):
                errors.append(f"{role} epoch {current_epoch} recovery descriptors exceeded envelope")
            if int(recovered["threads"]) > (int(previous_baseline["threads"]) + soak_profile.thread_delta_per_role):
                errors.append(f"{role} epoch {current_epoch} recovery threads exceeded envelope")
            if float(recovered["rss_bytes"]) - float(previous_baseline["rss_bytes"]) >= (
                soak_profile.rss_growth_limit_bytes_per_role
            ):
                errors.append(f"{role} epoch {current_epoch} recovery RSS reached 50 MiB")
    return errors


_LEVEL_LINE = re.compile(r"(?:^|\s|│)(ERROR|CRITICAL)(?:\s|│|$)")


def log_violations(text: str, allowlist: Sequence[str] = ()) -> list[str]:
    allowed = [re.compile(pattern) for pattern in allowlist]
    return [
        line
        for line in text.splitlines()
        if (_LEVEL_LINE.search(line) or line.startswith("Traceback (most recent call last):"))
        and not any(pattern.search(line) for pattern in allowed)
    ]


_SECRET_KEYS = re.compile(r"token|secret|password|credential|api[_-]?key", re.IGNORECASE)
_BOT_TOKEN = re.compile(r"[1-9][0-9]{5,19}:[A-Za-z0-9_-]{20,256}")
_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)")
_QUERY_SECRET = re.compile(r"(?i)([?&](?:token|secret|password|api[_-]?key)=)([^&#\s]+)")
_ASSIGNMENT_SECRET = re.compile(r"(?i)(\b(?:token|secret|password|credential|api[_-]?key)\s*[=:]\s*)([^\s,;]+)")
_SECRET_OPTIONS = frozenset({"--token", "--secret", "--password", "--credential", "--api-key", "--api_key"})
_SECRET_DETECTORS = (
    _BOT_TOKEN,
    re.compile(r"(?i)authorization\s*:\s*bearer\s+(?!<redacted>)[^\s,;]+"),
    re.compile(r"(?i)[?&](?:token|secret|password|api[_-]?key)=(?!<redacted>)[^&#\s]+"),
    re.compile(r"(?i)\b(?:token|secret|password|credential|api[_-]?key)\s*[=:]\s*(?!<redacted>)[^\s,;]+"),
    re.compile(r"(?i)--(?:token|secret|password|credential|api[-_]?key)\s+(?!<redacted>)[^\s,;]+"),
)


def _has_forbidden_capture_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in {"env", "environment", "environ"}:
                return True
            if _has_forbidden_capture_key(item):
                return True
    elif isinstance(value, list | tuple):
        return any(_has_forbidden_capture_key(item) for item in value)
    return False


def redact_text(value: str) -> str:
    value = _BOT_TOKEN.sub("<redacted-token>", value)
    value = _BEARER.sub(r"\1<redacted>", value)
    value = _QUERY_SECRET.sub(r"\1<redacted>", value)
    return _ASSIGNMENT_SECRET.sub(r"\1<redacted>", value)


def scrub_command(argv: Sequence[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for argument in argv:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        normalized = argument.casefold()
        if normalized in _SECRET_OPTIONS:
            result.append(argument)
            redact_next = True
            continue
        result.append(redact_text(argument))
    return result


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _SECRET_KEYS.search(str(key)) else redact(item) for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


def _validate_bounded_json(value: Any, *, path: str = "evidence", depth: int = 0) -> None:
    if depth > 32:
        raise ValueError(f"{path} nesting is excessive")
    if value is None or isinstance(value, bool | str):
        return
    if type(value) is int:
        if abs(value) > 2**63 - 1:
            raise ValueError(f"{path} integer exceeds bounded evidence range")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} number must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} keys must be strings")
            _validate_bounded_json(item, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_bounded_json(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    raise ValueError(f"{path} contains a non-JSON value")


def _validate_stream_record(name: str, payload: Any) -> None:
    _validate_bounded_json(payload, path=name)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} record must be an object")
    if name == "samples.jsonl":
        if set(payload) != {"elapsed_s", "wall_time", "roles"}:
            raise ValueError("sample fields are not exact")
        roles = payload.get("roles")
        if not isinstance(roles, Mapping) or set(roles) != set(ROLES):
            raise ValueError("sample lacks exact stack roles")
    elif name == "faults.jsonl":
        expected = {
            "target",
            "scheduled_s",
            "observed_s",
            "pre_pid",
            "pre_started_ns",
            "recheck_pid",
            "recheck_started_ns",
            "replacement_pid",
            "replacement_started_ns",
            "ready",
            "recovery_s",
            "bridge_data_resumed",
            "newer_h3_health",
            "signal",
            "injection_method",
        }
        if set(payload) != expected:
            raise ValueError("fault fields are not exact")


def _flat_basename(name: str) -> str:
    if name in {"", ".", ".."} or Path(name).name != name:
        raise ValueError("artifact path must be one flat basename")
    return name


def _read_owned_regular_at(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    """Read one flat artifact without following links or accepting replacement.

    The opened descriptor is the authority.  Device/inode, size and mtime must
    remain continuous from the no-follow topology check through EOF and the
    final pathname check.
    """

    name = _flat_basename(name)
    file_fd: int | None = None
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("artifact is not a regular file")
        file_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ValueError("artifact changed before no-follow open")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_fd)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        continuity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != continuity or (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        ) != continuity:
            raise ValueError("artifact changed during no-follow read")
        return b"".join(chunks), opened
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _read_owned_regular(path: Path) -> tuple[bytes, os.stat_result]:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(path.parent, directory_flags)
    try:
        return _read_owned_regular_at(directory_fd, path.name)
    finally:
        os.close(directory_fd)


def _read_owned_text(path: Path, *, errors: str = "strict") -> str:
    payload, _identity = _read_owned_regular(path)
    return payload.decode("utf-8", errors=errors)


def _read_owned_text_at(directory_fd: int, name: str, *, errors: str = "strict") -> str:
    payload, _identity = _read_owned_regular_at(directory_fd, name)
    return payload.decode("utf-8", errors=errors)


def _unlink_owned(path: Path) -> None:
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.unlink(path.name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def _append_owned(path: Path, payload: bytes) -> None:
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        _append_owned_at(directory_fd, path.name, payload)
    finally:
        os.close(directory_fd)


def _append_owned_at(directory_fd: int, name: str, payload: bytes) -> None:
    name = _flat_basename(name)
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise ValueError("typed stream is not a regular file")
        view = memoryview(payload)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("short typed-stream write")
            view = view[written:]
        os.fsync(file_fd)
    finally:
        if file_fd is not None:
            os.close(file_fd)


def secret_findings(directory: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.name == "summary.json":
            continue
        try:
            text = _read_owned_text(path, errors="replace")
        except (OSError, ValueError):
            findings.append(f"{path.name}:unsafe_artifact")
            continue
        for detector in _SECRET_DETECTORS:
            if detector.search(text):
                findings.append(f"{path.name}:{detector.pattern}")
    return findings


def _atomic_bytes_at(directory_fd: int, name: str, payload: bytes, *, replace: bool = True) -> None:
    name = _flat_basename(name)
    temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
    fd: int | None = None
    try:
        fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short atomic artifact write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        if replace:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        else:
            os.link(
                temporary_name,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        os.fsync(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _atomic_json_at(
    directory_fd: int,
    name: str,
    payload: Mapping[str, Any],
    *,
    replace: bool = True,
) -> None:
    encoded = (json.dumps(redact(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    _atomic_bytes_at(directory_fd, name, encoded, replace=replace)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write standalone test/setup JSON without following its parent basename."""

    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        _atomic_json_at(directory_fd, path.name, payload)
    finally:
        os.close(directory_fd)


def _remove_entry_at(directory_fd: int, name: str) -> None:
    """Recursively remove one owned entry without resolving the root path."""

    name = _flat_basename(name)
    identity = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISDIR(identity.st_mode):
        os.unlink(name, dir_fd=directory_fd)
        return
    child_fd = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        for child in os.listdir(child_fd):
            _remove_entry_at(child_fd, child)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=directory_fd)


class RunState(StrEnum):
    INITIAL_FAIL = "INITIAL_FAIL"
    MANIFEST_FINALIZED = "MANIFEST_FINALIZED"
    PREREQUISITES_VERIFIED = "PREREQUISITES_VERIFIED"
    RUNNING = "RUNNING"
    SHUTDOWN_VERIFIED = "SHUTDOWN_VERIFIED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    VALIDATED = "VALIDATED"
    PASS = "PASS"
    FAIL = "FAIL"


class EvidenceUnavailableError(RuntimeError):
    """The evidence capability is explicitly closed and cannot perform I/O."""


class EvidenceCapabilityError(ValueError):
    """The pinned directory capability was lost; no terminal write is safe."""


_PERIODIC_DELIVERY_RECORD_FIELDS = {
    "assistant_pid",
    "assistant_start_identity",
    "assistant_generation",
    "sequence",
    "receipt_id",
    "artifact_sha256",
    "artifact_name",
    "acknowledgement_sha256",
    "ledger_record_sha256",
    "destination_fingerprint",
    "state_updated_at",
    "health_updated_at",
}


def _validate_periodic_delivery_payload(
    payload: object,
    receipts: Sequence[object],
    *,
    ledger_validator: Callable[[dict[str, object]], bool],
) -> tuple[list[str], tuple[str, ...]]:
    """Revalidate the runner-issued result and its exact two ledger records."""

    errors: list[str] = []
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "status", "pre_fault", "post_fault"}
        or payload.get("schema") != "cryodaq-soak-periodic-delivery-result/v1"
        or payload.get("status") != "PASS"
        or len(receipts) != 2
    ):
        return ["periodic-delivery result schema is invalid"], ()
    result_records = (payload.get("pre_fault"), payload.get("post_fault"))
    artifact_names: list[str] = []
    identities: list[tuple[int, str]] = []
    destinations: list[str] = []
    state_times: list[float] = []
    health_times: list[float] = []
    for index, (result, receipt) in enumerate(zip(result_records, receipts, strict=True), start=1):
        label = "pre_fault" if index == 1 else "post_fault"
        if type(result) is not dict or set(result) != _PERIODIC_DELIVERY_RECORD_FIELDS:
            errors.append(f"periodic-delivery {label} record schema is invalid")
            continue
        if type(receipt) is not dict or not ledger_validator(receipt):
            errors.append(f"periodic-delivery {label} ledger record is invalid")
            continue
        generation = result.get("assistant_generation")
        sequence = result.get("sequence")
        artifact_sha = result.get("artifact_sha256")
        artifact_name = result.get("artifact_name")
        pid = result.get("assistant_pid")
        start_identity = result.get("assistant_start_identity")
        state_updated = result.get("state_updated_at")
        health_updated = result.get("health_updated_at")
        destination = result.get("destination_fingerprint")
        try:
            start_identity_bytes = start_identity.encode("utf-8") if isinstance(start_identity, str) else b""
        except UnicodeEncodeError:
            start_identity_bytes = b""
        expected_name = (
            f"periodic-g{generation}-s{sequence}-{str(artifact_sha)[7:]}.png"
            if type(generation) is int and type(sequence) is int and isinstance(artifact_sha, str)
            else ""
        )
        ledger_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
            ).hexdigest()
        )
        if (
            generation != index
            or type(generation) is not int
            or sequence != 1
            or type(sequence) is not int
            or result.get("receipt_id") != f"g{index}:s1"
            or type(pid) is not int
            or pid <= 0
            or not isinstance(start_identity, str)
            or not start_identity
            or not start_identity_bytes
            or len(start_identity_bytes) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in start_identity)
            or not isinstance(artifact_sha, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_sha) is None
            or artifact_name != expected_name
            or not isinstance(artifact_name, str)
            or _flat_basename(artifact_name) != artifact_name
            or result.get("acknowledgement_sha256") != receipt.get("acknowledgement_sha256")
            or result.get("ledger_record_sha256") != ledger_hash
            or not isinstance(destination, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", destination) is None
            or type(state_updated) not in {int, float}
            or not math.isfinite(float(state_updated))
            or type(health_updated) not in {int, float}
            or not math.isfinite(float(health_updated))
            or float(health_updated) < float(state_updated)
        ):
            errors.append(f"periodic-delivery {label} result semantics are invalid")
            continue
        projected = {
            "assistant_pid": receipt["assistant_pid"],
            "assistant_start_identity": receipt["assistant_start_identity"],
            "assistant_generation": receipt["assistant_generation"],
            "sequence": receipt["sequence"],
            "receipt_id": receipt["receipt_id"],
            "artifact_sha256": receipt["artifact_sha256"],
            "artifact_name": receipt["filename"],
            "acknowledgement_sha256": receipt["acknowledgement_sha256"],
        }
        if any(result.get(field) != value for field, value in projected.items()):
            errors.append(f"periodic-delivery {label} result differs from its ledger record")
            continue
        artifact_names.append(artifact_name)
        identities.append((pid, start_identity))
        destinations.append(destination)
        state_times.append(float(state_updated))
        health_times.append(float(health_updated))
    if len(artifact_names) == 2:
        if len(set(artifact_names)) != 2:
            errors.append("periodic-delivery artifacts are not distinct")
        if identities[0] == identities[1]:
            errors.append("periodic-delivery assistant identity did not change")
        if destinations[0] != destinations[1]:
            errors.append("periodic-delivery destination changed")
        if state_times[1] <= state_times[0] or health_times[1] <= health_times[0]:
            errors.append("periodic-delivery post-fault cut is not newer")
    return errors, tuple(artifact_names)


def _validate_source_fixture(payload: object) -> list[str]:
    expected_files = {
        "agent.yaml",
        "alarms_v3.yaml",
        "channel_descriptors.yaml",
        "channels.yaml",
        "cooldown.yaml",
        "housekeeping.yaml",
        "instruments.yaml",
        "interlocks.yaml",
        "notifications.yaml",
        "physical_alarms.yaml",
        "plugins.yaml",
        "safety.yaml",
    }
    expected_top = {
        "schema",
        "instrument_id",
        "authority",
        "mock",
        "descriptor_count",
        "binding_count",
        "expected_readings_per_sample",
        "entries",
        "tree_sha256",
    }
    if type(payload) is not dict or set(payload) != expected_top:
        return ["source fixture schema is invalid"]
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != len(expected_files) + 1:
        return ["source fixture entries are invalid"]
    paths: list[str] = []
    for entry in entries:
        if type(entry) is not dict or not isinstance(entry.get("path"), str):
            return ["source fixture entry schema is invalid"]
        path = entry["path"]
        paths.append(path)
        if path == "experiment_templates":
            if entry != {"path": path, "kind": "directory"}:
                return ["source fixture directory entry is invalid"]
        elif (
            path not in expected_files
            or set(entry) != {"path", "kind", "bytes", "sha256"}
            or entry.get("kind") != "file"
            or type(entry.get("bytes")) is not int
            or entry["bytes"] < 0
            or not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", entry["sha256"]) is None
        ):
            return ["source fixture file entry is invalid"]
    canonical_entries = sorted(entries, key=lambda item: item["path"])
    expected_tree = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(canonical_entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
    )
    if (
        paths != sorted(paths)
        or set(paths) != expected_files | {"experiment_templates"}
        or payload.get("schema") != "cryodaq-soak-source-fixture/v1"
        or payload.get("instrument_id") != "LS218_1"
        or payload.get("authority") != "passive_measurement"
        or payload.get("mock") is not True
        or payload.get("descriptor_count") != 16
        or type(payload.get("descriptor_count")) is not int
        or payload.get("binding_count") != 16
        or type(payload.get("binding_count")) is not int
        or payload.get("expected_readings_per_sample") != 8
        or type(payload.get("expected_readings_per_sample")) is not int
        or payload.get("tree_sha256") != expected_tree
    ):
        return ["source fixture semantics or tree seal is invalid"]
    return []


@dataclass(frozen=True, slots=True)
class RunIdentity:
    schema: str
    profile: str
    git_sha: str
    dirty: bool
    platform: str
    python: str
    source_command: tuple[str, ...]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PrerequisiteLedger:
    exact_six_command: tuple[str, ...]
    exact_six_git_sha: str
    exact_six_exit_code: int
    exact_six_status: str
    exact_six_result_artifact: str
    exact_six_result_sha256: str
    observer_identity: str
    observer_version: str
    local_publisher_identity: str
    bridge_capability: str


@dataclass(frozen=True, slots=True)
class SampleLedger:
    artifact: str
    sha256: str
    count: int
    validation: str


@dataclass(frozen=True, slots=True)
class FaultLedger:
    artifact: str
    sha256: str
    count: int
    validation: str


@dataclass(frozen=True, slots=True)
class LogLedger:
    artifacts: tuple[str, ...]
    allowlist_sha256: str
    validation: str


@dataclass(frozen=True, slots=True)
class ShutdownLedger:
    graceful_requested: bool
    launcher_exited: bool
    elapsed_s: float
    observed_identity_count: int
    survivor_count: int


@dataclass(frozen=True, slots=True)
class SecrecyLedger:
    capture_schema: str
    validation: str
    retained_finding_count: int
    quarantines: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PeriodicDeliveryLedger:
    artifact: str
    sha256: str
    receipt_ledger: str
    receipt_count: int
    validation: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    name: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AcceptanceLedger:
    run: RunIdentity
    prerequisites: PrerequisiteLedger
    samples: SampleLedger
    faults: FaultLedger
    logs: LogLedger
    shutdown: ShutdownLedger
    secrecy: SecrecyLedger
    periodic_delivery: PeriodicDeliveryLedger
    artifacts: tuple[ArtifactRecord, ...]

    def payload(self) -> dict[str, Any]:
        # Canonical JSON shape: tuples become arrays before sealing/comparison.
        return json.loads(json.dumps(asdict(self), sort_keys=True))


def _sha256(path: Path) -> str:
    payload, _identity = _read_owned_regular(path)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_lines(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line in _read_owned_text(path).splitlines():
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise ValueError(f"{path.name} contains a non-object record")
        rows.append(value)
    return rows


def _exact_keys(payload: Mapping[str, Any], expected: set[str], label: str) -> list[str]:
    if not isinstance(payload, Mapping):
        return [f"{label} is not an object"]
    return [] if set(payload) == expected else [f"{label} fields are not exact"]


def _validate_prerequisite_payload(payload: Mapping[str, Any], git_sha: str) -> list[str]:
    errors = _exact_keys(
        payload,
        {"exact_six", "observer", "local_publisher", "bridge_identity"},
        "prerequisites",
    )
    if not isinstance(payload, Mapping):
        return errors
    try:
        exact = payload["exact_six"]
        observer = payload["observer"]
        publisher = payload["local_publisher"]
        bridge = payload["bridge_identity"]
        if not all(isinstance(item, Mapping) for item in (exact, observer, publisher, bridge)):
            errors.append("prerequisite nested schemas must be objects")
            return errors
        errors += _exact_keys(
            exact,
            {"command", "git_sha", "exit_code", "status", "result_artifact", "result_sha256"},
            "exact_six",
        )
        errors += _exact_keys(observer, {"identity", "version", "locked"}, "observer")
        errors += _exact_keys(publisher, {"identity", "reviewed", "transport"}, "publisher")
        errors += _exact_keys(bridge, {"capability", "positive"}, "bridge")
        command = exact["command"]
        if command != list(EXACT_SIX_COMMAND):
            errors.append("exact-six command is not the canonical test command")
        if (
            exact["git_sha"] != git_sha
            or re.fullmatch(r"[0-9a-f]{40}", str(exact["git_sha"])) is None
            or type(exact["exit_code"]) is not int
            or exact["exit_code"] != 0
            or exact["status"] != "PASS"
        ):
            errors.append("exact-six prerequisite is not a same-SHA PASS")
        if exact.get("result_artifact") != "exact-six-result.json":
            errors.append("exact-six result artifact identity is invalid")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(exact.get("result_sha256"))) is None:
            errors.append("exact-six result artifact hash is invalid")
        for label, value in (
            ("observer identity", observer["identity"]),
            ("observer version", observer["version"]),
            ("local publisher identity", publisher["identity"]),
            ("bridge capability", bridge["capability"]),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label} is invalid")
        if type(observer["locked"]) is not bool or not observer["locked"]:
            errors.append("process observer is not locked")
        if type(publisher["reviewed"]) is not bool or not publisher["reviewed"]:
            errors.append("local publisher is not reviewed")
        if publisher["transport"] != "local-only":
            errors.append("publisher transport is not local-only")
        if type(bridge["positive"]) is not bool or not bridge["positive"]:
            errors.append("bridge identity capability is not positive")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("prerequisite schema is incomplete")
    return errors


def _validate_exact_six_result(payload: Mapping[str, Any], git_sha: str) -> list[str]:
    errors = _exact_keys(
        payload,
        {"schema", "command", "test_identity", "git_sha", "exit_code", "status"},
        "exact-six result",
    )
    if not isinstance(payload, Mapping):
        return errors
    if payload.get("schema") != EXACT_SIX_RESULT_SCHEMA:
        errors.append("exact-six result schema is invalid")
    if payload.get("command") != list(EXACT_SIX_COMMAND):
        errors.append("exact-six result command is not canonical")
    if payload.get("test_identity") != "tests/integration/test_periodic_png_multiprocess.py::exact-six":
        errors.append("exact-six result test identity is invalid")
    if (
        payload.get("git_sha") != git_sha
        or payload.get("exit_code") != 0
        or type(payload.get("exit_code")) is not int
        or payload.get("status") != "PASS"
    ):
        errors.append("exact-six result is not a same-SHA PASS")
    return errors


def _validate_faults(
    records: Sequence[Mapping[str, Any]], selected: SoakProfile, samples: Sequence[Mapping[str, Any]]
) -> list[str]:
    expected_fields = {
        "target",
        "scheduled_s",
        "observed_s",
        "pre_pid",
        "pre_started_ns",
        "recheck_pid",
        "recheck_started_ns",
        "replacement_pid",
        "replacement_started_ns",
        "ready",
        "recovery_s",
        "bridge_data_resumed",
        "newer_h3_health",
        "signal",
        "injection_method",
    }
    errors: list[str] = []
    expected = [(event.target, float(event.at_s)) for event in selected.events]
    observed: list[tuple[str, float]] = []
    for index, record in enumerate(records):
        errors += _exact_keys(record, expected_fields, f"fault {index}")
        try:
            target = str(record["target"])
            scheduled = float(record["scheduled_s"])
            observed.append((target, scheduled))
            observed_s = float(record["observed_s"])
            if record["signal"] != FAULT_SIGNAL or record["injection_method"] != FAULT_INJECTION_METHOD:
                errors.append(f"fault {index} injection contract is invalid")
            if not math.isfinite(scheduled) or scheduled <= 0:
                errors.append(f"fault {index} scheduled time is invalid")
            if not math.isfinite(observed_s) or observed_s < 0:
                errors.append(f"fault {index} observed time is invalid")
            elif abs(observed_s - scheduled) > SAMPLE_INTERVAL_S:
                errors.append(f"fault {index} exceeded schedule tolerance")
            for field in (
                "pre_pid",
                "pre_started_ns",
                "recheck_pid",
                "recheck_started_ns",
                "replacement_pid",
                "replacement_started_ns",
            ):
                if not _exact_positive_int(record[field]):
                    errors.append(f"fault {index} {field} is not a positive integer")
            if (record["pre_pid"], record["pre_started_ns"]) != (
                record["recheck_pid"],
                record["recheck_started_ns"],
            ):
                errors.append(f"fault {index} failed immediate identity recheck")
            if (record["pre_pid"], record["pre_started_ns"]) == (
                record["replacement_pid"],
                record["replacement_started_ns"],
            ):
                errors.append(f"fault {index} replacement identity did not change")
            if type(record["ready"]) is not bool or not record["ready"]:
                errors.append(f"fault {index} replacement was not ready")
            if not _finite_nonnegative(record["recovery_s"]) or float(record["recovery_s"]) > RECOVERY_CEILING_S:
                errors.append(f"fault {index} recovery exceeded ceiling")
            if target == "engine" and not record["bridge_data_resumed"]:
                errors.append(f"fault {index} lacks bridge-data recovery")
            if target == "assistant" and not record["newer_h3_health"]:
                errors.append(f"fault {index} lacks newer H3 health")
            for field in ("ready", "bridge_data_resumed", "newer_h3_health"):
                if type(record[field]) is not bool:
                    errors.append(f"fault {index} {field} is not boolean")
            before = [sample for sample in samples if float(sample["elapsed_s"]) <= observed_s]
            after = [sample for sample in samples if float(sample["elapsed_s"]) > observed_s]
            if not before or not after:
                errors.append(f"fault {index} is not bracketed by samples")
            else:
                pre = before[-1]["roles"][target]
                if (pre["pid"], pre["started_ns"]) != (record["pre_pid"], record["pre_started_ns"]):
                    errors.append(f"fault {index} pre identity is not the immediately preceding sample")
                replacement_index = next(
                    (
                        sample_index
                        for sample_index, sample in enumerate(after)
                        if (sample["roles"][target]["pid"], sample["roles"][target]["started_ns"])
                        == (record["replacement_pid"], record["replacement_started_ns"])
                    ),
                    None,
                )
                if replacement_index is None:
                    errors.append(f"fault {index} replacement is absent from samples")
                else:
                    replacement_sample = after[replacement_index]
                    replacement = replacement_sample["roles"][target]
                    if int(replacement["epoch"]) != int(pre["epoch"]) + 1:
                        errors.append(f"fault {index} replacement epoch is not the next epoch")
                    actual_recovery_s = float(replacement_sample["elapsed_s"]) - observed_s
                    if actual_recovery_s > RECOVERY_CEILING_S or not math.isclose(
                        actual_recovery_s, float(record["recovery_s"]), abs_tol=1e-9
                    ):
                        errors.append(f"fault {index} recovery does not match sample history")
                    if any(
                        (sample["roles"][target]["pid"], sample["roles"][target]["started_ns"])
                        != (record["pre_pid"], record["pre_started_ns"])
                        for sample in after[:replacement_index]
                    ):
                        errors.append(f"fault {index} has an unrecorded intermediate identity")
        except (KeyError, TypeError, ValueError):
            errors.append(f"fault {index} schema is invalid")
    if observed != expected:
        errors.append("fault schedule is missing, duplicated, reordered, or unscheduled")
    # The sample history is an independent authority: every restart transition
    # must correspond one-to-one with a scheduled fault, while non-target roles
    # must never restart during this qualification profile.
    transitions: list[tuple[str, float, tuple[int, int], tuple[int, int]]] = []
    for role in ROLES:
        previous = samples[0]["roles"][role] if samples else None
        for sample in samples[1:]:
            current = sample["roles"][role]
            if previous is not None and int(current["epoch"]) != int(previous["epoch"]):
                transitions.append(
                    (
                        role,
                        float(sample["elapsed_s"]),
                        (int(previous["pid"]), int(previous["started_ns"])),
                        (int(current["pid"]), int(current["started_ns"])),
                    )
                )
            previous = current
    if any(role in {"launcher", "bridge"} for role, *_ in transitions):
        errors.append("launcher or bridge restarted during fault qualification")
    expected_transitions: list[tuple[str, float, tuple[int, int], tuple[int, int]]] = []
    for record in records:
        if str(record.get("target")) not in {"engine", "assistant"}:
            continue
        try:
            expected_transitions.append(
                (
                    str(record["target"]),
                    float(record["observed_s"]),
                    (int(record["pre_pid"]), int(record["pre_started_ns"])),
                    (int(record["replacement_pid"]), int(record["replacement_started_ns"])),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append("fault transition correlation schema is invalid")
    for role, transition_s, old_identity, new_identity in transitions:
        candidates = [
            item
            for item in expected_transitions
            if item[0] == role
            and item[2] == old_identity
            and item[3] == new_identity
            and item[1] < transition_s <= item[1] + RECOVERY_CEILING_S
        ]
        if len(candidates) != 1:
            errors.append(f"{role} sample transition is phantom, unscheduled, or ambiguous")
    if len(transitions) != len(expected_transitions):
        errors.append("fault ledger and sample epoch transitions are not one-to-one")
    return errors


def _validate_shutdown_payload(payload: Mapping[str, Any]) -> list[str]:
    fields = {
        "graceful_requested",
        "launcher_exited",
        "elapsed_s",
        "observed_identities",
        "survivors",
    }
    errors = _exact_keys(payload, fields, "shutdown")
    if not isinstance(payload, Mapping):
        return errors
    if payload.get("graceful_requested") is not True or payload.get("launcher_exited") is not True:
        errors.append("graceful launcher shutdown was not verified")
    elapsed = payload.get("elapsed_s")
    if not _finite_nonnegative(elapsed) or float(elapsed) > SHUTDOWN_CEILING_S:
        errors.append("shutdown exceeded ceiling")
    observed = payload.get("observed_identities")
    if not isinstance(observed, list):
        errors.append("observed identities are not a list")
    else:
        for identity in observed:
            if not isinstance(identity, Mapping) or set(identity) != {"pid", "started_ns"}:
                errors.append("observed identity schema is invalid")
                break
            if not _exact_positive_int(identity["pid"]) or not _exact_positive_int(identity["started_ns"]):
                errors.append("observed identity values are invalid")
                break
        if len(observed) != len({json.dumps(item, sort_keys=True) for item in observed}):
            errors.append("observed identities are duplicated")
    if payload.get("survivors") != []:
        errors.append("recorded descendants survived shutdown")
    return errors


def _terminal_mutation(phase: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Make a public evidence mutation exception-total and terminal.

    Expected validation/transition exceptions retain their useful type and
    message.  Unexpected implementation/serialization exceptions are
    normalized to ``ValueError`` after the first terminal summary is written.
    """

    def decorate(method: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(method)
        def guarded(self: Evidence, *args: Any, **kwargs: Any) -> Any:
            try:
                self._assert_directory_path()
                return method(self, *args, **kwargs)
            except Exception as exc:
                try:
                    self.finish_fail(
                        f"{phase} evidence mutation failed",
                        phase=phase,
                        error_type=type(exc).__name__,
                    )
                except (EvidenceCapabilityError, EvidenceUnavailableError):
                    pass
                if isinstance(exc, (ValueError, RuntimeError)):
                    raise
                raise ValueError(f"{phase} evidence validation failed: {type(exc).__name__}") from None

        return guarded

    return decorate


class Evidence:
    """Sealed typed evidence; only internal validation can authorize PASS."""

    def __init__(self, directory: Path) -> None:
        if os.name != "posix":
            raise EvidenceCapabilityError("evidence capability is POSIX-only")
        directory = directory.absolute()
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        self._directory_fd = os.open(directory, flags)
        opened = os.fstat(self._directory_fd)
        self._directory_identity = (opened.st_dev, opened.st_ino)
        self._closed = False
        self._terminal_summary_available = False
        try:
            self._assert_directory_path()
            if os.listdir(self._directory_fd):
                raise FileExistsError("evidence directory must be empty")
        except Exception:
            os.close(self._directory_fd)
            self._directory_fd = -1
            raise
        self.state = RunState.INITIAL_FAIL
        self._manifest_sha256: str | None = None
        self._exact_six_provenance: object | None = None
        self._periodic_delivery_seal: tuple[tuple[object, ...], ...] | None = None
        self._quarantines: list[Mapping[str, Any]] = []
        self._atomic_json(
            "summary.json",
            {
                "schema": SCHEMA,
                "status": "FAIL",
                "reason": "incomplete",
                "finished_at": None,
                "manifest_sha256": None,
                "ledger_sha256": None,
                "state": self.state.value,
            },
        )

    def __del__(self) -> None:
        try:
            self._close(suppress_exceptions=True)
        except Exception:
            pass

    def __enter__(self) -> Evidence:
        if self._closed:
            raise EvidenceUnavailableError("evidence capability is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        del exc_type, exc, traceback
        self.close()
        return False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def terminal_summary_available(self) -> bool:
        return self._terminal_summary_available

    def _invalidate_capability(self) -> None:
        self.state = RunState.FAIL
        self._terminal_summary_available = False
        self._directory_fd = -1
        self._closed = True

    def _assert_capability_identity(self) -> None:
        if self._closed:
            raise EvidenceUnavailableError("evidence capability is closed")
        if self._directory_fd < 0:
            raise EvidenceCapabilityError("owned evidence directory capability is unavailable")
        try:
            opened = os.fstat(self._directory_fd)
        except OSError as exc:
            self._invalidate_capability()
            raise EvidenceCapabilityError("owned evidence directory capability is unavailable") from exc
        if (opened.st_dev, opened.st_ino) != self._directory_identity or not stat.S_ISDIR(opened.st_mode):
            self._invalidate_capability()
            raise EvidenceCapabilityError("owned evidence directory capability changed")

    def _assert_directory_path(self) -> None:
        self._assert_capability_identity()
        try:
            current = os.stat(self.directory, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("evidence directory path no longer names the owned directory") from exc
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != self._directory_identity:
            raise ValueError("evidence directory path no longer names the owned directory")

    def _close(self, *, suppress_exceptions: bool) -> bool:
        if self._closed:
            return False
        try:
            self._assert_capability_identity()
        except EvidenceCapabilityError:
            self._closed = True
            if suppress_exceptions:
                return True
            return True
        try:
            if not self.terminal:
                self.finish_fail(
                    "evidence closed before terminal completion",
                    phase="lifecycle",
                    error_type="ClosedError",
                )
        except Exception:
            if not suppress_exceptions:
                raise
        finally:
            directory_fd = self._directory_fd
            self._directory_fd = -1
            self._closed = True
            if directory_fd >= 0:
                try:
                    os.close(directory_fd)
                except OSError:
                    if not suppress_exceptions:
                        raise
        return True

    def close(self) -> bool:
        """Settle terminal state when safe and release the owned capability."""

        return self._close(suppress_exceptions=False)

    def _exists(self, name: str) -> bool:
        try:
            os.stat(_flat_basename(name), dir_fd=self._directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def _read(self, name: str) -> tuple[bytes, os.stat_result]:
        return _read_owned_regular_at(self._directory_fd, name)

    def _text(self, name: str, *, errors: str = "strict") -> str:
        return _read_owned_text_at(self._directory_fd, name, errors=errors)

    def _sha256(self, name: str) -> str:
        payload, _identity = self._read(name)
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def _json_lines(self, name: str) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for line in self._text(name).splitlines():
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} contains a non-object record")
            rows.append(value)
        return rows

    def _atomic_json(self, name: str, payload: Mapping[str, Any]) -> None:
        _atomic_json_at(self._directory_fd, name, payload)

    def _atomic_text(self, name: str, payload: str) -> None:
        _atomic_bytes_at(self._directory_fd, name, payload.encode())

    def _append(self, name: str, payload: bytes) -> None:
        _append_owned_at(self._directory_fd, name, payload)

    def _unlink(self, name: str) -> None:
        os.unlink(_flat_basename(name), dir_fd=self._directory_fd)

    def _names(self) -> tuple[str, ...]:
        return tuple(os.listdir(self._directory_fd))

    def _secret_findings(self) -> list[str]:
        findings: list[str] = []
        for name in sorted(self._names()):
            if name == "summary.json":
                continue
            try:
                text = self._text(name, errors="replace")
            except (OSError, ValueError):
                findings.append(f"{name}:unsafe_artifact")
                continue
            for detector in _SECRET_DETECTORS:
                if detector.search(text):
                    findings.append(f"{name}:{detector.pattern}")
        return findings

    @property
    def terminal(self) -> bool:
        return self.state in {RunState.PASS, RunState.FAIL}

    def _require(self, state: RunState) -> None:
        if self.state != state:
            current = self.state.value
            self.finish_fail(
                f"invalid evidence transition from {current}; expected {state.value}",
                phase="state_machine",
                error_type="TransitionError",
            )
            raise RuntimeError(f"invalid evidence transition: {self.state.value} -> expected {state.value}")

    @_terminal_mutation("manifest")
    def write_manifest(self, payload: Mapping[str, Any]) -> None:
        self._require(RunState.INITIAL_FAIL)
        _validate_bounded_json(payload, path="manifest")
        if MANIFEST_RESERVED & payload.keys() or _has_forbidden_capture_key(payload):
            self.finish_fail("manifest validation failed", phase="manifest", error_type="ValidationError")
            raise ValueError("manifest contains reserved or forbidden fields")
        if self._exists("manifest.json"):
            raise RuntimeError("manifest is write-once")
        self._atomic_json("manifest.json", {**payload, "schema": SCHEMA})
        self._manifest_sha256 = self._sha256("manifest.json")
        self._assert_directory_path()
        self.state = RunState.MANIFEST_FINALIZED

    @_terminal_mutation("prerequisites")
    def write_prerequisites(self, payload: Mapping[str, Any]) -> None:
        self._require(RunState.MANIFEST_FINALIZED)
        _validate_bounded_json(payload, path="prerequisites")
        if _has_forbidden_capture_key(payload):
            self.finish_fail("prerequisite validation failed", phase="prerequisites", error_type="ValidationError")
            raise ValueError("environment capture is forbidden")
        manifest = json.loads(self._text("manifest.json"))
        errors = _validate_prerequisite_payload(payload, manifest["git_sha"])
        try:
            result_bytes, _identity = self._read("exact-six-result.json")
            result = json.loads(result_bytes)
            if not isinstance(result, Mapping):
                raise ValueError
            errors += _validate_exact_six_result(result, manifest["git_sha"])
            exact_six = payload.get("exact_six") if isinstance(payload, Mapping) else None
            expected_hash = exact_six.get("result_sha256") if isinstance(exact_six, Mapping) else None
            actual_hash = "sha256:" + hashlib.sha256(result_bytes).hexdigest()
            if expected_hash != actual_hash:
                errors.append("exact-six result artifact hash does not match")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("exact-six result artifact is absent, unsafe, or invalid")
        if errors:
            self.finish_fail("prerequisite validation failed", phase="prerequisites", error_type="ValidationError")
            raise ValueError("; ".join(errors))
        if self._exists("prerequisites.json"):
            self.finish_fail("prerequisite artifact already exists", phase="prerequisites", error_type="WriteOnceError")
            raise RuntimeError("prerequisite artifact is write-once")
        self._atomic_json("prerequisites.json", payload)
        self._assert_directory_path()
        self.state = RunState.PREREQUISITES_VERIFIED

    @_terminal_mutation("prerequisites")
    def write_exact_six_result(self, payload: Mapping[str, Any]) -> None:
        """Reject caller-asserted exact-six results.

        A future reviewed runner must own execution and inject an internal,
        execution-bound result capability.  JSON supplied by a caller is not
        qualification authority, even when its fields and hashes look valid.
        """

        del payload
        self._require(RunState.MANIFEST_FINALIZED)
        self.finish_fail(
            "caller-asserted exact-six result rejected",
            phase="prerequisites",
            error_type="AuthorityError",
        )
        raise RuntimeError("exact-six result requires execution-produced runner authority")

    @_terminal_mutation("prerequisites")
    def _accept_exact_six_result(self, authority: object) -> None:
        """Consume one runner-issued, Evidence-bound exact-six result."""

        from scripts import soak_mock_stack_runner as runner

        self._require(RunState.MANIFEST_FINALIZED)
        if type(authority) is not runner._ExactSixAuthority:
            self.finish_fail(
                "forged exact-six runner authority rejected",
                phase="prerequisites",
                error_type="AuthorityError",
            )
            raise RuntimeError("exact-six result requires execution-produced runner authority")
        payload, provenance = runner._consume_exact_six_authority(authority, self)
        manifest = json.loads(self._text("manifest.json"))
        errors = _validate_exact_six_result(payload, str(manifest.get("git_sha", "")))
        if errors:
            self.finish_fail(
                "execution-produced exact-six result rejected",
                phase="prerequisites",
                error_type="ValidationError",
            )
            raise ValueError("; ".join(errors))
        try:
            _atomic_json_at(self._directory_fd, "exact-six-result.json", payload, replace=False)
        except FileExistsError:
            self.finish_fail(
                "exact-six result artifact already exists",
                phase="prerequisites",
                error_type="WriteOnceError",
            )
            raise RuntimeError("exact-six result artifact is write-once")
        self._assert_directory_path()
        self._exact_six_provenance = provenance

    @_terminal_mutation("running")
    def _accept_periodic_delivery_result(self, authority: object) -> None:
        """Consume the one runner-issued proof of the durable H3 cutover."""

        from scripts import soak_mock_stack_runner as runner

        self._require(RunState.RUNNING)
        if type(authority) is not runner._DeliveryEvidenceAuthority:
            self.finish_fail(
                "forged periodic-delivery authority rejected",
                phase="running",
                error_type="AuthorityError",
            )
            raise RuntimeError("periodic delivery requires execution-produced runner authority")
        payload = runner._consume_periodic_delivery_authority(authority, self)
        receipts = self._json_lines("periodic-receipts.jsonl")
        errors, artifact_names = _validate_periodic_delivery_payload(
            payload,
            receipts,
            ledger_validator=runner._ArtifactReceiptSink._valid_ledger_record,
        )
        if errors:
            raise ValueError("; ".join(errors))
        for label, name, record in zip(("pre_fault", "post_fault"), artifact_names, receipts, strict=True):
            artifact, _identity = self._read(name)
            if not artifact.startswith(b"\x89PNG\r\n\x1a\n") or self._sha256(name) != record["artifact_sha256"]:
                raise ValueError(f"periodic-delivery {label} PNG evidence is invalid")
        try:
            _atomic_json_at(self._directory_fd, "periodic-delivery-result.json", payload, replace=False)
        except FileExistsError:
            raise RuntimeError("periodic-delivery result is write-once") from None
        captured_payload = json.loads(self._text("periodic-delivery-result.json"))
        captured_receipts = self._json_lines("periodic-receipts.jsonl")
        errors, captured_names = _validate_periodic_delivery_payload(
            captured_payload,
            captured_receipts,
            ledger_validator=runner._ArtifactReceiptSink._valid_ledger_record,
        )
        if errors or captured_payload != payload or captured_names != artifact_names:
            raise ValueError("periodic-delivery evidence changed before authority sealing")
        captured_artifact_hashes = {
            name: record["artifact_sha256"] for name, record in zip(captured_names, captured_receipts, strict=True)
        }
        seal: list[tuple[object, ...]] = []
        for name in ("periodic-delivery-result.json", "periodic-receipts.jsonl", *artifact_names):
            content, identity = self._read(name)
            if name in captured_artifact_hashes and (
                not content.startswith(b"\x89PNG\r\n\x1a\n")
                or "sha256:" + hashlib.sha256(content).hexdigest() != captured_artifact_hashes[name]
            ):
                raise ValueError("periodic-delivery PNG changed before authority sealing")
            if (
                not stat.S_ISREG(identity.st_mode)
                or stat.S_IMODE(identity.st_mode) != 0o600
                or identity.st_uid != os.getuid()
                or identity.st_nlink != 1
            ):
                raise ValueError("periodic-delivery evidence identity is unsafe")
            seal.append(
                (
                    name,
                    identity.st_dev,
                    identity.st_ino,
                    identity.st_uid,
                    identity.st_gid,
                    stat.S_IMODE(identity.st_mode),
                    identity.st_nlink,
                    identity.st_size,
                    identity.st_mtime_ns,
                    identity.st_ctime_ns,
                    "sha256:" + hashlib.sha256(content).hexdigest(),
                )
            )
        self._periodic_delivery_seal = tuple(seal)
        self._verify_periodic_delivery_seal()
        self._assert_directory_path()

    def _verify_periodic_delivery_seal(self) -> None:
        if self._periodic_delivery_seal is None:
            raise ValueError("execution-produced periodic-delivery seal is unavailable")
        observed: list[tuple[object, ...]] = []
        for expected in self._periodic_delivery_seal:
            name = str(expected[0])
            content, identity = self._read(name)
            observed.append(
                (
                    name,
                    identity.st_dev,
                    identity.st_ino,
                    identity.st_uid,
                    identity.st_gid,
                    stat.S_IMODE(identity.st_mode),
                    identity.st_nlink,
                    identity.st_size,
                    identity.st_mtime_ns,
                    identity.st_ctime_ns,
                    "sha256:" + hashlib.sha256(content).hexdigest(),
                )
            )
        if tuple(observed) != self._periodic_delivery_seal:
            raise ValueError("authority-sealed periodic-delivery evidence changed")

    @_terminal_mutation("running")
    def begin_run(self) -> None:
        self._require(RunState.PREREQUISITES_VERIFIED)
        self._assert_directory_path()
        self.state = RunState.RUNNING

    @_terminal_mutation("running")
    def append(self, name: str, payload: Mapping[str, Any]) -> None:
        self._require(RunState.RUNNING)
        if name not in {"samples.jsonl", "faults.jsonl"}:
            self.finish_fail("invalid typed evidence stream", phase="running", error_type="ValidationError")
            raise ValueError("only typed samples/fault streams are accepted")
        _validate_stream_record(name, payload)
        if _has_forbidden_capture_key(payload):
            self.finish_fail("evidence capture validation failed", phase="running", error_type="ValidationError")
            raise ValueError("environment capture is forbidden")
        encoded = (json.dumps(redact(payload), ensure_ascii=False, sort_keys=True) + "\n").encode()
        self._append(name, encoded)
        self._assert_directory_path()

    @_terminal_mutation("running")
    def write_log(self, name: str, text: str, *, allowlist: Sequence[str] = ()) -> None:
        self._require(RunState.RUNNING)
        if not re.fullmatch(r"log-[A-Za-z0-9_.-]+\.txt", name):
            self.finish_fail("log capture validation failed", phase="running", error_type="ValidationError")
            raise ValueError("log artifact name is invalid")
        if self._exists(name):
            self.finish_fail("log artifact already exists", phase="running", error_type="WriteOnceError")
            raise RuntimeError("log artifact is write-once")
        index = {"allowlist": list(allowlist), "artifacts": []}
        if self._exists("log_capture.json"):
            index = json.loads(self._text("log_capture.json"))
            if index["allowlist"] != list(allowlist):
                self.finish_fail("log allowlist changed", phase="running", error_type="ValidationError")
                raise ValueError("log allowlist changed during one run")
        if name in index["artifacts"]:
            self.finish_fail("log index duplicates artifact", phase="running", error_type="WriteOnceError")
            raise ValueError("log artifact is write-once")
        sanitized = redact_text(text)
        self._atomic_text(name, sanitized)
        index["artifacts"].append(name)
        self._atomic_json("log_capture.json", index)
        self._assert_directory_path()

    @_terminal_mutation("shutdown")
    def record_shutdown(self, payload: Mapping[str, Any]) -> None:
        self._require(RunState.RUNNING)
        _validate_bounded_json(payload, path="shutdown")
        if _has_forbidden_capture_key(payload):
            self.finish_fail("shutdown validation failed", phase="shutdown", error_type="ValidationError")
            raise ValueError("environment capture is forbidden")
        errors = _validate_shutdown_payload(payload)
        if errors:
            self.finish_fail("shutdown validation failed", phase="shutdown", error_type="ValidationError")
            raise ValueError("; ".join(errors))
        if self._exists("shutdown.json"):
            self.finish_fail("shutdown artifact already exists", phase="shutdown", error_type="WriteOnceError")
            raise RuntimeError("shutdown artifact is write-once")
        self._atomic_json("shutdown.json", payload)
        self._assert_directory_path()
        self.state = RunState.SHUTDOWN_VERIFIED

    def _sanitize_detected_secrets(self) -> list[str]:
        findings = self._secret_findings()
        for finding in findings:
            name, finding_class = finding.split(":", 1)
            try:
                original, identity = self._read(name)
            except (OSError, ValueError):
                try:
                    self._unlink(name)
                except OSError:
                    pass
                self._quarantines.append(
                    {
                        "artifact": name,
                        "finding_class": "unsafe-no-follow",
                        "original_sha256": None,
                        "sanitized_sha256": None,
                    }
                )
                continue
            sanitized = redact_text(original.decode("utf-8", errors="replace"))
            if any(detector.search(sanitized) for detector in _SECRET_DETECTORS):
                sanitized = f"<quarantined sha256:{hashlib.sha256(original).hexdigest()}>\n"
            current = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                try:
                    self._unlink(name)
                except OSError:
                    pass
                raise ValueError("artifact changed before confined quarantine")
            self._atomic_text(name, sanitized)
            self._quarantines.append(
                {
                    "artifact": name,
                    "finding_class": "sha256:" + hashlib.sha256(finding_class.encode()).hexdigest(),
                    "original_sha256": "sha256:" + hashlib.sha256(original).hexdigest(),
                    "sanitized_sha256": self._sha256(name),
                }
            )
        if self._quarantines:
            self._atomic_json("quarantine.json", {"records": self._quarantines})
        return findings

    def _remove_unsafe_entries(self) -> list[str]:
        """Remove unsafe top-level entries without reading or following them."""

        removed: list[Mapping[str, str]] = []
        errors: list[str] = []
        for name in self._names():
            if name in {"summary.json", "ledger.json"}:
                continue
            try:
                mode = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False).st_mode
            except OSError as exc:
                errors.append(f"{name}:lstat:{type(exc).__name__}")
                continue
            if stat.S_ISREG(mode):
                continue
            kind = "directory" if stat.S_ISDIR(mode) else "symlink" if stat.S_ISLNK(mode) else "nonregular"
            quarantine = f".unsafe-{uuid.uuid4().hex}"
            try:
                os.replace(
                    name,
                    quarantine,
                    src_dir_fd=self._directory_fd,
                    dst_dir_fd=self._directory_fd,
                )
                _remove_entry_at(self._directory_fd, quarantine)
                removed.append({"artifact": name, "kind": kind, "action": "removed-without-reading"})
            except OSError as exc:
                errors.append(f"{name}:remove:{type(exc).__name__}")
        if removed:
            self._quarantines.extend(removed)
            self._atomic_json("quarantine.json", {"records": self._quarantines})
        return errors

    def _build_ledger(self) -> tuple[AcceptanceLedger | None, list[str]]:
        errors: list[str] = []
        from scripts import soak_mock_stack_runner as runner

        try:
            runner._consume_exact_six_provenance(self._exact_six_provenance, self)
        except runner._RunnerFoundationError:
            errors.append("execution-produced exact-six runner authority is unavailable")
        required = {
            "manifest.json",
            "prerequisites.json",
            "exact-six-result.json",
            "samples.jsonl",
            "faults.jsonl",
            "log_capture.json",
            "shutdown.json",
            "periodic-delivery-result.json",
            "periodic-receipts.jsonl",
        }
        missing: list[str] = []
        for name in sorted(required):
            try:
                self._read(name)
            except (OSError, ValueError):
                missing.append(name)
        if missing:
            return None, [f"missing required artifacts: {missing}"]
        try:
            manifest = json.loads(self._text("manifest.json"))
            prerequisites = json.loads(self._text("prerequisites.json"))
            exact_six_result = json.loads(self._text("exact-six-result.json"))
            samples = self._json_lines("samples.jsonl")
            faults = self._json_lines("faults.jsonl")
            log_index = json.loads(self._text("log_capture.json"))
            shutdown = json.loads(self._text("shutdown.json"))
            periodic_delivery = json.loads(self._text("periodic-delivery-result.json"))
            periodic_receipts = self._json_lines("periodic-receipts.jsonl")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return None, [f"artifact parse failed: {type(exc).__name__}"]
        if _has_forbidden_capture_key({"manifest": manifest, "prerequisites": prerequisites, "shutdown": shutdown}):
            errors.append("environment-like key is retained in evidence")
        expected_manifest = {
            "schema",
            "profile",
            "git_sha",
            "dirty",
            "platform",
            "python",
            "source_command",
            "thresholds",
            "periodic_schedule",
            "source_fixture",
            "fatal_log_allowlist",
            "capture_policy",
        }
        errors += _exact_keys(manifest, expected_manifest, "manifest")
        if manifest.get("schema") != SCHEMA:
            errors.append("manifest schema is invalid")
        selected = PROFILES.get(str(manifest.get("profile")))
        if selected is None:
            errors.append("manifest profile is invalid")
            return None, errors
        git_sha = str(manifest.get("git_sha", ""))
        if re.fullmatch(r"[0-9a-f]{40}", git_sha) is None or manifest.get("dirty") is not False:
            errors.append("run is not bound to an exact clean Git SHA")
        frozen_thresholds = json.loads(json.dumps(effective_thresholds(selected), sort_keys=True))
        if manifest.get("thresholds") != frozen_thresholds:
            errors.append("manifest thresholds differ from the frozen profile")
        errors += _validate_source_fixture(manifest.get("source_fixture"))
        periodic_schedule = manifest.get("periodic_schedule")
        if not isinstance(periodic_schedule, Mapping):
            errors.append("manifest periodic schedule is invalid")
        else:
            errors += _exact_keys(
                periodic_schedule,
                {"interval_s", "selection_boundary_offset_s", "expected_receipts"},
                "manifest periodic schedule",
            )
            interval_s = periodic_schedule.get("interval_s")
            boundary_offset_s = periodic_schedule.get("selection_boundary_offset_s")
            if (
                type(interval_s) is not int
                or not 600 <= interval_s <= 3600
                or type(boundary_offset_s) is not int
                or not 450 <= boundary_offset_s <= 600
                or boundary_offset_s + interval_s < 1050
                or type(periodic_schedule.get("expected_receipts")) is not int
                or periodic_schedule.get("expected_receipts") != 2
            ):
                errors.append("manifest periodic schedule is outside the reviewed short-run bounds")
        source_command = manifest.get("source_command")
        if (
            not isinstance(source_command, list)
            or not source_command
            or any(not isinstance(item, str) or not item for item in source_command)
        ):
            errors.append("source command is invalid")
        elif (
            tuple(source_command[1:]) != SOURCE_COMMAND_TAIL
            or Path(source_command[0]).resolve() != Path(sys.executable).resolve()
        ):
            errors.append("source command is not the canonical current-interpreter launcher command")
        for field in ("platform", "python", "capture_policy"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                errors.append(f"manifest {field} is invalid")
        errors += _validate_prerequisite_payload(prerequisites, git_sha)
        if not isinstance(exact_six_result, Mapping):
            errors.append("exact-six result artifact is not an object")
        else:
            errors += _validate_exact_six_result(exact_six_result, git_sha)
        if prerequisites.get("exact_six", {}).get("result_sha256") != self._sha256("exact-six-result.json"):
            errors.append("exact-six result artifact hash does not match prerequisite ledger")
        try:
            self._verify_periodic_delivery_seal()
        except (OSError, ValueError) as exc:
            errors.append(f"periodic-delivery authority seal failed: {exc}")
        periodic_errors, periodic_artifact_names = _validate_periodic_delivery_payload(
            periodic_delivery,
            periodic_receipts,
            ledger_validator=runner._ArtifactReceiptSink._valid_ledger_record,
        )
        errors += periodic_errors
        if not periodic_errors:
            for label, artifact_name, ledger_record in zip(
                ("pre_fault", "post_fault"),
                periodic_artifact_names,
                periodic_receipts,
                strict=True,
            ):
                try:
                    artifact, _identity = self._read(artifact_name)
                    if (
                        not artifact.startswith(b"\x89PNG\r\n\x1a\n")
                        or self._sha256(artifact_name) != ledger_record["artifact_sha256"]
                    ):
                        errors.append(f"periodic-delivery {label} artifact hash differs")
                except (OSError, ValueError):
                    errors.append(f"periodic-delivery {label} artifact is absent or unsafe")
        sample_errors = evaluate_resources(samples, selected)
        errors += [f"samples: {error}" for error in sample_errors]
        fault_errors = _validate_faults(faults, selected, samples)
        errors += [f"faults: {error}" for error in fault_errors]
        expected_log_index = {"allowlist", "artifacts"}
        errors += _exact_keys(log_index, expected_log_index, "log index")
        log_names = log_index.get("artifacts", [])
        if (
            not isinstance(log_names, list)
            or len(log_names) != len(set(log_names))
            or not log_names
            or any(
                not isinstance(name, str) or re.fullmatch(r"log-[A-Za-z0-9_.-]+\.txt", name) is None
                for name in log_names
            )
        ):
            errors.append("log artifact list is empty or duplicated")
            log_names = []
        allowlist = log_index.get("allowlist", [])
        if allowlist != manifest.get("fatal_log_allowlist"):
            errors.append("effective fatal-log allowlist differs from manifest")
        if not isinstance(allowlist, list) or any(not isinstance(item, str) for item in allowlist):
            errors.append("fatal-log allowlist is invalid")
            allowlist = []
        for name in log_names:
            try:
                violations = log_violations(self._text(str(name), errors="replace"), allowlist)
            except (OSError, ValueError):
                errors.append(f"log artifact is absent or unsafe: {name}")
                violations = []
            except re.error:
                errors.append("fatal-log allowlist contains an invalid regex")
                violations = []
            if violations:
                errors.append(f"log artifact failed scan: {name}")
        errors += _validate_shutdown_payload(shutdown)
        observed_identities = shutdown.get("observed_identities", [])
        expected_identities: set[tuple[int, int]] = set()
        try:
            expected_identities = {
                (int(record["pid"]), int(record["started_ns"]))
                for sample in samples
                for record in sample["roles"].values()
            }
            expected_identities.update(
                (int(record[field_pid]), int(record[field_started]))
                for record in faults
                for field_pid, field_started in (
                    ("pre_pid", "pre_started_ns"),
                    ("replacement_pid", "replacement_started_ns"),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append("identity evidence schema is incomplete or invalid")
        actual_identities = {
            (int(identity["pid"]), int(identity["started_ns"]))
            for identity in observed_identities
            if isinstance(identity, Mapping) and {"pid", "started_ns"} <= identity.keys()
        }
        if actual_identities != expected_identities:
            errors.append("shutdown identity set does not equal every observed identity")
        retained = self._secret_findings()
        if retained:
            errors.append("final secrecy scan retained findings")
        accepted_names = required | set(str(name) for name in log_names)
        accepted_names.update(periodic_artifact_names)
        if self._exists("quarantine.json"):
            accepted_names.add("quarantine.json")
        for name in self._names():
            if name in {"summary.json", "ledger.json"}:
                continue
            try:
                mode = os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False).st_mode
            except OSError:
                errors.append(f"artifact disappeared during topology scan: {name}")
                continue
            if not stat.S_ISREG(mode):
                errors.append(f"artifact tree contains a non-regular entry: {name}")
            elif name not in accepted_names:
                errors.append(f"artifact tree contains an unregistered artifact: {name}")
        artifact_names = sorted(accepted_names)
        artifact_payloads: dict[str, bytes] = {}
        for name in artifact_names:
            try:
                artifact_payloads[name], _identity = self._read(name)
            except (OSError, ValueError):
                errors.append(f"registered artifact disappeared or changed before hashing: {name}")
        if errors:
            return None, errors
        artifacts = tuple(
            ArtifactRecord(
                name,
                len(artifact_payloads[name]),
                "sha256:" + hashlib.sha256(artifact_payloads[name]).hexdigest(),
            )
            for name in artifact_names
        )
        ledger = AcceptanceLedger(
            run=RunIdentity(
                SCHEMA,
                selected.name,
                git_sha,
                False,
                str(manifest["platform"]),
                str(manifest["python"]),
                tuple(manifest["source_command"]),
                self._sha256("manifest.json"),
            ),
            prerequisites=PrerequisiteLedger(
                tuple(prerequisites["exact_six"]["command"]),
                prerequisites["exact_six"]["git_sha"],
                prerequisites["exact_six"]["exit_code"],
                prerequisites["exact_six"]["status"],
                prerequisites["exact_six"]["result_artifact"],
                prerequisites["exact_six"]["result_sha256"],
                prerequisites["observer"]["identity"],
                prerequisites["observer"]["version"],
                prerequisites["local_publisher"]["identity"],
                prerequisites["bridge_identity"]["capability"],
            ),
            samples=SampleLedger("samples.jsonl", self._sha256("samples.jsonl"), len(samples), "PASS"),
            faults=FaultLedger("faults.jsonl", self._sha256("faults.jsonl"), len(faults), "PASS"),
            logs=LogLedger(
                tuple(str(name) for name in log_names),
                "sha256:" + hashlib.sha256(json.dumps(allowlist, sort_keys=True).encode()).hexdigest(),
                "PASS",
            ),
            shutdown=ShutdownLedger(True, True, float(shutdown["elapsed_s"]), len(observed_identities), 0),
            secrecy=SecrecyLedger(str(manifest["capture_policy"]), "PASS", 0, tuple(self._quarantines)),
            periodic_delivery=PeriodicDeliveryLedger(
                "periodic-delivery-result.json",
                self._sha256("periodic-delivery-result.json"),
                "periodic-receipts.jsonl",
                len(periodic_receipts),
                "PASS",
            ),
            artifacts=artifacts,
        )
        return ledger, []

    @_terminal_mutation("sealing")
    def seal(self) -> None:
        self._require(RunState.SHUTDOWN_VERIFIED)
        try:
            unsafe_errors = self._remove_unsafe_entries()
            if unsafe_errors or self._quarantines:
                detail = "; ".join(unsafe_errors) if unsafe_errors else "unsafe entries removed"
                raise ValueError(f"non-regular artifact tree rejected: {detail}")
            findings = self._sanitize_detected_secrets()
            if findings or self._secret_findings():
                raise ValueError("secret detection prevented sealing")
            ledger, errors = self._build_ledger()
            if ledger is None or errors:
                raise ValueError("; ".join(errors))
            self._atomic_json("ledger.json", ledger.payload())
            self._assert_directory_path()
            self.state = RunState.EVIDENCE_SEALED
        except Exception as exc:
            self.finish_fail("ledger validation failed", phase="sealing", error_type="ValidationError")
            if isinstance(exc, ValueError):
                raise
            raise ValueError("seal validation failed: artifact schema is incomplete or invalid") from None

    def finish_fail(
        self,
        reason: str,
        *,
        phase: str | None = None,
        error_type: str | None = None,
        interrupted: bool = False,
    ) -> bool:
        self._assert_capability_identity()
        if self.terminal:
            return False
        metadata = {
            "phase": phase,
            "error_type": error_type,
            "interrupted": interrupted,
        }
        if _has_forbidden_capture_key(metadata):
            raise ValueError("failure metadata contains forbidden fields")
        self.state = RunState.FAIL

        def optional_hash(name: str) -> str | None:
            try:
                return self._sha256(name)
            except (OSError, ValueError):
                return None

        self._atomic_json(
            "summary.json",
            {
                "schema": SCHEMA,
                "status": "FAIL",
                "reason": redact_text(str(reason)),
                "finished_at": datetime.now(UTC).isoformat(),
                "manifest_sha256": optional_hash("manifest.json"),
                "ledger_sha256": optional_hash("ledger.json"),
                "state": RunState.FAIL.value,
                **metadata,
            },
        )
        self._terminal_summary_available = True
        return True

    @_terminal_mutation("validation")
    def finish_pass(self) -> None:
        self._require(RunState.EVIDENCE_SEALED)
        try:
            ledger, errors = self._build_ledger()
            stored = json.loads(self._text("ledger.json"))
            if ledger is None or errors or ledger.payload() != stored:
                raise ValueError("sealed ledger validation failed")
            self._assert_directory_path()
            self.state = RunState.VALIDATED
            ledger_again, errors = self._build_ledger()
            if ledger_again is None or errors or ledger_again.payload() != stored:
                raise ValueError("artifact rehash failed")
            ledger_sha = self._sha256("ledger.json")
            self._atomic_json(
                "summary.json",
                {
                    "schema": SCHEMA,
                    "status": "PASS",
                    "reason": "validated qualification ledger",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "manifest_sha256": ledger.run.manifest_sha256,
                    "ledger_sha256": ledger_sha,
                    "state": RunState.PASS.value,
                },
            )
            self._verify_periodic_delivery_seal()
            ledger_final, errors = self._build_ledger()
            if ledger_final is None or errors or ledger_final.payload() != stored:
                raise ValueError("post-summary artifact rehash failed")
            self._assert_directory_path()
            self.state = RunState.PASS
            self._terminal_summary_available = True
        except Exception as exc:
            self.finish_fail("sealed evidence changed before PASS", phase="validation", error_type="ValidationError")
            if isinstance(exc, ValueError):
                raise
            raise ValueError("PASS validation failed: artifact schema is incomplete or invalid") from None


class RunInterrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


class Lifecycle:
    def __init__(self, evidence: Evidence, cleanup: Callable[[], None]) -> None:
        self.evidence = evidence
        self.cleanup = cleanup
        self.phase = "setup"
        self._cleaned = False

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def _cleanup_once(self) -> None:
        if not self._cleaned:
            self._cleaned = True
            self.cleanup()

    def interrupt(self, signum: int, _frame: object = None) -> None:
        self._cleanup_once()
        self.evidence.finish_fail(f"interrupted by signal {signum}", phase=self.phase, interrupted=True)
        raise RunInterrupted(signum)

    def fail(self, reason: str, *, error_type: str | None = None) -> None:
        self._cleanup_once()
        self.evidence.finish_fail(reason, phase=self.phase, error_type=error_type)


def _psutil_process_start_ns(process: Any, *, epoch_seconds: object) -> int:
    """Use Linux's clock-stable process start time; preserve other platforms."""

    try:
        started = float(process._proc.create_time(monotonic=True)) if sys.platform == "linux" else float(epoch_seconds)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise ValueError("process start identity is unavailable") from exc
    if not math.isfinite(started) or started <= 0:
        raise ValueError("process start identity is invalid")
    return int(round(started * 1_000_000_000))


class PsutilObserver:
    def __init__(self, psutil_module: Any) -> None:
        self._psutil = psutil_module

    def snapshot(self) -> Sequence[ProcessSnapshot]:
        result: list[ProcessSnapshot] = []
        attributes = ["pid", "ppid", "cmdline", "name", "memory_info", "num_threads"]
        if sys.platform != "linux":
            attributes.append("create_time")
        for process in self._psutil.process_iter(attributes):
            try:
                info = process.info
                descriptors = process.num_handles() if sys.platform == "win32" else process.num_fds()
                result.append(
                    ProcessSnapshot(
                        ProcessIdentity(
                            int(info["pid"]),
                            _psutil_process_start_ns(process, epoch_seconds=info.get("create_time")),
                        ),
                        int(info["ppid"]) or None,
                        tuple(info.get("cmdline") or ()),
                        str(info.get("name") or ""),
                        int(info["memory_info"].rss),
                        int(info["num_threads"]),
                        int(descriptors),
                    )
                )
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, KeyError, TypeError):
                continue
        return result

    def signal(self, identity: ProcessIdentity, sig: int) -> None:
        process = self._psutil.Process(identity.pid)
        epoch_seconds = None if sys.platform == "linux" else process.create_time()
        current = _psutil_process_start_ns(process, epoch_seconds=epoch_seconds)
        if current != identity.started_ns:
            raise RuntimeError("refusing to signal reused PID")
        process.send_signal(sig)


def _git_metadata() -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        dirty = bool(
            subprocess.run(["git", "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
        )
        return sha, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def effective_thresholds(selected: SoakProfile) -> dict[str, Any]:
    return {
        "sample_interval_s": SAMPLE_INTERVAL_S,
        "max_cadence_gap_s": MAX_CADENCE_GAP_S,
        "max_slope_points": MAX_SLOPE_POINTS,
        "max_slope_pairs": MAX_SLOPE_PAIRS,
        "recovery_ceiling_s": RECOVERY_CEILING_S,
        "shutdown_ceiling_s": SHUTDOWN_CEILING_S,
        "rss_growth_limit_bytes": RSS_GROWTH_LIMIT_BYTES,
        "profile": asdict(selected),
        "event_ordering": "healthy sample and baseline commit precede same-cadence injection",
    }


def _default_evidence_dir(selected: SoakProfile) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return Path("artifacts") / "mock-stack-soak" / f"{stamp}-{os.getpid()}-{selected.name}"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CryoDAQ source-mode mock-stack soak")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="short")
    parser.add_argument("--evidence-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected = profile(args.profile)
    from scripts import soak_mock_stack_runner as runner

    try:
        runner._PosixSoakRunner.require_platform()
    except runner._RunnerActivationDisabled:
        return 2
    if selected.name != "short":
        return 2
    try:
        evidence = Evidence(args.evidence_dir or _default_evidence_dir(selected))
    except (FileExistsError, EvidenceCapabilityError):
        return 2
    previous_handlers: dict[int, Any] = {}
    interrupt_handler = _first_signal_interrupt_handler()
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, interrupt_handler)
        runner._PosixSoakRunner().run(evidence)
        return 0
    except RunInterrupted as exc:
        evidence.finish_fail(
            f"interrupted by signal {exc.signum}",
            phase="runner",
            interrupted=True,
        )
        return 128 + exc.signum
    except KeyboardInterrupt:
        evidence.finish_fail("interrupted by signal 2", phase="runner", interrupted=True)
        return 130
    except BaseException as exc:
        evidence.finish_fail(str(exc), phase="runner", error_type=type(exc).__name__)
        return 1
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
        evidence.close()


def _first_signal_interrupt_handler() -> Callable[[int, object], None]:
    """Raise once, then let fail-closed settlement finish despite signal storms."""

    first_signum: int | None = None

    def interrupt(received: int, _frame: object) -> None:
        nonlocal first_signum
        if first_signum is not None:
            return
        first_signum = received
        raise RunInterrupted(received)

    return interrupt


if __name__ == "__main__":
    raise SystemExit(main())
