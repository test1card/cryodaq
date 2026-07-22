from __future__ import annotations

import copy
import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml

from tools.agent_context_gate import (
    AgentContextError,
    canonical_capsule_bytes,
    observe_owned_current_blobs,
    owned_blob_manifest_digest,
    parse_and_validate_capsule,
    sha256_bytes,
    validate_capsule_set,
    validate_resume,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = yaml.safe_load((ROOT / "governance" / "agent_context_schema.yaml").read_text(encoding="utf-8"))
EMPTY = f"sha256:{hashlib.sha256(b'').hexdigest()}"


def _capsule(*, slug: str = "worker", owned: tuple[str, ...] = ("src/cryodaq/a.py",)) -> dict:
    preimages = {path: f"100644:{'1' * 40}" for path in owned}
    current_blobs = {path: f"100644:{'4' * 40}" for path in owned}
    return {
        "acknowledged_instruction": {
            "digest": EMPTY,
            "sequence": "instruction-1",
            "source": "reviewer",
            "summary": "bounded work",
        },
        "agent_id": f"/root/{slug}",
        "assignment": {
            "objective": "bounded implementation",
            "scope": "assigned paths",
            "state": "active",
        },
        "authority": None,
        "branch": "feat/montana-phase-a",
        "canonical_root": "C:/Users/3fall/Projects/cryodaq",
        "dependencies": [],
        "dirty_inventory_digest": EMPTY,
        "event_history": [],
        "evidence": [
            {
                "command": "pytest exact-node",
                "cwd": "C:/Users/3fall/Projects/cryodaq",
                "exit_code": 0,
                "kind": "test",
                "object_binding": f"commit={'2' * 40};tree={'3' * 40}",
                "result": "pass",
                "stderr_sha256": EMPTY,
                "stdout_sha256": EMPTY,
            }
        ],
        "excluded_worktrees": ["C:/tmp/cryodaq-cli-montana-half"],
        "forbidden_paths": ["docs/**"],
        "governing_hashes": {"AGENTS.md": EMPTY},
        "governing_set_id": "montana-v1",
        "head": "2" * 40,
        "next_action": {
            "command": "pytest exact-node",
            "description": "run exact guard",
            "kind": "test",
        },
        "open_findings": [],
        "owned_blob_manifest_digest": owned_blob_manifest_digest(current_blobs),
        "owned_current_blobs": current_blobs,
        "owned_paths": list(owned),
        "owned_preimages": preimages,
        "path_slug": slug,
        "prevention_ids": ["AGENT-CONTEXT-COMPACTION-001"],
        "proposal_state": {
            "commit": None,
            "frozen": False,
            "state": "working",
            "tree": None,
        },
        "role": "implementation",
        "schema_version": 1,
        "sequence": 1,
        "supersedes": None,
        "tree": "3" * 40,
        "updated_at": "2026-07-22T12:00:00+00:00",
    }


def _bind_repository(payload: dict, repository: Path) -> None:
    repository.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    payload["canonical_root"] = repository.resolve().as_posix()
    for path in payload["owned_paths"]:
        target = repository.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"current:{path}\n".encode())
    current = observe_owned_current_blobs(repository, payload["owned_paths"])
    payload["owned_current_blobs"] = current
    payload["owned_blob_manifest_digest"] = owned_blob_manifest_digest(current)


def _resume_kwargs(payload: dict, repository: Path) -> dict:
    return {
        "capsule_path": f".audit-run/montana/context/{payload['path_slug']}.yaml",
        "expected_capsule_path": f".audit-run/montana/context/{payload['path_slug']}.yaml",
        "agent_id": payload["agent_id"],
        "role": payload["role"],
        "path_slug": payload["path_slug"],
        "canonical_root": payload["canonical_root"],
        "branch": payload["branch"],
        "head": payload["head"],
        "tree": payload["tree"],
        "dirty_inventory_digest": payload["dirty_inventory_digest"],
        "governing_set_id": payload["governing_set_id"],
        "governing_hashes": payload["governing_hashes"],
        "owned_paths": payload["owned_paths"],
        "owned_preimages": payload["owned_preimages"],
        "forbidden_paths": payload["forbidden_paths"],
        "excluded_worktrees": payload["excluded_worktrees"],
        "proposal_state": payload["proposal_state"],
        "prevention_ids": payload["prevention_ids"],
        "repository": repository,
    }


def test_schema_requires_exact_identity_authority_git_and_evidence_bindings() -> None:
    valid = _capsule()
    parse_and_validate_capsule(canonical_capsule_bytes(valid), SCHEMA)

    mutations = []
    missing = copy.deepcopy(valid)
    missing.pop("head")
    mutations.append(missing)
    authoritative = copy.deepcopy(valid)
    authoritative["authority"] = "self-approved"
    mutations.append(authoritative)
    short_head = copy.deepcopy(valid)
    short_head["head"] = "2" * 12
    mutations.append(short_head)
    unbound = copy.deepcopy(valid)
    unbound["evidence"][0]["object_binding"] = ""
    mutations.append(unbound)
    for malformed in mutations:
        with pytest.raises(AgentContextError):
            parse_and_validate_capsule(canonical_capsule_bytes(malformed), SCHEMA)


def test_missing_stale_moved_or_cross_owned_capsule_fails_closed(tmp_path: Path) -> None:
    payload = _capsule()
    repository = tmp_path / "repo"
    _bind_repository(payload, repository)
    raw = canonical_capsule_bytes(payload)
    kwargs = _resume_kwargs(payload, repository)
    validate_resume(raw, SCHEMA, **kwargs)
    for changed in (
        {"raw": None},
        {"capsule_path": "scratchpad/montana/exec/progress.md"},
        {"agent_id": "/root/another-worker"},
        {"head": "4" * 40},
    ):
        invocation = dict(kwargs)
        candidate_raw = changed.pop("raw", raw)
        invocation.update(changed)
        with pytest.raises(AgentContextError):
            validate_resume(candidate_raw, SCHEMA, **invocation)


def test_duplicate_writer_overlap_and_secret_shaped_values_are_rejected() -> None:
    first = _capsule(slug="one", owned=("src/cryodaq/shared.py",))
    second = _capsule(slug="two", owned=("src/cryodaq/shared.py",))
    with pytest.raises(AgentContextError, match="overlaps"):
        validate_capsule_set(
            [
                (".audit-run/montana/context/one.yaml", canonical_capsule_bytes(first)),
                (".audit-run/montana/context/two.yaml", canonical_capsule_bytes(second)),
            ],
            SCHEMA,
        )

    secret = _capsule()
    secret["assignment"]["api_key"] = "sk-" + "A" * 32
    with pytest.raises(AgentContextError, match="secret"):
        parse_and_validate_capsule(canonical_capsule_bytes(secret), SCHEMA)


def test_campaign_instance_paths_are_ignored_and_one_writer() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".audit-run/" in gitignore
    first = _capsule(slug="worker")
    second = _capsule(slug="worker", owned=("src/cryodaq/b.py",))
    with pytest.raises(AgentContextError, match="duplicate capsule writer"):
        validate_capsule_set(
            [
                (".audit-run/montana/context/worker.yaml", canonical_capsule_bytes(first)),
                (".audit-run/montana/context/reviews/worker.yaml", canonical_capsule_bytes(second)),
            ],
            SCHEMA,
        )


def test_status_only_digest_cannot_validate_changed_dirty_blob(tmp_path: Path) -> None:
    payload = _capsule()
    repository = tmp_path / "repo"
    _bind_repository(payload, repository)
    raw = canonical_capsule_bytes(payload)
    owned = repository / "src" / "cryodaq" / "a.py"
    owned.write_bytes(b"changed bytes with identical status shape\n")
    with pytest.raises(AgentContextError, match="stale|owned_current_blobs"):
        validate_resume(raw, SCHEMA, **_resume_kwargs(payload, repository))


def test_nested_mapping_order_and_forbidden_path_patterns_fail_closed() -> None:
    payload = _capsule()
    canonical = canonical_capsule_bytes(payload)
    lines = canonical.splitlines(keepends=True)
    digest_line = next(index for index, line in enumerate(lines) if line.startswith(b"  digest:"))
    sequence_line = next(index for index, line in enumerate(lines) if line.startswith(b"  sequence:"))
    lines[digest_line], lines[sequence_line] = lines[sequence_line], lines[digest_line]
    noncanonical = b"".join(lines)
    with pytest.raises(AgentContextError, match="canonical"):
        parse_and_validate_capsule(noncanonical, SCHEMA)

    traversal = _capsule(owned=("../src/cryodaq/a.py",))
    with pytest.raises(AgentContextError, match="glob, traversal"):
        parse_and_validate_capsule(canonical_capsule_bytes(traversal), SCHEMA)
    globbed = _capsule(owned=("src/**",))
    with pytest.raises(AgentContextError, match="glob, traversal"):
        parse_and_validate_capsule(canonical_capsule_bytes(globbed), SCHEMA)


def test_owned_manifest_uses_cross_platform_ordinal_path_order() -> None:
    preimages = {
        "src/z.py": f"100644:{'1' * 40}",
        "src/A.py": f"100644:{'2' * 40}",
        "src/a.py": "untracked",
    }
    records = b"".join(
        (
            path.encode("utf-8")
            + b"\0"
            + (b"untracked\0untracked\0" if value == "untracked" else value.replace(":", "\0").encode() + b"\0")
        )
        for path, value in sorted(preimages.items(), key=lambda item: item[0].encode("utf-8"))
    )
    assert owned_blob_manifest_digest(preimages) == sha256_bytes(records)


def test_legacy_or_self_asserted_capsule_cannot_claim_continuity(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    previous_payload = _capsule()
    _bind_repository(previous_payload, repository)
    previous = canonical_capsule_bytes(previous_payload)
    successor = _capsule()
    _bind_repository(successor, repository)
    successor["sequence"] = 2
    successor["supersedes"] = sha256_bytes(previous)
    successor_raw = canonical_capsule_bytes(successor)
    with pytest.raises(AgentContextError, match="moved|legacy"):
        validate_resume(
            successor_raw,
            SCHEMA,
            **{
                **_resume_kwargs(successor, repository),
                "capsule_path": "scratchpad/montana/exec/progress.md",
            },
            previous_raw=previous,
        )

    for state in ("approved", "review_good", "ready_for_merge", "done_for_review"):
        self_approved = copy.deepcopy(successor)
        self_approved["proposal_state"]["state"] = state
        with pytest.raises(AgentContextError, match="allowed non-authoritative"):
            parse_and_validate_capsule(canonical_capsule_bytes(self_approved), SCHEMA)


def test_resume_rejects_redirected_repository_and_authority_changes(tmp_path: Path) -> None:
    payload = _capsule()
    repository = tmp_path / "repo"
    _bind_repository(payload, repository)
    raw = canonical_capsule_bytes(payload)
    kwargs = _resume_kwargs(payload, repository)

    redirected = tmp_path / "redirected"
    redirected_payload = copy.deepcopy(payload)
    _bind_repository(redirected_payload, redirected)
    with pytest.raises(AgentContextError, match="canonical Git root"):
        validate_resume(raw, SCHEMA, **{**kwargs, "repository": redirected})

    changes = {
        "role": "reviewer",
        "path_slug": "another",
        "governing_set_id": "other-campaign",
        "owned_paths": [],
        "owned_preimages": {},
        "forbidden_paths": [],
        "excluded_worktrees": [],
        "proposal_state": {**payload["proposal_state"], "state": "waiting_for_review"},
        "prevention_ids": [],
    }
    for field, value in changes.items():
        with pytest.raises(AgentContextError, match="stale|cross-owned"):
            validate_resume(raw, SCHEMA, **{**kwargs, field: value})


def test_successor_requires_exact_increment_and_immutable_authority(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    previous_payload = _capsule()
    _bind_repository(previous_payload, repository)
    previous = canonical_capsule_bytes(previous_payload)
    successor = copy.deepcopy(previous_payload)
    successor["sequence"] = 2
    successor["supersedes"] = sha256_bytes(previous)
    raw = canonical_capsule_bytes(successor)
    validate_resume(raw, SCHEMA, **_resume_kwargs(successor, repository), previous_raw=previous)

    for mutation in (
        {"sequence": 3},
        {"agent_id": "/root/replacement"},
        {"owned_preimages": {"src/cryodaq/a.py": "untracked"}},
        {"forbidden_paths": []},
    ):
        changed = copy.deepcopy(successor)
        changed.update(mutation)
        if "owned_preimages" in mutation:
            kwargs = {**_resume_kwargs(successor, repository), "owned_preimages": mutation["owned_preimages"]}
        elif "forbidden_paths" in mutation:
            kwargs = {**_resume_kwargs(successor, repository), "forbidden_paths": []}
        elif "agent_id" in mutation:
            kwargs = {**_resume_kwargs(successor, repository), "agent_id": mutation["agent_id"]}
        else:
            kwargs = _resume_kwargs(successor, repository)
        with pytest.raises(AgentContextError, match="continuity|stale|cross-owned"):
            validate_resume(
                canonical_capsule_bytes(changed),
                SCHEMA,
                **kwargs,
                previous_raw=previous,
            )
