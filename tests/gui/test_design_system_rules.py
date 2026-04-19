"""CI enforcement for design-system rules with automatable signatures.

Some DS rules have purely syntactic violation shapes that can be caught
by a grep-style regression test. This file pins those so a fresh
regression lands as a red bar in CI, not as an eventual reviewer
complaint three commits later.

Rules with automatable signatures:
- RULE-COPY-009 (no internal versioning in operator-facing copy):
  any `(v\\d+)` / ` vN ` / `legacy` token in string literals across
  shell/, dashboard/, widgets/. Docstrings are excluded to match the
  written rule text (maintainer-facing prose, not operator copy).
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

# RULE-COPY-009 patterns. The rule's written contract covers three
# operator-facing shapes:
#   1. Parenthesized suffix: "(v1)", "(v2)", "(v10)".
#   2. Bare version token: " v1 ", " v3 ", " v10.".
#   3. Explicit "legacy" marker.
# Each pattern requires a boundary so "v" inside a legitimate word
# (like "Vacuum", "SMU-v3-channel" internal identifier) is not flagged
# on its own — the filters downstream still require operator-facing
# Cyrillic / uppercase-English context before declaring a violation.
_VERSION_SUFFIX = re.compile(r"\(v\d+\)")
_BARE_VERSION = re.compile(r"(?:^|[\s])v\d+(?:$|[\s.,:])", re.IGNORECASE)
_LEGACY_WORD = re.compile(r"\blegacy\b", re.IGNORECASE)


def _iter_operator_string_constants(py_file: Path):
    """Yield (lineno, str_value) for every string constant that is NOT a docstring.

    Module / class / function / async function docstrings are the first
    statement in their respective bodies. They are developer-facing
    prose and the rule text explicitly exempts them. This walker skips
    them so the CI contract matches the written rule.
    """
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    docstring_nodes: set[int] = set()
    for parent in ast.walk(tree):
        if isinstance(
            parent,
            ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        ):
            body = getattr(parent, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_nodes.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            yield node.lineno, node.value


def _looks_operator_facing(text: str) -> bool:
    """Only flag matches that live alongside operator-visible copy.

    Accepts strings with Cyrillic characters, or the handful of
    hardware vendor labels that appear in UI (Keithley / LakeShore /
    Thyracont, any case). Case-insensitive match — operator-facing
    copy uses "Keithley" / "LakeShore" / "Thyracont" in mixed case,
    all-caps in headers only ("KEITHLEY 2604B"). A maintainer-facing
    `"legacy_smb_map"` identifier in code will not match.
    """
    if any("\u0400" <= ch <= "\u04ff" for ch in text):
        return True
    lowered = text.lower()
    return any(token in lowered for token in ("keithley", "lakeshore", "thyracont"))


def test_rule_copy_009_no_internal_versioning_in_operator_strings() -> None:
    """Operator-facing UI text must not contain '(vN)' / ' vN ' / 'legacy' tokens.

    RULE-COPY-009's written contract is broader than just '(v1)' — it
    also covers bare version markers like 'v3' and the 'legacy'
    label. Docstrings are exempt (maintainer-facing prose), which
    is why this check walks non-docstring string constants only.
    """
    violations: list[str] = []
    for root in _OPERATOR_FACING_DIRS:
        for py_file in root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            for lineno, text in _iter_operator_string_constants(py_file):
                if not _looks_operator_facing(text):
                    continue
                for pattern in (_VERSION_SUFFIX, _BARE_VERSION, _LEGACY_WORD):
                    if pattern.search(text):
                        violations.append(f"{py_file.relative_to(_REPO_ROOT)}:{lineno}: {text!r}")
                        break
    assert not violations, (
        "RULE-COPY-009: operator-facing strings must not embed internal "
        "version suffixes or 'legacy' labels. Use domain names (e.g. "
        "'Пороговые тревоги' / 'Фазо-зависимые тревоги') instead. "
        "Violations:\n" + "\n".join(violations)
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
