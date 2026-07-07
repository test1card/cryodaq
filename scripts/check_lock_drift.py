#!/usr/bin/env python3
"""Fail if any pyproject dependency lacks a pin in requirements-lock.txt.

build_scripts/build.sh installs the frozen bundle's transitive deps from
requirements-lock.txt and then `pip install -e . --no-deps`. So any top-level
dependency missing from the lock is simply absent from the frozen build
(e.g. lancedb -> RAG ImportError, tzdata -> Windows parquet
ZoneInfoNotFoundError). This gate catches that drift in CI before a build ships.

Resolves the same dependency set the lock is compiled from
(`pip-compile --extra=dev --extra=web`): base deps + the dev and web extras.
stdlib-only (tomllib + regex text parse) — no packaging-library dependency.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Extras the lock is compiled against (see requirements-lock.txt header).
LOCK_EXTRAS = ("dev", "web")

# PEP 508 name: leading token before any extras/version specifier.
_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
# Lock pin line: `name==x.y.z` or `name[extra]==x.y.z`.
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==")


def _canon(name: str) -> str:
    """PEP 503 normalized name (lowercase, runs of -_. -> single -)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pyproject_dep_names(pyproject: Path, extras: tuple[str, ...] = LOCK_EXTRAS) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data["project"]
    specs = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in extras:
        specs.extend(optional.get(extra, []))
    names = set()
    for spec in specs:
        m = _NAME_RE.match(spec.strip())
        if m:
            names.add(_canon(m.group(1)))
    return names


def locked_names(lock: Path) -> set[str]:
    names = set()
    for line in lock.read_text(encoding="utf-8").splitlines():
        m = _PIN_RE.match(line.strip())
        if m:
            names.add(_canon(m.group(1)))
    return names


def find_drift(pyproject: Path, lock: Path, extras: tuple[str, ...] = LOCK_EXTRAS) -> list[str]:
    """Top-level deps declared in pyproject but not pinned in the lock."""
    return sorted(pyproject_dep_names(pyproject, extras) - locked_names(lock))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=REPO_ROOT / "pyproject.toml")
    parser.add_argument("--lock", type=Path, default=REPO_ROOT / "requirements-lock.txt")
    args = parser.parse_args(argv)

    missing = find_drift(args.pyproject, args.lock)
    if missing:
        print("requirements-lock.txt is stale — missing pins for top-level deps:")
        for name in missing:
            print(f"  - {name}")
        print(f"\nRegenerate: pip-compile --extra=dev --extra=web "
              f"--output-file={args.lock.name} {args.pyproject.name}")
        return 1
    print(f"requirements-lock.txt is in sync ({len(pyproject_dep_names(args.pyproject))} top-level deps pinned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
