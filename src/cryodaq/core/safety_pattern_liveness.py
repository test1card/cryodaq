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


def _resolve_critical_patterns_to_raw(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    canonical_ids: list[str],
    raw_labels: list[str],
    patterns: list[re.Pattern[str]],
) -> tuple[list[re.Pattern[str]], list[_DeadPattern]]:
    """Resolve canonical critical identities to exact raw emitted labels.

    ``safety.yaml`` names the stable canonical identities.  SafetyManager's
    broker still receives the pre-bind emitted label, so production startup
    must resolve each canonical identity through the selected descriptor
    bindings and install a full-string escaped raw matcher.  A zero, multiple,
    missing, or colliding mapping is a configuration fault; silently falling
    back to a substring or alias would make the safety plane ambiguous.
    """

    storage_catalog = descriptor_catalog.storage_catalog_snapshot()
    raw_by_canonical: dict[str, list[str]] = {channel_id: [] for channel_id in canonical_ids}
    for (instrument_id, emitted_channel), channel_id in descriptor_catalog._bindings.items():
        if channel_id not in raw_by_canonical or emitted_channel not in raw_labels:
            continue
        descriptor = storage_catalog.by_channel_id.get(channel_id)
        if descriptor is None or descriptor.instrument_id != instrument_id:
            continue
        raw_by_canonical[channel_id].append(emitted_channel)
    raw_owners: dict[str, set[str]] = {}
    for channel_id, labels in raw_by_canonical.items():
        for label in labels:
            raw_owners.setdefault(label, set()).add(channel_id)
    colliding_raw = {label for label, owners in raw_owners.items() if len(owners) > 1}

    resolved: list[re.Pattern[str]] = []
    dead: list[_DeadPattern] = []
    for pattern in patterns:
        matches = [channel_id for channel_id in canonical_ids if pattern.fullmatch(channel_id)]
        if len(matches) != 1:
            dead.append(
                _DeadPattern(
                    pattern=pattern.pattern,
                    plane="canonical identity resolution to raw emitted label",
                    source="safety.yaml critical_channels",
                )
            )
            continue
        raw_matches = raw_by_canonical.get(matches[0], [])
        if len(raw_matches) != 1 or raw_matches[0] in colliding_raw:
            dead.append(
                _DeadPattern(
                    pattern=pattern.pattern,
                    plane="descriptor reverse binding to raw emitted label",
                    source="safety.yaml critical_channels",
                )
            )
            continue
        resolved.append(re.compile(rf"^{re.escape(raw_matches[0])}$"))
    return resolved, dead


def _resolve_adaptive_patterns_to_raw(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    canonical_ids: list[str],
    raw_labels: list[str],
    patterns: Collection[str],
) -> tuple[list[str], list[_DeadPattern]]:
    """Expand canonical AdaptiveThrottle expressions to exact raw labels.

    AdaptiveThrottle consumes pre-bind emitted labels.  Passing the canonical
    interlock expressions directly to its substring matcher is unsafe (and
    can make ``Т1`` collide with ``Т10``/``Т19``).  Every canonical match is
    therefore reverse-mapped to one full-string escaped raw label.  The disk
    channel is the sole explicit bypass because it is published directly to
    the broker and has no descriptor binding.
    """

    storage_catalog = descriptor_catalog.storage_catalog_snapshot()
    raw_by_canonical: dict[str, list[str]] = {channel_id: [] for channel_id in canonical_ids}
    for (instrument_id, emitted_channel), channel_id in descriptor_catalog._bindings.items():
        if channel_id not in raw_by_canonical or emitted_channel not in raw_labels:
            continue
        descriptor = storage_catalog.by_channel_id.get(channel_id)
        if descriptor is not None and descriptor.instrument_id == instrument_id:
            raw_by_canonical[channel_id].append(emitted_channel)
    raw_owners: dict[str, set[str]] = {}
    for channel_id, labels in raw_by_canonical.items():
        for label in labels:
            raw_owners.setdefault(label, set()).add(channel_id)
    colliding_raw = {label for label, owners in raw_owners.items() if len(owners) > 1}

    resolved: list[str] = []
    dead: list[_DeadPattern] = []
    for ref in sorted(set(patterns)):
        if ref in _THROTTLE_BYPASS_PATTERNS:
            resolved.append(ref)
            continue
        try:
            compiled = re.compile(ref)
        except re.error:
            dead.append(
                _DeadPattern(
                    pattern=ref,
                    plane="canonical AdaptiveThrottle expression",
                    source="AdaptiveThrottle protected patterns",
                )
            )
            continue
        canonical_matches = [channel_id for channel_id in canonical_ids if compiled.fullmatch(channel_id)]
        if not canonical_matches:
            dead.append(
                _DeadPattern(
                    pattern=ref,
                    plane="canonical AdaptiveThrottle expression",
                    source="AdaptiveThrottle protected patterns",
                )
            )
            continue
        for channel_id in canonical_matches:
            raw_matches = raw_by_canonical.get(channel_id, [])
            if len(raw_matches) != 1 or raw_matches[0] in colliding_raw:
                dead.append(
                    _DeadPattern(
                        pattern=ref,
                        plane="descriptor reverse binding to raw emitted label",
                        source="AdaptiveThrottle protected patterns",
                    )
                )
                continue
            resolved.append(rf"^{re.escape(raw_matches[0])}$")
    return resolved, dead


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
) -> list[str]:
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

    # Plane 2: safety.yaml names canonical identities, while SafetyManager
    # consumes raw labels. Resolve and install the exact reverse bindings
    # before any safety monitor starts.
    # Keep the canonical source immutable and resolve it on every validation.
    # The descriptor authority can be replaced at runtime, so a previously
    # resolved raw matcher must never be reused for a new descriptor snapshot.
    # ``load_config`` refreshes this source whenever safety.yaml is reloaded;
    # the fallback is only for test doubles that expose a SafetyConfig without
    # the normal loader.
    canonical_patterns = getattr(safety_manager, "_canonical_critical_patterns", None)
    if canonical_patterns is None:
        canonical_patterns = list(safety_manager._config.critical_channels)
        safety_manager._canonical_critical_patterns = list(canonical_patterns)
    else:
        canonical_patterns = list(canonical_patterns)
    resolved_critical, critical_dead = _resolve_critical_patterns_to_raw(
        descriptor_catalog=descriptor_catalog,
        canonical_ids=canonical_ids,
        raw_labels=raw_labels,
        patterns=list(canonical_patterns),
    )
    dead.extend(critical_dead)
    critical_manifest_ids = {
        channel_id
        for channel_id, descriptor in catalog.by_channel_id.items()
        if getattr(getattr(descriptor, "quantity", None), "value", None) == "temperature"
        and getattr(getattr(descriptor, "safety_class", None), "value", None) == "safety_critical_input"
    }
    matched_critical_ids: set[str] = set()
    for pattern in canonical_patterns:
        for channel_id in canonical_ids:
            if pattern.fullmatch(channel_id):
                matched_critical_ids.add(channel_id)
    if critical_manifest_ids and matched_critical_ids != critical_manifest_ids:
        dead.append(
            _DeadPattern(
                pattern=f"manifest={sorted(critical_manifest_ids)!r}",
                plane="canonical critical-temperature identity union",
                source="selected descriptor manifest vs safety.yaml critical_channels",
            )
        )
    if critical_dead:
        # Do not leave an earlier successful raw resolution installed after a
        # failed descriptor/configuration replacement. Boot fails below, and
        # an empty runtime matcher is fail-closed if inspected before raise.
        safety_manager._config.critical_channels = []
    else:
        safety_manager._config.critical_channels = resolved_critical

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

    # Plane 4: canonical protected expressions must be resolved before they
    # reach AdaptiveThrottle's raw substring matcher.  The returned list is
    # the only production input accepted by that plane.
    resolved_adaptive, adaptive_dead = _resolve_adaptive_patterns_to_raw(
        descriptor_catalog=descriptor_catalog,
        canonical_ids=canonical_ids,
        raw_labels=raw_labels,
        patterns=adaptive_throttle_patterns,
    )
    dead.extend(adaptive_dead)

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
    return resolved_adaptive
