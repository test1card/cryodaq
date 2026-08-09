"""Class-wide controls for PyYAML parser-table ownership."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_SAFETY_CONFIG = REPO_ROOT / "config" / "safety.yaml"
_YAML_TABLES = (
    "yaml_constructors",
    "yaml_multi_constructors",
    "yaml_implicit_resolvers",
    "yaml_path_resolvers",
    "bool_values",
)
_SHARED_DEFAULT_HELPERS = frozenset(
    {
        "full_load",
        "full_load_all",
        "safe_load",
        "safe_load_all",
        "unsafe_load",
        "unsafe_load_all",
    }
)
_LOADER_CALLS = frozenset({"compose", "compose_all", "load", "load_all", "parse", "scan"})
_YAML_MODULES = frozenset({"yaml", "yaml.cyaml", "yaml.loader"})
_SHARED_LOADER_CLASSES = frozenset(
    {
        "BaseLoader",
        "CBaseLoader",
        "CFullLoader",
        "CLoader",
        "CSafeLoader",
        "CUnsafeLoader",
        "FullLoader",
        "Loader",
        "SafeLoader",
        "UnsafeLoader",
    }
)


@pytest.fixture
def modified_shared_yaml_tables() -> Iterator[type]:
    """Register ordinary host customisations, then restore every shared table."""

    from cryodaq.core.safety_manager import SafetyManager

    originally_owned = {name: name in yaml.SafeLoader.__dict__ for name in _YAML_TABLES}
    originals = {name: getattr(yaml.SafeLoader, name) for name in _YAML_TABLES}
    snapshots = {
        name: ({key: list(value) for key, value in table.items()} if name == "yaml_implicit_resolvers" else dict(table))
        for name, table in originals.items()
    }
    try:
        yaml.SafeLoader.add_path_resolver("!host-channel", ["critical_channels", None], str)
        yaml.SafeLoader.add_constructor(
            "!host-channel",
            lambda loader, node: "LIBRARY_SUBSTITUTED_CHANNEL",
        )
        assert yaml.safe_load("critical_channels:\n  - Т11\n") == {"critical_channels": ["LIBRARY_SUBSTITUTED_CHANNEL"]}
        yield SafetyManager
    finally:
        for name, original in originals.items():
            if originally_owned[name]:
                current_snapshot = (
                    {key: list(value) for key, value in original.items()}
                    if name == "yaml_implicit_resolvers"
                    else dict(original)
                )
                if current_snapshot != snapshots[name]:
                    original.clear()
                    original.update(snapshots[name])
                setattr(yaml.SafeLoader, name, original)
            elif name in yaml.SafeLoader.__dict__:
                delattr(yaml.SafeLoader, name)
        assert {name: name in yaml.SafeLoader.__dict__ for name in _YAML_TABLES} == originally_owned
        assert all(getattr(yaml.SafeLoader, name) is original for name, original in originals.items())


def test_public_path_resolver_cannot_replace_shipped_safety_channel_identities(
    modified_shared_yaml_tables: type,
) -> None:
    """A host library must not silently rewrite authoritative channel identities."""

    from cryodaq.core.safety_broker import SafetyBroker

    manager = modified_shared_yaml_tables(SafetyBroker())
    manager.load_config(SHIPPED_SAFETY_CONFIG)

    assert tuple(pattern.pattern for pattern in manager._config.critical_channels) == ("Т11", "Т12")


@dataclass(frozen=True, order=True)
class _SharedDefaultSite:
    path: str
    line: int
    expression: str


def _qualified_root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_yaml_attribute(node: ast.AST, yaml_aliases: set[str], names: frozenset[str]) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in names and _qualified_root_name(node) in yaml_aliases


def _is_shared_loader_reference(
    node: ast.AST,
    yaml_aliases: set[str],
    loader_aliases: set[str],
) -> bool:
    return _is_yaml_attribute(node, yaml_aliases, _SHARED_LOADER_CLASSES) or (
        isinstance(node, ast.Name) and node.id in loader_aliases
    )


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return set().union(*(_target_names(element) for element in node.elts))
    return set()


def _owned_loader_aliases(tree: ast.Module) -> set[str]:
    names = {
        imported.asname or imported.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "cryodaq._owned_yaml"
        for imported in node.names
        if imported.name == "OwnedSafeLoader"
    }
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            discovered: set[str] = set()
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id in names for base in node.bases
            ):
                discovered.add(node.name)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in names:
                discovered.update(set().union(*(_target_names(target) for target in node.targets)))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Name) and node.value.id in names:
                discovered.update(_target_names(node.target))
            if not discovered <= names:
                names.update(discovered)
                changed = True
    return names


def _parser_violation(
    node: ast.Call,
    expression: str,
    owned_loader_aliases: set[str],
) -> str | None:
    loader_arguments = [keyword.value for keyword in node.keywords if keyword.arg == "Loader"]
    loader_arguments.extend(node.args[1:2])
    if loader_arguments and all(
        isinstance(argument, ast.Name) and argument.id in owned_loader_aliases for argument in loader_arguments
    ):
        return None
    return f"{expression} without the package-owned Loader"


def _shared_default_sites(root: Path) -> list[_SharedDefaultSite]:
    source_root = root / "src"
    if not source_root.is_dir():
        raise RuntimeError(f"YAML sweep root is missing: {source_root}")
    paths = sorted({*source_root.rglob("*.py"), *source_root.rglob("*.pyw")})
    if not paths:
        raise RuntimeError(f"YAML sweep root contains no Python files: {source_root}")

    sites: list[_SharedDefaultSite] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        yaml_aliases = {
            imported.asname or imported.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for imported in node.names
            if imported.name in _YAML_MODULES
        }
        yaml_imports = [
            node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module in _YAML_MODULES
        ]
        helper_aliases = {
            imported.asname or imported.name: imported.name
            for node in yaml_imports
            for imported in node.names
            if imported.name in _SHARED_DEFAULT_HELPERS
        }
        parser_aliases = {
            imported.asname or imported.name: imported.name
            for node in yaml_imports
            for imported in node.names
            if imported.name in _LOADER_CALLS
        }
        loader_aliases = {
            imported.asname or imported.name
            for node in yaml_imports
            for imported in node.names
            if imported.name in _SHARED_LOADER_CLASSES
        }
        owned_loader_aliases = _owned_loader_aliases(tree)
        sites.extend(
            _SharedDefaultSite(relative, node.lineno, f"from {node.module} import *")
            for node in yaml_imports
            if any(imported.name == "*" for imported in node.names)
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            expression: str | None = None
            rendered = ast.unparse(node.func)
            if _is_shared_loader_reference(node.func, yaml_aliases, loader_aliases):
                expression = f"{rendered} constructs a shared Loader"
            elif isinstance(node.func, ast.Name) and node.func.id in helper_aliases:
                expression = rendered
            elif isinstance(node.func, ast.Name) and node.func.id in parser_aliases:
                expression = _parser_violation(node, rendered, owned_loader_aliases)
            elif _is_yaml_attribute(node.func, yaml_aliases, _SHARED_DEFAULT_HELPERS):
                expression = rendered
            elif _is_yaml_attribute(node.func, yaml_aliases, _LOADER_CALLS):
                expression = _parser_violation(node, rendered, owned_loader_aliases)
            if expression is not None:
                sites.append(_SharedDefaultSite(relative, node.lineno, expression))
    return sorted(sites)


def _assert_no_shared_default_sites(root: Path) -> None:
    sites = _shared_default_sites(root)
    assert not sites, "shared-default PyYAML call sites:\n" + "\n".join(
        f"{site.path}:{site.line}: {site.expression}" for site in sites
    )


def test_production_has_no_shared_default_yaml_call_sites() -> None:
    """A new production YAML load must use CryoDAQ's owned loader."""

    _assert_no_shared_default_sites(REPO_ROOT)


@pytest.mark.parametrize(
    ("source", "line", "expression"),
    (
        ('import yaml\n\nyaml.safe_load("guard: enabled")\n', 3, "yaml.safe_load"),
        (
            'import yaml\n\nyaml.compose("guard: enabled")\n',
            3,
            "yaml.compose without the package-owned Loader",
        ),
        (
            'from yaml import compose as decode\n\ndecode("guard: enabled")\n',
            3,
            "decode without the package-owned Loader",
        ),
        (
            'import yaml\n\nShared = yaml.SafeLoader\nyaml.load("guard: enabled", Loader=Shared)\n',
            4,
            "yaml.load without the package-owned Loader",
        ),
        (
            'from yaml.loader import SafeLoader as Shared\n\nShared("guard: enabled")\n',
            3,
            "Shared constructs a shared Loader",
        ),
    ),
)
def test_yaml_sweep_rejects_new_shared_default_call_sites(
    tmp_path: Path,
    source: str,
    line: int,
    expression: str,
) -> None:
    """The class guard itself must fail on representative new shared loaders."""

    source_root = tmp_path / "src" / "example"
    source_root.mkdir(parents=True)
    probe = source_root / "new_config.py"
    probe.write_text(source, encoding="utf-8")

    with pytest.raises(
        AssertionError,
        match=rf"new_config\.py:{line}: {re.escape(expression)}",
    ):
        _assert_no_shared_default_sites(tmp_path)


def test_yaml_sweep_accepts_owned_loader_aliases_and_subclasses(tmp_path: Path) -> None:
    """Existing strict loaders may derive from the one package-owned class."""

    source_root = tmp_path / "src" / "example"
    source_root.mkdir(parents=True)
    (source_root / "owned_config.py").write_text(
        "from cryodaq._owned_yaml import OwnedSafeLoader\n"
        "from yaml import compose as decode\n\n"
        "Alias = OwnedSafeLoader\n\n"
        "class StrictLoader(Alias):\n"
        "    pass\n\n"
        'decode("guard: enabled", Loader=StrictLoader)\n',
        encoding="utf-8",
    )

    assert _shared_default_sites(tmp_path) == []
