"""TEST-SOURCE-OFF-RESULT-001: driver OFF doubles use the production result contract."""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS_ROOT = Path(__file__).parents[1]
_THIS_FILE = Path(__file__).resolve()
_INTENTIONAL_INVALID_SCOPES = {
    ("core/test_reviewed_source_disconnect.py", "test_truthy_non_boolean_proof_cannot_authorize_disconnect"),
    ("core/test_safety_fixes.py", "test_interlock_stop_source_rejects_truthy_non_bool_off_evidence"),
    ("core/test_safety_operator_snapshot_owner.py", "test_second_channel_unverified_target_fails_closed"),
    ("core/test_source_off_result_consumers.py", "_OffDriver.emergency_off"),
    ("core/test_source_off_result_consumers.py", "test_watchdog_ack_accepts_only_device_reported_off"),
}
_OFF_MEMBERS = {
    "COMMAND_ACCEPTED",
    "DEVICE_REPORTED_OFF",
    "PHYSICAL_STATE_UNKNOWN",
}


def _attribute_parts(node: ast.AST) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _is_source_off_result(node: ast.AST | None) -> bool:
    parts = _attribute_parts(node) if node is not None else []
    return len(parts) >= 2 and parts[-2] == "SourceOffResult" and parts[-1] in _OFF_MEMBERS


def _annotation_is_source_off_result(node: ast.AST | None) -> bool:
    parts = _attribute_parts(node) if node is not None else []
    return bool(parts) and parts[-1] == "SourceOffResult"


def _literal_bool_return(function: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and type(node.value.value) is bool
        for node in ast.walk(function)
    )


def _enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    scopes: list[str] = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append(current.name)
        elif isinstance(current, ast.ClassDef):
            scopes.append(current.name)
    if scopes and scopes[0] == "emergency_off" and len(scopes) > 1:
        return f"{scopes[1]}.emergency_off"
    return scopes[0] if scopes else "<module>"


def _find_named_function(
    name: str,
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
    tree: ast.Module,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            matches = [
                child
                for child in ast.walk(current)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name
            ]
            if matches:
                return min(matches, key=lambda child: abs(child.lineno - node.lineno))
    matches = [
        child
        for child in ast.walk(tree)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name
    ]
    return min(matches, key=lambda child: abs(child.lineno - node.lineno)) if matches else None


def _function_result_is_typed(function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
    return (
        function is not None
        and _annotation_is_source_off_result(function.returns)
        and not _literal_bool_return(function)
    )


def _is_exception_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    parts = _attribute_parts(node.func)
    return bool(parts) and (parts[-1].endswith("Error") or parts[-1].endswith("Exception"))


def test_driver_level_emergency_off_doubles_return_source_off_result() -> None:
    offenders: list[str] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if path.resolve() == _THIS_FILE:
            continue
        relative = path.relative_to(_TESTS_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

        for node in ast.walk(tree):
            scope = _enclosing_scope(node, parents)
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "emergency_off"
                and isinstance(parents.get(node), ast.ClassDef)
            ):
                scope = f"{parents[node].name}.emergency_off"
            if (relative, scope) in _INTENTIONAL_INVALID_SCOPES:
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "emergency_off":
                annotation = ast.unparse(node.returns) if node.returns is not None else ""
                if annotation.startswith("dict["):
                    continue
                if not _function_result_is_typed(node):
                    offenders.append(f"{relative}:{node.lineno}: emergency_off must return SourceOffResult")
                continue

            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                parts = _attribute_parts(target)
                if "safety_manager" in parts:
                    continue
                kind = ""
                if parts[-1:] == ["emergency_off"]:
                    kind = "double"
                elif parts[-2:] == ["emergency_off", "return_value"]:
                    kind = "return_value"
                elif parts[-2:] == ["emergency_off", "side_effect"]:
                    kind = "side_effect"
                if not kind:
                    continue

                value = node.value
                if kind == "return_value":
                    valid = _is_source_off_result(value)
                elif kind == "side_effect":
                    valid = isinstance(value, ast.Constant) and value.value is None
                    valid = valid or _is_exception_call(value)
                    if isinstance(value, ast.Name):
                        valid = valid or _function_result_is_typed(_find_named_function(value.id, node, parents, tree))
                elif isinstance(value, ast.Name):
                    valid = _function_result_is_typed(_find_named_function(value.id, node, parents, tree))
                elif isinstance(value, ast.Call) and _attribute_parts(value.func)[-1:] == ["AsyncMock"]:
                    keywords = {keyword.arg: keyword.value for keyword in value.keywords if keyword.arg is not None}
                    valid = _is_source_off_result(keywords.get("return_value"))
                    side_effect = keywords.get("side_effect")
                    if side_effect is not None:
                        valid = _is_exception_call(side_effect)
                        if isinstance(side_effect, ast.Name):
                            valid = valid or _function_result_is_typed(
                                _find_named_function(side_effect.id, node, parents, tree)
                            )
                else:
                    valid = False
                if not valid:
                    offenders.append(f"{relative}:{node.lineno}: driver OFF double has a non-SourceOffResult result")

    assert offenders == [], "\n" + "\n".join(offenders)
