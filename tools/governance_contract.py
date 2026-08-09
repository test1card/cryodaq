"""Fail-closed validator for the AI-first prevention registry."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ID = re.compile(r"[A-Z0-9][A-Z0-9-]*")
_NODE = re.compile(r"tests/[A-Za-z0-9_./-]+\.py::[A-Za-z0-9_\[\].:-]+")
_SCOPES = {"repository", "product_contract", "campaign_local"}
_STATUSES = {"open", "reopened", "closed", "expired"}
_OWNERS = {"reviewer", "primary", "cli", "each_agent"}
_PENDING = {"pending", "pending_immutable_capture"}
_PLATFORMS = {"posix", "windows"}
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_IMMUTABLE_LOCATOR = re.compile(r"(?:git|tree|github-run|artifact|bundle|red-reproduction):\S+")
_RED_REPRODUCTION_LOCATOR = re.compile(
    r"red-reproduction:governance/red_reproductions/[A-Za-z0-9][A-Za-z0-9_.-]*\.json"
)
_RED_REPRODUCTION_PROVENANCE = "local-executed-red-reproduction; lower provenance than sealed hosted CI"
_EXPECTED_STATUS_DEFINITIONS = {
    "open": "Required correction or evidence is incomplete.",
    "reopened": "A previously disposed invariant lost, weakened, skipped, or misbound enforcement.",
    "closed": "Invariant and guard are green with immutable reviewer-bound evidence.",
    "expired": "Campaign-local coordination no longer applies after its named expiry and immutable final disposition.",
}
_EXPECTED_SCOPE_DEFINITIONS = {
    "repository": "Universal developer-agent, evidence, review, or publication invariant.",
    "product_contract": "Durable CryoDAQ runtime or test invariant independent of the current campaign mechanics.",
    "campaign_local": "Temporary branch, worktree, lane, ordering, freeze, or completion rule with an explicit expiry.",
}
_EXPECTED_OWNERSHIP_SEMANTICS = {
    "correction_owner": (
        "Default durable role that maintains the affected runtime, governance, evidence, or integration state "
        "outside an active campaign override."
    ),
    "guard_owner": (
        "Default durable implementation role that maintains the machine-testable guard outside an active campaign "
        "override."
    ),
    "disposition_owner": "Reviewer; no author self-closes its correction or guard.",
    "campaign_edit_owner_override": (
        "Exact campaign-local path or node assignment that supersedes durable owners for authoring only and expires "
        "with the campaign."
    ),
    "edit_owner_precedence": (
        "Active exact campaign override, then durable owner; every active path and guard node resolves to exactly one "
        "editor."
    ),
    "allowed_owners": ["reviewer", "primary", "cli", "each_agent"],
}
_EXPECTED_CAMPAIGN_EXPIRY_SEMANTICS = {
    "required_terminal_status": "expired",
    "immutable_final_disposition": "required",
    "history_retention": "permanent_non_authoritative",
    "may_authorize_after_expiry": False,
}
_EXPECTED_DEFAULT_CI_JOBS = {
    "core": ["test (ubuntu-latest, core)", "test (windows-latest, core)"],
    "gui": ["test (ubuntu-latest, gui)", "test (windows-latest, gui)"],
    "agents": ["test (ubuntu-latest, agents)", "test (windows-latest, agents)"],
    "remaining": ["test (ubuntu-latest, remaining)", "test (windows-latest, remaining)"],
}
_EXPECTED_FALSE_GREEN_PAIR_SEMANTICS = {
    "status": "required_and_linked",
    "scope": "inherited_from_runtime_prevention_id",
    "guard_identity": "exact_runtime_guard_link",
    "correction_owner": "inherited_from_runtime_prevention_id",
    "guard_owner": "inherited_from_runtime_prevention_id",
    "disposition_owner": "reviewer",
    "close_requires_runtime_closed": True,
    "close_requires_immutable_red_and_green_evidence": True,
    # Green evidence names a MERGED head, which cannot exist before the merge it
    # would gate, so requiring it to close made `open` permanent by
    # construction. It is now appended by the post-merge sweep, and `pending` on
    # an otherwise satisfied record neither reopens it nor blocks a disposition.
    # The RED half is unchanged and still required before merge.
    #
    # NO COUNT IS RECORDED HERE. An earlier version cited "364 of 368 pairs",
    # which was already false in the tree that shipped it -- the number moves
    # with every PR, and a validator is the worst place to freeze one. Anyone
    # who wants the current figure should count it from the registry rather
    # than read it here: load the YAML and count entries whose
    # `green_evidence` is `pending` against the total.
    "green_evidence_bound_post_merge_by_sweep": True,
    "pending_green_evidence_blocks_disposition": False,
    "guard_removed_skipped_xfailed_deselected_or_nondefault": "reopen",
}
# The SAME post-merge evidence semantics, for runtime prevention records. The
# first version of this change declared them only for false-green pairs, while
# the registry's runtime records carry `green_evidence: pending` in bulk for the
# identical structural reason -- so the deadlock fix covered the bookkeeping and
# not the above-floor preventions whose disposition the rule also unblocks.
_EXPECTED_RECORD_EVIDENCE_SEMANTICS = {
    "green_evidence_bound_post_merge_by_sweep": True,
    "pending_green_evidence_blocks_disposition": False,
}
_CLASSIFICATION_CORPUS_REPEAT_THRESHOLD = 2
_PUBLICATION_DISPOSITION_RECEIPTS_PATH = Path("governance/publication_disposition_receipts.json")
_PUBLICATION_DISPOSITIONS = frozenset({"approved", "not_approved"})
_PUBLICATION_REVIEW_MANDATES = frozenset({"depth-and-delta", "BREADTH"})
_PUBLICATION_REVIEW_VERDICTS = frozenset({"approved", "do_not_approve"})
_PUBLICATION_REVIEWER_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_PUBLICATION_BINDING_FIELDS = frozenset({"commit", "tree", "base_commit", "diff_sha256", "path_manifest_sha256"})
_PUBLICATION_REVIEWER_FIELDS = frozenset(
    {"identity", "mandate", "distinct_context", "verdict", "disagreements"} | _PUBLICATION_BINDING_FIELDS
)


class GovernanceContractError(ValueError):
    """Raised when prevention evidence could silently lose enforcement."""


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernanceContractError(f"{field} must be a nonempty string")
    return value


def closure_semantics_sha256(entry: Mapping[str, Any]) -> str:
    """Digest the exact semantics that immutable closure evidence disposes."""

    excluded = {"status", "red_evidence", "green_evidence", "closure_semantics_sha256"}
    semantic = {key: entry[key] for key in sorted(entry) if key not in excluded}
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def disposition_state(record: Mapping[str, Any]) -> str:
    """Derive the record's lifecycle state, so `pending` is not one bucket.

    `record_evidence_semantics` declares that green evidence is appended after
    merge by a batch sweep and that its absence blocks nothing. A consumer could
    not act on that: a record whose correction and guard are done and is merely
    waiting for the sweep looked exactly like one where nothing has been built --
    both are `status: open` with `green_evidence: pending`. Anything enforcing
    the declaration had to guess, so the declaration was unenforceable.

    Derived, never stored, so it cannot drift from the record it describes:

    * ``closed`` / ``expired`` -- terminal, and already required to carry
      immutable evidence on both sides.
    * ``awaiting_green_sweep`` -- open, guards registered, red-before captured,
      and only the post-merge green capture outstanding. This is the state the
      semantics call non-blocking.
    * ``incomplete`` -- open with the correction or its guard still missing.
      This one genuinely holds a disposition open.
    """

    status = record.get("status")
    if status in {"closed", "expired"}:
        return str(status)
    # `reopened` is an ACTIVE status, not a third thing. Measured on the live
    # registry: statuses are `open` (85) and `reopened` (5), and a reopened
    # record is in exactly the same position as an open one -- its correction is
    # either built and guarded or it is not. An earlier version of this function
    # recognised only `open` and reported every reopened record `unknown`, which
    # would have made the very state this derivation exists to expose
    # unreadable for them.
    if status not in {"open", "reopened"}:
        return "unknown"
    red = record.get("red_evidence")
    green = record.get("green_evidence")
    if not (record.get("guards") and red and red != "pending"):
        return "incomplete"
    # Measured on the live registry: SEVEN active records already carry captured
    # green evidence. They are not waiting for the sweep -- it has run for them,
    # and they stay open for their own residual reasons. Folding them into
    # `awaiting_green_sweep` would have told a consumer to expect a capture that
    # already happened, so they get their own state rather than a convenient
    # bucket.
    if green and green != "pending":
        return "evidence_complete"
    return "awaiting_green_sweep"


def _validate_immutable_evidence(value: Any, field: str) -> None:
    if not isinstance(value, Mapping):
        raise GovernanceContractError(f"{field} immutable evidence shape is not exact")
    locator = value.get("locator")
    digest = value.get("sha256")
    is_artifact = isinstance(locator, str) and locator.startswith("artifact:")
    if isinstance(locator, str) and locator.startswith("bundle:"):
        # The aggregate bundle acquired a schema but never a seal. Nothing in
        # this tree produces one, and nothing resolves or verifies its
        # contents, so its declared tree and suite list are an assertion the
        # validator has no way to check. Accepting it would let a record close
        # on unverifiable evidence, which is the exact failure this registry
        # exists to prevent. The unsupported form fails closed until a producer
        # AND a validator for it exist.
        raise GovernanceContractError(
            f"{field} bundle evidence is not accepted: no aggregate-bundle producer or validator "
            "exists in this tree, so its declared tree and suites cannot be verified"
        )
    required_fields = {"locator", "sha256", "tree", "suite"} if is_artifact else {"locator", "sha256"}
    if set(value) != required_fields:
        if is_artifact:
            raise GovernanceContractError(f"{field} artifact evidence shape is not exact")
        raise GovernanceContractError(f"{field} immutable evidence shape is not exact")
    if not isinstance(locator, str) or _IMMUTABLE_LOCATOR.fullmatch(locator) is None:
        raise GovernanceContractError(f"{field} immutable evidence locator is invalid")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise GovernanceContractError(f"{field} immutable evidence digest is invalid")
    if is_artifact:
        if not isinstance(value["tree"], str) or _GIT_OBJECT_ID.fullmatch(value["tree"]) is None:
            raise GovernanceContractError(f"{field} artifact evidence tree is invalid")
        if value["suite"] not in _EXPECTED_DEFAULT_CI_JOBS:
            raise GovernanceContractError(f"{field} artifact evidence suite is invalid")


def _validate_evidence_partition(value: Any, partitions: set[str], field: str, *, required_for_closure: bool) -> None:
    """Require a closure's sealed evidence to cover EVERY registered guard partition.

    One sealed artifact is the record of one partition's execution, so mere
    membership is too weak: a record whose guards span ``agents``/``core``/
    ``gui``/``remaining`` was satisfiable by a single ``core`` artifact, which
    says nothing about the other three. The schema allows one locator per
    entry, so a multi-partition record cannot be closed on a single artifact at
    all.  Covering one would take an immutable aggregate bundle whose sealed
    tree and exact suite list span every required partition, and this tree has
    no producer and no validator for that form -- so a multi-partition record
    cannot be closed at all today, and the refusal says exactly that instead of
    accepting an assertion it cannot check.  Red evidence keeps the old
    permissive treatment for non-artifact locators: it records the failure
    reproduction, rather than claiming the green test coverage that closes the
    record.
    """

    locator = value.get("locator") if isinstance(value, Mapping) else None
    is_artifact = isinstance(value, Mapping) and isinstance(locator, str) and locator.startswith("artifact:")
    if is_artifact:
        suite = value["suite"]
        if partitions != {suite}:
            uncovered = sorted(partitions - {suite})
            raise GovernanceContractError(
                f"{field} artifact evidence attests only suite {suite!r} but its registered guards "
                f"span {sorted(partitions)}; uncovered partitions: {uncovered}"
            )
    elif required_for_closure and len(partitions) > 1:
        raise GovernanceContractError(
            f"{field} cannot close multi-partition guards {sorted(partitions)}: one sealed artifact "
            "attests one partition, and no verifiable aggregate-bundle evidence form exists"
        )


_OPTIONAL_RECORD_FIELDS = frozenset(
    {
        "expires_when",
        "expiry_disposition",
        "closure_semantics_sha256",
        "campaign_edit_owner_overrides",
        "campaign_guard_authorship",
        "proposal_guard_scope",
        "human_gate",
        "automation_limit",
        "guard_source_blobs",
        "classification_corpus",
    }
)


def _validate_campaign_edit_owner_overrides(value: Any, record_id: str) -> None:
    field = f"{record_id}.campaign_edit_owner_overrides"
    if not isinstance(value, list) or not value:
        raise GovernanceContractError(f"{field} must be a nonempty list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"edit_owner", "path"}:
            raise GovernanceContractError(f"{field}[{index}] shape is not exact")
        if item["edit_owner"] not in _OWNERS:
            raise GovernanceContractError(f"{field}[{index}].edit_owner is invalid")
        _nonempty(item["path"], f"{field}[{index}].path")


def _validate_campaign_guard_authorship(value: Any, record_id: str) -> None:
    field = f"{record_id}.campaign_guard_authorship"
    required_keys = {
        "author",
        "path_source",
        "implementation_worker_guard_authoring",
        "reviewer_product_authoring",
        "freeze_requires_worker_test_path_manifest",
        "independent_guard_review",
        "expires_when",
    }
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise GovernanceContractError(f"{field} shape is not exact")
    if value["author"] not in _OWNERS:
        raise GovernanceContractError(f"{field}.author is invalid")
    for key in (
        "path_source",
        "implementation_worker_guard_authoring",
        "reviewer_product_authoring",
        "independent_guard_review",
        "expires_when",
    ):
        _nonempty(value[key], f"{field}.{key}")
    if not isinstance(value["freeze_requires_worker_test_path_manifest"], bool):
        raise GovernanceContractError(f"{field}.freeze_requires_worker_test_path_manifest must be a boolean")


def _validate_proposal_guard_scope(value: Any, record_id: str) -> None:
    field = f"{record_id}.proposal_guard_scope"
    required_keys = {"combined_montana", "final_candidate", "lane_completion", "lane_proposal"}
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise GovernanceContractError(f"{field} shape is not exact")
    for key in required_keys:
        _nonempty(value[key], f"{field}.{key}")


def _validate_classification_corpus(value: Any, record_id: str) -> tuple[str, ...]:
    """Validate a class-level disposition for recurring prevention shapes.

    Two is deliberately the first observed recurrence: the registry currently
    contains five classifications with exactly two records and none with three.
    Waiting for a third instance would preserve the instance-by-instance escape
    that the corpus rule prohibits.
    """

    field = f"{record_id}.classification_corpus"
    if not isinstance(value, Mapping) or set(value) != {"repeat_threshold", "covered_classifications"}:
        raise GovernanceContractError(f"{field} shape is not exact")
    if value["repeat_threshold"] != _CLASSIFICATION_CORPUS_REPEAT_THRESHOLD:
        raise GovernanceContractError(
            f"{field}.repeat_threshold must be the observed first-recurrence threshold "
            f"{_CLASSIFICATION_CORPUS_REPEAT_THRESHOLD}"
        )
    classifications = value["covered_classifications"]
    if (
        not isinstance(classifications, list)
        or not classifications
        or classifications != sorted(set(classifications))
        or any(not isinstance(item, str) or not item.strip() for item in classifications)
    ):
        raise GovernanceContractError(f"{field}.covered_classifications must be a sorted unique nonempty list")
    return tuple(classifications)


def _validate_guard(guard: Any, partitions: set[str]) -> None:
    if not isinstance(guard, Mapping) or set(guard) not in (
        {"node", "ci_partition"},
        {"node", "ci_partition", "platform"},
    ):
        raise GovernanceContractError("guard shape is not exact")
    node = guard["node"]
    if not isinstance(node, str) or "[" in node or "]" in node or _NODE.fullmatch(node) is None:
        raise GovernanceContractError(f"guard node is not exact and collectable: {node!r}")
    if guard["ci_partition"] not in partitions:
        raise GovernanceContractError("guard is not assigned to a default CI partition")
    if "platform" in guard and guard["platform"] not in _PLATFORMS:
        raise GovernanceContractError("guard platform is not exact")


def _git_blob_id(raw: bytes) -> str:
    """Return the Git blob identity, matching ci_candidate_evidence's framing."""

    framed = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(framed).hexdigest()


def _repository_has_git_metadata(git_repository: Path | None) -> bool:
    """Does the repository UNDER VALIDATION carry Git metadata at all?

    A SEALED CANDIDATE is an exported tree with no ``.git`` whatsoever, so object
    binding there is not merely unverified, it is unverifiable -- and failing on it
    kills every partition before it can report anything. That is different from a
    repository that HAS Git but lacks a named object: there the absence is a real
    finding and must still be refused, which is why this asks about metadata rather
    than about whether some commit happens to resolve.

    *** This asks about the repository under validation, NEVER about where this
    module happens to live. Keying it on ``__file__`` is exactly what made the
    protected evidence path unrunnable. The ordinary run imports these tools from
    the sealed export, which has no ``.git``, so resolution was skipped. The
    protected run imports the SAME tools from the JUDGE checkout, which IS a
    repository, so resolution switched on and then hunted for the CANDIDATE's
    objects inside the judge's object database, where they cannot exist. Identical
    code, identical data, opposite outcome, decided purely by an import path. ***
    """

    return git_repository is not None and (git_repository / ".git").exists()


def _git_object_id(git_repository: Path, revision: str, *, kind: str, field: str) -> str:
    """Resolve one Git object in the repository under validation, or fail.

    ``git_repository`` is the candidate's real checkout, deliberately distinct from
    the materialized tree used for file reads: a sealed export carries the bytes but
    none of the history, so the two authorities cannot be collapsed into one.
    """

    revision_to_resolve = revision if ":" in revision else f"{revision}^{{{kind}}}"
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", revision_to_resolve],
        cwd=git_repository,
        capture_output=True,
        check=False,
    )
    resolved = completed.stdout.decode("ascii", errors="replace").strip()
    if completed.returncode != 0 or _GIT_OBJECT_ID.fullmatch(resolved) is None:
        raise GovernanceContractError(f"{field} does not resolve to a local Git {kind} object")
    typed = subprocess.run(
        ["git", "cat-file", "-e", f"{resolved}^{{{kind}}}"],
        cwd=git_repository,
        capture_output=True,
        check=False,
    )
    if typed.returncode != 0:
        raise GovernanceContractError(f"{field} does not resolve to a local Git {kind} object")
    return resolved


def _git_stdout(git_repository: Path, arguments: list[str], *, field: str) -> bytes:
    """Return raw Git object-database output without filesystem or text normalisation."""

    completed = subprocess.run(
        ["git", *arguments],
        cwd=git_repository,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GovernanceContractError(f"{field} could not be recomputed from the candidate repository")
    return completed.stdout


def _validate_publication_binding(value: Mapping[str, Any], *, field: str, git_repository: Path) -> dict[str, str]:
    binding = {key: value.get(key) for key in _PUBLICATION_BINDING_FIELDS}
    if any(not isinstance(item, str) for item in binding.values()):
        raise GovernanceContractError(f"{field} Git object and range binding is missing")
    commit = binding["commit"]
    tree = binding["tree"]
    base_commit = binding["base_commit"]
    assert isinstance(commit, str) and isinstance(tree, str) and isinstance(base_commit, str)
    if any(_GIT_OBJECT_ID.fullmatch(item) is None for item in (commit, tree, base_commit)):
        raise GovernanceContractError(f"{field} Git object and range binding is invalid")
    for digest_field in ("diff_sha256", "path_manifest_sha256"):
        digest = binding[digest_field]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise GovernanceContractError(f"{field}.{digest_field} is invalid")

    resolved_commit = _git_object_id(git_repository, commit, kind="commit", field=f"{field}.commit")
    resolved_tree = _git_object_id(git_repository, resolved_commit, kind="tree", field=f"{field}.tree")
    if tree != resolved_tree:
        raise GovernanceContractError(f"{field}.tree does not match its resolved commit")
    resolved_base = _git_object_id(git_repository, base_commit, kind="commit", field=f"{field}.base_commit")
    if resolved_base == resolved_commit:
        raise GovernanceContractError(f"{field}.base commit must differ from its candidate commit")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", resolved_base, resolved_commit],
        cwd=git_repository,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise GovernanceContractError(f"{field}.base_commit is not an ancestor of its candidate commit")

    diff = _git_stdout(
        git_repository,
        [
            "-c",
            "diff.orderFile=",
            "diff-tree",
            "--no-commit-id",
            "--raw",
            "-r",
            "-z",
            "--no-renames",
            "--abbrev=40",
            resolved_base,
            resolved_commit,
        ],
        field=f"{field}.diff_sha256",
    )
    paths = _git_stdout(
        git_repository,
        [
            "-c",
            "diff.orderFile=",
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-z",
            "--no-renames",
            resolved_base,
            resolved_commit,
        ],
        field=f"{field}.path_manifest_sha256",
    )
    if not diff or not paths:
        raise GovernanceContractError(f"{field} candidate range has no complete diff")
    for digest_field, raw in (("diff_sha256", diff), ("path_manifest_sha256", paths)):
        actual = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if binding[digest_field] != actual:
            raise GovernanceContractError(f"{field}.{digest_field} does not match the resolved candidate range")
    return {
        "commit": commit,
        "tree": tree,
        "base_commit": base_commit,
        "diff_sha256": binding["diff_sha256"],
        "path_manifest_sha256": binding["path_manifest_sha256"],
    }


def _decode_receipt_bytes(value: Any, digest: Any, field: str) -> bytes:
    if not isinstance(value, str) or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise GovernanceContractError(f"{field} bytes or SHA-256 digest is invalid")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise GovernanceContractError(f"{field} bytes are not valid base64") from exc
    actual = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if actual != digest:
        raise GovernanceContractError(f"{field} digest does not match its recorded bytes")
    return raw


def _validate_red_reproduction_evidence(
    value: Any,
    *,
    entry_id: str,
    guard_nodes: set[str],
    root: Path,
    git_repository: Path | None = None,
    require_git_resolution: bool = False,
) -> None:
    """Validate an executed local red receipt bound to Git and current guard bytes.

    This is intentionally a local-execution provenance tier, not a substitute
    for the sealed hosted-CI green artifact required to close a prevention.

    Two distinct authorities, which must not be conflated:

    ``root``
        the materialized tree the receipt's files are read from. A sealed export.
    ``git_repository``
        the candidate's real checkout, used ONLY to resolve Git objects. ``None``
        when no history is available.

    ``require_git_resolution`` makes the caller's expectation explicit and
    FAIL-CLOSED. The protected evidence path sets it, because there the candidate
    checkout is always present and a silent downgrade to "no history, skip object
    resolution" would hand back exactly the weaker check the protected path exists
    to strengthen. An unset flag preserves the sealed-export behaviour, where the
    absence of history is a fact about the tree rather than a missing input.
    """

    if require_git_resolution and not _repository_has_git_metadata(git_repository):
        raise GovernanceContractError(
            f"{entry_id}.red_evidence requires Git object resolution but no candidate "
            "repository was supplied; refusing to downgrade to an unresolved check"
        )

    if not isinstance(value, Mapping) or not isinstance(value.get("locator"), str):
        return
    locator = value["locator"]
    if not locator.startswith("red-reproduction:"):
        return
    if _RED_REPRODUCTION_LOCATOR.fullmatch(locator) is None:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction locator is invalid")
    if set(value) != {"locator", "sha256"}:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction evidence shape is not exact")
    digest = value["sha256"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction receipt digest is invalid")
    receipt_path = root / locator.removeprefix("red-reproduction:")
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as exc:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction receipt is unavailable") from exc
    if f"sha256:{hashlib.sha256(receipt_bytes).hexdigest()}" != digest:
        raise GovernanceContractError(f"{entry_id}.red_evidence receipt bytes digest does not match its locator")
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction receipt is not valid JSON") from exc

    required = {
        "schema_version",
        "record_ids",
        "provenance",
        "defective_commit",
        "defective_tree",
        "defective_source_blobs",
        "guard_blobs",
        "command",
        "environment",
        "python_version",
        "exit_code",
        "guard_nodes",
        "failed_nodes",
        "failure_signatures",
        "stdout_bytes_base64",
        "stdout_sha256",
        "stderr_bytes_base64",
        "stderr_sha256",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required or receipt["schema_version"] != 1:
        raise GovernanceContractError(f"{entry_id}.red_evidence red-reproduction receipt shape is not exact")
    record_ids = receipt["record_ids"]
    if (
        not isinstance(record_ids, list)
        or record_ids != sorted(set(record_ids))
        or any(not isinstance(item, str) or _ID.fullmatch(item) is None for item in record_ids)
        or entry_id not in record_ids
    ):
        raise GovernanceContractError(f"{entry_id}.red_evidence receipt is not bound to this prevention id")
    if receipt["provenance"] != _RED_REPRODUCTION_PROVENANCE:
        raise GovernanceContractError(f"{entry_id}.red_evidence receipt provenance is not explicitly local-executed")
    commit = receipt["defective_commit"]
    tree = receipt["defective_tree"]
    if not isinstance(commit, str) or not isinstance(tree, str) or _GIT_OBJECT_ID.fullmatch(commit) is None:
        raise GovernanceContractError(f"{entry_id}.red_evidence defective commit is invalid")
    # Only OBJECT RESOLUTION needs Git. Every other fact in this receipt -- exit
    # code, node equality, failure signatures, output digests, guard bytes -- is
    # verifiable from the receipt and the tree alone, and MUST be enforced in a
    # sealed candidate, which has no `.git`. An earlier revision returned here
    # when Git was absent and silently skipped all of it, so the sealed candidate
    # accepted a forged receipt. That is the failure mode docs/DECISIONS.md:165-173
    # forbids by name: a Git-dependent check is RELOCATED, never turned into a pass.
    resolvable = _repository_has_git_metadata(git_repository)
    resolved_commit = None
    if resolvable:
        assert git_repository is not None  # narrowed by _repository_has_git_metadata
        resolved_commit = _git_object_id(
            git_repository, commit, kind="commit", field=f"{entry_id}.red_evidence defective commit"
        )
        resolved_tree = _git_object_id(
            git_repository, resolved_commit, kind="tree", field=f"{entry_id}.red_evidence defective tree"
        )
        if tree != resolved_tree:
            raise GovernanceContractError(f"{entry_id}.red_evidence defective tree does not match its defective commit")
    source_blobs = receipt["defective_source_blobs"]
    if not isinstance(source_blobs, Mapping) or not source_blobs:
        raise GovernanceContractError(f"{entry_id}.red_evidence defective source blobs are missing")
    for path, blob in source_blobs.items():
        if (
            not isinstance(path, str)
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or not isinstance(blob, str)
            or _GIT_OBJECT_ID.fullmatch(blob) is None
        ):
            raise GovernanceContractError(f"{entry_id}.red_evidence defective source blob binding is invalid")
        if resolved_commit is None or git_repository is None:
            continue
        resolved_blob = _git_object_id(
            git_repository,
            f"{resolved_commit}:{path}",
            kind="blob",
            field=f"{entry_id}.red_evidence defective source blob {path}",
        )
        if blob != resolved_blob:
            raise GovernanceContractError(f"{entry_id}.red_evidence defective source blob does not match its tree")
    receipt_guard_blobs = receipt["guard_blobs"]
    expected_paths = {node.split("::", 1)[0] for node in guard_nodes}
    if not isinstance(receipt_guard_blobs, Mapping) or set(receipt_guard_blobs) != expected_paths:
        raise GovernanceContractError(f"{entry_id}.red_evidence receipt guard blobs do not bind its guard files")
    for path, expected_blob in receipt_guard_blobs.items():
        if not isinstance(expected_blob, str) or _GIT_OBJECT_ID.fullmatch(expected_blob) is None:
            raise GovernanceContractError(f"{entry_id}.red_evidence receipt guard blob is invalid")
        try:
            actual_blob = _git_blob_id((root / path).read_bytes())
        except OSError as exc:
            raise GovernanceContractError(f"{entry_id}.red_evidence registry guard file is unavailable") from exc
        if actual_blob != expected_blob:
            raise GovernanceContractError(
                f"{entry_id}.red_evidence receipt guard blob does not match registry guard file"
            )
    command = receipt["command"]
    environment = receipt["environment"]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
        or not isinstance(environment, Mapping)
        or not environment
        or any(not isinstance(key, str) or not isinstance(item, str) for key, item in environment.items())
        or not isinstance(environment.get("PYTHONPATH"), str)
        or not isinstance(receipt["python_version"], str)
        or not receipt["python_version"].strip()
    ):
        raise GovernanceContractError(f"{entry_id}.red_evidence command or environment is not exact")
    if not isinstance(receipt["exit_code"], int) or receipt["exit_code"] == 0:
        raise GovernanceContractError(f"{entry_id}.red_evidence red reproduction exit code indicates success")
    receipt_nodes = receipt["guard_nodes"]
    failed_nodes = receipt["failed_nodes"]
    if (
        not isinstance(receipt_nodes, list)
        or receipt_nodes != sorted(set(receipt_nodes))
        or not receipt_nodes
        or not set(receipt_nodes) <= guard_nodes
        or failed_nodes != receipt_nodes
    ):
        raise GovernanceContractError(
            f"{entry_id}.red_evidence failure signatures do not name selected registered guard nodes"
        )
    stdout = _decode_receipt_bytes(receipt["stdout_bytes_base64"], receipt["stdout_sha256"], f"{entry_id}.stdout")
    stderr = _decode_receipt_bytes(receipt["stderr_bytes_base64"], receipt["stderr_sha256"], f"{entry_id}.stderr")
    signatures = receipt["failure_signatures"]
    output = (stdout + stderr).decode("utf-8", errors="replace")
    if not isinstance(signatures, Mapping) or set(signatures) != set(receipt_nodes):
        raise GovernanceContractError(
            f"{entry_id}.red_evidence failure signatures do not include registered guard nodes"
        )
    for node, lines in signatures.items():
        if (
            not isinstance(lines, list)
            or not lines
            or any(
                not isinstance(line, str) or not line.startswith("FAILED ") or node not in line or line not in output
                for line in lines
            )
        ):
            raise GovernanceContractError(
                f"{entry_id}.red_evidence failure signatures do not include registered guard nodes"
            )


def _validate_guard_source_blobs(
    value: Any,
    *,
    entry_id: str,
    guard_nodes: set[str],
    root: Path,
) -> None:
    """Bind every closed guard file to its bytes at the evidence's attested tree.

    A sealed candidate has no Git metadata, so the registry records a Git blob
    identity rather than requiring a lookup at the evidence tree.  The current
    exported bytes must still match it; a mismatch means enforcement changed
    and requires an explicit reopened disposition.
    """

    field = f"{entry_id}.guard_source_blobs"
    expected_paths = {node.split("::", 1)[0] for node in guard_nodes}
    if not isinstance(value, Mapping) or set(value) != expected_paths:
        raise GovernanceContractError(f"{field} must bind exactly its covered guard files")
    for path, expected_blob in value.items():
        if not isinstance(expected_blob, str) or _GIT_OBJECT_ID.fullmatch(expected_blob) is None:
            raise GovernanceContractError(f"{field}.{path} is not a Git blob identity")
        source = root / path
        # The registry's existing collectability and strict-execution guards
        # reject an absent test file.  This content binding adds the distinct
        # in-place weakening check when the covered source is present.
        if not source.is_file():
            continue
        try:
            actual_blob = _git_blob_id(source.read_bytes())
        except OSError as exc:
            raise GovernanceContractError(f"{entry_id} covered guard source is unavailable; reopen it") from exc
        if actual_blob != expected_blob:
            raise GovernanceContractError(
                f"{entry_id} guard-source-blob-mismatch path={path} expected={expected_blob} actual={actual_blob}; "
                "restore it or reopen the prevention"
            )


def validate_publication_disposition_receipts(
    root: Path,
    *,
    git_repository: Path | None = None,
) -> dict[str, Any]:
    """Validate typed, fail-closed publication-review dispositions.

    Receipts are intentionally separate from the prevention registry: registry
    records are durable rules, while a receipt is a changing fact about one
    publication candidate.  Keeping them separate prevents a new candidate
    from changing a prevention rule merely to record its review outcome.
    """

    if not _repository_has_git_metadata(git_repository):
        raise GovernanceContractError(
            "publication disposition validation requires an explicit candidate repository; "
            "refusing unresolved Git object checks"
        )
    assert git_repository is not None

    path = root / _PUBLICATION_DISPOSITION_RECEIPTS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceContractError("publication disposition receipts are unavailable or invalid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "receipts"}:
        raise GovernanceContractError("publication disposition receipts top-level schema is not exact")
    if payload["schema_version"] != 2 or not isinstance(payload["receipts"], list) or not payload["receipts"]:
        raise GovernanceContractError("publication disposition receipts are missing or invalid")

    receipt_ids: set[str] = set()
    for receipt in payload["receipts"]:
        if not isinstance(receipt, Mapping) or set(receipt) != {
            "id",
            "disposition",
            "attestation",
            "reviewers",
        }:
            raise GovernanceContractError("publication disposition receipt shape is not exact")
        receipt_id = _nonempty(receipt["id"], "publication disposition receipt id")
        if _ID.fullmatch(receipt_id) is None or receipt_id in receipt_ids:
            raise GovernanceContractError("publication disposition receipt id is invalid or duplicate")
        receipt_ids.add(receipt_id)
        disposition = receipt["disposition"]
        if disposition not in _PUBLICATION_DISPOSITIONS:
            raise GovernanceContractError(f"{receipt_id}.disposition is invalid")
        attestation = receipt["attestation"]
        if not isinstance(attestation, Mapping) or set(attestation) != {
            "subject",
            "independent_contexts",
            *_PUBLICATION_BINDING_FIELDS,
        }:
            raise GovernanceContractError(f"{receipt_id}.attestation shape is not exact")
        _nonempty(attestation["subject"], f"{receipt_id}.attestation.subject")
        if attestation["independent_contexts"] is not True:
            raise GovernanceContractError(f"{receipt_id}.attestation.independent_contexts must be true")
        binding = _validate_publication_binding(
            attestation,
            field=f"{receipt_id}.attestation",
            git_repository=git_repository,
        )

        reviewers = receipt["reviewers"]
        if not isinstance(reviewers, list) or len(reviewers) < 2:
            raise GovernanceContractError(f"{receipt_id} requires at least two reviewers")
        identities: list[str] = []
        mandates: set[str] = set()
        verdicts: list[str] = []
        for index, reviewer in enumerate(reviewers):
            field = f"{receipt_id}.reviewers[{index}]"
            if not isinstance(reviewer, Mapping) or set(reviewer) != _PUBLICATION_REVIEWER_FIELDS:
                raise GovernanceContractError(
                    f"{field} must name identity, mandate, distinct_context, verdict, disagreements, and exact binding"
                )
            identity = _nonempty(reviewer["identity"], f"{field}.identity")
            # Identities must be a constrained ASCII token. A reviewer differing only by
            # a homoglyph is not independent, and normalisation does NOT catch that:
            # NFKC folds compatibility variants, but a Cyrillic capital rendering like a
            # Latin one is a genuinely distinct character it leaves alone. Restricting the
            # charset defeats the whole confusable family by construction instead.
            if _PUBLICATION_REVIEWER_IDENTITY.fullmatch(identity) is None:
                raise GovernanceContractError(f"{field}.identity must be a plain ASCII identity token")
            identities.append(identity.casefold())
            mandate = reviewer["mandate"]
            if mandate not in _PUBLICATION_REVIEW_MANDATES:
                raise GovernanceContractError(f"{field}.mandate is missing or unknown")
            mandates.add(mandate)
            if reviewer["distinct_context"] is not True:
                raise GovernanceContractError(f"{field}.distinct_context must attest true")
            if {key: reviewer[key] for key in _PUBLICATION_BINDING_FIELDS} != binding:
                raise GovernanceContractError(f"{receipt_id} reviewers must bind the attested object and range")
            verdict = reviewer.get("verdict")
            if verdict not in _PUBLICATION_REVIEW_VERDICTS:
                raise GovernanceContractError(f"{field}.verdict is missing or invalid")
            verdicts.append(verdict)
            disagreements = reviewer["disagreements"]
            if not isinstance(disagreements, list):
                raise GovernanceContractError(f"{field}.disagreements must be a list")
            for disagreement_index, disagreement in enumerate(disagreements):
                disagreement_field = f"{field}.disagreements[{disagreement_index}]"
                if not isinstance(disagreement, Mapping) or set(disagreement) != {
                    "subject",
                    "reviewer_assessment",
                    "disposition_assessment",
                }:
                    raise GovernanceContractError(f"{disagreement_field} shape is not exact")
                _nonempty(disagreement["subject"], f"{disagreement_field}.subject")
                assessments = {"blocking", "non_blocking"}
                if (
                    disagreement["reviewer_assessment"] not in assessments
                    or disagreement["disposition_assessment"] not in assessments
                    or disagreement["reviewer_assessment"] == disagreement["disposition_assessment"]
                ):
                    raise GovernanceContractError(f"{disagreement_field} must record differing assessments")
        if len(identities) != len(set(identities)):
            raise GovernanceContractError(f"{receipt_id} reviewers are not distinct")
        if mandates != _PUBLICATION_REVIEW_MANDATES:
            raise GovernanceContractError(f"{receipt_id} requires depth-and-delta and BREADTH mandates")
        if disposition == "approved" and any(verdict != "approved" for verdict in verdicts):
            raise GovernanceContractError(f"{receipt_id} cannot authorise approval while a reviewer does not approve")
    return dict(payload)


def validate_registry(
    payload: Any,
    *,
    root: Path | None = None,
    git_repository: Path | None = None,
    require_git_resolution: bool = False,
) -> dict[str, Any]:
    module_root = Path(__file__).resolve().parent.parent
    if root is None:
        if Path.cwd().resolve() != module_root:
            raise GovernanceContractError("registry root must be explicit outside the governance module tree")
        root = module_root
    # When the tree under validation IS itself a repository, that repository is the
    # right place to resolve its own objects, and object resolution must keep running
    # exactly as before. Omitting this silently disabled resolution for every in-repo
    # caller: `tests/governance/test_red_reproduction.py` caught it immediately, with
    # the `missing-defective-commit` and `wrong-defective-tree` mutations no longer
    # raising. Those tests are red proofs that each validator branch matters, so a
    # DID NOT RAISE there is a weakened guard, not a stale expectation.
    #
    # This is NOT a fallback that can rescue the protected path: there `root` is the
    # sealed export, which has no `.git`, so this leaves `git_repository` None and
    # `require_git_resolution` refuses unless the candidate checkout was passed.
    if git_repository is None and (root / ".git").exists():
        git_repository = root
    if not isinstance(payload, dict):
        raise GovernanceContractError("registry root must be a mapping")
    required_top = {
        "schema_version",
        "registry_id",
        "status_definitions",
        "scope_definitions",
        "ownership_semantics",
        "campaign_expiry_semantics",
        "durable_product_contract_authority",
        "policy_refs",
        "default_ci_jobs",
        "false_green_pair_semantics",
        "record_evidence_semantics",
        "false_green_pairs",
        "records",
    }
    if set(payload) != required_top or payload.get("schema_version") != 2:
        raise GovernanceContractError("registry top-level schema is not exact")
    if payload["status_definitions"] != _EXPECTED_STATUS_DEFINITIONS:
        raise GovernanceContractError("status definitions are not exact")
    if payload["scope_definitions"] != _EXPECTED_SCOPE_DEFINITIONS:
        raise GovernanceContractError("scope definitions are not exact")
    if payload["ownership_semantics"] != _EXPECTED_OWNERSHIP_SEMANTICS:
        raise GovernanceContractError("ownership semantics are not exact")
    if payload["campaign_expiry_semantics"] != _EXPECTED_CAMPAIGN_EXPIRY_SEMANTICS:
        raise GovernanceContractError("campaign expiry semantics are not exact")
    if payload["default_ci_jobs"] != _EXPECTED_DEFAULT_CI_JOBS:
        raise GovernanceContractError("default CI jobs are not exact")
    if payload["false_green_pair_semantics"] != _EXPECTED_FALSE_GREEN_PAIR_SEMANTICS:
        raise GovernanceContractError("false-green pair semantics are not exact")
    if payload["record_evidence_semantics"] != _EXPECTED_RECORD_EVIDENCE_SEMANTICS:
        raise GovernanceContractError("record evidence semantics are not exact")
    partitions = set(payload["default_ci_jobs"])
    if partitions != {"agents", "core", "gui", "remaining"}:
        raise GovernanceContractError("default CI partitions are not exact")
    if any(not payload["default_ci_jobs"][name] for name in partitions):
        raise GovernanceContractError("default CI partition has no required jobs")

    records = payload["records"]
    pairs = payload["false_green_pairs"]
    if not isinstance(records, list) or not isinstance(pairs, list):
        raise GovernanceContractError("records and false-green pairs must be lists")
    record_ids: set[str] = set()
    record_by_id: dict[str, Mapping[str, Any]] = {}
    guard_registration: dict[str, str] = {}
    record_guard_nodes: dict[str, dict[str, str | None]] = {}
    classifications: dict[str, list[str]] = {}
    classification_corpora: list[tuple[str, tuple[str, ...]]] = []
    base_record_fields = {
        "id",
        "status",
        "scope",
        "authority_source",
        "applies_to",
        "classification",
        "correction_owner",
        "guard_owner",
        "disposition_owner",
        "consequence",
        "invariant",
        "rule_refs",
        "guards",
        "red_evidence",
        "green_evidence",
    }
    for record in records:
        if not isinstance(record, Mapping):
            raise GovernanceContractError("prevention record is incomplete")
        raw_id = record.get("id")
        id_hint = raw_id if isinstance(raw_id, str) and raw_id.strip() else "<unidentified record>"
        record_fields = set(record)
        if not base_record_fields <= record_fields:
            raise GovernanceContractError(f"prevention record is incomplete: {id_hint}")
        unknown_fields = record_fields - base_record_fields - _OPTIONAL_RECORD_FIELDS
        if unknown_fields:
            raise GovernanceContractError(f"{id_hint} has unknown fields: {sorted(unknown_fields)}")
        record_id = _nonempty(record["id"], "record id")
        if _ID.fullmatch(record_id) is None or record_id in record_ids:
            raise GovernanceContractError(f"record id is invalid or duplicate: {record_id}")
        record_ids.add(record_id)
        record_by_id[record_id] = record
        if "campaign_edit_owner_overrides" in record:
            _validate_campaign_edit_owner_overrides(record["campaign_edit_owner_overrides"], record_id)
        if "campaign_guard_authorship" in record:
            _validate_campaign_guard_authorship(record["campaign_guard_authorship"], record_id)
        if "proposal_guard_scope" in record:
            _validate_proposal_guard_scope(record["proposal_guard_scope"], record_id)
        if "human_gate" in record:
            _nonempty(record["human_gate"], f"{record_id}.human_gate")
        if "automation_limit" in record:
            _nonempty(record["automation_limit"], f"{record_id}.automation_limit")
        if record["status"] not in _STATUSES or record["scope"] not in _SCOPES:
            raise GovernanceContractError(f"record status or scope is invalid: {record_id}")
        for field in ("authority_source", "applies_to", "classification", "consequence", "invariant"):
            _nonempty(record[field], f"{record_id}.{field}")
        classifications.setdefault(record["classification"], []).append(record_id)
        if "classification_corpus" in record:
            if record["scope"] != "repository":
                raise GovernanceContractError(f"{record_id}.classification_corpus must be repository-scoped")
            covered_classifications = _validate_classification_corpus(record["classification_corpus"], record_id)
            classification_corpora.append((record_id, covered_classifications))
        for owner_field in ("correction_owner", "guard_owner", "disposition_owner"):
            if record[owner_field] not in _OWNERS:
                raise GovernanceContractError(f"{record_id}.{owner_field} is invalid")
        if record["scope"] != "campaign_local" and "cli" in {
            record["correction_owner"],
            record["guard_owner"],
        }:
            raise GovernanceContractError("CLI-half ownership may exist only in a campaign-local record")
        if record["disposition_owner"] != "reviewer":
            raise GovernanceContractError("only the reviewer may dispose a prevention")
        if not isinstance(record["rule_refs"], list) or not record["rule_refs"]:
            raise GovernanceContractError(f"{record_id} has no governing rule references")
        guards = record["guards"]
        if not isinstance(guards, list) or not guards:
            raise GovernanceContractError(f"{record_id} has no machine-testable guard")
        owned_nodes: dict[str, str | None] = {}
        for guard in guards:
            _validate_guard(guard, partitions)
            node = guard["node"]
            previous = guard_registration.get(node)
            if previous is not None:
                raise GovernanceContractError(
                    f"guard node has multiple runtime registrations: {node} ({previous} and {record_id})"
                )
            guard_registration[node] = record_id
            owned_nodes[node] = guard.get("platform")
        record_guard_nodes[record_id] = owned_nodes
        if record["scope"] == "campaign_local":
            for field in ("expires_when", "expiry_disposition"):
                _nonempty(record.get(field), f"{record_id}.{field}")
        elif "expires_when" in record or "expiry_disposition" in record:
            raise GovernanceContractError("durable records cannot use campaign expiry")
        _validate_red_reproduction_evidence(
            record["red_evidence"],
            entry_id=record_id,
            guard_nodes=set(owned_nodes),
            root=root,
            git_repository=git_repository,
            require_git_resolution=require_git_resolution,
        )
        if record["status"] in {"closed", "expired"}:
            if "automation_limit" in record:
                raise GovernanceContractError(f"{record_id} cannot close while its automation_limit remains")
            _validate_immutable_evidence(record["red_evidence"], f"{record_id}.red_evidence")
            _validate_immutable_evidence(record["green_evidence"], f"{record_id}.green_evidence")
            guard_partitions = {guard["ci_partition"] for guard in guards}
            _validate_evidence_partition(
                record["red_evidence"], guard_partitions, f"{record_id}.red_evidence", required_for_closure=False
            )
            _validate_evidence_partition(
                record["green_evidence"], guard_partitions, f"{record_id}.green_evidence", required_for_closure=True
            )
            _validate_guard_source_blobs(
                record.get("guard_source_blobs"),
                entry_id=record_id,
                guard_nodes=set(owned_nodes),
                root=root,
            )
            if record.get("closure_semantics_sha256") != closure_semantics_sha256(record):
                raise GovernanceContractError(f"{record_id} closure evidence is semantically stale")
        elif "closure_semantics_sha256" in record or "guard_source_blobs" in record:
            raise GovernanceContractError(f"{record_id} has premature closure evidence")
        if record["status"] == "expired" and record["scope"] != "campaign_local":
            raise GovernanceContractError("only campaign-local records may expire")

    if len(classification_corpora) > 1:
        raise GovernanceContractError("registry has multiple classification corpus dispositions")
    if classification_corpora:
        corpus_id, covered_classifications = classification_corpora[0]
        if record_by_id[corpus_id]["classification"] != "corpus_disposition_governance":
            raise GovernanceContractError(f"{corpus_id}.classification must identify corpus disposition governance")
        repeated = {
            classification
            for classification, ids in classifications.items()
            if len(ids) >= _CLASSIFICATION_CORPUS_REPEAT_THRESHOLD
        }
        if set(covered_classifications) != repeated:
            missing = sorted(repeated - set(covered_classifications))
            unexpected = sorted(set(covered_classifications) - repeated)
            raise GovernanceContractError(
                f"classification corpus coverage must exactly name recurring classifications; "
                f"missing: {missing}; unexpected: {unexpected}"
            )

    pair_ids: set[str] = set()
    required_pair_fields = {
        "id",
        "status",
        "scope",
        "runtime_prevention_id",
        "guard",
        "ci_partition",
        "red_evidence",
        "green_evidence",
    }
    pair_guards: set[str] = set()
    for pair in pairs:
        optional_pair_fields = {"platform", "closure_semantics_sha256", "guard_source_blobs"}
        if (
            not isinstance(pair, Mapping)
            or not required_pair_fields <= set(pair)
            or set(pair) - required_pair_fields - optional_pair_fields
        ):
            raise GovernanceContractError("false-green pair shape is not exact")
        pair_id = _nonempty(pair["id"], "false-green pair id")
        if _ID.fullmatch(pair_id) is None or pair_id in pair_ids or pair_id in record_ids:
            raise GovernanceContractError(f"false-green pair id is invalid or duplicate: {pair_id}")
        pair_ids.add(pair_id)
        runtime = record_by_id.get(pair["runtime_prevention_id"])
        if runtime is None:
            raise GovernanceContractError(f"{pair_id} has a dangling runtime prevention")
        if pair["status"] not in _STATUSES or pair["scope"] != runtime["scope"]:
            raise GovernanceContractError(f"{pair_id} status or inherited scope is invalid")
        if pair["status"] == "expired" and pair["scope"] != "campaign_local":
            raise GovernanceContractError(f"{pair_id} expires outside campaign-local scope")
        if pair["status"] != "expired" and runtime["status"] == "expired":
            raise GovernanceContractError(f"{pair_id} remains active after its runtime prevention expired")
        _validate_guard(
            {
                "node": pair["guard"],
                "ci_partition": pair["ci_partition"],
                **({"platform": pair["platform"]} if "platform" in pair else {}),
            },
            partitions,
        )
        if pair["guard"] in pair_guards:
            raise GovernanceContractError(f"false-green guard has multiple pair registrations: {pair['guard']}")
        pair_guards.add(pair["guard"])
        runtime_guards = record_guard_nodes[pair["runtime_prevention_id"]]
        if pair["guard"] not in runtime_guards:
            raise GovernanceContractError(f"{pair_id} guard is absent from its runtime prevention")
        if pair.get("platform") != runtime_guards[pair["guard"]]:
            raise GovernanceContractError(f"{pair_id} platform differs from its runtime guard")
        _validate_red_reproduction_evidence(
            pair["red_evidence"],
            entry_id=pair_id,
            guard_nodes={pair["guard"]},
            root=root,
            git_repository=git_repository,
            require_git_resolution=require_git_resolution,
        )
        if pair["status"] in {"closed", "expired"}:
            if runtime["status"] not in {"closed", "expired"}:
                raise GovernanceContractError(f"{pair_id} closes before its runtime prevention")
            _validate_immutable_evidence(pair["red_evidence"], f"{pair_id}.red_evidence")
            _validate_immutable_evidence(pair["green_evidence"], f"{pair_id}.green_evidence")
            pair_partitions = {pair["ci_partition"]}
            _validate_evidence_partition(
                pair["red_evidence"], pair_partitions, f"{pair_id}.red_evidence", required_for_closure=False
            )
            _validate_evidence_partition(
                pair["green_evidence"], pair_partitions, f"{pair_id}.green_evidence", required_for_closure=True
            )
            _validate_guard_source_blobs(
                pair.get("guard_source_blobs"),
                entry_id=pair_id,
                guard_nodes={pair["guard"]},
                root=root,
            )
            if pair.get("closure_semantics_sha256") != closure_semantics_sha256(pair):
                raise GovernanceContractError(f"{pair_id} closure evidence is semantically stale")
        elif "closure_semantics_sha256" in pair or "guard_source_blobs" in pair:
            raise GovernanceContractError(f"{pair_id} has premature closure evidence")
    _validate_alarm_unknown_as_clear_class(record_by_id, pairs)
    # Publication receipts are NOT validated here. This validator runs inside
    # exported sealed candidates and synthetic fixture trees, where the receipt
    # file legitimately does not exist -- coupling the two made a minimal export
    # die before it could emit its own failure receipt. Receipts are a fact about
    # a candidate, so the publication gate validates them alongside the candidate;
    # see validate_publication_disposition_receipts and its governance tests.
    return payload


_REMOVAL_BASELINE_PATH = Path(__file__).resolve().parent.parent / "governance" / "agent_preventions_baseline.json"

_ALARM_UNKNOWN_AS_CLEAR_RUNTIME_ID = "ALARM-UNKNOWN-AS-CLEAR-033"
_ALARM_UNKNOWN_AS_CLEAR_FALSE_GREEN_GUARD = (
    "tests/core/test_alarm_v2_integration.py::test_every_evaluator_exception_holds_active_and_never_fires_inactive"
)
_ALARM_UNKNOWN_AS_CLEAR_FALSE_GREEN_ID = "ALARM-UNKNOWN-AS-CLEAR-FALSE-GREEN-201"
_ALARM_UNKNOWN_AS_CLEAR_CLASSIFICATION = "unknown_as_clear"
_ALARM_UNKNOWN_AS_CLEAR_PATH = (
    "_alarm_v2_tick_configs -> tick_alarm -> AlarmEvaluator.evaluate -> AlarmStateManager.process"
)
_ALARM_UNKNOWN_AS_CLEAR_GUARDS = frozenset(
    {
        "tests/core/test_alarm_v2_integration.py::test_shipped_vacuum_loss_cold_holds_when_evaluator_raises",
        "tests/core/test_alarm_v2_integration.py::test_every_evaluator_exception_holds_active_and_never_fires_inactive",
    }
)


def _validate_alarm_unknown_as_clear_class(record_by_id: Mapping[str, Mapping[str, Any]], pairs: list[Any]) -> None:
    """Keep the three unknown-as-clear instances bound as one alarm class."""

    runtime = record_by_id.get(_ALARM_UNKNOWN_AS_CLEAR_RUNTIME_ID)
    matching_pairs = [pair for pair in pairs if pair.get("id") == _ALARM_UNKNOWN_AS_CLEAR_FALSE_GREEN_ID]
    if runtime is None:
        if not matching_pairs:
            return
        raise GovernanceContractError("unknown-as-clear runtime class disposition is missing")
    if runtime["classification"] != _ALARM_UNKNOWN_AS_CLEAR_CLASSIFICATION:
        raise GovernanceContractError("unknown-as-clear runtime class classification is missing")
    if runtime["scope"] != "product_contract":
        raise GovernanceContractError("unknown-as-clear runtime class scope is not product_contract")
    if _ALARM_UNKNOWN_AS_CLEAR_PATH not in f"{runtime['applies_to']} {runtime['invariant']}":
        raise GovernanceContractError("unknown-as-clear runtime class omits its production invocation path")
    runtime_nodes = {guard["node"] for guard in runtime["guards"]}
    if runtime_nodes != _ALARM_UNKNOWN_AS_CLEAR_GUARDS:
        raise GovernanceContractError("unknown-as-clear runtime class guards are incomplete or changed")
    if any(guard["ci_partition"] != "core" for guard in runtime["guards"]):
        raise GovernanceContractError("unknown-as-clear runtime class guard is not in core CI")

    # Whole-registry pair removal is deliberately handled by the removal
    # baseline, whose test also needs a structurally valid pair-free payload.
    if not matching_pairs:
        return
    if len(matching_pairs) != 1:
        raise GovernanceContractError("unknown-as-clear false-green class disposition is missing or duplicated")
    pair = matching_pairs[0]
    if (
        pair["runtime_prevention_id"] != _ALARM_UNKNOWN_AS_CLEAR_RUNTIME_ID
        or pair["guard"] != _ALARM_UNKNOWN_AS_CLEAR_FALSE_GREEN_GUARD
        or pair["ci_partition"] != "core"
    ):
        raise GovernanceContractError("unknown-as-clear false-green class guard is incomplete or misbound")


def compute_removal_baseline(payload: Mapping[str, Any]) -> dict[str, str]:
    """Digest every record and false-green pair id, regardless of status.

    `closure_semantics_sha256` is only ever compared against a stored digest for
    `closed`/`expired` entries (see the `status in {"closed", "expired"}` branches
    above); every record and pair in this registry is currently `open`, so that
    comparison alone guards nothing today. This computes the same digest for
    *every* id independent of status, so a tracked baseline can detect silent
    weakening or removal of an entry no matter what its lifecycle state is.
    """
    digests: dict[str, str] = {}
    for record in payload["records"]:
        digests[record["id"]] = closure_semantics_sha256(record)
    for pair in payload["false_green_pairs"]:
        digests[pair["id"]] = closure_semantics_sha256(pair)
    return digests


def render_removal_baseline(payload: Mapping[str, Any]) -> str:
    """Byte-deterministic JSON rendering of the removal baseline.

    Sorted keys and fixed separators make two consecutive runs against the same
    registry content produce byte-identical output.
    """
    document = {
        "schema_version": payload.get("schema_version"),
        "record_count_floor": len(payload["records"]),
        "false_green_pair_count_floor": len(payload["false_green_pairs"]),
        "digests": compute_removal_baseline(payload),
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _entry_status(payload: Mapping[str, Any], entry_id: str) -> str | None:
    for record in payload["records"]:
        if record["id"] == entry_id:
            return record["status"]
    for pair in payload["false_green_pairs"]:
        if pair["id"] == entry_id:
            return pair["status"]
    return None


def validate_against_removal_baseline(payload: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    """Reject silent removal or undisclosed weakening of any previously known entry.

    ADR-003 requires rejecting "removal or weakening without an explicit reopened
    disposition" (docs/adr/003-governance-as-enforcement.md:104). Every record and
    pair already carries a mandatory `disposition_owner: reviewer` field
    (enforced unconditionally above, regardless of status); combined with the
    entry's own `status` this is the registry's existing "reviewer disposition"
    signal, so an id may only change digest here if its current status is
    `reopened` -- the status the registry already defines as "A previously
    disposed invariant lost, weakened, skipped, or misbound enforcement."
    Anything else that changes or disappears is rejected by name.
    """
    if not isinstance(baseline, Mapping) or not isinstance(baseline.get("digests"), Mapping):
        raise GovernanceContractError("removal baseline is malformed")
    current = compute_removal_baseline(payload)
    for entry_id, expected_digest in baseline["digests"].items():
        actual_digest = current.get(entry_id)
        if actual_digest is None:
            raise GovernanceContractError(
                f"registry baseline entry was removed without a reopened disposition: {entry_id}"
            )
        if actual_digest != expected_digest and _entry_status(payload, entry_id) != "reopened":
            raise GovernanceContractError(f"registry entry changed without a reopened disposition: {entry_id}")
    record_floor = baseline.get("record_count_floor", 0)
    pair_floor = baseline.get("false_green_pair_count_floor", 0)
    record_count = len(payload["records"])
    pair_count = len(payload["false_green_pairs"])
    if record_count < record_floor:
        raise GovernanceContractError(f"record count fell below the tracked floor: {record_count} < {record_floor}")
    if pair_count < pair_floor:
        raise GovernanceContractError(
            f"false-green pair count fell below the tracked floor: {pair_count} < {pair_floor}"
        )


def _write_removal_baseline() -> None:
    """Regenerate governance/agent_preventions_baseline.json from the live registry.

    Explicit command: `python tools/governance_contract.py --write-baseline`
    (run from the repository root, or anywhere -- paths are resolved from this
    file's location). Rerunning with no registry changes produces byte-identical
    output.
    """
    import yaml

    registry_path = _REMOVAL_BASELINE_PATH.parent / "agent_preventions.yaml"
    payload = validate_registry(
        yaml.safe_load(registry_path.read_text(encoding="utf-8")),
        root=_REMOVAL_BASELINE_PATH.parent.parent,
    )
    _REMOVAL_BASELINE_PATH.write_text(render_removal_baseline(payload), encoding="utf-8")


if __name__ == "__main__":
    import sys

    if "--write-baseline" in sys.argv[1:]:
        _write_removal_baseline()
    else:
        print("usage: python tools/governance_contract.py --write-baseline", file=sys.stderr)
        raise SystemExit(2)
