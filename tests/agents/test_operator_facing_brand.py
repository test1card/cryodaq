"""No operator-facing string may hardcode the assistant's name.

The operator renamed the assistant to РМКПшка and kept being greeted as Гемма.
The rename was declared finished three times:

    round 1  three literals in telegram_commands.py and launcher.py
    round 2  a fourth in live/agent.py — found by reading a boot log
    round 3  five more in the GUI panels and the DOCX report — found by review

Each round fixed an enumerated list of modules, and each round the list was
incomplete. THIS TEST WAS PART OF THE PROBLEM: it carried the list, so it could
only ever confirm that the places someone already thought of were clean.

So it no longer enumerates. It walks every module under ``src/cryodaq`` and
fails on the retired name in any string literal that is not a docstring.
Comments and docstrings stay exempt — they record the history, and the history
is the reason this file reads the way it does.

Latin ``gemma`` is deliberately not matched: ``gemma4:e4b`` is a model
identifier, ``gemma.*`` a retained legacy config namespace, and
``data/agents/gemma/audit`` a legacy path. Those are identifiers that share a
word with a retired display name; renaming them breaks compatibility and
changes nothing the operator sees.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cryodaq.agents.assistant.shared.brand import DEFAULT_BRAND_NAME

_SRC = Path(__file__).resolve().parents[2] / "src" / "cryodaq"

#: Display names the assistant has retired. A future rename appends here.
_RETIRED_BRANDS = ("Гемма",)


def _module_paths() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def _docstring_constants(tree: ast.AST) -> set[int]:
    """id() of every Constant that is a module/class/function docstring."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _offences(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our concern
        return []
    exempt = _docstring_constants(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in exempt:
            continue
        for brand in _RETIRED_BRANDS:
            if brand in node.value:
                found.append(f"{path.name}:{node.lineno}: {node.value[:70]!r}")
    return found


def test_no_module_under_src_names_a_retired_brand() -> None:
    offences: list[str] = []
    for path in _module_paths():
        offences.extend(_offences(path))
    assert not offences, (
        "retired assistant name in operator-facing string literals:\n  "
        + "\n  ".join(offences)
        + f"\n\nUse cryodaq.agents.assistant.shared.brand.DEFAULT_BRAND_NAME "
        f"({DEFAULT_BRAND_NAME!r}) or the caller's configured brand_name."
    )


def test_the_scan_actually_reaches_the_gui_and_reporting_surfaces() -> None:
    """A scan that silently walked nothing would pass the test above."""
    names = {p.as_posix() for p in _module_paths()}
    for expected in (
        "gui/shell/overlays/_assistant_chat_widget.py",
        "gui/shell/overlays/knowledge_base_panel.py",
        "gui/shell/views/assistant_insight_panel.py",
        "reporting/generator.py",
        "notifications/telegram_commands.py",
        "launcher.py",
    ):
        assert any(n.endswith(expected) for n in names), f"{expected} not scanned"


@pytest.mark.parametrize("brand", _RETIRED_BRANDS)
def test_the_guard_would_catch_a_reintroduction(tmp_path: Path, brand: str) -> None:
    """Negative control: the scanner must fail on a planted literal."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        f'"""Docstring mentioning {brand} stays legal."""\nlabel = "Помощник {brand}"\n',
        encoding="utf-8",
    )
    offences = _offences(planted)
    assert len(offences) == 1, offences
    assert "label" not in offences[0]
