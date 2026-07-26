"""Startup liveness validator for safety channel-matching patterns.

Guards the F-1 "silent safety kill" class at BOOT. A safety alarm/interlock
pattern is matched against a channel roster on a specific "plane". If a channel
rename makes a CRITICAL/safety pattern match NOTHING, the safety rule is
silently inert — it protects a channel that no longer exists under that name.
This module raises if any such pattern is dead against the ACTUALLY-SELECTED
descriptor manifest, so the failure is loud at boot instead of silent at
runtime. The same reasoning applies to every alarm reference regardless of
severity — a misspelled WARNING channel annunciates nothing just as silently
as a misspelled CRITICAL one — so alarm references are checked at all
severities (plane 5), with an explicit per-reference ``optional_channels``
opt-out for hardware a given lab does not populate. The opt-out is limited to
non-safety alarms, must be an exact list of unique channel strings, and cannot
silence a required composite/rate-condition arm. The engine's current
temporary lab-build policy catches
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

from cryodaq.core.housekeeping import _extract_channel_refs
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

# Channels that legitimately reach the ALARM plane without appearing in the
# descriptor manifest, because their publisher writes straight to the
# DataBroker instead of being scheduled from a descriptor-bound instrument.
# The alarm-v2 feed reads a DataBroker queue (src/cryodaq/engine.py:7233
# ``broker=broker``; src/cryodaq/engine_wiring/runtime_tasks.py:48
# ``state_tracker.update(reading)``), so such a channel IS live for alarms even
# though it has no descriptor row. DiskMonitor is the sole member today — it
# calls ``await self._broker.publish(reading)`` with channel
# ``system/disk_free_gb`` (src/cryodaq/core/disk_monitor.py:85,91).
#
# NOTE the difference from ``_THROTTLE_BYPASS_PATTERNS`` above: that set carves
# the disk channel OUT of the throttle plane (it never passes through the
# throttle); this set carves it INTO the alarm plane (it does reach the alarm
# evaluator). Same channel, opposite reasons — do not merge the two sets.
# ``test_non_descriptor_alarm_channels_are_current`` pins this membership.
_NON_DESCRIPTOR_ALARM_CHANNELS: frozenset[str] = frozenset({"system/disk_free_gb"})

# Pseudo-channels that are NOT channel names at all: the evaluator re-routes
# them to a non-broker data source. ``_resolve_channels`` explicitly refuses to
# resolve ``phase_elapsed_s`` (src/cryodaq/core/alarm_v2.py:600) and the
# ``above`` sub-condition re-routes it to the phase provider — the reasoning is
# written out in full at src/cryodaq/core/alarm_config.py:333-349. Requiring a
# roster entry for one would be a guaranteed false positive.
_ALARM_PSEUDO_CHANNELS: frozenset[str] = frozenset({"phase_elapsed_s"})

# Alarm-level key declaring which of that alarm's own channel references may be
# absent from the roster (optional / unpopulated hardware at a given lab). This
# is the ONLY sanctioned way to silence the liveness check for a reference, and
# it is per-reference and visible in the config: silence is opt-IN and named,
# never a blanket severity exclusion. The key is inert to the alarm loader,
# which stores the raw dict verbatim (src/cryodaq/core/alarm_config.py:254-259)
# and rejects only unknown *enum values*, not unknown keys.
_OPTIONAL_CHANNELS_KEY = "optional_channels"

# Match the existing ``load_critical_channels_from_alarms_v3`` classification:
# ``HIGH`` is a legacy spelling that participates in the critical protection
# path, so it must not receive a weaker liveness escape hatch. The
# ``interlocks`` section is safety-class irrespective of a ``level`` field.
_SAFETY_ALARM_LEVELS = frozenset({"critical", "high"})


@dataclass(frozen=True, slots=True)
class _DeadPattern:
    pattern: str
    plane: str
    source: str


def _alarm_channel_resolution_set(canonical_ids: Collection[str]) -> set[str]:
    """Names an alarm channel reference may legitimately carry.

    The alarm evaluator looks its channels up in ``ChannelStateTracker``, which
    is keyed by the published ``Reading.channel`` — the CANONICAL post-bind
    identity, because the alarm-v2 feed consumes a DataBroker queue and the
    DataBroker carries the post-bind canonical stream
    (src/cryodaq/core/scheduler.py:676 ``committed_publish_readings``).
    ``ChannelStateTracker.get`` first tries the exact key, then a short-prefix
    alias built as ``channel.split(" ", 1)[0]``
    (src/cryodaq/core/channel_state.py:90,105-111), so both spellings resolve
    at runtime and both must be accepted here. Today canonical ids carry no
    space, making the prefix set identical to the id set; including it anyway
    keeps a future spaced-identity manifest from producing a false failure.
    """
    resolvable = set(canonical_ids)
    resolvable |= {cid.split(" ", 1)[0] for cid in canonical_ids if " " in cid}
    resolvable |= _NON_DESCRIPTOR_ALARM_CHANNELS
    return resolvable


def _iter_alarm_entries(data: dict) -> list[tuple[str, dict]]:
    """Yield ``(source_label, alarm_dict)`` for every alarm in alarms_v3.yaml.

    Covers the three sections the production loader reads: flat
    ``global_alarms``, nested ``phase_alarms`` (phase -> alarm_id -> alarm) and
    ``interlocks`` (src/cryodaq/core/alarm_config.py:116-141). Severity is NOT
    consulted: a dead reference blinds a WARNING annunciator exactly as
    silently as a CRITICAL one.
    """
    entries: list[tuple[str, dict]] = []
    for alarm_id, alarm in (data.get("global_alarms") or {}).items():
        if isinstance(alarm, dict):
            entries.append((f"global_alarms/{alarm_id}", alarm))
    for phase_name, section in (data.get("phase_alarms") or {}).items():
        if not isinstance(section, dict):
            continue
        for alarm_id, alarm in section.items():
            if isinstance(alarm, dict):
                entries.append((f"phase_alarms/{phase_name}/{alarm_id}", alarm))
    for alarm_id, alarm in (data.get("interlocks") or {}).items():
        if isinstance(alarm, dict):
            entries.append((f"interlocks/{alarm_id}", alarm))
    return entries


def _optional_channels_for_alarm(*, source_name: str, label: str, alarm: dict) -> set[str]:
    """Validate and return one non-safety alarm's optional channel references.

    ``optional_channels`` changes a liveness failure into an intentional
    absence, so it is never valid for a CRITICAL/HIGH alarm or an alarm-v3
    interlock. YAML mappings are iterable and must not be accepted as a
    convenient list of keys; accepting one would silently grant the escape
    hatch to references the operator did not explicitly declare.
    """
    if _OPTIONAL_CHANNELS_KEY not in alarm:
        return set()

    location = f"{source_name} alarm {label!r} key {_OPTIONAL_CHANNELS_KEY!r}"
    level = str(alarm.get("level", "")).strip().lower()
    if label.startswith("interlocks/") or level in _SAFETY_ALARM_LEVELS:
        raise SafetyPatternLivenessError(
            f"{location} is forbidden for CRITICAL/HIGH or interlock safety alarms. "
            "Remove the key and provision or correct every referenced channel; "
            "a safety reference must remain live."
        )

    value = alarm[_OPTIONAL_CHANNELS_KEY]
    if type(value) is not list:
        raise SafetyPatternLivenessError(
            f"{location} must be an exact list of unique non-empty channel strings, "
            f"got {type(value).__name__}. Replace it with a YAML list or remove the key "
            "so a dangling reference fails validation."
        )

    declared: set[str] = set()
    for index, item in enumerate(value):
        if type(item) is not str:
            raise SafetyPatternLivenessError(
                f"{location} item {index} must be a channel string, got {type(item).__name__}. "
                "Replace it with a unique channel string or remove the key so a dangling "
                "reference fails validation."
            )
        channel = item.strip()
        if not channel:
            raise SafetyPatternLivenessError(
                f"{location} item {index} must be a non-empty channel string. "
                "Replace it with a unique channel string or remove the key so a dangling "
                "reference fails validation."
            )
        if channel in declared:
            raise SafetyPatternLivenessError(
                f"{location} repeats channel {channel!r}. Use each optional channel once, "
                "or remove the key so a dangling reference fails validation."
            )
        declared.add(channel)
    return declared


def _reject_optional_required_condition_arms(
    *, source_name: str, label: str, alarm: dict, declared_optional: set[str]
) -> None:
    """Reject opt-outs that make an otherwise-required condition permanently false."""
    if not declared_optional:
        return

    conditions: list[tuple[str, object]] = []
    if alarm.get("alarm_type") == "composite" and alarm.get("operator", "AND") == "AND":
        for index, condition in enumerate(alarm.get("conditions", [])):
            conditions.append((f"AND composite condition {index}", condition))
    if alarm.get("alarm_type") == "rate" and "additional_condition" in alarm:
        conditions.append(("rate additional_condition", alarm["additional_condition"]))

    for context, condition in conditions:
        if not isinstance(condition, dict):
            continue
        refs = {
            ref
            for ref in _extract_channel_refs(condition)
            if not ref.startswith("__group__:") and ref not in _ALARM_PSEUDO_CHANNELS
        }
        optional_refs = refs & declared_optional
        if refs and refs <= declared_optional:
            location = f"{source_name} alarm {label!r} key {_OPTIONAL_CHANNELS_KEY!r}"
            raise SafetyPatternLivenessError(
                f"{location} makes required {context} unavailable via {sorted(optional_refs)!r}. "
                "Remove those optional declarations or redesign the alarm so unpopulated "
                "hardware is not a required condition."
            )


def _collect_dead_alarm_channel_refs(
    *,
    alarms_config_path: Path,
    canonical_ids: Collection[str],
) -> list[_DeadPattern]:
    """Find alarm channel references that resolve to NO real channel.

    Applies to EVERY severity. A WARNING or INFO alarm whose channel reference
    is misspelled loads cleanly, evaluates forever against a channel that never
    reports, and never fires — the operator sees a configured annunciator and
    gets no protection. That is the same silent-inertness class the CRITICAL
    planes above exist to prevent, so it is checked the same way.

    A missing alarms file is not this validator's error to raise: the engine
    already fails closed on it through ``load_alarm_config``
    (src/cryodaq/engine.py:6614, ``AlarmConfigError``). Same for a file that
    fails to parse. Returning no findings here leaves that authoritative error
    in place instead of shadowing it with a confusing liveness message.
    """
    if not alarms_config_path.exists():
        return []
    try:
        with alarms_config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    raw_groups = data.get("channel_groups") or {}
    groups: dict[str, list[str]] = {}
    if isinstance(raw_groups, dict):
        for name, channels in raw_groups.items():
            if isinstance(channels, list):
                groups[str(name)] = [str(c) for c in channels if isinstance(c, str)]

    resolvable = _alarm_channel_resolution_set(canonical_ids)
    source_name = alarms_config_path.name
    dead: list[_DeadPattern] = []

    for label, alarm in _iter_alarm_entries(data):
        declared_optional = _optional_channels_for_alarm(
            source_name=source_name,
            label=label,
            alarm=alarm,
        )
        _reject_optional_required_condition_arms(
            source_name=source_name,
            label=label,
            alarm=alarm,
            declared_optional=declared_optional,
        )
        # ``_extract_channel_refs`` is the production ref traversal
        # (src/cryodaq/core/housekeeping.py:106) and is reused rather than
        # re-implemented so the two never drift over which nested shapes
        # (composite ``conditions``, rate ``additional_condition``) carry a
        # channel. It yields group references as ``__group__:<name>`` and
        # ignores bare strings inside other lists, so ``optional_channels``
        # itself contributes no references.
        for ref in _extract_channel_refs(alarm):
            if ref.startswith("__group__:"):
                group_name = ref.removeprefix("__group__:")
                members = groups.get(group_name)
                if members is None:
                    dead.append(
                        _DeadPattern(
                            pattern=f"channel_group:{group_name}",
                            plane="alarm annunciation (canonical post-bind channel_id)",
                            source=f"{source_name} (alarm {label!r})",
                        )
                    )
                    continue
                candidates = [(member, f"{member!r} via channel_group {group_name!r}") for member in members]
            else:
                candidates = [(ref, repr(ref))]

            for channel, described in candidates:
                if channel in _ALARM_PSEUDO_CHANNELS or channel in declared_optional:
                    continue
                if channel in resolvable:
                    continue
                dead.append(
                    _DeadPattern(
                        pattern=described,
                        plane="alarm annunciation (canonical post-bind channel_id)",
                        source=f"{source_name} (alarm {label!r})",
                    )
                )
    return dead


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
    alarms_config_path: Path | None = None,
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
    all checked patterns are live.

    ``alarms_config_path`` defaults to ``alarms_v3.yaml`` beside
    ``interlocks_config_path``. In production those are the same directory:
    the engine resolves both from ``_CONFIG_DIR`` (src/cryodaq/engine.py:6433
    ``_CONFIG_DIR / "alarms_v3.yaml"`` and ``_engine_config_path("interlocks")``
    at src/cryodaq/engine.py:2236-2239, which only ever returns
    ``_CONFIG_DIR/interlocks[.local].yaml``), so the default reproduces the
    production pairing exactly rather than guessing it. Pass the argument
    explicitly to validate a manifest pair that does not live side by side.

    Scope (fail-closed for these — when in doubt, do NOT raise, because a false
    fail-closed that bricks the lab is the worse outcome):

      1. ``interlocks.yaml`` — every interlock is safety-class. CANONICAL plane,
         ``.match`` (``InterlockCondition.matches_channel``).
      2. ``safety.yaml`` ``critical_channels`` — RAW plane, ``.match``.
      3. ``safety.yaml`` ``keithley_channels`` — RAW plane, ``.match`` (source
         heartbeat watchdog, existential per active SMU in
         ``SafetyManager._has_fresh_keithley_data``).
      4. The exact runtime ``AdaptiveThrottle`` protected-pattern union:
         legacy ``interlocks.yaml`` patterns plus ``alarms_v3.yaml`` patterns
         derived from CRITICAL/HIGH alarms and all v3 interlocks. RAW plane,
         ``.search`` (substring).
      5. ``alarms_v3.yaml`` channel references, at EVERY severity. CANONICAL
         plane, exact key (with the tracker's short-prefix alias). Severity is
         deliberately not a filter here: plane 4 above only sees the channels
         of CRITICAL/HIGH alarms because its purpose is throttle protection,
         which left a typo in a WARNING or INFO alarm loading cleanly and
         annunciating nothing, forever. Adding a channel alarm is the single
         most common adaptation a new lab makes, so that reference is exactly
         the one that must fail loudly rather than silently. Per-reference
         opt-out via ``optional_channels`` is limited to non-CRITICAL,
         non-HIGH, non-interlock alarms; see
         ``_collect_dead_alarm_channel_refs``.

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
        matched_channels = {channel for channel in raw_labels if pattern.match(channel)}
        if not matched_channels:
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

    # Plane 5: every alarms_v3.yaml channel reference, at every severity, on
    # the plane the alarm evaluator actually reads.
    resolved_alarms_path = (
        alarms_config_path if alarms_config_path is not None else interlocks_config_path.parent / "alarms_v3.yaml"
    )
    dead.extend(
        _collect_dead_alarm_channel_refs(
            alarms_config_path=resolved_alarms_path,
            canonical_ids=canonical_ids,
        )
    )

    if dead:
        lines = [
            "Startup safety-pattern liveness check FAILED: safety monitoring must be live before startup:",
        ]
        if dead:
            lines.append(
                f"Dead safety/alarm channel pattern(s): {len(dead)} match NO "
                "channel on the plane their consumer sees (F-1 silent safety kill). "
                "An alarm reference that resolves to nothing never fires; correct or "
                "provision it. Only a non-CRITICAL, non-HIGH, non-interlock alarm may "
                f"declare a legitimately absent channel under {_OPTIONAL_CHANNELS_KEY!r}; "
                "safety references must remain live."
            )
            for d in dead:
                lines.append(f"  - pattern={d.pattern!r} plane={d.plane} source={d.source}")
        lines.append(f"Canonical roster sample: {canonical_ids[:6]}. Raw roster sample: {raw_labels[:6]}.")
        raise SafetyPatternLivenessError("\n".join(lines))
    return resolved_adaptive
