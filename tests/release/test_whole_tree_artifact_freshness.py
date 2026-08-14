"""Release-time whole-tree artifact checks (OB-006).

The owner decided these tree-wide bindings run on release, not on pull requests.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    """Read required UTF-8 evidence; missing or invalid input must fail."""
    return path.read_text(encoding="utf-8")


def test_claim_corrections_changed_python_count_matches_workflow_index() -> None:
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "main.yml")
    corrections = _read(REPO_ROOT / "docs" / "CLAIM_CORRECTIONS.md")

    def assert_current(candidate_workflow: str, candidate_corrections: str) -> None:
        bases = re.findall(r"(?m)^\s*FORMAT_BASE=([0-9a-f]{40})\s*$", candidate_workflow)
        assert len(bases) == 1
        format_base = bases[0]
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", format_base, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ancestry.returncode == 0, ancestry.stderr
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACMR",
                format_base,
                "--",
                "*.py",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert changed == sorted(set(changed))
        anchor = (
            f"workflow-exact changed-file set in the current candidate index contains **{len(changed):,}** Python paths"
        )
        assert anchor in candidate_corrections

    assert_current(workflow, corrections)

    # The negative control has to mutate the LIVE candidate anchor that
    # ``assert_current`` actually validates.  Matching the first
    # ``contains **N** Python paths`` in the file is not equivalent: this branch
    # also carries the frozen PR7 correction, whose count appears earlier and is
    # deliberately pinned, so mutating it leaves the guard green and the control
    # proves nothing.  The count itself stays un-hardcoded so the control keeps
    # working as the candidate set moves.
    current_anchor = re.search(r"current candidate index contains \*\*[\d,]+\*\* Python paths", corrections)
    assert current_anchor is not None
    stale_count = corrections.replace(
        current_anchor.group(0), "current candidate index contains **669** Python paths", 1
    )
    assert stale_count != corrections
    with pytest.raises(AssertionError):
        assert_current(workflow, stale_count)

    stale_base = workflow.replace(
        "FORMAT_BASE=f5d6434d20dffae62c9f03fbc12f68b03f48351b",
        "FORMAT_BASE=dc2f911b4da7e01325ef4627c21a3f6140d3bc67",
        1,
    )
    assert stale_base != workflow
    with pytest.raises(AssertionError):
        assert_current(stale_base, corrections)

    # Regression for the detached/exported-checkout topology defect: a
    # FORMAT_BASE that is a valid commit but NOT an ancestor of HEAD must fail
    # closed as an AssertionError from the ancestry guard. With the old
    # ``check=True`` form this escaped as a CalledProcessError (which
    # ``pytest.raises(AssertionError)`` cannot catch), so a non-ancestor base in
    # a GitHub-shaped detached checkout turned the guard into an error instead
    # of a clean failure. The dangling commit below is a real child of HEAD, so
    # it is a valid commit that is provably not an ancestor of HEAD, and it
    # touches no ref or working tree.
    non_ancestor_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "cryodaq-test",
        "GIT_AUTHOR_EMAIL": "cryodaq-test@example.com",
        "GIT_COMMITTER_NAME": "cryodaq-test",
        "GIT_COMMITTER_EMAIL": "cryodaq-test@example.com",
    }
    head_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    non_ancestor = subprocess.run(
        ["git", "commit-tree", head_tree, "-p", "HEAD", "-m", "non-ancestor ancestry probe"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=non_ancestor_env,
        check=True,
    ).stdout.strip()
    ancestry_check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", non_ancestor, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestry_check.returncode == 1, (non_ancestor, ancestry_check.stderr)
    non_ancestor_workflow = workflow.replace(
        "FORMAT_BASE=f5d6434d20dffae62c9f03fbc12f68b03f48351b",
        f"FORMAT_BASE={non_ancestor}",
        1,
    )
    assert non_ancestor_workflow != workflow
    with pytest.raises(AssertionError):
        assert_current(non_ancestor_workflow, corrections)


def _svg_metadata(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    records = [element for element in root if element.tag.endswith("metadata")]
    assert len(records) == 1 and records[0].text
    payload = json.loads(records[0].text)
    assert type(payload) is dict
    return payload


def _svg_nodes(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        element.attrib["data-path"]
        for element in root.iter()
        if element.tag.endswith("g") and element.attrib.get("class") == "file-node"
    ]


@cache
def _architecture_inventory() -> tuple[object, tuple[str, ...], dict[str, bytes]]:
    import tools.generate_montana_architecture_svgs as generator

    snapshot = generator.target_snapshot()
    paths = tuple(snapshot.paths)
    return snapshot, paths, {path: snapshot.read(path) for path in paths}


def test_checked_in_montana_architecture_svgs_match_frozen_index_snapshot(tmp_path: Path) -> None:
    """Narrowed to the one surviving architecture graph (manifest SVG decision).

    Previously checked both the exhaustive 1,085-file "all-files" map and the
    legible "important" map. The manifest kept only the latter — the
    all-files map is a provenance artifact, not a document a human or a weak
    model can read, and the two before/after comparison maps are pure
    campaign evidence. Only ``docs/architecture-montana-important.svg``
    (moved out of the campaign-named ``docs/refactor/``) ships in PR-A, so
    this is the only checked-in SVG this test can still verify.
    """
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    paths = list(frozen_paths)
    reader = contents.__getitem__
    assert paths
    assert not any(generator._is_generated_output(path) for path in paths)

    important_svg = REPO_ROOT / "docs/architecture-montana-important.svg"
    important = list(generator.IMPORTANT_MONTANA)
    assert _svg_metadata(important_svg) == generator.metadata_payload(
        "montana-important",
        important,
        len(generator.EDGES_MONTANA),
        reader,
        snapshot,
    )
    assert _svg_nodes(important_svg) == important
    generator.verify(important_svg, important, exhaustive=False)
    rendered = tmp_path / important_svg.name
    generator.important_svg("montana", paths, reader, rendered, snapshot)
    generator.verify(rendered, important, exhaustive=False)
    assert rendered.read_bytes() == generator._git_bytes("show", ":docs/architecture-montana-important.svg")


def test_montana_report_inventory_metrics_match_frozen_index_snapshot() -> None:
    """Bind one generated metric block and the surviving SVG to one index snapshot."""
    import tools.generate_montana_architecture_svgs as generator

    snapshot, frozen_paths, contents = _architecture_inventory()
    assert frozen_paths and contents
    svg_path = REPO_ROOT / "docs/architecture-montana-important.svg"

    expected = generator.current_metrics_bytes(
        snapshot, generator._git_bytes("show", ":docs/architecture-montana-important.svg")
    )
    assert generator._git_bytes("show", ":docs/current_candidate_metrics.md") == expected

    metrics = expected.decode("utf-8")
    svg_metadata = _svg_metadata(svg_path)
    assert f"| Source snapshot tree | `{snapshot.tree_sha}` |" in metrics
    assert f"| Source snapshot object manifest SHA-256 | `{snapshot.object_manifest_sha256()}` |" in metrics
    assert svg_metadata["source_tree_sha"] == snapshot.tree_sha
    assert svg_metadata["source_tree_file_count"] == len(snapshot.paths)

    report = _read(REPO_ROOT / "docs/MONTANA_REFACTOR_REPORT.md")
    metrics_link = "[generated current-candidate metrics](current_candidate_metrics.md)"
    assert report.count(metrics_link) >= 5
    assert "current_candidate_metrics.md" in report

    # The owner plan must authorize and require both shipped artifacts: the
    # generator writes them from one frozen snapshot, so a plan that
    # regenerates only the SVG leaves the metrics tree hash stale.
    roadmap = _read(REPO_ROOT / "ROADMAP.md")
    p3_amendment = roadmap[roadmap.index("* **P3**") : roadmap.index("* **P4**")]
    assert "docs/architecture-montana-important.svg" in p3_amendment
    assert "docs/current_candidate_metrics.md" in p3_amendment

    # The narrative is no longer a second numeric database. This structural
    # check rejects a newly worded contradictory aggregate instead of listing
    # every prose anchor that happened to exist when the guard was written.
    comma_number = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
    aggregate_claim = re.compile(
        r"(?i)(?<![\w.])\d(?:[\d,]*\d)?(?:\s+[a-z+/_-]+){0,4}\s+"
        r"(?:files?|paths?|nodes?|lines?|insertions?|deletions?|imports?|additions?|tests?|bytes?)\b"
    )
    # Compact suffix forms (the historical `130k lines` escape named in
    # MONTANA-REPORT-METRIC-FALSE-GREEN-234): the unit suffix is attached to
    # the digits, so the two patterns above cannot see them.
    compact_aggregate_claim = re.compile(
        r"(?i)(?<![\w.])\d+(?:\.\d+)?[kM](?:\s+[a-z+/_-]+){0,4}\s+"
        r"(?:files?|paths?|nodes?|lines?|insertions?|deletions?|imports?|additions?|tests?|bytes?)\b"
    )
    assert not comma_number.search(report)
    assert not aggregate_claim.search(report)
    assert not compact_aggregate_claim.search(report)

    mutant = report + "\nThe current candidate now claims 999999 newly measured source paths.\n"
    assert aggregate_claim.search(mutant)
    for compact_form in ("130k lines", "1M lines"):
        compact_mutant = report + f"\nThe campaign interim count was {compact_form} of source text.\n"
        assert compact_aggregate_claim.search(compact_mutant)
