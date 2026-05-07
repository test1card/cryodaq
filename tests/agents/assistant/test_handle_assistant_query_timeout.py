"""F-TimeoutRelax H7 — cold-start timeout envelope ordering."""

from __future__ import annotations

import inspect

from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_SLOW_S
from cryodaq.engine import _handle_assistant_query_command
from cryodaq.gui.zmq_client import _CMD_REPLY_TIMEOUT_S


def test_timeout_layer_ordering_invariant() -> None:
    """helper_s < envelope_s <= client_s. Each layer must fire after the next."""
    sig = inspect.signature(_handle_assistant_query_command)
    helper_s = sig.parameters["timeout_s"].default

    envelope_s = HANDLER_TIMEOUT_SLOW_S
    client_s = _CMD_REPLY_TIMEOUT_S

    assert helper_s < envelope_s, (
        f"helper {helper_s}s must fire before ZMQ slow envelope {envelope_s}s"
    )
    assert envelope_s <= client_s, (
        f"ZMQ slow envelope {envelope_s}s must fire before client reply {client_s}s"
    )


def test_helper_default_absorbs_cold_start() -> None:
    """H7: helper default must be ≥40s to cover Ollama cold-start (20–40s)."""
    sig = inspect.signature(_handle_assistant_query_command)
    helper_s = sig.parameters["timeout_s"].default
    assert helper_s >= 40.0, (
        f"helper default {helper_s}s does not cover Ollama cold-start"
    )
