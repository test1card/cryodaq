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
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

INVENTORY_PATH = Path("tests/governance/guard_coverage_inventory.json")
_STABLE_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]*-\d{3}$")


class GuardCoverageError(RuntimeError):
    """The comparison could not establish guard coverage."""


_GIT_REDIRECT_ENVIRONMENT_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _git_environment() -> dict[str, str]:
    """Return a sanitized process environment for one Git authority boundary.

    This mirrors the production G4 source-control authority in
    ``tests/docs/test_docs_freshness.py::_g4_is_source_controlled``: an
    inherited ``GIT_DIR``, ``GIT_WORK_TREE``, object-directory, namespace, or
    ``GIT_CONFIG_*`` injection can redirect a command into a second
    repository's object database, so a weakened requested repository
    false-passes against a strong one. The full redirect surface is cleared
    while the ordinary environment needed to locate the ``git`` executable and
    the operating system (``PATH``, ``SystemRoot``, ...) is preserved.
    Object replacement is already disabled per-command via
    ``--no-replace-objects``, so a ``GIT_REPLACE_REF_DIR`` redirect cannot
    substitute an ancestor tree either.
    """

    environment = os.environ.copy()
    for key in _GIT_REDIRECT_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    for key in tuple(environment):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(key, None)
    return environment


def _verify_repository(repo: Path) -> None:
    """Fail closed unless ``rev-parse`` resolves the requested repository exactly.

    Equivalent to the production G4 authority boundary: the requested
    repository is verified once, before any revision resolution, because every
    later ``_git``/``_git_file`` call reuses this one sanitized boundary. An
    unavailable top-level, an ambiguous resolution, or a foreign resolved root
    is unavailable evidence and never an implicit pass.
    """

    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        env=_git_environment(),
        check=False,
    )
    if completed.returncode:
        stderr = completed.stderr.strip()
        raise GuardCoverageError(
            "guard coverage requires the requested repository to resolve exactly; "
            f"rev-parse --show-toplevel failed: {stderr or 'top-level unavailable'}"
        )
    resolved = completed.stdout.strip()
    if not resolved or Path(resolved).resolve() != repo:
        raise GuardCoverageError(
            "guard coverage requires the requested repository to resolve exactly; "
            f"{repo} resolved to {resolved or '<empty>'}"
        )


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


def _git(repo: Path, *arguments: str, text: bool = True) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            capture_output=True,
            text=text,
            check=False,
            env=_git_environment(),
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


def _resolve(repo: Path, revision: str) -> str:
    return str(_git(repo, "--no-replace-objects", "rev-parse", "--verify", f"{revision}^{{commit}}")).strip()


def _git_file(repo: Path, revision: str, path: Path) -> bytes | None:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "show", f"{revision}:{path.as_posix()}"],
        cwd=repo,
        capture_output=True,
        check=False,
        env=_git_environment(),
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
    repo: Path,
    base: str,
    candidate: str,
    inventory_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_path = repo / inventory_path
    try:
        bootstrap_raw = runtime_path.read_bytes()
    except OSError as exc:
        raise GuardCoverageError(f"bootstrap inventory is unavailable: {runtime_path}") from exc
    bootstrap = _load_inventory(bootstrap_raw, "bootstrap")
    base_raw = _git_file(repo, base, inventory_path)
    candidate_raw = _git_file(repo, candidate, inventory_path)
    if base_raw is None and candidate_raw is None:
        return bootstrap, bootstrap
    if base_raw is None:
        candidate_inventory = _load_inventory(candidate_raw, candidate)
        return candidate_inventory, candidate_inventory
    base_inventory = _load_inventory(base_raw, base)
    if candidate_raw is None:
        return base_inventory, {"schema_version": 1, "guards": {}, "reduction_declarations": []}
    return base_inventory, _load_inventory(candidate_raw, candidate)


def _materialize(repo: Path, revision: str, destination: Path) -> None:
    archive = _git(repo, "--no-replace-objects", "archive", "--format=tar", revision, text=False)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(destination, filter="data")


def _revision_source_controlled(repo: Path, revision: str, relative_path: str) -> bool:
    """Resolve one path against the exact revision tree behind an exported root."""

    output = _git(
        repo,
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
    repo: Path,
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
                    lambda relative_path: _revision_source_controlled(repo, revision, relative_path),
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
    if guard_id == "C2-DESCRIPTOR-SELECTION":
        for key, value in getattr(module, "_ALLOWLIST", {}).items():
            if not isinstance(key, tuple) or len(key) != 2:
                descriptors.append({"kind": "c2_allowlist", "path": "<malformed>", "symbol": "<malformed>"})
                continue
            path, line = key
            purpose = value[0] if isinstance(value, tuple) else value
            symbol = _symbol_at_line(revision_root / path, int(line))
            descriptors.append(
                {
                    "kind": "c2_allowlist",
                    "path": str(path),
                    "symbol": symbol,
                    "purpose": str(purpose),
                }
            )
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
    return {_descriptor_id(descriptor, catalog) for descriptor in descriptors}


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
    _verify_repository(repo)
    base = _resolve(repo, base_revision)
    candidate = _resolve(repo, candidate_revision)
    base_inventory, candidate_inventory = _inventories(repo, base, candidate, inventory_path)
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
        _materialize(repo, base, base_root)
        _materialize(repo, candidate, candidate_root)

        for guard_id in sorted(base_guards.keys() | candidate_guards.keys()):
            base_guard = base_guards.get(guard_id)
            candidate_guard = candidate_guards.get(guard_id)
            authoritative = base_guard or candidate_guard
            if authoritative is None:
                continue
            guard_path = authoritative["path"]
            lost: list[str] = []
            for challenge_id, challenge in (base_guard or authoritative)["challenges"].items():
                base_result = _run_challenge(repo, base, base_root, guard_path, challenge_id, challenge, "base")
                if not base_result.passed and base_result.detail.startswith("guard error:"):
                    raise GuardCoverageError(f"base challenge failed: {guard_id}:{challenge_id}: {base_result.detail}")
                candidate_result = _run_challenge(
                    repo,
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
