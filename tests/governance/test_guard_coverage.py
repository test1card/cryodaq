from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.guard_coverage import (
    INVENTORY_PATH,
    GuardCoverageError,
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


def test_gitless_export_fails_hard_instead_of_skipping(tmp_path: Path) -> None:
    _write(tmp_path / INVENTORY_PATH, json.dumps(_c2_inventory(), indent=2) + "\n")

    with pytest.raises(GuardCoverageError, match="requires an exact Git checkout"):
        compare(tmp_path, "HEAD^", "HEAD")
