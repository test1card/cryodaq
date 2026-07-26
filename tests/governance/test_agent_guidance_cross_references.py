"""Guard: named section cross-references in ACTIVE agent guidance must resolve.

Defect class prevented (see docs/adr/003-governance-as-enforcement.md): an
active agent-authority document tells a fresh or compacted agent to read
``FILE.md``, especially "<Named Section>", but that section does not exist in
``FILE.md``. The mandatory startup ritual then either cannot locate current
authority or is pushed toward treating archived campaign material as live
policy. This is invisible to the existing freshness gates, which resolve
backtick file paths (tests/docs/test_docs_freshness.py::
test_no_dead_repo_paths_referenced_in_docs) and generated-artifact freshness,
not in-file section anchors.

Design choice (soundness over coverage): instead of scanning freeform prose
across the whole doc corpus with a fragile regex — which would fire on any
quoted phrase that resembles a heading — this guard resolves an explicit,
maintainer-curated registry of load-bearing ``(source_doc, target_doc,
heading)`` triples. Every entry is intentional, so false positives are
impossible by construction; the only parsing is the well-defined ATX-heading
grammar plus whitespace normalization, applied to the single registered target
file. Add a new entry whenever an agent-authority document points an agent at a
named section that must keep existing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Each triple: (source guidance doc, referenced doc, section heading that must
# exist as a real ATX heading in the referenced doc). The heading text must
# also appear in the source doc so the registry cannot drift from what the
# document actually says.
AGENT_GUIDANCE_SECTION_REFERENCES: list[tuple[str, str, str]] = [
    (
        "docs/MONTANA_IMPLEMENTATION_AGENT_SPEC.md",
        "ROADMAP.md",
        "Current milestone \u2014 software-side pre-lab readiness",
    ),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _headings(text: str) -> set[str]:
    """ATX headings outside fenced code blocks, whitespace-normalized.

    Fenced blocks (``` or ~~~ at line start) are skipped so a pseudo-heading
    inside an example cannot satisfy a real cross-reference.
    """
    headings: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.add(_normalize(match.group(2)))
    return headings


def _resolve(repo_root: Path, source: str, target: str, heading: str) -> None:
    """Resolve one registered cross-reference or raise AssertionError.

    Pure filesystem check (no Git), so the negative test can exercise it on
    tmp_path fixtures without a repository.
    """
    source_path = repo_root / source
    target_path = repo_root / target
    if not source_path.is_file():
        raise AssertionError(f"source guidance doc not found: {source}")
    if not target_path.is_file():
        raise AssertionError(f"referenced doc not found: {source} -> {target}")
    want = _normalize(heading)
    if want not in _headings(_read(target_path)):
        raise AssertionError(
            f"{source} directs agents to section {heading!r} in {target}, but no such ATX heading exists in {target}."
        )
    if want not in _normalize(_read(source_path)):
        raise AssertionError(
            f"registry says {source} references {heading!r}, but that text is "
            f"not present in {source}; update the registry or restore the reference."
        )


def test_registered_section_cross_references_resolve() -> None:
    for source, target, heading in AGENT_GUIDANCE_SECTION_REFERENCES:
        _resolve(REPO_ROOT, source, target, heading)


def test_guard_rejects_missing_renamed_fenced_and_unmentioned_headings(
    tmp_path: Path,
) -> None:
    # Correct reference resolves cleanly.
    (tmp_path / "TARGET.md").write_text("# Title\n\n## Real Section \u2014 live\n\nbody\n", encoding="utf-8")
    (tmp_path / "SOURCE.md").write_text('read TARGET.md, especially "Real Section \u2014 live"\n', encoding="utf-8")
    _resolve(tmp_path, "SOURCE.md", "TARGET.md", "Real Section \u2014 live")

    cases = [
        # heading absent from target
        ("# Title\n\n## Unrelated\n", 'esp "Real"\n', "no such ATX heading"),
        # heading renamed in target
        ("# Title\n\n## Real Section \u2014 renamed\n", 'esp "Real \u2014 live"\n', "no such ATX heading"),
        # heading only inside a fenced code block must not count
        ("# Title\n\n```\n## Fenced Heading\n```\n", 'esp "Fenced Heading"\n', "no such ATX heading"),
        # heading exists in target but source no longer mentions it (registry drift)
        ("# Title\n\n## Real Section \u2014 live\n", 'esp "Something else"\n', "not present in"),
    ]
    for target_text, source_text, pattern in cases:
        (tmp_path / "TARGET.md").write_text(target_text, encoding="utf-8")
        (tmp_path / "SOURCE.md").write_text(source_text, encoding="utf-8")
        with pytest.raises(AssertionError, match=pattern):
            _resolve(tmp_path, "SOURCE.md", "TARGET.md", "Real Section \u2014 live")
