"""The hot/cold mapping is declared once per run, in channel IDs.

The zone split decides the SIGN and the VALUE of every dT and G a run
publishes, and it used to be inferred: first from the selection order, then
from the words "Верх"/"Низ" in the display names. Both are presentation. A
different click order, or a renamed or translated channel, silently changed the
physics while the number still looked plausible.

Review required it be declared instead: Start proposes a mapping from the
selection order, shows the physical channel IDs, and the operator confirms.
Confirming freezes the two ID tuples for the run; display names appear beside
each ID for recognition and take no part in the calculation.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel  # noqa: E402


@pytest.fixture
def panel():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    return ConductivityPanel()


def test_confirming_freezes_the_channel_ids(panel, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    chain = ("Т1", "Т14", "Т13", "Т3")

    assert panel._confirm_zones_for_run(chain) is True
    assert panel._auto_confirmed_hot == ("Т1", "Т14")
    assert panel._auto_confirmed_cold == ("Т13", "Т3")


def test_cancelling_does_not_arm_the_run(panel, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))

    assert panel._confirm_zones_for_run(("Т1", "Т14", "Т13", "Т3")) is False
    assert panel._auto_confirmed_hot == ()
    assert panel._auto_confirmed_cold == ()


def test_the_confirmed_ids_are_used_and_not_the_names(panel, monkeypatch):
    """A rename after confirmation must not move a sensor between zones."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    chain = ("Т1", "Т14", "Т13", "Т3")
    panel._confirm_zones_for_run(chain)

    hot, cold = panel._confirmed_zones(chain)

    assert hot == ("Т1", "Т14")
    assert cold == ("Т13", "Т3")


def test_a_single_channel_chain_is_refused_before_arming(panel, monkeypatch):
    """An empty zone cannot produce a difference; refuse before the writer."""
    warned: list = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a) or 0))
    asked: list = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Ok)
    )

    assert panel._confirm_zones_for_run(("Т1",)) is False
    assert warned, "the operator must be told why"
    assert asked == [], "an unusable mapping is refused without asking to confirm it"


def test_zones_fall_back_to_the_proposal_before_any_run(panel):
    """The live table renders before a run is armed."""
    hot, cold = panel._confirmed_zones(("Т1", "Т14", "Т13", "Т3"))
    assert hot == ("Т1", "Т14")
    assert cold == ("Т13", "Т3")


def test_a_confirmed_mapping_is_ignored_for_a_different_chain(panel, monkeypatch):
    """Changing the selection must not silently reuse the old geometry."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    panel._confirm_zones_for_run(("Т1", "Т14", "Т13", "Т3"))

    hot, cold = panel._confirmed_zones(("Т2", "Т7"))

    assert hot == ("Т2",)
    assert cold == ("Т7",)
