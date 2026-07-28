"""Run registry-selected tests that require the exact Git checkout."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.check_python_compile import compile_python_tree
from tools.ci_candidate_runner import _TAIL, _strict_guard_command, _validate_strict_guard_receipt
from tools.ci_guard_execution import active_guard_specs, checkout_execution_selection, current_guard_platform

# The sealed candidate disables autoload; this checkout runner must not reuse its explicit plugin list.
_PYTEST = (sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"exact checkout verification failed: git {' '.join(arguments)}")
    return completed.stdout.strip()


def _verify_checkout(root: Path, revision: str) -> None:
    if _git(root, "rev-parse", "HEAD") != revision:
        raise RuntimeError("exact checkout HEAD does not match the requested revision")
    _git(root, "diff", "--quiet")
    _git(root, "diff", "--cached", "--quiet")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("exact checkout has tracked or untracked changes")


def run_suite(suite: str, *, root: Path, revision: str, basetemp: Path) -> int:
    """Execute all and only the registry-selected exact-checkout tests once."""

    root = root.resolve(strict=True)
    _verify_checkout(root, revision)
    compile_python_tree(root)
    files, nodes = checkout_execution_selection(root, suite)
    file_set = set(files)
    selected_nodes = tuple(node for node in nodes if node.split("::", 1)[0] not in file_set)
    platform = current_guard_platform()
    guard_specs = active_guard_specs(root, suite, platform=platform, execution_root="git-index")
    guard_nodes = tuple(spec.node for spec in guard_specs)
    basetemp.mkdir(parents=True, exist_ok=True)

    strict = _strict_guard_command(
        suite,
        active_nodes=guard_nodes,
        basetemp=basetemp,
        execution_root="git-index",
        pytest_command=_PYTEST,
    )
    if strict is not None:
        completed = subprocess.run(strict, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)
        if completed.returncode:
            return completed.returncode
        _validate_strict_guard_receipt(
            completed.stdout + completed.stderr,
            suite=suite,
            expected=guard_nodes,
            expected_platforms={spec.node: spec.platform for spec in guard_specs},
            platform=platform,
        )

    ordinary = (*files, *selected_nodes)
    if ordinary:
        command = _PYTEST + ("--basetemp", str(basetemp / "ordinary"), *ordinary)
        command += tuple(argument for node in guard_nodes for argument in ("--deselect", node)) + _TAIL
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode:
            return completed.returncode
    _verify_checkout(root, revision)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--suite", choices=("remaining",), required=True)
    parser.add_argument("--basetemp", type=Path, required=True)
    args = parser.parse_args(argv)
    return run_suite(args.suite, root=args.repository, revision=args.revision, basetemp=args.basetemp)


if __name__ == "__main__":
    raise SystemExit(main())
