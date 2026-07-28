"""PARTIAL C1 seal for EngineQueryClient adapter availability.

This filesystem/AST guard covers each ``async def`` under the assistant query
adapter package that awaits ``self._client.call``.  It rejects a bare ``None``
after that call unless the result is explicitly declared absent by a
reply-shape predicate, and requires the failed-reply branch to return a typed
result instead.

It intentionally does not seal these C1 rows, whose blast radius remains an
operator-facing false absence: E4-007 (RagSearcher index/dimension failure
becoming an empty search), E4-008 (RAGAdapter has no EngineQueryClient call),
E4-009 (CompositeAdapter snapshot failure), E4-010 (cached snapshot
staleness), and E4-011 (Telegram cached readings reported as active).
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_EXPLICIT_ABSENCE_PREDICATES = {
    "reply_declares_absence",
    "reply_declares_empty_sequence",
    "reply_declares_no_data",
}


def _called_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_engine_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "call"
        and isinstance(node.value.func.value, ast.Attribute)
        and node.value.func.value.attr == "_client"
    )


def _has_availability_keywords(call: ast.Call) -> bool:
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
    return (
        isinstance(keywords.get("available"), ast.Constant)
        and keywords["available"].value is False
        and isinstance(keywords.get("stale"), ast.Constant)
        and keywords["stale"].value is True
        and "reason" in keywords
        and not (isinstance(keywords["reason"], ast.Constant) and not str(keywords["reason"].value).strip())
    )


def _return_has_availability_contract(node: ast.Return, class_node: ast.ClassDef | None) -> bool:
    if not isinstance(node.value, ast.Call):
        return False
    if _has_availability_keywords(node.value):
        return True
    if (
        class_node is None
        or not isinstance(node.value.func, ast.Attribute)
        or node.value.func.attr != "_unavailable"
    ):
        return False
    return any(
        _has_availability_keywords(call)
        for helper in class_node.body
        if isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)) and helper.name == "_unavailable"
        for returned in ast.walk(helper)
        if isinstance(returned, ast.Return) and isinstance(returned.value, ast.Call)
        for call in (returned.value,)
    )


def _is_failure_branch(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Call)
        and _called_name(test.operand.func) == "reply_is_success"
    )


def _is_explicit_absence_branch(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and _called_name(node.test.func) in _EXPLICIT_ABSENCE_PREDICATES
    )


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _has_ancestor(node: ast.AST, parents: dict[ast.AST, ast.AST], predicate) -> bool:
    while node in parents:
        node = parents[node]
        if predicate(node):
            return True
    return False


def _violations(root: Path) -> list[str]:
    adapters = root / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters"
    violations: list[str] = []
    for path in sorted(adapters.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = _parent_map(tree)
        for method in (node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)):
            calls = [node for node in ast.walk(method) if _is_engine_call(node)]
            if not calls:
                continue
            first_call = min(node.lineno for node in calls)
            class_node = next(
                (
                    parent
                    for parent in (parents.get(method),)
                    if isinstance(parent, ast.ClassDef)
                ),
                None,
            )
            failure_branches = [
                node for node in ast.walk(method) if isinstance(node, ast.If) and _is_failure_branch(node)
            ]
            if not any(
                any(
                    _return_has_availability_contract(node, class_node)
                    for node in ast.walk(branch)
                    if isinstance(node, ast.Return)
                )
                for branch in failure_branches
            ):
                violations.append(
                    f"{path.name}:{method.name}: failed reply does not return available=False, stale=True with reason"
                )
            for returned in (node for node in ast.walk(method) if isinstance(node, ast.Return)):
                if (
                    returned.lineno > first_call
                    and isinstance(returned.value, ast.Constant)
                    and returned.value.value is None
                    and not _has_ancestor(returned, parents, _is_explicit_absence_branch)
                ):
                    violations.append(
                        f"{path.name}:{method.name}:{returned.lineno}: "
                        "bare None after engine call is not explicit absence"
                    )
    return violations


def test_c1_engine_adapter_seal_accepts_current_adapters() -> None:
    assert _violations(_ROOT) == []


def test_c1_engine_adapter_seal_rejects_injected_conflation_then_accepts_restored_copy(tmp_path: Path) -> None:
    scratch = tmp_path / "repo"
    shutil.copytree(_ROOT / "src", scratch / "src")
    target = scratch / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters" / "archive_adapter.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(
        original
        + "\n\nclass _InjectedViolation:\n"
        + "    async def lost_failure(self):\n"
        + "        reply = await self._client.call({'cmd': 'injected'})\n"
        + "        if not reply_is_success(reply):\n"
        + "            return None\n",
        encoding="utf-8",
    )

    violations = _violations(scratch)
    assert violations[0] == (
        "archive_adapter.py:lost_failure: failed reply does not return available=False, stale=True with reason"
    )
    assert violations[1].endswith("bare None after engine call is not explicit absence")

    target.write_text(original, encoding="utf-8")
    assert _violations(scratch) == []
