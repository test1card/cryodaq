"""Compile every repository Python source without creating bytecode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SOURCE_DIRECTORIES = ("build_scripts", "plugins", "scripts", "src", "tests", "tools")


def python_sources(root: Path) -> tuple[Path, ...]:
    """Return repository Python sources in deterministic relative-path order."""

    resolved_root = root.resolve(strict=True)
    paths = [path for path in resolved_root.glob("*.py") if path.is_file()]
    for directory_name in _SOURCE_DIRECTORIES:
        directory = resolved_root / directory_name
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*.py") if path.is_file())
    return tuple(sorted(paths, key=lambda path: path.relative_to(resolved_root).as_posix()))


def compile_python_tree(root: Path) -> tuple[str, ...]:
    """Compile all Python source text and return its relative manifest."""

    resolved_root = root.resolve(strict=True)
    manifest: list[str] = []
    for path in python_sources(resolved_root):
        relative = path.relative_to(resolved_root).as_posix()
        source = path.read_text(encoding="utf-8")
        compile(source, relative, "exec", dont_inherit=True)
        manifest.append(relative)
    if not manifest:
        raise ValueError("candidate contains no Python sources")
    return tuple(manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        manifest = compile_python_tree(args.root)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        print(f"python-compile-check failed: {exc}", file=sys.stderr)
        return 1
    print(f"python-compile-check sources={len(manifest)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
