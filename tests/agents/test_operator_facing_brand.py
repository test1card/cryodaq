"""No operator-facing string may hardcode the assistant's name.

The operator renamed the assistant to РМКПшка in `agent.yaml`, and kept being
greeted as "Гемма" — because three messages carried the name as a literal
instead of reading `agent.brand_name`:

    telegram_commands.py  "🤖 Гемма: уже обрабатываю предыдущий вопрос…"
    telegram_commands.py  "🤖 Гемма: внутренняя ошибка. См. логи."
    launcher.py           "Ассистент (Гемма) перезапускается…"

A rename that leaves the old name in the places the operator actually looks has
not happened. This pins the shape of the fix rather than the fix itself: string
LITERALS in operator-facing modules must not name a brand, whatever the brand
is called next.

Comments and docstrings are exempt — they record history, and the history here
is worth keeping.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Retired names. A future rename adds to this rather than editing the test.
_RETIRED_BRANDS = ("Гемма", "Gemma")

# The list was three modules and missed live/agent.py, which announced the
# retired brand on every start — found by reading the boot log after a deploy,
# not by this test. Any module that renders the assistant's identity belongs
# here.
_OPERATOR_FACING = (
    "src/cryodaq/notifications/telegram_commands.py",
    "src/cryodaq/launcher.py",
    "src/cryodaq/agents/assistant/shared/report_intro.py",
    "src/cryodaq/agents/assistant/live/agent.py",
    "src/cryodaq/agents/assistant/query/agent.py",
    "src/cryodaq/agents/assistant_main.py",
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id() of every Constant that is a module/class/function docstring."""

    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    out.add(id(body[0].value))
    return out


@pytest.mark.parametrize("relative", _OPERATOR_FACING)
def test_no_retired_brand_in_string_literals(relative: str) -> None:
    path = _ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)

    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and any(brand in node.value for brand in _RETIRED_BRANDS)
    ]
    assert not offenders, (
        f"{relative} carries a retired brand in a string literal: {offenders}. "
        "Read agent.brand_name instead — a rename must reach the operator."
    )


def test_both_brand_resolvers_agree_with_the_shipped_config() -> None:
    """The launcher and the engine must not disagree about the name.

    They resolve it separately on purpose — the launcher avoids importing
    engine-side modules — so nothing but a test keeps them consistent.
    """

    from cryodaq.engine import _assistant_brand as engine_brand
    from cryodaq.launcher import _assistant_brand as launcher_brand

    assert engine_brand() == launcher_brand()


def test_a_missing_name_falls_back_to_a_neutral_label(tmp_path, monkeypatch) -> None:
    """An unreadable config must not resurrect a brand from a default."""

    from cryodaq import launcher

    monkeypatch.setattr("cryodaq.paths.get_config_dir", lambda: tmp_path)
    label = launcher._assistant_brand()
    assert label == "Ассистент"
    assert not any(brand in label for brand in _RETIRED_BRANDS)


def test_the_telegram_bot_takes_the_brand_as_a_parameter() -> None:
    """The messages must interpolate, not embed."""

    import inspect

    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    assert "brand" in inspect.signature(TelegramCommandBot.__init__).parameters
