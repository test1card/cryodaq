"""Hazardous-source authority is a roster, not one vendor's binding.

A second lab must be able to adopt its own hazardous actuator by putting that
actuator's binding through the same review the Keithley binding went through
and adding it to the reviewed roster -- not by editing an identity comparison
in the registry or in the engine.  These tests pin that property, and pin the
safety properties that must survive it: an unrostered binding never acquires
source authority, a structurally conforming driver never acquires it either,
and SafetyManager still supervises at most one reviewed source.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

import cryodaq.drivers.registry as registry_module
import cryodaq.engine as engine_module
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import ControlledSource, DriverTrustClass, VerifiedOffSource
from cryodaq.drivers.registry import (
    KEITHLEY_2604B_SOURCE_BINDING,
    DriverAuthority,
    DriverCapability,
    DriverConstructionContext,
    DriverRegistryError,
    DriverSpec,
    ReviewedSourceBinding,
    ValidatedInstrumentConfig,
    runtime_binding_for_driver,
)
from cryodaq.engine import _load_drivers

ACME_SOURCE_BINDING = ReviewedSourceBinding(
    driver_type="acme_psu_9000",
    adapter_module="cryodaq.core.safety_manager",
    adapter_class="SafetyManager",
    contract_version=1,
)


class _AcmePSU9000(InstrumentDriver):
    """A fictional second reviewed actuator with real source behaviour."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        return None

    async def stop_source(self, channel: str) -> None:
        return None

    async def emergency_off(self, channel: str | None = None) -> bool:
        return True

    @property
    def output_state_unverified(self) -> bool:
        return False


class _AcmeWithoutVerifiedOff(InstrumentDriver):
    """Same vendor, no readback-verified OFF: must not become the source."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        return None

    async def stop_source(self, channel: str) -> None:
        return None


def _construct_acme(
    config: ValidatedInstrumentConfig,
    context: DriverConstructionContext,
) -> InstrumentDriver:
    return _AcmePSU9000(config.name, mock=context.mock)


def _construct_acme_without_verified_off(
    config: ValidatedInstrumentConfig,
    context: DriverConstructionContext,
) -> InstrumentDriver:
    return _AcmeWithoutVerifiedOff(config.name, mock=context.mock)


def _acme_spec(
    *,
    binding: ReviewedSourceBinding = ACME_SOURCE_BINDING,
    factory: object = _construct_acme,
) -> DriverSpec:
    """Build the fictional actuator's spec from the reviewed source shape."""

    keithley = registry_module.REVIEWED_SOURCE_SPECS["keithley_2604b"]
    return DriverSpec(
        type_name="acme_psu_9000",
        module="cryodaq.drivers.instruments.acme_psu_9000",
        class_name="AcmePSU9000",
        authority=DriverAuthority.REVIEWED_SOURCE,
        capabilities=frozenset(
            {
                DriverCapability.PASSIVE_SENSOR,
                DriverCapability.CONTROLLED_SOURCE,
                DriverCapability.VERIFIED_OFF_SOURCE,
            }
        ),
        config_fields=dict(keithley.config_fields),
        normalizer=keithley.normalizer,
        factory=factory,  # type: ignore[arg-type]
        reviewed_source_binding=binding,
    )


def _review(monkeypatch: pytest.MonkeyPatch, *bindings: ReviewedSourceBinding) -> None:
    """Adopt further reviewed bindings the way a lab would: extend the roster."""

    roster: Mapping[str, ReviewedSourceBinding] = MappingProxyType(
        {binding.driver_type: binding for binding in (KEITHLEY_2604B_SOURCE_BINDING, *bindings)}
    )
    # raising=True on purpose: if the roster is ever renamed away, these tests
    # must fail loudly rather than patch a name nothing reads and quietly stop
    # testing the property they exist for.
    monkeypatch.setattr(registry_module, "REVIEWED_SOURCE_BINDINGS", roster)


def _install_spec(monkeypatch: pytest.MonkeyPatch, spec: DriverSpec) -> None:
    specs = MappingProxyType({**registry_module.BUILTIN_DRIVER_SPECS, spec.type_name: spec})
    monkeypatch.setattr(registry_module, "BUILTIN_DRIVER_SPECS", specs)


def _write_config(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_second_reviewed_actuator_is_admitted_as_a_driver_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)

    spec = _acme_spec()

    assert spec.authority is DriverAuthority.REVIEWED_SOURCE
    assert spec.reviewed_source_binding is ACME_SOURCE_BINDING


def test_engine_adopts_a_second_reviewed_actuator_as_the_reviewed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)
    _install_spec(monkeypatch, _acme_spec())
    path = _write_config(
        tmp_path,
        {"instruments": [{"type": "acme_psu_9000", "name": "acme-source", "resource": "USB::9"}]},
    )

    result = _load_drivers(path, mock=True, data_dir=tmp_path)

    assert isinstance(result.reviewed_source, _AcmePSU9000)
    assert isinstance(result.reviewed_source, ControlledSource)
    assert isinstance(result.reviewed_source, VerifiedOffSource)
    assert result.reviewed_source_binding is ACME_SOURCE_BINDING
    binding = runtime_binding_for_driver(result.reviewed_source)
    assert binding is not None
    assert binding.trust_class is DriverTrustClass.REVIEWED_SOURCE


def test_unrostered_binding_never_acquires_source_authority() -> None:
    unreviewed = ReviewedSourceBinding(
        driver_type="acme_psu_9000",
        adapter_module="cryodaq.core.safety_manager",
        adapter_class="SafetyManager",
        contract_version=1,
    )

    with pytest.raises(ValueError) as exc_info:
        _acme_spec(binding=unreviewed)

    assert "roster" in str(exc_info.value)
    assert "keithley" not in str(exc_info.value).lower()


def test_equal_but_unreviewed_copy_of_a_rostered_binding_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)
    copy = replace(ACME_SOURCE_BINDING)
    assert copy == ACME_SOURCE_BINDING

    with pytest.raises(ValueError, match="roster"):
        _acme_spec(binding=copy)


def test_rostered_binding_must_belong_to_its_own_driver_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)

    with pytest.raises(ValueError, match="driver type"):
        _acme_spec(binding=KEITHLEY_2604B_SOURCE_BINDING)


def test_structural_conformance_alone_does_not_satisfy_the_source_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)
    _install_spec(monkeypatch, _acme_spec(factory=_construct_acme_without_verified_off))
    path = _write_config(
        tmp_path,
        {"instruments": [{"type": "acme_psu_9000", "name": "acme-source", "resource": "USB::9"}]},
    )

    with pytest.raises(DriverRegistryError, match="violates the reviewed source contract"):
        _load_drivers(path, mock=True, data_dir=tmp_path)


def test_two_reviewed_sources_of_any_type_are_still_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _review(monkeypatch, ACME_SOURCE_BINDING)
    _install_spec(monkeypatch, _acme_spec())
    calls: list[object] = []
    monkeypatch.setattr(engine_module, "construct_driver", lambda *args: calls.append(args))
    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {"type": "keithley_2604b", "name": "source-a", "resource": "USB::1"},
                {"type": "acme_psu_9000", "name": "source-b", "resource": "USB::9"},
            ]
        },
    )

    with pytest.raises(DriverRegistryError, match="multiple reviewed sources") as exc_info:
        _load_drivers(path, mock=True, data_dir=tmp_path)

    assert "exactly zero or one reviewed source" in str(exc_info.value)
    assert calls == []


def test_engine_loader_names_no_vendor_source_type() -> None:
    loader_source = inspect.getsource(engine_module._load_drivers)

    assert "keithley" not in loader_source.lower()
