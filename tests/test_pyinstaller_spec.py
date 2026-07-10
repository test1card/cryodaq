from __future__ import annotations

import ast
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "build_scripts" / "cryodaq.spec"


def test_periodic_child_hidden_imports_are_explicit() -> None:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    hidden: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "hidden_imports"
            for target in node.targets
        ):
            assert isinstance(node.value, ast.List)
            hidden.update(
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )

    assert {
        "cryodaq.reporting.__main__",
        "cryodaq.reporting.periodic_input",
        "cryodaq.reporting.periodic_renderer",
        "matplotlib",
        "matplotlib.backends.backend_agg",
    } <= hidden

