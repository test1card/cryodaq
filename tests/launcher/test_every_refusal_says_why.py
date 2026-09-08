"""A stop that blocks the operator must carry its reason.

The launcher logged `type(exc).__name__` and nothing else at twenty-three
CRITICAL and ERROR sites — the class of the exception, never its message and
never a traceback. On 2026-09-09 that cost the stand five minutes of
acquisition: it refused to start with `exception=RuntimeError` as the entire
diagnosis in the log and in the systemd journal both, and the cause was found
only by starting the same code a different way.

Several of these sites block a restart AND the launcher's own exit. A stop that
takes the stand away from its operator has to say what happened.

The root handlers carry `_TokenRedactFilter` on the record and
`_TokenRedactFormatter` on the traceback, so `exc_info` does not reintroduce
the bot-token leak fixed on 2026-09-07.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import cryodaq.launcher as launcher_module

_TYPE_NAME = re.compile(r"type\((.+)\)\.__name__")


def _bare_type_logs(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text())
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if not isinstance(node, ast.Call) or not isinstance(func, ast.Attribute):
            continue
        if func.attr not in {"critical", "error"}:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "logger"):
            continue
        if any(kw.arg == "exc_info" for kw in node.keywords):
            continue
        if any(_TYPE_NAME.fullmatch(ast.unparse(arg)) for arg in node.args):
            offenders.append((node.lineno, ast.unparse(node).split("\n")[0][:80]))
    return offenders


def test_no_refusal_logs_only_the_exception_class() -> None:
    """Parsed, not grepped: a comment that mentions the pattern is not a use of
    it, and this file mentions it several times."""

    path = Path(launcher_module.__file__)
    offenders = _bare_type_logs(path)

    assert not offenders, "\n".join(
        f"launcher.py:{line} logs only the class: {text}" for line, text in offenders
    )


def test_the_check_can_actually_fail() -> None:
    """A guard that cannot fire guards nothing."""

    import tempfile

    source = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(exc):\n"
        "    logger.critical('boom %s', type(exc).__name__)\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        temp = Path(handle.name)

    try:
        assert _bare_type_logs(temp), "the check does not detect the pattern it forbids"
    finally:
        temp.unlink()
