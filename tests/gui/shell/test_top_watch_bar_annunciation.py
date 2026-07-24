"""TopWatchBar must present alarm state without owning audible annunciation."""

from __future__ import annotations

import ast
from pathlib import Path


def test_top_watch_bar_contains_no_audio_or_recent_alarm_polling() -> None:
    source = Path(__file__).parents[3].joinpath("src/cryodaq/gui/shell/top_watch_bar.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}

    assert "QApplication" not in names
    assert "recent_alarms" not in strings
