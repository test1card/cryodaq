"""The derived prevention baseline must be written with LF on every platform.

WHY THIS EXISTS. ``governance/agent_preventions_baseline.json`` is generated from
``governance/agent_preventions.yaml`` by ``tools/governance_contract.py``. The write used
``Path.write_text`` with no ``newline`` argument, which applies the platform separator.
The same registry therefore regenerated as LF on Linux and CRLF on Windows. Measured on
2026-08-14: a Windows regeneration that changed no content produced a file differing from
the committed one by exactly 490 carriage returns, and was byte-identical once those were
normalised. Three separate runs hit it, one of them an independent lane.

The damage is not cosmetic. ``test_prevention_removal_baseline`` compares the committed
baseline against a fresh render, so a Windows checkout reports the registry out of sync
having changed nothing, and the obvious response -- commit the regenerated file -- writes
carriage returns into a tracked governance artifact.

Both tests below bind on EVERY platform. An earlier draft regenerated through a subprocess
and could only fail on Windows, which made it vacuous on CI; it was replaced rather than
kept, because a guard that silently skips on the machine that runs it is the defect class
this repository exists to remove.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "governance" / "agent_preventions_baseline.json"
GENERATOR = ROOT / "tools" / "governance_contract.py"


def test_committed_baseline_contains_no_carriage_return() -> None:
    """The tracked artifact itself is LF-only and carries no byte-order mark."""
    raw = BASELINE.read_bytes()
    assert raw, "the baseline artifact is empty"
    # Counted from BYTES. A shell pattern for a carriage return has already lied in this
    # repository by matching the letter "r", so the count is never taken from a grep.
    carriage_returns = raw.count(b"\r")
    assert carriage_returns == 0, (
        f"{BASELINE.name} carries {carriage_returns} carriage returns; it must be LF-only. "
        "Regenerate with: python tools/governance_contract.py --write-baseline"
    )
    assert not raw.startswith(b"\xef\xbb\xbf"), "the baseline must not carry a byte-order mark"


def test_generator_pins_the_line_separator_explicitly() -> None:
    """The generator must pass an explicit newline, not inherit the platform default.

    Checked with ``ast`` rather than a substring search: a comment or a docstring that
    merely mentions ``newline`` would satisfy a text match while the call itself stayed
    platform-dependent.
    """
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"), filename=str(GENERATOR))
    writer = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_write_removal_baseline"
        ),
        None,
    )
    assert writer is not None, "_write_removal_baseline is gone; this guard needs re-aiming"

    write_calls = [
        node
        for node in ast.walk(writer)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
    ]
    assert write_calls, "_write_removal_baseline no longer calls write_text; re-aim this guard"

    for call in write_calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "newline" in keywords, (
            "write_text in _write_removal_baseline must pass an explicit newline. "
            "Without it the platform separator applies and the same registry renders as "
            "LF on Linux and CRLF on Windows."
        )
        newline = next(kw.value for kw in call.keywords if kw.arg == "newline")
        assert isinstance(newline, ast.Constant) and newline.value == "\n", 'the explicit newline must be "\\n"'
