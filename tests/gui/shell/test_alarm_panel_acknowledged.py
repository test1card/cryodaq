"""SeverityChip acknowledged styling — v0.55.2 A1 (visual habituation guard).

Architect-flagged: backend kept the alarm in `_active` until the physical
condition cleared (correct), but the GUI rendered acknowledged alarms
identically to fresh ones. Operator habituation = safety regression.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_severity_chip_fresh_uses_status_token() -> None:
    _app()
    chip = SeverityChip("CRITICAL")
    assert chip.text() == "КРИТ"
    assert theme.STATUS_FAULT in chip.styleSheet()


def test_severity_chip_acknowledged_uses_muted_palette() -> None:
    _app()
    chip = SeverityChip("CRITICAL", acknowledged=True)
    assert chip.text().startswith("✓")
    qss = chip.styleSheet()
    assert theme.SURFACE_MUTED in qss
    assert theme.MUTED_FOREGROUND in qss
    assert theme.STATUS_FAULT not in qss


def test_severity_chip_acknowledged_warning_too() -> None:
    _app()
    chip = SeverityChip("WARNING", acknowledged=True)
    qss = chip.styleSheet()
    assert theme.STATUS_WARNING not in qss
    assert theme.SURFACE_MUTED in qss


# v0.55.4 — v1 (threshold) path acknowledged styling. v0.55.2 only
# patched the v2 path; the v1 _refresh_table built SeverityChip without
# the acknowledged kwarg, so v1 alarms never visually muted on
# acknowledge.


def test_v1_acknowledged_alarm_chip_uses_muted_palette() -> None:
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.gui.shell.overlays.alarm_panel import AlarmPanel

    _app()
    panel = AlarmPanel()

    def _reading(event_type: str) -> Reading:
        return Reading(
            timestamp=datetime.now(UTC),
            instrument_id="LS218_1",
            channel="Т1",
            value=300.0,
            unit="K",
            status=ChannelStatus.OK,
            metadata={
                "alarm_name": "v1_test",
                "event_type": event_type,
                "severity": "CRITICAL",
                "threshold": 290.0,
            },
        )

    panel._handle_reading(_reading("activated"))
    chip_active = panel._table.cellWidget(0, 0)
    assert chip_active is not None
    assert theme.STATUS_FAULT in chip_active.styleSheet()
    assert theme.SURFACE_MUTED not in chip_active.styleSheet()

    panel._handle_reading(_reading("acknowledged"))
    chip_ack = panel._table.cellWidget(0, 0)
    assert chip_ack is not None
    qss = chip_ack.styleSheet()
    assert theme.SURFACE_MUTED in qss
    assert theme.MUTED_FOREGROUND in qss
    assert theme.STATUS_FAULT not in qss
    assert chip_ack.text().startswith("✓")
