"""Revert each production artifact a change touches, and report which are unguarded.

THE MEASUREMENT THIS EXISTS FOR. A guard written from the same mental model as
the code inherits that code's blind spots; `AGENTS.md` says so about guards, and
it is equally true of the claim that a change is "ready". The only cheap way to
tell whether a change is guarded AT ITS OWN PURPOSE is to undo it, one artifact
at a time, and see whether anything notices.

    A production artifact whose revert introduces NO NEW failure is unguarded.

Twice in this campaign a change shipped whose guards exercised a helper rather
than the production path: once the guard measured the writer only, and once
five migrated GUI selectors could each be reverted with every guard still
passing. Both were found in review, after the work was called done.

FIVE WAYS THIS TOOL COULD HAVE LIED, each closed here after review found it:

* **A dirty control.** If the suite already fails, every reverted artifact
  collects that same failure and is reported guarded. The suite is therefore
  run FIRST, unmutated, and only failures NEW relative to that control count.
  A control that is not green fails the run closed rather than manufacturing
  coverage.
* **Configuration invisible.** Requiring a `.py` suffix meant `--include
  config/` selected nothing, so interlock thresholds, channel patterns and
  shutdown actions -- production by the severity floor's own definition --
  could never be measured. Suffixes are declared, not assumed.
* **Added files skipped.** A new module has no base content to revert to, so
  it was skipped while the run still exited 0. An added artifact is now
  measured by REMOVING it, and a target that cannot be measured fails the run.
* **Stale bytecode.** A revert and a restore of equal length inside one
  filesystem-timestamp second can leave a `.pyc` compiled from the reverted
  bytes, which a later process then executes while the source shows the
  candidate. Each mutation run gets a fresh `PYTHONPYCACHEPREFIX`, discarded
  afterwards.
* **Two different bases.** Discovery used the three-dot merge base while
  content came from the base BRANCH TIP, so an unrelated upstream edit could
  fail the suite and falsely certify this change's artifact. The merge base is
  resolved once and used for both.

USAGE

    python -m tools.unguarded_production_files --base origin/master \\
        --suite tests/gui --include src/ --include config/

Each artifact is restored from the ORIGINAL bytes read before mutation, and the
restore is verified byte-for-byte. It refuses to run against a dirty tree for
the artifacts it would touch, because a revert it cannot undo is worse than a
measurement it never took.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Production artifacts are not only Python: the severity floor counts tracked
# runtime configuration -- interlock thresholds, channel patterns, shutdown
# actions -- as production, because a wrong value there misfires an interlock
# exactly as wrong code does.
_DEFAULT_SUFFIXES = (".py", ".pyw", ".yaml", ".yml", ".json", ".toml")


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def merge_base(base: str) -> str:
    out = _run(["git", "merge-base", base, "HEAD"])
    out.check_returncode()
    return out.stdout.strip()


def changed_files(point: str, includes: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
    out = _run(["git", "diff", "--name-only", point, "HEAD"])
    out.check_returncode()
    return sorted(
        line.strip()
        for line in out.stdout.splitlines()
        if line.strip().endswith(suffixes) and any(line.strip().startswith(prefix) for prefix in includes)
    )


def base_content(point: str, path: str) -> bytes | None:
    out = _run(["git", "show", f"{point}:{path}"])
    return out.stdout.encode("utf-8") if out.returncode == 0 else None


class MeasurementError(RuntimeError):
    """A suite run whose result cannot be read as evidence either way."""


def failures(suites: list[str], cache_prefix: Path) -> list[str]:
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(cache_prefix), PYTHONDONTWRITEBYTECODE="")
    found: list[str] = []
    for suite in suites:
        run = _run(
            [sys.executable, "-m", "pytest", suite, "-q", "--no-header", "-rf", "-p", "no:cacheprovider"], env=env
        )
        parsed = [line.split("::")[-1].strip() for line in run.stdout.splitlines() if line.startswith("FAILED")]
        # A CRASHED suite prints no `FAILED` lines, so parsing stdout alone
        # reads a native fault, an internal error, a usage error or an empty
        # collection as "nothing failed" -- and in the CONTROL run that is a
        # false green which certifies every revert that follows it. pytest
        # exits 0 for all-passed and 1 for tests-failed; everything else (2
        # interrupted, 3 internal, 4 usage, 5 nothing collected) means the
        # measurement did not happen. An exit of 1 with no parsable FAILED
        # line is the same situation wearing the expected exit code.
        if run.returncode not in (0, 1) or (run.returncode == 1 and not parsed):
            tail = "\n".join((run.stdout + run.stderr).splitlines()[-15:])
            raise MeasurementError(f"pytest over {suite!r} exited {run.returncode} with no readable result:\n{tail}")
        found += parsed
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--suffix", action="append", default=[])
    options = parser.parse_args()
    suites = options.suite or ["tests"]
    includes = tuple(options.include or ["src/", "config/"])
    suffixes = tuple(options.suffix or _DEFAULT_SUFFIXES)

    point = merge_base(options.base)
    targets = changed_files(point, includes, suffixes)
    if not targets:
        print(f"no production artifacts changed against {point[:8]}; nothing to measure")
        return 0

    dirty = _run(["git", "status", "--porcelain", "--", *targets]).stdout.strip()
    if dirty:
        print("REFUSING: these artifacts have uncommitted changes, so a revert could not be undone safely:")
        print(dirty)
        return 2

    # THE CONTROL. Without it, a suite that already fails hands the same failure
    # to every reverted artifact and every one is reported guarded.
    control_cache = Path(tempfile.mkdtemp(prefix="unguarded-control-"))
    try:
        control = failures(suites, control_cache)
    except MeasurementError as unreadable:
        print(f"REFUSING: the control run produced no readable result, so nothing can be attributed:\n{unreadable}")
        return 2
    finally:
        shutil.rmtree(control_cache, ignore_errors=True)
    if control:
        print(f"REFUSING: the control run is not green ({len(control)} failing), so no revert can be attributed:")
        for name in sorted(set(control))[:10]:
            print(f"    {name}")
        return 2
    print(f"control: green over {', '.join(suites)}")
    print()
    print("| reverted production artifact | new failures introduced by the revert |")
    print("|---|---|")

    unguarded: list[str] = []
    unmeasured: list[str] = []
    for path in targets:
        source = Path(path)
        original = source.read_bytes() if source.exists() else None
        before = base_content(point, path)
        cache = Path(tempfile.mkdtemp(prefix="unguarded-mutant-"))
        try:
            if before is None:
                if original is None:
                    unmeasured.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — absent from both sides |")
                    continue
                source.unlink()  # an ADDED artifact is reverted by removing it
            else:
                if original is not None and before == original:
                    print(f"| `{path}` | identical to the merge base — not measured |")
                    continue
                source.write_bytes(before)
            try:
                introduced = sorted(set(failures(suites, cache)) - set(control))
            except MeasurementError as unreadable:
                unmeasured.append(path)
                print(f"| `{path}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                continue
        finally:
            shutil.rmtree(cache, ignore_errors=True)
            if original is None:
                source.unlink(missing_ok=True)
            else:
                source.write_bytes(original)
                assert source.read_bytes() == original, f"{path} was NOT restored byte-identically"
        if introduced:
            print(f"| `{path}` | **{len(introduced)} new** — {', '.join(introduced[:3])} |")
        else:
            print(f"| `{path}` | **0 new — UNGUARDED** |")
            unguarded.append(path)

    print()
    if unmeasured:
        print("COULD NOT BE MEASURED (this is a failure, not a pass):")
        for path in unmeasured:
            print(f"    {path}")
    if unguarded:
        print("UNGUARDED AT THIS CHANGE'S OWN PURPOSE:")
        for path in unguarded:
            print(f"    {path}")
    if unguarded or unmeasured:
        return 1
    print("every reverted production artifact introduced a new failure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
