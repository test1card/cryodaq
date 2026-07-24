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

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import cryodaq.engine as engine
from cryodaq.core.housekeeping import (
    HousekeepingConfigError,
    load_critical_channels_from_alarms_v3,
    resolve_canonical_temperature_labels,
    resolve_protected_channel_bindings,
)
from cryodaq.core.physical_alarms_config import (
    PhysicalAlarmsConfigError,
    load_production_physical_alarms_config,
)
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.safety_pattern_liveness import (
    _THROTTLE_BYPASS_PATTERNS,
    SafetyPatternLivenessError,
    validate_safety_pattern_liveness,
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
    sm.install_exact_temperature_bindings(
        resolve_canonical_temperature_labels(_real_catalog(), {"\u042211", "\u042212"})
    )
    return sm


def _real_alarms_v3_patterns() -> set[str]:
    return load_critical_channels_from_alarms_v3(_ALARMS_V3_PATH)


def _real_merged_patterns() -> set[str]:
    return resolve_protected_channel_bindings(
        _real_catalog(),
        {
            *engine.load_protected_channel_patterns(_INTERLOCKS_PATH),
            *_real_alarms_v3_patterns(),
        },
    )


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
) -> dict[str, object]:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "instruments.local.yaml").write_text("instruments: []\n", encoding="utf-8")
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

    class _SafetyManager:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def load_config(self, path: Path) -> None:
            observed["safety_path"] = path

        def install_exact_temperature_bindings(self, bindings: dict[str, str]) -> None:
            observed["installed_temperature_bindings"] = dict(bindings)

        def install_startup_blocker(self, code: str, message: str, remediation: str) -> None:
            observed["startup_blocker"] = (code, message, remediation)

    class _Writer:
        def __init__(self, _data_dir: Path, *, channel_catalog: object) -> None:
            observed["writer_called"] = True
            observed["writer_catalog"] = channel_catalog
            raise _StopAtWriter

    monkeypatch.setattr(engine, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(engine, "_DATA_DIR", data_dir)
    monkeypatch.setattr(engine, "_load_drivers", _load_drivers)
    monkeypatch.setattr(engine, "SafetyManager", _SafetyManager)
    monkeypatch.setattr(engine, "load_housekeeping_config", lambda _path: {})
    monkeypatch.setattr(engine, "load_protected_channel_patterns", lambda _path: legacy_patterns)
    monkeypatch.setattr(
        engine,
        "load_alarm_config_authority",
        lambda _path: SimpleNamespace(
            critical_channel_patterns=frozenset(v3_patterns),
            engine_config=SimpleNamespace(rate_window_s=120.0, rate_min_points=60),
            alarms=(),
        ),
    )
    monkeypatch.setattr(engine, "SQLiteWriter", _Writer)
    monkeypatch.setattr(
        engine,
        "load_production_physical_alarms_config",
        lambda *_args, **_kwargs: (
            {"predictor_model_path": str(tmp_path / "missing-reviewed-model.json")},
            {},
            {},
        ),
    )
    monkeypatch.setattr(
        engine,
        "resolve_canonical_temperature_labels",
        lambda *_args, **_kwargs: {"\u042211": "local T11", "\u042212": "local T12"},
    )
    monkeypatch.setattr(
        engine,
        "resolve_protected_channel_bindings",
        lambda _catalog, patterns: set(patterns),
    )
    return observed


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


def test_actual_runtime_union_is_exact_and_live() -> None:
    patterns = _real_merged_patterns()
    assert "^\u042211\\ \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a\\ 1$" in patterns
    assert "^\u042212\\ \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a\\ 2$" in patterns
    validate_safety_pattern_liveness(
        descriptor_catalog=_real_catalog(),
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns=patterns,
    )


def test_safety_tests_and_production_have_no_hidden_legacy_definitions() -> None:
    root = Path(__file__).parents[2]
    paths = [
        root / "tests/core/test_safety_manager.py",
        root / "tests/core/test_physical_alarm_exactness.py",
        root / "tests/core/test_safety_pattern_liveness.py",
        root / "tests/core/test_startup_safety_liveness_gate.py",
        root / "tests/test_engine_config_error.py",
        root / "src/cryodaq/core/physical_alarms_config.py",
        root / "src/cryodaq/core/housekeeping.py",
    ]
    forbidden: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name.startswith("_legacy_test")
                or node.name.startswith("disabled_test")
                or node.name.startswith("_disabled_test")
                or node.name.startswith("test_disabled_")
                or node.name.startswith("_legacy_")
            ):
                forbidden.append(f"{path.name}:{node.lineno}:{node.name}")
    assert forbidden == []


def _install_invalid_physical_document(config_dir: Path, case: str) -> None:
    path = config_dir / "physical_alarms.yaml"
    if case == "missing":
        return
    if case == "duplicate":
        path.write_text("cooldown: {}\ncooldown: {}\nvacuum: {}\nlandmarks: {}\n", encoding="utf-8")
        return
    if case == "alias":
        path.write_text("cooldown: &same {}\nvacuum: *same\nlandmarks: {}\n", encoding="utf-8")
        return
    if case == "oversized":
        path.write_text("#" + ("x" * (64 * 1024)), encoding="utf-8")
        return
    if case == "nonregular":
        path.mkdir()
        return
    document = yaml.safe_load((_CONFIG_DIR / "physical_alarms.yaml").read_text(encoding="utf-8"))
    if case == "type":
        document["cooldown"]["enabled"] = "true"
    elif case == "unicode":
        document["landmarks"]["\u042211"]["aliases"].append("bad\u200dformat")
    elif case == "traversal":
        document["cooldown"]["predictor_model_path"] = "../outside/predictor_model.json"
    else:
        raise AssertionError(f"unknown invalid physical case {case}")
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "case",
    ["missing", "duplicate", "alias", "type", "unicode", "oversized", "nonregular", "traversal"],
)
async def test_run_engine_invalid_physical_document_fails_before_binding_or_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=[],
        v3_patterns=set(),
    )
    _install_invalid_physical_document(tmp_path / "config", case)
    monkeypatch.setattr(
        engine,
        "load_production_physical_alarms_config",
        load_production_physical_alarms_config,
    )
    with pytest.raises(PhysicalAlarmsConfigError):
        await engine._run_engine(mock=True)
    assert observed["writer_called"] is False
    assert "installed_temperature_bindings" not in observed


async def test_run_engine_ambiguous_descriptor_binding_fails_before_install_or_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=[],
        v3_patterns=set(),
    )

    def _ambiguous(*_args, **_kwargs):
        raise HousekeepingConfigError("ambiguous T11 binding")

    monkeypatch.setattr(engine, "resolve_canonical_temperature_labels", _ambiguous)
    with pytest.raises(HousekeepingConfigError, match="ambiguous T11"):
        await engine._run_engine(mock=True)
    assert observed["writer_called"] is False
    assert "installed_temperature_bindings" not in observed


async def test_run_engine_dead_liveness_fails_before_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=["legacy-only$"],
        v3_patterns={"v3-only"},
    )

    def _dead_validator(**_kwargs) -> None:
        raise SafetyPatternLivenessError("synthetic dead pattern")

    monkeypatch.setattr(engine, "validate_safety_pattern_liveness", _dead_validator)
    with pytest.raises(SafetyPatternLivenessError, match="synthetic dead pattern"):
        await engine._run_engine(mock=True)
    assert observed["writer_called"] is False
    assert observed["installed_temperature_bindings"] == {
        "\u042211": "local T11",
        "\u042212": "local T12",
    }


async def test_run_engine_missing_physical_config_fails_before_binding_or_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_engine_startup_harness(
        tmp_path,
        monkeypatch,
        legacy_patterns=[],
        v3_patterns=set(),
    )
    monkeypatch.setattr(
        engine,
        "load_production_physical_alarms_config",
        load_production_physical_alarms_config,
    )
    with pytest.raises(PhysicalAlarmsConfigError):
        await engine._run_engine(mock=True)
    assert observed["writer_called"] is False
    assert "installed_temperature_bindings" not in observed


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


def test_dead_safety_critical_pattern_raises_raw() -> None:
    """A dead raw safety.yaml critical_channels pattern makes validation raise.

    Loads the real safety config, then appends a critical_channels pattern that
    matches NO raw emitted label. The validator must raise and name the dead
    pattern, its plane, and the safety.yaml source.
    """
    sm = _real_safety_manager()
    sm._config.critical_channels.append(re.compile("__DEAD_SAFETY_CRITICAL__"))
    with pytest.raises(SafetyPatternLivenessError) as exc_info:
        validate_safety_pattern_liveness(
            descriptor_catalog=_real_catalog(),
            interlocks_config_path=_INTERLOCKS_PATH,
            safety_manager=sm,
            adaptive_throttle_patterns=_real_alarms_v3_patterns(),
        )
    message = str(exc_info.value)
    assert "__DEAD_SAFETY_CRITICAL__" in message
    assert "raw" in message
    assert "critical_channels" in message


def test_dead_adaptive_throttle_pattern_raises_raw_substring() -> None:
    """A dead protected ref on the throttle's raw substring plane raises.

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
    assert "substring" in message
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

    # Protected patterns containing ONLY the disk channel: must NOT raise.
    validate_safety_pattern_liveness(
        descriptor_catalog=catalog,
        interlocks_config_path=_INTERLOCKS_PATH,
        safety_manager=_real_safety_manager(),
        adaptive_throttle_patterns={re.escape(_DISK_CHANNEL)},
    )


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
    safety_document = yaml.safe_load(_SAFETY_PATH.read_text(encoding="utf-8"))
    safety_document["critical_channels"] = ["^source heartbeat$"]
    safety_document["keithley_channels"] = ["^custom keithley heartbeat$"]
    safety_path.write_text(
        yaml.safe_dump(safety_document, allow_unicode=True, sort_keys=False),
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
