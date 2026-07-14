"""D7.4 Phase-1: real-socket ZMQ e2e test.

Proves the full loopback transport stack:
  ZMQPublisher (real PUB socket, production serialize+send)
  -> loopback TCP
  -> ZmqBridge subprocess (real SUB socket, production drain)
  -> MainWindowV2.dispatch_qualified_reading
  -> DescriptorStore + _dispatch_reading

Assertions:
- Every published bare reading reaches the recording sink EXACTLY once
  (count == published, no loss, no duplicate).
- Descriptor-bearing channels are AUTHORITATIVE in the store.
- Legacy-absent channels are LEGACY_ABSENT in the store (never AUTHORITATIVE).
- Ordering within a channel is preserved.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.state.descriptor_store import IdentityStatus
from tests.e2e._zmq_harness import (
    ZmqHarness,
    encode_descriptor_envelope,
    make_descriptor,
    zmq_harness,
)

# Re-export fixture so pytest discovers it from this module.
__all__ = ["zmq_harness"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    from PySide6.QtCore import QTimer

    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _make_reading(
    *,
    channel: str,
    instrument_id: str = "test_inst",
    unit: str = "K",
    value: float = 4.2,
) -> Reading:
    return Reading(
        timestamp=datetime.now(tz=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


# ---------------------------------------------------------------------------
# Core e2e test
# ---------------------------------------------------------------------------


def test_real_socket_loopback_roundtrip(zmq_harness: ZmqHarness) -> None:  # noqa: F811
    """Publish 6 readings over a real loopback ZMQ socket, drain via ZmqBridge,
    dispatch into MainWindowV2, and assert correctness of delivery and store state.

    Mix:
      - 2 descriptor-bearing readings on channel "e2e.ch.alpha" (expect AUTHORITATIVE)
      - 2 descriptor-bearing readings on channel "e2e.ch.beta"  (expect AUTHORITATIVE)
      - 2 legacy-absent readings on channel "e2e.ch.gamma"      (expect LEGACY_ABSENT)

    Total published: 6 readings.
    """
    _app()

    # --- Build descriptors and their wire envelopes (production encoder) -------
    desc_alpha = make_descriptor(
        channel_id="e2e.ch.alpha",
        instrument_id="test_inst",
        source_key="e2e.alpha",
        unit="K",
        quantity=ChannelQuantity.TEMPERATURE,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="e2e",
        display_name="E2E Alpha",
    )
    desc_beta = make_descriptor(
        channel_id="e2e.ch.beta",
        instrument_id="test_inst",
        source_key="e2e.beta",
        unit="K",
        quantity=ChannelQuantity.TEMPERATURE,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="e2e",
        display_name="E2E Beta",
    )
    env_alpha = encode_descriptor_envelope(desc_alpha)
    env_beta = encode_descriptor_envelope(desc_beta)

    # --- Build readings --------------------------------------------------------
    readings_alpha = [
        _make_reading(channel="e2e.ch.alpha", unit="K", value=4.0),
        _make_reading(channel="e2e.ch.alpha", unit="K", value=4.1),
    ]
    readings_beta = [
        _make_reading(channel="e2e.ch.beta", unit="K", value=5.0),
        _make_reading(channel="e2e.ch.beta", unit="K", value=5.1),
    ]
    readings_gamma = [
        _make_reading(channel="e2e.ch.gamma", unit="K", value=6.0),
        _make_reading(channel="e2e.ch.gamma", unit="K", value=6.1),
    ]

    total = len(readings_alpha) + len(readings_beta) + len(readings_gamma)
    assert total == 6

    # --- Publish all 6 readings via the real publisher queue ------------------
    for r in readings_alpha:
        zmq_harness.publish(r, descriptor_envelope=env_alpha)
    for r in readings_beta:
        zmq_harness.publish(r, descriptor_envelope=env_beta)
    for r in readings_gamma:
        zmq_harness.publish(r, descriptor_envelope=None)  # legacy-absent

    # --- Drain via real ZmqBridge subprocess until all 6 arrive ---------------
    qualified_list = zmq_harness.drain_until(total, timeout_s=15.0)
    assert len(qualified_list) == total

    # --- Feed each qualified reading into a real MainWindowV2 -----------------
    w = MainWindowV2()
    _stop_timers(w)

    # Wrap _dispatch_reading to record calls.
    dispatch_calls: list[Reading] = []
    original_dispatch = w._dispatch_reading

    def _recording_dispatch(reading: Reading) -> None:
        dispatch_calls.append(reading)
        original_dispatch(reading)

    with patch.object(w, "_dispatch_reading", side_effect=_recording_dispatch):
        for q in qualified_list:
            w.dispatch_qualified_reading(q)

    # --- Assertions -----------------------------------------------------------

    # 1. Every published reading reached the sink exactly once.
    assert len(dispatch_calls) == total, f"Expected {total} _dispatch_reading calls, got {len(dispatch_calls)}"

    # 2. No duplicates — each (channel, value) pair appears exactly once
    #    per published reading.
    call_pairs = [(r.channel, r.value) for r in dispatch_calls]
    all_expected = (
        [("e2e.ch.alpha", 4.0), ("e2e.ch.alpha", 4.1)]
        + [("e2e.ch.beta", 5.0), ("e2e.ch.beta", 5.1)]
        + [("e2e.ch.gamma", 6.0), ("e2e.ch.gamma", 6.1)]
    )
    assert sorted(call_pairs) == sorted(all_expected), (
        f"Dispatch call mismatch.\nExpected: {sorted(all_expected)}\nGot:      {sorted(call_pairs)}"
    )

    # 3. Descriptor-bearing channels are AUTHORITATIVE in the store.
    status_alpha = w._descriptor_store.identity_status("e2e.ch.alpha")
    status_beta = w._descriptor_store.identity_status("e2e.ch.beta")
    assert status_alpha is IdentityStatus.AUTHORITATIVE, f"e2e.ch.alpha: expected AUTHORITATIVE, got {status_alpha}"
    assert status_beta is IdentityStatus.AUTHORITATIVE, f"e2e.ch.beta: expected AUTHORITATIVE, got {status_beta}"

    # 4. Legacy-absent channel is LEGACY_ABSENT in the store (never AUTHORITATIVE).
    status_gamma = w._descriptor_store.identity_status("e2e.ch.gamma")
    assert status_gamma is IdentityStatus.LEGACY_ABSENT, f"e2e.ch.gamma: expected LEGACY_ABSENT, got {status_gamma}"

    # 5. Ordering within each channel is preserved.
    alpha_dispatched = [r.value for r in dispatch_calls if r.channel == "e2e.ch.alpha"]
    beta_dispatched = [r.value for r in dispatch_calls if r.channel == "e2e.ch.beta"]
    gamma_dispatched = [r.value for r in dispatch_calls if r.channel == "e2e.ch.gamma"]

    assert alpha_dispatched == [4.0, 4.1], f"Alpha ordering broken: {alpha_dispatched}"
    assert beta_dispatched == [5.0, 5.1], f"Beta ordering broken: {beta_dispatched}"
    assert gamma_dispatched == [6.0, 6.1], f"Gamma ordering broken: {gamma_dispatched}"

    # Teardown window.
    _stop_timers(w)
    w.close()
    w.deleteLater()
    _app().processEvents()
