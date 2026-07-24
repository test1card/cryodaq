"""Closed, one-use launcher authority envelope guards."""

from __future__ import annotations

from collections.abc import MutableMapping

import pytest

import cryodaq.engine as engine

_CHANNEL = "CRYODAQ_CHILD_READY_CHANNEL"
_NONCE = "CRYODAQ_ENGINE_READY_NONCE"
_INSTANCE = "CRYODAQ_ENGINE_INSTANCE_ID"
_CAPABILITY = "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY"
_AUTHORITY_KEYS = {_CHANNEL, _NONCE, _INSTANCE, _CAPABILITY}


def _full_envelope() -> dict[str, str]:
    return {
        _CHANNEL: "channel-authority",
        _NONCE: "b" * 64,
        _INSTANCE: "a" * 32,
        _CAPABILITY: "c" * 64,
        "UNRELATED": "preserved",
    }


def _fake_channel(environment: MutableMapping[str, str]) -> int | None:
    encoded = environment.pop(_CHANNEL, None)
    return 71 if encoded is not None else None


def test_complete_or_absent_launch_envelope_is_consumed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "_consume_child_ready_channel", _fake_channel)
    complete = _full_envelope()

    assert engine._consume_engine_launch_authority(complete) == (
        "a" * 32,
        "c" * 64,
        "b" * 64,
        71,
    )
    assert complete == {"UNRELATED": "preserved"}
    assert engine._consume_engine_launch_authority({}) == ("", "", "", None)


@pytest.mark.parametrize("missing_key", sorted(_AUTHORITY_KEYS))
def test_every_partial_launch_envelope_is_rejected_consumed_and_settled(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(engine, "_consume_child_ready_channel", _fake_channel)
    monkeypatch.setattr(engine.os, "close", closed.append)
    partial = _full_envelope()
    partial.pop(missing_key)

    with pytest.raises(RuntimeError, match="shutdown authority is invalid|envelope is incomplete"):
        engine._consume_engine_launch_authority(partial)

    assert _AUTHORITY_KEYS.isdisjoint(partial)
    assert partial == {"UNRELATED": "preserved"}
    assert closed == ([] if missing_key == _CHANNEL else [71])


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ({_NONCE: "not-a-nonce"}, "readiness nonce is invalid"),
        ({_INSTANCE: "short"}, "shutdown authority is invalid"),
        ({_CAPABILITY: "A" * 64}, "shutdown authority is invalid"),
    ],
)
def test_invalid_launch_envelope_consumes_all_secrets_and_closes_acquired_fd_once(
    monkeypatch: pytest.MonkeyPatch,
    corruption: dict[str, str],
    message: str,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(engine, "_consume_child_ready_channel", _fake_channel)
    monkeypatch.setattr(engine.os, "close", closed.append)
    invalid = {**_full_envelope(), **corruption}

    with pytest.raises(RuntimeError, match=message):
        engine._consume_engine_launch_authority(invalid)

    assert _AUTHORITY_KEYS.isdisjoint(invalid)
    assert invalid == {"UNRELATED": "preserved"}
    assert closed == [71]


def test_invalid_channel_still_consumes_every_other_launch_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = _full_envelope()

    def reject_channel(environment: MutableMapping[str, str]) -> int:
        assert environment.pop(_CHANNEL) == "channel-authority"
        raise RuntimeError("launcher readiness channel is invalid")

    monkeypatch.setattr(engine, "_consume_child_ready_channel", reject_channel)

    with pytest.raises(RuntimeError, match="readiness channel is invalid"):
        engine._consume_engine_launch_authority(invalid)

    assert invalid == {"UNRELATED": "preserved"}


def test_unicode_decimal_ready_descriptor_is_rejected_before_os_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = {_CHANNEL: "fd:٧"}
    monkeypatch.setattr(engine.sys, "platform", "linux")
    monkeypatch.setattr(
        engine.os,
        "fstat",
        lambda _fd: (_ for _ in ()).throw(AssertionError("non-ASCII descriptor reached OS lookup")),
    )

    with pytest.raises(RuntimeError, match="readiness channel is invalid"):
        engine._consume_child_ready_channel(environment)

    assert environment == {}
