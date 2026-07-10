from __future__ import annotations

import ast
from pathlib import Path

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
