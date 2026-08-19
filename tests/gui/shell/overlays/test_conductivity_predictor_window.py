"""The predictor window must hold the number of points it promises.

A SEPARATE module on purpose. ``tests/gui/shell/overlays/test_conductivity_panel.py``
is a registered guard file of record ``CONDUCTIVITY-AUTO-EVIDENCE-AUTHORITY-081``, and
a red-reproduction receipt binds its exact blob, so adding a test there invalidates the
receipt and drags an unrelated governance repair into a one-line arithmetic fix. Putting
the new test beside it costs nothing and keeps the guard's evidence untouched.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.gui.shell.overlays import conductivity_panel as module  # noqa: E402
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    created = QApplication([])
    yield created


def test_the_predictor_window_never_lands_below_the_point_count_it_promises(app) -> None:
    """A measured cadence must not shorten the window by one unit in the last place.

    This drives the real method rather than recomputing its arithmetic. The cadence is a
    MEASURED median of observed gaps, so a nominal 30-second feed arrives as
    29.999999999999996 and the raw product is 899.9999999999999 -- one ulp below the
    window that holds the required number of points. A window a hair too short holds one
    point fewer than the count the method exists to guarantee, which is the "silently
    never producing a valid prediction" failure its own docstring names.

    Measured at master on Ubuntu 22.04.5: the neighbouring guard failed 1 run in 12 for
    exactly this, so besides the defect it cost a CI round in eight, on a queue that is
    already the constraint on merging anything.
    """
    points = module._PREDICTOR_MIN_POINTS
    panel = ConductivityPanel()
    panel._auto_step_temperature_channels = ("Т1",)

    for nominal in (30.0, 45.0, 60.0):
        measured = nominal - 4 * math.ulp(nominal)
        panel._auto_cadence_gaps = {"Т1": [measured, measured, measured]}

        window = panel._required_predictor_window_s()

        assert window >= nominal * points, (
            f"a {nominal}s feed needs {nominal * points}s to hold {points} points; got {window!r}"
        )
        assert window == float(math.ceil(measured * points)), window


def test_an_unobserved_cadence_leaves_the_base_window_alone(app) -> None:
    """Rounding up must not invent a window where no cadence has been measured."""
    panel = ConductivityPanel()
    panel._auto_step_temperature_channels = ()
    panel._auto_cadence_gaps = {}

    assert panel._required_predictor_window_s() == module._PREDICTOR_BASE_WINDOW_S
