from __future__ import annotations

import copy
import json

import pytest

from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_SCHEMA,
    alarm_ack_request_fingerprint,
    deterministic_alarm_ack_request_id,
    deterministic_safety_audio_ack_request_id,
    safety_audio_ack_request_fingerprint,
    validate_alarm_ack_wire_result,
    validate_safety_audio_ack_wire_result,
)
from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer

_ENGINE_A = "a" * 32
_ENGINE_B = "b" * 32


def _wire(handler_result: dict[str, object]) -> dict[str, object]:
    return json.loads(ZMQCommandServer()._encode_reply(handler_result))


def _alarm_command() -> dict[str, str]:
    semantic = {
        "cmd": "alarm_v2_ack",
        "alarm_name": "pressure_high",
        "engine_instance_id": _ENGINE_A,
        "activation_id": "public-activation-a",
        "operator": "operator-a",
        "reason": "observed locally",
    }
    return {
        **semantic,
        "request_id": deterministic_alarm_ack_request_id(
            alarm_name=semantic["alarm_name"],
            engine_instance_id=semantic["engine_instance_id"],
            activation_id=semantic["activation_id"],
            operator=semantic["operator"],
            reason=semantic["reason"],
        ),
    }


def _alarm_handler_result(*, pending: bool = False) -> dict[str, object]:
    command = _alarm_command()
    fingerprint = alarm_ack_request_fingerprint(command)
    receipt = {
        "schema": ALARM_ACK_COMMIT_SCHEMA,
        "request_id": command["request_id"],
        "request_fingerprint": fingerprint,
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "acknowledged_at": 123.5,
        "committed": True,
    }
    result: dict[str, object] = {
        "ok": not pending,
        "committed": True,
        "retry_safe": False,
        "publication_state": "pending" if pending else "published",
        "event_emitted": not pending,
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "request_id": command["request_id"],
        "commit_receipt": receipt,
    }
    if pending:
        result.update(
            error_code="alarm_ack_publication_pending",
            error="alarm acknowledgement is committed; publication settlement is pending",
        )
    return result


def _alarm_aborted_handler_result(
    *,
    terminal_code: str = "activation_changed_before_ack_commit",
) -> dict[str, object]:
    command = _alarm_command()
    return {
        "ok": False,
        "committed": False,
        "retry_safe": False,
        "publication_state": "aborted",
        "event_emitted": False,
        "error_code": "alarm_ack_aborted",
        "error": "alarm acknowledgement was terminally aborted before durable commit",
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "request_id": command["request_id"],
        "request_fingerprint": alarm_ack_request_fingerprint(command),
        "terminal_code": terminal_code,
        "terminal_engine_instance_id": (
            _ENGINE_B if terminal_code == "engine_restart_before_ack_commit" else command["engine_instance_id"]
        ),
    }


@pytest.mark.parametrize(
    ("pending", "expected"),
    [(False, "published"), (True, "pending")],
)
def test_alarm_ack_codec_accepts_only_real_wire_settlement(pending: bool, expected: str) -> None:
    handler_result = _alarm_handler_result(pending=pending)
    handler_result["proto"] = 999

    wire = _wire(handler_result)

    assert wire["proto"] == PROTOCOL_VERSION
    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) == expected
    assert validate_alarm_ack_wire_result(handler_result, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None


@pytest.mark.parametrize(
    "terminal_code",
    ["engine_restart_before_ack_commit", "activation_changed_before_ack_commit"],
)
def test_alarm_ack_codec_accepts_only_exact_real_wire_terminal_abort(terminal_code: str) -> None:
    handler_result = _alarm_aborted_handler_result(terminal_code=terminal_code)
    handler_result["proto"] = 999

    wire = _wire(handler_result)

    assert wire["proto"] == PROTOCOL_VERSION
    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) == "aborted"
    assert validate_alarm_ack_wire_result(handler_result, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None
    assert "commit_receipt" not in wire


def test_alarm_ack_codec_rejects_restart_abort_without_new_engine_incarnation() -> None:
    command = _alarm_command()
    wire = _wire(_alarm_aborted_handler_result(terminal_code="engine_restart_before_ack_commit"))
    wire["terminal_engine_instance_id"] = command["engine_instance_id"]

    assert validate_alarm_ack_wire_result(wire, command, expected_proto=PROTOCOL_VERSION) is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("ok", True),
        ("committed", True),
        ("retry_safe", True),
        ("publication_state", "pending"),
        ("event_emitted", True),
        ("error_code", "alarm_ack_publication_pending"),
        ("error", ""),
        ("error", "line one\nline two"),
        ("error", "x" * 513),
        ("alarm_name", "other"),
        ("activation_id", "other"),
        ("engine_instance_id", _ENGINE_B),
        ("source_activation_id", "07"),
        ("source_activation_id", "٧"),
        ("source_activation_id", 7),
        ("request_id", "f" * 32),
        ("request_fingerprint", "f" * 64),
        ("request_fingerprint", 7),
        ("terminal_code", "unknown_abort"),
        ("terminal_code", None),
        ("terminal_engine_instance_id", "not-canonical"),
        ("terminal_engine_instance_id", "A" * 32),
        ("proto", True),
        ("proto", PROTOCOL_VERSION + 1),
    ],
)
def test_alarm_ack_codec_rejects_corrupted_terminal_abort(field: str, bad_value: object) -> None:
    wire = _wire(_alarm_aborted_handler_result())
    wire[field] = bad_value

    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None


def test_alarm_ack_codec_rejects_open_smuggled_or_unbound_terminal_abort() -> None:
    command = _alarm_command()
    wire = _wire(_alarm_aborted_handler_result())
    extra = {**wire, "compat": True}
    missing = dict(wire)
    missing.pop("terminal_code")
    smuggled_receipt = {**wire, "commit_receipt": _alarm_handler_result()["commit_receipt"]}
    activation_change_wrong_terminal_engine = {**wire, "terminal_engine_instance_id": _ENGINE_B}
    cross_command = {**command, "reason": "different reason"}

    for candidate, bound_command in (
        (extra, command),
        (missing, command),
        (smuggled_receipt, command),
        (activation_change_wrong_terminal_engine, command),
        (wire, cross_command),
    ):
        assert validate_alarm_ack_wire_result(candidate, bound_command, expected_proto=PROTOCOL_VERSION) is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("ok", 1),
        ("committed", 1),
        ("retry_safe", True),
        ("publication_state", "ready"),
        ("event_emitted", False),
        ("alarm_name", "other"),
        ("activation_id", "other"),
        ("engine_instance_id", _ENGINE_B),
        ("source_activation_id", "07"),
        ("source_activation_id", "٧"),
        ("source_activation_id", 7),
        ("source_activation_id", "0"),
        ("request_id", "f" * 32),
        ("proto", True),
        ("proto", PROTOCOL_VERSION + 1),
    ],
)
def test_alarm_ack_codec_rejects_corrupted_outer_wire_identity(field: str, bad_value: object) -> None:
    wire = _wire(_alarm_handler_result())
    wire[field] = bad_value

    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema", "alarm_ack_commit_v0"),
        ("request_id", "f" * 32),
        ("request_fingerprint", "f" * 64),
        ("alarm_name", "other"),
        ("activation_id", "other"),
        ("engine_instance_id", _ENGINE_B),
        ("source_activation_id", "8"),
        ("acknowledged_at", 123),
        ("acknowledged_at", float("nan")),
        ("acknowledged_at", float("inf")),
        ("acknowledged_at", 0.0),
        ("committed", 1),
    ],
)
def test_alarm_ack_codec_rejects_corrupted_commit_receipt(field: str, bad_value: object) -> None:
    wire = _wire(_alarm_handler_result())
    receipt = copy.deepcopy(wire["commit_receipt"])
    assert type(receipt) is dict
    receipt[field] = bad_value
    wire["commit_receipt"] = receipt

    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None


def test_alarm_ack_codec_rejects_open_or_cross_command_shapes() -> None:
    command = _alarm_command()
    wire = _wire(_alarm_handler_result())

    extra_outer = {**wire, "compat": True}
    missing_outer = dict(wire)
    missing_outer.pop("publication_state")
    extra_receipt = copy.deepcopy(wire)
    assert type(extra_receipt["commit_receipt"]) is dict
    extra_receipt["commit_receipt"]["compat"] = True
    cross_command = {**command, "reason": "different reason"}

    for candidate, bound_command in (
        (extra_outer, command),
        (missing_outer, command),
        (extra_receipt, command),
        (wire, cross_command),
    ):
        assert validate_alarm_ack_wire_result(candidate, bound_command, expected_proto=PROTOCOL_VERSION) is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("error_code", "temporary"),
        ("error", ""),
        ("error", "line one\nline two"),
        ("error", "x" * 513),
    ],
)
def test_alarm_ack_codec_rejects_malformed_pending_error(field: str, bad_value: object) -> None:
    wire = _wire(_alarm_handler_result(pending=True))
    wire[field] = bad_value

    assert validate_alarm_ack_wire_result(wire, _alarm_command(), expected_proto=PROTOCOL_VERSION) is None


def test_alarm_ack_request_identity_is_stable_and_semantically_scoped() -> None:
    command = _alarm_command()
    repeated = _alarm_command()

    assert command["request_id"] == repeated["request_id"]
    semantic = {
        "alarm_name": command["alarm_name"],
        "engine_instance_id": command["engine_instance_id"],
        "activation_id": command["activation_id"],
        "operator": command["operator"],
        "reason": command["reason"],
    }
    identities = {command["request_id"]}
    for field, replacement in (
        ("alarm_name", f"{command['alarm_name']}-new"),
        ("engine_instance_id", _ENGINE_B),
        ("activation_id", "public-activation-b"),
        ("operator", "operator-b"),
        ("reason", "different observed reason"),
    ):
        candidate = {**semantic, field: replacement}
        identities.add(deterministic_alarm_ack_request_id(**candidate))
    assert len(identities) == 6


@pytest.mark.parametrize(
    ("command_factory", "fingerprint"),
    [
        pytest.param(_alarm_command, alarm_ack_request_fingerprint, id="alarm"),
        pytest.param(lambda: _safety_command(), safety_audio_ack_request_fingerprint, id="safety-audio"),
    ],
)
@pytest.mark.parametrize("field", ["operator", "reason"])
@pytest.mark.parametrize("edge", ["leading", "trailing"])
def test_ack_request_fingerprints_reject_noncanonical_attribution(
    command_factory,
    fingerprint,
    field: str,
    edge: str,
) -> None:
    command = command_factory()
    command[field] = f" {command[field]}" if edge == "leading" else f"{command[field]} "

    with pytest.raises(ValueError, match="canonical"):
        fingerprint(command)


def _safety_command() -> dict[str, str]:
    semantic = {
        "cmd": "annunciation_ack",
        "engine_instance_id": _ENGINE_A,
        "activation_id": "safety-public-a",
        "operator": "operator-a",
        "reason": "observed locally",
    }
    return {
        **semantic,
        "request_id": deterministic_safety_audio_ack_request_id(
            engine_instance_id=semantic["engine_instance_id"],
            activation_id=semantic["activation_id"],
            operator=semantic["operator"],
            reason=semantic["reason"],
        ),
    }


def _safety_handler_result() -> dict[str, object]:
    command = _safety_command()
    return {
        "ok": True,
        "engine_instance_id": command["engine_instance_id"],
        "activation_id": command["activation_id"],
        "request_id": command["request_id"],
        "snapshot_revision": 8,
        "audit_receipt": {
            "schema": "safety_audio_ack_v1",
            "request_id": command["request_id"],
            "request_fingerprint": safety_audio_ack_request_fingerprint(command),
            "engine_instance_id": command["engine_instance_id"],
            "activation_id": command["activation_id"],
            "source_activation_id": "9",
            "entry_id": 12,
            "committed": True,
        },
    }


def test_safety_audio_ack_codec_accepts_real_wire_and_stable_restart_identity() -> None:
    command = _safety_command()
    wire = _wire(_safety_handler_result())

    assert validate_safety_audio_ack_wire_result(wire, command, expected_proto=PROTOCOL_VERSION)
    assert _safety_command()["request_id"] == command["request_id"]
    assert not validate_safety_audio_ack_wire_result(_safety_handler_result(), command, expected_proto=PROTOCOL_VERSION)


def test_safety_audio_ack_request_identity_changes_with_every_semantic_field() -> None:
    command = _safety_command()
    semantic = {
        "engine_instance_id": command["engine_instance_id"],
        "activation_id": command["activation_id"],
        "operator": command["operator"],
        "reason": command["reason"],
    }
    identities = {command["request_id"]}
    for field, replacement in (
        ("engine_instance_id", _ENGINE_B),
        ("activation_id", "safety-public-b"),
        ("operator", "operator-b"),
        ("reason", "different observed reason"),
    ):
        candidate = {**semantic, field: replacement}
        identities.add(deterministic_safety_audio_ack_request_id(**candidate))
    assert len(identities) == 5


@pytest.mark.parametrize(
    ("scope", "field", "bad_value"),
    [
        ("outer", "ok", 1),
        ("outer", "engine_instance_id", _ENGINE_B),
        ("outer", "activation_id", "other"),
        ("outer", "request_id", "f" * 32),
        ("outer", "snapshot_revision", True),
        ("outer", "snapshot_revision", -1),
        ("outer", "proto", True),
        ("receipt", "schema", "safety_audio_ack_v0"),
        ("receipt", "request_id", "f" * 32),
        ("receipt", "request_fingerprint", "f" * 64),
        ("receipt", "engine_instance_id", _ENGINE_B),
        ("receipt", "activation_id", "other"),
        ("receipt", "source_activation_id", "09"),
        ("receipt", "source_activation_id", "٧"),
        ("receipt", "source_activation_id", 9),
        ("receipt", "entry_id", True),
        ("receipt", "entry_id", 0),
        ("receipt", "committed", 1),
    ],
)
def test_safety_audio_ack_codec_rejects_corrupted_wire_identity(
    scope: str,
    field: str,
    bad_value: object,
) -> None:
    wire = _wire(_safety_handler_result())
    if scope == "outer":
        wire[field] = bad_value
    else:
        receipt = copy.deepcopy(wire["audit_receipt"])
        assert type(receipt) is dict
        receipt[field] = bad_value
        wire["audit_receipt"] = receipt

    assert not validate_safety_audio_ack_wire_result(wire, _safety_command(), expected_proto=PROTOCOL_VERSION)


@pytest.mark.parametrize("expected_proto", [True, 2.0, "2", None])
def test_ack_codecs_reject_non_exact_protocol_authority(expected_proto: object) -> None:
    with pytest.raises(TypeError, match="expected_proto"):
        validate_alarm_ack_wire_result(_wire(_alarm_handler_result()), _alarm_command(), expected_proto=expected_proto)
    with pytest.raises(TypeError, match="expected_proto"):
        validate_safety_audio_ack_wire_result(
            _wire(_safety_handler_result()),
            _safety_command(),
            expected_proto=expected_proto,
        )
