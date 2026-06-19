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


def test_changelog_documents_current_version():
    """The current project version (pyproject) must have a CHANGELOG entry.

    Derived from pyproject so it can't go stale: a release that bumps the version
    without a changelog entry fails here (the old fixed 0.51–0.53.2 list silently
    stayed green long after the project reached 0.56.x)."""
    import tomllib

    root = Path(__file__).parents[1]
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    with (root / "pyproject.toml").open("rb") as fh:
        version = tomllib.load(fh)["project"]["version"]
    assert f"[{version}]" in text, (
        f"CHANGELOG.md has no entry for the current version [{version}]"
    )
