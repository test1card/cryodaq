"""Startup liveness validator for safety channel-matching patterns.

Guards the F-1 "silent safety kill" class at BOOT. A safety alarm/interlock
pattern is matched against a channel roster on a specific "plane". If a channel
rename makes a CRITICAL/safety pattern match NOTHING, the safety rule is
silently inert — it protects a channel that no longer exists under that name.
This module raises if any CRITICAL/safety pattern is dead against the
ACTUALLY-SELECTED descriptor manifest, so the failure is loud at boot instead
of silent at runtime.  The engine's current temporary lab-build policy catches
only this diagnostic exception and continues after a CRITICAL log until the
exact lab manifest has been validated.  Removing that narrow catch restores
the intended fail-closed startup behavior.

The planes, matchers, and the disk-synthetic-channel bypass are copied from
the proven regression test ``tests/core/test_safety_pattern_liveness.py``
(commit dca5ff5). See that file for the consuming-code citations that PROVE
each plane (canonical post-bind ``channel_id`` vs raw pre-bind emitted label).
DO NOT reinvent those semantics here.

This validator is OBSERVATIONAL at startup only: it reads configs and the
selected descriptor manifest and raises a diagnostic exception. It issues no
commands, holds no write credentials, and acquires no actuator authority.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from cryodaq.core.interlock import InterlockCondition
from cryodaq.core.safety_manager import SafetyConfigError

if TYPE_CHECKING:
    from cryodaq.core.safety_manager import SafetyManager
    from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog


class SafetyPatternLivenessError(SafetyConfigError):
    """Raised when a startup CRITICAL/safety channel-pattern is dead.

    Subclasses ``SafetyConfigError`` so the final fail-closed policy maps an
    uncaught instance to ``ENGINE_CONFIG_ERROR_EXIT_CODE`` (2), which the
    launcher does not auto-restart.  The current lab-build call site catches
    exactly this subclass temporarily and logs at CRITICAL.  The message names
    every dead pattern with its plane and config source.
    """


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
#
# Exact copy of tests/core/test_safety_pattern_liveness.py:_THROTTLE_BYPASS_PATTERNS
# (commit dca5ff5). That test's ``test_throttle_bypass_patterns_are_current``
# pins the set; keep this in sync with it.
_THROTTLE_BYPASS_PATTERNS: frozenset[str] = frozenset({re.escape("system/disk_free_gb")})


@dataclass(frozen=True, slots=True)
class _DeadPattern:
    pattern: str
    plane: str
    source: str


def _load_interlock_conditions(config_path: Path) -> list[InterlockCondition]:
    """Parse interlocks.yaml into InterlockConditions.

    Mirrors the production ``InterlockEngine.load_config`` entry construction
    (src/cryodaq/core/interlock.py:309-319). ``InterlockCondition.__post_init__``
    compiles + validates the pattern identically, and ``matches_channel()`` is
    the production matcher (``_pattern.match``) — reusing it here avoids
    hand-duplicating regex semantics. ``InterlockEngine`` itself cannot be
    reused as the loader here because ``add_condition`` rejects every action
    not present in the engine's actions dict; the validator needs only the
    compiled patterns, not action dispatch.
    """
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    entries = raw.get("interlocks", []) if isinstance(raw, dict) else []
    conditions: list[InterlockCondition] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            conditions.append(
                InterlockCondition(
                    name=entry["name"],
                    description=entry.get("description", ""),
                    channel_pattern=entry["channel_pattern"],
                    threshold=float(entry.get("threshold", 0.0)),
                    comparison=entry.get("comparison", ">"),
                    action=entry.get("action", ""),
                    cooldown_s=float(entry.get("cooldown_s", 0.0)),
                )
            )
        except (KeyError, ValueError, TypeError, re.error):
            # A structurally-invalid interlock is OUT OF SCOPE for this
            # liveness diagnostic. InterlockEngine.load_config later raises
            # InterlockConfigError on the same entry before acquisition starts
            # (src/cryodaq/core/interlock.py:322-326). Skip it here rather than
            # replace that authoritative configuration error with a confusing
            # liveness message.
            continue
    return conditions


def validate_safety_pattern_liveness(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    interlocks_config_path: Path,
    safety_manager: SafetyManager,
    adaptive_throttle_patterns: Collection[str],
) -> None:
    """Raise if any CRITICAL/safety channel-pattern is dead against the
    SELECTED descriptor manifest, on the plane its consumer sees.

    Reuses the engine's already-loaded ``safety_manager`` (the actual runtime
    SafetyManager with its compiled critical/keithley patterns) and the
    already-computed ``adaptive_throttle_patterns``: the exact union of legacy
    interlock patterns and alarms-v3 protected patterns supplied to the
    runtime ``AdaptiveThrottle``.  No safety config is parsed twice at boot.
    Only ``interlocks_config_path`` is read here, to build
    ``InterlockCondition`` objects for the canonical ``.match`` matcher.

    Raises ``SafetyPatternLivenessError`` (a ``SafetyConfigError``) listing
    every dead pattern with its plane and config source. Returns cleanly when
    all CRITICAL/safety patterns are live. WARNING/INFO-only refs are NOT
    checked.

    Severity scope (fail-closed ONLY for these — when in doubt, do NOT raise,
    because a false fail-closed that bricks the lab is the worse outcome):

      1. ``interlocks.yaml`` — every interlock is safety-class. CANONICAL plane,
         ``.match`` (``InterlockCondition.matches_channel``).
      2. ``safety.yaml`` ``critical_channels`` — RAW plane, ``.match``.
      3. ``safety.yaml`` ``keithley_channels`` — RAW plane, ``.match`` (source
         heartbeat watchdog, src/cryodaq/core/safety_manager.py:1794).
      4. The exact runtime ``AdaptiveThrottle`` protected-pattern union:
         legacy ``interlocks.yaml`` patterns plus ``alarms_v3.yaml`` patterns
         derived from CRITICAL/HIGH alarms and all v3 interlocks. RAW plane,
         ``.search`` (substring).

    ``descriptor_catalog`` is whichever manifest the engine actually selected
    for this run (base ``channel_descriptors.yaml`` or the complete local
    replacement when ``instruments.local.yaml`` is active) — see
    src/cryodaq/engine.py:_load_live_descriptor_authority. This closes the gap
    left by the base-manifest-only regression test.

    Planes, matchers, and bypass are proven in
    tests/core/test_safety_pattern_liveness.py (commit dca5ff5).
    """
    catalog = descriptor_catalog.storage_catalog_snapshot()
    canonical_ids = sorted(catalog.by_channel_id)
    # ``_bindings`` maps (instrument_id, emitted_channel) -> channel_id
    # (src/cryodaq/storage/channel_descriptors.py:817). The emitted_channel key
    # is the raw pre-bind label the RAW-plane consumers see. Same access path
    # as the proven regression test (tests/core/test_safety_pattern_liveness.py).
    raw_labels = sorted({emitted for (_instr, emitted) in descriptor_catalog._bindings})

    dead: list[_DeadPattern] = []

    # Plane 1: interlocks (CANONICAL, .match). All interlocks are safety.
    for condition in _load_interlock_conditions(interlocks_config_path):
        if not any(condition.matches_channel(cid) for cid in canonical_ids):
            dead.append(
                _DeadPattern(
                    pattern=condition.channel_pattern,
                    plane="canonical (InterlockEngine post-bind channel_id, .match)",
                    source=f"{interlocks_config_path.name} (interlock {condition.name!r})",
                )
            )

    # Plane 2: safety.yaml critical_channels (RAW, .match).
    for pattern in safety_manager._config.critical_channels:
        if not any(pattern.match(ch) for ch in raw_labels):
            dead.append(
                _DeadPattern(
                    pattern=pattern.pattern,
                    plane="raw (SafetyManager pre-bind emitted label, .match)",
                    source="safety.yaml critical_channels",
                )
            )

    # Plane 3: safety.yaml keithley_channels (RAW, .match). Source heartbeat.
    # ``_keithley_patterns`` holds the YAML-loaded compiled patterns
    # (src/cryodaq/core/safety_manager.py:257) — the actual runtime value the
    # heartbeat watchdog matches, not the dataclass default.
    for pattern in safety_manager._keithley_patterns:
        if not any(pattern.match(ch) for ch in raw_labels):
            dead.append(
                _DeadPattern(
                    pattern=pattern.pattern,
                    plane="raw (SafetyManager heartbeat pre-bind, .match)",
                    source="safety.yaml keithley_channels",
                )
            )

    # Plane 4: the exact AdaptiveThrottle protected-pattern union (RAW,
    # .search substring), MINUS the direct-to-DataBroker bypass set
    # (system/disk_free_gb etc.).
    for ref in sorted(set(adaptive_throttle_patterns) - _THROTTLE_BYPASS_PATTERNS):
        compiled = re.compile(ref)
        if not any(compiled.search(ch) for ch in raw_labels):
            dead.append(
                _DeadPattern(
                    pattern=ref,
                    plane="raw substring (AdaptiveThrottle pre-bind, .search)",
                    source="AdaptiveThrottle protected patterns "
                    "(legacy interlocks + alarms_v3 CRITICAL/HIGH/interlocks)",
                )
            )

    if dead:
        lines = [
            f"Startup safety-pattern liveness check FAILED: {len(dead)} "
            f"CRITICAL/safety channel pattern(s) match NO channel on the plane "
            f"their consumer sees (F-1 silent safety kill). Correct each one in "
            f"its config file before permanent fail-closed activation:",
        ]
        for d in dead:
            lines.append(f"  - pattern={d.pattern!r} plane={d.plane} source={d.source}")
        lines.append(f"Canonical roster sample: {canonical_ids[:6]}. Raw roster sample: {raw_labels[:6]}.")
        raise SafetyPatternLivenessError("\n".join(lines))
