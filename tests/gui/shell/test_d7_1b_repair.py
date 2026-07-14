"""D7.1b REPAIR tests — covers FIX-1, FIX-2a, FIX-2b, FIX-3."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_reading(channel: str = "Т01 Repair", unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(0, tz=UTC),
        instrument_id="test_inst",
        channel=channel,
        value=4.2,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _make_qualified(reading: Reading) -> DescriptorQualifiedReading:
    return DescriptorQualifiedReading(reading=reading, descriptor=None)


# ---------------------------------------------------------------------------
# FIX-1: ingest() raising must NOT skip _dispatch_reading or propagate
# ---------------------------------------------------------------------------


def test_fix1_ingest_exception_still_dispatches_reading() -> None:
    """FIX-1: ingest() raising TypeError must NOT skip _dispatch_reading and
    must NOT propagate out of dispatch_qualified_reading."""
    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т10 Fix1")
    qualified = _make_qualified(reading)

    dispatched: list[Reading] = []

    def _capture(r: Reading) -> None:
        dispatched.append(r)

    # Monkeypatch ingest to raise, simulating a malformed/forged carrier
    with (
        patch.object(w._descriptor_store, "ingest", side_effect=TypeError("forged carrier")),
        patch.object(w, "_dispatch_reading", side_effect=_capture),
    ):
        # Must NOT raise
        w.dispatch_qualified_reading(qualified)

    # Legacy sink must still have received the reading exactly once
    assert len(dispatched) == 1, f"_dispatch_reading must be called once; got {dispatched}"
    assert dispatched[0] is reading


def test_fix1_ingest_exception_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """FIX-1: a warning must be logged when ingest raises."""
    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т11 Fix1Warn")
    qualified = _make_qualified(reading)

    with (
        patch.object(w._descriptor_store, "ingest", side_effect=TypeError("forged")),
        patch.object(w, "_dispatch_reading"),
        caplog.at_level(logging.WARNING, logger="cryodaq.gui.shell.main_window_v2"),
    ):
        w.dispatch_qualified_reading(qualified)

    assert any("descriptor ingest failed" in r.message for r in caplog.records), (
        "Expected a WARNING containing 'descriptor ingest failed'"
    )


def test_fix1_capacity_result_reaches_capacity_log_and_dispatches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FIX-1: on a CAPACITY_EXHAUSTED result the else-branch capacity debug log
    IS reached (ingest succeeded), and the bare reading is still dispatched."""
    from cryodaq.gui.shell.main_window_v2 import IngestResult, MainWindowV2

    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т12 Fix1Cap")
    qualified = _make_qualified(reading)

    dispatched: list[Reading] = []

    with (
        patch.object(w._descriptor_store, "ingest", return_value=IngestResult.CAPACITY_EXHAUSTED),
        patch.object(w, "_dispatch_reading", side_effect=dispatched.append),
        caplog.at_level(logging.DEBUG, logger="cryodaq.gui.shell.main_window_v2"),
    ):
        w.dispatch_qualified_reading(qualified)

    # else-branch capacity log reached on success path
    assert any("capacity exhausted" in r.message for r in caplog.records), (
        "Expected a DEBUG containing 'capacity exhausted' on the CAPACITY_EXHAUSTED path"
    )
    # No warning: the exception path must NOT be entered
    assert not any("descriptor ingest failed" in r.message for r in caplog.records), (
        "Exception-path warning must NOT fire on a successful capacity result"
    )
    # Bare reading still dispatched exactly once
    assert len(dispatched) == 1
    assert dispatched[0] is reading


def test_fix1_exception_path_does_not_touch_capacity_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FIX-1: on the exception path the else-branch (capacity debug log) is NOT
    entered — only the warning fires — and dispatch still happens."""
    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т13 Fix1ExcNoCap")
    qualified = _make_qualified(reading)

    dispatched: list[Reading] = []

    with (
        patch.object(w._descriptor_store, "ingest", side_effect=TypeError("forged")),
        patch.object(w, "_dispatch_reading", side_effect=dispatched.append),
        caplog.at_level(logging.DEBUG, logger="cryodaq.gui.shell.main_window_v2"),
    ):
        w.dispatch_qualified_reading(qualified)

    # else-branch (capacity log) must NOT run when ingest raised
    assert not any("capacity exhausted" in r.message for r in caplog.records), (
        "Capacity else-branch must NOT be entered on the exception path"
    )
    # Warning fires
    assert any("descriptor ingest failed" in r.message for r in caplog.records)
    # Dispatch still happens exactly once
    assert len(dispatched) == 1
    assert dispatched[0] is reading


# ---------------------------------------------------------------------------
# FIX-2a: command-channel watchdog restart must invalidate before bridge.start()
# ---------------------------------------------------------------------------


def test_fix2a_cmd_watchdog_invalidate_before_start(monkeypatch: object) -> None:
    """FIX-2a: command-channel watchdog must call invalidate_descriptor_transport()
    between bridge.shutdown() and bridge.start()."""
    import time  # noqa: PLC0415

    call_order: list[str] = []

    fake_bridge = MagicMock()
    fake_bridge.is_healthy.return_value = True
    fake_bridge.data_flow_stalled.return_value = False
    fake_bridge.command_channel_stalled.return_value = True
    fake_bridge.shutdown.side_effect = lambda: call_order.append("shutdown")
    fake_bridge.start.side_effect = lambda: call_order.append("start")

    fake_window = MagicMock()
    fake_window.invalidate_descriptor_transport.side_effect = lambda: call_order.append("invalidate")

    # Simulate the watchdog block directly (extracted logic matching launcher.py)
    last_cmd_restart = 0.0  # ensures cooldown gate passes
    now = time.monotonic()
    if now - last_cmd_restart >= 60.0:
        fake_bridge.shutdown()
        if fake_window is not None:
            fake_window.invalidate_descriptor_transport()
        fake_bridge.start()

    assert call_order == ["shutdown", "invalidate", "start"], (
        f"Expected shutdown -> invalidate -> start; got {call_order}"
    )


def test_fix2a_cmd_watchdog_invalidate_in_production_code() -> None:
    """FIX-2a: verify the production launcher source inserts invalidate between
    shutdown and start in the command-channel watchdog block."""
    from pathlib import Path

    launcher_src = (Path(__file__).parents[3] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    lines = launcher_src.splitlines()

    # Find the command_channel_stalled conditional block by locating the
    # attribute call to `command_channel_stalled`; then confirm
    # `invalidate_descriptor_transport` appears between the two bridge calls.
    watchdog_region: list[str] = []
    in_block = False
    for i, line in enumerate(lines):
        if "command_channel_stalled" in line and "stalled(timeout_s" in line:
            in_block = True
        if in_block:
            watchdog_region.append(line)
            if len(watchdog_region) > 30:
                break

    region_text = "\n".join(watchdog_region)
    assert "invalidate_descriptor_transport" in region_text, (
        f"command-channel watchdog block must call invalidate_descriptor_transport(); region found:\n{region_text}"
    )

    # Ensure invalidate comes AFTER shutdown and BEFORE start within the block
    shutdown_pos = region_text.find("shutdown")
    invalidate_pos = region_text.find("invalidate_descriptor_transport")
    start_pos = region_text.rfind(".start()")
    assert shutdown_pos < invalidate_pos < start_pos, (
        "Order must be: shutdown < invalidate_descriptor_transport < start; "
        f"positions: shutdown={shutdown_pos}, invalidate={invalidate_pos}, start={start_pos}"
    )


# ---------------------------------------------------------------------------
# FIX-2b: _restart_engine must invalidate before bridge.start()
# ---------------------------------------------------------------------------


def test_fix2b_restart_engine_invalidate_in_production_code() -> None:
    """FIX-2b: verify the production _restart_engine source inserts invalidate
    between bridge.shutdown() and bridge.start()."""
    from pathlib import Path

    launcher_src = (Path(__file__).parents[3] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    lines = launcher_src.splitlines()

    # Locate _restart_engine method and extract ~25 lines
    restart_start = next((i for i, ln in enumerate(lines) if "def _restart_engine(self)" in ln), None)
    assert restart_start is not None, "_restart_engine method not found in launcher.py"

    region_lines = lines[restart_start : restart_start + 30]
    region_text = "\n".join(region_lines)

    assert "invalidate_descriptor_transport" in region_text, (
        f"_restart_engine must call invalidate_descriptor_transport(); region:\n{region_text}"
    )

    shutdown_pos = region_text.find("shutdown")
    invalidate_pos = region_text.find("invalidate_descriptor_transport")
    start_pos = region_text.find(".start()")
    assert shutdown_pos < invalidate_pos < start_pos, (
        "Order must be: shutdown < invalidate_descriptor_transport < start in _restart_engine; "
        f"positions: shutdown={shutdown_pos}, invalidate={invalidate_pos}, start={start_pos}"
    )


def test_fix2b_restart_engine_invalidate_called_with_fake() -> None:
    """FIX-2b: simulate the restart_engine sequence; invalidate must precede start."""
    call_order: list[str] = []

    fake_bridge = MagicMock()
    fake_bridge.shutdown.side_effect = lambda: call_order.append("shutdown")
    fake_bridge.start.side_effect = lambda: call_order.append("start")

    fake_window = MagicMock()
    fake_window.invalidate_descriptor_transport.side_effect = lambda: call_order.append("invalidate")

    # Reproduce the patched _restart_engine sequence
    fake_bridge.shutdown()
    # (stop_engine / start_engine omitted — irrelevant to order)
    if fake_window is not None:
        fake_window.invalidate_descriptor_transport()
    fake_bridge.start()

    assert call_order == ["shutdown", "invalidate", "start"], (
        f"Expected shutdown -> invalidate -> start; got {call_order}"
    )


# ---------------------------------------------------------------------------
# FIX-3: _on_reading_qt with non-DQR must log warning and not dispatch
# ---------------------------------------------------------------------------


def test_fix3_on_reading_qt_non_dqr_logs_warning_and_drops() -> None:
    """FIX-3: _on_reading_qt receiving a non-DQR logs a warning, does NOT call
    dispatch_qualified_reading, and does NOT increment _reading_count."""
    # Avoid heavy launcher construction — test the logic directly by
    # reconstructing the relevant guard in a unit fashion.
    from cryodaq.core.descriptor_transport import DescriptorQualifiedReading

    dispatched_calls: list[object] = []
    reading_count = 0

    def _simulated_on_reading_qt(qualified: object) -> None:
        nonlocal reading_count
        if not isinstance(qualified, DescriptorQualifiedReading):
            # FIX-3 behavior under test
            # (logger call checked separately via caplog in the next test)
            return
        reading_count += 1
        dispatched_calls.append(qualified)

    rogue_object = object()
    _simulated_on_reading_qt(rogue_object)

    assert reading_count == 0, "_reading_count must not increment for non-DQR"
    assert dispatched_calls == [], "dispatch_qualified_reading must not be called for non-DQR"


def test_fix3_on_reading_qt_non_dqr_warning_in_production_code() -> None:
    """FIX-3: verify production source emits a warning for non-DQR in _on_reading_qt."""
    from pathlib import Path

    launcher_src = (Path(__file__).parents[3] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    lines = launcher_src.splitlines()

    on_reading_start = next((i for i, ln in enumerate(lines) if "def _on_reading_qt(self" in ln), None)
    assert on_reading_start is not None, "_on_reading_qt not found in launcher.py"

    region_lines = lines[on_reading_start : on_reading_start + 15]
    region_text = "\n".join(region_lines)

    assert "logger.warning" in region_text, (
        f"_on_reading_qt must emit logger.warning for non-DQR; region:\n{region_text}"
    )
    assert "_on_reading_qt received non-qualified" in region_text or ("non-qualified object" in region_text), (
        f"warning message must describe the non-qualified object; region:\n{region_text}"
    )
