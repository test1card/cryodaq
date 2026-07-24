"""BottomStatusBar is a passive truth presenter, not an audio owner."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.bottom_status_bar import (
    BottomStatusBar,
    _disk_state_color,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("fault", theme.STATUS_FAULT),
        ("caution", theme.STATUS_CAUTION),
        ("ok", theme.TEXT_MUTED),
    ],
)
def test_disk_state_maps_backend_owned_operator_state(state: str, expected: str) -> None:
    assert _disk_state_color(state) == expected


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
    now = datetime.now(UTC)
    assert not bar.set_disk_evidence(float("nan"), source="disk_monitor", state="ok", source_time=now)
    assert not bar.set_disk_evidence(5.0, source="other", state="caution", source_time=now)
    assert not bar.set_disk_evidence(1.0, source="disk_monitor", state="unknown", source_time=now)
    assert "unavailable" in bar._disk_label.accessibleDescription()
    assert bar.set_disk_evidence(5.0, source="disk_monitor", state="caution", source_time=now)


@pytest.mark.parametrize(("value", "state"), [(2.0, "fault"), (10.0, "caution")])
def test_rounded_disk_value_never_overrides_backend_state(value: float, state: str) -> None:
    bar = _make_bar()
    assert bar.set_disk_evidence(
        value,
        source="disk_monitor",
        state=state,
        source_time=datetime.now(UTC),
    )
    assert _disk_state_color(state) in bar._disk_label.styleSheet()


def test_disk_evidence_expires_independently_and_retains_last_known_value() -> None:
    bar = _make_bar()
    source_time = datetime.now(UTC)
    assert bar.set_disk_evidence(5.0, source="disk_monitor", state="caution", source_time=source_time)
    assert not bar._disk_evidence_is_current(
        now_monotonic=bar._last_disk_receipt_monotonic + 601.0,
        now_utc=source_time + timedelta(seconds=601),
    )
    bar.set_disk_unavailable()
    assert "~5.0" in bar._disk_label.text()
    assert "last-known" in bar._disk_label.accessibleDescription()


def test_invalid_rate_retains_last_known_value_without_fabricating_zero() -> None:
    bar = _make_bar()
    bar.set_data_rate(7.0)
    bar.set_data_rate(-1.0)

    assert bar._rate_label.text().startswith("~7")
    assert "-1.0" in bar._rate_label.accessibleDescription()


def test_protocol_maxima_fit_1280_with_full_evidence_in_accessible_detail() -> None:
    bar = _make_bar()
    bar.set_safety_state("x" * 1_000, stale=True)
    bar.set_data_rate(1e300)
    bar.set_connected(False, "y" * 1_000)
    assert bar.set_disk_evidence(
        1e300,
        source="disk_monitor",
        state="ok",
        source_time=datetime.now(UTC),
    )
    bar._start_time -= 10**12
    bar._tick()
    bar.resize(1280, bar.height())
    bar.show()
    QApplication.processEvents()

    assert bar.minimumSizeHint().width() <= 1280
    for label in (
        bar._safety_label,
        bar._uptime_label,
        bar._disk_label,
        bar._rate_label,
        bar._conn_label,
        bar._time_label,
    ):
        assert label.geometry().right() <= bar.rect().right()
    assert "x" * 100 in bar._safety_label.accessibleDescription()
    assert "1e+300" in bar._disk_label.accessibleDescription()
    assert "y" * 100 in bar._conn_label.accessibleDescription()
    assert "д" in bar._uptime_label.accessibleDescription()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
