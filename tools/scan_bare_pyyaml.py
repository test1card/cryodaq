"""List bare PyYAML loader calls in OC-040 group A."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

LOADER_NAMES = {"safe_load", "full_load", "load"}


class BareLoaderVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.yaml_modules: set[str] = set()
        self.yaml_loaders: dict[str, str] = {}
        self.findings: list[tuple[Path, int]] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for item in node.names:
            if item.name == "yaml":
                self.yaml_modules.add(item.asname or "yaml")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module == "yaml":
            for item in node.names:
                if item.name in LOADER_NAMES:
                    self.yaml_loaders[item.asname or item.name] = item.name

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        loader_name: str | None = None
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id in self.yaml_modules and node.func.attr in LOADER_NAMES:
                loader_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            loader_name = self.yaml_loaders.get(node.func.id)

        has_explicit_loader = len(node.args) > 1 or any(keyword.arg == "Loader" for keyword in node.keywords)
        if loader_name and (loader_name != "load" or not has_explicit_loader):
            self.findings.append((self.path, node.lineno))
        self.generic_visit(node)


def scan(root: Path) -> list[tuple[Path, int]]:
    findings: list[tuple[Path, int]] = []
    for path in sorted(root.rglob("*.py")):
        if "gui" in path.relative_to(root).parts or "agents" in path.relative_to(root).parts:
            continue
        visitor = BareLoaderVisitor(path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        findings.extend(visitor.findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("src/cryodaq"))
    args = parser.parse_args()
    findings = scan(args.root)
    for path, line in findings:
        print(f"{path.as_posix()}:{line}")
    print(f"group A bare PyYAML loader calls: {len(findings)}")
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
