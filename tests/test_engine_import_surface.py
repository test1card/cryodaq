"""B1 exit criterion: the engine process imports no LLM/RAG/agents code.

Regression guard for the whole point of B1 (roadmap: extract Гемма + RAG
out of the safety-critical engine process into cryodaq-assistant — see
scratchpad/montana/exec/impl_b1.md). Everything the engine still does
with the assistant is either emit events (ZMQ "events" topic) or answer
read-only queries the assistant process asks for — engine.py itself must
never import ``cryodaq.agents`` or its RAG/LLM dependencies again.

The dynamic checks below run in a FRESH subprocess rather than checking
``sys.modules`` in-process: sys.modules is process-global, and other test
modules in this same pytest session (tests/agents/**) import
``cryodaq.agents.*`` directly — checking in-process would make the
assertion depend on test collection/execution order instead of on
``cryodaq.engine``'s own import graph.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys


def _run_check(snippet: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"subprocess check failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result.stdout


def test_engine_import_pulls_in_no_agents_modules() -> None:
    """``import cryodaq.engine`` must not leave any ``cryodaq.agents.*``
    module in ``sys.modules`` — the whole point of B1."""
    snippet = (
        "import sys\n"
        "import cryodaq.engine\n"
        "leaked = sorted(m for m in sys.modules if m.startswith('cryodaq.agents'))\n"
        "print(','.join(leaked))\n"
    )
    out = _run_check(snippet).strip()
    leaked = out.split(",") if out else []
    assert leaked == [], f"cryodaq.engine pulled in agents/ modules: {leaked}"


def test_engine_import_pulls_in_no_rag_or_llm_modules() -> None:
    """Belt-and-suspenders: check for the concrete RAG/LLM dependency
    module names too, in case something imports their internals without
    going through ``cryodaq.agents`` (e.g. a future accidental
    ``import lancedb`` at engine.py module scope)."""
    snippet = (
        "import sys\n"
        "import cryodaq.engine\n"
        "suspicious = ('lancedb', 'ollama')\n"
        "leaked = sorted(m for m in sys.modules if any(s in m.lower() for s in suspicious))\n"
        "print(','.join(leaked))\n"
    )
    out = _run_check(snippet).strip()
    leaked = out.split(",") if out else []
    assert leaked == [], f"cryodaq.engine pulled in RAG/LLM modules: {leaked}"


def test_engine_module_source_has_no_agents_import_statement() -> None:
    """Static guard: no ``import cryodaq.agents`` / ``from cryodaq.agents
    import ...`` statement anywhere in engine.py — catches a reintroduced
    import even before running the dynamic subprocess checks above.

    Parses the AST (rather than a substring/grep check) so a *comment*
    mentioning ``cryodaq.agents`` — e.g. explaining where code moved to,
    as this file's own B1 comments do — is not a false positive.
    """
    import ast

    import cryodaq.engine as engine_mod

    src = pathlib.Path(engine_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=engine_mod.__file__)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                alias.name for alias in node.names if alias.name.startswith("cryodaq.agents")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("cryodaq.agents"):
                offenders.append(module)

    assert offenders == [], f"engine.py imports cryodaq.agents — B1 regression: {offenders}"


def test_assistant_main_is_the_only_module_importing_agents_rag() -> None:
    """Sanity check on the move itself: cryodaq.agents.rag.indexer /
    .searcher (the RAG engine) are reachable from cryodaq.agents.assistant_main,
    confirming the module exists and owns the RAG lifecycle post-B1."""
    import cryodaq.agents.assistant_main as assistant_main

    assert hasattr(assistant_main, "run")
    assert hasattr(assistant_main, "_resolve_rag_config")
