"""BottomStatusBar is a passive truth presenter, not an audio owner."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.bottom_status_bar import (
    BottomStatusBar,
    _disk_space_color,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    ("free_gb", "expected"),
    [
        (0.0, theme.STATUS_FAULT),
        (1.99, theme.STATUS_FAULT),
        (2.0, theme.STATUS_CAUTION),
        (9.99, theme.STATUS_CAUTION),
        (10.0, theme.TEXT_MUTED),
    ],
)
def test_disk_space_thresholds_use_canonical_safety_rungs(free_gb: float, expected: str) -> None:
    assert _disk_space_color(free_gb) == expected


def _make_bar() -> BottomStatusBar:
    _app()
    bar = BottomStatusBar()
    bar._timer.stop()
    return bar


@pytest.mark.parametrize("state", ["run_permitted", "running"])
def test_activity_state_uses_accent_without_claiming_healthy(state: str) -> None:
    bar = _make_bar()
    bar.set_safety_state(state)
    style = bar._safety_label.styleSheet()
    assert theme.ACCENT in style
    assert theme.STATUS_OK not in style


def test_ready_is_informational_not_healthy() -> None:
    bar = _make_bar()
    bar.set_safety_state("ready")
    style = bar._safety_label.styleSheet()
    assert theme.STATUS_INFO in style
    assert theme.STATUS_OK not in style


def test_bottom_bar_has_no_filesystem_probe_and_rejects_malformed_disk_evidence() -> None:
    import ast
    from pathlib import Path

    module = ast.parse(
        Path(__file__).parents[3].joinpath("src/cryodaq/gui/shell/bottom_status_bar.py").read_text(encoding="utf-8")
    )
    names = {node.id for node in ast.walk(module) if isinstance(node, ast.Name)}
    assert not {"shutil", "get_data_dir", "QApplication"} & names
    bar = _make_bar()
    old = bar._disk_label.text()
    assert not bar.set_disk_evidence(float("nan"), source="disk_monitor", state="ok")
    assert not bar.set_disk_evidence(5.0, source="other", state="caution")
    assert bar._disk_label.text() == old
    assert bar.set_disk_evidence(5.0, source="disk_monitor", state="caution")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
