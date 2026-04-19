"""AST-based enforcement of RULE-COPY-009 (no internal versioning in operator text).

Walks every ``*.py`` under ``src/cryodaq/gui/`` and flags string
literals passed to known operator-facing Qt methods when the string
matches forbidden versioning vocabulary (``v1`` / ``v2`` / ``legacy``
/ …).

IV.3 Finding 6: replaces the regex-based module scan shipped in
IV.2 B.3 (``tests/gui/test_design_system_rules.py``) which relied on
string-constant heuristics to decide if a literal was "operator-facing"
or an internal identifier. The AST approach is precise: operator-
facing-ness is decided by the method name at the call site, not by
the shape of the literal. Docstrings, imports, variable assignments,
and internal comparisons never show up in the visitor's result.

Handles:
- ``ast.Constant`` string literals
- ``ast.JoinedStr`` f-string constant parts (formatted expressions
  are deliberately not introspected — the rule is about authored
  copy, not runtime values)
- ``ast.BinOp + ast.Add`` string concatenation (``"A " + "v1"``)
- ``ast.List`` / ``ast.Tuple`` elements for list-valued methods
  (``addItems`` / ``setHorizontalHeaderLabels`` etc.)
- Both positional and keyword args

Deliberately omits class / attribute type inference — a plain
``widget.setText("...")`` is treated as operator-facing even though
``widget`` might technically be a non-UI object. The project
convention is that ``setText`` is a Qt method, not a custom one,
so false-positive risk is low. If a real collision ever appears,
add the offending receiver type to an ignore set rather than
loosening the rule.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_GUI_ROOT = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "gui"

# Qt methods that emit strings to operator-visible surfaces.
_OPERATOR_FACING_METHODS: set[str] = {
    "setText",
    "setPlaceholderText",
    "setToolTip",
    "setWindowTitle",
    "setStatusTip",
    "setWhatsThis",
    "setTitle",
    "addItem",
    "addItems",
    "setLabels",
    "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels",
    "addAction",
}

# Forbidden versioning tokens in operator text. Case-insensitive.
# Covers v1/v2/vN suffix, and common engineering labels that leak
# internal status into UI ("legacy" / "deprecated" / etc.).
#
# Note: Russian «устар.» / «устарел» / «устарело» are NOT on this
# list. The codebase uses them as a legitimate stale-data cue
# (TopWatchBar, sensor cells, Keithley readouts) — "value went stale"
# is domain copy, not an engineering marker. The rule bars
# development lineage terminology («старая версия» in the sense of
# "previous iteration of the code") but not data freshness.
_FORBIDDEN_PATTERN = re.compile(
    r"\b(v[0-9]+|legacy|deprecated|experimental|beta|alpha|"
    r"новая\s+версия|старая\s+версия)\b",
    re.IGNORECASE,
)


class _OperatorTextVisitor(ast.NodeVisitor):
    """Collect string literals passed to operator-facing methods."""

    def __init__(self) -> None:
        # (lineno, method_name, string_snippet)
        self.violations: list[tuple[int, str, str]] = []

    # Public entry keeps the tests's signature
    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 — ast hook
        method_name = self._extract_method_name(node.func)
        if method_name in _OPERATOR_FACING_METHODS:
            for arg in node.args:
                self._check_arg(node, method_name, arg)
            for kw in node.keywords:
                self._check_arg(node, method_name, kw.value)
        self.generic_visit(node)

    @staticmethod
    def _extract_method_name(func_node: ast.expr) -> str | None:
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None

    def _check_arg(self, call_node: ast.Call, method: str, arg: ast.expr) -> None:
        # IV.3 F6 amend: list/tuple literals passed to list-valued
        # methods (addItems, setHorizontalHeaderLabels, setLabels,
        # setVerticalHeaderLabels) must be recursed so each element is
        # inspected. Otherwise a violation inside a header list slips
        # past because the top-level arg is an ast.List, not a string.
        if isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                self._check_arg(call_node, method, elt)
            return
        text = self._extract_string(arg)
        if text is None:
            return
        if _FORBIDDEN_PATTERN.search(text):
            snippet = text[:60] + ("…" if len(text) > 60 else "")
            self.violations.append((call_node.lineno, method, snippet))

    def _extract_string(self, node: ast.expr) -> str | None:
        """Extract a string from Constant, JoinedStr (f-string), or BinOp + concat."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            # f-string: collect only the Constant str segments; the
            # formatted expression pieces are runtime values.
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
            return "".join(parts) if parts else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._extract_string(node.left) or ""
            right = self._extract_string(node.right) or ""
            combined = left + right
            return combined if combined else None
        return None


def _collect_violations_in_source(source: str) -> list[tuple[int, str, str]]:
    """Helper for unit tests — visits a literal source string."""
    tree = ast.parse(source)
    visitor = _OperatorTextVisitor()
    visitor.visit(tree)
    return visitor.violations


def _collect_violations_in_tree(root: Path) -> list[tuple[Path, int, str, str]]:
    violations: list[tuple[Path, int, str, str]] = []
    for py_file in root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        visitor = _OperatorTextVisitor()
        visitor.visit(tree)
        for line, method, snippet in visitor.violations:
            violations.append((py_file, line, method, snippet))
    return violations


# ----------------------------------------------------------------------
# Visitor self-checks
# ----------------------------------------------------------------------


def test_ast_detects_v1_in_setText() -> None:
    src = "widget.setText('Alarms (v1)')"
    violations = _collect_violations_in_source(src)
    assert len(violations) == 1
    assert violations[0][1] == "setText"


def test_ast_detects_v2_in_addItem() -> None:
    src = "combo.addItem('Лог (v2)')"
    violations = _collect_violations_in_source(src)
    assert len(violations) == 1
    assert violations[0][1] == "addItem"


def test_ast_detects_legacy_in_placeholder() -> None:
    src = "edit.setPlaceholderText('legacy mode — deprecated')"
    violations = _collect_violations_in_source(src)
    assert len(violations) == 1
    assert violations[0][1] == "setPlaceholderText"


def test_ast_does_not_flag_docstrings() -> None:
    src = '''
def f():
    """Handles v1 alarms from legacy engine."""
    return 1
'''
    assert _collect_violations_in_source(src) == []


def test_ast_does_not_flag_variable_names() -> None:
    src = "alarm_v1 = 1\nlegacy_shim = object()\nzmq_v2_port = 5556\n"
    assert _collect_violations_in_source(src) == []


def test_ast_handles_fstrings() -> None:
    # A constant fragment inside an f-string still matches.
    src = "label.setText(f'{name} — v1')"
    violations = _collect_violations_in_source(src)
    assert len(violations) == 1


def test_ast_handles_string_concatenation() -> None:
    src = "label.setText('Старая версия' + ' v1')"
    violations = _collect_violations_in_source(src)
    assert len(violations) == 1


def test_ast_ignores_non_string_args() -> None:
    """Passing a variable / int / list to setText doesn't raise and
    doesn't produce a violation (we can't know the value statically)."""
    src = "widget.setText(some_variable)\nwidget.setText(42)\n"
    assert _collect_violations_in_source(src) == []


def test_ast_only_flags_operator_facing_methods() -> None:
    """A non-UI method call with the same word does NOT match."""
    src = "config.set_legacy_mode('v1')\nsome.log('legacy token')\n"
    assert _collect_violations_in_source(src) == []


def test_ast_recurses_into_list_args() -> None:
    """addItems / setHorizontalHeaderLabels take a list; inner elements
    must be inspected (IV.3 F6 amend)."""
    src = (
        "table.setHorizontalHeaderLabels(['Колонка (v1)', 'OK'])\n"
        "combo.addItems(['legacy', 'current'])\n"
        "other.setLabels(('beta build', 'stable'))\n"
    )
    violations = _collect_violations_in_source(src)
    methods = [v[1] for v in violations]
    assert "setHorizontalHeaderLabels" in methods
    assert "addItems" in methods
    assert "setLabels" in methods


# ----------------------------------------------------------------------
# Full-tree contract
# ----------------------------------------------------------------------


def test_no_internal_versioning_in_operator_text() -> None:
    """RULE-COPY-009: scan src/cryodaq/gui/ and report any violations.

    Replaces the regex-based walker shipped in IV.2 B.3. Should pass on
    current HEAD — IV.2 B.3 already migrated the two known
    alarm_panel.py labels."""
    violations = _collect_violations_in_tree(_GUI_ROOT)
    if violations:
        report = "\n".join(
            f"  {path.relative_to(_GUI_ROOT.parent.parent.parent)}:{line} — {method}(): {snippet!r}"
            for path, line, method, snippet in violations
        )
        pytest.fail("RULE-COPY-009 violations — internal versioning in operator text:\n" + report)
