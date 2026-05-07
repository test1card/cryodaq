"""F-CHANGELOG-Audit: structural validation of CHANGELOG.md."""
import re
from pathlib import Path


def test_changelog_exists():
    assert (Path(__file__).parents[1] / "CHANGELOG.md").exists()


def test_changelog_has_unreleased_section():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text


def test_changelog_versions_in_descending_order():
    """Versions sorted newest-first per Keep a Changelog convention."""
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"## \[(\d+\.\d+\.\d+)\]", text)
    parsed = [tuple(int(p) for p in v.split(".")) for v in versions]
    assert parsed == sorted(parsed, reverse=True), (
        f"Versions not in descending order: {versions}"
    )


def test_changelog_recent_versions_present():
    """v0.51.0 → v0.53.2 all present in CHANGELOG.md."""
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    expected = [
        "0.51.0", "0.52.0", "0.52.1", "0.52.2",
        "0.52.10", "0.52.11", "0.53.0", "0.53.1", "0.53.2",
    ]
    for v in expected:
        assert f"[{v}]" in text, f"Missing version {v} in CHANGELOG.md"
