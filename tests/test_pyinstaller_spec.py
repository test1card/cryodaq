from __future__ import annotations

import ast
import importlib
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import cryodaq.drivers.registry as driver_registry

SPEC = Path(__file__).resolve().parent.parent / "build_scripts" / "cryodaq.spec"


class FrozenDriverContractError(AssertionError):
    """The live registry and executable spec cannot produce one driver set."""


def _execute_spec() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Execute the actual spec with inert PyInstaller build-object stand-ins."""

    analysis_calls: list[dict[str, object]] = []
    collected: list[str] = []
    candidates = (
        "cryodaq.engine",
        "cryodaq.drivers.instruments",
        "cryodaq.drivers.instruments.unallowlisted_control",
        "cryodaq.drivers.passive_extensions",
        "cryodaq.drivers.passive_extensions.unallowlisted_control",
        *(spec.module for spec in driver_registry.BUILTIN_DRIVER_SPECS.values()),
    )

    def collect_submodules(package: str, **kwargs: object) -> list[str]:
        assert package == "cryodaq"
        predicate = kwargs.get("filter")
        assert predicate is None or callable(predicate)
        selected = [name for name in candidates if predicate is None or predicate(name)]
        collected.extend(selected)
        return selected

    def collect_data_files(_package: str) -> list[object]:
        return []

    def analysis(*_args: object, **kwargs: object) -> SimpleNamespace:
        analysis_calls.append(kwargs)
        return SimpleNamespace(pure=(), zipped_data=(), scripts=(), binaries=(), datas=(), zipfiles=())

    def build_artifact(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace()

    pyinstaller = ModuleType("PyInstaller")
    utils = ModuleType("PyInstaller.utils")
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = collect_submodules  # type: ignore[attr-defined]
    hooks.collect_data_files = collect_data_files  # type: ignore[attr-defined]
    source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SPEC))
    wiring = [
        node
        for node in tree.body
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "hidden_imports"
        and isinstance(node.op, ast.Add)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "list"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "FROZEN_DRIVER_MODULES"
        and not node.value.keywords
    ]
    if len(wiring) != 1:
        raise FrozenDriverContractError(
            "the actual spec must append FROZEN_DRIVER_MODULES to hidden_imports exactly once"
        )
    namespace: dict[str, object] = {
        "__file__": str(SPEC),
        "SPECPATH": str(SPEC.parent),
        "Analysis": analysis,
        "PYZ": build_artifact,
        "EXE": build_artifact,
        "COLLECT": build_artifact,
    }
    with patch.dict(
        sys.modules,
        {
            "PyInstaller": pyinstaller,
            "PyInstaller.utils": utils,
            "PyInstaller.utils.hooks": hooks,
        },
    ):
        exec(compile(source, str(SPEC), "exec"), namespace)

    assert len(analysis_calls) == 1
    frozen = namespace["FROZEN_DRIVER_MODULES"]
    hidden = analysis_calls[0]["hiddenimports"]
    assert isinstance(frozen, tuple) and all(isinstance(item, str) for item in frozen)
    assert isinstance(hidden, list) and all(isinstance(item, str) for item in hidden)
    return frozen, tuple(hidden), tuple(collected)


def _assert_frozen_driver_contract() -> None:
    frozen, hidden, broadly_collected = _execute_spec()
    registry_modules = tuple(spec.module for spec in driver_registry.BUILTIN_DRIVER_SPECS.values())
    projected_modules = tuple(sorted(registry_modules))
    if projected_modules != driver_registry.ALLOWLISTED_DRIVER_MODULES:
        raise FrozenDriverContractError("ALLOWLISTED_DRIVER_MODULES is stale relative to BUILTIN_DRIVER_SPECS")

    duplicate_registry = sorted(module for module, count in Counter(registry_modules).items() if count > 1)
    duplicate_frozen = sorted(module for module, count in Counter(frozen).items() if count > 1)
    registry_only = sorted(set(registry_modules) - set(frozen))
    frozen_only = sorted(set(frozen) - set(registry_modules))
    if duplicate_registry or duplicate_frozen or registry_only or frozen_only:
        raise FrozenDriverContractError(
            f"duplicate_registry={duplicate_registry}; duplicate_frozen={duplicate_frozen}; "
            f"registry_only={registry_only}; frozen_only={frozen_only}"
        )

    broad_driver_modules = sorted(set(registry_modules) & set(broadly_collected))
    if broad_driver_modules:
        raise FrozenDriverContractError(
            f"allowlisted drivers reached Analysis through broad collection: {broad_driver_modules}"
        )
    hidden_counts = Counter(hidden)
    incorrectly_wired = sorted(module for module in frozen if hidden_counts[module] != 1)
    if incorrectly_wired:
        raise FrozenDriverContractError(
            f"frozen driver modules must reach Analysis.hiddenimports exactly once: {incorrectly_wired}"
        )
    frozen_set = set(frozen)
    hidden_driver_modules = {
        module
        for module in hidden
        if module in frozen_set
        or module == "cryodaq.drivers.instruments"
        or module.startswith("cryodaq.drivers.instruments.")
        or module == "cryodaq.drivers.passive_extensions"
        or module.startswith("cryodaq.drivers.passive_extensions.")
    }
    analysis_driver_missing = sorted(frozen_set - hidden_driver_modules)
    analysis_driver_extra = sorted(hidden_driver_modules - frozen_set)
    if analysis_driver_missing or analysis_driver_extra:
        raise FrozenDriverContractError(
            f"analysis_driver_missing={analysis_driver_missing}; analysis_driver_extra={analysis_driver_extra}"
        )

    verified = driver_registry.verify_allowlisted_driver_imports()
    if verified != projected_modules:
        raise FrozenDriverContractError(
            f"import verifier returned {verified!r}, expected live registry projection {projected_modules!r}"
        )


def _replace_registry(
    monkeypatch: pytest.MonkeyPatch,
    specs: tuple[driver_registry.DriverSpec, ...],
) -> None:
    mapping = MappingProxyType({spec.type_name: spec for spec in specs})
    monkeypatch.setattr(driver_registry, "BUILTIN_DRIVER_SPECS", mapping)
    monkeypatch.setattr(
        driver_registry,
        "ALLOWLISTED_DRIVER_MODULES",
        tuple(sorted(spec.module for spec in specs)),
    )


def _explicit_hidden_imports() -> set[str]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    hidden: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "hidden_imports" for target in node.targets
        ):
            assert isinstance(node.value, ast.List)
            hidden.update(
                item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return hidden


def _frozen_driver_modules() -> tuple[str, ...]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "FROZEN_DRIVER_MODULES" for target in node.targets)
    ]
    assert len(assignments) == 1
    value = assignments[0].value
    assert isinstance(value, ast.Tuple)
    modules = tuple(item.value for item in value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
    assert len(modules) == len(value.elts)
    return modules


def _driver_filter_accepts(module: str) -> bool:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_is_non_driver_application_module"
    )
    module_tree = ast.Module(body=[function], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(module_tree, str(SPEC), "exec"), {"__builtins__": {}}, namespace)
    predicate = namespace["_is_non_driver_application_module"]
    assert callable(predicate)
    return bool(predicate(module))


def test_periodic_child_hidden_imports_are_explicit() -> None:
    hidden = _explicit_hidden_imports()

    assert {
        "cryodaq.reporting.__main__",
        "cryodaq.reporting.periodic_input",
        "cryodaq.reporting.periodic_renderer",
        "matplotlib",
        "matplotlib.backends.backend_agg",
    } <= hidden


def test_h3_assistant_and_lazy_dependencies_are_explicit_not_collect_only() -> None:
    hidden = _explicit_hidden_imports()
    assert {
        "cryodaq.agents.assistant_bootstrap",
        "cryodaq.agents.assistant.periodic_png",
        "cryodaq.agents.assistant.periodic_projection",
        "cryodaq.agents.assistant.periodic_runtime",
        "cryodaq.agents.assistant.periodic_telegram",
        "cryodaq.periodic_config",
        "cryodaq.periodic_state",
        "cryodaq.report_process",
        "cryodaq.storage.archive_reader",
        "zmq",
        "zmq.asyncio",
        "zmq.backend.cython",
        "zmq.utils.monitor",
        "msgpack",
        "msgpack._cmsgpack",
        "aiohttp",
        "aiohttp.client",
        "aiohttp.client_reqrep",
        "aiohttp.cookiejar",
        "aiohttp.connector",
        "aiohttp.formdata",
        "aiohttp.payload",
        "aiohttp.resolver",
        "pyarrow",
        "pyarrow.compute",
        "pyarrow.parquet",
    } <= hidden


def test_spec_remains_onedir_with_frozen_dispatch_entry() -> None:
    source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "COLLECT" in calls
    assert "BUNDLE" not in calls
    assert '"cryodaq" / "_frozen_main.py"' in source
    exe_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "EXE"
    ]
    assert len(exe_calls) == 1
    exclude = next(keyword.value for keyword in exe_calls[0].keywords if keyword.arg == "exclude_binaries")
    assert isinstance(exclude, ast.Constant) and exclude.value is True


def test_gui_package_resources_are_bundled_next_to_the_frozen_module() -> None:
    source = SPEC.read_text(encoding="utf-8")

    assert '"src" / "cryodaq" / "gui" / "resources"' in source
    assert '"cryodaq/gui/resources"' in source


def test_frozen_driver_allowlist_is_exactly_the_runtime_registry_and_importable() -> None:
    _assert_frozen_driver_contract()


def test_frozen_driver_guard_rejects_misdeclared_abstract_base(monkeypatch: pytest.MonkeyPatch) -> None:
    live_specs = tuple(driver_registry.BUILTIN_DRIVER_SPECS.values())
    seed = next(
        spec
        for spec in live_specs
        if getattr(importlib.import_module(spec.module), "InstrumentDriver", None) is driver_registry.InstrumentDriver
    )
    corrupted = replace(seed, class_name="InstrumentDriver")
    _replace_registry(
        monkeypatch,
        tuple(corrupted if spec is seed else spec for spec in live_specs),
    )

    with pytest.raises(driver_registry.DriverRegistryError, match="concrete InstrumentDriver class"):
        _assert_frozen_driver_contract()


def test_frozen_driver_guard_rejects_registry_only_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    live_specs = tuple(driver_registry.BUILTIN_DRIVER_SPECS.values())
    seed = next(spec for spec in live_specs if spec.reviewed_source_binding is None)
    added = replace(
        seed,
        type_name=f"{seed.type_name}_registry_only_control",
        module=f"{seed.module}_registry_only_control",
    )
    _replace_registry(monkeypatch, (*live_specs, added))

    with pytest.raises(FrozenDriverContractError) as caught:
        _assert_frozen_driver_contract()

    message = str(caught.value)
    assert f"registry_only=['{added.module}']" in message
    assert "frozen_only=[]" in message


def test_frozen_driver_guard_rejects_frozen_only_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    live_specs = tuple(driver_registry.BUILTIN_DRIVER_SPECS.values())
    removed = live_specs[0]
    _replace_registry(monkeypatch, tuple(spec for spec in live_specs if spec is not removed))

    with pytest.raises(FrozenDriverContractError) as caught:
        _assert_frozen_driver_contract()

    message = str(caught.value)
    assert "registry_only=[]" in message
    assert f"frozen_only=['{removed.module}']" in message


def test_frozen_driver_guard_rejects_direct_hidden_driver_outside_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SPEC.read_text(encoding="utf-8")
    anchor = "hidden_imports = [\n"
    assert source.count(anchor) == 1
    unexpected = "cryodaq.drivers.instruments.unallowlisted_direct_control"
    mutated_source = source.replace(anchor, f'{anchor}    "{unexpected}",\n', 1)
    mutated_spec = tmp_path / "cryodaq.spec"
    ast.parse(mutated_source, filename=str(mutated_spec))
    mutated_spec.write_text(mutated_source, encoding="utf-8", newline="\n")
    monkeypatch.setitem(globals(), "SPEC", mutated_spec)

    with pytest.raises(FrozenDriverContractError) as caught:
        _assert_frozen_driver_contract()

    message = str(caught.value)
    assert "analysis_driver_missing=[]" in message
    assert f"analysis_driver_extra=['{unexpected}']" in message


def test_frozen_driver_guard_rejects_unallowlisted_driver_from_broad_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SPEC.read_text(encoding="utf-8")
    anchor = "def _is_non_driver_application_module(name):\n    return not (\n"
    assert source.count(anchor) == 1
    unexpected = "cryodaq.drivers.instruments.unallowlisted_control"
    replacement = (
        "def _is_non_driver_application_module(name):\n"
        f'    if name == "{unexpected}":\n'
        "        return True\n"
        "    return not (\n"
    )
    mutated_source = source.replace(anchor, replacement, 1)
    mutated_spec = tmp_path / "cryodaq.spec"
    ast.parse(mutated_source, filename=str(mutated_spec))
    mutated_spec.write_text(mutated_source, encoding="utf-8", newline="\n")
    monkeypatch.setitem(globals(), "SPEC", mutated_spec)

    with pytest.raises(FrozenDriverContractError) as caught:
        _assert_frozen_driver_contract()

    message = str(caught.value)
    assert "analysis_driver_missing=[]" in message
    assert f"analysis_driver_extra=['{unexpected}']" in message


def test_broad_collection_excludes_all_driver_namespaces_before_allowlist_addition() -> None:
    source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "collect_submodules"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "cryodaq"
    ]
    assert len(calls) == 1
    filter_keywords = [keyword for keyword in calls[0].keywords if keyword.arg == "filter"]
    assert len(filter_keywords) == 1
    assert isinstance(filter_keywords[0].value, ast.Name)
    assert filter_keywords[0].value.id == "_is_non_driver_application_module"

    assert not _driver_filter_accepts("cryodaq.drivers.instruments")
    assert not _driver_filter_accepts("cryodaq.drivers.instruments.rogue_source")
    assert not _driver_filter_accepts("cryodaq.drivers.passive_extensions")
    assert not _driver_filter_accepts("cryodaq.drivers.passive_extensions.rogue_driver")
    assert _driver_filter_accepts("cryodaq.engine")
    assert _driver_filter_accepts("cryodaq.drivers.registry")


def test_no_driver_leaf_is_duplicated_in_general_explicit_hidden_imports() -> None:
    assert _explicit_hidden_imports().isdisjoint(_frozen_driver_modules())
