"""Small enforceable prohibition for mutation-capable Ruff recipes."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RECIPE_PREFIXES = (".github/", "scripts/", "tools/")
_RECIPE_NAMES = {
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "Makefile",
    "noxfile.py",
    "pyproject.toml",
    "tox.ini",
}
_RECIPE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".json",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}


def _tracked_recipes() -> list[tuple[str, Path]]:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        timeout=20,
    )
    names = completed.stdout.decode("utf-8", errors="strict").split("\0")
    selected: list[tuple[str, Path]] = []
    for relative in names:
        if not relative:
            continue
        path = ROOT.joinpath(*relative.split("/"))
        named_recipe = Path(relative).name in _RECIPE_NAMES
        selected_recipe = relative.startswith(_RECIPE_PREFIXES) or named_recipe
        if selected_recipe and (named_recipe or path.suffix.casefold() in _RECIPE_SUFFIXES | {""}):
            selected.append((relative, path))
    return selected


def _normalized(command: str) -> str:
    return re.sub(r"[\s,\x27\x22\[\](){}]+", " ", command.casefold()).strip()


def _ruff_violation(command: str) -> str | None:
    normalized = _normalized(command)
    if "ruff-format" in normalized:
        return "ruff-format hook is mutation-capable"
    match = re.search(r"\bruff(?:\.exe)?\s+(format|check)\b", normalized)
    if match is None:
        return None
    mode = match.group(1)
    if mode == "format" and not ({"--check", "--diff"} & set(normalized.split())):
        return "ruff format lacks a read-only --check/--diff mode"
    if "--no-cache" not in normalized:
        return "Ruff invocation lacks --no-cache"
    forbidden = ("--fix", "--fix-only", "--unsafe-fixes")
    if any(flag in normalized for flag in forbidden):
        return "ruff check uses a mutation-capable fix flag"
    return None


def _python_argv_candidates(text: str) -> list[str]:
    tree = ast.parse(text)
    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "ruff" in node.value.casefold():
            candidates.append(node.value)
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        values: list[str] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                values.append(element.value)
        if values and any("ruff" in value.casefold() for value in values):
            candidates.append(" ".join(values))
    return candidates


def test_tracked_recipes_forbid_mutating_ruff_modes() -> None:
    violations: list[str] = []
    for relative, path in _tracked_recipes():
        text = path.read_text(encoding="utf-8", errors="strict")
        candidates = list(text.splitlines())
        if path.suffix.casefold() == ".py":
            candidates.extend(_python_argv_candidates(text))
        for command in candidates:
            reason = _ruff_violation(command)
            if reason is not None:
                violations.append(f"{relative}: {reason}: {command.strip()}")
    assert violations == []


def test_mutating_formatter_wrapper_is_absent() -> None:
    assert not (ROOT / "tools" / "agent_formatter_gate.py").exists()
    policy_paths = [
        ROOT / "AGENTS.md",
        ROOT / "governance" / "agent_preventions.yaml",
        *(path for _relative, path in _tracked_recipes()),
    ]
    stale_references: list[str] = []
    for path in policy_paths:
        text = path.read_text(encoding="utf-8", errors="strict")
        if "tools/agent_formatter_gate.py" in text or "FORMATTER-PREIMAGE-ATOMICITY-020" in text:
            stale_references.append(path.relative_to(ROOT).as_posix())
    assert stale_references == []

    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8", errors="strict")
    assert "ruff format --check --no-cache" in agents
    assert "ruff format --diff --no-cache" in agents
    assert "ruff check --no-cache" in agents
    normalized_agents = " ".join(agents.lower().split())
    assert "formatting corrections are explicit reviewed patches" in normalized_agents
