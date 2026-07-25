"""Асинхронная обёртка над pyvisa для USB-TMC коммуникации."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import multiprocessing
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Имитированные ответы Keithley 2604B для mock-режима
_MOCK_IDN = "Keithley Instruments Inc., Model 2604B, MOCK00001, 3.0.0"
# smua.measure.iv() возвращает ток\tнапряжение
_MOCK_IV_RESPONSE = "0.01\t5.0"
_CLOSE_TIMEOUT_S = 1.0
_OPEN_TIMEOUT_S = 5.0
_IO_SETTLE_TIMEOUT_S = 6.0
_PROCESS_JOIN_TIMEOUT_S = 0.5
_IPC_VERSION = 1
_IPC_FRAME_MAX_BYTES = 1_100_000
_IPC_RESOURCE_MAX_BYTES = 1_024
_IPC_COMMAND_MAX_BYTES = 262_144
_IPC_RAW_MAX_BYTES = 786_432
_IPC_RESPONSE_MAX_BYTES = 1_048_576
_IPC_TIMEOUT_MIN_MS = 1
_IPC_TIMEOUT_MAX_MS = 120_000
_IPC_COUNTER_MAX = (1 << 63) - 1
_IPC_OPERATIONS = frozenset({"open", "query", "write", "write_raw", "close"})
_OFF_CHALLENGE_RE = re.compile(
    r'^print\(string\.format\("CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g", '
    r"(smua|smub)\.source\.output\)\)$"
)
_QUARANTINE_OFF_WRITES = frozenset(
    {
        "smua.source.levelv = 0",
        "smub.source.levelv = 0",
        "smua.source.output = smua.OUTPUT_OFF",
        "smub.source.output = smub.OUTPUT_OFF",
    }
)
_MOCK_PRINTBUFFER_RE = re.compile(
    r"printbuffer\((\d+), (\d+), (smua|smub)\.nvbuffer1\.timestamps, "
    r"\3\.nvbuffer1\.sourcevalues, \3\.nvbuffer1\)"
)


class USBTMCIncompleteCloseError(RuntimeError):
    """A VISA handle remains owned by an unsettled close operation.

    A normal return from :meth:`USBTMCTransport.close` is therefore a terminal
    settlement receipt, not merely evidence that a wrapper was invoked.
    """

    def __init__(
        self,
        message: str,
        *,
        settled: bool = False,
        terminal_error: BaseException | None = None,
        primary_error: BaseException | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.settled = settled
        self.terminal_error = terminal_error
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error


class USBTMCFailedOpenError(RuntimeError):
    """Preserve both exact failures from one failed VISA open attempt."""

    def __init__(self, *, primary_error: BaseException, cleanup_error: BaseException) -> None:
        super().__init__("USBTMC VISA open failed and resource-manager cleanup also failed")
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error


class _HandleCloseFailure(RuntimeError):
    """Exact terminal failures from one resource/manager close attempt."""

    def __init__(
        self,
        resource_error: BaseException | None,
        manager_error: BaseException | None,
    ) -> None:
        self.resource_error = resource_error
        self.manager_error = manager_error
        super().__init__(self._message())

    def _message(self) -> str:
        failures = []
        if self.resource_error is not None:
            failures.append(f"resource: {self.resource_error}")
        if self.manager_error is not None:
            failures.append(f"manager: {self.manager_error}")
        return "USBTMC handle close failed (" + "; ".join(failures) + ")"


@dataclass(frozen=True)
class _HandleCloseOutcome:
    resource_error: BaseException | None = None
    manager_error: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return self.resource_error is None and self.manager_error is None


class USBTMCRemoteOperationError(RuntimeError):
    """A bounded VISA worker reported an exception without exporting handles."""

    def __init__(self, operation: str, error_code: str) -> None:
        super().__init__(f"USBTMC {operation} failed in bounded worker ({error_code})")
        self.operation = operation
        self.error_code = error_code


@dataclass(frozen=True)
class _ProcessHandleToken:
    generation: int
    kind: str


@dataclass
class _VisaProcessOwner:
    process: Any
    connection: Any
    generation: int
    next_sequence: int = 0
    close_command_sent: bool = False
    close_receipt: dict[str, Any] | None = None
    terminal_error: BaseException | None = None


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate IPC object key")
        value[key] = item
    return value


def _reject_json_float_or_constant(_value: str) -> None:
    raise ValueError("USBTMC IPC protocol does not admit floating-point values")


def _encode_ipc_frame(document: dict[str, Any]) -> bytes:
    try:
        frame = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid USBTMC IPC document") from exc
    if not frame or len(frame) > _IPC_FRAME_MAX_BYTES:
        raise ValueError("USBTMC IPC frame exceeds the fixed bound")
    return frame


def _decode_ipc_frame(frame: bytes) -> dict[str, Any]:
    if type(frame) is not bytes or not frame or len(frame) > _IPC_FRAME_MAX_BYTES:
        raise ValueError("invalid USBTMC IPC frame size")
    try:
        value = json.loads(
            frame.decode("ascii"),
            object_pairs_hook=_strict_json_object,
            parse_float=_reject_json_float_or_constant,
            parse_constant=_reject_json_float_or_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid USBTMC IPC frame encoding") from exc
    if type(value) is not dict:
        raise ValueError("USBTMC IPC frame root must be an object")
    return value


def _bounded_text(value: Any, *, field: str, maximum: int) -> str:
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8") from exc
    if not encoded or len(encoded) > maximum:
        raise ValueError(f"{field} exceeds its fixed bound")
    return value


def _bounded_timeout_ms(value: Any) -> int:
    if type(value) is not int or not (_IPC_TIMEOUT_MIN_MS <= value <= _IPC_TIMEOUT_MAX_MS):
        raise ValueError("timeout_ms is outside the fixed finite range")
    return value


def _error_code(operation: str, *, cleanup: bool = False) -> str:
    if cleanup:
        return "VISA_MANAGER_CLOSE_FAILED"
    return {
        "open": "VISA_OPEN_FAILED",
        "query": "VISA_QUERY_FAILED",
        "write": "VISA_WRITE_FAILED",
        "write_raw": "VISA_WRITE_RAW_FAILED",
        "close": "VISA_CLOSE_FAILED",
    }.get(operation, "VISA_OPERATION_FAILED")


def _request_document(operation: str, *, generation: int, sequence: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "generation": generation,
        "kind": "request",
        "operation": operation,
        "payload": payload,
        "sequence": sequence,
        "version": _IPC_VERSION,
    }


def _response_document(
    operation: str,
    *,
    generation: int,
    sequence: int,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generation": generation,
        "kind": "response",
        "operation": operation,
        "payload": payload,
        "sequence": sequence,
        "status": status,
        "version": _IPC_VERSION,
    }


def _validate_request(
    document: dict[str, Any],
    *,
    expected_generation: int | None,
    expected_sequence: int,
) -> tuple[str, int, int, dict[str, Any]]:
    if set(document) != {"generation", "kind", "operation", "payload", "sequence", "version"}:
        raise ValueError("invalid USBTMC request schema")
    generation = document["generation"]
    sequence = document["sequence"]
    operation = document["operation"]
    payload = document["payload"]
    if (
        type(document["version"]) is not int
        or document["version"] != _IPC_VERSION
        or type(document["kind"]) is not str
        or document["kind"] != "request"
        or type(generation) is not int
        or not (1 <= generation <= _IPC_COUNTER_MAX)
        or type(sequence) is not int
        or not (0 <= sequence <= _IPC_COUNTER_MAX)
        or sequence != expected_sequence
        or type(operation) is not str
        or operation not in _IPC_OPERATIONS
        or type(payload) is not dict
    ):
        raise ValueError("invalid USBTMC request envelope")
    if expected_generation is not None and generation != expected_generation:
        raise ValueError("USBTMC request generation mismatch")
    return operation, generation, sequence, payload


def _validate_response(
    document: dict[str, Any],
    *,
    operation: str,
    generation: int,
    sequence: int,
) -> tuple[str, dict[str, Any]]:
    if set(document) != {
        "generation",
        "kind",
        "operation",
        "payload",
        "sequence",
        "status",
        "version",
    }:
        raise ValueError("invalid USBTMC response schema")
    payload = document["payload"]
    status = document["status"]
    response_generation = document["generation"]
    response_sequence = document["sequence"]
    if (
        type(document["version"]) is not int
        or document["version"] != _IPC_VERSION
        or type(document["kind"]) is not str
        or document["kind"] != "response"
        or type(document["operation"]) is not str
        or document["operation"] not in _IPC_OPERATIONS
        or document["operation"] != operation
        or type(response_generation) is not int
        or not (1 <= response_generation <= _IPC_COUNTER_MAX)
        or response_generation != generation
        or type(response_sequence) is not int
        or not (0 <= response_sequence <= _IPC_COUNTER_MAX)
        or response_sequence != sequence
        or type(status) is not str
        or status not in {"ok", "error"}
        or type(payload) is not dict
    ):
        raise ValueError("invalid USBTMC response correlation")
    return status, payload


def _send_document(connection: Any, document: dict[str, Any]) -> None:
    connection.send_bytes(_encode_ipc_frame(document))


def _receive_document(connection: Any) -> dict[str, Any]:
    return _decode_ipc_frame(connection.recv_bytes(_IPC_FRAME_MAX_BYTES))


def _validated_operation_payload(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one exact request before any native call."""

    if operation == "open" and set(payload) == {"resource"}:
        return {
            "resource": _bounded_text(
                payload["resource"],
                field="resource",
                maximum=_IPC_RESOURCE_MAX_BYTES,
            )
        }
    if operation == "query" and set(payload) == {"command", "timeout_ms"}:
        return {
            "command": _bounded_text(
                payload["command"],
                field="command",
                maximum=_IPC_COMMAND_MAX_BYTES,
            ),
            "timeout_ms": _bounded_timeout_ms(payload["timeout_ms"]),
        }
    if operation == "write" and set(payload) == {"command"}:
        return {
            "command": _bounded_text(
                payload["command"],
                field="command",
                maximum=_IPC_COMMAND_MAX_BYTES,
            )
        }
    if operation == "write_raw" and set(payload) == {"data_b64"}:
        encoded = _bounded_text(
            payload["data_b64"],
            field="data_b64",
            maximum=(_IPC_RAW_MAX_BYTES * 4 // 3) + 4,
        )
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid write_raw encoding") from exc
        if not data or len(data) > _IPC_RAW_MAX_BYTES:
            raise ValueError("write_raw payload exceeds its fixed bound")
        return {"data": data}
    if operation == "close" and payload == {}:
        return {}
    raise ValueError("invalid USBTMC operation payload schema")


def _send_invalid_request_receipt(
    connection: Any,
    *,
    operation: str,
    generation: int,
    sequence: int,
) -> None:
    _send_document(
        connection,
        _response_document(
            operation,
            generation=generation,
            sequence=sequence,
            status="error",
            payload={"code": "IPC_REQUEST_INVALID"},
        ),
    )


def _blocking_open_handles(resource_str: str) -> tuple[Any, Any]:
    import pyvisa

    manager = pyvisa.ResourceManager()
    try:
        resource = manager.open_resource(resource_str)
    except BaseException as primary_error:
        try:
            manager.close()
        except BaseException as cleanup_error:
            combined = USBTMCFailedOpenError(
                primary_error=primary_error,
                cleanup_error=cleanup_error,
            )
            raise combined from primary_error
        raise
    return manager, resource


def _blocking_close_handles(resource: Any, manager: Any) -> _HandleCloseOutcome:
    resource_error: BaseException | None = None
    manager_error: BaseException | None = None
    try:
        if resource is not None:
            resource.close()
    except BaseException as exc:
        resource_error = exc
    try:
        if manager is not None:
            manager.close()
    except BaseException as exc:
        manager_error = exc
    return _HandleCloseOutcome(resource_error=resource_error, manager_error=manager_error)


def _visa_process_main(connection: Any) -> None:
    """Own native VISA handles behind a bounded, non-pickle protocol."""

    resource = None
    manager = None
    generation: int | None = None
    expected_sequence = 0
    try:
        request = _receive_document(connection)
        operation, generation, sequence, payload = _validate_request(
            request,
            expected_generation=None,
            expected_sequence=expected_sequence,
        )
        if operation != "open":
            _send_invalid_request_receipt(
                connection,
                operation=operation,
                generation=generation,
                sequence=sequence,
            )
            return
        try:
            validated_payload = _validated_operation_payload(operation, payload)
        except ValueError:
            _send_invalid_request_receipt(
                connection,
                operation=operation,
                generation=generation,
                sequence=sequence,
            )
            return
        resource_str = validated_payload["resource"]
        try:
            manager, resource = _blocking_open_handles(resource_str)
        except USBTMCFailedOpenError:
            _send_document(
                connection,
                _response_document(
                    "open",
                    generation=generation,
                    sequence=sequence,
                    status="error",
                    payload={
                        "cleanup_code": _error_code("open", cleanup=True),
                        "code": _error_code("open"),
                    },
                ),
            )
            return
        except BaseException:
            _send_document(
                connection,
                _response_document(
                    "open",
                    generation=generation,
                    sequence=sequence,
                    status="error",
                    payload={"code": _error_code("open")},
                ),
            )
            return
        _send_document(
            connection,
            _response_document(
                "open",
                generation=generation,
                sequence=sequence,
                status="ok",
                payload={},
            ),
        )
        expected_sequence += 1
        while True:
            request = _receive_document(connection)
            operation, _generation, sequence, payload = _validate_request(
                request,
                expected_generation=generation,
                expected_sequence=expected_sequence,
            )
            expected_sequence += 1
            if operation == "open":
                _send_invalid_request_receipt(
                    connection,
                    operation=operation,
                    generation=generation,
                    sequence=sequence,
                )
                return
            try:
                validated_payload = _validated_operation_payload(operation, payload)
            except ValueError:
                _send_invalid_request_receipt(
                    connection,
                    operation=operation,
                    generation=generation,
                    sequence=sequence,
                )
                return
            try:
                if operation == "query":
                    command = validated_payload["command"]
                    resource.timeout = validated_payload["timeout_ms"]
                    result = resource.query(command).strip()
                    _bounded_text(result, field="response", maximum=_IPC_RESPONSE_MAX_BYTES)
                    response_payload = {"text": result}
                elif operation == "write":
                    command = validated_payload["command"]
                    resource.write(command)
                    response_payload = {}
                elif operation == "write_raw":
                    resource.write_raw(validated_payload["data"])
                    response_payload = {}
                elif operation == "close":
                    outcome = _blocking_close_handles(resource, manager)
                    _send_document(
                        connection,
                        _response_document(
                            "close",
                            generation=generation,
                            sequence=sequence,
                            status="ok",
                            payload={
                                "manager_error": (
                                    None if outcome.manager_error is None else "VISA_MANAGER_CLOSE_FAILED"
                                ),
                                "resource_error": (
                                    None if outcome.resource_error is None else "VISA_RESOURCE_CLOSE_FAILED"
                                ),
                            },
                        ),
                    )
                    return
                else:
                    raise AssertionError("validated USBTMC operation has no native dispatch")
            except BaseException:
                _send_document(
                    connection,
                    _response_document(
                        operation,
                        generation=generation,
                        sequence=sequence,
                        status="error",
                        payload={"code": _error_code(operation)},
                    ),
                )
                continue
            _send_document(
                connection,
                _response_document(
                    operation,
                    generation=generation,
                    sequence=sequence,
                    status="ok",
                    payload=response_payload,
                ),
            )
    except (EOFError, BrokenPipeError, OSError, ValueError):
        return
    finally:
        try:
            connection.close()
        except (OSError, ValueError):
            pass


class USBTMCTransport:
    """Асинхронный транспорт USB-TMC на основе pyvisa.

    Production pyvisa ownership and blocking calls live in one tracked,
    killable subprocess so native hangs cannot outlive bounded settlement.
    Production dispatch has no thread-executor or private-method fallback.

    Интерфейс аналогичен :class:`~cryodaq.drivers.transport.gpib.GPIBTransport`,
    адаптирован для USB-TMC приборов (в частности Keithley 2604B с TSP).

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда,
        возвращает предопределённые ответы Keithley 2604B.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource: Any = None
        self._rm: Any = None
        self._resource_str: str = ""
        self._lock: asyncio.Lock = asyncio.Lock()
        self._process_owner: _VisaProcessOwner | None = None
        self._process_generation = 0
        self._close_terminal_error: BaseException | None = None
        self._close_incomplete = False
        self._close_settled = False
        # A failed query may leave an unread or partial response in the VISA
        # session. Once that happens no later response can be attributed to
        # its command with confidence. Recovery requires a clean close and a
        # genuinely successful new open.
        self._query_desynchronized = False
        self._quarantine_clean_close = False
        self._off_challenge_nonces: set[str] = set()
        # Внутренний счётчик для mock: имитация буфера измерений
        self._mock_buf_index: int = 0

    @staticmethod
    def _terminate_process_owner(owner: _VisaProcessOwner) -> bool:
        """Stop one exact owner; unknown process state is never settlement."""

        process = owner.process
        try:
            alive = process.is_alive()
        except (AssertionError, OSError, ValueError):
            return False
        if alive:
            try:
                process.terminate()
                process.join(_PROCESS_JOIN_TIMEOUT_S)
                alive = process.is_alive()
            except (AssertionError, OSError, ValueError):
                return False
        if alive:
            try:
                process.kill()
                process.join(_PROCESS_JOIN_TIMEOUT_S)
                alive = process.is_alive()
            except (AssertionError, OSError, ValueError):
                return False
        if alive:
            return False
        try:
            if process.exitcode is None:
                return False
        except (AssertionError, OSError, ValueError):
            return False
        try:
            owner.connection.close()
        except (OSError, ValueError):
            pass
        try:
            process.close()
        except (OSError, ValueError):
            pass
        return True

    async def _receive_process_message(
        self,
        owner: _VisaProcessOwner,
        *,
        operation: str,
        sequence: int,
        timeout_s: float,
    ) -> tuple[str, dict[str, Any]]:
        """Receive one bounded frame correlated to the exact owner request."""

        if not (0.0 < timeout_s <= (_IPC_TIMEOUT_MAX_MS / 1000.0 + 1.0)):
            raise ValueError("USBTMC IPC wait is outside the fixed finite range")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            if owner.connection.poll(0):
                document = _receive_document(owner.connection)
                return _validate_response(
                    document,
                    operation=operation,
                    generation=owner.generation,
                    sequence=sequence,
                )
            try:
                alive = owner.process.is_alive()
                exitcode = owner.process.exitcode
            except (AssertionError, OSError, ValueError) as exc:
                raise RuntimeError("USBTMC worker state is unavailable") from exc
            if not alive:
                raise RuntimeError(f"USBTMC worker exited without a receipt (exit code {exitcode})")
            if loop.time() >= deadline:
                raise TimeoutError("USBTMC worker did not settle within its wall-clock bound")
            await asyncio.sleep(0.005)

    def _send_process_request(
        self,
        owner: _VisaProcessOwner,
        operation: str,
        payload: dict[str, Any],
    ) -> int:
        sequence = owner.next_sequence
        _send_document(
            owner.connection,
            _request_document(
                operation,
                generation=owner.generation,
                sequence=sequence,
                payload=payload,
            ),
        )
        owner.next_sequence += 1
        return sequence

    def _release_stopped_owner(self, owner: _VisaProcessOwner) -> None:
        if self._process_owner is owner:
            self._process_owner = None
        if isinstance(self._resource, _ProcessHandleToken) and self._resource.generation == owner.generation:
            self._resource = None
        if isinstance(self._rm, _ProcessHandleToken) and self._rm.generation == owner.generation:
            self._rm = None

    def _quarantine_process_owner(
        self,
        owner: _VisaProcessOwner,
        *,
        error: BaseException,
    ) -> bool:
        """Terminate one exact process generation and retain terminal quarantine."""

        owner.terminal_error = owner.terminal_error or error
        self._close_incomplete = True
        self._close_terminal_error = owner.terminal_error
        self._query_desynchronized = True
        self._quarantine_clean_close = False
        stopped = self._terminate_process_owner(owner)
        self._close_settled = stopped
        if stopped:
            self._release_stopped_owner(owner)
        return stopped

    async def _settle_process_open(self, resource_str: str) -> None:
        """Create one process-owned VISA session using strict framed IPC."""

        resource_str = _bounded_text(resource_str, field="resource", maximum=_IPC_RESOURCE_MAX_BYTES)
        self._process_generation += 1
        generation = self._process_generation
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(
            target=_visa_process_main,
            args=(child_connection,),
            daemon=True,
            name=f"cryodaq-usbtmc-{generation}",
        )
        owner = _VisaProcessOwner(
            process=process,
            connection=parent_connection,
            generation=generation,
        )
        self._process_owner = owner
        try:
            try:
                process.start()
            finally:
                child_connection.close()
            sequence = self._send_process_request(owner, "open", {"resource": resource_str})
            status, payload = await self._receive_process_message(
                owner,
                operation="open",
                sequence=sequence,
                timeout_s=_OPEN_TIMEOUT_S,
            )
        except asyncio.CancelledError:
            error = RuntimeError("USBTMC open was cancelled before native ownership settled")
            self._quarantine_process_owner(owner, error=error)
            raise
        except BaseException as exc:
            stopped = self._quarantine_process_owner(owner, error=exc)
            raise USBTMCIncompleteCloseError(
                "USBTMC native open did not settle inside its bounded process",
                settled=stopped,
                terminal_error=exc,
            ) from exc
        if status == "ok" and payload == {}:
            self._resource = _ProcessHandleToken(generation, "resource")
            self._rm = _ProcessHandleToken(generation, "manager")
            return
        if status != "error":
            error = RuntimeError("USBTMC worker returned an invalid open receipt")
            stopped = self._quarantine_process_owner(owner, error=error)
            raise USBTMCIncompleteCloseError(
                "USBTMC worker returned an invalid open receipt",
                settled=stopped,
                terminal_error=error,
            ) from error

        if payload == {"code": "IPC_REQUEST_INVALID"}:
            protocol_error = USBTMCRemoteOperationError("open", "IPC_REQUEST_INVALID")
            stopped = self._quarantine_process_owner(owner, error=protocol_error)
            raise USBTMCIncompleteCloseError(
                "USBTMC open request was rejected as protocol corruption",
                settled=stopped,
                terminal_error=protocol_error,
            ) from protocol_error
        if payload == {"code": "VISA_OPEN_FAILED"}:
            primary = USBTMCRemoteOperationError("open", "VISA_OPEN_FAILED")
            stopped = self._terminate_process_owner(owner)
            if stopped:
                self._release_stopped_owner(owner)
            if not stopped:
                owner.terminal_error = primary
                self._close_incomplete = True
                self._close_terminal_error = primary
                self._close_settled = False
                raise USBTMCIncompleteCloseError(
                    "USBTMC failed-open owner did not reach bounded settlement",
                    settled=False,
                    terminal_error=primary,
                    primary_error=primary,
                ) from primary
            raise primary
        if payload == {
            "cleanup_code": "VISA_MANAGER_CLOSE_FAILED",
            "code": "VISA_OPEN_FAILED",
        }:
            primary = USBTMCRemoteOperationError("open", "VISA_OPEN_FAILED")
            cleanup = USBTMCRemoteOperationError("resource-manager cleanup", "VISA_MANAGER_CLOSE_FAILED")
            combined = USBTMCFailedOpenError(primary_error=primary, cleanup_error=cleanup)
            combined.__cause__ = primary
            stopped = self._terminate_process_owner(owner)
            if stopped:
                self._release_stopped_owner(owner)
            self._close_incomplete = True
            self._close_terminal_error = combined
            self._close_settled = stopped
            raise USBTMCIncompleteCloseError(
                "USBTMC open failed and resource-manager cleanup also failed",
                settled=stopped,
                terminal_error=combined,
                primary_error=primary,
                cleanup_error=cleanup,
            ) from combined
        error = RuntimeError("USBTMC worker returned an invalid open receipt")
        stopped = self._quarantine_process_owner(owner, error=error)
        raise USBTMCIncompleteCloseError(
            "USBTMC worker returned an invalid open receipt",
            settled=stopped,
            terminal_error=error,
        ) from error

    async def _call_process_owner(
        self,
        operation: str,
        payload: dict[str, Any],
        timeout_s: float,
    ) -> Any:
        owner = self._process_owner
        if owner is None or owner.close_command_sent:
            raise RuntimeError("USBTMC has no live process-owned session")
        try:
            sequence = self._send_process_request(owner, operation, payload)
            status, response_payload = await self._receive_process_message(
                owner,
                operation=operation,
                sequence=sequence,
                timeout_s=timeout_s,
            )
        except asyncio.CancelledError:
            error = RuntimeError(f"USBTMC {operation} was cancelled before native settlement")
            self._quarantine_process_owner(owner, error=error)
            raise
        except BaseException as exc:
            self._quarantine_process_owner(owner, error=exc)
            raise USBTMCRemoteOperationError(operation, "IPC_PROTOCOL_FAILED") from exc
        if status == "error" and response_payload == {"code": "IPC_REQUEST_INVALID"}:
            error = USBTMCRemoteOperationError(operation, "IPC_REQUEST_INVALID")
            stopped = self._quarantine_process_owner(owner, error=error)
            raise USBTMCIncompleteCloseError(
                "USBTMC worker rejected a corrupted operation request",
                settled=stopped,
                terminal_error=error,
            ) from error
        if status == "error" and response_payload == {"code": _error_code(operation)}:
            error = USBTMCRemoteOperationError(operation, response_payload["code"])
            if operation == "query":
                self._mark_query_desynchronized()
            raise error
        if status == "ok" and operation == "query" and set(response_payload) == {"text"}:
            return _bounded_text(
                response_payload["text"],
                field="response",
                maximum=_IPC_RESPONSE_MAX_BYTES,
            )
        if status == "ok" and operation in {"write", "write_raw"} and response_payload == {}:
            return None
        error = RuntimeError("USBTMC worker returned an invalid operation receipt")
        self._quarantine_process_owner(owner, error=error)
        raise error

    def _apply_close_receipt(self, owner: _VisaProcessOwner) -> None:
        receipt = owner.close_receipt
        if receipt is None or set(receipt) != {"manager_error", "resource_error"}:
            error = owner.terminal_error or RuntimeError("USBTMC process close returned no exact terminal receipt")
            self._close_incomplete = True
            self._close_terminal_error = error
            self._close_settled = True
            raise USBTMCIncompleteCloseError(
                "USBTMC process close returned no exact terminal receipt",
                settled=True,
                terminal_error=error,
            ) from error
        resource_code = receipt["resource_error"]
        manager_code = receipt["manager_error"]
        resource_code_valid = resource_code is None or (
            type(resource_code) is str and resource_code == "VISA_RESOURCE_CLOSE_FAILED"
        )
        manager_code_valid = manager_code is None or (
            type(manager_code) is str and manager_code == "VISA_MANAGER_CLOSE_FAILED"
        )
        if not resource_code_valid or not manager_code_valid:
            error = RuntimeError("USBTMC process close returned an invalid terminal receipt")
            self._close_incomplete = True
            self._close_terminal_error = error
            self._close_settled = True
            raise USBTMCIncompleteCloseError(
                "USBTMC process close returned no exact terminal receipt",
                settled=True,
                terminal_error=error,
            ) from error
        if resource_code is not None or manager_code is not None:
            resource_error = (
                None if resource_code is None else USBTMCRemoteOperationError("resource close", resource_code)
            )
            manager_error = None if manager_code is None else USBTMCRemoteOperationError("manager close", manager_code)
            failure = _HandleCloseFailure(resource_error, manager_error)
            failure.__cause__ = resource_error or manager_error
            self._close_incomplete = True
            self._close_terminal_error = failure
            self._close_settled = True
            raise USBTMCIncompleteCloseError(
                "USBTMC process-owned VISA handle close settled with a terminal failure",
                settled=True,
                terminal_error=failure,
            ) from failure
        self._close_incomplete = False
        self._close_terminal_error = None
        self._close_settled = True
        if self._query_desynchronized:
            self._quarantine_clean_close = True

    async def _close_process_owner(self) -> None:
        """Issue physical close once, then reconcile only the same owner."""

        owner = self._process_owner
        if owner is None:
            return
        if owner.close_command_sent:
            stopped = self._terminate_process_owner(owner)
            if not stopped:
                error = owner.terminal_error or RuntimeError("USBTMC worker remains alive after bounded stop")
                raise USBTMCIncompleteCloseError(
                    "USBTMC process close remains owned by the same unsettled owner",
                    settled=False,
                    terminal_error=error,
                ) from error
            self._release_stopped_owner(owner)
            if owner.close_receipt is not None:
                self._apply_close_receipt(owner)
                return
            error = owner.terminal_error or RuntimeError("USBTMC process close has no terminal receipt")
            self._close_incomplete = True
            self._close_terminal_error = error
            self._close_settled = True
            raise USBTMCIncompleteCloseError(
                "USBTMC process close settled without a physical-close receipt",
                settled=True,
                terminal_error=error,
            ) from error

        owner.close_command_sent = True
        try:
            sequence = self._send_process_request(owner, "close", {})
            status, payload = await self._receive_process_message(
                owner,
                operation="close",
                sequence=sequence,
                timeout_s=_CLOSE_TIMEOUT_S,
            )
        except asyncio.CancelledError as exc:
            terminal = RuntimeError("USBTMC close cancelled before exact native settlement")
            owner.terminal_error = terminal
            stopped = self._quarantine_process_owner(owner, error=terminal)
            incomplete = USBTMCIncompleteCloseError(
                "USBTMC close cancellation reached bounded process settlement",
                settled=stopped,
                terminal_error=terminal,
            )
            raise exc from incomplete
        except BaseException as exc:
            owner.terminal_error = owner.terminal_error or exc
            stopped = self._quarantine_process_owner(owner, error=owner.terminal_error)
            raise USBTMCIncompleteCloseError(
                "USBTMC close exceeded its bounded process settlement",
                settled=stopped,
                terminal_error=owner.terminal_error,
            ) from exc

        if status == "error" and payload == {"code": "IPC_REQUEST_INVALID"}:
            protocol_error = USBTMCRemoteOperationError("close", "IPC_REQUEST_INVALID")
            owner.terminal_error = protocol_error
            stopped = self._quarantine_process_owner(owner, error=protocol_error)
            raise USBTMCIncompleteCloseError(
                "USBTMC close request was rejected as protocol corruption",
                settled=stopped,
                terminal_error=protocol_error,
            ) from protocol_error
        if status != "ok":
            protocol_error = USBTMCRemoteOperationError("close", "IPC_PROTOCOL_FAILED")
            owner.terminal_error = protocol_error
            stopped = self._quarantine_process_owner(owner, error=protocol_error)
            raise USBTMCIncompleteCloseError(
                "USBTMC close response was protocol-corrupt",
                settled=stopped,
                terminal_error=protocol_error,
            ) from protocol_error
        owner.close_receipt = payload
        stopped = self._terminate_process_owner(owner)
        if not stopped:
            error = RuntimeError("USBTMC worker survived bounded termination after close")
            owner.terminal_error = error
            self._close_incomplete = True
            self._close_terminal_error = error
            self._close_settled = False
            raise USBTMCIncompleteCloseError(
                "USBTMC worker could not be reaped after close",
                settled=False,
                terminal_error=error,
            ) from error
        self._release_stopped_owner(owner)
        self._apply_close_receipt(owner)

    def _mark_query_desynchronized(self) -> None:
        self._query_desynchronized = True
        self._quarantine_clean_close = False

    def _authorize_write_locked(self, cmd: str) -> None:
        if self._query_desynchronized and (type(cmd) is not str or cmd not in _QUARANTINE_OFF_WRITES):
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")

    def _authorize_query_locked(self, cmd: str) -> None:
        if self._query_desynchronized and type(cmd) is not str:
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")
        challenge = _OFF_CHALLENGE_RE.fullmatch(cmd)
        if not self._query_desynchronized:
            if challenge is not None:
                self._off_challenge_nonces.add(challenge.group(1))
            return
        if challenge is None or challenge.group(1) in self._off_challenge_nonces:
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")
        self._off_challenge_nonces.add(challenge.group(1))

    async def open(self, resource_str: str) -> None:
        """Открыть соединение с USB-TMC ресурсом.

        Parameters
        ----------
        resource_str:
            VISA-строка ресурса, например
            ``"USB0::0x05E6::0x2604::SERIALNUM::INSTR"``.
        """
        async with self._lock:
            if self._close_incomplete:
                raise RuntimeError("USBTMC transport is terminal after an incomplete close")
            if not self.mock and (self._resource is not None or self._rm is not None):
                raise RuntimeError("USBTMC resource is already open; close it before reopening")
            if self._query_desynchronized and not self._quarantine_clean_close:
                raise RuntimeError("USBTMC quarantined session requires a completed clean close before reopening")
            self._resource_str = resource_str

            if self.mock:
                log.info("USBTMC [mock]: имитация открытия ресурса %s", resource_str)
                return

            try:
                await self._settle_process_open(resource_str)
                if self._resource is None or self._rm is None:
                    raise RuntimeError("USBTMC VISA open completed without resource handles")
                self._query_desynchronized = False
                self._quarantine_clean_close = False
                log.info("USBTMC: ресурс %s успешно открыт", resource_str)
            except Exception:
                log.error("USBTMC: resource open failed")
                raise

    async def close(self) -> None:
        """Close or reconcile the one exact process-owned VISA session."""
        async with self._lock:
            if self.mock:
                log.info("USBTMC [mock]: closing resource %s", self._resource_str)
                return
            if self._process_owner is not None:
                await self._close_process_owner()
                log.info("USBTMC: process-owned resource %s closed", self._resource_str)
                return
            if self._close_incomplete:
                terminal_error = self._close_terminal_error
                primary_error = (
                    terminal_error.primary_error if isinstance(terminal_error, USBTMCFailedOpenError) else None
                )
                cleanup_error = (
                    terminal_error.cleanup_error if isinstance(terminal_error, USBTMCFailedOpenError) else None
                )
                raise USBTMCIncompleteCloseError(
                    "USBTMC retained VISA handle close settled with a terminal failure; "
                    "reconnect and replacement are blocked",
                    settled=self._close_settled,
                    terminal_error=terminal_error,
                    primary_error=primary_error,
                    cleanup_error=cleanup_error,
                ) from terminal_error
            if self._resource is None and self._rm is None:
                return
            error = RuntimeError("USBTMC process handle tokens exist without their exact owner")
            self._close_incomplete = True
            self._close_terminal_error = error
            self._close_settled = False
            raise USBTMCIncompleteCloseError(
                "USBTMC retained VISA handles have no exact process owner",
                settled=False,
                terminal_error=error,
            ) from error

    async def write(self, cmd: str) -> None:
        """Отправить TSP-команду прибору без ожидания ответа.

        Parameters
        ----------
        cmd:
            TSP-команда на языке Lua, например
            ``"smua.source.output = smua.OUTPUT_OFF"``.
        """
        async with self._lock:
            cmd = _bounded_text(cmd, field="command", maximum=_IPC_COMMAND_MAX_BYTES)
            self._authorize_write_locked(cmd)
            if self.mock:
                log.debug("USBTMC [mock]: bounded write accepted")
                return
            try:
                await self._call_process_owner(
                    "write",
                    {"command": cmd},
                    timeout_s=_IO_SETTLE_TIMEOUT_S,
                )
                log.debug("USBTMC: bounded write completed")
            except Exception:
                log.error("USBTMC: bounded write failed")
                raise

    async def write_raw(self, data: bytes) -> None:
        """Отправить сырые байты прибору (для загрузки больших TSP-скриптов).

        Parameters
        ----------
        data:
            Байтовая последовательность для передачи в прибор.
        """
        async with self._lock:
            if type(data) is not bytes or not data or len(data) > _IPC_RAW_MAX_BYTES:
                raise ValueError("write_raw payload exceeds its fixed bound")
            if self._query_desynchronized:
                raise RuntimeError("USBTMC session is quarantined after query desynchronization")
            if self.mock:
                log.debug(
                    "USBTMC [mock] write_raw: %d байт",
                    len(data),
                )
                return
            try:
                await self._call_process_owner(
                    "write_raw",
                    {"data_b64": base64.b64encode(data).decode("ascii")},
                    timeout_s=_IO_SETTLE_TIMEOUT_S,
                )
                log.debug(
                    "USBTMC write_raw → %s: %d байт",
                    self._resource_str,
                    len(data),
                )
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка write_raw в %s — %s",
                    self._resource_str,
                    exc,
                )
                raise

    async def query(self, cmd: str, timeout_ms: int = 5000) -> str:
        """Отправить TSP-запрос и вернуть ответ прибора.

        Parameters
        ----------
        cmd:
            TSP-команда, возвращающая значение через ``print()``,
            например ``"print(smua.measure.iv())"``.
        timeout_ms:
            Таймаут ожидания ответа в миллисекундах (по умолчанию 5000).

        Returns
        -------
        str
            Ответ прибора без завершающих пробелов и символов новой строки.
        """
        async with self._lock:
            cmd = _bounded_text(cmd, field="command", maximum=_IPC_COMMAND_MAX_BYTES)
            timeout_ms = _bounded_timeout_ms(timeout_ms)
            self._authorize_query_locked(cmd)
            if self.mock:
                try:
                    response = self._mock_response(cmd)
                except BaseException:
                    self._mark_query_desynchronized()
                    raise
                log.debug("USBTMC [mock]: bounded query completed")
                return response
            try:
                response = await self._call_process_owner(
                    "query",
                    {"command": cmd, "timeout_ms": timeout_ms},
                    timeout_s=max(_IO_SETTLE_TIMEOUT_S, timeout_ms / 1000 + 1.0),
                )
                log.debug("USBTMC: bounded query completed")
                return response
            except Exception:
                log.error("USBTMC: bounded query failed")
                raise

    # ------------------------------------------------------------------
    # Блокирующие вспомогательные методы (выполняются в executor)
    # ------------------------------------------------------------------

    def _blocking_open(self, resource_str: str) -> tuple[Any, Any]:
        """Direct helper retained for isolated unit tests, never production dispatch."""
        return _blocking_open_handles(resource_str)

    def _blocking_close_handles(self, resource: Any, manager: Any) -> _HandleCloseOutcome:
        """Direct helper retained for isolated unit tests, never production dispatch."""
        return _blocking_close_handles(resource, manager)

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    def _mock_response(self, cmd: str) -> str:
        """Return evidence only for an exact, explicitly simulated query."""
        if cmd == "*IDN?":
            return _MOCK_IDN
        if cmd in {"print(smua.measure.iv())", "print(smub.measure.iv())"}:
            return _MOCK_IV_RESPONSE
        if cmd in {"print(smua.source.output)", "print(smub.source.output)"}:
            return "0"
        if cmd in {"print(smua.source.compliance)", "print(smub.source.compliance)"}:
            return "false"
        if cmd == "print(errorqueue.count)":
            return "0"
        if cmd == "print(CRYODAQ_WDOG_VERSION)":
            return "3"
        if cmd in {
            "print(cryodaq_wdog_active)",
            "print(cryodaq_wdog_autonomous)",
            "print(cryodaq_wdog_tripped)",
        }:
            return "0"
        challenge = _OFF_CHALLENGE_RE.fullmatch(cmd)
        if challenge is not None:
            return f"CRYODAQ_OFF_V1|{challenge.group(1)}|0"
        if _MOCK_PRINTBUFFER_RE.fullmatch(cmd) is not None:
            self._mock_buf_index += 1
            ts = float(self._mock_buf_index) * 0.5
            return f"{ts}\t5.0\t0.01"
        raise ValueError(f"unsupported USBTMC mock query: {cmd!r}")
