"""Startup safety channel-pattern liveness diagnostic (F-1 class).

Proves ``validate_safety_pattern_liveness`` checks the planes and exact runtime
AdaptiveThrottle union it is given.  It also proves the engine's temporary lab
policy catches only ``SafetyPatternLivenessError``, logs CRITICAL, and continues
with the actually selected local descriptor replacement.  An unrelated error
still aborts startup.

The validator reuses the engine's already-loaded ``SafetyManager`` and the
pre-computed legacy-plus-v3 AdaptiveThrottle union; these tests mirror that
contract by constructing a real SafetyManager from production safety.yaml and
the real protected-pattern set, then injecting one deliberately dead
CRITICAL/safety ref and asserting the gate names it.

Planes, matchers, and the disk bypass are proven in the sibling regression
test ``tests/core/test_safety_pattern_liveness.py`` (commit dca5ff5); this file
exercises the startup gate that consumes the same proven logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

import cryodaq.engine as engine
from cryodaq.core.housekeeping import load_critical_channels_from_alarms_v3, load_housekeeping_config
from cryodaq.core.interlock import InterlockEngine
from cryodaq.core.physical_policy import PhysicalPolicyReceipt
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.core.safety_pattern_liveness import (
    _THROTTLE_BYPASS_PATTERNS,
    SafetyPatternLivenessError,
    validate_safety_pattern_liveness,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)
from cryodaq.engine import DriverLoadResult
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_DESCRIPTORS_PATH = _CONFIG_DIR / "channel_descriptors.yaml"
_INTERLOCKS_PATH = _CONFIG_DIR / "interlocks.yaml"
_SAFETY_PATH = _CONFIG_DIR / "safety.yaml"
_ALARMS_V3_PATH = _CONFIG_DIR / "alarms_v3.yaml"

_DISK_CHANNEL = "system/disk_free_gb"


def _real_catalog():
    """The base descriptor manifest the regression test checks against."""
    return load_live_channel_descriptor_catalog(_DESCRIPTORS_PATH)


def _real_safety_manager() -> SafetyManager:
    sm = SafetyManager(SafetyBroker())
    sm.load_config(_SAFETY_PATH)
    return sm


def _real_alarms_v3_patterns() -> set[str]:
    return load_critical_channels_from_alarms_v3(_ALARMS_V3_PATH)


def _real_merged_patterns() -> set[str]:
    return {
        *engine.load_protected_channel_patterns(_INTERLOCKS_PATH),
        *_real_alarms_v3_patterns(),
    }


def _manifest(*, instrument_id: str, emitted_channel: str, channel_id: str) -> dict:
    return {
        "schema_version": 1,
        "descriptors": [
            {
                "schema_version": 1,
                "channel_id": channel_id,
                "instrument_id": instrument_id,
                "source_key": "input.1.temperature",
                "quantity": "temperature",
                "unit": "K",
                "role": "primary_measurement",
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
                "instrument_id": instrument_id,
                "emitted_channel": emitted_channel,
                "channel_id": channel_id,
            }
        ],
    }


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


class _StopAtWriter(RuntimeError):
    """Sentinel proving startup continued past the liveness diagnostic."""


def _install_engine_startup_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    legacy_patterns: list[str],
    v3_patterns: set[str],
    safety_manager_type: type[SafetyManager] | None = None,
) -> dict[str, object]:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "instruments.local.yaml").write_text("instruments: []\n", encoding="utf-8")
    (config_dir / "interlocks.yaml").write_text("interlocks: []\n", encoding="utf-8")
    (config_dir / "housekeeping.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "safety.yaml").write_text("critical_channels:\n  - '^default$'\n", encoding="utf-8")
    (config_dir / "cooldown.yaml").write_text("cooldown:\n  enabled: false\n", encoding="utf-8")
    _write_manifest(
        config_dir / "channel_descriptors.yaml",
        _manifest(instrument_id="base", emitted_channel="base emitted", channel_id="base.1"),
    )
    _write_manifest(
        config_dir / "channel_descriptors.local.yaml",
        _manifest(instrument_id="probe", emitted_channel="local emitted", channel_id="local.1"),
    )

    observed: dict[str, object] = {"writer_called": False}

    def _load_drivers(*_args, **_kwargs) -> DriverLoadResult:
        return DriverLoadResult((), (SimpleNamespace(name="probe"),), None, None)  # type: ignore[arg-type]

    if safety_manager_type is None:

        class _SafetyManager:
            def __init__(self, *_args, **_kwargs) -> None:
                return None

            def load_config(self, path: Path) -> PhysicalPolicyReceipt:
                observed["safety_path"] = path
                return engine.receipt_for_applied_policy("safety", path, b"")

        safety_manager_type = _SafetyManager

    class _Writer:
        def __init__(self, _data_dir: Path, *, channel_catalog: object) -> None:
            observed["writer_called"] = True
            observed["writer_catalog"] = channel_catalog
            raise _StopAtWriter

    monkeypatch.setattr(engine, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(engine, "_DATA_DIR", data_dir)
    monkeypatch.setattr(engine, "_load_drivers", _load_drivers)
    monkeypatch.setattr(engine, "SafetyManager", safety_manager_type)
    monkeypatch.setattr(
        engine,
        "load_housekeeping_config",
        lambda path: ({}, engine.receipt_for_applied_policy("housekeeping", path, b"")),
    )
    monkeypatch.setattr(engine, "load_protected_channel_patterns", lambda _path, **_kwargs: legacy_patterns)
    monkeypatch.setattr(engine, "load_critical_channels_from_alarms_v3", lambda _path: v3_patterns)
    monkeypatch.setattr(engine, "SQLiteWriter", _Writer)
    return observed


@pytest.mark.parametrize("local_override", [True, False], ids=["local_override", "tracked_base"])
async def test_run_engine_records_effective_physical_policy_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    local_override: bool,
) -> None:
    """The production startup path logs the selected safety policy and still proceeds."""
    captured: list[SafetyManager] = []

    class _CapturingSafetyManager(SafetyManager):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.append(self)

    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=[],
        v3_patterns=set(),
        safety_manager_type=_CapturingSafetyManager,
    )
    config_dir = tmp_path / "config"
    (config_dir / "interlocks.yaml").write_text("interlocks: []\n", encoding="utf-8")
    (config_dir / "housekeeping.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "cooldown.yaml").write_text("cooldown:\n  enabled: false\n", encoding="utf-8")
    (config_dir / "safety.yaml").write_text(
        "critical_channels:\n  - '^tracked$'\nsource_limits:\n  max_power_w: 1.0\n",
        encoding="utf-8",
    )
    selected = config_dir / ("safety.local.yaml" if local_override else "safety.yaml")
    if local_override:
        selected.write_text(
            "critical_channels:\n  - '^local$'\nsource_limits:\n  max_power_w: 2.0\n",
            encoding="utf-8",
        )
    expected_hash = hashlib.sha256(selected.read_bytes()).hexdigest()
    source_kind = "local_override" if local_override else "tracked_base"
    expected = (
        f"Physical policy provenance: policy=safety source={selected.name} origin={source_kind} sha256={expected_hash}"
    )
    monkeypatch.setattr(engine, "validate_safety_pattern_liveness", lambda **_kwargs: [])

    with caplog.at_level("INFO", logger="cryodaq.engine"):
        with pytest.raises(_StopAtWriter):
            await engine._run_engine(mock=True)

    assert observed["writer_called"] is True
    assert captured[0]._config.max_power_w == (2.0 if local_override else 1.0)
    assert expected in caplog.text
    if local_override:
        assert "Physical policy provenance: policy=safety source=safety.yaml origin=tracked_base" not in caplog.text
        assert any(record.message == expected and record.levelname == "WARNING" for record in caplog.records)
    else:
        assert any(record.message == expected and record.levelname == "INFO" for record in caplog.records)


async def test_run_engine_provenance_hash_matches_the_safety_bytes_it_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A provenance hash must describe the safety policy the loader parsed."""
    captured: list[SafetyManager] = []

    class _CapturingSafetyManager(SafetyManager):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.append(self)

    _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=[],
        v3_patterns=set(),
        safety_manager_type=_CapturingSafetyManager,
    )
    config_dir = tmp_path / "config"
    (config_dir / "interlocks.yaml").write_text("interlocks: []\n", encoding="utf-8")
    (config_dir / "housekeeping.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "cooldown.yaml").write_text("cooldown:\n  enabled: false\n", encoding="utf-8")
    safety_path = config_dir / "safety.yaml"
    bytes_before = b"critical_channels:\n  - '^before$'\nsource_limits:\n  max_power_w: 1.0\n"
    bytes_applied = b"critical_channels:\n  - '^applied$'\nsource_limits:\n  max_power_w: 2.0\n"
    safety_path.write_bytes(bytes_before)
    original_read_bytes = Path.read_bytes

    def _mutate_after_snapshot_read(path: Path) -> bytes:
        snapshot = original_read_bytes(path)
        if path == safety_path:
            safety_path.write_bytes(bytes_applied)
        return snapshot

    monkeypatch.setattr(Path, "read_bytes", _mutate_after_snapshot_read)
    monkeypatch.setattr(engine, "validate_safety_pattern_liveness", lambda **_kwargs: [])

    with caplog.at_level("INFO", logger="cryodaq.engine"):
        with pytest.raises(_StopAtWriter):
            await engine._run_engine(mock=True)

    snapshot_hash = hashlib.sha256(bytes_before).hexdigest()
    assert safety_path.read_bytes() == bytes_applied
    assert captured[0]._config.max_power_w == 1.0
    assert f"policy=safety source=safety.yaml origin=tracked_base sha256={snapshot_hash}" in caplog.text


def test_all_physical_policy_loaders_return_applied_snapshot_receipts(tmp_path: Path) -> None:
    """Every physical policy loader returns its accepted snapshot receipt."""
    safety_path = tmp_path / "safety.yaml"
    interlocks_path = tmp_path / "interlocks.yaml"
    housekeeping_path = tmp_path / "housekeeping.yaml"
    cooldown_path = tmp_path / "cooldown.yaml"
    safety_path.write_bytes(b"critical_channels:\n  - '^safety$'\n")
    interlocks_path.write_bytes(b"interlocks: []\n")
    housekeeping_path.write_bytes(b"adaptive_throttle:\n  enabled: true\n")
    cooldown_path.write_bytes(b"cooldown:\n  enabled: false\n")

    safety_receipt = SafetyManager(SafetyBroker()).load_config(safety_path)
    interlocks_receipt = InterlockEngine(None, actions={"emergency_off": lambda: None}).load_config(interlocks_path)
    _housekeeping, housekeeping_receipt = load_housekeeping_config(housekeeping_path)
    _cooldown, cooldown_receipt = engine._load_cooldown_config(cooldown_path)

    for policy, path, receipt in (
        ("safety", safety_path, safety_receipt),
        ("interlocks", interlocks_path, interlocks_receipt),
        ("housekeeping", housekeeping_path, housekeeping_receipt),
        ("cooldown", cooldown_path, cooldown_receipt),
    ):
        assert receipt.selected_path == path
        assert receipt.origin == "tracked_base"
        assert receipt.sha256 == hashlib.sha256(path.read_bytes()).hexdigest(), policy


def test_real_v3_patterns_validate_cleanly_before_legacy_union() -> None:
    """All non-legacy production safety planes are live on the base manifest.

    The legacy interlock regexes are separately shown dead on their second,
    raw AdaptiveThrottle plane below; modern v3 patterns cover those channels.
    """
    validate_safety_pattern_liveness(
        descriptor_catalog=_real_catalog(),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=_real_alarms_v3_patterns(),
    )


def test_actual_runtime_union_resolves_canonical_patterns_to_raw_throttle_plane() -> None:
    """The runtime union is live only after descriptor-authority resolution."""
    resolved = validate_safety_pattern_liveness(
        descriptor_catalog=_real_catalog(),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=_real_merged_patterns(),
    )

    assert "Т[1-8]$" not in resolved
    assert "Т(9|10|11|12)$" not in resolved
    assert "Т12$" not in resolved
    assert "^Т1\\ Криостат\\ верх$" in resolved
    assert "^Т12\\ Теплообменник\\ 2$" in resolved


def test_unprotected_keithley_heartbeat_does_not_block_startup_liveness() -> None:
    """Throttle protection is archival only; it cannot starve SafetyBroker."""
    patterns = _real_merged_patterns() - {"Keithley_1/smub/power"}

    validate_safety_pattern_liveness(
        descriptor_catalog=_real_catalog(),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=patterns,
    )


async def test_runtime_heartbeat_accepts_power_as_the_only_fresh_metric_per_active_smu(
    tmp_path: Path,
) -> None:
    """The watchdog requires one fresh matching metric per active SMU, not every metric."""
    broker = SafetyBroker()
    keithley = MagicMock()
    keithley.connected = True
    keithley.output_state_unverified = False
    keithley.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    keithley.start_source = AsyncMock()
    keithley.stop_source = AsyncMock()
    binding = _issue_registry_runtime_binding(
        driver=keithley,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:startup-safety-liveness",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    manager = SafetyManager(
        broker,
        keithley_driver=keithley,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    safety_config = yaml.safe_load(_SAFETY_PATH.read_text(encoding="utf-8"))
    safety_config["heartbeat_timeout_s"] = 0.2
    safety_config["stale_timeout_s"] = 5.0
    safety_path = tmp_path / "safety.yaml"
    safety_path.write_text(
        yaml.safe_dump(safety_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    manager.load_config(safety_path)
    validate_safety_pattern_liveness(
        descriptor_catalog=_real_catalog(),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=manager,
        adaptive_throttle_patterns=_real_merged_patterns(),
    )

    async def _publish(channel: str, value: float, unit: str) -> None:
        await broker.publish(
            Reading.now(
                channel=channel,
                value=value,
                unit=unit,
                instrument_id="test",
                status=ChannelStatus.OK,
            )
        )

    await manager.start()
    try:
        generation = await manager.begin_reviewed_source_connect(keithley, binding, "test setup")
        assert await manager.complete_reviewed_source_connect(
            keithley,
            binding,
            generation,
            "test setup",
        )
        await _publish("Т11 Теплообменник 1", 40.0, "K")
        await _publish("Т12 Теплообменник 2", 3.0, "K")
        for _ in range(150):
            if manager.state == SafetyState.READY:
                break
            await asyncio.sleep(0.01)
        assert manager.state == SafetyState.READY

        assert (await manager.request_run(0.5, 10.0, 0.1, channel="smua"))["ok"] is True
        assert (await manager.request_run(0.5, 10.0, 0.1, channel="smub"))["ok"] is True

        # Keep only power fresh for longer than two heartbeat windows. Current,
        # resistance, and voltage are deliberately absent.
        for _ in range(30):
            await _publish("Keithley_1/smua/power", 0.5, "W")
            await _publish("Keithley_1/smub/power", 0.5, "W")
            await asyncio.sleep(0.05)

        assert manager.state == SafetyState.RUNNING
    finally:
        await manager.stop()


async def test_run_engine_uses_local_replacement_and_fails_closed_on_dead_pattern(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production wiring validates the selected authority before persistence."""
    legacy = ["legacy-only$"]
    v3 = {"v3-only"}
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=legacy,
        v3_patterns=v3,
    )

    def _dead_validator(**kwargs) -> None:
        observed["validator_kwargs"] = kwargs
        raise SafetyPatternLivenessError("synthetic local dead pattern")

    monkeypatch.setattr(engine, "validate_safety_pattern_liveness", _dead_validator)
    with pytest.raises(SafetyPatternLivenessError, match="synthetic local dead pattern"):
        await engine._run_engine(mock=True)

    kwargs = observed["validator_kwargs"]
    selected_catalog = kwargs["descriptor_catalog"]
    assert set(selected_catalog._bindings) == {("probe", "local emitted")}
    assert ("base", "base emitted") not in selected_catalog._bindings
    assert set(kwargs["adaptive_throttle_patterns"]) == {"legacy-only$", "v3-only"}
    assert observed["writer_called"] is False


async def test_run_engine_does_not_catch_unrelated_validator_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The temporary policy catches exactly SafetyPatternLivenessError."""
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=["legacy-only$"],
        v3_patterns={"v3-only"},
    )

    def _broken_validator(**_kwargs) -> None:
        raise LookupError("unrelated validator defect")

    monkeypatch.setattr(engine, "validate_safety_pattern_liveness", _broken_validator)

    with pytest.raises(LookupError, match="unrelated validator defect"):
        await engine._run_engine(mock=True)
    assert observed["writer_called"] is False


def test_dead_interlock_pattern_raises_canonical(tmp_path) -> None:
    """A dead canonical interlock pattern makes the validator raise.

    Writes a temp interlocks.yaml whose pattern matches NO canonical
    channel_id. The validator must raise and name the dead pattern, its plane,
    and the interlocks config source.
    """
    interlocks_cfg = tmp_path / "interlocks.yaml"
    interlocks_cfg.write_text(
        "interlocks:\n"
        "  - name: dead_interlock_never_matches\n"
        "    description: synthetic dead ref\n"
        '    channel_pattern: "__DEAD_INTERLOCK_CHANNEL__$"\n'
        "    threshold: 1.0\n"
        '    comparison: ">"\n'
        '    action: "emergency_off"\n',
        encoding="utf-8",
    )
    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(
            descriptor_catalog=_real_catalog(),
            interlocks_config_path=interlocks_cfg,
            safety_manager=_real_safety_manager(),
            adaptive_throttle_patterns=_real_alarms_v3_patterns(),
        )
    message = str(exc_info.value)
    assert "__DEAD_INTERLOCK_CHANNEL__" in message
    assert "canonical" in message
    assert "interlocks.yaml" in message


def test_dead_safety_critical_pattern_raises_from_canonical_authority() -> None:
    """A dead canonical safety.yaml critical pattern makes validation raise.

    Loads the real safety config, then appends a critical_channels pattern that
    matches NO raw emitted label. The validator must raise and name the dead
    pattern, its plane, and the safety.yaml source.
    """
    sm = _real_safety_manager()
    sm._canonical_critical_patterns.append(re.compile("__DEAD_SAFETY_CRITICAL__"))
    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(
            descriptor_catalog=_real_catalog(),
            interlocks_config_path=_INTERLOCKS_PATH,
            safety_manager=sm,
            adaptive_throttle_patterns=_real_alarms_v3_patterns(),
        )
    message = str(exc_info.value)
    assert "__DEAD_SAFETY_CRITICAL__" in message
    assert "canonical" in message
    assert "critical_channels" in message


def test_dead_adaptive_throttle_pattern_raises_before_raw_resolution() -> None:
    """A dead protected ref on the canonical resolution plane raises.

    The disk-bypass channel alone would be skipped, so add a second dead ref
    that matches NO raw emitted label. The validator must raise and name the
    dead ref, its plane, and the alarms_v3.yaml source.
    """
    patterns = _real_alarms_v3_patterns() | {re.escape("__DEAD_ALARM_REF__")}
    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(
            descriptor_catalog=_real_catalog(),
            interlocks_config_path=_INTERLOCKS_PATH,
            safety_manager=_real_safety_manager(),
            adaptive_throttle_patterns=patterns,
        )
    message = str(exc_info.value)
    assert "__DEAD_ALARM_REF__" in message
    assert "canonical AdaptiveThrottle expression" in message
    assert "AdaptiveThrottle protected patterns" in message
    # The disk channel must NOT be listed as dead even when another ref is.
    assert _DISK_CHANNEL not in message


def test_disk_synthetic_channel_does_not_trigger_raise() -> None:
    """The direct-to-DataBroker disk channel is exempt (no false fail-closed).

    DiskMonitor publishes ``system/disk_free_gb`` straight to the DataBroker,
    bypassing the scheduler/AdaptiveThrottle, so it is intentionally NOT in the
    descriptor roster. The bypass MUST keep it from tripping the gate.

    Proven non-vacuous: the disk channel genuinely is absent from the roster,
    so without the bypass this input WOULD raise.
    """
    catalog = _real_catalog()
    raw_labels = {emitted for (_instr, emitted) in catalog._bindings}
    canonical_ids = set(catalog.storage_catalog_snapshot().by_channel_id)
    assert _DISK_CHANNEL not in raw_labels
    assert _DISK_CHANNEL not in canonical_ids

    # Keep all actual safety requirements protected and prove that the
    # descriptor-less disk pattern itself does not add a false failure.
    resolved = validate_safety_pattern_liveness(
        descriptor_catalog=catalog,
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=_real_merged_patterns(),
    )
    assert re.escape(_DISK_CHANNEL) in resolved


def test_non_default_yaml_keithley_pattern_uses_effective_runtime_field(tmp_path: Path) -> None:
    """A non-default YAML Keithley regex is checked from ``_keithley_patterns``."""
    descriptor_path = tmp_path / "channel_descriptors.local.yaml"
    _write_manifest(
        descriptor_path,
        _manifest(instrument_id="source", emitted_channel="source heartbeat", channel_id="source.heartbeat"),
    )
    interlocks_path = tmp_path / "interlocks.yaml"
    interlocks_path.write_text("interlocks: []\n", encoding="utf-8")
    safety_path = tmp_path / "safety.yaml"
    safety_path.write_text(
        'critical_channels:\n  - "^source heartbeat$"\nkeithley_channels:\n  - "^custom keithley heartbeat$"\n',
        encoding="utf-8",
    )
    safety_manager = SafetyManager(SafetyBroker())
    safety_manager.load_config(safety_path)

    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(
            descriptor_catalog=load_live_channel_descriptor_catalog(descriptor_path),
            interlocks_config_path=interlocks_path,
            safety_manager=safety_manager,
            adaptive_throttle_patterns=set(),
        )

    message = str(exc_info.value)
    assert "^custom keithley heartbeat$" in message
    assert "safety.yaml keithley_channels" in message


def test_throttle_bypass_pattern_constant_is_current() -> None:
    """Pin the bypass set against silent drift (mirrors the regression test).

    If a new direct-to-DataBroker publisher appears, this forces a conscious
    revisit instead of silently weakening (or over-excluding) throttle-plane
    liveness protection. Matches
    tests/core/test_safety_pattern_liveness.py:test_throttle_bypass_patterns_are_current.
    """
    assert _THROTTLE_BYPASS_PATTERNS == frozenset({re.escape(_DISK_CHANNEL)})
