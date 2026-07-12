from __future__ import annotations

import ast
from pathlib import Path


def test_health_contract_and_simulator_do_not_import_authority_or_ui_subsystems() -> None:
    root = Path(__file__).parents[2]
    prohibited = {
        "cryodaq.core",
        "cryodaq.drivers",
        "cryodaq.engine",
        "cryodaq.engine_wiring",
        "cryodaq.gui",
        "cryodaq.safety",
        "cryodaq.storage",
    }

    for relative in ("src/cryodaq/health/contract.py", "src/cryodaq/health/simulator.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not {
            imported
            for imported in imports
            for boundary in prohibited
            if imported == boundary or imported.startswith(f"{boundary}.")
        }
