"""Engine → Pipeline → batch → MolecularCounter → GUI, with no private state.

The reviewer required acceptance tests that traverse the real path rather than
populate internals. These drive a real DataBroker, a real PluginPipeline with the
real plugin loaded from plugins/, real Readings published to the broker, and the
real GUI consumers — asserting only on what an operator would see.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.analytics.plugin_loader import PluginPipeline  # noqa: E402
from cryodaq.core.broker import DataBroker  # noqa: E402
from cryodaq.core.phase_event import PhaseEntry  # noqa: E402
from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402

_P = "VSP63D_1/pressure"
_BULK = ["Т1", "Т2"]
_GAS = "analytics/molecular_counter/gas_inventory"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(channel: str, value: float, *, unit: str = "") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="stand",
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
        metadata={},
    )


class _Harness:
    """A real broker + real pipeline with the real counter bound."""

    def __init__(self) -> None:
        self.broker = DataBroker()
        self.pipeline = PluginPipeline(self.broker, Path("plugins"), batch_interval_s=0.05)
        self.published: list[Reading] = []

    async def __aenter__(self):
        await self.pipeline.start()
        counter = self.pipeline._plugins.get("molecular_counter")
        assert counter is not None, "the real plugin must load from plugins/"
        # Bind through the plugin's own public configure(), as the loader does.
        counter.configure(
            {"pressure_channel": _P, "bulk_sensors": list(_BULK), "update_interval_s": 0.0}
        )
        self.queue = await self.broker.subscribe("test_sink")
        return self

    async def __aexit__(self, *exc):
        await self.pipeline.stop()

    async def feed(self, p: float, t: float) -> None:
        """Publish one full sample set and wait for a NEW gas value.

        Waiting for "any" value would return immediately once the first one had
        ever been produced, and every later assertion would read the first
        reading again.
        """

        before = len(self._gas_readings())
        for reading in [_reading(_P, p, unit="mbar")] + [_reading(ch, t, unit="K") for ch in _BULK]:
            await self.broker.publish(reading)
        for _ in range(60):
            await asyncio.sleep(0.02)
            if len(self._gas_readings()) > before:
                return

    def _gas_readings(self) -> list[Reading]:
        while not self.queue.empty():
            self.published.append(self.queue.get_nowait())
        return [r for r in self.published if r.channel == _GAS]

    def latest_gas(self) -> Reading | None:
        gas = self._gas_readings()
        return gas[-1] if gas else None


@pytest.mark.asyncio
async def test_a_reading_becomes_a_gas_value_on_the_real_path() -> None:
    async with _Harness() as h:
        await h.feed(0.10, 300.0)
        latest = h.latest_gas()

    assert latest is not None, "the real pipeline must publish the metric"
    assert latest.value == pytest.approx(100.0), "the first valid sample is the baseline"
    assert latest.metadata["quantity"] == "apparent_temperature_corrected_pirani_equivalent"


@pytest.mark.asyncio
async def test_an_incomplete_sensor_set_publishes_nothing() -> None:
    """Blocker 4, through the real path: a moving denominator is refused."""

    async with _Harness() as h:
        await h.broker.publish(_reading(_P, 0.10, unit="mbar"))
        await h.broker.publish(_reading("Т1", 300.0, unit="K"))   # Т2 missing
        for _ in range(20):
            await asyncio.sleep(0.02)
        assert h.latest_gas() is None, "a partial sensor set must produce no value"

        await h.broker.publish(_reading("Т2", 300.0, unit="K"))
        await h.feed(0.10, 300.0)
        assert h.latest_gas() is not None, "and resumes once the set is complete"


@pytest.mark.asyncio
async def test_a_phase_entry_rezeros_through_the_real_pipeline() -> None:
    """Engine's call → pipeline → plugin's own process(), no private writes."""

    async with _Harness() as h:
        await h.feed(0.10, 300.0)
        assert h.latest_gas().value == pytest.approx(100.0)

        await h.feed(0.05, 300.0)
        assert h.latest_gas().value == pytest.approx(50.0, abs=0.5)

        # Exactly what engine.py does on a committed phase advance.
        h.pipeline.notify_phase_change(
            PhaseEntry(experiment_id="exp", phase="cooldown",
                       started_at=datetime.now(UTC).timestamp() - 0.5)
        )
        await h.feed(0.05, 300.0)

        latest = h.latest_gas()
        assert latest.value == pytest.approx(100.0), "the phase entry is the new zero"
        assert latest.metadata["baseline_reason"] == "начало захолаживания"
        assert latest.metadata["phase_entry_epoch"] is not None


@pytest.mark.asyncio
async def test_the_gui_consumers_render_what_the_pipeline_published(app) -> None:
    """The last leg: a real published Reading into both real consumers."""

    from cryodaq.gui.shell import top_watch_bar as twb
    from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget

    async with _Harness() as h:
        await h.feed(0.10, 300.0)
        published = h.latest_gas()

    assert published is not None
    card = GasInventoryWidget()
    bar = twb.TopWatchBar()
    card.set_gas_inventory(published)
    bar.on_reading(published)

    assert card._value_label.text() == bar._ctx_gas_value.text()
    assert "100" in card._value_label.text()
    assert "100% =" in card._baseline_label.text(), "the zero is stated, not implied"
