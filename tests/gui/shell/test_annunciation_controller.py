from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_event_emitted_false_does_not_silence() -> None:
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.shell.annunciation_controller import AnnunciationController

    app = QApplication.instance() or QApplication([])
    assert app is not None
    beeps: list[str] = []
    controller = AnnunciationController(beep=lambda: beeps.append("beep"))
    controller._poll_timer.stop()
    activation = {
        "activation_id": "activation-1",
        "source": "safety_fault",
        "source_key": "safety_manager",
        "severity": "CRITICAL",
        "activated_at": 12.0,
        "acknowledged": False,
    }
    assert controller.accept_status(
        {
            "ok": True,
            "engine_instance_id": "engine-a",
            "snapshot_revision": 1,
            "activations": [activation],
        }
    )
    assert controller.audible
    accepted = controller.accept_acknowledgement(
        {
            "ok": True,
            "activation_id": "activation-1",
            "event_emitted": False,
            "snapshot_revision": 2,
        },
        "engine-a",
        "activation-1",
    )
    assert accepted is False
    assert controller.audible
    assert controller.shutdown()
