"""Run one GitHub Actions test partition from an exported candidate tree."""

from __future__ import annotations

import argparse
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
)
_TAIL = ("--tb=short", "-v", "--timeout=120", "--timeout-method=thread")
_SUITES: dict[str, tuple[tuple[str, ...], ...]] = {
    "core": ((_PYTEST + ("tests/core", "tests/health", "tests/engine_wiring") + _TAIL),),
    "gui": (
        (_PYTEST + ("tests/gui/test_app_palette.py",) + _TAIL),
        (
            _PYTEST
            + (
                "tests/gui/shell/operator_components/test_freshness_and_card.py",
                "tests/gui/shell/views/test_operator_display.py",
            )
            + _TAIL
        ),
        (
            _PYTEST
            + (
                "tests/gui",
                "--deselect",
                "tests/gui/test_app_palette.py",
                "--deselect",
                "tests/gui/shell/operator_components/test_freshness_and_card.py",
                "--deselect",
                "tests/gui/shell/views/test_operator_display.py",
            )
            + _TAIL
        ),
    ),
    "agents": (
        (
            _PYTEST
            + (
                "tests/agents",
                "tests/periodic",
                "tests/reporting",
                "tests/notifications",
            )
            + _TAIL
        ),
    ),
    "remaining": (
        (
            _PYTEST
            + (
                "tests/",
                "--ignore=tests/core",
                "--ignore=tests/health",
                "--ignore=tests/engine_wiring",
                "--ignore=tests/gui",
                "--ignore=tests/agents",
                "--ignore=tests/periodic",
                "--ignore=tests/reporting",
                "--ignore=tests/notifications",
            )
            + _TAIL
        ),
    ),
}


def run_suite(suite: str, *, root: Path) -> int:
    commands = _SUITES.get(suite)
    if commands is None:
        raise ValueError(f"unknown candidate suite: {suite}")
    for index, command in enumerate(commands, start=1):
        print(f"candidate-suite={suite} command={index}/{len(commands)}", flush=True)
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(_SUITES), required=True)
    args = parser.parse_args(argv)
    return run_suite(args.suite, root=Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    raise SystemExit(main())
