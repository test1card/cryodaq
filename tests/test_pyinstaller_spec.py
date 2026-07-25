from __future__ import annotations

import ast
from pathlib import Path

from cryodaq.drivers.registry import ALLOWLISTED_DRIVER_MODULES

SPEC = Path(__file__).resolve().parent.parent / "build_scripts" / "cryodaq.spec"


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


def test_frozen_driver_allowlist_is_exactly_the_runtime_registry() -> None:
    frozen = _frozen_driver_modules()
    assert len(frozen) == len(set(frozen))
    assert set(frozen) == set(ALLOWLISTED_DRIVER_MODULES)
    assert "cryodaq.drivers.instruments.etalon_multiline" in frozen
    assert "cryodaq.drivers.passive_extensions.asc_reference_tcp" in frozen


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
