"""Liveness guard for safety channel-matching patterns (F-1 regression class).

The F-1 incident: a channel-identity change silently broke overtemp interlock
regexes because they were matched against the WRONG plane — canonical post-bind
channel_id vs raw pre-bind emitted label. A pattern written for one plane that
is consumed on the other matches nothing and silently blinds a safety function.

This test asserts that EVERY safety-relevant channel-matching pattern in the
three safety configs matches at least one REAL production channel on the SAME
plane its consumer actually sees. A pattern matching nothing FAILS — that is
the bug. Patterns and channels are loaded via production config loaders; no
regex is hand-duplicated.

PLANES — proven from the CONSUMING code (not assumed):

1. config/interlocks.yaml -> InterlockEngine : CANONICAL plane.
     InterlockEngine subscribes to the main DataBroker (src/cryodaq/core/
     interlock.py:415 ``self._broker.subscribe``). The DataBroker receives the
     post-bind canonical stream ``committed_publish_readings`` (src/cryodaq/
     core/scheduler.py:676). The bind step rewrites ``Reading.channel`` to the
     canonical ``descriptor.channel_id`` (src/cryodaq/storage/channel_descriptors
     .py:877-878: ``if owned.channel != channel_id: owned = replace(owned,
     channel=channel_id)``). Matching is ``self._pattern.match(channel)`` inside
     ``matches_channel`` (src/cryodaq/core/interlock.py:114-116), invoked on
     ``reading.channel`` in ``_process_reading`` (src/cryodaq/core/interlock.py:
     470).  => match against canonical channel_id.

2. config/safety.yaml -> SafetyManager : RAW plane.
     SafetyManager subscribes to SafetyBroker (src/cryodaq/core/safety_manager.
     py:268 ``self._broker.subscribe``). SafetyBroker receives the PRE-bind
     driver output: scheduler publishes the raw ``readings`` parameter to the
     safety broker (src/cryodaq/core/scheduler.py:681
     ``await self._safety_broker.publish_batch(readings)``), distinct from the
     canonical stream it sends to the DataBroker at scheduler.py:676.
     ``self._latest`` is keyed by ``reading.channel`` (src/cryodaq/core/
     safety_manager.py:1652), i.e. the raw emitted label. ``critical_channels``
     patterns are matched with ``pattern.match(ch)`` (src/cryodaq/core/
     safety_manager.py:988, 1612, 1715, 1720).  => match against raw
     emitted_channel.

3. config/alarms_v3.yaml -> AdaptiveThrottle (src/cryodaq/core/housekeeping.py):
   RAW plane.
     The scheduler filters the PRE-bind ``readings`` through the throttle
     (src/cryodaq/core/scheduler.py:602 ``self._adaptive_throttle
     .filter_for_archive(readings)``). Protected patterns are the re.escape'd
     channel refs extracted by ``load_critical_channels_from_alarms_v3``
     (src/cryodaq/core/housekeeping.py:137), merged with legacy interlock
     patterns at engine wiring (src/cryodaq/engine.py:2577-2589). Matching is
     ``pattern.search(reading.channel)`` (src/cryodaq/core/housekeeping.py:293,
     335).  => match against raw emitted_channel, substring semantics.

The two planes are both carried by the production descriptor manifest
(config/channel_descriptors.yaml): ``descriptors[].channel_id`` is canonical;
``bindings[].emitted_channel`` is the raw label the bind step translates FROM.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from cryodaq.core.housekeeping import load_critical_channels_from_alarms_v3
from cryodaq.core.interlock import InterlockCondition
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_INTERLOCKS_PATH = _CONFIG_DIR / "interlocks.yaml"
_SAFETY_PATH = _CONFIG_DIR / "safety.yaml"
_ALARMS_V3_PATH = _CONFIG_DIR / "alarms_v3.yaml"
_DESCRIPTORS_PATH = _CONFIG_DIR / "channel_descriptors.yaml"


def _node_id(label: str) -> str:
    """Stable, filesystem-safe parametrize id (keeps Cyrillic; drops path separators)."""
    return label.replace("/", "_").replace(" ", "_")


def _load_roster() -> tuple[list[str], list[str]]:
    """Return (canonical channel_ids, raw emitted_channels) via the production loader."""
    owner = load_live_channel_descriptor_catalog(_DESCRIPTORS_PATH)
    catalog = owner.storage_catalog_snapshot()
    canonical = sorted(catalog.by_channel_id)
    # ``_bindings`` maps (instrument_id, emitted_channel) -> channel_id
    # (src/cryodaq/storage/channel_descriptors.py:817). The emitted_channel key
    # is the raw pre-bind label the consumer sees on the RAW plane.
    raw = sorted({emitted for (_instr, emitted) in owner._bindings})
    return canonical, raw


def _load_interlock_conditions() -> list[InterlockCondition]:
    raw = yaml.safe_load(_INTERLOCKS_PATH.read_text(encoding="utf-8"))
    conditions: list[InterlockCondition] = []
    for entry in raw.get("interlocks", []):
        # Same construction path as InterlockEngine.load_config
        # (src/cryodaq/core/interlock.py:311-319): __post_init__ compiles and
        # validates channel_pattern identically, and matches_channel() is the
        # production matcher (``_pattern.match``).
        conditions.append(
            InterlockCondition(
                name=entry["name"],
                description=entry.get("description", ""),
                channel_pattern=entry["channel_pattern"],
                threshold=float(entry.get("threshold", 0.0)),
                comparison=entry.get("comparison", ">"),
                action=entry.get("action", ""),
            )
        )
    return conditions


def _load_safety_patterns() -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    # Mirrors src/cryodaq/gui/first_run_config.py:194
    # ``SafetyManager(SafetyBroker()).load_config(safety_path)`` — the production
    # loader (src/cryodaq/core/safety_manager.py:195) compiles + validates the
    # critical_channels regexes and rejects an empty/invalid set.
    sm = SafetyManager(SafetyBroker())
    sm.load_config(_SAFETY_PATH)
    critical = list(sm._config.critical_channels)
    keithley = [re.compile(p) for p in sm._config.keithley_channel_patterns]
    return critical, keithley


CANONICAL_CHANNEL_IDS, RAW_EMITTED_CHANNELS = _load_roster()
INTERLOCK_CONDITIONS = _load_interlock_conditions()
SAFETY_CRITICAL_PATTERNS, SAFETY_KEITHLEY_PATTERNS = _load_safety_patterns()
ALARMS_V3_PROTECTED_PATTERNS = sorted(load_critical_channels_from_alarms_v3(_ALARMS_V3_PATH))

# Channels published DIRECTLY to the DataBroker, bypassing the scheduler and
# therefore the AdaptiveThrottle (which only ever filters the scheduler's
# pre-bind readings — src/cryodaq/core/scheduler.py:602
# ``self._adaptive_throttle.filter_for_archive(readings)``). Such a channel is
# real and its alarm is a genuine safety alarm, but a throttle-plane liveness
# check for it is a FALSE POSITIVE: the channel can never be thinned by a
# component it never passes through, and it is not (and must not be) carried by
# the descriptor-manifest roster. DiskMonitor is the sole member today — it
# calls ``await self._broker.publish(reading)`` directly with channel
# ``system/disk_free_gb`` (src/cryodaq/core/disk_monitor.py:85,91) and is not
# driven by the scheduler at all.
_THROTTLE_BYPASS_PATTERNS = frozenset({re.escape("system/disk_free_gb")})

# Protected patterns that are actually checkable against the RAW roster — i.e.
# the full protected set MINUS the direct-to-DataBroker bypass set above.
ALARMS_V3_THROTTLE_CHECKED_PATTERNS = sorted(set(ALARMS_V3_PROTECTED_PATTERNS) - _THROTTLE_BYPASS_PATTERNS)


def test_roster_is_populated() -> None:
    """Fail fast if the descriptor manifest path/loader changed and the roster is empty."""
    assert CANONICAL_CHANNEL_IDS, "no canonical channel_ids loaded from channel_descriptors.yaml"
    assert RAW_EMITTED_CHANNELS, "no raw emitted_channel labels loaded from channel_descriptors.yaml"


@pytest.mark.parametrize(
    "condition",
    INTERLOCK_CONDITIONS,
    ids=[_node_id(c.name) for c in INTERLOCK_CONDITIONS],
)
def test_interlock_pattern_matches_canonical_channel(condition: InterlockCondition) -> None:
    """interlocks.yaml channel_pattern must match >=1 canonical channel_id.

    InterlockEngine consumes the CANONICAL plane (DataBroker post-bind stream),
    so a pattern written for the raw emitted label (with display-name suffix)
    would match nothing and silently disarm every overtemp interlock.
    """
    matched = [cid for cid in CANONICAL_CHANNEL_IDS if condition.matches_channel(cid)]
    assert matched, (
        f"interlock {condition.name!r} channel_pattern "
        f"{condition.channel_pattern!r} matches NO canonical channel_id "
        f"(InterlockEngine plane = post-bind Reading.channel). "
        f"Roster had {len(CANONICAL_CHANNEL_IDS)} canonical ids; sample: "
        f"{CANONICAL_CHANNEL_IDS[:6]}."
    )


@pytest.mark.parametrize(
    "pattern",
    SAFETY_CRITICAL_PATTERNS,
    ids=[_node_id(p.pattern) for p in SAFETY_CRITICAL_PATTERNS],
)
def test_safety_critical_pattern_matches_raw_channel(pattern: re.Pattern[str]) -> None:
    """safety.yaml critical_channels pattern must match >=1 raw emitted label.

    SafetyManager consumes the RAW plane (SafetyBroker pre-bind stream), so a
    pattern written for the canonical id (e.g. ``Т11$`` with no display-name
    suffix) would match nothing, defeat the stale/invalid-input gate, and let
    RUN proceed without monitoring the critical channel.
    """
    matched = [ch for ch in RAW_EMITTED_CHANNELS if pattern.match(ch)]
    assert matched, (
        f"safety.yaml critical_channels pattern {pattern.pattern!r} matches NO "
        f"raw emitted_channel (SafetyManager plane = pre-bind SafetyBroker "
        f"output). If it was written for canonical channel_id, that is the "
        f"F-1 class bug. Roster had {len(RAW_EMITTED_CHANNELS)} raw labels; "
        f"sample: {RAW_EMITTED_CHANNELS[:6]}."
    )


@pytest.mark.parametrize(
    "pattern",
    SAFETY_KEITHLEY_PATTERNS,
    ids=[_node_id(p.pattern) for p in SAFETY_KEITHLEY_PATTERNS],
)
def test_safety_keithley_pattern_matches_raw_channel(pattern: re.Pattern[str]) -> None:
    """safety.yaml keithley_channels pattern must match >=1 raw Keithley label.

    Used by the RUNNING heartbeat check (src/cryodaq/core/safety_manager.py:1794)
    against the RAW ``self._latest`` keys. A dead pattern here would silently
    disable the source heartbeat watchdog.
    """
    matched = [ch for ch in RAW_EMITTED_CHANNELS if pattern.match(ch)]
    assert matched, (
        f"safety.yaml keithley_channels pattern {pattern.pattern!r} matches NO "
        f"raw emitted_channel (SafetyManager heartbeat plane = pre-bind). "
        f"Roster sample: {[c for c in RAW_EMITTED_CHANNELS if 'smu' in c][:4]}."
    )


@pytest.mark.parametrize(
    "pattern",
    ALARMS_V3_THROTTLE_CHECKED_PATTERNS,
    ids=[_node_id(p) for p in ALARMS_V3_THROTTLE_CHECKED_PATTERNS],
)
def test_alarms_v3_protected_pattern_matches_raw_channel(pattern: str) -> None:
    """alarms_v3.yaml protected-channel ref must match >=1 raw emitted label.

    The AdaptiveThrottle consumes the RAW plane (scheduler pre-bind readings)
    with substring (``.search``) semantics. A dead ref silently removes a
    safety-critical channel from throttle protection, so a stable sensor reading
    can be thinned out of the archive right when an operator needs it.

    Channels that publish directly to the DataBroker (bypassing the scheduler)
    are excluded from this check via ``_THROTTLE_BYPASS_PATTERNS`` — see
    ``test_throttle_bypass_patterns_are_current`` for the evidence and the guard.
    """
    compiled = re.compile(pattern)
    matched = [ch for ch in RAW_EMITTED_CHANNELS if compiled.search(ch)]
    assert matched, (
        f"alarms_v3.yaml protected-channel ref {pattern!r} matches NO raw "
        f"emitted_channel (AdaptiveThrottle plane = pre-bind, .search). It "
        f"protects nothing. Roster had {len(RAW_EMITTED_CHANNELS)} raw labels; "
        f"sample: {RAW_EMITTED_CHANNELS[:6]}."
    )


def test_throttle_bypass_patterns_are_current() -> None:
    """Guard the direct-to-DataBroker bypass against silent drift.

    DiskMonitor does not pass through the scheduler, so ``system/disk_free_gb``
    has no place in the throttle-plane liveness check above and is carved out by
    ``_THROTTLE_BYPASS_PATTERNS``. This test pins that bypass set to the
    channels currently known to bypass the throttle, and verifies each bypassed
    pattern is still referenced as a protected channel in alarms_v3.yaml — so a
    rename/removal of the disk alarm (or a new direct-to-DataBroker publisher)
    forces a conscious revisit instead of silently weakening throttle protection
    or silently over-excluding it.

    Evidence: DiskMonitor publishes directly to the DataBroker
    (src/cryodaq/core/disk_monitor.py:85,91, channel ``system/disk_free_gb``)
    and is never handed to ``AdaptiveThrottle.filter_for_archive`` (that call
    site lives in the scheduler, src/cryodaq/core/scheduler.py:602).
    """
    expected = frozenset({re.escape("system/disk_free_gb")})
    assert _THROTTLE_BYPASS_PATTERNS == expected, (
        "throttle-bypass set drifted from the known DiskMonitor-only membership; "
        "update _THROTTLE_BYPASS_PATTERNS and document the new bypass publisher"
    )
    stale = sorted(_THROTTLE_BYPASS_PATTERNS - set(ALARMS_V3_PROTECTED_PATTERNS))
    assert not stale, (
        "throttle-bypass patterns no longer referenced as protected channels in "
        f"alarms_v3.yaml (the exclusion may be stale): {stale}"
    )
