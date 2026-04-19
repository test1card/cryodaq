"""Phase III.A — accent / status decoupling invariants.

Ensures STATUS_OK is used only in status-display contexts inside the
shell overlays, NOT in button backgrounds, active-tab indicators, or
selection handlers. Regression guard against the Phase II state where
primary buttons + mode badges rendered safety-green.

Tests are grep-based — they assert on source text, not on rendered
Qt widgets — so they run fast and catch the «mechanical replace that
broke status display» and «new button added with STATUS_OK bg» failure
modes without requiring a QApplication.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OVERLAYS_DIR = _REPO_ROOT / "src" / "cryodaq" / "gui" / "shell" / "overlays"
_SHELL_DIR = _REPO_ROOT / "src" / "cryodaq" / "gui" / "shell"
_DASHBOARD_DIR = _REPO_ROOT / "src" / "cryodaq" / "gui" / "dashboard"

# Sites cleared by Phase III.A migration — each must assert its
# STATUS_OK occurrences are status-only, and must NOT re-introduce
# STATUS_OK in a button/primary/selection context.
_OVERLAY_FILES = (
    "alarm_panel.py",
    "archive_panel.py",
    "calibration_panel.py",
    "conductivity_panel.py",
    "instruments_panel.py",
    "keithley_panel.py",
    "operator_log_panel.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Patterns that indicate STATUS_OK is being used as UI-activation, not
# safety-status. Any hit here is a migration regression.
_FORBIDDEN_CONTEXTS = [
    # STATUS_OK as primary-button background
    re.compile(r'variant\s*==\s*"primary".*?theme\.STATUS_OK', re.DOTALL),
    # STATUS_OK as QPushButton background-color inline
    re.compile(
        r"QPushButton[^}]*background-color:\s*\{theme\.STATUS_OK\}",
        re.DOTALL,
    ),
]


@pytest.mark.parametrize("filename", _OVERLAY_FILES)
def test_primary_variant_does_not_use_status_ok(filename):
    """`_style_button("primary")` helpers used STATUS_OK as the button
    background — migrated to ACCENT in Phase III.A. Regression guard.

    Scans only the code body of the primary branch (between `if variant
    == "primary":` and the next elif/else keyword at the same
    indentation), not surrounding comments that may explain the
    migration."""
    src = _read(_OVERLAYS_DIR / filename)
    # Grab each line of the primary branch: the `if variant == "primary":`
    # line and then subsequent indented lines until we hit the next
    # `elif` / `else` at the same level.
    lines = src.splitlines()
    primary_lines: list[str] = []
    in_branch = False
    branch_indent: int | None = None
    for line in lines:
        stripped = line.lstrip()
        if not in_branch:
            if re.match(r'if\s+variant\s*==\s*"primary":', stripped):
                in_branch = True
                branch_indent = len(line) - len(stripped)
            continue
        # Inside branch — stop on next elif/else at the same indentation.
        assert branch_indent is not None
        cur_indent = len(line) - len(stripped)
        if stripped and cur_indent <= branch_indent and stripped.startswith(("elif", "else")):
            break
        # Skip comment-only lines — commit migration explanations are
        # allowed to mention STATUS_OK without being a migration loss.
        if stripped.startswith("#"):
            continue
        primary_lines.append(stripped)
    if not primary_lines:
        pytest.skip(f"{filename} has no _style_button primary branch")
    primary_body = "\n".join(primary_lines)
    assert "STATUS_OK" not in primary_body, (
        f"{filename}: primary button still uses STATUS_OK — III.A migration lost\n"
        f"Body:\n{primary_body}"
    )


def _strip_comments(source: str) -> str:
    """Remove Python line comments so that migration-explanation
    comments do not trip `STATUS_OK not in …` assertions."""
    out: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Inline comment — drop anything from the first '#' that is NOT
        # inside an f-string brace. Good-enough heuristic; source files
        # here don't have '#' in f-string paths.
        hash_idx = line.find("#")
        if hash_idx > 0 and "{" not in line[:hash_idx]:
            line = line[:hash_idx].rstrip()
        out.append(line)
    return "\n".join(out)


def test_top_watch_bar_experiment_badge_not_status_ok():
    """The «Эксперимент» mode badge previously rendered STATUS_OK
    background — reads as «this is healthy», not «you are in experiment
    mode». Phase III.A migrated to SURFACE_ELEVATED + FOREGROUND."""
    src = _strip_comments(_read(_SHELL_DIR / "top_watch_bar.py"))
    # Find the _update_mode_badge block
    match = re.search(r'if app_mode\s*==\s*"experiment":.*?(?=\belif\b|def\s)', src, re.DOTALL)
    assert match is not None, "could not locate experiment-mode badge block"
    block = match.group(0)
    assert "STATUS_OK" not in block, (
        "TopWatchBar experiment mode badge still uses STATUS_OK — III.A migration lost"
    )
    assert "SURFACE_ELEVATED" in block, (
        "TopWatchBar experiment mode badge should use SURFACE_ELEVATED per III.A spec"
    )


def test_experiment_card_mode_badge_not_status_ok():
    """ExperimentCard mirrors TopWatchBar mode-badge styling; migrated
    with the same rule."""
    src = _strip_comments(_read(_DASHBOARD_DIR / "experiment_card.py"))
    match = re.search(r"def _set_mode_badge_style.*?(?=\n    def\s|\nclass\s)", src, re.DOTALL)
    assert match is not None, "could not locate _set_mode_badge_style"
    block = match.group(0)
    assert "STATUS_OK" not in block, "ExperimentCard mode badge still uses STATUS_OK — III.A lost"
    assert "SURFACE_ELEVATED" in block, (
        "ExperimentCard mode badge should use SURFACE_ELEVATED per III.A"
    )


def test_conductivity_progress_chunk_uses_accent():
    """The auto-sweep progress bar chunk previously used STATUS_OK;
    Phase III.A migrated to ACCENT (progress is UI activation, not
    safety status)."""
    src = _read(_OVERLAYS_DIR / "conductivity_panel.py")
    match = re.search(
        r"QProgressBar::chunk\s*\{\{.*?background-color:\s*\{([^}]+)\}",
        src,
        re.DOTALL,
    )
    assert match is not None, "could not locate QProgressBar::chunk background"
    token_expr = match.group(1)
    assert "STATUS_OK" not in token_expr, (
        "conductivity_panel QProgressBar::chunk still uses STATUS_OK"
    )
    assert "ACCENT" in token_expr, "conductivity_panel QProgressBar::chunk should use ACCENT"


def test_status_ok_still_used_in_status_display_contexts():
    """Sanity guard: the migration should NOT have stripped STATUS_OK
    from legitimate status contexts (engine label, connection label,
    channel-health helpers, etc). At least one STATUS_OK usage must
    remain in the shell subtree — otherwise we over-migrated."""
    hit_count = 0
    for path in _SHELL_DIR.rglob("*.py"):
        if "test_" in path.name:
            continue
        if "STATUS_OK" in path.read_text(encoding="utf-8"):
            hit_count += 1
    assert hit_count >= 5, (
        f"STATUS_OK appears in only {hit_count} shell files — "
        f"over-migration suspected (expected ≥5 for status-display contexts)"
    )
