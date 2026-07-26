"""Liveness guard for alarm channel references at EVERY severity.

The gap this closes: ``validate_safety_pattern_liveness`` used to validate only
CRITICAL/safety patterns, and its throttle plane only ever saw the channels of
CRITICAL/HIGH alarms (``load_critical_channels_from_alarms_v3`` filters on
``_CRITICAL_LEVELS``, src/cryodaq/core/housekeeping.py:103). A typo in a
WARNING or INFO alarm's channel reference was therefore syntactically valid,
loaded cleanly, and annunciated NOTHING — permanently, with no signal.

That matters most for the adaptation this product is built for: "add an alarm
for my new channel" is the most common change a new lab makes, and a silent
non-firing alarm reads exactly like a working one.

The plane checked here is the one the alarm evaluator actually reads: the
CANONICAL post-bind ``channel_id``. The alarm-v2 feed consumes a DataBroker
queue (src/cryodaq/engine.py:7233; src/cryodaq/engine_wiring/runtime_tasks.py:48)
and the DataBroker carries the post-bind canonical stream
(src/cryodaq/core/scheduler.py:676). ``ChannelStateTracker.get`` does an exact
key lookup after a short-prefix alias attempt
(src/cryodaq/core/channel_state.py:105-111).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.safety_pattern_liveness import (
    _NON_DESCRIPTOR_ALARM_CHANNELS,
    SafetyPatternLivenessError,
    validate_safety_pattern_liveness,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_DESCRIPTORS_PATH = _CONFIG_DIR / "channel_descriptors.yaml"
_INTERLOCKS_PATH = _CONFIG_DIR / "interlocks.yaml"
_SAFETY_PATH = _CONFIG_DIR / "safety.yaml"
_ALARMS_V3_PATH = _CONFIG_DIR / "alarms_v3.yaml"

_DISK_CHANNEL = "system/disk_free_gb"

# The one canonical identity carried by the minimal fixture manifest below.
_LIVE_CHANNEL = "source.heartbeat"
_RAW_LABEL = "source heartbeat"
_DEAD_CHANNEL = "Т99 Опечатка"


def _write_fixture_manifest(path: Path) -> None:
    """Minimal one-channel descriptor manifest (shape copied from the gate test)."""
    payload = {
        "schema_version": 1,
        "descriptors": [
            {
                "schema_version": 1,
                "channel_id": _LIVE_CHANNEL,
                "instrument_id": "source",
                "source_key": "input.1.temperature",
                "quantity": "temperature",
                "unit": "K",
                "role": "primary_measurement",
                # observational keeps the critical-temperature union check
                # (safety_pattern_liveness.py plane 2) out of this fixture, so a
                # failure here can only come from the alarm plane.
                "safety_class": "observational",
                "display_group": "test",
                "display_name": "Test channel",
                "visible_by_default": True,
                "display_order": 1,
                "descriptor_revision": 1,
            }
        ],
        "bindings": [
            {
                "instrument_id": "source",
                "emitted_channel": _RAW_LABEL,
                "channel_id": _LIVE_CHANNEL,
            }
        ],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_fixture(tmp_path: Path, alarms: dict) -> dict:
    """A config dir whose planes 1-4 are clean, so only the alarm plane can fail.

    ``interlocks.yaml`` and ``alarms_v3.yaml`` are written side by side exactly
    as production lays them out, so the validator's default sibling resolution
    of the alarms config is exercised rather than bypassed.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    descriptor_path = config_dir / "channel_descriptors.local.yaml"
    _write_fixture_manifest(descriptor_path)

    interlocks_path = config_dir / "interlocks.yaml"
    interlocks_path.write_text("interlocks: []\n", encoding="utf-8")

    (config_dir / "alarms_v3.yaml").write_text(
        yaml.safe_dump(alarms, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    safety_path = config_dir / "safety.yaml"
    # Single-quoted YAML scalars keep the regex backslash literal.
    safety_path.write_text(
        "critical_channels:\n  - '^source\\.heartbeat$'\nkeithley_channels:\n  - '^source heartbeat$'\n",
        encoding="utf-8",
    )
    safety_manager = SafetyManager(SafetyBroker())
    safety_manager.load_config(safety_path)

    return {
        "descriptor_catalog": load_live_channel_descriptor_catalog(descriptor_path),
        "interlocks_config_path": interlocks_path,
        "safety_manager": safety_manager,
        "adaptive_throttle_patterns": set(),
    }


def _alarm(level: str, channel: str, **extra: object) -> dict:
    alarm = {
        "alarm_type": "threshold",
        "check": "above",
        "channel": channel,
        "threshold": 300.0,
        "level": level,
        "message": "test alarm",
    }
    alarm.update(extra)
    return alarm


def test_fixture_without_alarms_validates_cleanly(tmp_path: Path) -> None:
    """Non-vacuity guard: the fixture's other planes are clean on their own.

    Without this, a later assertion that a dangling WARNING reference raises
    would not prove the ALARM plane caused it.
    """
    validate_safety_pattern_liveness(**_build_fixture(tmp_path, {"global_alarms": {}}))


def test_live_warning_alarm_reference_is_accepted(tmp_path: Path) -> None:
    """A WARNING alarm naming a real channel must not trip the gate."""
    alarms = {"global_alarms": {"ok_warning": _alarm("warning", _LIVE_CHANNEL)}}
    validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))


def test_warning_alarm_with_dangling_reference_is_rejected(tmp_path: Path) -> None:
    """THE FINDING: a typo'd WARNING channel ref must fail validation loudly.

    Before the fix this config loaded and ran; the alarm simply never fired.
    """
    alarms = {"global_alarms": {"new_lab_warning": _alarm("warning", _DEAD_CHANNEL)}}

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    message = str(exc_info.value)
    assert _DEAD_CHANNEL in message, "the offending reference must be named"
    assert "new_lab_warning" in message, "the offending alarm must be named"
    assert "alarms_v3.yaml" in message
    assert "alarm annunciation" in message


def test_info_alarm_with_dangling_reference_is_rejected(tmp_path: Path) -> None:
    """INFO severity is checked on the same terms as WARNING."""
    alarms = {"global_alarms": {"new_lab_info": _alarm("info", _DEAD_CHANNEL)}}

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    message = str(exc_info.value)
    assert _DEAD_CHANNEL in message
    assert "new_lab_info" in message


def test_dangling_reference_in_phase_alarm_is_rejected(tmp_path: Path) -> None:
    """Phase-scoped WARNING alarms are reached too, not only global ones."""
    alarms = {"phase_alarms": {"cooldown": {"phase_warning": _alarm("warning", _DEAD_CHANNEL)}}}

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    assert "phase_warning" in str(exc_info.value)


def test_dangling_group_member_is_rejected(tmp_path: Path) -> None:
    """A typo in ONE member of a channel_group must not hide behind live siblings."""
    alarms = {
        "channel_groups": {"lab_temps": [_LIVE_CHANNEL, _DEAD_CHANNEL]},
        "global_alarms": {
            "group_warning": {
                "alarm_type": "stale",
                "channel_group": "lab_temps",
                "timeout_s": 60.0,
                "level": "warning",
                "message": "test alarm",
            }
        },
    }

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    message = str(exc_info.value)
    assert _DEAD_CHANNEL in message
    assert "lab_temps" in message, "the group the dead member came from must be named"


def test_declared_optional_reference_is_permitted(tmp_path: Path) -> None:
    """The sanctioned opt-out: silence is opt-IN, per reference, and visible."""
    alarms = {
        "global_alarms": {
            "optional_hardware_warning": _alarm(
                "warning",
                _DEAD_CHANNEL,
                optional_channels=[_DEAD_CHANNEL],
            )
        }
    }
    validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))


def test_optional_declaration_does_not_silence_other_references(tmp_path: Path) -> None:
    """The opt-out is per reference — it must not become a per-alarm blanket."""
    other_dead = "Т98 Вторая опечатка"
    alarms = {
        "global_alarms": {
            "partially_optional": {
                "alarm_type": "stale",
                "channels": [_DEAD_CHANNEL, other_dead],
                "timeout_s": 60.0,
                "level": "warning",
                "message": "test alarm",
                "optional_channels": [_DEAD_CHANNEL],
            }
        }
    }

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    message = str(exc_info.value)
    assert other_dead in message, "the undeclared dangling reference must still fail"
    assert _DEAD_CHANNEL not in message, "the declared-optional reference must stay silent"


def test_optional_declaration_in_another_alarm_does_not_leak(tmp_path: Path) -> None:
    """An ``optional_channels`` declaration is scoped to its own alarm."""
    alarms = {
        "global_alarms": {
            "declares_it": _alarm("info", _DEAD_CHANNEL, optional_channels=[_DEAD_CHANNEL]),
            "does_not_declare_it": _alarm("warning", _DEAD_CHANNEL),
        }
    }

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))

    assert "does_not_declare_it" in str(exc_info.value)


def test_phase_elapsed_pseudo_channel_is_not_dead(tmp_path: Path) -> None:
    """``phase_elapsed_s`` is re-routed to the phase provider, not a roster channel.

    Treating it as a channel reference would be a guaranteed false fail-closed
    (src/cryodaq/core/alarm_v2.py:600; src/cryodaq/core/alarm_config.py:333-349).
    """
    alarms = {
        "phase_alarms": {
            "vacuum": {
                "elapsed_warning": _alarm("warning", "phase_elapsed_s"),
            }
        }
    }
    validate_safety_pattern_liveness(**_build_fixture(tmp_path, alarms))


def test_non_descriptor_alarm_channels_are_current() -> None:
    """Pin the direct-to-DataBroker allowlist against silent growth.

    A new entry here silences a real liveness check, so it must be a conscious
    edit with a cited publisher, not an accident.
    """
    assert _NON_DESCRIPTOR_ALARM_CHANNELS == frozenset({_DISK_CHANNEL})


def test_shipped_alarms_v3_has_no_dead_references() -> None:
    """The shipped config passes the check at EVERY severity.

    This is the evidence that enabling WARNING/INFO liveness broke nothing that
    ships: the sole reference absent from the descriptor manifest is the disk
    channel, which is live on the alarm plane via DiskMonitor's direct publish.
    """
    validate_safety_pattern_liveness(
        descriptor_catalog=load_live_channel_descriptor_catalog(_DESCRIPTORS_PATH),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=set(),
        alarms_config_path=_ALARMS_V3_PATH,
    )


def test_default_resolution_finds_the_shipped_alarms_config() -> None:
    """Production gets this check without passing the new argument.

    The engine calls the validator with ``interlocks_config_path=
    _engine_config_path("interlocks")``, which only ever returns
    ``_CONFIG_DIR/interlocks[.local].yaml`` (src/cryodaq/engine.py), and reads
    its alarms from ``_CONFIG_DIR/alarms_v3.yaml``. The sibling default must
    therefore land on the real shipped file — if it did not, the whole check
    would be silently inert in production, which is the very failure mode this
    module exists to prevent.
    """
    assert (_INTERLOCKS_PATH.parent / "alarms_v3.yaml") == _ALARMS_V3_PATH
    assert _ALARMS_V3_PATH.exists()

    validate_safety_pattern_liveness(
        descriptor_catalog=load_live_channel_descriptor_catalog(_DESCRIPTORS_PATH),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=set(),
    )


def test_shipped_config_check_is_non_vacuous() -> None:
    """Prove the shipped-config test above actually inspects WARNING alarms.

    A green run means nothing if the config carries no WARNING references, so
    assert the population directly.
    """
    data = yaml.safe_load(_ALARMS_V3_PATH.read_text(encoding="utf-8")) or {}
    levels = {
        str(alarm.get("level", "")).strip().lower()
        for alarm in (data.get("global_alarms") or {}).values()
        if isinstance(alarm, dict)
    }
    assert "warning" in levels, "shipped alarms_v3.yaml no longer has WARNING alarms to check"


def _real_safety_manager() -> SafetyManager:
    manager = SafetyManager(SafetyBroker())
    manager.load_config(_SAFETY_PATH)
    return manager
