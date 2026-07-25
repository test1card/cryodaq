from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow

from cryodaq.gui.tray_status import TrayController, TrayLevel, resolve_tray_status, tray_icon_for_level


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_resolve_tray_status_marks_fault_on_alarm() -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="running",
        alarm_count=2,
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.FAULT
    assert "Т: 2" in status.tooltip


def test_resolve_tray_status_marks_warning_on_missing_truth() -> None:
    status = resolve_tray_status(connected=False, safety_state=None, alarm_count=0)

    assert status.level is TrayLevel.CAUTION
    assert "НЕТ ПОЛНОЙ ИНФОРМАЦИИ" in status.tooltip


def test_resolve_tray_status_marks_healthy_only_for_known_safe_state() -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="safe_off",
        alarm_count=0,
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.HEALTHY
    assert "Б: безопасно выкл." in status.tooltip


def test_resolve_tray_status_never_infers_zero_alarms_from_unknown_authority() -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="safe_off",
        alarm_count=None,
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.CAUTION
    assert "НЕТ ПОЛНОЙ ИНФОРМАЦИИ" in status.tooltip
    assert "Т: неизв." in status.tooltip
    assert status.tooltip.startswith("CryoDAQ · сводка; детали в окне")


@pytest.mark.parametrize("malformed_count", [-1, True, 1.5, "0"])
def test_resolve_tray_status_never_clamps_malformed_alarm_authority_to_zero(
    malformed_count: object,
) -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="safe_off",
        alarm_count=malformed_count,  # type: ignore[arg-type]
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.CAUTION
    assert "Т: неизв." in status.tooltip


@pytest.mark.parametrize(
    ("data_fresh", "reporting_fault"),
    [(None, False), (False, False), (True, None), (True, True)],
)
def test_healthy_requires_fresh_data_and_known_reporting_truth(data_fresh, reporting_fault) -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="running",
        alarm_count=0,
        data_fresh=data_fresh,
        reporting_fault=reporting_fault,
    )

    assert status.level is TrayLevel.CAUTION


def test_unknown_safety_value_is_not_leaked_or_painted_healthy() -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="vendor_private_magic",
        alarm_count=0,
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.CAUTION
    assert "vendor_private_magic" not in status.tooltip
    assert "Б: неизв." in status.tooltip


def test_tooltip_is_bounded_for_windows_and_keeps_disclaimer_first() -> None:
    status = resolve_tray_status(
        connected=True,
        safety_state="fault_latched",
        alarm_count=10**50,
        data_fresh=False,
        reporting_fault=True,
    )

    assert status.tooltip.startswith("CryoDAQ · сводка; детали в окне")
    assert len(status.tooltip.encode("utf-16-le")) // 2 <= 127
    assert "9999+" in status.tooltip


@pytest.mark.parametrize("connected", [1, 0, "yes", object()])
def test_non_boolean_connection_authority_is_unknown(connected: object) -> None:
    status = resolve_tray_status(
        connected=connected,  # type: ignore[arg-type]
        safety_state="safe_off",
        alarm_count=0,
        data_fresh=True,
        reporting_fault=False,
    )

    assert status.level is TrayLevel.CAUTION
    assert "Связь: неизв." in status.tooltip


def test_launcher_uses_resolver_for_startup_freshness_and_reporting_truth() -> None:
    launcher = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "launcher.py"
    source = launcher.read_text(encoding="utf-8")

    assert "initial_status = resolve_tray_status(" in source
    assert "data_fresh=data_flowing" in source
    assert "reporting_fault=self._periodic_reporting_fault" in source
    assert "self._last_reading_time > 0.0" in source

    resolver_tail = source.split("tray_truth = resolve_tray_status(", 1)[1].split("@Slot(dict)", 1)[0]
    assert "elif self._periodic_reporting_fault" not in resolver_tail
    assert "elif not data_flowing" not in resolver_tail
    assert "self._tray.setToolTip(tray_truth.tooltip)" in resolver_tail


def test_tray_levels_have_distinct_non_color_silhouettes() -> None:
    _app()
    masks: list[tuple[bool, ...]] = []
    for level in (TrayLevel.HEALTHY, TrayLevel.CAUTION, TrayLevel.FAULT):
        image = tray_icon_for_level(level).pixmap(16, 16).toImage()
        masks.append(tuple(image.pixelColor(x, y).alpha() > 0 for y in range(16) for x in range(16)))

    assert len(set(masks)) == 3
    assert TrayLevel.WARNING is TrayLevel.CAUTION


def test_tray_controller_gracefully_disables_when_tray_unavailable(monkeypatch) -> None:
    _app()
    monkeypatch.setattr("cryodaq.gui.tray_status.QSystemTrayIcon.isSystemTrayAvailable", lambda: False)

    controller = TrayController(QMainWindow())

    assert controller.available is False
