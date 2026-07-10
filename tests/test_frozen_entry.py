"""Test frozen entry point structure.

These tests verify the Phase 1 CRITICAL fix for ``multiprocessing.freeze_support``
ordering without actually building a PyInstaller bundle. They are pure AST
inspections and run in any environment.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_MAIN = REPO_ROOT / "src" / "cryodaq" / "_frozen_main.py"
LAUNCHER = REPO_ROOT / "src" / "cryodaq" / "launcher.py"
GUI_APP = REPO_ROOT / "src" / "cryodaq" / "gui" / "app.py"


def test_frozen_main_exists():
    assert FROZEN_MAIN.exists(), "src/cryodaq/_frozen_main.py must exist"


def test_freeze_support_called_before_heavy_imports():
    """``freeze_support()`` MUST be called before any cryodaq.*/PySide6 import.

    Inspects every ``main_*`` function in ``_frozen_main.py`` and verifies the
    source line of ``freeze_support()`` is strictly less than every nested
    cryodaq/PySide6 import, including imports inside ``_dispatch`` branches.
    """
    tree = ast.parse(FROZEN_MAIN.read_text(encoding="utf-8"))

    # Include _dispatch: it is the actual __main__ entry point and must also
    # call freeze_support() before any heavy imports.
    main_funcs = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and (n.name.startswith("main_") or n.name == "_dispatch")
    ]
    assert main_funcs, "_frozen_main.py must define main_* functions or _dispatch"

    for func in main_funcs:
        freeze_calls = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "freeze_support"
        ]

        def heavy_names(node: ast.AST) -> list[str]:
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            return names

        heavy_imports = [
            node
            for node in ast.walk(func)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(name.startswith("cryodaq") or name.startswith("PySide6") for name in heavy_names(node))
        ]
        assert freeze_calls, f"{func.name}: missing freeze_support() call"
        freeze_line = min(node.lineno for node in freeze_calls)
        for heavy in heavy_imports:
            assert freeze_line < heavy.lineno, (
                f"{func.name}: freeze_support() at line {freeze_line} must be "
                f"BEFORE heavy import at line {heavy.lineno}"
            )


def _no_active_freeze_support_calls(path: Path) -> None:
    """Assert that ``freeze_support`` only appears in comments in *path*."""
    src = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if "freeze_support" not in line:
            continue
        # Allow comment lines.
        if stripped.startswith("#"):
            continue
        # Allow comment-prefixed NOTE lines that include a literal mention.
        if "NOTE:" in line and "freeze_support" in line and line.lstrip().startswith("#"):
            continue
        pytest.fail(f"{path.name}:{line_no} still references freeze_support() in non-comment code: {line!r}")


def test_launcher_main_does_not_call_freeze_support():
    """``launcher.main()`` must NOT call ``freeze_support`` — it's too late."""
    _no_active_freeze_support_calls(LAUNCHER)


def test_gui_app_main_does_not_call_freeze_support():
    """Same constraint for ``gui/app.py``."""
    _no_active_freeze_support_calls(GUI_APP)


def test_frozen_main_imports_in_function_body_only():
    """All cryodaq/PySide6 imports in _frozen_main MUST be inside function bodies,
    NOT at module top level — otherwise they'd run before freeze_support()."""
    tree = ast.parse(FROZEN_MAIN.read_text(encoding="utf-8"))

    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            names: list[str] = []
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                names.append(stmt.module)
            if isinstance(stmt, ast.Import):
                names.extend(a.name for a in stmt.names)
            for name in names:
                assert not name.startswith("cryodaq"), (
                    f"_frozen_main.py: top-level import of {name!r} would defeat freeze_support() ordering"
                )
                assert not name.startswith("PySide6"), (
                    f"_frozen_main.py: top-level import of {name!r} would defeat freeze_support() ordering"
                )


def test_frozen_dispatch_supports_report_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq._frozen_main as module

    called: list[bool] = []
    fake = types.ModuleType("cryodaq.reporting.__main__")
    fake.main = lambda: called.append(True) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cryodaq.reporting.__main__", fake)
    monkeypatch.setattr(sys, "argv", ["CryoDAQ.exe", "--mode=report-render"])
    with pytest.raises(SystemExit) as exc:
        module._dispatch()
    assert exc.value.code == 0
    assert called == [True]


def test_frozen_dispatch_forwards_periodic_argv_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq._frozen_main as module

    seen: list[list[str]] = []
    fake = types.ModuleType("cryodaq.reporting.__main__")
    fake.main = lambda: seen.append(list(sys.argv)) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cryodaq.reporting.__main__", fake)
    argv = [
        "CryoDAQ.exe",
        "--mode=report-render",
        "periodic",
        f"--generation-id={'a' * 32}",
        "--deadline-epoch=123.000000",
        "--max-input-bytes=65536",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        module._dispatch()

    assert exc.value.code == 0
    assert seen == [[argv[0], *argv[2:]]]


def test_frozen_dispatch_uses_lightweight_assistant_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq._frozen_main as module

    called: list[bool] = []
    fake = types.ModuleType("cryodaq.agents.assistant_bootstrap")
    fake.main = lambda: called.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cryodaq.agents.assistant_bootstrap", fake)
    monkeypatch.setattr(sys, "argv", ["CryoDAQ.exe", "--mode=assistant"])

    module._dispatch()

    assert called == [True]


def test_exact_on_h3_import_closure_keeps_renderer_and_control_stacks_out() -> None:
    code = (
        "import sys; "
        "import cryodaq.agents.assistant_bootstrap as bootstrap; "
        "bootstrap._load_periodic_runtime(); "
        "from cryodaq.agents.assistant.periodic_telegram import _load_aiohttp; "
        "_load_aiohttp(); "
        "required = ('cryodaq.agents.assistant.periodic_png', "
        "'cryodaq.agents.assistant.periodic_runtime', "
        "'cryodaq.agents.assistant.periodic_telegram', 'zmq', 'msgpack', 'aiohttp'); "
        "blocked = ('matplotlib', 'matplotlib.pyplot', 'docx', "
        "'cryodaq.reporting.generator', 'cryodaq.reporting.periodic_renderer', "
        "'PySide6', 'cryodaq.engine'); "
        "assert all(name in sys.modules for name in required), "
        "[name for name in required if name not in sys.modules]; "
        "assert not [name for name in blocked if name in sys.modules], "
        "[name for name in blocked if name in sys.modules]"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_frozen_report_commands_reinvoke_exe_without_python_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\CryoDAQ build\CryoDAQ.exe")
    experiment = module.build_report_command(
        "exp-1",
        "a" * 32,
        deadline_epoch=123.0,
    )
    periodic = module.build_periodic_report_command(
        "b" * 32,
        deadline_epoch=123.0,
        max_input_bytes=65_536,
    )
    for command in (experiment, periodic):
        assert command[:2] == [sys.executable, "--mode=report-render"]
        assert "-m" not in command
        assert "python" not in " ".join(command).lower()

    monkeypatch.delattr(sys, "frozen")
    development = module.build_periodic_report_command(
        "c" * 32,
        deadline_epoch=123.0,
        max_input_bytes=65_536,
    )
    assert development[:3] == [sys.executable, "-m", "cryodaq.reporting"]


def test_frozen_replay_llm_path_keeps_h3_exact_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq._frozen_main as frozen
    import cryodaq.agents.assistant_bootstrap as bootstrap

    (tmp_path / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "0")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "0")
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(bootstrap.signal, "signal", lambda _signum, _handler: object())
    llm_started: list[bool] = []
    h2_stopped: list[bool] = []

    class H2:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            h2_stopped.append(True)

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        llm_started.append(True)
        shutdown_event.set()

    monkeypatch.setattr(bootstrap, "ReportCoordinator", H2)
    monkeypatch.setattr(bootstrap, "_load_llm_runtime", lambda: llm)
    monkeypatch.setattr(
        bootstrap,
        "_load_periodic_runtime",
        lambda: pytest.fail("frozen replay exact-off constructed H3"),
    )
    fake = types.ModuleType("cryodaq.agents.assistant_bootstrap")
    fake.main = lambda: asyncio.run(  # type: ignore[attr-defined]
        bootstrap.run(config_dir=tmp_path, data_dir=tmp_path)
    )
    monkeypatch.setitem(sys.modules, "cryodaq.agents.assistant_bootstrap", fake)
    monkeypatch.setattr(sys, "argv", ["CryoDAQ.exe", "--mode=assistant"])

    frozen._dispatch()

    assert llm_started == [True]
    assert h2_stopped == [True]


def test_frozen_periodic_only_dispatch_reaches_h3_without_h2_or_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq._frozen_main as frozen
    import cryodaq.agents.assistant_bootstrap as bootstrap

    monkeypatch.setenv("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "0")
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "1")
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(bootstrap.signal, "signal", lambda _signum, _handler: object())
    h3_started: list[bool] = []
    h3_stopped: list[bool] = []

    class H2:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class H3:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self) -> None:
            h3_started.append(True)

        async def stop(self) -> None:
            h3_stopped.append(True)

    monkeypatch.setattr(bootstrap, "ReportCoordinator", H2)
    monkeypatch.setattr(
        bootstrap,
        "_load_periodic_runtime",
        lambda: (H3, lambda **_kwargs: object()),
    )
    monkeypatch.setattr(
        bootstrap,
        "_load_llm_runtime",
        lambda: pytest.fail("periodic-only frozen path loaded LLM"),
    )
    fake = types.ModuleType("cryodaq.agents.assistant_bootstrap")
    fake.main = lambda: asyncio.run(  # type: ignore[attr-defined]
        bootstrap.run(config_dir=tmp_path, data_dir=tmp_path)
    )
    monkeypatch.setitem(sys.modules, "cryodaq.agents.assistant_bootstrap", fake)
    monkeypatch.setattr(sys, "argv", ["CryoDAQ.exe", "--mode=assistant"])

    with pytest.raises(RuntimeError, match="periodic PNG supervisor stopped unexpectedly"):
        frozen._dispatch()

    assert h3_started == [True]
    assert h3_stopped == [True]
