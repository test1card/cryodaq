from __future__ import annotations

import ast
from pathlib import Path


def test_no_existing_production_module_imports_or_activates_channel_contract() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    channel_root = source_root / "channels"
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        if path.is_relative_to(channel_root):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cryodaq.channels"):
                offenders.append(str(path.relative_to(source_root)))
            elif isinstance(node, ast.Import) and any(
                alias.name.startswith("cryodaq.channels") for alias in node.names
            ):
                offenders.append(str(path.relative_to(source_root)))
    assert offenders == []


def test_channel_contract_has_no_product_subsystem_imports() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    forbidden = ("cryodaq.core", "cryodaq.drivers", "cryodaq.engine", "cryodaq.storage")
    offenders: list[tuple[str, str]] = []
    for path in (source_root / "channels").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(forbidden):
                offenders.append((path.name, node.module or ""))
            elif isinstance(node, ast.Import):
                offenders.extend((path.name, alias.name) for alias in node.names if alias.name.startswith(forbidden))
    assert offenders == []
