"""Inventory bare PyYAML loader calls for OC-040 source groups.

The scanner resolves aliases instead of matching the literal spelling ``yaml``.
That is required for function-local imports such as ``import yaml as _yaml``.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_LOAD_FUNCTIONS = frozenset({"safe_load", "full_load", "load"})
_DEFAULT_GROUP_B = (Path("src/cryodaq/gui"), Path("src/cryodaq/agents"))


@dataclass(frozen=True, order=True)
class BareYamlCall:
    """One loader call that does not name an owned Loader class."""

    path: str
    line: int
    function: str

    def location(self) -> str:
        return f"{self.path}:{self.line}"


def _import_aliases(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    module_aliases: set[str] = set()
    function_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "yaml":
                    module_aliases.add(imported.asname or "yaml")
        elif isinstance(node, ast.ImportFrom) and node.module == "yaml":
            for imported in node.names:
                if imported.name in _LOAD_FUNCTIONS:
                    function_aliases[imported.asname or imported.name] = imported.name

    # Resolve simple aliases such as ``load_yaml = _yaml.safe_load``. Repeat so
    # aliases of aliases are covered without depending on source spelling.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            resolved: str | None = None
            if (
                isinstance(value, ast.Attribute)
                and value.attr in _LOAD_FUNCTIONS
                and isinstance(value.value, ast.Name)
                and value.value.id in module_aliases
            ):
                resolved = value.attr
            elif isinstance(value, ast.Name):
                resolved = function_aliases.get(value.id)
            if resolved is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and function_aliases.get(target.id) != resolved:
                    function_aliases[target.id] = resolved
                    changed = True
    return module_aliases, function_aliases


def _called_loader(
    node: ast.Call,
    module_aliases: set[str],
    function_aliases: dict[str, str],
) -> str | None:
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module_aliases
        and node.func.attr in _LOAD_FUNCTIONS
    ):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return function_aliases.get(node.func.id)
    return None


def _is_bare(node: ast.Call, function: str) -> bool:
    if function != "load":
        return True
    has_loader_keyword = any(keyword.arg in {"Loader", "loader"} for keyword in node.keywords)
    has_loader_positional = len(node.args) >= 2
    return not has_loader_keyword and not has_loader_positional


def find_bare_yaml_calls_in_source(source: str, path: str = "<source>") -> list[BareYamlCall]:
    """Return alias-resolved bare calls from one Python source string."""

    tree = ast.parse(source, filename=path)
    module_aliases, function_aliases = _import_aliases(tree)
    findings: list[BareYamlCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = _called_loader(node, module_aliases, function_aliases)
        if function is not None and _is_bare(node, function):
            findings.append(BareYamlCall(path=path, line=node.lineno, function=function))
    return sorted(findings)


def _python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def find_bare_yaml_calls(paths: Iterable[Path], repo_root: Path) -> list[BareYamlCall]:
    """Return bare calls below ``paths``, with locations relative to the repo."""

    findings: list[BareYamlCall] = []
    for path in _python_files(paths):
        relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
        source = path.read_text(encoding="utf-8")
        findings.extend(find_bare_yaml_calls_in_source(source, relative))
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=list(_DEFAULT_GROUP_B))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    paths = [path if path.is_absolute() else args.repo_root / path for path in args.paths]
    findings = find_bare_yaml_calls(paths, args.repo_root)
    for finding in findings:
        print(f"{finding.location()} {finding.function}")
    print(f"GROUP_B_BARE_YAML_CALLS={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
