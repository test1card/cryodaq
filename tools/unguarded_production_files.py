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

FOURTEEN WAYS THIS TOOL COULD HAVE LIED, each closed here after review found it --
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
* **A custom filter erased runtime artifacts.** `--include src/` replaced rather
  than extended the default roster, silently dropping `tsp/` and `plugins/`;
  `--suffix .py` could similarly drop the watchdog's `.lua`. Both are additive.
* **A hanging mutant stranded the worktree.** Every pytest child now has a
  120-second timeout, and restore intent is persisted before the rewrite so the
  next invocation can recover after its parent is killed.
* **A killed restore could truncate the candidate.** Candidate bytes are
  restored through an atomic same-volume replacement.
* **One flaky red counted as coverage.** A mutant failure must repeat exactly,
  then the same node must disappear on the restored candidate in this invocation.

USAGE

    python -m tools.unguarded_production_files --base origin/master \\
        --suite tests/gui --include src/ --include config/

`--include` and `--suffix` add to the runtime defaults; they never remove them.

Each artifact is restored from the ORIGINAL bytes read before mutation, and the
restore is verified byte-for-byte. It refuses to run against a dirty tree for
the artifacts it would touch, because a revert it cannot undo is worse than a
measurement it never took.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Production artifacts are not only Python, and not only this repository's own
# process. The severity floor counts tracked runtime configuration -- interlock
# thresholds, channel patterns, shutdown actions -- because a wrong value there
# misfires an interlock exactly as wrong code does. It equally counts code this
# repository UPLOADS to an instrument: `tsp/cryodaq_wdog.lua` is re-sent to the
# Keithley on every connection and is the watchdog that takes the source down.
#
# That file is why the amendment stopped defining the floor as a list of
# directories, and for one review round the TOOL still could not see it on
# either axis -- no `.lua` suffix, no `tsp/` prefix -- so the instrument that
# measures the floor disagreed with the floor's own text. A measuring tool that
# cannot see the artifact its rule names is the first false-green that rule
# would have shipped.
#
# `plugins/` is the SAME CLASS, found the same way one round later:
# `analytics/plugin_loader.py` loads every `.py` in that directory at runtime
# and subscribes it to the broker, so a defect in `plugins/phase_detector.py`
# executes during an experiment. It was invisible here for exactly the reason
# `tsp/` was -- the default target set was still a list of two directories
# rather than an answer to "what does the instrument read or execute". Adding
# entries one review round at a time is treating instances; the rule is that
# this roster tracks RUNTIME REACH, and a new runtime-loaded location belongs
# here the day it is created.
_DEFAULT_SUFFIXES = (".py", ".pyw", ".yaml", ".yml", ".json", ".toml", ".lua")
_DEFAULT_INCLUDES = ("src/", "config/", "tsp/", "plugins/")
_PYTEST_TIMEOUT_SECONDS = 120
_RECOVERY_NAME = ".audit-unguarded-production-recovery.json"


@dataclass(frozen=True)
class ChangedArtifact:
    """One production change, including both names of a rename."""

    base_path: str | None
    candidate_path: str | None

    @property
    def label(self) -> str:
        if self.base_path != self.candidate_path:
            return f"{self.base_path} -> {self.candidate_path}"
        return str(self.candidate_path or self.base_path)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(path for path in (self.base_path, self.candidate_path) if path is not None))


@dataclass(frozen=True)
class PathIdentity:
    """Filesystem identity sufficient to preserve another writer's path."""

    kind: str
    payload: bytes | str | None = None
    mode: int | None = None


@dataclass(frozen=True)
class GitEntry:
    """The complete tree identity relevant to an executable artifact."""

    mode: str
    object_type: str
    object_id: str
    content: bytes


@dataclass(frozen=True)
class SuiteInputs:
    """Candidate and repository inputs whose stability makes attribution valid."""

    head: str
    index_entries: bytes
    listed_paths: tuple[str, ...]
    worktree: tuple[tuple[str, PathIdentity], ...]

    def excluding(self, paths: set[str]) -> SuiteInputs:
        return SuiteInputs(
            self.head,
            self.index_entries,
            tuple(path for path in self.listed_paths if path not in paths),
            tuple(item for item in self.worktree if item[0] not in paths),
        )


def path_identity(path: Path) -> PathIdentity:
    if path.is_symlink():
        return PathIdentity("symlink", os.readlink(path), stat.S_IMODE(path.lstat().st_mode))
    if not path.exists():
        return PathIdentity("absent")
    if not path.is_file():
        raise MeasurementError(f"{path} is not a regular file or symlink")
    return PathIdentity("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def restore_path(path: Path, identity: PathIdentity) -> None:
    path.unlink(missing_ok=True)
    if identity.kind == "absent":
        return
    if identity.kind == "symlink":
        os.symlink(str(identity.payload), path)
    elif identity.kind == "file":
        path.write_bytes(bytes(identity.payload))
    else:  # pragma: no cover - construction is private and exhaustive
        raise AssertionError(f"unknown path identity {identity.kind!r}")
    if identity.mode is None:
        return
    if identity.kind != "symlink":
        os.chmod(path, identity.mode)
        return
    try:
        os.chmod(path, identity.mode, follow_symlinks=False)
    except NotImplementedError:
        lchmod = getattr(os, "lchmod", None)
        if lchmod is not None:
            lchmod(path, identity.mode)


def restore_path_atomically(root: Path, path: Path, identity: PathIdentity) -> None:
    """Restore through a same-volume replacement so a killed writer cannot truncate the target."""

    if identity.kind == "absent":
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".audit-unguarded-restore-", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        restore_path(temporary, identity)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run(
    args: list[str], env: dict[str, str] | None = None, *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


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


def changed_files(point: str, includes: tuple[str, ...], suffixes: tuple[str, ...]) -> list[ChangedArtifact]:
    out = _git(["diff", "--name-status", "-z", "--find-renames", point, "HEAD"])
    out.check_returncode()
    fields = out.stdout.split("\0")
    if fields and not fields[-1]:
        fields.pop()
    artifacts: list[ChangedArtifact] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith("R"):
            old, new = fields[index : index + 2]
            index += 2
            artifact = ChangedArtifact(old, new)
        else:
            path = fields[index]
            index += 1
            kind = status[:1]
            artifact = ChangedArtifact(None if kind == "A" else path, None if kind == "D" else path)
        if any(
            path.endswith(suffixes) and any(path.startswith(prefix) for prefix in includes) for path in artifact.paths
        ):
            artifacts.append(artifact)
    return sorted(artifacts, key=lambda artifact: artifact.label)


def changed_hunk_count(point: str, path: str) -> int:
    out = _git(["diff", "--unified=0", "--no-ext-diff", "--no-textconv", point, "HEAD", "--", path])
    out.check_returncode()
    return sum(line.startswith("@@ ") for line in out.stdout.splitlines())


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


class SuiteInputDrift(MeasurementError):
    """The candidate or a possible suite input changed between observations."""


def _suite_inputs_once(root: Path, excluded: set[str] | None = None) -> SuiteInputs:
    excluded = excluded or set()
    head = _git(["rev-parse", "HEAD"])
    head.check_returncode()
    index_entries = _git_bytes(["ls-files", "--stage", "-z"])
    index_entries.check_returncode()
    listed_paths = _git_bytes(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    listed_paths.check_returncode()
    paths = tuple(os.fsdecode(raw) for raw in listed_paths.stdout.split(b"\0") if raw)
    included = tuple(path for path in paths if path not in excluded)
    identities = tuple((path, path_identity(root / path)) for path in included)
    return SuiteInputs(head.stdout.strip(), index_entries.stdout, included, identities)


def capture_suite_inputs(root: Path) -> SuiteInputs:
    """Take a stable snapshot, refusing a repository moving while it is read."""

    first = _suite_inputs_once(root)
    second = _suite_inputs_once(root)
    if first != second:
        raise SuiteInputDrift("suite inputs changed while their initial identity was captured")
    return first


def assert_suite_inputs_unchanged(expected: SuiteInputs, root: Path, *, excluded: tuple[str, ...] = ()) -> None:
    omitted = {*excluded, _RECOVERY_NAME, f"{_RECOVERY_NAME}.tmp"}
    first = _suite_inputs_once(root, omitted)
    second = _suite_inputs_once(root, omitted)
    if first != second:
        raise SuiteInputDrift("suite inputs changed while their identity was rechecked")
    baseline = expected.excluding(omitted)
    if first == baseline:
        return
    if first.head != baseline.head:
        detail = f"HEAD moved from {baseline.head[:8]} to {first.head[:8]}"
    elif first.index_entries != baseline.index_entries:
        detail = "the Git index changed"
    elif first.listed_paths != baseline.listed_paths:
        detail = "the tracked/untracked input inventory changed"
    else:
        current = dict(first.worktree)
        detail = next(
            (f"{path} changed" for path, identity in baseline.worktree if current.get(path) != identity),
            "a suite input changed",
        )
    raise SuiteInputDrift(detail)


def git_entry(point: str, path: str | None) -> GitEntry | None:
    if path is None:
        return None
    out = _git_bytes(["ls-tree", "-z", point, "--", path])
    if out.returncode != 0:
        raise MeasurementError(
            f"{path} tree identity at {point[:8]} could not be read: "
            f"{out.stderr.decode('utf-8', 'replace').strip()[:200]}"
        )
    if not out.stdout:
        return None
    metadata, returned_path = out.stdout.rstrip(b"\0").split(b"\t", 1)
    mode, object_type, object_id = metadata.decode("ascii").split()
    if os.fsdecode(returned_path) != path:
        raise MeasurementError(f"Git returned {os.fsdecode(returned_path)!r} while reading {path!r}")
    if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
        raise MeasurementError(f"{path} has unsupported Git identity {mode} {object_type}")
    content = base_content(point, path)
    if content is None:
        raise MeasurementError(f"{path} has a tree entry at {point[:8]} but no readable blob")
    return GitEntry(mode, object_type, object_id, content)


def path_matches_git_entry(path: Path, entry: GitEntry | None) -> bool:
    if entry is None:
        return path_identity(path).kind == "absent"
    if entry.mode == "120000":
        return path.is_symlink() and os.fsencode(os.readlink(path)) == entry.content
    if path.is_symlink() or not path.is_file() or path.read_bytes() != entry.content:
        return False
    executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
    return executable == (entry.mode == "100755")


def materialize_git_entry(path: Path, entry: GitEntry) -> None:
    """Put one tree entry on disk, or refuse if this host cannot represent it."""

    path.unlink(missing_ok=True)
    if entry.mode == "120000":
        try:
            os.symlink(os.fsdecode(entry.content), path)
        except OSError as exc:
            raise MeasurementError(f"{path} symlink mode cannot be represented on this host: {exc}") from exc
    else:
        path.write_bytes(entry.content)
        current = stat.S_IMODE(path.stat().st_mode)
        if entry.mode == "100755":
            desired = current | ((current & 0o444) >> 2)
        else:
            desired = current & ~0o111
        os.chmod(path, desired)
    if not path_matches_git_entry(path, entry):
        raise MeasurementError(f"{path} Git mode {entry.mode} cannot be represented on this host")


def _identity_json(identity: PathIdentity) -> dict[str, object]:
    payload: object = identity.payload
    if isinstance(payload, bytes):
        payload = {"bytes": base64.b64encode(payload).decode("ascii")}
    return {"kind": identity.kind, "payload": payload, "mode": identity.mode}


def _identity_from_json(payload: object) -> PathIdentity:
    if not isinstance(payload, dict) or payload.get("kind") not in {"absent", "file", "symlink"}:
        raise ValueError("invalid original path identity")
    value = payload.get("payload")
    if isinstance(value, dict) and set(value) == {"bytes"}:
        value = base64.b64decode(str(value["bytes"]), validate=True)
    mode = payload.get("mode")
    if mode is not None and not isinstance(mode, int):
        raise ValueError("invalid original path mode")
    return PathIdentity(str(payload["kind"]), value, mode)


def _entry_json(entry: GitEntry | None) -> dict[str, str] | None:
    if entry is None:
        return None
    return {
        "mode": entry.mode,
        "object_type": entry.object_type,
        "object_id": entry.object_id,
        "content": base64.b64encode(entry.content).decode("ascii"),
    }


def _entry_from_json(payload: object) -> GitEntry | None:
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {"mode", "object_type", "object_id", "content"}:
        raise ValueError("invalid mutant Git identity")
    return GitEntry(
        str(payload["mode"]),
        str(payload["object_type"]),
        str(payload["object_id"]),
        base64.b64decode(str(payload["content"]), validate=True),
    )


def _recovery_path(root: Path) -> Path:
    return root / _RECOVERY_NAME


def arm_recovery(root: Path, records: tuple[tuple[str, PathIdentity, GitEntry | None], ...]) -> None:
    """Persist restore intent before changing any candidate path."""

    journal = _recovery_path(root)
    if journal.exists():
        raise MeasurementError(f"pending recovery journal already exists at {journal}")
    payload = {
        "version": 1,
        "paths": [
            {"path": path, "original": _identity_json(original), "mutant": _entry_json(mutant)}
            for path, original, mutant in records
        ],
    }
    temporary = journal.with_suffix(journal.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, journal)


def clear_recovery(root: Path) -> None:
    _recovery_path(root).unlink(missing_ok=True)


def recover_pending(root: Path) -> bool:
    """Restore an interrupted mutation, but never overwrite unknown bytes."""

    journal = _recovery_path(root)
    if not journal.exists():
        return False
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("paths"), list):
            raise ValueError("invalid recovery journal schema")
        records: list[tuple[Path, PathIdentity, GitEntry | None]] = []
        for record in payload["paths"]:
            if not isinstance(record, dict) or set(record) != {"path", "original", "mutant"}:
                raise ValueError("invalid recovery path record")
            relative = str(record["path"])
            parsed = PurePosixPath(relative)
            if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != relative:
                raise ValueError(f"unsafe recovery path {relative!r}")
            path = root.joinpath(*parsed.parts)
            if not path.parent.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"recovery parent escapes the worktree: {relative!r}")
            records.append((path, _identity_from_json(record["original"]), _entry_from_json(record["mutant"])))
    except (OSError, TypeError, ValueError) as exc:
        raise MeasurementError(f"pending recovery journal is unreadable: {exc}") from exc

    states: list[tuple[Path, PathIdentity, bool]] = []
    for path, original, mutant in records:
        current = path_identity(path)
        is_original = current == original
        is_mutant = path_matches_git_entry(path, mutant)
        if not (is_original or is_mutant):
            raise MeasurementError(f"{path} matches neither the recorded candidate nor mutant; left untouched")
        states.append((path, original, is_original))
    for path, original, is_original in states:
        if not is_original:
            restore_path_atomically(root, path, original)
        if path_identity(path) != original:
            raise MeasurementError(f"{path} could not be restored from the recovery journal")
    journal.unlink()
    return True


def failures(suites: list[str], cache_prefix: Path) -> list[str]:
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(cache_prefix), PYTHONDONTWRITEBYTECODE="")
    found: list[str] = []
    for suite in suites:
        try:
            run = _run(
                [sys.executable, "-m", "pytest", suite, "-q", "--no-header", "-rf", "-p", "no:cacheprovider"],
                env=env,
                timeout=_PYTEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise MeasurementError(f"pytest over {suite!r} exceeded {_PYTEST_TIMEOUT_SECONDS} seconds") from exc
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


def fresh_failures(suites: list[str], prefix: str) -> list[str]:
    cache = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        return failures(suites, cache)
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def repeated_mutant_failures(suites: list[str]) -> list[str]:
    first = sorted(set(fresh_failures(suites, "unguarded-mutant-")))
    second = sorted(set(fresh_failures(suites, "unguarded-mutant-repeat-")))
    if first != second:
        raise MeasurementError("mutant failures did not repeat exactly on the second run")
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--suffix", action="append", default=[])
    options = parser.parse_args()
    suites = options.suite or ["tests"]
    includes = tuple(dict.fromkeys((*_DEFAULT_INCLUDES, *options.include)))
    suffixes = tuple(dict.fromkeys((*_DEFAULT_SUFFIXES, *options.suffix)))

    root = repository_root()
    try:
        recovered = recover_pending(root)
    except MeasurementError as unreadable:
        print(f"REFUSING: an interrupted mutation could not be recovered safely: {unreadable}")
        return 2
    if recovered:
        print("recovered the candidate from an interrupted mutation before measuring")

    point = merge_base(options.base)
    targets = changed_files(point, includes, suffixes)
    if not targets:
        print(f"no production artifacts changed against {point[:8]}; nothing to measure")
        return 0

    target_paths = tuple(dict.fromkeys(path for target in targets for path in target.paths))
    dirty = _git(["status", "--porcelain", "--", *target_paths]).stdout.strip()
    if dirty:
        print("REFUSING: these artifacts have uncommitted changes, so a revert could not be undone safely:")
        print(dirty)
        return 2

    uncommitted = _git(["status", "--porcelain=v1", "--untracked-files=all"]).stdout.strip()
    if uncommitted:
        print("REFUSING: uncommitted candidate inputs cannot be attributed to HEAD:")
        print(uncommitted)
        return 2

    try:
        suite_inputs = capture_suite_inputs(root)
    except MeasurementError as unreadable:
        print(f"REFUSING: suite input identity could not be captured: {unreadable}")
        return 2

    # THE CONTROL. Without it, a suite that already fails hands the same failure
    # to every reverted artifact and every one is reported guarded.
    try:
        control = fresh_failures(suites, "unguarded-control-")
    except MeasurementError as unreadable:
        print(f"REFUSING: the control run produced no readable result, so nothing can be attributed:\n{unreadable}")
        return 2
    if control:
        print(f"REFUSING: the control run is not green ({len(control)} failing), so no revert can be attributed:")
        for name in sorted(set(control))[:10]:
            print(f"    {name}")
        return 2
    try:
        assert_suite_inputs_unchanged(suite_inputs, root)
    except SuiteInputDrift as drift:
        print(f"REFUSING: suite inputs drifted after the green control: {drift}")
        return 2
    print(f"control: green over {', '.join(suites)}")
    print()
    print("| reverted production artifact | new failures introduced by the revert |")
    print("|---|---|")

    unguarded: list[str] = []
    unmeasured: list[str] = []
    clobbered: list[str] = []
    for target in targets:
        try:
            assert_suite_inputs_unchanged(suite_inputs, root)
        except SuiteInputDrift as drift:
            print(f"REFUSING: suite inputs drifted before mutation attribution: {drift}")
            return 2
        path = str(target.candidate_path or target.base_path)
        if (
            target.base_path == target.candidate_path
            and target.candidate_path is not None
            and changed_hunk_count(point, target.candidate_path) > 1
        ):
            unmeasured.append(target.label)
            print(f"| `{target.label}` | **NOT MEASURED** — multiple independent diff hunks need separate evidence |")
            continue
        if target.base_path != target.candidate_path:
            old = root / str(target.base_path)
            new = root / str(target.candidate_path)
            old_original = path_identity(old)
            new_original = path_identity(new)
            before = git_entry(point, target.base_path)
            candidate = git_entry("HEAD", target.candidate_path)
            concurrent = False
            armed = False
            old_mutant: PathIdentity | None = None
            new_mutant: PathIdentity | None = None
            drift_error: SuiteInputDrift | None = None
            try:
                if (
                    before is None
                    or candidate is None
                    or old_original.kind != "absent"
                    or not path_matches_git_entry(new, candidate)
                ):
                    unmeasured.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — rename pair has an unreadable identity |")
                    continue
                if path_identity(old) != old_original or path_identity(new) != new_original:
                    clobbered.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — rename pair changed before mutation |")
                    continue
                arm_recovery(
                    root,
                    (
                        (str(target.base_path), old_original, before),
                        (str(target.candidate_path), new_original, None),
                    ),
                )
                armed = True
                old.parent.mkdir(parents=True, exist_ok=True)
                materialize_git_entry(old, before)
                old_mutant = path_identity(old)
                new.unlink()
                new_mutant = path_identity(new)
                try:
                    introduced = sorted(set(repeated_mutant_failures(suites)) - set(control))
                    assert_suite_inputs_unchanged(suite_inputs, root, excluded=target.paths)
                except SuiteInputDrift as drift:
                    drift_error = drift
                    introduced = []
                except MeasurementError as unreadable:
                    unmeasured.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                    continue
            finally:
                old_unchanged = old_mutant is not None and path_identity(old) == old_mutant
                new_unchanged = new_mutant is not None and path_identity(new) == new_mutant
                concurrent = old_mutant is not None and not (old_unchanged and new_unchanged)
                if old_unchanged:
                    restore_path_atomically(root, old, old_original)
                if new_unchanged:
                    restore_path_atomically(root, new, new_original)
                if concurrent:
                    clobbered.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — rename pair changed during the run |")
                if armed and (
                    concurrent or (path_identity(old) == old_original and path_identity(new) == new_original)
                ):
                    clear_recovery(root)
            if drift_error is not None:
                print(f"REFUSING: suite inputs drifted before mutation attribution: {drift_error}")
                return 2
            if concurrent:
                continue
            if introduced:
                try:
                    restored = fresh_failures(suites, "unguarded-restored-")
                    assert_suite_inputs_unchanged(suite_inputs, root)
                except MeasurementError as unreadable:
                    unmeasured.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                    continue
                if restored:
                    unmeasured.append(target.label)
                    print(f"| `{target.label}` | **NOT MEASURED** — restored candidate was not green |")
                    continue
                print(f"| `{target.label}` | **{len(introduced)} new** — {', '.join(introduced[:3])} |")
            else:
                print(f"| `{target.label}` | **0 new — UNGUARDED** |")
                unguarded.append(target.label)
            continue
        source = root / path
        original = path_identity(source)
        before = git_entry(point, target.base_path)
        candidate = git_entry("HEAD", target.candidate_path)
        armed = False
        mutant: PathIdentity | None = None
        drift_error: SuiteInputDrift | None = None
        try:
            if before is None:
                if candidate is None or original.kind == "absent":
                    unmeasured.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — absent from both sides |")
                    continue
                # Window one applies here too. An added artifact took this
                # branch without the reread and left `mutant` None, so the
                # post-run check below could not fire for it: another lane's
                # newly written file could be deleted and then recreated from
                # bytes this tool captured before that lane wrote them.
                if not path_matches_git_entry(source, candidate) or path_identity(source) != original:
                    clobbered.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — changed on disk before mutation; refusing to remove |")
                    continue
                arm_recovery(root, ((path, original, None),))
                armed = True
                source.unlink()  # an ADDED artifact is reverted by removing it
                mutant = path_identity(source)
            else:
                if candidate is not None and before == candidate:
                    print(f"| `{path}` | identical to the merge base — not measured |")
                    continue
                if candidate is not None and not path_matches_git_entry(source, candidate):
                    unmeasured.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — candidate Git identity is not present on this host |")
                    continue
                # WINDOW ONE. The up-front porcelain check cannot see an edit
                # made after it ran. Re-read immediately before writing, and
                # refuse rather than destroy a concurrent writer's bytes.
                if path_identity(source) != original:
                    clobbered.append(path)
                    print(f"| `{path}` | **NOT MEASURED** — changed on disk before mutation; refusing to overwrite |")
                    continue
                arm_recovery(root, ((path, original, before),))
                armed = True
                materialize_git_entry(source, before)
                mutant = path_identity(source)
            try:
                introduced = sorted(set(repeated_mutant_failures(suites)) - set(control))
                assert_suite_inputs_unchanged(suite_inputs, root, excluded=target.paths)
            except SuiteInputDrift as drift:
                drift_error = drift
                introduced = []
            except MeasurementError as unreadable:
                unmeasured.append(path)
                print(f"| `{path}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                continue
        finally:
            # WINDOW TWO. Another worker may have written while pytest ran. If
            # what is on disk is no longer the mutant we placed there, those are
            # someone else's bytes: leave them, and say so. An unconditional
            # restore here would erase work this tool never owned.
            concurrent = mutant is not None and path_identity(source) != mutant
            if concurrent:
                clobbered.append(path)
                print(f"| `{path}` | **NOT MEASURED** — changed on disk during the run; left as found |")
            else:
                restore_path_atomically(root, source, original)
                assert path_identity(source) == original, f"{path} was NOT restored with its complete identity"
            if armed and (concurrent or path_identity(source) == original):
                clear_recovery(root)
        if drift_error is not None:
            print(f"REFUSING: suite inputs drifted before mutation attribution: {drift_error}")
            return 2
        if concurrent:
            continue
        if introduced:
            try:
                restored = fresh_failures(suites, "unguarded-restored-")
                assert_suite_inputs_unchanged(suite_inputs, root)
            except MeasurementError as unreadable:
                unmeasured.append(path)
                print(f"| `{path}` | **NOT MEASURED** — {str(unreadable).splitlines()[0]} |")
                continue
            if restored:
                unmeasured.append(path)
                print(f"| `{path}` | **NOT MEASURED** — restored candidate was not green |")
                continue
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
