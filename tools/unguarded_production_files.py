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

TEN WAYS THIS TOOL COULD HAVE LIED, each closed here after review found it --
and every one of them was found by review rather than by the author, which is
the same asymmetry the tool exists to exploit:

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
* **A crashed suite read as green.** Only `FAILED` lines were parsed and the
  exit code was discarded, so a native fault, an internal error, a usage error
  or an empty collection all meant "nothing failed" -- and in the CONTROL run
  that false green certified every revert measured after it.
* **Text transcoding.** `git show` was decoded with `errors="replace"` and
  re-encoded, so a base artifact holding valid non-UTF-8 bytes became a
  CORRUPTED mutant: the suite then failed on encoding damage rather than on the
  reverted behaviour, and the artifact was reported guarded. Blobs are read as
  bytes.
* **Clobbering a concurrent writer.** The up-front porcelain check cannot see an
  edit made after it ran, and the restore was unconditional, so another worker's
  bytes could be destroyed in either window. The file is re-read immediately
  before the mutation and again before the restore; a mismatch is preserved and
  reported instead of overwritten.
* **Losing the file's identity.** An added artifact that was a symlink or
  carried an executable bit was restored with `write_bytes`, producing a plain
  file with default permissions. The byte assertion still passed while the TYPE
  was gone, and a worktree that started clean did not end clean.
* **Inherited Git authority.** Every query ran with the caller's `GIT_DIR`,
  `GIT_WORK_TREE`, `GIT_INDEX_FILE`, grafts and replacement refs, so discovery
  could describe a FOREIGN repository while the writes still landed here.
  Queries are bound to this checkout with that environment stripped.

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
import stat
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


def _git_env() -> dict[str, str]:
    """Strip inherited Git authority so a query cannot describe another repo.

    `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, grafts and replacement refs
    all redirect what `git` answers while the `Path` writes below still land in
    the current directory. A discovery run against a FOREIGN index, or a revert
    taken from a foreign graph, manufactures guard coverage for this tree out of
    another one -- the same measured-through-a-layer-that-rewrites-it failure
    this tool exists to detect, applied to the tool itself.
    """

    return {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def repository_root() -> Path:
    """The one directory every relative path in this module resolves against.

    `git diff --name-only` emits names relative to the REPOSITORY ROOT, while
    `Path(name)` resolves against the current working directory. Invoked from a
    subdirectory the two disagree, and the tool would then revert a path that
    does not exist -- or, worse, one that does and is not the artifact Git named.
    """

    out = _run(["git", "rev-parse", "--show-toplevel"], env=_git_env())
    out.check_returncode()
    return Path(out.stdout.strip())


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repository_root()), "--no-replace-objects", *args], env=_git_env())


def _git_bytes(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repository_root()), "--no-replace-objects", *args], capture_output=True, env=_git_env()
    )


def merge_base(base: str) -> str:
    out = _git(["merge-base", base, "HEAD"])
    out.check_returncode()
    return out.stdout.strip()


def changed_files(point: str, includes: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
    out = _git(["diff", "--name-only", point, "HEAD"])
    out.check_returncode()
    return sorted(
        line.strip()
        for line in out.stdout.splitlines()
        if line.strip().endswith(suffixes) and any(line.strip().startswith(prefix) for prefix in includes)
    )


def base_content(point: str, path: str) -> bytes | None:
    """The base blob, or None when the path genuinely does not exist there.

    Any OTHER failure -- a missing object in a partial checkout, a corrupt
    object, a permission error -- used to return None too, and None means
    "added" further down, so the artifact was measured by DELETING it. An
    unreadable base is not an added file; it is an unmeasurable one.
    """

    out = _git_bytes(["cat-file", "-e", f"{point}:{path}"])
    if out.returncode != 0:
        return None
    blob = _git_bytes(["show", f"{point}:{path}"])
    if blob.returncode != 0:
        raise MeasurementError(
            f"{path} exists at {point[:8]} but its blob could not be read: "
            f"{blob.stderr.decode('utf-8', 'replace').strip()[:200]}"
        )
    return blob.stdout


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

    dirty = _git(["status", "--porcelain", "--", *targets]).stdout.strip()
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
    clobbered: list[str] = []
    root = repository_root()
    for path in targets:
        source = root / path
        # The FULL identity, not just the bytes. An added artifact that is a
        # symlink or carries an executable bit was being restored with
        # write_bytes, which yields a plain file with default permissions: the
        # byte assertion still passed while the file TYPE was silently lost, and
        # a worktree that started clean did not end clean.
        was_symlink = source.is_symlink()
        link_target = os.readlink(source) if was_symlink else None
        original_mode = source.lstat().st_mode if (was_symlink or source.exists()) else None
        original = None if was_symlink else (source.read_bytes() if source.exists() else None)
        before = base_content(point, path)
        cache = Path(tempfile.mkdtemp(prefix="unguarded-mutant-"))
        mutant: bytes | None = None
        removed = False
        try:
            if before is None:
                if original is None and not was_symlink:
                    unmeasured.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — absent from both sides |")
                    continue
                # Window one applies here too. An added artifact took this
                # branch without the reread and left `mutant` None, so the
                # post-run check below could not fire for it: another lane's
                # newly written file could be deleted and then recreated from
                # bytes this tool captured before that lane wrote them.
                if original is not None and source.read_bytes() != original:
                    clobbered.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — changed on disk before mutation; refusing to remove |")
                    continue
                source.unlink()  # an ADDED artifact is reverted by removing it
                removed = True  # the mutation IS the file's absence
            else:
                if original is not None and before == original:
                    print(f"| `{path}` | identical to the merge base — not measured |")
                    continue
                # WINDOW ONE. The up-front porcelain check cannot see an edit
                # made after it ran. Re-read immediately before writing, and
                # refuse rather than destroy a concurrent writer's bytes.
                if source.exists() and source.read_bytes() != original:
                    clobbered.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — changed on disk before mutation; refusing to overwrite |")
                    continue
                source.write_bytes(before)
                mutant = before
            try:
                introduced = sorted(set(failures(suites, cache)) - set(control))
            except MeasurementError as unreadable:
                unmeasured.append(path)
                print(f"| `{path}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                continue
        finally:
            shutil.rmtree(cache, ignore_errors=True)
            # WINDOW TWO. Another worker may have written while pytest ran. If
            # what is on disk is no longer the mutant we placed there, those are
            # someone else's bytes: leave them, and say so. An unconditional
            # restore here would erase work this tool never owned.
            if removed:
                concurrent = source.exists()  # someone recreated it while the suite ran
            else:
                concurrent = mutant is not None and source.exists() and source.read_bytes() != mutant
            if concurrent:
                clobbered.append(path)
                print(f"| `{path}` | **NOT MEASURED** — changed on disk during the run; left as found |")
            elif was_symlink:
                source.unlink(missing_ok=True)
                os.symlink(link_target, source)
                assert source.is_symlink() and os.readlink(source) == link_target, f"{path} lost its symlink identity"
            elif original is None:
                source.unlink(missing_ok=True)
            else:
                source.write_bytes(original)
                assert source.read_bytes() == original, f"{path} was NOT restored byte-identically"
                if original_mode is not None:
                    os.chmod(source, stat.S_IMODE(original_mode))
        if concurrent:
            continue
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
    if clobbered:
        print("ANOTHER WRITER TOUCHED THESE DURING THE RUN, so they were left as found and NOT measured.")
        print("Their current contents are that writer's, not this tool's -- check them before trusting the tree:")
        for path in clobbered:
            print(f"    {path}")
    if unguarded:
        print("UNGUARDED AT THIS CHANGE'S OWN PURPOSE:")
        for path in unguarded:
            print(f"    {path}")
    if unguarded or unmeasured or clobbered:
        return 1
    print("every reverted production artifact introduced a new failure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
