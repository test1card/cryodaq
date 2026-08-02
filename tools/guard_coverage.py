"""Reject undeclared guard-coverage reductions between two Git revisions.

This tool intentionally runs in the exact Git checkout, not an exported
candidate: both revisions and their trees are read from the local object
database.  The tracked inventory declares executable challenges and stable
semantic exemption IDs.  Commit messages are never consulted.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

INVENTORY_PATH = Path("tests/governance/guard_coverage_inventory.json")
_STABLE_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]*-\d{3}$")


class GuardCoverageError(RuntimeError):
    """The comparison could not establish guard coverage."""


@contextmanager
def _git_environment(*, neutralize_history: bool = True) -> Iterator[dict[str, str]]:
    """Yield a comparator-owned environment for one Git authority boundary.

    This mirrors the production G4 source-control authority in
    ``tests/docs/test_docs_freshness.py::_g4_is_source_controlled``. The
    comparator, not its caller, owns repository, revision, object, history, and
    configuration authority. Every inherited ``GIT_*`` variable is removed
    rather than attempting to enumerate Git's growing environment surface.
    Comparator-owned empty graft and shallow files also override their
    repository-local defaults; otherwise ``.git/info/grafts`` or
    ``.git/shallow`` can rewrite ancestry without changing the repository
    top-level. System/global configuration is replaced with an empty file.

    The ordinary environment needed to locate ``git`` and the operating system
    (``PATH``, ``SystemRoot``, ...) is preserved. Object replacement is also
    disabled per-command via ``--no-replace-objects`` as defense in depth.
    """

    with tempfile.TemporaryDirectory(prefix="cryodaq-guard-git-authority-") as temporary:
        authority_root = Path(temporary)
        empty_config = authority_root / "config"
        empty_grafts = authority_root / "grafts"
        empty_shallow = authority_root / "shallow"
        for path in (empty_config, empty_grafts, empty_shallow):
            path.write_bytes(b"")

        environment = os.environ.copy()
        for key in tuple(environment):
            if key.upper().startswith("GIT_"):
                environment.pop(key, None)
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": str(empty_config),
                "GIT_CONFIG_GLOBAL": str(empty_config),
            }
        )
        if neutralize_history:
            environment.update(
                {
                    "GIT_GRAFT_FILE": str(empty_grafts),
                    "GIT_SHALLOW_FILE": str(empty_shallow),
                    "GIT_REPLACE_REF_BASE": "refs/guard-coverage-disabled-replacements/",
                }
            )
        yield environment


@dataclass(frozen=True)
class RepositoryAuthority:
    """One immutable worktree, Git directory, and common-directory binding."""

    worktree: Path
    git_dir: Path
    common_dir: Path
    marker: Path
    marker_bytes: bytes | None
    backpointer_bytes: bytes | None
    commondir_bytes: bytes | None


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise GuardCoverageError(f"repository authority path is unavailable: {path}") from exc
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse)


def _read_authority_file(path: Path, label: str) -> bytes:
    if _is_link_or_reparse(path) or not path.is_file():
        raise GuardCoverageError(f"repository {label} authority is not a regular file")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise GuardCoverageError(f"repository {label} authority is unreadable") from exc
    if not payload or b"\0" in payload:
        raise GuardCoverageError(f"repository {label} authority is malformed")
    return payload


def _authority_line(payload: bytes, label: str, *, prefix: str | None = None) -> str:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GuardCoverageError(f"repository {label} authority is not UTF-8") from exc
    if len(lines) != 1 or not lines[0].strip():
        raise GuardCoverageError(f"repository {label} authority is malformed")
    value = lines[0]
    if prefix is not None:
        if not value.startswith(prefix) or not value[len(prefix) :].strip():
            raise GuardCoverageError(f"repository {label} authority is malformed")
        value = value[len(prefix) :]
    return value


def _declared_path(base: Path, value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise GuardCoverageError(f"repository {label} authority path is unavailable") from exc


def _assert_real_directory_components(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise GuardCoverageError(f"repository {label} authority path is not absolute")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if _is_link_or_reparse(current) or not current.is_dir():
            raise GuardCoverageError(f"repository {label} authority is not a real directory")


def _assert_repository_authority(authority: RepositoryAuthority) -> None:
    """Prove the filesystem registration still matches the bound Git authority."""

    marker = authority.marker
    _assert_real_directory_components(authority.worktree, "requested worktree")
    if authority.marker_bytes is None:
        _assert_real_directory_components(marker, "direct Git")
        if not marker.is_dir():
            raise GuardCoverageError("repository direct Git authority is not a real directory")
        if marker.resolve(strict=True) != authority.git_dir or authority.common_dir != authority.git_dir:
            raise GuardCoverageError("repository direct Git authority is inconsistent")
        return

    _assert_real_directory_components(authority.common_dir, "common-directory")
    _assert_real_directory_components(authority.git_dir, "linked Git")
    worktrees_dir = authority.common_dir / "worktrees"
    if authority.common_dir == authority.git_dir:
        raise GuardCoverageError("repository linked-worktree authority requires a distinct common directory")
    if authority.git_dir.parent != worktrees_dir or not authority.git_dir.name:
        raise GuardCoverageError("repository linked-worktree authority is not registered under its common directory")
    _assert_real_directory_components(worktrees_dir, "linked-worktree registration")
    _assert_real_directory_components(marker.parent, "worktree marker")
    if _read_authority_file(marker, "worktree marker") != authority.marker_bytes:
        raise GuardCoverageError("repository worktree marker authority changed")
    marker_target = _declared_path(
        marker.parent,
        _authority_line(authority.marker_bytes, "worktree marker", prefix="gitdir: "),
        "worktree marker",
    )
    if marker_target != authority.git_dir:
        raise GuardCoverageError("repository worktree marker does not bind the discovered Git directory")

    backpointer = authority.git_dir / "gitdir"
    commondir = authority.git_dir / "commondir"
    if authority.backpointer_bytes is None or authority.commondir_bytes is None:
        raise GuardCoverageError("repository linked-worktree authority is incomplete")
    if _read_authority_file(backpointer, "Git-directory backpointer") != authority.backpointer_bytes:
        raise GuardCoverageError("repository Git-directory backpointer authority changed")
    if _read_authority_file(commondir, "common-directory pointer") != authority.commondir_bytes:
        raise GuardCoverageError("repository common-directory authority changed")
    backpointer_target = _declared_path(
        authority.git_dir,
        _authority_line(authority.backpointer_bytes, "Git-directory backpointer"),
        "Git-directory backpointer",
    )
    common_target = _declared_path(
        authority.git_dir,
        _authority_line(authority.commondir_bytes, "common-directory pointer"),
        "common-directory pointer",
    )
    try:
        marker_target_root = marker.resolve(strict=True)
    except OSError as exc:
        raise GuardCoverageError("repository worktree marker authority is unavailable") from exc
    if backpointer_target != marker_target_root or common_target != authority.common_dir:
        raise GuardCoverageError("repository linked-worktree authority is inconsistent")


def _repository_authority(repo: Path) -> RepositoryAuthority:
    """Discover and bind one self-consistent repository before revision lookup."""

    with _git_environment() as environment:
        completed = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-C",
                str(repo),
                "rev-parse",
                "--is-inside-work-tree",
                "--show-toplevel",
                "--path-format=absolute",
                "--absolute-git-dir",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
    if completed.returncode:
        stderr = completed.stderr.strip()
        raise GuardCoverageError(
            "guard coverage requires one self-consistent repository authority; "
            f"Git discovery failed: {stderr or 'repository unavailable'}"
        )
    values = completed.stdout.splitlines()
    if len(values) != 4 or values[0] != "true":
        raise GuardCoverageError("guard coverage requires one worktree-bound repository authority")
    try:
        discovered_top_level = Path(values[1])
        discovered_git_dir = Path(values[2])
        discovered_common_dir = Path(values[3])
        _assert_real_directory_components(discovered_top_level, "requested worktree")
        _assert_real_directory_components(discovered_git_dir, "Git")
        _assert_real_directory_components(discovered_common_dir, "common-directory")
        top_level = discovered_top_level.resolve(strict=True)
        git_dir = discovered_git_dir.resolve(strict=True)
        common_dir = discovered_common_dir.resolve(strict=True)
    except OSError as exc:
        raise GuardCoverageError("repository discovery returned an unavailable authority path") from exc
    if top_level != repo or not git_dir.is_dir() or not common_dir.is_dir():
        raise GuardCoverageError("repository discovery does not bind the exact requested worktree")

    marker = repo / ".git"
    marker_bytes: bytes | None = None
    backpointer_bytes: bytes | None = None
    commondir_bytes: bytes | None = None
    marker_is_reparse = _is_link_or_reparse(marker)
    if marker.is_file() and not marker_is_reparse:
        marker_bytes = _read_authority_file(marker, "worktree marker")
        try:
            backpointer_bytes = _read_authority_file(git_dir / "gitdir", "Git-directory backpointer")
            commondir_bytes = _read_authority_file(git_dir / "commondir", "common-directory pointer")
        except GuardCoverageError as exc:
            raise GuardCoverageError("repository linked-worktree authority is incomplete") from exc
    elif not marker.is_dir() or marker_is_reparse:
        raise GuardCoverageError("repository .git authority is not a regular directory or file")
    authority = RepositoryAuthority(
        worktree=repo,
        git_dir=git_dir,
        common_dir=common_dir,
        marker=marker,
        marker_bytes=marker_bytes,
        backpointer_bytes=backpointer_bytes,
        commondir_bytes=commondir_bytes,
    )
    _assert_repository_authority(authority)
    return authority


@dataclass(frozen=True)
class ChallengeResult:
    passed: bool
    detail: str


@dataclass(frozen=True)
class Comparison:
    base: str
    candidate: str
    reductions: tuple[dict[str, Any], ...]
    approved: tuple[str, ...]
    gains: tuple[str, ...]
    removed_exemptions: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.reductions


def _git(
    authority: RepositoryAuthority,
    *arguments: str,
    text: bool = True,
    neutralize_history: bool = True,
) -> str | bytes:
    try:
        with _git_environment(neutralize_history=neutralize_history) as environment:
            completed = subprocess.run(
                [
                    "git",
                    f"--git-dir={authority.git_dir}",
                    f"--work-tree={authority.worktree}",
                    *arguments,
                ],
                cwd=authority.worktree,
                capture_output=True,
                text=text,
                check=False,
                env=environment,
            )
    except OSError as exc:
        raise GuardCoverageError(
            "guard coverage requires an exact Git checkout and the requested objects; no comparison was performed"
        ) from exc
    if completed.returncode:
        stderr = completed.stderr.strip() if text else completed.stderr.decode(errors="replace").strip()
        raise GuardCoverageError(
            "guard coverage requires an exact Git checkout and the requested objects; "
            f"git {' '.join(arguments)} failed: {stderr or 'object unavailable'}"
        )
    return completed.stdout


def _preflight_repository_authority(authority: RepositoryAuthority) -> None:
    """Reject repository-local state that can reinterpret revision authority.

    The immutable authority already proves the exact requested worktree and
    explicitly binds every Git call to its registered Git directory. Active
    graft, shallow, or replacement state instead changes the commit graph
    itself. That is unavailable comparison evidence, so reject it before
    resolving either requested revision.
    """

    for label, relative in (("graft", "info/grafts"), ("shallow", "shallow")):
        raw_path = str(
            _git(
                authority,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                relative,
                neutralize_history=False,
            )
        ).strip()
        if not raw_path:
            raise GuardCoverageError(f"repository-local Git {label} authority path is unavailable")
        path = Path(raw_path)
        try:
            active = path.is_file() and bool(path.read_bytes().strip())
        except OSError as exc:
            raise GuardCoverageError(f"repository-local Git {label} authority is unreadable") from exc
        if active:
            raise GuardCoverageError(f"repository-local Git {label} authority is active")

    replacements = str(
        _git(
            authority,
            "--no-replace-objects",
            "for-each-ref",
            "--format=%(refname)",
            "refs/replace/",
            neutralize_history=False,
        )
    ).strip()
    if replacements:
        raise GuardCoverageError("repository-local Git replacement authority is active")


def _resolve(authority: RepositoryAuthority, revision: str) -> str:
    return str(_git(authority, "--no-replace-objects", "rev-parse", "--verify", f"{revision}^{{commit}}")).strip()


def _git_file(authority: RepositoryAuthority, revision: str, path: Path) -> bytes | None:
    with _git_environment() as environment:
        completed = subprocess.run(
            [
                "git",
                f"--git-dir={authority.git_dir}",
                f"--work-tree={authority.worktree}",
                "--no-replace-objects",
                "show",
                f"{revision}:{path.as_posix()}",
            ],
            cwd=authority.worktree,
            capture_output=True,
            check=False,
            env=environment,
        )
    if completed.returncode:
        return None
    return completed.stdout


def _load_inventory(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardCoverageError(f"{label} guard-coverage inventory is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "guards",
        "reduction_declarations",
    }:
        raise GuardCoverageError(f"{label} guard-coverage inventory has an unexpected shape")
    if payload["schema_version"] != 1 or not isinstance(payload["guards"], dict):
        raise GuardCoverageError(f"{label} guard-coverage inventory schema is unsupported")
    if not isinstance(payload["reduction_declarations"], list):
        raise GuardCoverageError(f"{label} reduction declarations are not a list")
    for guard_id, guard in payload["guards"].items():
        if not _STABLE_ID_RE.fullmatch(f"{guard_id}-000"):
            raise GuardCoverageError(f"{label} guard ID is not stable: {guard_id!r}")
        if not isinstance(guard, dict) or set(guard) != {"path", "challenges", "exemptions"}:
            raise GuardCoverageError(f"{label} guard inventory is malformed: {guard_id}")
        if not isinstance(guard["path"], str) or not guard["path"].startswith("tests/"):
            raise GuardCoverageError(f"{label} guard path is not repository-relative: {guard_id}")
        for field in ("challenges", "exemptions"):
            entries = guard[field]
            if not isinstance(entries, dict):
                raise GuardCoverageError(f"{label} {guard_id}.{field} is not an ID mapping")
            for stable_id, spec in entries.items():
                if not _STABLE_ID_RE.fullmatch(stable_id) or not isinstance(spec, dict):
                    raise GuardCoverageError(f"{label} {guard_id}.{field} has an unstable ID")
                if "line" in spec or "lineno" in spec:
                    raise GuardCoverageError(f"{label} {stable_id} uses forbidden line-number identity")
    return payload


def _inventories(
    authority: RepositoryAuthority,
    base: str,
    candidate: str,
    inventory_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_path = authority.worktree / inventory_path
    try:
        bootstrap_raw = runtime_path.read_bytes()
    except OSError as exc:
        raise GuardCoverageError(f"bootstrap inventory is unavailable: {runtime_path}") from exc
    bootstrap = _load_inventory(bootstrap_raw, "bootstrap")
    base_raw = _git_file(authority, base, inventory_path)
    candidate_raw = _git_file(authority, candidate, inventory_path)
    if base_raw is None and candidate_raw is None:
        return bootstrap, bootstrap
    if base_raw is None:
        candidate_inventory = _load_inventory(candidate_raw, candidate)
        return candidate_inventory, candidate_inventory
    base_inventory = _load_inventory(base_raw, base)
    if candidate_raw is None:
        return base_inventory, {"schema_version": 1, "guards": {}, "reduction_declarations": []}
    return base_inventory, _load_inventory(candidate_raw, candidate)


def _materialize(authority: RepositoryAuthority, revision: str, destination: Path) -> None:
    archive = _git(authority, "--no-replace-objects", "archive", "--format=tar", revision, text=False)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(destination, filter="data")


def _revision_source_controlled(
    authority: RepositoryAuthority,
    revision: str,
    relative_path: str,
) -> bool:
    """Resolve one path against the exact revision tree behind an exported root."""

    output = _git(
        authority,
        "--no-replace-objects",
        "--literal-pathspecs",
        "ls-tree",
        "-z",
        "--full-tree",
        revision,
        "--",
        relative_path,
        text=False,
    )
    if not output:
        return False
    entries = output.split(b"\0")
    if entries[-1] == b"":
        entries.pop()
    expected = relative_path.encode("utf-8")
    paths = [entry.split(b"\t", 1)[1] for entry in entries if b"\t" in entry]
    if len(entries) != 1 or paths != [expected]:
        raise GuardCoverageError(f"committed tree lookup returned ambiguous evidence for {relative_path}")
    return True


def _load_module(root: Path, relative: str, suffix: str) -> ModuleType | None:
    path = root / relative
    if not path.is_file():
        return None
    name = f"_guard_coverage_{suffix}_{abs(hash((str(path), suffix)))}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GuardCoverageError(f"cannot load guard module {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe_root(revision_root: Path, challenge_id: str) -> Path:
    root = revision_root / ".guard-coverage-probes" / challenge_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _invoke_g4_docs_validator(
    module: ModuleType,
    revision_root: Path,
    overrides: Mapping[str, str],
    source_controlled: Callable[[str], bool],
) -> None:
    """Invoke current or archived G4 validators without guessing from exceptions."""

    validator = getattr(module, "_validate_g4_docs", None)
    if not callable(validator):
        raise GuardCoverageError("G4 guard module has no callable _validate_g4_docs")
    try:
        validator_signature = inspect.signature(validator)
    except (TypeError, ValueError) as exc:
        raise GuardCoverageError("G4 validator signature is unavailable") from exc

    try:
        validator_signature.bind(
            revision_root,
            overrides,
            source_controlled=source_controlled,
        )
    except TypeError:
        try:
            validator_signature.bind(revision_root, overrides)
        except TypeError as exc:
            raise GuardCoverageError(f"unsupported archived G4 validator signature: {validator_signature}") from exc

        historical_authority = getattr(module, "_g4_is_source_controlled", None)
        if not callable(historical_authority):
            raise GuardCoverageError("pre-signature G4 validator has no callable _g4_is_source_controlled capability")
        try:
            inspect.signature(historical_authority).bind(revision_root, "probe")
        except (TypeError, ValueError) as exc:
            raise GuardCoverageError("pre-signature G4 source-control capability has an unsupported signature") from exc

        expected_root = revision_root.resolve()

        def archived_source_controlled(root: Path, relative_path: str) -> bool:
            if root.resolve() != expected_root:
                raise GuardCoverageError("archived G4 validator requested source control for a foreign root")
            return source_controlled(relative_path)

        module._g4_is_source_controlled = archived_source_controlled
        try:
            validator(revision_root, overrides)
        finally:
            module._g4_is_source_controlled = historical_authority
        return

    validator(
        revision_root,
        overrides,
        source_controlled=source_controlled,
    )


def _run_challenge(
    authority: RepositoryAuthority,
    revision: str,
    revision_root: Path,
    guard_path: str,
    challenge_id: str,
    challenge: Mapping[str, Any],
    suffix: str,
) -> ChallengeResult:
    module = _load_module(revision_root, guard_path, f"{suffix}_{challenge_id}")
    if module is None:
        return ChallengeResult(False, "guard file is absent")
    kind = challenge.get("kind")
    expected = challenge.get("expected")
    if not isinstance(expected, str) or not expected:
        raise GuardCoverageError(f"{challenge_id} has no exact expected finding")
    try:
        if kind == "c2_source":
            root = _probe_root(revision_root, challenge_id)
            target = root / "src" / "cryodaq" / "reporting" / "probe.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(challenge["source"]), encoding="utf-8", newline="\n")
            findings = module._violations(root)
            passed = any(expected in finding for finding in findings)
            return ChallengeResult(passed, expected if passed else f"missing finding: {expected}")
        if kind == "c1_source":
            root = _probe_root(revision_root, challenge_id)
            target = root / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters" / "probe.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(challenge["source"]), encoding="utf-8", newline="\n")
            findings = module._violations(root)
            passed = any(expected in finding for finding in findings)
            return ChallengeResult(passed, expected if passed else f"missing finding: {expected}")
        if kind == "g4_external_as_software":
            checklist_path = revision_root / "docs" / "new_lab_acceptance_checklist.md"
            checklist = checklist_path.read_text(encoding="utf-8")
            mutated = checklist.replace("result: PHYSICAL", "result: SOFTWARE-PROVABLE", 1)
            if mutated == checklist:
                return ChallengeResult(False, "physical procedure fixture is unavailable")
            try:
                _invoke_g4_docs_validator(
                    module,
                    revision_root,
                    {"docs/new_lab_acceptance_checklist.md": mutated},
                    lambda relative_path: _revision_source_controlled(authority, revision, relative_path),
                )
            except AssertionError as exc:
                passed = expected in str(exc)
                return ChallengeResult(passed, expected if passed else f"wrong rejection: {exc}")
            return ChallengeResult(False, f"missing rejection: {expected}")
        if kind == "source_off_source":
            root = _probe_root(revision_root, challenge_id)
            target = root / "tests" / "probe.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(challenge["source"]), encoding="utf-8", newline="\n")
            module._TESTS_ROOT = root / "tests"
            module._THIS_FILE = revision_root / guard_path
            try:
                module.test_driver_level_emergency_off_doubles_return_source_off_result()
            except AssertionError as exc:
                passed = expected in str(exc)
                return ChallengeResult(passed, expected if passed else f"wrong rejection: {exc}")
            return ChallengeResult(False, f"missing rejection: {expected}")
    except Exception as exc:  # a broken guard is a failed challenge, never a pass
        return ChallengeResult(False, f"guard error: {type(exc).__name__}: {exc}")
    raise GuardCoverageError(f"{challenge_id} uses unsupported challenge kind {kind!r}")


def _symbol_at_line(path: Path, line: int) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches: list[tuple[int, str]] = []

    def visit(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = node.end_lineno or node.lineno
                name = f"{prefix}{node.name}"
                if node.lineno <= line <= end:
                    matches.append((end - node.lineno, name))
                if isinstance(node, ast.ClassDef):
                    visit(node.body, f"{name}.")

    visit(tree.body)
    return min(matches)[1] if matches else "<module>"


def _descriptor_id(
    descriptor: Mapping[str, str],
    catalog: tuple[tuple[str, Mapping[str, Any]], ...],
) -> str:
    for exemption_id, spec in catalog:
        if all(descriptor.get(key) == value for key, value in spec.items()):
            return exemption_id
    detail = ",".join(f"{key}={value}" for key, value in sorted(descriptor.items()))
    return f"UNDECLARED[{detail}]"


def _catalog(
    base_guard: Mapping[str, Any] | None,
    candidate_guard: Mapping[str, Any] | None,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    variants: list[tuple[str, Mapping[str, Any]]] = []
    for guard in (base_guard, candidate_guard):
        if guard is None:
            continue
        for exemption_id, spec in guard["exemptions"].items():
            item = (exemption_id, spec)
            if item not in variants:
                variants.append(item)
    return tuple(variants)


def _has_dict_annotation_skip(path: Path) -> bool:
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not any(isinstance(item, ast.Continue) for item in node.body):
            continue
        for call in (item for item in ast.walk(node.test) if isinstance(item, ast.Call)):
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "startswith"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "annotation"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "dict["
            ):
                return True
    return False


def _actual_exemptions(
    revision_root: Path,
    guard_id: str,
    guard_path: str,
    catalog: tuple[tuple[str, Mapping[str, Any]], ...],
    suffix: str,
) -> set[str]:
    module = _load_module(revision_root, guard_path, f"{suffix}_exemptions")
    if module is None:
        return set()
    descriptors: list[dict[str, str]] = []
    undeclared_descriptors: list[dict[str, str]] = []
    if guard_id == "C2-DESCRIPTOR-SELECTION":
        allowlist = getattr(module, "_ALLOWLIST", {})
        if isinstance(allowlist, Mapping):
            allowlist_items = allowlist.items()
        elif isinstance(allowlist, (set, frozenset)):
            # The current guard intentionally has no exemptions and represents
            # that state as ``frozenset()``. If a later set-shaped guard adds
            # an entry, it has no purpose field with which to match a tracked
            # descriptor, so surface it as undeclared instead of granting an
            # exemption by shape alone.
            allowlist_items = ((key, None) for key in allowlist)
        else:
            raise GuardCoverageError(f"C2 allowlist has unsupported shape: {type(allowlist).__name__}")
        for key, value in allowlist_items:
            if not isinstance(key, tuple) or len(key) != 2:
                descriptors.append({"kind": "c2_allowlist", "path": "<malformed>", "symbol": "<malformed>"})
                continue
            path, line = key
            purpose = value[0] if isinstance(value, tuple) else value
            symbol = _symbol_at_line(revision_root / path, int(line))
            descriptor = {
                "kind": "c2_allowlist",
                "path": str(path),
                "symbol": symbol,
                "purpose": ("set-shaped allowlist entry has no declared purpose" if purpose is None else str(purpose)),
            }
            if purpose is None:
                undeclared_descriptors.append(descriptor)
            else:
                descriptors.append(descriptor)
    elif guard_id == "C1-ENGINE-ADAPTER-SEAL":
        for locator in getattr(module, "_KNOWN_PRODUCTION_VIOLATIONS", {}):
            filename, symbol, *_rest = str(locator).split(":", 3)
            descriptors.append(
                {
                    "kind": "c1_known_violation",
                    "path": f"src/cryodaq/agents/assistant/query/adapters/{filename}",
                    "symbol": symbol,
                    "purpose": "empty experiment identifier absence contract",
                }
            )
    elif guard_id == "SOURCE-OFF-RESULT-DOUBLES":
        for path, symbol in getattr(module, "_INTENTIONAL_INVALID_SCOPES", set()):
            descriptors.append(
                {
                    "kind": "source_off_scope",
                    "path": f"tests/{path}",
                    "symbol": str(symbol),
                    "purpose": "intentional invalid result",
                }
            )
        if _has_dict_annotation_skip(revision_root / guard_path):
            descriptors.append(
                {
                    "kind": "source_off_dict_annotation_skip",
                    "path": guard_path,
                    "symbol": "test_driver_level_emergency_off_doubles_return_source_off_result",
                    "purpose": "dict-annotated emergency_off bypass",
                }
            )
    return {
        *(_descriptor_id(descriptor, catalog) for descriptor in descriptors),
        *(_descriptor_id(descriptor, ()) for descriptor in undeclared_descriptors),
    }


def _inventory_changes(
    base_guard: Mapping[str, Any] | None,
    candidate_guard: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if base_guard is None:
        return {
            "removed_challenge_inventory_ids": [],
            "changed_challenge_inventory_ids": [],
            "removed_exemption_inventory_ids": [],
            "changed_exemption_inventory_ids": [],
            "guard_definition_changed": False,
        }
    candidate_guard = candidate_guard or {"path": None, "challenges": {}, "exemptions": {}}
    base_challenges = base_guard["challenges"]
    candidate_challenges = candidate_guard["challenges"]
    base_exemptions = base_guard["exemptions"]
    candidate_exemptions = candidate_guard["exemptions"]
    return {
        "removed_challenge_inventory_ids": sorted(base_challenges.keys() - candidate_challenges.keys()),
        "changed_challenge_inventory_ids": sorted(
            key
            for key in base_challenges.keys() & candidate_challenges.keys()
            if base_challenges[key] != candidate_challenges[key]
        ),
        "removed_exemption_inventory_ids": sorted(base_exemptions.keys() - candidate_exemptions.keys()),
        "changed_exemption_inventory_ids": sorted(
            key
            for key in base_exemptions.keys() & candidate_exemptions.keys()
            if base_exemptions[key] != candidate_exemptions[key]
        ),
        "guard_definition_changed": base_guard["path"] != candidate_guard["path"],
    }


def _declaration_matches(declaration: Any, event: Mapping[str, Any]) -> bool:
    if not isinstance(declaration, dict):
        return False
    required = set(event) | {"id", "status", "reviewer", "reason"}
    return (
        set(declaration) == required
        and declaration.get("status") == "approved"
        and isinstance(declaration.get("reviewer"), str)
        and bool(declaration["reviewer"].strip())
        and isinstance(declaration.get("reason"), str)
        and bool(declaration["reason"].strip())
        and all(declaration.get(key) == value for key, value in event.items())
        and _STABLE_ID_RE.fullmatch(str(declaration.get("id", ""))) is not None
    )


def compare(
    repo: Path,
    base_revision: str,
    candidate_revision: str,
    *,
    inventory_path: Path = INVENTORY_PATH,
) -> Comparison:
    repo = repo.resolve(strict=True)
    authority = _repository_authority(repo)
    _preflight_repository_authority(authority)
    base = _resolve(authority, base_revision)
    candidate = _resolve(authority, candidate_revision)
    base_inventory, candidate_inventory = _inventories(authority, base, candidate, inventory_path)
    base_guards = base_inventory["guards"]
    candidate_guards = candidate_inventory["guards"]
    reductions: list[dict[str, Any]] = []
    approved: list[str] = []
    gains: list[str] = []
    removed_exemptions: list[str] = []

    with tempfile.TemporaryDirectory(prefix=".guard-coverage-", dir=repo) as temporary:
        temporary_root = Path(temporary)
        base_root = temporary_root / "base"
        candidate_root = temporary_root / "candidate"
        base_root.mkdir()
        candidate_root.mkdir()
        _materialize(authority, base, base_root)
        _materialize(authority, candidate, candidate_root)

        for guard_id in sorted(base_guards.keys() | candidate_guards.keys()):
            base_guard = base_guards.get(guard_id)
            candidate_guard = candidate_guards.get(guard_id)
            authoritative = base_guard or candidate_guard
            if authoritative is None:
                continue
            guard_path = authoritative["path"]
            lost: list[str] = []
            for challenge_id, challenge in (base_guard or authoritative)["challenges"].items():
                base_result = _run_challenge(authority, base, base_root, guard_path, challenge_id, challenge, "base")
                if not base_result.passed and base_result.detail.startswith("guard error:"):
                    raise GuardCoverageError(f"base challenge failed: {guard_id}:{challenge_id}: {base_result.detail}")
                candidate_result = _run_challenge(
                    authority,
                    candidate,
                    candidate_root,
                    guard_path,
                    challenge_id,
                    challenge,
                    "candidate",
                )
                if base_result.passed and not candidate_result.passed:
                    lost.append(challenge_id)
                elif not base_result.passed and candidate_result.passed:
                    gains.append(f"{guard_id}:{challenge_id}")

            catalog = _catalog(base_guard, candidate_guard)
            base_exemptions = _actual_exemptions(base_root, guard_id, guard_path, catalog, "base")
            candidate_exemptions = _actual_exemptions(
                candidate_root,
                guard_id,
                guard_path,
                catalog,
                "candidate",
            )
            added = sorted(candidate_exemptions - base_exemptions)
            removed_exemptions.extend(
                f"{guard_id}:{exemption_id}" for exemption_id in sorted(base_exemptions - candidate_exemptions)
            )
            inventory_changes = _inventory_changes(base_guard, candidate_guard)
            event = {
                "base_commit": base,
                "guard_id": guard_id,
                "lost_challenge_ids": sorted(lost),
                "added_exemption_ids": added,
                **inventory_changes,
            }
            reducing = (
                event["lost_challenge_ids"]
                or event["added_exemption_ids"]
                or event["removed_challenge_inventory_ids"]
                or event["changed_challenge_inventory_ids"]
                or event["removed_exemption_inventory_ids"]
                or event["changed_exemption_inventory_ids"]
                or event["guard_definition_changed"]
            )
            if not reducing:
                continue
            declaration = next(
                (item for item in candidate_inventory["reduction_declarations"] if _declaration_matches(item, event)),
                None,
            )
            if declaration is None:
                reductions.append(event)
            else:
                approved.append(str(declaration["id"]))

    _assert_repository_authority(authority)
    return Comparison(
        base=base,
        candidate=candidate,
        reductions=tuple(reductions),
        approved=tuple(sorted(approved)),
        gains=tuple(sorted(gains)),
        removed_exemptions=tuple(sorted(removed_exemptions)),
    )


def _print_result(result: Comparison) -> None:
    if result.reductions:
        print(f"guard coverage regression: {result.base}..{result.candidate}", file=sys.stderr)
        for event in result.reductions:
            print(f"- {event['guard_id']}", file=sys.stderr)
            for field in (
                "lost_challenge_ids",
                "added_exemption_ids",
                "removed_challenge_inventory_ids",
                "changed_challenge_inventory_ids",
                "removed_exemption_inventory_ids",
                "changed_exemption_inventory_ids",
            ):
                for stable_id in event[field]:
                    print(f"  {field}: {stable_id}", file=sys.stderr)
            if event["guard_definition_changed"]:
                print("  guard_definition_changed: true", file=sys.stderr)
        print(
            "coverage reductions require an exact tracked declaration with status=approved, "
            "reviewer, reason, and the computed event fields",
            file=sys.stderr,
        )
        return
    print(f"guard coverage comparison passed: {result.base}..{result.candidate}")
    for declaration_id in result.approved:
        print(f"approved reduction: {declaration_id}")
    for gain in result.gains:
        print(f"gained challenge: {gain}")
    for exemption in result.removed_exemptions:
        print(f"removed exemption: {exemption}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    args = parser.parse_args(argv)
    try:
        result = compare(
            args.repo,
            args.base,
            args.candidate,
            inventory_path=args.inventory,
        )
    except GuardCoverageError as exc:
        print(f"guard coverage unavailable: {exc}", file=sys.stderr)
        return 2
    _print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
