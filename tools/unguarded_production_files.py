"""Revert each production file a change touches, and report which are unguarded.

THE MEASUREMENT THIS EXISTS FOR. A guard written from the same mental model as
the code inherits that code's blind spots; `AGENTS.md` already says so about
guards, and it is equally true of the claim that a change is "ready". The only
cheap way to tell whether a change is guarded AT ITS OWN PURPOSE is to undo it,
one file at a time, and see whether anything notices.

    A production file whose revert leaves the suite GREEN is unguarded.

Twice in this campaign a change shipped whose guards exercised a helper rather
than the production path: once the guard measured the writer only, and once
five migrated GUI selectors could each be reverted with every guard still
passing. Both were found in review, after the work was called done. This runs
the same measurement before that claim is made.

USAGE

    python -m tools.unguarded_production_files --base origin/master --suite tests/gui

  --base    revision to take the "before" content of each file from
  --suite   pytest target to run per revert (repeatable)
  --include limit to paths matching a prefix (repeatable; default src/)

Each file is restored from the ORIGINAL bytes read before mutation, and the
script verifies the restore byte-for-byte. It refuses to run against a dirty
tree for the files it would touch, because a revert it cannot undo is worse
than a measurement it never took.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")


def changed_files(base: str, includes: tuple[str, ...]) -> list[str]:
    out = _run(["git", "diff", "--name-only", f"{base}...HEAD"])
    out.check_returncode()
    return [
        line.strip()
        for line in out.stdout.splitlines()
        if line.strip().endswith(".py") and any(line.strip().startswith(prefix) for prefix in includes)
    ]


def base_content(base: str, path: str) -> bytes | None:
    out = _run(["git", "show", f"{base}:{path}"])
    return out.stdout.encode("utf-8") if out.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--include", action="append", default=["src/"])
    options = parser.parse_args()
    suites = options.suite or ["tests"]

    targets = changed_files(options.base, tuple(options.include))
    if not targets:
        print(f"no production files changed against {options.base}; nothing to measure")
        return 0

    dirty = _run(["git", "status", "--porcelain", "--", *targets]).stdout.strip()
    if dirty:
        print("REFUSING: these files have uncommitted changes, so a revert could not be undone safely:")
        print(dirty)
        return 2

    print(f"| reverted production file | suite result |")
    print(f"|---|---|")
    unguarded: list[str] = []
    for path in targets:
        source = Path(path)
        original = source.read_bytes()
        before = base_content(options.base, path)
        if before is None:
            print(f"| `{path}` | NEW FILE at {options.base} — nothing to revert to, not measured |")
            continue
        try:
            with io.open(source, "wb") as handle:
                handle.write(before)
            if source.read_bytes() == original:
                print(f"| `{path}` | identical to {options.base} — not measured |")
                continue
            failed: list[str] = []
            for suite in suites:
                run = _run([sys.executable, "-m", "pytest", suite, "-q", "--no-header", "-rf", "-p", "no:cacheprovider"])
                failed += [line.split("::")[-1].strip() for line in run.stdout.splitlines() if line.startswith("FAILED")]
        finally:
            with io.open(source, "wb") as handle:
                handle.write(original)
            assert source.read_bytes() == original, f"{path} was NOT restored byte-identically"
        if failed:
            print(f"| `{path}` | **{len(failed)} red** — {', '.join(sorted(set(failed))[:3])} |")
        else:
            print(f"| `{path}` | **0 red — UNGUARDED** |")
            unguarded.append(path)

    print()
    if unguarded:
        print("UNGUARDED AT THIS CHANGE'S OWN PURPOSE:")
        for path in unguarded:
            print(f"    {path}")
        return 1
    print("every reverted production file turned something red")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
