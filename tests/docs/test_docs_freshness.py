"""Doc-lint: mechanical freshness invariants for the docs-as-product gate (E2).

No LLM, no fuzzy matching — every check below is a plain string/path
comparison against the live tree. Intentionally narrow where a broader
check would produce false positives (see docstrings per test).
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> list[str]:
    """Git-tracked repo-relative paths (posix), gitignored files excluded.

    Falls back to a filesystem walk if git is unavailable (e.g. a tarball
    checkout with no ``.git``) so this test degrades gracefully rather than
    erroring on an environment quirk unrelated to doc freshness.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [line for line in out.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        skip_dirs = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv"}
        return [
            p.relative_to(REPO_ROOT).as_posix()
            for p in REPO_ROOT.rglob("*")
            if p.is_file() and not any(part in skip_dirs for part in p.parts)
        ]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# (a) every console script in pyproject.toml [project.scripts] is named in
# docs/quickstart.md or docs/operator_manual.md. Word-boundary match (not
# preceded/followed by a word char or hyphen) so "cryodaq" doesn't
# false-positive off "cryodaq-engine".
# ---------------------------------------------------------------------------


def test_console_scripts_documented_in_quickstart_or_operator_manual():
    scripts = sorted(_pyproject()["project"]["scripts"])
    text = _read(REPO_ROOT / "docs" / "quickstart.md") + _read(
        REPO_ROOT / "docs" / "operator_manual.md"
    )
    missing = [s for s in scripts if not re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", text)]
    assert not missing, (
        "Console scripts from pyproject.toml [project.scripts] not documented "
        "in docs/quickstart.md or docs/operator_manual.md:\n" + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# (b) every top-level config/*.yaml file (git-tracked; "*.local.yaml"
# machine overrides are gitignored and excluded by construction, since
# _tracked_files() only returns tracked paths) is mentioned in at least one
# tracked doc. Non-recursive by design: config/themes/*.yaml and
# config/experiment_templates/*.yaml are documented via the glob itself
# (existing convention in README.md), not per-file.
# ---------------------------------------------------------------------------


def test_top_level_config_yaml_mentioned_in_some_doc():
    tracked = _tracked_files()
    config_yaml = sorted(
        p for p in tracked if p.startswith("config/") and p.count("/") == 1 and p.endswith(".yaml")
    )
    assert config_yaml, "expected at least one top-level config/*.yaml file"
    all_docs_text = "".join(_read(REPO_ROOT / p) for p in tracked if p.endswith(".md"))
    missing = [c for c in config_yaml if c not in all_docs_text]
    assert not missing, "config/*.yaml files not mentioned in any tracked doc:\n" + "\n".join(
        missing
    )


# ---------------------------------------------------------------------------
# (c) CHANGELOG.md's newest versioned entry (skipping "## [Unreleased]")
# must equal pyproject.toml's [project] version — catches a release that
# bumped one file but not the other.
# ---------------------------------------------------------------------------


def test_changelog_top_version_matches_pyproject():
    text = _read(REPO_ROOT / "CHANGELOG.md")
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions, "CHANGELOG.md has no '## [X.Y.Z]' version heading"
    pyproject_version = _pyproject()["project"]["version"]
    assert versions[0] == pyproject_version, (
        f"CHANGELOG.md top version [{versions[0]}] != pyproject.toml version "
        f"[{pyproject_version}]"
    )


# ---------------------------------------------------------------------------
# (d) no tracked doc references a repo-relative path (in backticks) that
# does not exist on disk. Mechanical, deliberately narrow to avoid false
# positives:
#
# - only paths starting under docs/, config/, src/, tests/, tools/,
#   scripts/, build_scripts/, tsp/ (source-tree-like; NOT data/ or logs/,
#   which are runtime output dirs that legitimately don't exist in a fresh
#   checkout)
# - CHANGELOG.md is exempt as a source doc — it is an append-only
#   historical ledger, expected to reference files removed in later
#   releases (e.g. the Alarm Engine v1 config)
# - docs/design-system/** is exempt as a source of references — a
#   separately-governed UI spec (see docs/design-system/governance/) whose
#   component-file citations predate the MainWindowV2 refactor in places;
#   reconciling that subtree is out of scope for this gate
# - glob/placeholder markers (* < > { }) are skipped — e.g.
#   "config/themes/*.yaml", "data/experiments/<id>/metadata.json"
# - any path containing ".local." is skipped — gitignored machine-local
#   override files that intentionally don't exist until an operator copies
#   them from a ".example" template
# - a trailing ":N" or ":N-M" line-range citation is stripped before the
#   existence check
# - the final path segment must end in a lowercase alnum "extension"
#   (1-6 chars) — filters out dotted Python references like
#   "base.InstrumentDriver" that are not file paths at all
# ---------------------------------------------------------------------------

_PATH_PREFIXES = ("docs/", "config/", "src/", "tests/", "tools/", "scripts/", "build_scripts/", "tsp/")
_EXEMPT_SOURCE_PREFIXES = ("docs/design-system/",)
_LINE_REF_RE = re.compile(r":\d+(-\d+)?$")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _is_path_candidate(span: str) -> bool:
    if not any(span.startswith(p) for p in _PATH_PREFIXES):
        return False
    if any(ch in span for ch in "*<>{}"):
        return False
    if ".local." in span:
        return False
    last_seg = span.rsplit("/", 1)[-1]
    if "." not in last_seg:
        return False
    ext = _LINE_REF_RE.sub("", last_seg.rsplit(".", 1)[-1])
    return bool(re.fullmatch(r"[a-z0-9]{1,6}", ext))


def test_no_dead_repo_paths_referenced_in_docs():
    dead: dict[str, list[str]] = {}
    for p in _tracked_files():
        if not p.endswith(".md") or p == "CHANGELOG.md":
            continue
        if p.startswith(_EXEMPT_SOURCE_PREFIXES):
            continue
        text = _read(REPO_ROOT / p)
        for span in _BACKTICK_RE.findall(text):
            if not _is_path_candidate(span):
                continue
            target = _LINE_REF_RE.sub("", span)
            if not (REPO_ROOT / target).exists():
                dead.setdefault(span, []).append(p)
    assert not dead, "Dead repo-relative paths referenced in docs:\n" + "\n".join(
        f"{path!r} in {sorted(set(srcs))}" for path, srcs in sorted(dead.items())
    )
