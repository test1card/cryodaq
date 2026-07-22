"""Run one GitHub Actions test partition from an exported candidate tree."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_PYTEST = (
    sys.executable,
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
)
_TAIL = ("--tb=short", "-v", "--timeout=120", "--timeout-method=thread")
ACTIVE_CHECKOUT_REMAINING_FILES = (
    "tests/docs/test_docs_freshness.py",
    "tests/test_claudemd_index.py",
)
ACTIVE_CHECKOUT_REMAINING_NODES = (
    "tests/scripts/test_soak_mock_stack_runner.py::test_controlled_environment_genuinely_collects_strict_exact_six",
    "tests/scripts/test_soak_mock_stack_runner.py::test_controlled_environment_genuinely_executes_strict_exact_six",
)
EXPORTED_REMAINING_EXCLUDED_FILES = ACTIVE_CHECKOUT_REMAINING_FILES
EXPORTED_REMAINING_EXCLUDED_NODES = ACTIVE_CHECKOUT_REMAINING_NODES

_SELECTIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "core": (("tests/core", "tests/health", "tests/engine_wiring"),),
    "gui": (
        ("tests/gui/test_app_palette.py",),
        (
            "tests/gui/shell/operator_components/test_freshness_and_card.py",
            "tests/gui/shell/views/test_operator_display.py",
        ),
        (
            "tests/gui",
            "--deselect",
            "tests/gui/test_app_palette.py",
            "--deselect",
            "tests/gui/shell/operator_components/test_freshness_and_card.py",
            "--deselect",
            "tests/gui/shell/views/test_operator_display.py",
        ),
    ),
    "agents": (
        (
            "tests/agents",
            "tests/periodic",
            "tests/reporting",
            "tests/notifications",
        ),
    ),
    "remaining": (
        (
            "tests/",
            "--ignore=tests/core",
            "--ignore=tests/health",
            "--ignore=tests/engine_wiring",
            "--ignore=tests/gui",
            "--ignore=tests/agents",
            "--ignore=tests/periodic",
            "--ignore=tests/reporting",
            "--ignore=tests/notifications",
            *(f"--ignore={path}" for path in EXPORTED_REMAINING_EXCLUDED_FILES),
            *(argument for node in EXPORTED_REMAINING_EXCLUDED_NODES for argument in ("--deselect", node)),
        ),
    ),
}


def suite_for_node(node: str) -> str:
    """Return the one default matrix suite that owns an exact pytest node."""

    path = node.split("::", 1)[0]
    if path.startswith(("tests/core/", "tests/health/", "tests/engine_wiring/")):
        return "core"
    if path.startswith("tests/gui/"):
        return "gui"
    if path.startswith(("tests/agents/", "tests/periodic/", "tests/reporting/", "tests/notifications/")):
        return "agents"
    if not path.startswith("tests/"):
        raise ValueError(f"candidate guard is not a pytest node: {node}")
    return "remaining"


def _suite_commands(suite: str, *, root: Path, basetemp: Path | None) -> tuple[tuple[str, ...], ...]:
    selections = _SELECTIONS.get(suite)
    if selections is None:
        raise ValueError(f"unknown candidate suite: {suite}")
    if basetemp is None:
        raw = os.environ.get("CRYODAQ_CANDIDATE_PYTEST_BASETEMP")
        if not raw:
            raise ValueError("candidate pytest basetemp is not bound")
        basetemp = Path(raw)
    resolved_root = root.resolve(strict=True)
    resolved_base = basetemp.resolve(strict=False)
    try:
        resolved_base.relative_to(resolved_root)
    except ValueError:
        pass
    else:
        raise ValueError("candidate pytest basetemp must be outside the exported tree")
    resolved_base.mkdir(parents=True, exist_ok=True)
    return tuple(
        _PYTEST + ("--basetemp", str(resolved_base / f"{suite}-{index}")) + selection + _TAIL
        for index, selection in enumerate(selections, start=1)
    )


def run_suite(suite: str, *, root: Path, basetemp: Path | None = None) -> int:
    commands = _suite_commands(suite, root=root, basetemp=basetemp)
    failures: list[tuple[int, int]] = []
    for index, command in enumerate(commands, start=1):
        print(f"candidate-suite={suite} command={index}/{len(commands)}", flush=True)
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            failures.append((index, completed.returncode))
    if failures:
        print(f"candidate-suite={suite} failures={failures!r}", file=sys.stderr, flush=True)
        return failures[0][1] or 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(_SELECTIONS), required=True)
    args = parser.parse_args(argv)
    return run_suite(args.suite, root=Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    raise SystemExit(main())
