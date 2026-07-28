"""Partial C1 seal for EngineQueryClient adapter availability.

This AST sweep follows ``await *.call(...)`` through same-class async helpers,
regardless of adapter class name or decorators.  In every reachable routine it
rejects a bare return, literal or locally-proven ``None``, ``or None``, and a
one-argument ``.get()`` return, unless an enclosing reply-shape predicate
explicitly declares absence.  It also requires a direct engine caller's
failed-reply branch to return a typed unavailable result.

It cannot prove runtime dispatch, values returned from another module, aliases
assembled at runtime, a helper selected dynamically, or ``None`` hidden in
arbitrary expressions or containers; conditional-expression branches that
directly return ``None`` are checked. It intentionally does not seal E4-007
through E4-011.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_EXPLICIT_ABSENCE_PREDICATES = {
    "reply_declares_absence",
    "reply_declares_empty_sequence",
    "reply_declares_no_data",
}
_KNOWN_PRODUCTION_VIOLATIONS: dict[str, str] = {}


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
    if class_node is None or not isinstance(node.value.func, ast.Attribute) or node.value.func.attr != "_unavailable":
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


def _class_for(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.ClassDef | None:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.ClassDef):
            return node
    return None


def _called_helpers(method: ast.AsyncFunctionDef) -> set[str]:
    return {
        name for call in ast.walk(method) if isinstance(call, ast.Call) if (name := _called_name(call.func)) is not None
    }


def _engine_reachable_methods(
    tree: ast.AST, parents: dict[ast.AST, ast.AST]
) -> tuple[set[ast.AsyncFunctionDef], set[ast.AsyncFunctionDef]]:
    methods = {node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)}
    direct = {method for method in methods if any(_is_engine_call(node) for node in ast.walk(method))}
    reachable = set(direct)
    changed = True
    while changed:
        additions = {
            method
            for method in methods
            if _called_helpers(method)
            & {reached.name for reached in reachable if _class_for(reached, parents) is _class_for(method, parents)}
        }
        changed = not additions <= reachable
        reachable |= additions
    return direct, reachable


def _locally_none_names(method: ast.AsyncFunctionDef, returned: ast.Return) -> set[str]:
    assignments: dict[str, ast.expr | None] = {}
    for node in sorted(ast.walk(method), key=lambda item: getattr(item, "lineno", -1)):
        if getattr(node, "lineno", returned.lineno) >= returned.lineno:
            continue
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        assignments.update({target.id: value for target in targets if isinstance(target, ast.Name)})
    return {name for name, value in assignments.items() if isinstance(value, ast.Constant) and value.value is None}


def _absent_expression_reason(value: ast.expr | None, method: ast.AsyncFunctionDef, returned: ast.Return) -> str | None:
    if value is None:
        return "bare return after engine query"
    if isinstance(value, ast.Constant) and value.value is None:
        return "None return after engine query"
    if isinstance(value, ast.Name) and value.id in _locally_none_names(method, returned):
        return "last local assignment is None before return after engine query"
    if isinstance(value, ast.IfExp):
        for branch in (value.body, value.orelse):
            if reason := _absent_expression_reason(branch, method, returned):
                return f"conditional expression {reason}"
    if (
        isinstance(value, ast.BoolOp)
        and isinstance(value.op, ast.Or)
        and any(isinstance(item, ast.Constant) and item.value is None for item in value.values)
    ):
        return "or None return after engine query"
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "get"
        and len(value.args) == 1
    ):
        return ".get() without default returned after engine query"
    return None


def _absent_return_reason(method: ast.AsyncFunctionDef, returned: ast.Return) -> str | None:
    return _absent_expression_reason(returned.value, method, returned)


def _violations(root: Path) -> list[str]:
    adapters = root / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters"
    if not adapters.is_dir():
        raise RuntimeError(f"C1 adapter tree is missing: {adapters}")
    paths = sorted(adapters.rglob("*.py"))
    if not paths:
        raise RuntimeError(f"C1 adapter tree contains no Python files: {adapters}")
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = _parent_map(tree)
        direct, reachable = _engine_reachable_methods(tree, parents)
        for method in reachable:
            for returned in (node for node in ast.walk(method) if isinstance(node, ast.Return)):
                reason = _absent_return_reason(method, returned)
                if reason and not _has_ancestor(returned, parents, _is_explicit_absence_branch):
                    violations.append(f"{path.name}:{method.name}:{returned.lineno}: {reason}")
        for method in direct:
            class_node = _class_for(method, parents)
            failure_branches = [
                node for node in ast.walk(method) if isinstance(node, ast.If) and _is_failure_branch(node)
            ]
            if not failure_branches or any(
                not (returns := [node for node in ast.walk(branch) if isinstance(node, ast.Return)])
                or not all(_return_has_availability_contract(node, class_node) for node in returns)
                for branch in failure_branches
            ):
                violations.append(
                    f"{path.name}:{method.name}: failed reply does not return available=False, stale=True with reason"
                )
    return sorted(violations)


def test_c1_engine_adapter_seal_accepts_current_adapters() -> None:
    assert _KNOWN_PRODUCTION_VIOLATIONS == {}
    assert _violations(_ROOT) == []


@pytest.mark.parametrize("root_name", ("missing", "empty"))
def test_c1_engine_adapter_seal_fails_open_for_a_missing_or_empty_adapter_tree(tmp_path: Path, root_name: str) -> None:
    root = tmp_path / root_name
    if root_name == "empty":
        (root / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="C1 adapter tree"):
        _violations(root)


def test_c1_engine_adapter_seal_rejects_multiple_conflations_then_accepts_restored_copy(tmp_path: Path) -> None:
    scratch = tmp_path / "repo"
    shutil.copytree(_ROOT / "src", scratch / "src")
    target = scratch / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters" / "archive_adapter.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(
        original
        + "\n\nclass _InjectedShape:\n"
        + "    @decorator\n"
        + "    async def helper_or_none(self):\n"
        + "        reply = await self._fetch_reply()\n"
        + "        return reply or None\n\n"
        + "    async def _fetch_reply(self):\n"
        + "        reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        if not reply_is_success(reply):\n"
        + "            return Result(available=False, stale=True, reason='injected')\n"
        + "        return Result(available=True, stale=False, reason='')\n\n"
        + "    async def early_none(self):\n"
        + "        reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        if not reply_is_success(reply):\n"
        + "            return Result(available=False, stale=True, reason='injected')\n"
        + "        if reply.get('skip'):\n"
        + "            return None\n"
        + "        return Result(available=True, stale=False, reason='')\n\n"
        + "    async def bare_return(self):\n"
        + "        reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        if not reply_is_success(reply):\n"
        + "            return Result(available=False, stale=True, reason='injected')\n"
        + "        return\n\n"
        + "    async def except_value_error(self):\n"
        + "        try:\n"
        + "            reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        except ValueError:\n"
        + "            return None\n"
        + "        if not reply_is_success(reply):\n"
        + "            return Result(available=False, stale=True, reason='injected')\n"
        + "        return Result(available=True, stale=False, reason='')\n\n"
        + "    async def finally_local_none(self):\n"
        + "        missing = None\n"
        + "        try:\n"
        + "            reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        finally:\n"
        + "            return missing\n\n"
        + "    async def get_without_default(self):\n"
        + "        reply = await self.transport.call({'cmd': 'injected'})\n"
        + "        if not reply_is_success(reply):\n"
        + "            return Result(available=False, stale=True, reason='injected')\n"
        + "        return reply.get('payload')\n",
        encoding="utf-8",
    )

    violations = _violations(scratch)
    for method, reason in {
        "helper_or_none": "or None return after engine query",
        "early_none": "None return after engine query",
        "bare_return": "bare return after engine query",
        "except_value_error": "None return after engine query",
        "finally_local_none": "last local assignment is None before return after engine query",
        "get_without_default": ".get() without default returned after engine query",
    }.items():
        assert any(f":{method}:" in finding and finding.endswith(reason) for finding in violations), violations

    target.write_text(original, encoding="utf-8")
    assert set(_violations(scratch)) == set(_KNOWN_PRODUCTION_VIOLATIONS)


_C1_PROOF_CASES = {
    "conditional_none": (
        "\nclass _InjectedConditional:\n"
        "    async def conditional_none(self):\n"
        "        reply = await self.transport.call({'cmd': 'injected'})\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        return None if reply.get('skip') else Result(available=True, stale=False, reason='')\n",
        "conditional expression None return after engine query",
    ),
    "helper_or_none": (
        "\nclass _InjectedHelper:\n"
        "    @decorator\n"
        "    async def helper_or_none(self):\n"
        "        return await self._fetch() or None\n"
        "    async def _fetch(self):\n"
        "        reply = await self.transport.call({'cmd': 'injected'})\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        return Result(available=True, stale=False, reason='')\n",
        "or None return after engine query",
    ),
    "early_none": (
        "\nclass _InjectedEarly:\n"
        "    async def early_none(self):\n"
        "        reply = await self.transport.call({'cmd': 'injected'})\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        if reply.get('skip'):\n"
        "            return None\n"
        "        return Result(available=True, stale=False, reason='')\n",
        "None return after engine query",
    ),
    "bare_return": (
        "\nclass _InjectedBare:\n"
        "    async def bare_return(self):\n"
        "        reply = await self.transport.call({'cmd': 'injected'})\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        return\n",
        "bare return after engine query",
    ),
    "except_value_error": (
        "\nclass _InjectedExcept:\n"
        "    async def except_value_error(self):\n"
        "        try:\n"
        "            reply = await self.transport.call({'cmd': 'injected'})\n"
        "        except ValueError:\n"
        "            return None\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        return Result(available=True, stale=False, reason='')\n",
        "None return after engine query",
    ),
    "finally_local_none": (
        "\nclass _InjectedFinally:\n"
        "    async def finally_local_none(self):\n"
        "        missing = None\n"
        "        try:\n"
        "            reply = await self.transport.call({'cmd': 'injected'})\n"
        "        finally:\n"
        "            return missing\n",
        "last local assignment is None before return after engine query",
    ),
    "get_without_default": (
        "\nclass _InjectedGet:\n"
        "    async def get_without_default(self):\n"
        "        reply = await self.transport.call({'cmd': 'injected'})\n"
        "        if not reply_is_success(reply):\n"
        "            return Result(available=False, stale=True, reason='injected')\n"
        "        return reply.get('payload')\n",
        ".get() without default returned after engine query",
    ),
}


def test_c1_engine_adapter_seal_proves_each_injected_shape_and_restoration(tmp_path: Path) -> None:
    for name, (injected, reason) in _C1_PROOF_CASES.items():
        scratch = tmp_path / name
        shutil.copytree(_ROOT / "src", scratch / "src")
        target = scratch / "src" / "cryodaq" / "agents" / "assistant" / "query" / "adapters" / "archive_adapter.py"
        original = target.read_text(encoding="utf-8")
        target.write_text(original + injected, encoding="utf-8")
        assert any(f":{name}:" in finding and finding.endswith(reason) for finding in _violations(scratch))
        target.write_text(original, encoding="utf-8")
        assert set(_violations(scratch)) == set(_KNOWN_PRODUCTION_VIOLATIONS)
