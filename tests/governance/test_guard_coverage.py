from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.guard_coverage import (
    INVENTORY_PATH,
    GuardCoverageError,
    _git_file,
    _inventory_changes,
    _load_inventory,
    compare,
)

ROOT = Path(__file__).resolve().parents[2]


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Guard Coverage Test", "-c", "user.email=guard@example.invalid", "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _c2_inventory() -> dict:
    payload = json.loads((ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "guards": {"C2-DESCRIPTOR-SELECTION": payload["guards"]["C2-DESCRIPTOR-SELECTION"]},
        "reduction_declarations": [],
    }


def _g4_inventory() -> dict:
    payload = json.loads((ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "guards": {"G4-DOCUMENTATION-PROCEDURES": payload["guards"]["G4-DOCUMENTATION-PROCEDURES"]},
        "reduction_declarations": [],
    }


def _g4_guard_source(
    *,
    weakened: bool,
    source_controlled_parameter: bool = True,
    callback_type_error: bool = False,
) -> str:
    physical_check = "if False:" if weakened else 'if result == "SOFTWARE-PROVABLE":'
    validator_parameters = (
        "root: Path, overrides=None, *, source_controlled=None"
        if source_controlled_parameter
        else "root: Path, overrides=None"
    )
    authority = (
        "source_controlled or (lambda relative_path: _g4_is_source_controlled(root, relative_path))"
        if source_controlled_parameter
        else "lambda relative_path: _g4_is_source_controlled(root, relative_path)"
    )
    type_error = "    raise TypeError('unrelated callback body failure')\n" if callback_type_error else ""
    return (
        "from pathlib import Path\n"
        "import subprocess\n\n"
        "def _g4_is_source_controlled(root: Path, relative_path: str) -> bool:\n"
        "    root = root.resolve()\n"
        "    repository = subprocess.run(\n"
        "        ['git', '--no-replace-objects', '-C', str(root), 'rev-parse', '--show-toplevel'],\n"
        "        capture_output=True, text=True,\n"
        "    )\n"
        "    if repository.returncode or Path(repository.stdout.strip()).resolve() != root:\n"
        "        raise RuntimeError('source-control evidence is unavailable')\n"
        "    return False\n\n"
        f"def _validate_g4_docs({validator_parameters}) -> None:\n"
        f"{type_error}"
        f"    is_source_controlled = {authority}\n"
        "    if is_source_controlled('cooldown_v5/predictor_model.json'):\n"
        "        raise AssertionError('source-control binding is wrong')\n"
        "    checklist = (overrides or {}).get(\n"
        "        'docs/new_lab_acceptance_checklist.md',\n"
        "        (root / 'docs/new_lab_acceptance_checklist.md').read_text(encoding='utf-8'),\n"
        "    )\n"
        "    result = checklist.split('result: ', 1)[1].splitlines()[0]\n"
        f"    {physical_check}\n"
        "        raise AssertionError('acceptance evidence is external or physical, not SOFTWARE-PROVABLE')\n"
    )


def test_inventory_uses_stable_ids_and_never_line_number_identity() -> None:
    payload = _load_inventory((ROOT / INVENTORY_PATH).read_bytes(), "live")
    for guard in payload["guards"].values():
        for stable_id, exemption in guard["exemptions"].items():
            prefix, separator, suffix = stable_id.rpartition("-")
            assert prefix and separator and len(suffix) == 3 and suffix.isdigit()
            assert "line" not in exemption
            assert "lineno" not in exemption


def test_inventory_challenge_and_exemption_changes_are_independent_reductions() -> None:
    base = _c2_inventory()["guards"]["C2-DESCRIPTOR-SELECTION"]
    candidate = copy.deepcopy(base)
    removed_challenge = candidate["challenges"].pop("C2-CHALLENGE-DIRECT-RE-FINDITER-002")
    candidate["exemptions"]["C2-EXEMPT-OC-010"]["purpose"] = "weakened"

    changes = _inventory_changes(base, candidate)

    assert changes["removed_challenge_inventory_ids"] == ["C2-CHALLENGE-DIRECT-RE-FINDITER-002"]
    assert changes["changed_exemption_inventory_ids"] == ["C2-EXEMPT-OC-010"]
    assert removed_challenge


def test_guard_coverage_reduction_requires_exact_tracked_declaration(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / INVENTORY_PATH, json.dumps(_c2_inventory(), indent=2) + "\n")
    _write(
        repo / "tests" / "analytics" / "test_c2_descriptor_selection_guard.py",
        "from pathlib import Path\n\n"
        "_ALLOWLIST = {}\n\n"
        "def _violations(root: Path):\n"
        "    text = (root / 'src/cryodaq/reporting/probe.py').read_text(encoding='utf-8')\n"
        "    return [\n"
        "        f'regular expression {method}() over an identifier'\n"
        "        for method in ('findall', 'finditer')\n"
        "        if f're.{method}' in text\n"
        "    ]\n",
    )
    _write(
        repo / "src" / "cryodaq" / "reporting" / "periodic_renderer.py",
        "def _channel_key(value):\n    return value\n",
    )
    base = _commit(repo, "base guard")

    _write(
        repo / "tests" / "analytics" / "test_c2_descriptor_selection_guard.py",
        "from pathlib import Path\n\n"
        "_ALLOWLIST = {\n"
        "    ('src/cryodaq/reporting/periodic_renderer.py', 2):\n"
        "        ('BLOCKED-ON-SCHEMA', 'semantic exemption'),\n"
        "}\n\n"
        "def _violations(root: Path):\n"
        "    text = (root / 'src/cryodaq/reporting/probe.py').read_text(encoding='utf-8')\n"
        "    return [\n"
        "        'regular expression findall() over an identifier'\n"
        "        if 're.findall' in text else ''\n"
        "    ]\n",
    )
    weakened = _commit(repo, "message wording is irrelevant")

    red = compare(repo, base, weakened)

    assert not red.passed
    assert red.reductions[0]["lost_challenge_ids"] == ["C2-CHALLENGE-DIRECT-RE-FINDITER-002"]
    assert red.reductions[0]["added_exemption_ids"] == ["C2-EXEMPT-OC-010"]

    inventory = _c2_inventory()
    inventory["reduction_declarations"] = [
        {
            "id": "TEST-REDUCTION-001",
            "status": "approved",
            "reviewer": "independent-test-reviewer",
            "reason": "exercise the exact tracked-declaration path",
            **red.reductions[0],
        }
    ]
    _write(repo / INVENTORY_PATH, json.dumps(inventory, indent=2) + "\n")
    declared = _commit(repo, "tracked exact declaration")

    green = compare(repo, base, declared)

    assert green.passed
    assert green.approved == ("TEST-REDUCTION-001",)


def test_g4_archived_revision_binds_source_control_to_the_compared_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(repo / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(repo / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    base = _commit(repo, "base G4 guard")

    # The candidate deliberately loses the procedure rejection. Coverage must
    # distinguish that weakening after loading both revisions from Git-less
    # archives; a shared archive-root Git failure must not make both challenges
    # fail before the changed behavior is reached.
    _write(repo / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=True))
    weakened = _commit(repo, "weaken G4 procedure guard")
    _git(repo, "replace", base, weakened)

    red = compare(repo, base, weakened)

    assert not red.passed
    assert red.reductions[0]["guard_id"] == "G4-DOCUMENTATION-PROCEDURES"
    assert red.reductions[0]["lost_challenge_ids"] == ["G4-CHALLENGE-EXTERNAL-AS-SOFTWARE-001"]


def test_g4_pre_signature_archive_runs_and_detects_later_coverage_loss(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(repo / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(
        repo / "tests" / "docs" / "test_docs_freshness.py",
        _g4_guard_source(weakened=False, source_controlled_parameter=False),
    )
    archived_base = _commit(repo, "pre-signature G4 guard")

    _write(repo / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    current_guard = _commit(repo, "add revision source-control callback")

    compatible = compare(repo, archived_base, current_guard)
    assert compatible.passed
    assert compatible.gains == ()

    _write(repo / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=True))
    weakened = _commit(repo, "remove G4 procedure rejection")

    red = compare(repo, archived_base, weakened)
    assert not red.passed
    assert red.reductions[0]["guard_id"] == "G4-DOCUMENTATION-PROCEDURES"
    assert red.reductions[0]["lost_challenge_ids"] == ["G4-CHALLENGE-EXTERNAL-AS-SOFTWARE-001"]


def test_g4_pre_signature_callback_body_type_error_is_a_base_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(repo / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(
        repo / "tests" / "docs" / "test_docs_freshness.py",
        _g4_guard_source(
            weakened=False,
            source_controlled_parameter=False,
            callback_type_error=True,
        ),
    )
    archived_base = _commit(repo, "pre-signature callback with unrelated defect")

    _write(repo / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    current_guard = _commit(repo, "working current callback")

    with pytest.raises(
        GuardCoverageError,
        match=(
            "base challenge failed: G4-DOCUMENTATION-PROCEDURES:"
            "G4-CHALLENGE-EXTERNAL-AS-SOFTWARE-001: guard error: TypeError: "
            "unrelated callback body failure"
        ),
    ):
        compare(repo, archived_base, current_guard)


def test_gitless_export_fails_hard_instead_of_skipping(tmp_path: Path) -> None:
    _write(tmp_path / INVENTORY_PATH, json.dumps(_c2_inventory(), indent=2) + "\n")

    with pytest.raises(GuardCoverageError, match="requires the requested repository to resolve exactly"):
        compare(tmp_path, "HEAD^", "HEAD")


def test_g4_guard_coverage_rejects_inherited_git_repository_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A weakened requested repository must stay red even when an inherited
    GIT_DIR/GIT_WORK_TREE redirect points every Git call at a second strong
    repository.

    Without the sanitized authority boundary both revisions resolved against
    the strong repository's object database, so both challenges loaded the
    strong guard and the lost G4 procedure challenge reported no reduction.
    """

    strong = tmp_path / "strong"
    strong.mkdir()
    _git(strong, "init")
    _write(strong / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(strong / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(strong / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    _commit(strong, "strong base guard")
    _write(strong / "strong-repository-marker.txt", "unrelated second commit\n")
    _commit(strong, "strong second commit keeps the strong guard at HEAD")

    requested = tmp_path / "requested"
    requested.mkdir()
    _git(requested, "init")
    _write(requested / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(requested / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(requested / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    _commit(requested, "requested base guard")
    _write(requested / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=True))
    _commit(requested, "weaken the requested G4 procedure guard")

    monkeypatch.setenv("GIT_DIR", str(strong / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(strong))

    red = compare(requested, "HEAD^", "HEAD")

    assert not red.passed
    assert red.reductions[0]["guard_id"] == "G4-DOCUMENTATION-PROCEDURES"
    assert red.reductions[0]["lost_challenge_ids"] == ["G4-CHALLENGE-EXTERNAL-AS-SOFTWARE-001"]


def test_g4_guard_coverage_fails_closed_when_requested_repo_resolves_to_a_foreign_root(
    tmp_path: Path,
) -> None:
    """The requested-repository verification is fail-closed: a path whose
    ``rev-parse --show-toplevel`` resolves anywhere but the requested
    repository is unavailable evidence, never an implicit pass.

    A directory nested inside a foreign repository borrows that repository's
    objects for both revisions, so without the top-level check the comparison
    reported no reduction; the authority boundary rejects it before any
    revision is resolved.
    """

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    _git(foreign, "init")
    _write(foreign / INVENTORY_PATH, json.dumps(_g4_inventory(), indent=2) + "\n")
    _write(foreign / "docs" / "new_lab_acceptance_checklist.md", "result: PHYSICAL\n")
    _write(foreign / "tests" / "docs" / "test_docs_freshness.py", _g4_guard_source(weakened=False))
    _commit(foreign, "foreign base guard")
    _write(foreign / "foreign-repository-marker.txt", "unrelated second commit\n")
    _commit(foreign, "foreign second commit keeps the strong guard at HEAD")

    nested = foreign / "nested"
    nested.mkdir()

    with pytest.raises(GuardCoverageError, match="requires the requested repository to resolve exactly"):
        compare(nested, "HEAD^", "HEAD")


def test_git_file_reads_the_requested_repository_not_an_inherited_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """``_git_file`` shares the sanitized boundary: an inherited redirect into a
    second repository must not satisfy a path read against the requested one."""

    requested = tmp_path / "requested"
    requested.mkdir()
    _git(requested, "init")
    _write(requested / "identity.txt", "requested\n")
    requested_revision = _commit(requested, "requested marker")

    strong = tmp_path / "strong"
    strong.mkdir()
    _git(strong, "init")
    _write(strong / "identity.txt", "strong\n")
    _commit(strong, "strong marker")

    monkeypatch.setenv("GIT_DIR", str(strong / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(strong))

    content = _git_file(requested, requested_revision, Path("identity.txt"))

    assert content == b"requested\n"
