"""Tests for ZMQ bridge — pack/unpack serialization and pub/sub integration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cryodaq.core.zmq_bridge import (
    _SLOW_COMMANDS,
    HANDLER_TIMEOUT_FAST_S,
    HANDLER_TIMEOUT_SLOW_S,
    ZMQCommandServer,
    _pack_reading,
    _timeout_for,
    _unpack_reading,
)
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reading(
    channel: str = "CH1",
    value: float = 4.2,
    unit: str = "K",
    status: ChannelStatus = ChannelStatus.OK,
    raw: float | None = None,
    metadata: dict | None = None,
) -> Reading:
    return Reading(
        timestamp=datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC),
        instrument_id="test",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
        raw=raw,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Basic roundtrip
# ---------------------------------------------------------------------------


async def test_pack_unpack_roundtrip() -> None:
    original = _make_reading(channel="T_STAGE", value=4.2, unit="K")
    packed = _pack_reading(original)
    result = _unpack_reading(packed)

    assert result.channel == original.channel
    assert abs(result.value - original.value) < 1e-9
    assert result.unit == original.unit
    assert result.status == original.status
    # Timestamps are equal up to microsecond precision after float roundtrip
    assert abs((result.timestamp - original.timestamp).total_seconds()) < 1e-3


# ---------------------------------------------------------------------------
# 2. All fields preserved
# ---------------------------------------------------------------------------


async def test_pack_preserves_all_fields() -> None:
    original = Reading(
        timestamp=datetime(2026, 1, 15, 8, 30, 0, tzinfo=UTC),
        instrument_id="vg1",
        channel="VACUUM",
        value=1.23e-5,
        unit="mbar",
        status=ChannelStatus.OK,
        raw=0.987,
        metadata={"range": "low"},
    )
    result = _unpack_reading(_pack_reading(original))

    assert result.channel == "VACUUM"
    assert abs(result.value - 1.23e-5) < 1e-15
    assert result.unit == "mbar"
    assert result.raw is not None
    assert abs(result.raw - 0.987) < 1e-9
    assert result.instrument_id == "vg1"
    assert result.metadata == {"range": "low"}


# ---------------------------------------------------------------------------
# 3. ChannelStatus enum survives roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(ChannelStatus))
async def test_channel_status_serialized(status: ChannelStatus) -> None:
    reading = _make_reading(status=status)
    result = _unpack_reading(_pack_reading(reading))
    assert result.status is status


# ---------------------------------------------------------------------------
# 4. Metadata dict survives msgpack roundtrip
# ---------------------------------------------------------------------------


async def test_metadata_preserved() -> None:
    meta = {
        "instrument_id": "ls218s_1",
        "rack": 3,
        "calibrated": True,
        "offset": 0.012,
    }
    reading = _make_reading(metadata=meta)
    result = _unpack_reading(_pack_reading(reading))

    assert result.metadata["instrument_id"] == "ls218s_1"
    assert result.metadata["rack"] == 3
    assert result.metadata["calibrated"] is True
    assert abs(result.metadata["offset"] - 0.012) < 1e-12


# ---------------------------------------------------------------------------
# 5. Publisher/Subscriber integration via _pack/_unpack (no live sockets)
# ---------------------------------------------------------------------------


async def test_publisher_subscriber_integration() -> None:
    """Verify that a batch of readings can be serialized and deserialized
    in the same way the pub/sub loop does it (topic-stripped payload)."""
    readings = [_make_reading(channel=f"CH{i}", value=float(i), unit="K") for i in range(5)]

    # Simulate what ZMQPublisher sends and ZMQSubscriber receives
    topic = b"readings"
    wire_frames = [(topic, _pack_reading(r)) for r in readings]

    received: list[Reading] = []
    for _topic, payload in wire_frames:
        received.append(_unpack_reading(payload))

    assert len(received) == 5
    for i, r in enumerate(received):
        assert r.channel == f"CH{i}"
        assert abs(r.value - float(i)) < 1e-9
        assert r.unit == "K"
        assert r.status == ChannelStatus.OK


# ---------------------------------------------------------------------------
# IV.3 Finding 7 — handler timeout tiering + REP unwedge
# ---------------------------------------------------------------------------


def test_slow_commands_set_covers_experiment_lifecycle() -> None:
    """Every known-slow command uses the 30 s envelope."""
    for cmd in (
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_create",
        "experiment_create_retroactive",
        "experiment_start",
        "experiment_generate_report",
        "calibration_curve_import",
        "calibration_curve_export",
        "calibration_v2_fit",
        "calibration_v2_extract",
    ):
        assert cmd in _SLOW_COMMANDS


def test_timeout_for_fast_commands() -> None:
    assert _timeout_for({"cmd": "safety_status"}) == HANDLER_TIMEOUT_FAST_S
    assert _timeout_for({"cmd": "alarm_v2_status"}) == HANDLER_TIMEOUT_FAST_S
    assert _timeout_for({"cmd": "log_get"}) == HANDLER_TIMEOUT_FAST_S


def test_timeout_for_slow_commands() -> None:
    assert _timeout_for({"cmd": "experiment_finalize"}) == HANDLER_TIMEOUT_SLOW_S
    assert _timeout_for({"cmd": "experiment_create"}) == HANDLER_TIMEOUT_SLOW_S
    assert _timeout_for({"cmd": "calibration_curve_import"}) == HANDLER_TIMEOUT_SLOW_S


def test_timeout_for_malformed_payload_falls_back_to_fast() -> None:
    """Unknown or malformed cmd MUST NOT accidentally promote to slow tier."""
    assert _timeout_for(None) == HANDLER_TIMEOUT_FAST_S
    assert _timeout_for({}) == HANDLER_TIMEOUT_FAST_S
    assert _timeout_for({"cmd": ""}) == HANDLER_TIMEOUT_FAST_S
    assert _timeout_for({"cmd": "unrecognized_command"}) == HANDLER_TIMEOUT_FAST_S


@pytest.mark.asyncio
async def test_handler_timeout_returns_error_reply_not_silence() -> None:
    """REP wedge protection: a timed-out handler MUST return a dict.

    A silent raise would leave the REP state machine in "awaiting
    send" forever, cascading every subsequent command into a
    timeout. ``_run_handler`` always returns a dict so the serve
    loop can send() and move on.
    """

    async def slow_handler(cmd: dict) -> dict:
        await asyncio.sleep(5.0)
        return {"ok": True, "slow": True}

    server = ZMQCommandServer(handler=slow_handler, handler_timeout_s=0.05)
    reply = await server._run_handler({"cmd": "safety_status"})
    assert isinstance(reply, dict)
    assert reply["ok"] is False
    assert reply.get("_handler_timeout") is True
    assert "timeout" in reply.get("error", "").lower()


@pytest.mark.asyncio
async def test_handler_exception_returns_error_reply() -> None:
    """Handler raising an arbitrary exception still yields an error dict."""

    async def boom(cmd: dict) -> dict:
        raise RuntimeError("boom")

    server = ZMQCommandServer(handler=boom, handler_timeout_s=1.0)
    reply = await server._run_handler({"cmd": "safety_status"})
    assert isinstance(reply, dict)
    assert reply["ok"] is False
    assert "boom" in reply.get("error", "")
    # Exceptions are NOT timeouts — the marker must only fire for
    # the wait_for path.
    assert "_handler_timeout" not in reply


@pytest.mark.asyncio
async def test_handler_after_timeout_next_request_works() -> None:
    """After a timeout reply, subsequent commands still get replies.

    Real regression test for the smoke-session cascade: a slow
    command must not leave _run_handler in a state that breaks
    the next call.
    """
    call_count = {"n": 0}

    async def handler(cmd: dict) -> dict:
        call_count["n"] += 1
        if call_count["n"] == 1:
            await asyncio.sleep(5.0)
            return {"ok": True}
        return {"ok": True, "call": call_count["n"]}

    server = ZMQCommandServer(handler=handler, handler_timeout_s=0.05)
    first = await server._run_handler({"cmd": "safety_status"})
    assert first["ok"] is False
    assert first.get("_handler_timeout") is True
    second = await server._run_handler({"cmd": "safety_status"})
    assert second["ok"] is True
    assert second.get("call") == 2


@pytest.mark.asyncio
async def test_handler_timeout_explicit_override_respected() -> None:
    """Tests can pin a timeout via the ctor parameter, overriding the tier."""

    async def slow_handler(cmd: dict) -> dict:
        await asyncio.sleep(1.0)
        return {"ok": True}

    server = ZMQCommandServer(handler=slow_handler, handler_timeout_s=0.05)
    reply = await server._run_handler({"cmd": "experiment_finalize"})
    assert reply["ok"] is False
    assert reply.get("_handler_timeout") is True


@pytest.mark.asyncio
async def test_no_handler_returns_error_not_hang() -> None:
    server = ZMQCommandServer(handler=None)
    reply = await server._run_handler({"cmd": "safety_status"})
    assert reply == {"ok": False, "error": "no handler"}


def test_gui_client_cmd_reply_timeout_exceeds_server_slow_ceiling() -> None:
    """Client future wait outlasts the server's slow ceiling so a slow
    reply is never lost because the client gave up first."""
    from cryodaq.gui.zmq_client import _CMD_REPLY_TIMEOUT_S

    assert _CMD_REPLY_TIMEOUT_S > HANDLER_TIMEOUT_SLOW_S


def test_subprocess_req_timeout_exceeds_server_slow_ceiling() -> None:
    """Subprocess REQ RCVTIMEO/SNDTIMEO must outlast the server's cap."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "core" / "zmq_subprocess.py"
    text = src.read_text(encoding="utf-8")
    # Raised from 3 s → 35 s as part of IV.3 Finding 7. Hex grep is
    # enough: finding either the old 3000 literal would mean an
    # incomplete fix.
    assert "RCVTIMEO, 35000" in text
    assert "SNDTIMEO, 35000" in text
    assert "RCVTIMEO, 3000)" not in text
    assert "SNDTIMEO, 3000)" not in text
