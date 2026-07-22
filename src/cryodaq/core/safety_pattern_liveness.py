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

from cryodaq.channels.descriptors import ChannelQuantity, ChannelSafetyClass
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


@dataclass(frozen=True, slots=True)
class ResolvedRawChannelBinding:
    """One canonical descriptor identity projected onto the raw input plane.

    ``raw_pattern`` is deliberately a full-string regular expression because
    AdaptiveThrottle uses ``search`` while SafetyManager uses ``match``.  The
    exact anchors make both consumers select only this one manifest binding.
    """

    canonical_channel_id: str
    emitted_channel: str
    raw_pattern: str


def _full_string_raw_pattern(emitted_channel: str) -> str:
    """Return an exact raw-plane matcher safe for both ``match`` and ``search``."""

    return rf"\A{re.escape(emitted_channel)}\Z"


def _binding_for_canonical_channel(
    descriptor_catalog: LiveChannelDescriptorCatalog,
    channel_id: str,
) -> ResolvedRawChannelBinding:
    """Reverse one manifest identity binding without accepting aliases."""

    candidates = [
        emitted_channel
        for (_instrument_id, emitted_channel), bound_id in descriptor_catalog._bindings.items()
        if bound_id == channel_id
    ]
    if len(candidates) != 1:
        raise SafetyPatternLivenessError(
            "canonical channel must have exactly one emitted binding for raw-plane safety "
            f"resolution: {channel_id!r} had {len(candidates)}"
        )
    emitted_channel = candidates[0]
    if channel_id.endswith(".raw") or emitted_channel.endswith("_raw"):
        raise SafetyPatternLivenessError(
            f"canonical safety pattern resolved an observational raw companion: {channel_id!r} -> {emitted_channel!r}"
        )
    return ResolvedRawChannelBinding(
        canonical_channel_id=channel_id,
        emitted_channel=emitted_channel,
        raw_pattern=_full_string_raw_pattern(emitted_channel),
    )


def resolve_canonical_patterns_to_raw_bindings(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    canonical_patterns: Collection[re.Pattern[str]],
) -> tuple[ResolvedRawChannelBinding, ...]:
    """Resolve canonical patterns to exact emitted labels, fail-closed.

    Canonical identifiers are matched with ``fullmatch`` regardless of the
    eventual raw-plane consumer.  This prevents a policy such as ``Т1`` from
    selecting ``Т10`` through ``Т19`` or a ``*.raw`` observational companion.
    Every selected canonical identity must have one manifest binding, and two
    policy patterns may not silently collide on the same raw label.
    """

    catalog = descriptor_catalog.storage_catalog_snapshot()
    canonical_ids = tuple(catalog.by_channel_id)
    resolved: list[ResolvedRawChannelBinding] = []
    seen_raw: dict[str, str] = {}

    for pattern in canonical_patterns:
        if not isinstance(pattern, re.Pattern):
            raise SafetyPatternLivenessError("canonical safety pattern must be a compiled regular expression")
        matches = [channel_id for channel_id in canonical_ids if pattern.fullmatch(channel_id)]
        if not matches:
            raise SafetyPatternLivenessError(
                f"canonical safety pattern matches no descriptor identity: {pattern.pattern!r}"
            )
        for channel_id in matches:
            binding = _binding_for_canonical_channel(descriptor_catalog, channel_id)
            previous = seen_raw.get(binding.emitted_channel)
            if previous is not None and previous != binding.canonical_channel_id:
                raise SafetyPatternLivenessError(
                    f"canonical safety patterns collide on one raw emitted label: {binding.emitted_channel!r}"
                )
            if previous is None:
                seen_raw[binding.emitted_channel] = binding.canonical_channel_id
                resolved.append(binding)
    return tuple(resolved)


def resolve_adaptive_throttle_patterns(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    patterns: Collection[str],
) -> tuple[str, ...]:
    """Project canonical protection refs onto the raw throttle input plane.

    Legacy interlock and alarms-v3 references are written using canonical
    channel identities.  AdaptiveThrottle sees pre-bind emitted labels, so a
    canonical regex is first evaluated with ``fullmatch`` against the selected
    descriptor snapshot and then reverse-mapped to an exact escaped raw label.
    References that match no canonical identity are retained as raw-plane
    expressions (for example Keithley power channels).  The disk channel is
    the sole explicit direct-to-broker bypass.
    """

    catalog = descriptor_catalog.storage_catalog_snapshot()
    canonical_ids = tuple(catalog.by_channel_id)
    projected: set[str] = set()
    for ref in patterns:
        if ref in _THROTTLE_BYPASS_PATTERNS:
            projected.add(ref)
            continue
        try:
            compiled = re.compile(ref)
        except re.error as exc:
            raise SafetyPatternLivenessError(f"invalid AdaptiveThrottle pattern: {ref!r}") from exc
        matches = [channel_id for channel_id in canonical_ids if compiled.fullmatch(channel_id)]
        if matches:
            bindings = resolve_canonical_patterns_to_raw_bindings(
                descriptor_catalog=descriptor_catalog,
                canonical_patterns=(compiled,),
            )
            projected.update(binding.raw_pattern for binding in bindings)
        else:
            projected.add(ref)
    return tuple(sorted(projected))


def resolve_safety_critical_temperature_bindings(
    *,
    descriptor_catalog: LiveChannelDescriptorCatalog,
    canonical_patterns: Collection[re.Pattern[str]],
) -> tuple[ResolvedRawChannelBinding, ...]:
    """Resolve exactly the manifest's safety-critical temperature identities.

    ``safety.yaml`` is canonical policy.  This projection is the only allowed
    route from that policy to SafetyManager's and AdaptiveThrottle's raw input
    planes.  It rejects zero/multiple identity matches, raw/observational
    companions, and a policy set that differs from the selected manifest's
    complete safety-critical temperature identity set.
    """

    catalog = descriptor_catalog.storage_catalog_snapshot()
    expected = {
        descriptor.channel_id
        for descriptor in catalog.descriptors
        if descriptor.quantity is ChannelQuantity.TEMPERATURE
        and descriptor.safety_class is ChannelSafetyClass.SAFETY_CRITICAL_INPUT
    }
    if not expected:
        raise SafetyPatternLivenessError("descriptor manifest has no safety-critical temperature identities")

    for pattern in canonical_patterns:
        matches = [channel_id for channel_id in catalog.by_channel_id if pattern.fullmatch(channel_id)]
        if len(matches) != 1:
            raise SafetyPatternLivenessError(
                "each safety-critical canonical pattern must resolve exactly one descriptor identity: "
                f"{pattern.pattern!r} had {len(matches)} matches"
            )

    resolved = resolve_canonical_patterns_to_raw_bindings(
        descriptor_catalog=descriptor_catalog,
        canonical_patterns=canonical_patterns,
    )
    actual = {binding.canonical_channel_id for binding in resolved}
    if actual != expected:
        raise SafetyPatternLivenessError(
            "safety critical canonical identities do not equal the manifest's "
            f"safety-critical temperature identities: expected={sorted(expected)!r} actual={sorted(actual)!r}"
        )

    for binding in resolved:
        descriptor = catalog.by_channel_id[binding.canonical_channel_id]
        if (
            descriptor.quantity is not ChannelQuantity.TEMPERATURE
            or descriptor.safety_class is not ChannelSafetyClass.SAFETY_CRITICAL_INPUT
        ):
            raise SafetyPatternLivenessError(
                "safety critical canonical pattern resolved a non-critical or non-temperature descriptor: "
                f"{binding.canonical_channel_id!r}"
            )
        if binding.canonical_channel_id.endswith(".raw") or binding.emitted_channel.endswith("_raw"):
            raise SafetyPatternLivenessError(
                "safety critical canonical pattern resolved an observational raw companion: "
                f"{binding.canonical_channel_id!r} -> {binding.emitted_channel!r}"
            )
    return resolved


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
      2. ``safety.yaml`` ``critical_channels`` — canonical identities resolved
         through the selected descriptor snapshot to exact raw bindings.
      3. ``safety.yaml`` ``keithley_channels`` — RAW plane, ``.match`` (source
         heartbeat watchdog, src/cryodaq/core/safety_manager.py:1794).
      4. The exact runtime ``AdaptiveThrottle`` protected-pattern union after
         canonical-to-raw descriptor resolution:
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

    # Plane 2: safety.yaml critical_channels are canonical policy identities.
    # Resolve them against the selected manifest before any raw-plane check;
    # passing these regexes directly to a raw consumer would make T1 match T10
    # and observational companions.
    try:
        critical_bindings = resolve_safety_critical_temperature_bindings(
            descriptor_catalog=descriptor_catalog,
            canonical_patterns=safety_manager._config.critical_channels,
        )
        for binding in critical_bindings:
            if not any(re.fullmatch(binding.raw_pattern, ch) for ch in raw_labels):
                dead.append(
                    _DeadPattern(
                        pattern=binding.canonical_channel_id,
                        plane="canonical -> exact raw (SafetyManager pre-bind emitted label)",
                        source="safety.yaml critical_channels",
                    )
                )
    except SafetyPatternLivenessError as exc:
        dead.append(
            _DeadPattern(
                pattern="<critical_channels>",
                plane="canonical -> exact raw (SafetyManager pre-bind emitted label)",
                source=f"safety.yaml critical_channels: {exc}",
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

    # Plane 4: the exact AdaptiveThrottle protected-pattern union after
    # canonical-to-raw resolution, MINUS the direct-to-DataBroker bypass set.
    try:
        projected_throttle_patterns = resolve_adaptive_throttle_patterns(
            descriptor_catalog=descriptor_catalog,
            patterns=adaptive_throttle_patterns,
        )
    except SafetyPatternLivenessError as exc:
        dead.append(
            _DeadPattern(
                pattern="<adaptive_throttle_patterns>",
                plane="canonical -> exact raw (AdaptiveThrottle pre-bind)",
                source=f"AdaptiveThrottle protected patterns: {exc}",
            )
        )
        projected_throttle_patterns = ()

    for ref in sorted(set(projected_throttle_patterns) - _THROTTLE_BYPASS_PATTERNS):
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
