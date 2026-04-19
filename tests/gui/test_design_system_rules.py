"""CI enforcement for design-system rules with automatable signatures.

Some DS rules have purely syntactic violation shapes that can be caught
by a grep-style regression test. This file pins those so a fresh
regression lands as a red bar in CI, not as an eventual reviewer
complaint three commits later.

Rules with automatable signatures:
- RULE-COPY-009 (no internal versioning in operator-facing copy):
  `"...(v1)..."`, `"...(v2)..."`, etc. string literals in shell/overlays/.
- Anything else in this file is reviewer-enforced.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUI_ROOT = _REPO_ROOT / "src" / "cryodaq" / "gui"

# Scope for RULE-COPY-009: anything reachable from the operator through
# the shell. Engine code, core modules, configs, tests, and the
# launcher's internal log messages are not in scope — internal
# versioning there is a contract between maintainers.
_OPERATOR_FACING_DIRS: tuple[Path, ...] = (
    _GUI_ROOT / "shell",
    _GUI_ROOT / "dashboard",
    _GUI_ROOT / "widgets",
)

# Matches the exact "(vN)" suffix shape that leaked to operators in
# alarm_panel.py prior to IV.2.B.3. Deliberately narrow — Keithley
# 2604B stays; alarm_v2_ack command name stays; only the operator-
# facing "(v1)" / "(v2)" shape in a string literal is flagged.
_VERSION_SUFFIX = re.compile(r"\(v\d+\)")


def _iter_string_constants(py_file: Path):
    """Yield (lineno, str_value) for every string constant in the module."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_rule_copy_009_no_internal_versioning_in_operator_strings() -> None:
    """Operator-facing UI text must not contain '(v1)' / '(v2)' suffixes.

    Prior to IV.2.B.3 the alarm panel's two section titles leaked
    schema versioning directly to the operator. The RULE-COPY-009
    guidance is that operators see domain names, not engine
    generations. Docstrings and comments are exempt — this check
    walks string *constants* in the AST, so block docstrings land in
    a Constant node but most internal engine identifiers
    (alarm_v2_ack, etc.) don't match the parenthesized suffix shape
    anyway.
    """
    violations: list[str] = []
    for root in _OPERATOR_FACING_DIRS:
        for py_file in root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            for lineno, text in _iter_string_constants(py_file):
                if _VERSION_SUFFIX.search(text):
                    # Require the match to land alongside content that
                    # looks like operator UI text: either Cyrillic
                    # letters or one of a handful of operator-visible
                    # English labels. Rule-text / comment-like strings
                    # with "(v1)" embedded in prose explaining the rule
                    # itself do not match that filter.
                    has_operator_text = (
                        any("\u0400" <= ch <= "\u04ff" for ch in text) or "KEITHLEY" in text
                    )
                    if not has_operator_text:
                        continue
                    violations.append(f"{py_file.relative_to(_REPO_ROOT)}:{lineno}: {text!r}")
    assert not violations, (
        "RULE-COPY-009: operator-facing strings must not embed internal "
        "version suffixes. Use domain names (e.g. 'Аппаратные тревоги' / "
        "'Физические тревоги') instead. Violations:\n" + "\n".join(violations)
    )


def test_rule_surf_011_rule_file_exists() -> None:
    """Pin RULE-SURF-011 presence — pattern is reviewer-enforced so the
    rule text itself is the contract. A removed / missing rule file
    would silently drop the empty-state requirement."""
    surface_rules = _REPO_ROOT / "docs" / "design-system" / "rules" / "surface-rules.md"
    text = surface_rules.read_text(encoding="utf-8")
    assert "RULE-SURF-011" in text
    assert "Empty-state surface" in text


def test_rule_copy_009_rule_file_exists() -> None:
    content_voice = _REPO_ROOT / "docs" / "design-system" / "rules" / "content-voice-rules.md"
    text = content_voice.read_text(encoding="utf-8")
    assert "RULE-COPY-009" in text
    assert "No internal versioning" in text
