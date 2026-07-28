"""Seal C2: physical identity must not be inferred from identifier spelling.

This AST sweep detects direct fields and same-scope local aliases used in string
predicates, literal comparisons, regex matching, indexing/slicing, split calls,
identifier fabrication, and dict or match dispatch.  It cannot prove dynamic
construction, values crossing module boundaries, or identifiers assembled at
runtime; those remain outside this local AST sweep.
"""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path

_SOURCE_DIRS = ("storage", "reporting", "analytics")
_IDENTIFIER_FIELDS = frozenset({"channel", "channel_id", "instrument_id"})
_STRING_METHODS = frozenset({"casefold", "endswith", "lower", "replace", "split", "startswith", "upper"})
_REGEX_METHODS = frozenset({"fullmatch", "match", "search"})

# Each exemption is (bucket, reason). C2 has no exemptions: legacy rows are
# neutral and no source module may infer semantics from their identifiers.
_ALLOWLIST: dict[tuple[str, int], tuple[str, str]] = {
    (
        "src/cryodaq/reporting/periodic_renderer.py",
        142,
    ): (
        "BLOCKED-ON-SCHEMA",
        "_channel_key sorts thermometry-style names; replace this spelling inference with descriptor ordering.",
    ),
}


def _root() -> Path:
    configured = os.environ.get("CRYODAQ_C2_GUARD_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[2]


def _is_identifier(expression: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(expression, ast.Attribute)
        and expression.attr in _IDENTIFIER_FIELDS
        or isinstance(expression, ast.Name)
        and expression.id in (_IDENTIFIER_FIELDS | aliases)
    )


def _has_identifier(expression: ast.AST, aliases: set[str]) -> bool:
    return any(_is_identifier(node, aliases) for node in ast.walk(expression))


def _is_string_literal(expression: ast.AST) -> bool:
    return isinstance(expression, ast.Constant) and isinstance(expression.value, str)


def _is_literal_collection(expression: ast.AST) -> bool:
    return isinstance(expression, (ast.Tuple, ast.List, ast.Set)) and all(
        _is_string_literal(item) for item in expression.elts
    )


def _is_identifier_name(target: ast.AST) -> bool:
    return isinstance(target, ast.Name) and target.id.endswith(("channel", "channel_id", "instrument_id"))


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            if child is not scope and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            visit(child)

    visit(scope)
    return nodes


def _aliases(scope: ast.AST) -> tuple[set[str], set[str]]:
    aliases: set[str] = set()
    regexes: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in _scope_nodes(scope):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            if value is None:
                continue
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if _is_identifier(value, aliases) and not names <= aliases:
                aliases |= names
                changed = True
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "compile"
                and not names <= regexes
            ):
                regexes |= names
                changed = True
    return aliases, regexes


def _is_regex_call(node: ast.Call, aliases: set[str], regexes: set[str]) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in _REGEX_METHODS:
        return False
    return (
        isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
        and any(_has_identifier(argument, aliases) for argument in node.args)
        or isinstance(node.func.value, ast.Name)
        and node.func.value.id in regexes
        and any(_has_identifier(argument, aliases) for argument in node.args)
        or isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Attribute)
        and node.func.value.func.attr == "compile"
        and any(_has_identifier(argument, aliases) for argument in node.args)
    )


def _reason(node: ast.AST, aliases: set[str], regexes: set[str]) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _STRING_METHODS and _has_identifier(node.func.value, aliases):
            return f"identifier string method {node.func.attr}()"
        if node.func.attr == "split" and any(_has_identifier(argument, aliases) for argument in node.args):
            return "str.split() over an identifier"
        if _is_regex_call(node, aliases, regexes):
            return f"regular expression {node.func.attr}() over an identifier"
    elif isinstance(node, ast.Compare):
        operands = (node.left, *node.comparators)
        if any(_has_identifier(operand, aliases) for operand in operands) and any(
            _is_string_literal(operand) or _is_literal_collection(operand) for operand in operands
        ):
            if any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
                return "string-membership test over an identifier"
            if any(isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops):
                return "literal comparison over an identifier"
    elif isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Dict) and _has_identifier(node.slice, aliases):
            return "dict dispatch keyed on an identifier"
        if _is_identifier(node.value, aliases):
            return "identifier indexing or slicing"
    elif isinstance(node, ast.Match) and _has_identifier(node.subject, aliases):
        return "match dispatch keyed on an identifier"
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if (
            value is not None
            and (isinstance(value, ast.JoinedStr) or isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add))
            and _has_identifier(value, aliases)
            and any(_is_identifier_name(target) for target in targets)
        ):
            return "identifier fabricated from another identifier"
        if (
            value is not None
            and _is_string_literal(value)
            and any(
                isinstance(target, ast.Name) and target.id.startswith("DEFAULT_") and _is_identifier_name(target)
                for target in targets
            )
        ):
            return "literal identifier default"
        if (
            value is not None
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "get"
            and len(value.args) >= 2
            and _is_string_literal(value.args[1])
            and any(_is_identifier_name(target) for target in targets)
        ):
            return "literal identifier fallback from configuration"
    return None


def _violations(root: Path) -> list[str]:
    findings: list[str] = []
    for directory in _SOURCE_DIRS:
        for path in sorted((root / "src" / "cryodaq" / directory).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            scopes = [
                tree,
                *(
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))
                ),
            ]
            scope_data = {scope: _aliases(scope) for scope in scopes}
            for node in ast.walk(tree):
                scope = node
                while scope in parents and scope not in scope_data:
                    scope = parents[scope]
                aliases, regexes = scope_data[scope]
                reason = _reason(node, aliases, regexes)
                if reason and (relative, node.lineno) not in _ALLOWLIST:
                    findings.append(f"{relative}:{node.lineno}: {reason}")
    return sorted(findings)


def test_c2_descriptor_selection_guard() -> None:
    assert _violations(_root()) == []


def test_c2_descriptor_selection_guard_rejects_multiple_forms_then_accepts_restored_copy(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    shutil.copytree(_root() / "src", scratch / "src")
    target = scratch / "src" / "cryodaq" / "reporting" / "sections.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(
        original
        + "\n\ndef _injected_bad_selection(item):\n"
        + "    local = item.channel\n"
        + "    starts = local.startswith('power/')\n"
        + "    member = local in ('cold', 'warm')\n"
        + "    regex = re.compile('power').search(local)\n"
        + "    prefix = local[:3] == 'abc'\n"
        + "    split = str.split(local) == ['cold']\n"
        + "    fabricated_channel = f'{local}/derived'\n"
        + "    dispatch = {'cold': 1}[local]\n"
        + "    match local:\n"
        + "        case 'cold':\n"
        + "            return starts or member or regex or prefix or split or fabricated_channel or dispatch\n",
        encoding="utf-8",
    )

    violations = _violations(scratch)
    expected = {
        "identifier string method startswith()",
        "string-membership test over an identifier",
        "regular expression search() over an identifier",
        "identifier indexing or slicing",
        "str.split() over an identifier",
        "identifier fabricated from another identifier",
        "dict dispatch keyed on an identifier",
        "match dispatch keyed on an identifier",
    }
    assert expected <= {finding.rsplit(": ", 1)[1] for finding in violations}

    target.write_text(original, encoding="utf-8")
    assert _violations(scratch) == []


_C2_PROOF_CASES = {
    "startswith": (
        "    local = item.channel\n    return local.startswith('power/')\n",
        "identifier string method startswith()",
    ),
    "membership": (
        "    local = item.channel\n    return local in ('cold', 'warm')\n",
        "string-membership test over an identifier",
    ),
    "regex": (
        "    local = item.channel\n    return re.compile('power').search(local)\n",
        "regular expression search() over an identifier",
    ),
    "slicing": ("    local = item.channel\n    return local[:3] == 'abc'\n", "identifier indexing or slicing"),
    "split": ("    local = item.channel\n    return str.split(local) == ['cold']\n", "str.split() over an identifier"),
    "fabrication": (
        "    local = item.channel\n    derived_channel = f'{local}/derived'\n    return derived_channel\n",
        "identifier fabricated from another identifier",
    ),
    "dict_dispatch": (
        "    local = item.channel\n    return {'cold': 1}[local]\n",
        "dict dispatch keyed on an identifier",
    ),
    "match_dispatch": (
        "    local = item.channel\n    match local:\n        case 'cold':\n            return 1\n",
        "match dispatch keyed on an identifier",
    ),
}


def test_c2_descriptor_selection_guard_proves_each_injected_shape_and_restoration(tmp_path: Path) -> None:
    for name, (body, reason) in _C2_PROOF_CASES.items():
        scratch = tmp_path / name
        shutil.copytree(_root() / "src", scratch / "src")
        target = scratch / "src" / "cryodaq" / "reporting" / "sections.py"
        original = target.read_text(encoding="utf-8")
        target.write_text(original + f"\n\ndef _injected_{name}(item):\n" + body, encoding="utf-8")
        assert any(finding.endswith(reason) for finding in _violations(scratch))
        target.write_text(original, encoding="utf-8")
        assert _violations(scratch) == []
