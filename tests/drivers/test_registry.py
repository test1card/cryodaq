from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

import cryodaq.drivers.registry as registry_module
from cryodaq.drivers.base import InstrumentDriver
from cryodaq.drivers.contracts import ControlledSource, DriverTrustClass, VerifiedOffSource
from cryodaq.drivers.instruments.keithley_2604b import WatchdogMode
from cryodaq.drivers.registry import (
    ALLOWLISTED_DRIVER_MODULES,
    BUILTIN_DRIVER_SPECS,
    DRIVER_REGISTRY_COMPAT_VERSION,
    KEITHLEY_2604B_SOURCE_BINDING,
    PASSIVE_DRIVER_SPECS,
    REVIEWED_SOURCE_SPECS,
    ConfigField,
    DriverAuthority,
    DriverCapability,
    DriverConstructionContext,
    DriverRegistryError,
    DriverSpec,
    DuplicateInstrumentNameError,
    ReviewedSourceBinding,
    UnknownDriverTypeError,
    ValidatedInstrumentConfig,
    ValueKind,
    construct_driver,
    get_driver_spec,
    runtime_binding_for_driver,
    validate_instrument_entries,
    validate_instrument_entry,
)


def _normalizer(values: dict[str, object], _path: str) -> dict[str, object]:
    return values


def _factory(config: object, context: object) -> InstrumentDriver:
    raise AssertionError((config, context))


def test_registry_is_exact_static_allowlist() -> None:
    assert DRIVER_REGISTRY_COMPAT_VERSION == 1
    assert set(BUILTIN_DRIVER_SPECS) == {
        "lakeshore_218s",
        "keithley_2604b",
        "thyracont_vsp63d",
        "etalon_multiline",
        "asc_reference_tcp",
    }
    assert ALLOWLISTED_DRIVER_MODULES == tuple(sorted(spec.module for spec in BUILTIN_DRIVER_SPECS.values()))


def test_exported_partitions_have_independent_inaccessible_backing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_passive = set(PASSIVE_DRIVER_SPECS)
    expected_source = set(REVIEWED_SOURCE_SPECS)
    expected_all = set(BUILTIN_DRIVER_SPECS)
    assert not hasattr(registry_module, "_PASSIVE_SPECS")
    assert not hasattr(registry_module, "_SOURCE_SPECS")
    with pytest.raises(TypeError):
        PASSIVE_DRIVER_SPECS["evil"] = PASSIVE_DRIVER_SPECS["lakeshore_218s"]  # type: ignore[index]

    monkeypatch.setattr(
        registry_module,
        "_PASSIVE_SPECS",
        {"evil": PASSIVE_DRIVER_SPECS["lakeshore_218s"]},
        raising=False,
    )
    assert set(PASSIVE_DRIVER_SPECS) == expected_passive
    assert set(REVIEWED_SOURCE_SPECS) == expected_source
    assert set(BUILTIN_DRIVER_SPECS) == expected_all
    assert expected_all == expected_passive | expected_source


def test_passive_and_reviewed_source_namespaces_are_disjoint() -> None:
    assert PASSIVE_DRIVER_SPECS.keys().isdisjoint(REVIEWED_SOURCE_SPECS)
    assert set(REVIEWED_SOURCE_SPECS) == {"keithley_2604b"}
    source = REVIEWED_SOURCE_SPECS["keithley_2604b"]
    assert source.authority is DriverAuthority.REVIEWED_SOURCE
    assert source.reviewed_source_binding == KEITHLEY_2604B_SOURCE_BINDING
    assert isinstance(source.reviewed_source_binding, ReviewedSourceBinding)
    assert {
        DriverCapability.CONTROLLED_SOURCE,
        DriverCapability.VERIFIED_OFF_SOURCE,
    }.issubset(source.capabilities)
    assert DriverCapability.CALIBRATABLE_SENSOR not in PASSIVE_DRIVER_SPECS["lakeshore_218s"].capabilities

    extension = PASSIVE_DRIVER_SPECS["asc_reference_tcp"]
    assert extension.authority is DriverAuthority.PASSIVE_EXTENSION
    assert extension.capabilities == frozenset({DriverCapability.PASSIVE_SENSOR})
    assert extension.reviewed_source_binding is None
    assert {
        DriverCapability.CONTROLLED_SOURCE,
        DriverCapability.VERIFIED_OFF_SOURCE,
    }.isdisjoint(extension.capabilities)


def test_protocol_conformance_cannot_promote_passive_spec_to_source() -> None:
    passive = PASSIVE_DRIVER_SPECS["thyracont_vsp63d"]
    with pytest.raises(ValueError, match="passive DriverSpec cannot declare source authority"):
        replace(
            passive,
            capabilities=passive.capabilities | {DriverCapability.CONTROLLED_SOURCE},
        )


def test_reviewed_source_requires_explicit_binding() -> None:
    with pytest.raises(ValueError, match="controlled-source and verified-OFF"):
        DriverSpec(
            type_name="source",
            module="cryodaq.drivers.instruments.source",
            class_name="Source",
            authority=DriverAuthority.REVIEWED_SOURCE,
            capabilities=frozenset({DriverCapability.CONTROLLED_SOURCE}),
            config_fields={"name": ConfigField(ValueKind.STRING, required=True)},
            normalizer=_normalizer,
            factory=_factory,
        )


def test_reviewed_source_rejects_arbitrary_nonempty_binding() -> None:
    fake = ReviewedSourceBinding("source", "some.module", "Adapter", 1)
    with pytest.raises(ValueError, match="exact typed Keithley safety binding"):
        DriverSpec(
            type_name="source",
            module="cryodaq.drivers.instruments.source",
            class_name="Source",
            authority=DriverAuthority.REVIEWED_SOURCE,
            capabilities=frozenset(
                {
                    DriverCapability.CONTROLLED_SOURCE,
                    DriverCapability.VERIFIED_OFF_SOURCE,
                }
            ),
            config_fields={"name": ConfigField(ValueKind.STRING, required=True)},
            normalizer=_normalizer,
            factory=_factory,
            reviewed_source_binding=fake,
        )


def test_reviewed_source_rejects_equal_but_unreviewed_binding_copy() -> None:
    binding_copy = replace(KEITHLEY_2604B_SOURCE_BINDING)
    with pytest.raises(ValueError, match="exact typed Keithley safety binding"):
        replace(
            REVIEWED_SOURCE_SPECS["keithley_2604b"],
            reviewed_source_binding=binding_copy,
        )


def test_unknown_type_fails_visibly() -> None:
    with pytest.raises(UnknownDriverTypeError, match="unknown instrument type 'plugin.module'"):
        get_driver_spec("plugin.module")


@pytest.mark.parametrize("type_name", ["lakeshore_218s", "keithley_2604b"])
def test_validated_config_cannot_be_directly_forged(type_name: str) -> None:
    spec = BUILTIN_DRIVER_SPECS[type_name]
    with pytest.raises(DriverRegistryError, match="cannot be constructed directly"):
        ValidatedInstrumentConfig(
            spec=spec,
            name="forged",
            values={"type": type_name, "name": "forged"},
        )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"type": "lakeshore_218s", "name": "", "resource": "GPIB::1"},
        {"type": "lakeshore_218s", "name": "LS"},
        {
            "type": "keithley_2604b",
            "name": "K",
            "resource": "USB::1",
            "poll_interval_s": float("nan"),
        },
    ],
)
def test_missing_empty_and_nan_configs_fail_only_as_registry_errors(
    values: dict[str, object],
) -> None:
    with pytest.raises(DriverRegistryError):
        validate_instrument_entry(values)


@pytest.mark.parametrize(
    ("type_name", "values"),
    [
        (
            "lakeshore_218s",
            {
                "type": "lakeshore_218s",
                "name": "LS",
                "poll_interval_s": float("nan"),
            },
        ),
        (
            "keithley_2604b",
            {
                "type": "keithley_2604b",
                "name": "K",
                "poll_interval_s": 1.0,
            },
        ),
    ],
)
def test_private_provenance_factory_revalidates_all_values(type_name: str, values: dict[str, object]) -> None:
    with pytest.raises(DriverRegistryError):
        ValidatedInstrumentConfig._from_validated(
            spec=BUILTIN_DRIVER_SPECS[type_name],
            name=str(values["name"]),
            values=values,
        )


def test_construct_driver_rejects_object_without_provenance() -> None:
    forged = object.__new__(ValidatedInstrumentConfig)
    with pytest.raises(DriverRegistryError, match="requires output from"):
        construct_driver(forged, DriverConstructionContext(mock=True))


def test_valid_lakeshore_config_is_normalized_and_immutable() -> None:
    config = validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS218_1",
            "resource": "GPIB0::12::INSTR",
            "poll_interval_s": 2,
            "channels": {1: "T1"},
        }
    )
    assert config.spec is PASSIVE_DRIVER_SPECS["lakeshore_218s"]
    assert config.values["poll_interval_s"] == 2.0
    with pytest.raises(TypeError):
        config.values["name"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        config.values["channels"][1] = "changed"  # type: ignore[index]


def test_schema_inputs_are_deeply_frozen() -> None:
    choices = ["a", "b"]
    default = {"nested": [1, 2]}
    field = ConfigField(ValueKind.STRING, default=default, choices=choices)  # type: ignore[arg-type]
    choices.append("c")
    default["nested"].append(3)
    assert field.choices == ("a", "b")
    assert isinstance(field.default, MappingProxyType)
    assert field.default["nested"] == (1, 2)  # type: ignore[index]


def test_driver_capabilities_are_copied_into_frozenset() -> None:
    passive = PASSIVE_DRIVER_SPECS["thyracont_vsp63d"]
    capabilities = [DriverCapability.PASSIVE_SENSOR]
    copied = replace(passive, capabilities=capabilities)  # type: ignore[arg-type]
    capabilities.append(DriverCapability.BURST_SENSOR)
    assert copied.capabilities == frozenset({DriverCapability.PASSIVE_SENSOR})


def test_schema_rejects_custom_mutable_default() -> None:
    with pytest.raises(TypeError, match="unsupported mutable/custom value"):
        ConfigField(ValueKind.STRING, default=object())
    with pytest.raises(TypeError, match="unordered container"):
        ConfigField(ValueKind.STRING, choices={"a", "b"})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"type": "thyracont_vsp63d", "name": "P", "resource": "COM3", "extra": 1}, "unknown keys"),
        (
            {
                "type": "thyracont_vsp63d",
                "name": "P",
                "resource": "COM3",
                "validate_checksum": "false",
            },
            "must be a boolean",
        ),
        (
            {
                "type": "thyracont_vsp63d",
                "name": "P",
                "resource": "COM3",
                "poll_interval_s": float("nan"),
            },
            "must be finite",
        ),
        (
            {
                "type": "thyracont_vsp63d",
                "name": "P",
                "resource": "COM3",
                "poll_interval_s": 10**1000,
            },
            r"instruments\[0\]\.poll_interval_s must be a finite representable number",
        ),
        ({"type": "etalon_multiline", "name": "M", "channels": [1], "channel_count": 1}, "exactly one"),
        ({"type": "etalon_multiline", "name": "M"}, "exactly one"),
        ({"type": "etalon_multiline", "name": "M", "channels": [1, 1]}, "unique channel"),
    ],
)
def test_strict_schema_rejects_invalid_entries(entry: dict[str, object], message: str) -> None:
    with pytest.raises(DriverRegistryError, match=message):
        validate_instrument_entry(entry)


def test_duplicate_instrument_names_fail_with_path() -> None:
    entries = [
        {"type": "keithley_2604b", "name": "same", "resource": "USB::1"},
        {"type": "thyracont_vsp63d", "name": "same", "resource": "COM3"},
    ]
    with pytest.raises(DuplicateInstrumentNameError, match=r"instruments\[1\].*same"):
        validate_instrument_entries(entries)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connect_timeout_s", True),
        ("connect_timeout_s", 0),
        ("read_timeout_s", float("nan")),
        ("read_timeout_s", float("inf")),
        ("poll_interval_s", 10**1000),
    ],
)
def test_runtime_timing_fields_fail_closed(field: str, value: object) -> None:
    entry = {
        "type": "thyracont_vsp63d",
        "name": "P",
        "resource": "COM3",
        field: value,
    }
    with pytest.raises(DriverRegistryError):
        validate_instrument_entry(entry)


@pytest.fixture
def current_root_config() -> dict[str, object]:
    return yaml.safe_load(Path("config/instruments.yaml").read_text(encoding="utf-8"))


async def test_current_config_constructs_and_runs_all_mock_lifecycles(
    tmp_path: Path, current_root_config: dict[str, object]
) -> None:
    root = current_root_config
    configs = validate_instrument_entries(root["instruments"])
    context = DriverConstructionContext.from_root_config(root, mock=True, data_dir=tmp_path)

    constructed: list[InstrumentDriver] = []
    for config in configs:
        driver = construct_driver(config, context)
        constructed.append(driver)
        await driver.connect()
        assert driver.connected
        readings = await driver.read_channels()
        assert isinstance(readings, list)
        assert all(reading.instrument_id == config.name for reading in readings)
        await driver.disconnect()
        assert not driver.connected

    assert [type(driver).__name__ for driver in constructed] == [
        "LakeShore218S",
        "LakeShore218S",
        "LakeShore218S",
        "Keithley2604B",
        "ThyracontVSP63D",
        "MultiLineDriver",
    ]


def test_root_keithley_watchdog_is_strict_and_path_qualified() -> None:
    with pytest.raises(DriverRegistryError, match=r"keithley\.watchdog\.enabled"):
        DriverConstructionContext.from_root_config({"keithley": {"watchdog": {"enabled": "false"}}}, mock=True)
    with pytest.raises(DriverRegistryError, match=r"keithley.*watchdg"):
        DriverConstructionContext.from_root_config({"keithley": {"watchdg": {}}}, mock=True)


async def test_constructed_reviewed_source_executes_mock_control_contract() -> None:
    config = validate_instrument_entry({"type": "keithley_2604b", "name": "K", "resource": "USB::1"})
    context = DriverConstructionContext(
        mock=True,
        keithley_watchdog={"mode": "best_effort", "timeout_s": 5.0},
    )
    driver = construct_driver(config, context)
    assert isinstance(driver, ControlledSource)
    assert isinstance(driver, VerifiedOffSource)
    assert driver._wdog_mode is WatchdogMode.BEST_EFFORT  # type: ignore[attr-defined]

    await driver.connect()
    await driver.start_source("smua", 1.0, 10.0, 0.5)
    await driver.stop_source("smua")
    assert await driver.emergency_off()
    await driver.disconnect()


async def test_reference_extension_constructs_in_mock_mode_with_passive_binding() -> None:
    config = validate_instrument_entry(
        {
            "type": "asc_reference_tcp",
            "name": "asc.reference.instrument-1",
            "host": "localhost",
            "port": 9000,
            "channels": [
                {
                    "channel_id": "asc.reference.temperature.stage-a",
                    "unit": "K",
                    "mock_value": 4.2,
                }
            ],
            "poll_interval_s": 0.25,
        }
    )
    driver = construct_driver(config, DriverConstructionContext(mock=True))
    binding = runtime_binding_for_driver(driver)

    assert type(driver).__module__ == "cryodaq.drivers.passive_extensions.asc_reference_tcp"
    assert binding is not None
    assert binding.driver is driver
    assert binding.trust_class is DriverTrustClass.PASSIVE_EXTENSION
    assert binding.timing.poll_interval_s == 0.25
    assert binding.bus_descriptor is None
    assert binding.participant is None
    assert binding.coordinator is None
    assert binding.lifecycle is None
    assert not isinstance(driver, ControlledSource)
    assert not isinstance(driver, VerifiedOffSource)

    await driver.connect()
    readings = await driver.read_channels()
    await driver.disconnect()
    assert [(item.instrument_id, item.channel, item.value, item.unit) for item in readings] == [
        (
            "asc.reference.instrument-1",
            "asc.reference.temperature.stage-a",
            4.2,
            "K",
        )
    ]


@pytest.mark.parametrize(
    ("channels", "message"),
    [
        ([], "at least one"),
        ([{"channel_id": "a", "unit": "K", "extra": 1}], "unknown keys"),
        ([{"channel_id": "a"}], "requires channel_id and unit"),
        ([{"channel_id": "not a stable id", "unit": "K"}], "invalid ASC reference grammar"),
        ([{"channel_id": "a", "unit": "not a unit"}], "invalid ASC reference grammar"),
        (
            [
                {"channel_id": "a", "unit": "K"},
                {"channel_id": "a", "unit": "K"},
            ],
            "must be unique",
        ),
        ([{"channel_id": "a", "unit": "K", "mock_value": float("nan")}], "must be finite"),
    ],
)
def test_reference_extension_channel_schema_fails_closed(channels: object, message: str) -> None:
    with pytest.raises(DriverRegistryError, match=message):
        validate_instrument_entry(
            {
                "type": "asc_reference_tcp",
                "name": "asc.reference.instrument-1",
                "port": 9000,
                "channels": channels,
            }
        )


def test_reference_extension_rejects_non_local_host_during_validation() -> None:
    with pytest.raises(DriverRegistryError, match="must be one of"):
        validate_instrument_entry(
            {
                "type": "asc_reference_tcp",
                "name": "asc.reference.instrument-1",
                "host": "192.0.2.1",
                "port": 9000,
                "channels": [{"channel_id": "a", "unit": "K"}],
            }
        )
