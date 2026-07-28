"""Seal C2: physical identity must not be inferred from identifier spelling."""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path

_SOURCE_DIRS = ("storage", "reporting", "analytics")
_IDENTIFIER_FIELDS = frozenset({"channel", "channel_id", "instrument_id"})
_STRING_METHODS = frozenset({"casefold", "endswith", "lower", "replace", "split", "startswith", "upper"})
_REGEX_METHODS = frozenset({"compile", "findall", "finditer", "fullmatch", "match", "search"})

# Each exemption must be a (relative path, line, reason) tuple.  C2 has no
# exemptions: legacy rows are neutral and no source module may infer semantics
# from their identifiers.
_ALLOWLIST: dict[tuple[str, int], str] = {}


def _root() -> Path:
    configured = os.environ.get("CRYODAQ_C2_GUARD_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[2]


def _is_identifier(expression: ast.AST) -> bool:
    if isinstance(expression, ast.Attribute):
        return expression.attr in _IDENTIFIER_FIELDS
    return isinstance(expression, ast.Name) and expression.id in _IDENTIFIER_FIELDS


def _has_identifier(expression: ast.AST) -> bool:
    return any(_is_identifier(node) for node in ast.walk(expression))


def _is_string_literal(expression: ast.AST) -> bool:
    return isinstance(expression, ast.Constant) and isinstance(expression.value, str)


def _is_identifier_name(target: ast.AST) -> bool:
    return isinstance(target, ast.Name) and target.id.endswith(("channel", "channel_id", "instrument_id"))


def _derived_identifier(expression: ast.AST) -> bool:
    if isinstance(expression, ast.JoinedStr):
        return _has_identifier(expression)
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
        return _has_identifier(expression)
    return False


def _literal_identifier_from_config(expression: ast.AST) -> bool:
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "get"
        and len(expression.args) >= 2
        and _is_string_literal(expression.args[1])
    )


def _violations(root: Path) -> list[str]:
    findings: list[str] = []
    for directory in _SOURCE_DIRS:
        for path in sorted((root / "src" / "cryodaq" / directory).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            for node in ast.walk(tree):
                reason: str | None = None
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in _STRING_METHODS and _is_identifier(node.func.value):
                        reason = f"identifier string method {node.func.attr}()"
                    elif (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "re"
                        and node.func.attr in _REGEX_METHODS
                        and any(_has_identifier(argument) for argument in node.args)
                    ):
                        reason = f"regular expression {node.func.attr}() over an identifier"
                elif isinstance(node, ast.Compare):
                    operands = (node.left, *node.comparators)
                    if any(_is_identifier(operand) for operand in operands) and any(
                        _is_string_literal(operand) for operand in operands
                    ):
                        if any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
                            reason = "string-membership test over an identifier"
                        elif any(isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops):
                            reason = "literal comparison over an identifier"
                elif isinstance(node, ast.Assign) and _derived_identifier(node.value) and any(
                    _is_identifier_name(target) for target in node.targets
                ):
                    reason = "identifier fabricated from another identifier"
                elif (
                    isinstance(node, ast.AnnAssign)
                    and _derived_identifier(node.value)
                    and _is_identifier_name(node.target)
                ):
                    reason = "identifier fabricated from another identifier"
                elif isinstance(node, ast.Assign) and _is_string_literal(node.value) and any(
                    isinstance(target, ast.Name)
                    and target.id.startswith("DEFAULT_")
                    and _is_identifier_name(target)
                    for target in node.targets
                ):
                    reason = "literal identifier default"
                elif (
                    isinstance(node, ast.AnnAssign)
                    and _is_string_literal(node.value)
                    and isinstance(node.target, ast.Name)
                    and node.target.id.startswith("DEFAULT_")
                    and _is_identifier_name(node.target)
                ):
                    reason = "literal identifier default"
                elif isinstance(node, ast.Assign) and _literal_identifier_from_config(node.value) and any(
                    _is_identifier_name(target) for target in node.targets
                ):
                    reason = "literal identifier fallback from configuration"
                if reason and (relative, node.lineno) not in _ALLOWLIST:
                    findings.append(f"{relative}:{node.lineno}: {reason}")
    return findings


def test_c2_descriptor_selection_guard() -> None:
    assert _violations(_root()) == []


def test_c2_descriptor_selection_guard_detects_a_new_channel_suffix_predicate(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    shutil.copytree(_root() / "src", scratch / "src")
    target = scratch / "src" / "cryodaq" / "reporting" / "sections.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef _injected_bad_selection(item):\n"
        + "    return item.channel.endswith('/power')\n",
        encoding="utf-8",
    )

    assert _violations(scratch) == [
        finding
        for finding in _violations(scratch)
        if finding.endswith("identifier string method endswith()")
    ]
