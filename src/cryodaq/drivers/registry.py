"""Static built-in driver registry, schemas, and explicit construction.

The registry is an allowlist: it performs no entry-point, filesystem, or
module-name discovery.  Structural protocol conformance never grants source
authority; only the exact reviewed binding below can do so.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

from cryodaq.drivers.base import InstrumentDriver
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusDescriptor,
    DriverRuntimeBinding,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)

DRIVER_REGISTRY_COMPAT_VERSION: Final = 1
logger = logging.getLogger(__name__)


class DriverRegistryError(ValueError):
    """Base class for visible registry/configuration failures."""


class UnknownDriverTypeError(DriverRegistryError):
    """A configured type is not present in the built-in allowlist."""


class DuplicateInstrumentNameError(DriverRegistryError):
    """Two configured instruments use the same stable instance name."""


class DriverAuthority(StrEnum):
    PASSIVE_MEASUREMENT = "passive_measurement"
    REVIEWED_SOURCE = "reviewed_source"


class DriverCapability(StrEnum):
    PASSIVE_SENSOR = "passive_sensor"
    CALIBRATABLE_SENSOR = "calibratable_sensor"
    BURST_SENSOR = "burst_sensor"
    SHARED_BUS_DEVICE = "shared_bus_device"
    CONTROLLED_SOURCE = "controlled_source"
    VERIFIED_OFF_SOURCE = "verified_off_source"


class ValueKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    STRING_MAP = "string_map"
    INTEGER_LIST = "integer_list"


def _freeze_schema_value(value: object, *, path: str) -> object:
    """Recursively freeze simple declarative schema data or reject it."""

    if value is None or isinstance(value, (str, int, float, bool, StrEnum)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[object, object] = {}
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise TypeError(f"{path} has unsupported mapping key {key!r}")
            frozen[key] = _freeze_schema_value(item, path=f"{path}[{key!r}]")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_schema_value(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    if isinstance(value, (set, frozenset)):
        raise TypeError(f"{path} uses an unordered container")
    raise TypeError(f"{path} contains unsupported mutable/custom value {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ConfigField:
    """Declarative schema for one driver configuration/setup field."""

    kind: ValueKind
    required: bool = False
    default: object | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[object, ...] = ()
    setup_visible: bool = True
    secret: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "default",
            _freeze_schema_value(self.default, path="ConfigField.default"),
        )
        frozen_choices = _freeze_schema_value(self.choices, path="ConfigField.choices")
        assert isinstance(frozen_choices, tuple)
        object.__setattr__(self, "choices", frozen_choices)


@dataclass(frozen=True, slots=True)
class ReviewedSourceBinding:
    """Typed identity of a separately reviewed safety-authority adapter."""

    driver_type: str
    adapter_module: str
    adapter_class: str
    contract_version: int


KEITHLEY_2604B_SOURCE_BINDING: Final = ReviewedSourceBinding(
    driver_type="keithley_2604b",
    adapter_module="cryodaq.core.safety_manager",
    adapter_class="SafetyManager",
    contract_version=1,
)


@dataclass(frozen=True, slots=True)
class DriverConstructionContext:
    """External dependencies supplied explicitly to registry factories."""

    mock: bool
    calibration_store: object | None = None
    data_dir: Path = Path("data")
    keithley_watchdog: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        normalized = _normalize_keithley_watchdog(self.keithley_watchdog, path="keithley.watchdog")
        object.__setattr__(self, "keithley_watchdog", MappingProxyType(normalized))

    @classmethod
    def from_root_config(
        cls,
        root: Mapping[str, object],
        *,
        mock: bool,
        calibration_store: object | None = None,
        data_dir: Path = Path("data"),
    ) -> DriverConstructionContext:
        if not isinstance(root, Mapping):
            raise DriverRegistryError("root config must be a mapping")
        keithley = root.get("keithley", {})
        if not isinstance(keithley, Mapping):
            raise DriverRegistryError("keithley must be a mapping")
        if any(not isinstance(key, str) for key in keithley):
            raise DriverRegistryError("keithley keys must be strings")
        unknown = sorted(set(keithley) - {"watchdog"})
        if unknown:
            raise DriverRegistryError(f"keithley has unknown keys: {', '.join(unknown)}")
        watchdog = keithley.get("watchdog", {})
        if not isinstance(watchdog, Mapping):
            raise DriverRegistryError("keithley.watchdog must be a mapping")
        return cls(
            mock=mock,
            calibration_store=calibration_store,
            data_dir=data_dir,
            keithley_watchdog=watchdog,
        )


_VALIDATION_PROVENANCE: Final = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedInstrumentConfig:
    """A registry-created proof that one complete entry passed validation."""

    spec: DriverSpec
    name: str
    values: Mapping[str, object]
    _provenance: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise DriverRegistryError(
            "ValidatedInstrumentConfig cannot be constructed directly; use validate_instrument_entry"
        )

    @classmethod
    def _from_validated(cls, *, spec: DriverSpec, name: str, values: Mapping[str, object]) -> ValidatedInstrumentConfig:
        values = _revalidate_canonical_values(spec=spec, name=name, values=values)
        frozen = _freeze_schema_value(values, path="ValidatedInstrumentConfig.values")
        assert isinstance(frozen, Mapping)
        instance = object.__new__(cls)
        object.__setattr__(instance, "spec", spec)
        object.__setattr__(instance, "name", name)
        object.__setattr__(instance, "values", frozen)
        object.__setattr__(instance, "_provenance", _VALIDATION_PROVENANCE)
        return instance


ConfigNormalizer = Callable[[dict[str, object], str], dict[str, object]]
DriverFactory = Callable[[ValidatedInstrumentConfig, DriverConstructionContext], InstrumentDriver]


@dataclass(frozen=True, slots=True)
class DriverSpec:
    """Immutable metadata and exact constructor for one built-in driver."""

    type_name: str
    module: str
    class_name: str
    authority: DriverAuthority
    capabilities: frozenset[DriverCapability]
    config_fields: Mapping[str, ConfigField]
    normalizer: ConfigNormalizer
    factory: DriverFactory
    reviewed_source_binding: ReviewedSourceBinding | None = None

    def __post_init__(self) -> None:
        capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, DriverCapability) for item in capabilities):
            raise TypeError("DriverSpec.capabilities must contain DriverCapability values")
        object.__setattr__(self, "capabilities", capabilities)

        fields = dict(self.config_fields)
        if any(not isinstance(key, str) or not isinstance(value, ConfigField) for key, value in fields.items()):
            raise TypeError("DriverSpec.config_fields must map strings to ConfigField values")
        object.__setattr__(self, "config_fields", MappingProxyType(fields))

        source_capabilities = {
            DriverCapability.CONTROLLED_SOURCE,
            DriverCapability.VERIFIED_OFF_SOURCE,
        }
        if self.authority is DriverAuthority.PASSIVE_MEASUREMENT:
            if capabilities & source_capabilities or self.reviewed_source_binding is not None:
                raise ValueError("passive DriverSpec cannot declare source authority")
            return
        if not source_capabilities.issubset(capabilities):
            raise ValueError("reviewed source requires controlled-source and verified-OFF capabilities")
        binding = self.reviewed_source_binding
        if binding is not KEITHLEY_2604B_SOURCE_BINDING or binding.driver_type != self.type_name:
            raise ValueError("reviewed source requires the exact typed Keithley safety binding")


def _identity_normalizer(values: dict[str, object], _path: str) -> dict[str, object]:
    return values


def _lakeshore_normalizer(values: dict[str, object], path: str) -> dict[str, object]:
    resource = values.get("resource")
    if not isinstance(resource, str) or re.fullmatch(r"GPIB[0-9]+::[0-9]+::INSTR", resource, re.IGNORECASE) is None:
        raise DriverRegistryError(f"{path}.resource must be an exact GPIB instrument resource")
    return values


def _multiline_normalizer(values: dict[str, object], path: str) -> dict[str, object]:
    selected = int("channels" in values) + int("channel_count" in values)
    if selected != 1:
        raise DriverRegistryError(f"{path} must define exactly one of channels or channel_count")
    return values


def _construct_lakeshore(config: ValidatedInstrumentConfig, context: DriverConstructionContext) -> InstrumentDriver:
    from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S

    values = config.values
    channels = values["channels"]
    assert isinstance(channels, Mapping)
    return LakeShore218S(
        config.name,
        str(values["resource"]),
        channel_labels=dict(channels),
        mock=context.mock,
        calibration_store=context.calibration_store,  # type: ignore[arg-type]
        connect_timeout_s=float(values["connect_timeout_s"]),
        read_timeout_s=float(values["read_timeout_s"]),
    )


def _construct_thyracont(config: ValidatedInstrumentConfig, context: DriverConstructionContext) -> InstrumentDriver:
    from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D

    values = config.values
    return ThyracontVSP63D(
        config.name,
        str(values["resource"]),
        baudrate=int(values["baudrate"]),
        address=str(values["address"]),
        validate_checksum=bool(values["validate_checksum"]),
        mock=context.mock,
    )


def _construct_multiline(config: ValidatedInstrumentConfig, context: DriverConstructionContext) -> InstrumentDriver:
    from cryodaq.drivers.instruments.etalon_multiline import MultiLineDriver

    values = config.values
    channels = values.get("channels")
    return MultiLineDriver(
        config.name,
        str(values["host"]),
        port=int(values["port"]),
        channel_numbers=list(channels) if isinstance(channels, tuple) else None,
        channel_count=int(values["channel_count"]) if "channel_count" in values else None,
        connect_timeout_s=float(values["connect_timeout_s"]),
        read_timeout_s=float(values["read_timeout_s"]),
        mode=str(values["mode"]),
        target_rate_hz=float(values["target_rate_hz"]),
        burst_dir=context.data_dir / "multiline_bursts",
        mock=context.mock,
    )


def _construct_keithley(config: ValidatedInstrumentConfig, context: DriverConstructionContext) -> InstrumentDriver:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    watchdog = context.keithley_watchdog
    mode = watchdog.get("mode")
    enabled = None if mode is not None else bool(watchdog.get("enabled", False))
    driver = Keithley2604B(
        config.name,
        str(config.values["resource"]),
        mock=context.mock,
        watchdog_mode=str(mode) if mode is not None else None,
        watchdog_enabled=enabled,
        watchdog_timeout_s=float(watchdog.get("timeout_s", 5.0)),
    )
    timeout_s = float(watchdog.get("timeout_s", 5.0))
    poll_interval_s = float(config.values["poll_interval_s"])
    armed = (mode not in (None, "off")) or bool(enabled)
    if armed and timeout_s < 2.0 * poll_interval_s:
        logger.warning(
            "Keithley watchdog timeout_s=%.2f is < 2×poll_interval_s=%.2f "
            "— a single slow poll may trigger the late-pet watchdog",
            timeout_s,
            poll_interval_s,
        )
    return driver


_COMMON_FIELDS: Final[dict[str, ConfigField]] = {
    "type": ConfigField(ValueKind.STRING, required=True, setup_visible=False),
    "name": ConfigField(ValueKind.STRING, required=True),
    "poll_interval_s": ConfigField(ValueKind.NUMBER, default=1.0, minimum=0.01, maximum=86_400.0),
    "connect_timeout_s": ConfigField(ValueKind.NUMBER, default=10.0, minimum=0.01, maximum=300.0),
    "read_timeout_s": ConfigField(ValueKind.NUMBER, default=10.0, minimum=0.01, maximum=300.0),
}


def _fields(**specific: ConfigField) -> Mapping[str, ConfigField]:
    return {**_COMMON_FIELDS, **specific}


_PASSIVE_SPECS = {
    "lakeshore_218s": DriverSpec(
        type_name="lakeshore_218s",
        module="cryodaq.drivers.instruments.lakeshore_218s",
        class_name="LakeShore218S",
        authority=DriverAuthority.PASSIVE_MEASUREMENT,
        capabilities=frozenset({DriverCapability.PASSIVE_SENSOR}),
        config_fields=_fields(
            resource=ConfigField(ValueKind.STRING, required=True),
            channels=ConfigField(ValueKind.STRING_MAP, default={}),
            connect_timeout_s=ConfigField(ValueKind.NUMBER, default=3.0, minimum=0.01, maximum=300.0),
            read_timeout_s=ConfigField(ValueKind.NUMBER, default=3.0, minimum=0.01, maximum=300.0),
        ),
        normalizer=_lakeshore_normalizer,
        factory=_construct_lakeshore,
    ),
    "thyracont_vsp63d": DriverSpec(
        type_name="thyracont_vsp63d",
        module="cryodaq.drivers.instruments.thyracont_vsp63d",
        class_name="ThyracontVSP63D",
        authority=DriverAuthority.PASSIVE_MEASUREMENT,
        capabilities=frozenset({DriverCapability.PASSIVE_SENSOR}),
        config_fields=_fields(
            resource=ConfigField(ValueKind.STRING, required=True),
            baudrate=ConfigField(ValueKind.INTEGER, default=9600, choices=(9600, 115200)),
            address=ConfigField(ValueKind.STRING, default="001"),
            validate_checksum=ConfigField(ValueKind.BOOLEAN, default=True),
        ),
        normalizer=_identity_normalizer,
        factory=_construct_thyracont,
    ),
    "etalon_multiline": DriverSpec(
        type_name="etalon_multiline",
        module="cryodaq.drivers.instruments.etalon_multiline",
        class_name="MultiLineDriver",
        authority=DriverAuthority.PASSIVE_MEASUREMENT,
        capabilities=frozenset({DriverCapability.PASSIVE_SENSOR, DriverCapability.BURST_SENSOR}),
        config_fields=_fields(
            host=ConfigField(ValueKind.STRING, default="localhost"),
            port=ConfigField(ValueKind.INTEGER, default=2001, minimum=1, maximum=65_535),
            channels=ConfigField(ValueKind.INTEGER_LIST),
            channel_count=ConfigField(ValueKind.INTEGER, minimum=1, maximum=32),
            connect_timeout_s=ConfigField(ValueKind.NUMBER, default=5.0, minimum=0.01, maximum=300.0),
            read_timeout_s=ConfigField(ValueKind.NUMBER, default=10.0, minimum=0.01, maximum=300.0),
            mode=ConfigField(
                ValueKind.STRING,
                default="averaged",
                choices=("averaged", "continuous"),
            ),
            target_rate_hz=ConfigField(ValueKind.NUMBER, default=1.0, minimum=0.01, maximum=10_000.0),
        ),
        normalizer=_multiline_normalizer,
        factory=_construct_multiline,
    ),
}

_SOURCE_SPECS = {
    "keithley_2604b": DriverSpec(
        type_name="keithley_2604b",
        module="cryodaq.drivers.instruments.keithley_2604b",
        class_name="Keithley2604B",
        authority=DriverAuthority.REVIEWED_SOURCE,
        capabilities=frozenset(
            {
                DriverCapability.PASSIVE_SENSOR,
                DriverCapability.CONTROLLED_SOURCE,
                DriverCapability.VERIFIED_OFF_SOURCE,
            }
        ),
        config_fields=_fields(resource=ConfigField(ValueKind.STRING, required=True)),
        normalizer=_identity_normalizer,
        factory=_construct_keithley,
        reviewed_source_binding=KEITHLEY_2604B_SOURCE_BINDING,
    )
}

_CANONICAL_DRIVER_SPECS: Final[tuple[DriverSpec, ...]] = tuple([*_PASSIVE_SPECS.values(), *_SOURCE_SPECS.values()])
PASSIVE_DRIVER_SPECS: Final[Mapping[str, DriverSpec]] = MappingProxyType(
    {spec.type_name: spec for spec in _CANONICAL_DRIVER_SPECS if spec.authority is DriverAuthority.PASSIVE_MEASUREMENT}
)
REVIEWED_SOURCE_SPECS: Final[Mapping[str, DriverSpec]] = MappingProxyType(
    {spec.type_name: spec for spec in _CANONICAL_DRIVER_SPECS if spec.authority is DriverAuthority.REVIEWED_SOURCE}
)
BUILTIN_DRIVER_SPECS: Final[Mapping[str, DriverSpec]] = MappingProxyType(
    {spec.type_name: spec for spec in _CANONICAL_DRIVER_SPECS}
)
del _PASSIVE_SPECS, _SOURCE_SPECS
ALLOWLISTED_DRIVER_MODULES: Final[tuple[str, ...]] = tuple(
    sorted(spec.module for spec in BUILTIN_DRIVER_SPECS.values())
)


def _normalize_keithley_watchdog(value: object, *, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise DriverRegistryError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise DriverRegistryError(f"{path} keys must be strings")
    unknown = sorted(set(value) - {"mode", "enabled", "timeout_s"})
    if unknown:
        raise DriverRegistryError(f"{path} has unknown keys: {', '.join(unknown)}")
    normalized: dict[str, object] = {}
    if "mode" in value:
        mode = value["mode"]
        if not isinstance(mode, str) or mode not in {"off", "best_effort", "required"}:
            raise DriverRegistryError(f"{path}.mode must be one of ('off', 'best_effort', 'required')")
        normalized["mode"] = mode
    if "enabled" in value:
        enabled = value["enabled"]
        if not isinstance(enabled, bool):
            raise DriverRegistryError(f"{path}.enabled must be a boolean")
        normalized["enabled"] = enabled
    timeout = value.get("timeout_s", 5.0)
    normalized["timeout_s"] = _validate_number(f"{path}.timeout_s", timeout, minimum=1.0, maximum=300.0)
    return normalized


def get_driver_spec(type_name: object) -> DriverSpec:
    """Resolve one exact built-in type or fail visibly."""

    if not isinstance(type_name, str) or not type_name:
        raise UnknownDriverTypeError("instrument.type must be a non-empty string")
    try:
        return BUILTIN_DRIVER_SPECS[type_name]
    except KeyError as exc:
        raise UnknownDriverTypeError(f"unknown instrument type {type_name!r}") from exc


def _validate_number(
    path: str,
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DriverRegistryError(f"{path} must be a number")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DriverRegistryError(f"{path} must be a finite representable number") from exc
    if not math.isfinite(result):
        raise DriverRegistryError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise DriverRegistryError(f"{path} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise DriverRegistryError(f"{path} must be <= {maximum}")
    return result


def _validate_field(path: str, value: object, field: ConfigField) -> object:
    kind = field.kind
    if kind is ValueKind.STRING:
        if not isinstance(value, str) or not value.strip():
            raise DriverRegistryError(f"{path} must be a non-empty string")
        result: object = value
    elif kind is ValueKind.BOOLEAN:
        if not isinstance(value, bool):
            raise DriverRegistryError(f"{path} must be a boolean")
        result = value
    elif kind is ValueKind.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DriverRegistryError(f"{path} must be an integer")
        result = value
    elif kind is ValueKind.NUMBER:
        result = _validate_number(path, value, minimum=field.minimum, maximum=field.maximum)
    elif kind is ValueKind.STRING_MAP:
        if not isinstance(value, Mapping):
            raise DriverRegistryError(f"{path} must be a mapping")
        normalized: dict[int, str] = {}
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, int) or key < 1:
                raise DriverRegistryError(f"{path} keys must be positive integers")
            if not isinstance(item, str) or not item.strip():
                raise DriverRegistryError(f"{path}[{key}] must be a non-empty string")
            normalized[key] = item
        result = MappingProxyType(normalized)
    elif kind is ValueKind.INTEGER_LIST:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise DriverRegistryError(f"{path} must be a sequence of integers")
        items = tuple(value)
        if not items or any(isinstance(item, bool) or not isinstance(item, int) for item in items):
            raise DriverRegistryError(f"{path} must contain integers")
        if any(item < 1 or item > 32 for item in items) or len(set(items)) != len(items):
            raise DriverRegistryError(f"{path} must contain unique channel numbers in 1..32")
        result = items
    else:  # pragma: no cover
        raise AssertionError(f"unsupported field kind {kind}")

    if kind is ValueKind.INTEGER:
        if field.minimum is not None and result < field.minimum:  # type: ignore[operator]
            raise DriverRegistryError(f"{path} must be >= {field.minimum}")
        if field.maximum is not None and result > field.maximum:  # type: ignore[operator]
            raise DriverRegistryError(f"{path} must be <= {field.maximum}")
    if field.choices and result not in field.choices:
        raise DriverRegistryError(f"{path} must be one of {field.choices!r}")
    return result


def _revalidate_canonical_values(*, spec: DriverSpec, name: str, values: Mapping[str, object]) -> dict[str, object]:
    """Revalidate provenance-factory input so even private misuse fails closed."""

    if not isinstance(spec, DriverSpec):
        raise DriverRegistryError("validated config spec must be a DriverSpec")
    canonical = get_driver_spec(spec.type_name)
    if spec is not canonical:
        raise DriverRegistryError("validated config requires a canonical registry spec")
    if not isinstance(values, Mapping):
        raise DriverRegistryError("validated config values must be a mapping")
    if any(not isinstance(key, str) for key in values):
        raise DriverRegistryError("validated config keys must be strings")
    unknown = sorted(set(values) - set(spec.config_fields))
    if unknown:
        raise DriverRegistryError(f"validated config has unknown keys: {', '.join(unknown)}")
    checked: dict[str, object] = {}
    for key, schema in spec.config_fields.items():
        if key in values:
            checked[key] = _validate_field(f"validated config.{key}", values[key], schema)
        elif schema.required or schema.default is not None:
            raise DriverRegistryError(f"validated config.{key} is missing")
    checked = spec.normalizer(checked, "validated config")
    checked_name = checked.get("name")
    if not isinstance(name, str) or name != checked_name:
        raise DriverRegistryError("validated config.name does not match its identity")
    return checked


def validate_instrument_entry(entry: object, *, path: str = "instruments[0]") -> ValidatedInstrumentConfig:
    """Validate and normalize one complete instrument entry."""

    if not isinstance(entry, Mapping):
        raise DriverRegistryError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in entry):
        raise DriverRegistryError(f"{path} keys must be strings")
    try:
        spec = get_driver_spec(entry.get("type"))
    except UnknownDriverTypeError as exc:
        raise UnknownDriverTypeError(f"{path}.type: {exc}") from exc
    unknown = sorted(set(entry) - set(spec.config_fields))
    if unknown:
        raise DriverRegistryError(f"{path} has unknown keys: {', '.join(unknown)}")

    values: dict[str, object] = {}
    for key, schema in spec.config_fields.items():
        if key in entry:
            values[key] = _validate_field(f"{path}.{key}", entry[key], schema)
        elif schema.required:
            raise DriverRegistryError(f"{path}.{key} is required")
        elif schema.default is not None:
            values[key] = _validate_field(f"{path}.{key}", schema.default, schema)

    values = spec.normalizer(values, path)
    name = values["name"]
    assert isinstance(name, str)
    return ValidatedInstrumentConfig._from_validated(spec=spec, name=name, values=values)


def validate_instrument_entries(entries: object) -> tuple[ValidatedInstrumentConfig, ...]:
    """Validate an instrument list and reject duplicate instance identities."""

    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise DriverRegistryError("instruments must be a sequence")
    configs: list[ValidatedInstrumentConfig] = []
    names: set[str] = set()
    for index, entry in enumerate(entries):
        config = validate_instrument_entry(entry, path=f"instruments[{index}]")
        if config.name in names:
            raise DuplicateInstrumentNameError(f"instruments[{index}].name duplicates {config.name!r}")
        names.add(config.name)
        configs.append(config)
    return tuple(configs)


def construct_driver(config: ValidatedInstrumentConfig, context: DriverConstructionContext) -> InstrumentDriver:
    """Construct through the exact factory owned by the validated spec."""

    if (
        not isinstance(config, ValidatedInstrumentConfig)
        or getattr(config, "_provenance", None) is not _VALIDATION_PROVENANCE
    ):
        raise DriverRegistryError("construct_driver requires output from validate_instrument_entry")
    if not isinstance(context, DriverConstructionContext):
        raise DriverRegistryError("construct_driver requires a DriverConstructionContext")
    canonical = get_driver_spec(config.spec.type_name)
    if config.spec is not canonical:
        raise DriverRegistryError("validated config does not reference a canonical registry spec")
    driver = canonical.factory(config, context)
    if not isinstance(driver, InstrumentDriver):
        raise DriverRegistryError(f"factory for {canonical.type_name!r} returned an invalid driver")
    binding = _runtime_binding(config, driver)
    with _RUNTIME_BINDINGS_LOCK:
        _RUNTIME_BINDINGS[driver] = binding
    return driver


_GPIB_RESOURCE = re.compile(r"^(GPIB[0-9]+)::[0-9]+::INSTR$", re.IGNORECASE)
_RUNTIME_BINDINGS: weakref.WeakKeyDictionary[InstrumentDriver, DriverRuntimeBinding] = weakref.WeakKeyDictionary()
_RUNTIME_BINDINGS_LOCK = threading.Lock()


def _runtime_binding(config: ValidatedInstrumentConfig, driver: InstrumentDriver) -> DriverRuntimeBinding:
    values = config.values
    timing = AcquisitionTiming(
        connect_timeout_s=float(values["connect_timeout_s"]),
        read_timeout_s=float(values["read_timeout_s"]),
        poll_interval_s=float(values["poll_interval_s"]),
    )
    bus_descriptor: BusDescriptor | None = None
    if config.spec.type_name == "lakeshore_218s":
        resource = str(values["resource"])
        match = _GPIB_RESOURCE.fullmatch(resource)
        if match is None:
            raise DriverRegistryError(
                f"validated config.resource is not an exact GPIB instrument resource: {resource!r}"
            )
        bus_descriptor = BusDescriptor(match.group(1).upper())
    if config.spec.authority is DriverAuthority.REVIEWED_SOURCE and bus_descriptor is not None:
        raise DriverRegistryError("reviewed source cannot receive generic shared-bus recovery authority")
    trust_class = (
        DriverTrustClass.REVIEWED_SOURCE
        if config.spec.authority is DriverAuthority.REVIEWED_SOURCE
        else DriverTrustClass.PASSIVE_MEASUREMENT
    )
    return _issue_registry_runtime_binding(
        driver=driver,
        timing=timing,
        registry_provenance=f"builtin:{DRIVER_REGISTRY_COMPAT_VERSION}:{config.spec.type_name}",
        trust_class=trust_class,
        bus_descriptor=bus_descriptor,
        lifecycle=driver if config.spec.type_name == "lakeshore_218s" else None,
    )


def runtime_binding_for_driver(driver: InstrumentDriver) -> DriverRuntimeBinding | None:
    """Return only the binding created beside this exact registry driver instance."""

    with _RUNTIME_BINDINGS_LOCK:
        return _RUNTIME_BINDINGS.get(driver)
