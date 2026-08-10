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

FAILURE CLASSES THIS TOOL COULD HAVE LIED THROUGH, each enforced here after
review found it -- and each found by review rather than by the author, which is
the same asymmetry the tool exists to exploit:

* **A dirty control.** If the suite already fails, every reverted artifact
  collects that same failure and is reported guarded. The suite is therefore
  run FIRST, unmutated, and only failures NEW relative to that control count.
  A control that is not green fails the run closed rather than manufacturing
  coverage.
* **Configuration and assets invisible.** Requiring a known suffix meant
  configuration, firmware, served HTML, icons, and fonts could disappear from
  measurement. Every tracked artifact below a derived runtime root is eligible;
  there is no second suffix allowlist.
* **Added files skipped.** A new module has no base content to revert to, so
  it was skipped while the run still exited 0. Added/deleted content cannot be
  isolated honestly and is now reported NOT MEASURED with a nonzero result.
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
* **Clobbering a concurrent writer.** The up-front porcelain check could not see
  a later edit, and an unconditional restore destroyed another worker's bytes.
  The source checkout is now read-only and revalidated around every disposable
  run; no mutant or confirmation operation targets a source path.
* **Losing the file's identity.** A byte-only restore erased symlink and mode
  identity while its content assertion passed. Disposable checkouts come from
  Git, exact renames move the entry itself, and its complete Git identity is
  verified before pytest runs.
* **Inherited Git authority.** Every query ran with the caller's `GIT_DIR`,
  `GIT_WORK_TREE`, `GIT_INDEX_FILE`, grafts and replacement refs, so discovery
  could describe a FOREIGN repository while the writes still landed here.
  Queries are bound to this checkout with that environment stripped.
* **A custom filter erased runtime artifacts.** `--include src/` replaced rather
  than extended the default roster, silently dropping runtime roots. Default
  roots now derive from both Git trees by excluding only the severity floor's
  explicit non-production categories; custom includes are additive.
* **One artifact concealed independent edits.** Whole-file reversion cannot
  attribute separate behaviours within a file, so every content change refuses
  certification; only identity-only changes can be measured honestly.
* **Transaction state changed the measured checkout.** The measured source
  checkout is never mutated. Control, mutant, and confirmation runs use verified
  disposable
  local Git checkouts under external same-volume state.
* **A hanging mutant stranded descendants.** Timed pytest runs execute inside a
  Windows Job or Linux subreaper boundary, and disposable-state cleanup begins
  only after the entire process tree is verified settled.
* **A killed write could truncate the candidate.** Content and mode changes are
  refused. An exact-entry rename is reversed only inside a disposable checkout
  with an atomic filesystem rename, then committed into a clean synthetic
  snapshot before pytest can run.
* **A mutation created persistent structure.** A former parent is created only
  inside the disposable checkout; the source tree never gains directories or
  recovery artifacts.
* **Measurement scaffolding looked like production.** Dirty/staged mutant Git
  state and phase-labelled cache paths could make unrelated tests red. Every
  phase now runs from a clean deterministic synthetic commit and uses the same
  neutral external-state path shape.
* **A clean checkout hid transformed bytes.** Git filters can materialize bytes
  that differ from the tree while porcelain remains clean. Every tracked raw
  blob and supported mode is verified before candidate code runs.
* **Candidate code retained judge authority.** Protected CI channels, inherited
  Git redirection, source-path environment values, clone origins, and
  unconfined pytest selectors could escape the disposable boundary. They are
  stripped or rejected before launch.
* **One flaky red counted as coverage.** A mutant failure must repeat exactly,
  then the same node must disappear in a fresh candidate checkout in this
  invocation.

USAGE

    python -m tools.unguarded_production_files --base origin/master \\
        --suite tests/gui --include src/ --include config/

--include adds to the derived runtime defaults; it never removes them.

The measured source checkout is read-only. Only an exact-entry rename is
measured in a disposable verified clean snapshot; content, add/delete, and mode
changes fail closed.
The tool refuses uncommitted inputs because they cannot be reproduced in that
checkout or attributed to HEAD.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from tools.ci_active_checkout_runner import (
    CandidateProcessSettlementError,
    CandidateProcessUnsettledError,
    _checkout_environment,
    _run_candidate_process,
)

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
# executes during an experiment. An allowlist cannot enforce that lesson: the
# next top-level runtime root would be invisible until somebody remembered to
# add it. Defaults therefore derive every top-level Git tree except the
# categories the severity floor explicitly calls non-production. A new root is
# measured on the commit that introduces it, without changing this tool.
# Every tracked artifact below a derived runtime root is eligible; runtime-loaded assets have no safe suffix allowlist.
_NON_RUNTIME_TOP_LEVELS = frozenset({".github", "build_scripts", "docs", "governance", "scripts", "tests", "tools"})
_PYTEST_TIMEOUT_SECONDS = 120
_STATE_DIRECTORY_NAME = "cryodaq-unguarded-production-files"


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
    porcelain: bytes
    listed_paths: tuple[str, ...]
    worktree: tuple[tuple[str, PathIdentity], ...]

    def excluding(self, paths: set[str]) -> SuiteInputs:
        return SuiteInputs(
            self.head,
            self.index_entries,
            self.porcelain,
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


def _state_directory(root: Path) -> Path:
    """Return same-volume disposable state outside the read-only candidate checkout."""

    canonical_root = root.resolve(strict=True)
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if temporary_root == canonical_root or temporary_root.is_relative_to(canonical_root):
        raise MeasurementError("temporary state root is inside the measured checkout")
    if os.stat(temporary_root).st_dev != os.stat(canonical_root).st_dev:
        raise MeasurementError("temporary state root is not on the measured checkout volume")
    state = temporary_root / _STATE_DIRECTORY_NAME
    state.mkdir(parents=True, exist_ok=True)
    state = state.resolve(strict=True)
    if state.is_relative_to(canonical_root):
        raise MeasurementError("disposable state resolved inside the measured checkout")
    if os.stat(state).st_dev != os.stat(canonical_root).st_dev:
        raise MeasurementError("disposable state resolved onto another volume")
    return state


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


def _git_at(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(root), "--no-replace-objects", *args], env=_git_env())


def _git_bytes_at(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), "--no-replace-objects", *args],
        capture_output=True,
        env=_git_env(),
    )


def merge_base(base: str, head: str) -> str:
    out = _git(["merge-base", base, head])
    out.check_returncode()
    return out.stdout.strip()


def default_runtime_includes(*points: str) -> tuple[str, ...]:
    """Derive top-level runtime candidates from immutable Git trees."""

    roots: set[str] = set()
    for point in points:
        out = _git(["ls-tree", "-z", point])
        out.check_returncode()
        for record in out.stdout.split("\0"):
            if not record:
                continue
            metadata, name = record.split("\t", 1)
            _mode, object_type, _object_id = metadata.split()
            if "/" in name or name in {".", ".."}:
                raise MeasurementError(f"Git returned a non-top-level runtime candidate: {name!r}")
            if name in _NON_RUNTIME_TOP_LEVELS:
                continue
            if object_type == "tree":
                roots.add(f"{name}/")
            elif object_type == "blob":
                roots.add(name)
            else:
                raise MeasurementError(f"Git returned unsupported top-level object type {object_type!r} for {name}")
    return tuple(sorted(roots))


def _path_is_included(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return bool(normalized) and (path == normalized or path.startswith(normalized + "/"))


def changed_files(
    point: str,
    candidate: str,
    includes: tuple[str, ...],
) -> list[ChangedArtifact]:
    out = _git(["diff", "--name-status", "-z", "--find-renames", point, candidate])
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
        if any(any(_path_is_included(path, prefix) for prefix in includes) for path in artifact.paths):
            artifacts.append(artifact)
    return sorted(artifacts, key=lambda artifact: artifact.label)


def base_content_at(root: Path, point: str, path: str) -> bytes | None:
    """Return one exact blob, distinguishing absence from an unreadable object."""

    out = _git_bytes_at(root, ["cat-file", "-e", f"{point}:{path}"])
    if out.returncode != 0:
        return None
    blob = _git_bytes_at(root, ["show", f"{point}:{path}"])
    if blob.returncode != 0:
        raise MeasurementError(
            f"{path} exists at {point[:8]} but its blob could not be read: "
            f"{blob.stderr.decode('utf-8', 'replace').strip()[:200]}"
        )
    return blob.stdout


def base_content(point: str, path: str) -> bytes | None:
    return base_content_at(repository_root(), point, path)


class MeasurementError(RuntimeError):
    """A suite run whose result cannot be read as evidence either way."""


class UnsettledProcessTree(MeasurementError):
    """A candidate process tree could not be proven terminated."""


class SuiteInputDrift(MeasurementError):
    """The candidate or a possible suite input changed between observations."""


def _suite_inputs_once(root: Path, excluded: set[str] | None = None) -> SuiteInputs:
    excluded = excluded or set()
    head = _git_at(root, ["rev-parse", "HEAD"])
    index_entries = _git_bytes_at(root, ["ls-files", "--stage", "-z"])
    listed_paths = _git_bytes_at(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    paths = tuple(os.fsdecode(raw) for raw in listed_paths.stdout.split(b"\0") if raw)
    included = tuple(path for path in paths if path not in excluded)
    identities = tuple((path, path_identity(root / path)) for path in included)
    porcelain = _git_bytes_at(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if any(run.returncode != 0 for run in (head, index_entries, listed_paths, porcelain)):
        raise SuiteInputDrift("repository inputs became unreadable while their identity was captured")
    return SuiteInputs(head.stdout.strip(), index_entries.stdout, porcelain.stdout, included, identities)


def capture_suite_inputs(root: Path) -> SuiteInputs:
    """Take a stable snapshot, refusing a repository moving while it is read."""

    first = _suite_inputs_once(root)
    second = _suite_inputs_once(root)
    if first != second:
        raise SuiteInputDrift("suite inputs changed while their initial identity was captured")
    return first


def assert_suite_inputs_unchanged(expected: SuiteInputs, root: Path, *, excluded: tuple[str, ...] = ()) -> None:
    omitted = set(excluded)
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
    elif first.porcelain != baseline.porcelain:
        detail = "the Git worktree/index cleanliness changed"
    elif first.listed_paths != baseline.listed_paths:
        detail = "the tracked/untracked input inventory changed"
    else:
        current = dict(first.worktree)
        detail = next(
            (f"{path} changed" for path, identity in baseline.worktree if current.get(path) != identity),
            "a suite input changed",
        )
    raise SuiteInputDrift(detail)


def git_entry_at(root: Path, point: str, path: str | None) -> GitEntry | None:
    if path is None:
        return None
    out = _git_bytes_at(root, ["ls-tree", "-z", point, "--", path])
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
    content = base_content_at(root, point, path)
    if content is None:
        raise MeasurementError(f"{path} has a tree entry at {point[:8]} but no readable blob")
    return GitEntry(mode, object_type, object_id, content)


def git_entry(point: str, path: str | None) -> GitEntry | None:
    return git_entry_at(repository_root(), point, path)


def path_matches_git_entry(path: Path, entry: GitEntry | None) -> bool:
    if entry is None:
        return path_identity(path).kind == "absent"
    if entry.mode == "120000":
        return path.is_symlink() and os.fsencode(os.readlink(path)) == entry.content
    if path.is_symlink() or not path.is_file() or path.read_bytes() != entry.content:
        return False
    executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
    return executable == (entry.mode == "100755")


def _git_blob_id(payload: bytes, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest()


def assert_checkout_matches_tree(root: Path, revision: str) -> None:
    """Prove every materialized tracked entry has the tree's raw bytes and mode."""

    object_format = _git_at(root, ["rev-parse", "--show-object-format"])
    listing = _git_bytes_at(root, ["ls-tree", "-r", "-z", revision])
    if object_format.returncode != 0 or listing.returncode != 0:
        raise MeasurementError("disposable checkout tree identity could not be read")
    algorithm = object_format.stdout.strip()
    try:
        hashlib.new(algorithm)
    except ValueError as exc:
        raise MeasurementError(f"unsupported Git object format {algorithm!r}") from exc

    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_relative = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split()
        relative = _safe_relative(os.fsdecode(raw_relative))
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise MeasurementError(f"tracked entry {relative!r} has unsupported checkout identity {mode} {object_type}")
        path = _checkout_path(root, relative)
        if mode == "120000":
            if not path.is_symlink():
                raise MeasurementError(f"tracked symlink {relative!r} was not materialized as a symlink")
            payload = os.fsencode(os.readlink(path))
        else:
            if path.is_symlink() or not path.is_file():
                raise MeasurementError(f"tracked file {relative!r} was not materialized as a regular file")
            payload = path.read_bytes()
            if os.name != "nt":
                executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
                if executable != (mode == "100755"):
                    raise MeasurementError(f"tracked file {relative!r} has the wrong executable mode")
        if _git_blob_id(payload, algorithm) != object_id:
            raise MeasurementError(f"tracked file {relative!r} does not have its Git tree's raw blob identity")


def _synthetic_commit_environment() -> dict[str, str]:
    environment = _git_env()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_AUTHOR_EMAIL": "measurement@example.invalid",
            "GIT_AUTHOR_NAME": "CryoDAQ measurement",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_EMAIL": "measurement@example.invalid",
            "GIT_COMMITTER_NAME": "CryoDAQ measurement",
        }
    )
    return environment


def _materialize_clean_snapshot(
    checkout: Path,
    revision: str,
    reverse_rename: tuple[str, str, GitEntry, GitEntry] | None,
) -> str:
    """Normalize candidate and mutant alike to clean, deterministic synthetic commits."""

    candidate_tree = _git_at(checkout, ["rev-parse", f"{revision}^{{tree}}"])
    if candidate_tree.returncode != 0:
        raise MeasurementError("candidate tree could not be resolved in the disposable checkout")
    assert_checkout_matches_tree(checkout, revision)

    old_relative: str | None = None
    new_relative: str | None = None
    before: GitEntry | None = None
    candidate: GitEntry | None = None
    if reverse_rename is not None:
        old_relative, new_relative, before, candidate = reverse_rename
        old_relative = _safe_relative(old_relative)
        new_relative = _safe_relative(new_relative)
        if before != candidate or old_relative == new_relative:
            raise MeasurementError("disposable mutation is not an exact-entry rename")
        old = _checkout_path(checkout, old_relative)
        new = _checkout_path(checkout, new_relative)
        if old.exists() or old.is_symlink() or not path_matches_git_entry(new, candidate):
            raise MeasurementError("disposable candidate rename pair has an unexpected identity")
        old.parent.mkdir(parents=True, exist_ok=True)
        old = _checkout_path(checkout, old_relative)
        os.replace(new, old)
        if not path_matches_git_entry(old, before) or new.exists() or new.is_symlink():
            raise MeasurementError("atomic disposable rename did not produce the requested mutant")
        _run_measurement_command(("git", "update-index", "--force-remove", "--", new_relative), root=checkout)
        _run_measurement_command(
            (
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"{before.mode},{before.object_id},{old_relative}",
            ),
            root=checkout,
        )

    tree = _run_measurement_command(("git", "write-tree"), root=checkout).stdout.strip()
    if reverse_rename is None:
        if tree != candidate_tree.stdout.strip():
            raise MeasurementError("clean candidate snapshot changed the candidate tree")
    else:
        difference = _git_at(
            checkout,
            ["diff", "--cached", "--name-status", "-z", "--find-renames=100%", revision, "--"],
        )
        expected = f"R100\0{new_relative}\0{old_relative}\0"
        if difference.returncode != 0 or difference.stdout != expected:
            raise MeasurementError("synthetic mutant tree differs by more than the exact reverse rename")

    commit = _run_measurement_command(
        ("git", "commit-tree", tree, "-p", revision, "-m", "CryoDAQ phase-neutral measurement snapshot"),
        root=checkout,
        environment=_synthetic_commit_environment(),
    ).stdout.strip()
    _run_measurement_command(("git", "reset", "--hard", "--quiet", commit), root=checkout)
    observed_head = _git_at(checkout, ["rev-parse", "HEAD"])
    status = _git_at(checkout, ["status", "--porcelain=v1", "--untracked-files=all"])
    if observed_head.returncode != 0 or observed_head.stdout.strip() != commit:
        raise MeasurementError("synthetic measurement snapshot did not become HEAD")
    if status.returncode != 0 or status.stdout:
        raise MeasurementError("synthetic measurement snapshot is not index/worktree clean")
    assert_checkout_matches_tree(checkout, commit)
    if reverse_rename is not None:
        assert old_relative is not None and new_relative is not None and before is not None
        old = _checkout_path(checkout, old_relative)
        new = _checkout_path(checkout, new_relative)
        if not path_matches_git_entry(old, before) or new.exists() or new.is_symlink():
            raise MeasurementError("clean synthetic mutant lost the exact reverse rename")
    return commit


def _safe_relative(value: object) -> str:
    relative = str(value)
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not relative
        or "\0" in relative
        or "\\" in relative
        or posix.is_absolute()
        or not posix.parts
        or ".." in posix.parts
        or posix.as_posix() != relative
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
    ):
        raise MeasurementError(f"unsafe repository path {relative!r}")
    return relative


def _checkout_path(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(_safe_relative(relative))
    path = root.joinpath(*parsed.parts)
    canonical_root = root.resolve(strict=True)
    current = root
    for part in parsed.parts[:-1]:
        current /= part
        if not current.exists():
            continue
        observed = current.lstat()
        junction = getattr(current, "is_junction", None)
        if current.is_symlink() or (junction is not None and junction()):
            raise MeasurementError(f"disposable-checkout parent is a link or junction: {current}")
        if not stat.S_ISDIR(observed.st_mode) or not current.resolve(strict=True).is_relative_to(canonical_root):
            raise MeasurementError(f"disposable-checkout parent escapes its root: {current}")
    return path


def _run_measurement_command(
    args: tuple[str, ...],
    *,
    root: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        run = _run_candidate_process(
            args,
            root=root,
            environment=environment if environment is not None else _git_env(),
            capture_output=True,
            timeout=_PYTEST_TIMEOUT_SECONDS,
        )
    except CandidateProcessUnsettledError as exc:
        raise UnsettledProcessTree(f"measurement command process tree did not settle: {exc}") from exc
    except CandidateProcessSettlementError as exc:
        raise MeasurementError(f"measurement command boundary failed safely: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MeasurementError(f"measurement command exceeded {_PYTEST_TIMEOUT_SECONDS} seconds: {args[0]}") from exc
    if run.returncode != 0:
        tail = "\n".join((str(run.stdout or "") + str(run.stderr or "")).splitlines()[-15:])
        raise MeasurementError(f"measurement command exited {run.returncode}: {' '.join(args[:3])}\n{tail}")
    return run


def _scrub_clone_source_metadata(checkout: Path, source: Path) -> None:
    """Remove clone metadata that would disclose or redirect into the measured source."""

    _run_measurement_command(("git", "remote", "remove", "origin"), root=checkout)
    git_directory = checkout / ".git"
    alternates = git_directory / "objects" / "info" / "alternates"
    if alternates.exists() and alternates.read_bytes().strip():
        raise MeasurementError("disposable checkout unexpectedly borrows source Git objects")
    try:
        shutil.rmtree(git_directory / "logs", ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise MeasurementError("disposable checkout clone reflogs could not be scrubbed") from exc
    for name in ("FETCH_HEAD", "ORIG_HEAD"):
        try:
            (git_directory / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise MeasurementError(f"disposable checkout {name} could not be scrubbed") from exc

    remotes = _git_at(checkout, ["remote"])
    remote_urls = _git_at(checkout, ["config", "--local", "--get-regexp", r"^remote\..*\.url$"])
    if remotes.returncode != 0 or remotes.stdout.strip():
        raise MeasurementError("disposable checkout retained a source remote")
    if remote_urls.returncode not in {0, 1} or remote_urls.stdout.strip():
        raise MeasurementError("disposable checkout retained a source remote URL")
    config = (git_directory / "config").read_text(encoding="utf-8", errors="replace").casefold()
    source_spellings = {str(source).casefold(), source.as_posix().casefold()}
    if any(spelling and spelling in config for spelling in source_spellings):
        raise MeasurementError("disposable checkout configuration still discloses the measured source")


def _remove_disposable_state(state: Path, source: Path) -> None:
    expected_parent = _state_directory(source).resolve(strict=True)
    junction = getattr(state, "is_junction", None)
    if state.is_symlink() or (junction is not None and junction()):
        raise MeasurementError(f"refusing to clean linked disposable state at {state}")
    canonical = state.resolve(strict=True)
    if canonical.parent != expected_parent or not canonical.name.startswith("measurement-"):
        raise MeasurementError(f"refusing to clean unbound disposable state at {canonical}")

    def make_writable_and_retry(function: object, path: str, _error: object) -> None:
        os.chmod(path, stat.S_IWRITE)
        function(path)  # type: ignore[operator]

    shutil.rmtree(canonical, onerror=make_writable_and_retry)


@contextmanager
def disposable_checkout(
    source: Path,
    revision: str,
    *,
    reverse_rename: tuple[str, str, GitEntry, GitEntry] | None = None,
) -> Iterator[Path]:
    """Yield a verified local checkout and never write the measured source tree."""

    source = source.resolve(strict=True)
    state = Path(tempfile.mkdtemp(prefix="measurement-", dir=_state_directory(source))).resolve(strict=True)
    checkout = state / "checkout"
    preserve = False
    try:
        _run_measurement_command(
            (
                "git",
                "clone",
                "--quiet",
                "--no-hardlinks",
                "--no-checkout",
                str(source),
                str(checkout),
            ),
            root=state,
        )
        _run_measurement_command(("git", "checkout", "--quiet", "--detach", revision), root=checkout)
        observed_head = _git_at(checkout, ["rev-parse", "HEAD"])
        if observed_head.returncode != 0 or observed_head.stdout.strip() != revision:
            raise MeasurementError("disposable checkout did not bind the requested candidate commit")
        status = _git_at(checkout, ["status", "--porcelain=v1", "--untracked-files=all"])
        if status.returncode != 0 or status.stdout.strip():
            raise MeasurementError("fresh disposable candidate checkout is not clean")

        _scrub_clone_source_metadata(checkout, source)
        _materialize_clean_snapshot(checkout, revision, reverse_rename)
        yield checkout
    except UnsettledProcessTree as unsettled:
        preserve = True
        raise UnsettledProcessTree(f"{unsettled}; disposable checkout preserved at {state}") from unsettled
    finally:
        if not preserve:
            try:
                _remove_disposable_state(state, source)
            except OSError as exc:
                raise MeasurementError(f"disposable checkout cleanup failed and was left at {state}: {exc}") from exc


def _validated_suite_selector(root: Path, selector: str) -> str:
    if not selector or any(character in selector for character in "\0\r\n"):
        raise MeasurementError(f"unsafe pytest suite selector {selector!r}")
    path_text, separator, node = selector.partition("::")
    relative = _safe_relative(path_text)
    if relative != "tests" and not relative.startswith("tests/"):
        raise MeasurementError(f"pytest suite selector escapes tests/: {selector!r}")
    target = _checkout_path(root, relative)
    junction = getattr(target, "is_junction", None)
    if (
        not target.exists()
        or target.is_symlink()
        or (junction is not None and junction())
        or not target.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    ):
        raise MeasurementError(f"pytest suite selector is not a confined checkout path: {selector!r}")
    if separator and not node:
        raise MeasurementError(f"pytest suite selector has an empty node: {selector!r}")
    return selector


def _measurement_environment(source_root: Path, checkout_root: Path, run_root: Path) -> dict[str, str]:
    environment = _checkout_environment(checkout_root)
    for key in tuple(environment):
        if key.startswith("GIT_"):
            environment.pop(key)
    for key in ("GITHUB_WORKSPACE", "INIT_CWD", "OLDPWD", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(key, None)

    source_spellings = {str(source_root).casefold(), source_root.as_posix().casefold()}
    for key in ("PYTHONPATH", "PWD"):
        value = environment.get(key, "")
        if any(spelling and spelling in value.casefold() for spelling in source_spellings):
            environment.pop(key, None)

    runtime = run_root / "runtime"
    temporary = run_root / "tmp"
    cache = run_root / "cache"
    pycache = run_root / "pycache"
    for path in (runtime, temporary, cache, pycache):
        path.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "COVERAGE_FILE": str(cache / ".coverage"),
            "CRYODAQ_STATE_ROOT": str(runtime),
            "MPLCONFIGDIR": str(cache / "matplotlib"),
            "NUMBA_CACHE_DIR": str(cache / "numba"),
            "PWD": str(checkout_root),
            "PYTHONPYCACHEPREFIX": str(pycache),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(cache / "xdg"),
        }
    )
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    return environment


def failures(
    suites: list[str],
    run_root: Path,
    *,
    root: Path | None = None,
    source_root: Path | None = None,
) -> list[str]:
    root = (root or repository_root()).resolve(strict=True)
    source_root = (source_root or root).resolve(strict=True)
    environment = _measurement_environment(source_root, root, run_root)
    found: list[str] = []
    for raw_suite in suites:
        suite = _validated_suite_selector(root, raw_suite)
        try:
            run = _run_candidate_process(
                (sys.executable, "-m", "pytest", suite, "-q", "--no-header", "-rf", "-p", "no:cacheprovider"),
                root=root,
                environment=environment,
                capture_output=True,
                timeout=_PYTEST_TIMEOUT_SECONDS,
            )
        except CandidateProcessUnsettledError as exc:
            raise UnsettledProcessTree(f"pytest process tree over {suite!r} did not settle: {exc}") from exc
        except CandidateProcessSettlementError as exc:
            raise MeasurementError(f"pytest process boundary over {suite!r} failed safely: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise MeasurementError(f"pytest over {suite!r} exceeded {_PYTEST_TIMEOUT_SECONDS} seconds") from exc
        stdout = str(run.stdout or "")
        stderr = str(run.stderr or "")
        parsed = [line.split("::")[-1].strip() for line in stdout.splitlines() if line.startswith("FAILED")]
        if run.returncode not in (0, 1) or (run.returncode == 1 and not parsed):
            tail = "\n".join((stdout + stderr).splitlines()[-15:])
            raise MeasurementError(f"pytest over {suite!r} exited {run.returncode} with no readable result:\n{tail}")
        found += parsed
    return found


def fresh_failures(
    suites: list[str],
    *,
    root: Path | None = None,
    source_root: Path | None = None,
) -> list[str]:
    run_root = Path(tempfile.mkdtemp(prefix="unguarded-run-"))
    preserve = False
    try:
        return failures(suites, run_root, root=root, source_root=source_root)
    except UnsettledProcessTree as unsettled:
        preserve = True
        raise UnsettledProcessTree(f"{unsettled}; phase-neutral pytest state preserved at {run_root}") from unsettled
    finally:
        if not preserve:
            try:
                shutil.rmtree(run_root)
            except OSError as exc:
                raise MeasurementError(f"pytest state cleanup failed at {run_root}: {exc}") from exc


def repeated_mutant_failures(
    suites: list[str],
    *,
    root: Path,
    source_root: Path,
    inputs: SuiteInputs,
) -> list[str]:
    first = sorted(set(fresh_failures(suites, root=root, source_root=source_root)))
    assert_suite_inputs_unchanged(inputs, root)
    second = sorted(set(fresh_failures(suites, root=root, source_root=source_root)))
    assert_suite_inputs_unchanged(inputs, root)
    if first != second:
        raise MeasurementError("mutant failures did not repeat exactly on the second run")
    return first


def _measure(options: argparse.Namespace, root: Path) -> int:
    try:
        source_inputs = capture_suite_inputs(root)
    except SuiteInputDrift as drift:
        print(f"REFUSING: source inputs were unstable during candidate capture: {drift}")
        return 2
    if source_inputs.porcelain:
        print("REFUSING: uncommitted candidate inputs cannot be attributed to HEAD:")
        print(source_inputs.porcelain.decode("utf-8", "replace").replace("\0", "\n").rstrip())
        return 2

    head = source_inputs.head
    point = merge_base(options.base, head)
    suites = options.suite or ["tests"]
    includes = tuple(dict.fromkeys((*default_runtime_includes(point, head), *options.include)))
    targets = changed_files(point, head, includes)
    try:
        assert_suite_inputs_unchanged(source_inputs, root)
    except SuiteInputDrift as drift:
        print(f"REFUSING: source inputs drifted during candidate discovery: {drift}")
        return 2
    if not targets:
        print(f"no production artifacts changed against {point[:8]}; nothing to measure")
        return 0

    try:
        with disposable_checkout(root, head) as control_root:
            control_inputs = capture_suite_inputs(control_root)
            control = fresh_failures(
                suites,
                root=control_root,
                source_root=root,
            )
            assert_suite_inputs_unchanged(control_inputs, control_root)
    except UnsettledProcessTree as unsettled:
        print(f"REFUSING: control process tree did not settle: {unsettled}")
        return 2
    except MeasurementError as unreadable:
        print(f"REFUSING: the control run produced no readable result, so nothing can be attributed:\n{unreadable}")
        return 2
    if control:
        print(f"REFUSING: the control run is not green ({len(control)} failing), so no revert can be attributed:")
        for name in sorted(set(control))[:10]:
            print(f"    {name}")
        return 2
    try:
        assert_suite_inputs_unchanged(source_inputs, root)
    except SuiteInputDrift as drift:
        print(f"REFUSING: source inputs drifted after the green control: {drift}")
        return 2

    print(f"control: green over {', '.join(suites)} in a disposable checkout")
    print()
    print("| reverted production artifact | new failures introduced by the revert |")
    print("|---|---|")

    unguarded: list[str] = []
    unmeasured: list[str] = []
    for target in targets:
        try:
            assert_suite_inputs_unchanged(source_inputs, root)
        except SuiteInputDrift as drift:
            print(f"REFUSING: source inputs drifted before mutation attribution: {drift}")
            return 2
        before = git_entry_at(root, point, target.base_path)
        candidate = git_entry_at(root, head, target.candidate_path)
        if before is None or candidate is None or before.content != candidate.content:
            unmeasured.append(target.label)
            print(
                f"| `{target.label}` | **NOT MEASURED** - content changes may contain multiple independent edits; "
                "whole-file reversion cannot attribute them separately |"
            )
            continue
        if before != candidate or target.base_path == target.candidate_path:
            unmeasured.append(target.label)
            print(
                f"| `{target.label}` | **NOT MEASURED** - only an exact-entry rename can be isolated "
                "without writing the source checkout |"
            )
            continue

        old_relative = _safe_relative(str(target.base_path))
        new_relative = _safe_relative(str(target.candidate_path))
        try:
            with disposable_checkout(
                root,
                head,
                reverse_rename=(old_relative, new_relative, before, candidate),
            ) as mutant_root:
                mutant_inputs = capture_suite_inputs(mutant_root)
                mutant_failures = repeated_mutant_failures(
                    suites,
                    root=mutant_root,
                    source_root=root,
                    inputs=mutant_inputs,
                )
            assert_suite_inputs_unchanged(source_inputs, root)
        except UnsettledProcessTree as unsettled:
            print(f"REFUSING: mutant process tree did not settle: {unsettled}")
            return 2
        except SuiteInputDrift as drift:
            print(f"REFUSING: suite inputs drifted during mutation attribution: {drift}")
            return 2
        except MeasurementError as unreadable:
            unmeasured.append(target.label)
            print(f"| `{target.label}` | **NOT MEASURED** - {str(unreadable).splitlines()[0]} |")
            continue

        introduced = sorted(set(mutant_failures) - set(control))
        if introduced:
            try:
                with disposable_checkout(root, head) as confirmation_root:
                    confirmation_inputs = capture_suite_inputs(confirmation_root)
                    restored = fresh_failures(
                        suites,
                        root=confirmation_root,
                        source_root=root,
                    )
                    assert_suite_inputs_unchanged(confirmation_inputs, confirmation_root)
                assert_suite_inputs_unchanged(source_inputs, root)
            except UnsettledProcessTree as unsettled:
                print(f"REFUSING: confirmation process tree did not settle: {unsettled}")
                return 2
            except SuiteInputDrift as drift:
                print(f"REFUSING: source or confirmation inputs drifted: {drift}")
                return 2
            except MeasurementError as unreadable:
                unmeasured.append(target.label)
                print(f"| `{target.label}` | **NOT MEASURED** - {str(unreadable).splitlines()[0]} |")
                continue
            if restored:
                unmeasured.append(target.label)
                print(f"| `{target.label}` | **NOT MEASURED** - fresh candidate confirmation was not green |")
                continue
            print(f"| `{target.label}` | **{len(introduced)} new** - {', '.join(introduced[:3])} |")
        else:
            print(f"| `{target.label}` | **0 new - UNGUARDED** |")
            unguarded.append(target.label)

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
    print("every isolated production artifact introduced a new failure")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--include", action="append", default=[])
    options = parser.parse_args()

    root = repository_root().resolve(strict=True)
    try:
        return _measure(options, root)
    except MeasurementError as unsafe:
        print(f"REFUSING: production-file measurement did not complete safely: {unsafe}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
