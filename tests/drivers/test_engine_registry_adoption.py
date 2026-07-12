"""Engine adoption tests for the static F35 driver registry."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
import yaml

import cryodaq.engine as engine_module
from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.drivers.base import InstrumentDriver
from cryodaq.drivers.registry import (
    KEITHLEY_2604B_SOURCE_BINDING,
    DriverRegistryError,
    DuplicateInstrumentNameError,
    UnknownDriverTypeError,
)
from cryodaq.engine import DriverLoadResult, _load_drivers, _run_engine


@pytest.mark.parametrize(
    "registry_error",
    [
        UnknownDriverTypeError("unknown instrument type 'missing'"),
        DuplicateInstrumentNameError("duplicate instrument name 'same'"),
    ],
)
def test_main_labels_registry_subclasses_and_exits_as_config_error(
    registry_error: DriverRegistryError,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_startup(*, mock: bool) -> None:
        assert mock is True
        raise registry_error

    monkeypatch.setattr(engine_module.sys, "argv", ["cryodaq-engine", "--mock"])
    monkeypatch.setattr(engine_module, "_acquire_engine_lock", lambda: 42)
    monkeypatch.setattr(engine_module, "_release_engine_lock", lambda _fd: None)
    monkeypatch.setattr(engine_module, "_run_engine", _fail_startup)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)

    with caplog.at_level("CRITICAL"), pytest.raises(SystemExit) as exc_info:
        engine_module.main()

    assert exc_info.value.code == engine_module.ENGINE_CONFIG_ERROR_EXIT_CODE == 2
    assert "CONFIG ERROR (driver registry config)" in caplog.text


def _write_config(tmp_path: Path, root: object) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.safe_dump(root, allow_unicode=True), encoding="utf-8")
    return path


def test_current_config_preserves_classes_order_metadata_and_dependencies(tmp_path: Path) -> None:
    calibration_store = CalibrationStore(tmp_path / "calibration")
    data_dir = tmp_path / "runtime-data"

    result = _load_drivers(
        Path("config/instruments.yaml"),
        mock=True,
        calibration_store=calibration_store,
        data_dir=data_dir,
    )

    assert [type(config.driver).__name__ for config in result.instrument_configs] == [
        "LakeShore218S",
        "LakeShore218S",
        "LakeShore218S",
        "Keithley2604B",
        "ThyracontVSP63D",
        "MultiLineDriver",
    ]
    assert [config.driver.name for config in result.instrument_configs] == [
        "LS218_1",
        "LS218_2",
        "LS218_3",
        "Keithley_1",
        "VSP63D_1",
        "MultiLine_1",
    ]
    assert [config.poll_interval_s for config in result.instrument_configs] == [
        2.0,
        2.0,
        2.0,
        1.0,
        2.0,
        2.0,
    ]
    assert [config.resource_str for config in result.instrument_configs] == [
        "GPIB0::12::INSTR",
        "GPIB0::14::INSTR",
        "GPIB0::16::INSTR",
        "USB0::0x05E6::0x2604::04052028::INSTR",
        "COM3",
        "",
    ]
    assert [config.read_timeout_s for config in result.instrument_configs] == [
        3.0,
        3.0,
        3.0,
        10.0,
        10.0,
        10.0,
    ]
    assert [config.connect_timeout_s for config in result.instrument_configs] == [
        3.0,
        3.0,
        3.0,
        10.0,
        10.0,
        5.0,
    ]
    assert [
        config.runtime_binding.bus_descriptor.bus_id
        if config.runtime_binding and config.runtime_binding.bus_descriptor
        else None
        for config in result.instrument_configs
    ] == ["GPIB0", "GPIB0", "GPIB0", None, None, None]
    assert all(config.enabled is True for config in result.instrument_configs)
    assert all(
        config.driver._calibration_store is calibration_store  # type: ignore[attr-defined]
        for config in result.instrument_configs[:3]
    )
    assert result.instrument_configs[-1].driver._burst_dir == data_dir / "multiline_bursts"  # type: ignore[attr-defined]


def test_load_result_preserves_canonical_provenance_and_exact_source_identity(tmp_path: Path) -> None:
    result = _load_drivers(Path("config/instruments.yaml"), mock=True, data_dir=tmp_path)

    source_config = next(config for config in result.instrument_configs if config.driver.name == "Keithley_1")
    assert result.reviewed_source is source_config.driver
    assert result.reviewed_source_binding is KEITHLEY_2604B_SOURCE_BINDING
    assert result.validated_configs[3].spec.reviewed_source_binding is KEITHLEY_2604B_SOURCE_BINDING
    with pytest.raises(AttributeError):
        result.instrument_configs = ()  # type: ignore[misc]


def test_zero_reviewed_sources_is_valid_and_returns_no_authority(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {
                    "type": "thyracont_vsp63d",
                    "name": "vacuum",
                    "resource": "COM3",
                }
            ]
        },
    )

    result = _load_drivers(path, mock=True, data_dir=tmp_path)

    assert len(result.instrument_configs) == 1
    assert result.reviewed_source is None
    assert result.reviewed_source_binding is None


def test_all_entries_validate_before_any_factory_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {
                    "type": "thyracont_vsp63d",
                    "name": "valid-first",
                    "resource": "COM3",
                },
                {"type": "unknown_source", "name": "invalid-second", "resource": "USB::1"},
            ]
        },
    )
    calls: list[object] = []
    monkeypatch.setattr(engine_module, "construct_driver", lambda *args: calls.append(args))

    with pytest.raises(DriverRegistryError, match=r"instruments\[1\].*unknown instrument type"):
        _load_drivers(path, mock=True, data_dir=tmp_path)

    assert calls == []


def test_multiple_reviewed_sources_fail_before_any_factory_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {"type": "keithley_2604b", "name": "source-a", "resource": "USB::1"},
                {"type": "keithley_2604b", "name": "source-b", "resource": "USB::2"},
            ]
        },
    )
    calls: list[object] = []
    monkeypatch.setattr(engine_module, "construct_driver", lambda *args: calls.append(args))

    with pytest.raises(DriverRegistryError, match="multiple reviewed sources"):
        _load_drivers(path, mock=True, data_dir=tmp_path)

    assert calls == []


@pytest.mark.parametrize("root", [None, [], "instruments", 42])
def test_malformed_root_is_path_qualified_registry_error(tmp_path: Path, root: object) -> None:
    path = _write_config(tmp_path, root)

    with pytest.raises(DriverRegistryError, match=rf"{path}.*root config must be a mapping"):
        _load_drivers(path, mock=True, data_dir=tmp_path)


def test_constructor_failure_has_one_path_qualified_public_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {
                    "type": "thyracont_vsp63d",
                    "name": "vacuum",
                    "resource": "COM3",
                }
            ]
        },
    )

    def _fail(_config: object, _context: object) -> InstrumentDriver:
        raise RuntimeError("constructor detail")

    monkeypatch.setattr(engine_module, "construct_driver", _fail)

    with pytest.raises(
        DriverRegistryError,
        match=rf"{path}.*instruments\[0\].*'vacuum'.*construction failed",
    ) as exc_info:
        _load_drivers(path, mock=True, data_dir=tmp_path)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "constructor detail" not in str(exc_info.value)


def test_passive_protocol_lookalike_cannot_become_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PassiveLookalike(InstrumentDriver):
        async def connect(self) -> None:
            self._connected = True

        async def disconnect(self) -> None:
            self._connected = False

        async def read_channels(self) -> list[object]:  # type: ignore[override]
            return []

        async def start_source(self, *_args: object) -> None:
            return None

        async def stop_source(self, *_args: object) -> None:
            return None

        async def emergency_off(self, *_args: object) -> bool:
            return True

        @property
        def output_state_unverified(self) -> bool:
            return False

    path = _write_config(
        tmp_path,
        {
            "instruments": [
                {
                    "type": "thyracont_vsp63d",
                    "name": "passive",
                    "resource": "COM3",
                }
            ]
        },
    )
    lookalike = _PassiveLookalike("lookalike", mock=True)
    monkeypatch.setattr(engine_module, "construct_driver", lambda *_args: lookalike)

    # Protocol conformance is deliberately insufficient without the exact
    # canonical reviewed registry spec/binding paired to this instance.
    result = _load_drivers(path, mock=True, data_dir=tmp_path)
    assert result.reviewed_source is None
    assert result.reviewed_source_binding is None


def test_engine_loader_contains_no_vendor_switch_or_method_authority_scan() -> None:
    loader_tree = ast.parse(inspect.getsource(engine_module._load_drivers))
    for node in ast.walk(loader_tree):
        if not isinstance(node, ast.If):
            continue
        compared_literals = {
            child.value
            for child in ast.walk(node.test)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        assert compared_literals.isdisjoint(
            {
                "lakeshore_218s",
                "thyracont_vsp63d",
                "etalon_multiline",
                "asc_reference_tcp",
                "keithley_2604b",
            }
        )

    run_source = inspect.getsource(engine_module._run_engine)
    assert 'hasattr(cfg.driver, "emergency_off")' not in run_source
    assert "keithley_driver=driver_load.reviewed_source" in run_source


def test_reference_extension_adoption_requires_no_central_engine_edit() -> None:
    source = Path(inspect.getsourcefile(engine_module) or "").read_text(encoding="utf-8")
    assert "asc_reference_tcp" not in source
    assert "ASCReferenceTCP" not in source


async def test_run_engine_passes_live_dependencies_and_exact_recorded_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StopAfterSafetyBinding(RuntimeError):
        pass

    source = object()
    observed: dict[str, object] = {}

    def _fake_load_drivers(
        config_path: Path,
        *,
        mock: bool,
        calibration_store: CalibrationStore | None = None,
        data_dir: Path | None = None,
    ) -> DriverLoadResult:
        observed["config_path"] = config_path
        observed["mock"] = mock
        observed["calibration_store"] = calibration_store
        observed["data_dir"] = data_dir
        return DriverLoadResult((), (), source, KEITHLEY_2604B_SOURCE_BINDING)  # type: ignore[arg-type]

    class _RecordingSafetyManager:
        def __init__(self, _broker: object, *, keithley_driver: object, **_kwargs: object) -> None:
            observed["source"] = keithley_driver

        def load_config(self, _path: Path) -> None:
            raise _StopAfterSafetyBinding

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "live-data"
    config_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(engine_module, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(engine_module, "_DATA_DIR", data_dir)
    monkeypatch.setattr(engine_module, "_load_drivers", _fake_load_drivers)
    monkeypatch.setattr(engine_module, "SafetyManager", _RecordingSafetyManager)

    with pytest.raises(_StopAfterSafetyBinding):
        await _run_engine(mock=True)

    assert observed["config_path"] == config_dir / "instruments.yaml"
    assert observed["mock"] is True
    assert isinstance(observed["calibration_store"], CalibrationStore)
    assert observed["data_dir"] is data_dir
    assert observed["source"] is source
