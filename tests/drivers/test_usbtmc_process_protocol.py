"""Adversarial guards for the bounded USBTMC process-owner protocol."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import pytest

import cryodaq.drivers.transport.usbtmc as usbtmc


class _Connection:
    def __init__(self, incoming: list[bytes | BaseException] | None = None) -> None:
        self.incoming = deque(incoming or [])
        self.sent: list[bytes] = []
        self.closed = False

    def poll(self, _timeout: float = 0.0) -> bool:
        return bool(self.incoming)

    def recv_bytes(self, maxlength: int | None = None) -> bytes:
        if not self.incoming:
            raise EOFError
        value = self.incoming.popleft()
        if isinstance(value, BaseException):
            raise value
        if maxlength is not None and len(value) > maxlength:
            raise OSError("frame exceeds receiver bound")
        return value

    def send_bytes(self, value: bytes) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(self, *, alive: bool = True, refuse_terminate: bool = False, refuse_kill: bool = False) -> None:
        self.alive = alive
        self.exitcode: int | None = None if alive else 0
        self.refuse_terminate = refuse_terminate
        self.refuse_kill = refuse_kill
        self.terminate_calls = 0
        self.kill_calls = 0
        self.close_calls = 0

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.refuse_terminate:
            self.alive = False
            self.exitcode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        if not self.refuse_kill:
            self.alive = False
            self.exitcode = -9

    def join(self, _timeout: float) -> None:
        return None

    def close(self) -> None:
        self.close_calls += 1


def _owner(
    *,
    incoming: list[bytes | BaseException] | None = None,
    process: _Process | None = None,
    generation: int = 1,
) -> tuple[usbtmc._VisaProcessOwner, _Connection, _Process]:
    connection = _Connection(incoming)
    actual_process = process or _Process()
    owner = usbtmc._VisaProcessOwner(
        process=actual_process,
        connection=connection,
        generation=generation,
    )
    return owner, connection, actual_process


def _response(
    operation: str,
    *,
    generation: object = 1,
    sequence: object = 0,
    status: object = "ok",
    payload: object | None = None,
    **changes: object,
) -> bytes:
    document: dict[str, object] = {
        "version": 1,
        "kind": "response",
        "operation": operation,
        "generation": generation,
        "sequence": sequence,
        "status": status,
        "payload": {} if payload is None else payload,
    }
    document.update(changes)
    return usbtmc._encode_ipc_frame(document)


def test_production_transport_has_no_executor_or_mutable_process_target_seam() -> None:
    transport = usbtmc.USBTMCTransport(mock=False)

    assert not hasattr(transport, "_executor")
    assert not hasattr(transport, "_get_executor")
    assert not hasattr(transport, "_process_target")


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"[]",
        b'{"version":1,"version":1}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'{"value":1e10000}',
        b'{"value":1.0}',
        b'{"value":"\xff"}',
        b"x" * (usbtmc._IPC_FRAME_MAX_BYTES + 1),
    ],
    ids=[
        "empty",
        "wrong-root",
        "duplicate",
        "nan",
        "infinity",
        "negative-infinity",
        "float-overflow",
        "float",
        "non-ascii",
        "oversize",
    ],
)
def test_ipc_decoder_rejects_noncanonical_or_unbounded_frames(frame: bytes) -> None:
    with pytest.raises(ValueError):
        usbtmc._decode_ipc_frame(frame)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("generation", True),
        ("generation", 0),
        ("generation", 2**63),
        ("sequence", False),
        ("sequence", -1),
        ("sequence", 2**63),
        ("kind", 1),
        ("kind", "request"),
        ("operation", 1),
        ("operation", "write"),
        ("status", True),
        ("status", "maybe"),
    ],
)
def test_response_correlation_rejects_bool_aliases_ranges_and_wrong_scalars(field: str, value: object) -> None:
    document = usbtmc._decode_ipc_frame(_response("query", payload={"text": "0"}))
    document[field] = value

    with pytest.raises(ValueError):
        usbtmc._validate_response(document, operation="query", generation=1, sequence=0)


@pytest.mark.parametrize("timeout", [0, -1, True, False, 120001, 1.0, float("nan"), float("inf")])
def test_query_timeout_requires_exact_finite_bounded_integer(timeout: object) -> None:
    with pytest.raises(ValueError):
        usbtmc._bounded_timeout_ms(timeout)


@pytest.mark.parametrize(
    "payload",
    [
        {"command": ""},
        {"command": "x" * (usbtmc._IPC_COMMAND_MAX_BYTES + 1)},
        {"command": "ok", "extra": "forbidden"},
        {"data_b64": "not-base64!"},
        {"data_b64": ""},
        {"data_b64": "QQ==", "extra": True},
    ],
)
def test_worker_rejects_invalid_operation_payload_with_fixed_code(monkeypatch, payload: dict[str, object]) -> None:
    class Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            return "0"

        def write(self, _command: str) -> None:
            return None

        def write_raw(self, _data: bytes) -> None:
            return None

    connection = _Connection(
        [
            usbtmc._encode_ipc_frame(
                usbtmc._request_document("open", generation=1, sequence=0, payload={"resource": "USB0::1"})
            ),
            usbtmc._encode_ipc_frame(
                usbtmc._request_document(
                    "write_raw" if "data_b64" in payload else "write",
                    generation=1,
                    sequence=1,
                    payload=payload,
                )
            ),
            EOFError(),
        ]
    )
    monkeypatch.setattr(usbtmc, "_blocking_open_handles", lambda _resource: (object(), Resource()))

    usbtmc._visa_process_main(connection)

    assert len(connection.sent) == 2
    error = usbtmc._decode_ipc_frame(connection.sent[1])
    assert error["status"] == "error"
    assert error["payload"] == {"code": "IPC_REQUEST_INVALID"}
    assert connection.closed is True


def test_worker_exports_fixed_error_code_without_exception_text(monkeypatch) -> None:
    secret = "TOP-SECRET\r\nFORGED"

    class Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            raise RuntimeError(secret)

    connection = _Connection(
        [
            usbtmc._encode_ipc_frame(
                usbtmc._request_document("open", generation=1, sequence=0, payload={"resource": "USB0::1"})
            ),
            usbtmc._encode_ipc_frame(
                usbtmc._request_document(
                    "query",
                    generation=1,
                    sequence=1,
                    payload={"command": "print(1)", "timeout_ms": 1000},
                )
            ),
            EOFError(),
        ]
    )
    monkeypatch.setattr(usbtmc, "_blocking_open_handles", lambda _resource: (object(), Resource()))

    usbtmc._visa_process_main(connection)

    wire = b"".join(connection.sent)
    assert secret.encode() not in wire
    assert usbtmc._decode_ipc_frame(connection.sent[1])["payload"] == {"code": "VISA_QUERY_FAILED"}


@pytest.mark.asyncio
async def test_malformed_response_quarantines_and_reaps_exact_owner() -> None:
    owner, connection, process = _owner(incoming=[_response("query", generation=True, payload={"text": "0"})])
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCRemoteOperationError) as raised:
        await transport.query("print(1)")

    assert raised.value.error_code == "IPC_PROTOCOL_FAILED"
    assert connection.closed
    assert process.terminate_calls == 1
    assert transport._process_owner is None
    assert transport._close_incomplete is True
    assert transport._close_settled is True


@pytest.mark.asyncio
async def test_parent_protocol_invalid_receipt_quarantines_exact_generation() -> None:
    owner, connection, process = _owner(
        incoming=[_response("write", status="error", payload={"code": "IPC_REQUEST_INVALID"})]
    )
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCIncompleteCloseError) as raised:
        await transport.write("smua.source.output = smua.OUTPUT_OFF")

    assert raised.value.settled is True
    assert isinstance(raised.value.terminal_error, usbtmc.USBTMCRemoteOperationError)
    assert raised.value.terminal_error.error_code == "IPC_REQUEST_INVALID"
    assert process.terminate_calls == 1
    assert connection.closed is True
    assert transport._process_owner is None
    assert transport._close_incomplete is True
    assert len(connection.sent) == 1
    with pytest.raises(RuntimeError, match="terminal|no live"):
        await transport.write("smua.source.output = smua.OUTPUT_OFF")
    assert len(connection.sent) == 1


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("query", {"command": "print(1)", "timeout_ms": 1000}),
        ("open", {"resource": "USB0::1", "extra": True}),
    ],
)
def test_worker_rejects_invalid_initial_request_before_native_open(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    payload: dict[str, object],
) -> None:
    native_calls: list[str] = []
    connection = _Connection(
        [usbtmc._encode_ipc_frame(usbtmc._request_document(operation, generation=1, sequence=0, payload=payload))]
    )
    monkeypatch.setattr(
        usbtmc,
        "_blocking_open_handles",
        lambda _resource: native_calls.append("open") or (object(), object()),
    )

    usbtmc._visa_process_main(connection)

    assert native_calls == []
    assert connection.closed is True
    assert len(connection.sent) == 1
    receipt = usbtmc._decode_ipc_frame(connection.sent[0])
    assert receipt["operation"] == operation
    assert receipt["payload"] == {"code": "IPC_REQUEST_INVALID"}
    assert receipt["status"] == "error"


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("query", {"command": "print(1)", "timeout_ms": True}),
        ("query", {"command": "print(1)", "timeout_ms": 0}),
        ("query", {"command": "print(1)", "timeout_ms": 120001}),
        ("query", {"command": "print(1)", "timeout_ms": 1000, "extra": True}),
        ("close", {"extra": True}),
    ],
)
def test_worker_rejects_invalid_query_or_close_before_native_call(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    payload: dict[str, object],
) -> None:
    native_calls: list[str] = []

    class Resource:
        def query(self, _command: str) -> str:
            native_calls.append("query")
            return "0"

        def close(self) -> None:
            native_calls.append("resource-close")

    class Manager:
        def close(self) -> None:
            native_calls.append("manager-close")

    connection = _Connection(
        [
            usbtmc._encode_ipc_frame(
                usbtmc._request_document("open", generation=1, sequence=0, payload={"resource": "USB0::1"})
            ),
            usbtmc._encode_ipc_frame(usbtmc._request_document(operation, generation=1, sequence=1, payload=payload)),
        ]
    )
    monkeypatch.setattr(usbtmc, "_blocking_open_handles", lambda _resource: (Manager(), Resource()))

    usbtmc._visa_process_main(connection)

    assert native_calls == []
    assert connection.closed is True
    assert len(connection.sent) == 2
    receipt = usbtmc._decode_ipc_frame(connection.sent[1])
    assert receipt["operation"] == operation
    assert receipt["payload"] == {"code": "IPC_REQUEST_INVALID"}
    assert receipt["status"] == "error"


def test_worker_rejects_float_timeout_frame_before_native_call(monkeypatch: pytest.MonkeyPatch) -> None:
    native_calls: list[str] = []
    connection = _Connection(
        [
            usbtmc._encode_ipc_frame(
                usbtmc._request_document("open", generation=1, sequence=0, payload={"resource": "USB0::1"})
            ),
            (
                b'{"generation":1,"kind":"request","operation":"query",'
                b'"payload":{"command":"print(1)","timeout_ms":1.0},'
                b'"sequence":1,"version":1}'
            ),
        ]
    )
    monkeypatch.setattr(
        usbtmc,
        "_blocking_open_handles",
        lambda _resource: (object(), type("Resource", (), {"query": lambda *_args: native_calls.append("query")})()),
    )

    usbtmc._visa_process_main(connection)

    assert native_calls == []
    assert connection.closed is True
    # The JSON decoder rejects all floats before a request identity can be
    # trusted, so only the prior valid open receipt may be emitted.
    assert len(connection.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("incoming", [[EOFError()], []], ids=["eof", "death"])
async def test_eof_or_child_death_never_becomes_success(incoming: list[BaseException]) -> None:
    process = _Process(alive=bool(incoming))
    owner, _connection, process = _owner(incoming=incoming, process=process)
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCRemoteOperationError) as raised:
        await transport.write("smua.source.output = 0")

    assert raised.value.error_code == "IPC_PROTOCOL_FAILED"
    assert transport._close_incomplete is True
    assert transport._close_settled is True


def test_terminate_and_kill_failure_retains_exact_owner() -> None:
    process = _Process(refuse_terminate=True, refuse_kill=True)
    owner, _connection, _process = _owner(process=process)
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    assert transport._quarantine_process_owner(owner, error=RuntimeError("protocol")) is False
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert transport._process_owner is owner
    assert transport._close_settled is False


@pytest.mark.asyncio
async def test_later_close_reconciles_same_owner_without_second_physical_close() -> None:
    process = _Process(refuse_terminate=True, refuse_kill=True)
    owner, connection, _process = _owner(process=process)
    owner.close_command_sent = True
    owner.close_receipt = {"resource_error": None, "manager_error": None}
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCIncompleteCloseError) as first:
        await transport.close()
    assert first.value.settled is False
    assert transport._process_owner is owner
    assert connection.sent == []

    process.refuse_terminate = False
    await transport.close()

    assert transport._process_owner is None
    assert connection.sent == []
    assert transport._close_settled is True
    assert transport._close_incomplete is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [[], {}, True, 1, "WRONG"])
async def test_malformed_close_receipt_is_typed_terminal_after_owner_stop(bad_value: Any) -> None:
    process = _Process(alive=False)
    owner, _connection, _process = _owner(process=process)
    owner.close_command_sent = True
    owner.close_receipt = {"resource_error": bad_value, "manager_error": None}
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCIncompleteCloseError) as raised:
        await transport.close()

    assert raised.value.settled is True
    assert transport._process_owner is None
    assert transport._close_settled is True


@pytest.mark.asyncio
async def test_cancelled_operation_has_bounded_process_settlement() -> None:
    owner, _connection, process = _owner()
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")
    task = asyncio.create_task(transport.query("print(1)", timeout_ms=120_000))
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminate_calls == 1
    assert transport._process_owner is None
    assert transport._close_settled is True


@pytest.mark.asyncio
async def test_query_failure_quarantine_allows_only_exact_off_traffic_and_fresh_challenge() -> None:
    nonce = "d" * 32
    challenge = f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))'
    incoming = [
        _response("query", status="error", payload={"code": "VISA_QUERY_FAILED"}),
        _response("write", sequence=1),
        _response("query", sequence=2, payload={"text": f"CRYODAQ_OFF_V1|{nonce}|0"}),
    ]
    owner, connection, _process = _owner(incoming=incoming)
    transport = usbtmc.USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")

    with pytest.raises(usbtmc.USBTMCRemoteOperationError) as failed_query:
        await transport.query("poison-query")
    assert failed_query.value.error_code == "VISA_QUERY_FAILED"
    assert transport._query_desynchronized is True

    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write("smua.source.output = 1")
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write_raw(b"unsafe")
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query("print(smua.source.output)")

    await transport.write("smua.source.output = smua.OUTPUT_OFF")
    assert await transport.query(challenge) == f"CRYODAQ_OFF_V1|{nonce}|0"
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query(challenge)

    assert len(connection.sent) == 3


@pytest.mark.asyncio
async def test_clean_close_and_fresh_open_are_both_required_to_clear_query_quarantine(monkeypatch) -> None:
    transport = usbtmc.USBTMCTransport(mock=False)
    old_owner, old_connection, old_process = _owner(
        incoming=[_response("close", payload={"resource_error": None, "manager_error": None})]
    )
    transport._process_owner = old_owner
    transport._resource = usbtmc._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc._ProcessHandleToken(1, "manager")
    transport._query_desynchronized = True

    with pytest.raises(RuntimeError, match="already open|clean close"):
        await transport.open("USB0::NEW")

    await transport.close()
    assert old_process.terminate_calls == 1
    assert old_connection.closed
    assert transport._quarantine_clean_close is True
    assert transport._query_desynchronized is True

    new_connection = _Connection([_response("open", generation=1)])
    new_process = _Process()

    class ChildConnection:
        def close(self) -> None:
            return None

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[_Connection, ChildConnection]:
            assert duplex is True
            return new_connection, ChildConnection()

        def Process(self, **kwargs: object) -> _Process:
            assert kwargs["target"] is usbtmc._visa_process_main
            assert kwargs["daemon"] is True
            return new_process

    monkeypatch.setattr(usbtmc.multiprocessing, "get_context", lambda method: Context())

    await transport.open("USB0::NEW")

    assert transport._query_desynchronized is False
    assert transport._quarantine_clean_close is False
    assert isinstance(transport._resource, usbtmc._ProcessHandleToken)
    assert isinstance(transport._rm, usbtmc._ProcessHandleToken)


def test_utf8_bounds_are_measured_in_bytes_not_code_points() -> None:
    exact = "я" * (usbtmc._IPC_RESOURCE_MAX_BYTES // 2)
    assert usbtmc._bounded_text(exact, field="resource", maximum=usbtmc._IPC_RESOURCE_MAX_BYTES) == exact

    with pytest.raises(ValueError):
        usbtmc._bounded_text(exact + "я", field="resource", maximum=usbtmc._IPC_RESOURCE_MAX_BYTES)


def test_frame_encoder_rejects_nonfinite_and_unserializable_values() -> None:
    for value in (float("nan"), float("inf"), object()):
        with pytest.raises(ValueError):
            usbtmc._encode_ipc_frame({"value": value})
