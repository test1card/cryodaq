from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_runtime import make_periodic_coordinator_factory
from cryodaq.agents.assistant.periodic_telegram import TelegramDeliveryResult, TelegramOutcome
from cryodaq.periodic_state import (
    PeriodicContractError,
    PeriodicStateDocument,
    load_periodic_state,
    periodic_local_destination_fingerprint,
    periodic_state_path,
    rotate_terminal_active,
    write_periodic_state,
)
from tests.agents.assistant.test_periodic_png_coordinator import _config
from tests.periodic.test_periodic_state_durable_edges import _variants
from tests.periodic.test_periodic_state_transitions import _allocate

HASH = "sha256:" + "a" * 64
TOKEN = "b" * 32
CAPTION_HASH = "sha256:" + hashlib.sha256(b"caption").hexdigest()


def _context() -> PeriodicDeliveryContext:
    return PeriodicDeliveryContext(HASH, TOKEN, "c" * 32, HASH, 33, CAPTION_HASH, 7)


def test_contract_module_has_no_provider_or_authority_imports() -> None:
    path = Path(__file__).resolve().parents[2] / "src/cryodaq/agents/assistant/periodic_delivery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {
        "aiohttp",
        "socket",
        "subprocess",
        "pathlib",
        "cryodaq.periodic_config",
        "cryodaq.agents.assistant.periodic_telegram",
    }


def test_receipt_contract_is_one_neutral_identity() -> None:
    from cryodaq.periodic_delivery_receipt import PeriodicDeliveryReceipt as NeutralReceipt

    assert PeriodicDeliveryReceipt is NeutralReceipt


def test_delivery_context_is_closed_and_bounded() -> None:
    assert _context().artifact_size == 33
    with pytest.raises(ValueError, match="artifact_size"):
        PeriodicDeliveryContext(HASH, TOKEN, "c" * 32, HASH, 32, CAPTION_HASH, 7)
    with pytest.raises(ValueError, match="slot_id"):
        PeriodicDeliveryContext("bad", TOKEN, "c" * 32, HASH, 33, CAPTION_HASH, 7)
    with pytest.raises(ValueError, match="owner_token"):
        PeriodicDeliveryContext(HASH, TOKEN, "owner", HASH, 33, CAPTION_HASH, 7)
    with pytest.raises(ValueError, match="caption_size"):
        PeriodicDeliveryContext(HASH, TOKEN, "c" * 32, HASH, 33, CAPTION_HASH, 0)


def test_receipts_are_provider_specific_without_provider_authority() -> None:
    telegram = PeriodicDeliveryReceipt("telegram", "42", None)
    local = PeriodicDeliveryReceipt("soak_local", "g2:s7", HASH)
    assert telegram.as_dict()["acknowledgement_sha256"] is None
    assert local.as_dict()["acknowledgement_sha256"] == HASH
    for invalid in (
        ("telegram", "042", None),
        ("telegram", "42", HASH),
        ("soak_local", "g0:s1", HASH),
        ("soak_local", "g9223372036854775808:s1", HASH),
        ("soak_local", "g1:s1", None),
        ("other", "1", None),
    ):
        with pytest.raises(ValueError):
            PeriodicDeliveryReceipt(*invalid)


def test_delivery_result_requires_exact_receipt_and_failure_evidence() -> None:
    receipt = PeriodicDeliveryReceipt("telegram", "42", None)
    accepted = PeriodicDeliveryResult(PeriodicDeliveryOutcome.ACCEPTED, receipt, False, None, None, "")
    assert accepted.receipt is receipt
    retryable = PeriodicDeliveryResult(
        PeriodicDeliveryOutcome.NOT_SENT,
        None,
        True,
        None,
        "telegram_connect_failed",
        "Telegram connection was not established",
    )
    assert retryable.retryable is True
    with pytest.raises(ValueError):
        PeriodicDeliveryResult(
            PeriodicDeliveryOutcome.ACCEPTED,
            None,
            False,
            None,
            None,
            "",
        )
    with pytest.raises(ValueError):
        PeriodicDeliveryResult(
            PeriodicDeliveryOutcome.UNKNOWN,
            None,
            True,
            None,
            "unknown",
            "unknown outcome",
        )


def test_v1_telegram_state_migrates_in_memory_and_mixed_shapes_fail(
    tmp_path: Path,
) -> None:
    payload = copy.deepcopy(load_periodic_state(tmp_path).payload)
    payload["schema"] = 1
    migrated = PeriodicStateDocument(payload)
    assert migrated.payload["schema"] == 2

    # A v1 document may contain only the exact old nested key set.  A v2 key
    # smuggled beside the old provider-specific field is rejected.
    pending = copy.deepcopy(_allocate(tmp_path / "pending")[0].payload)
    active = pending["active"]
    assert isinstance(active, dict)
    active["telegram_message_id"] = active.pop("receipt")
    pending["schema"] = 1
    assert PeriodicStateDocument(pending).payload["active"]["receipt"] is None
    pending["active"]["receipt"] = None
    with pytest.raises(PeriodicContractError, match="v1 active"):
        PeriodicStateDocument(pending)

    succeeded = copy.deepcopy(_variants(tmp_path / "succeeded")["SUCCEEDED"].payload)
    succeeded_active = succeeded["active"]
    assert isinstance(succeeded_active, dict)
    receipt = succeeded_active.pop("receipt")
    succeeded_active["telegram_message_id"] = int(receipt["receipt_id"])
    succeeded["schema"] = 1
    assert PeriodicStateDocument(succeeded).payload["active"]["receipt"] == receipt

    terminal_v1 = copy.deepcopy(_variants(tmp_path / "terminal")["NONE"].payload)
    terminal = terminal_v1["last_terminal"]
    assert isinstance(terminal, dict)
    terminal_receipt = terminal.pop("receipt")
    terminal["telegram_message_id"] = int(terminal_receipt["receipt_id"])
    terminal_v1["schema"] = 1
    assert PeriodicStateDocument(terminal_v1).payload["last_terminal"]["receipt"] == terminal_receipt

    data_dir = tmp_path / "on_disk"
    reporting = data_dir / "reporting"
    reporting.mkdir(parents=True)
    periodic_state_path(data_dir).write_text(json.dumps(succeeded), encoding="utf-8")
    loaded = load_periodic_state(data_dir)
    write_periodic_state(data_dir, rotate_terminal_active(loaded, now=7_206.0))
    written = json.loads(periodic_state_path(data_dir).read_text(encoding="utf-8"))
    assert written["schema"] == 2
    assert "telegram_message_id" not in written["last_terminal"]
    assert written["last_terminal"]["receipt"] == receipt


def test_local_factory_is_mutually_exclusive_with_telegram_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    constructed = 0

    def forbidden(_config):
        nonlocal constructed
        constructed += 1
        raise AssertionError("Telegram must not be constructed for local delivery")

    class LocalDelivery:
        async def send_artifact(self, _photo, _caption, _context):
            raise AssertionError("construction test only")

        async def close(self) -> None:
            return None

    local = LocalDelivery()
    factory_calls: list[tuple[object, ...]] = []

    def local_factory(*args: object):
        factory_calls.append(args)
        return local

    monkeypatch.setattr(periodic_runtime, "PeriodicTelegramClient", forbidden)
    destination = periodic_local_destination_fingerprint("d" * 64)
    factory = make_periodic_coordinator_factory(
        data_dir=tmp_path,
        archive_dir=tmp_path / "archive",
        _delivery_factory=local_factory,
        _destination_fingerprint=destination,
        _delivery_kind="soak_local",
    )
    coordinator = factory(_config())
    assert coordinator._delivery._target is local
    assert coordinator._destination_fingerprint == destination
    assert coordinator._expected_delivery_kind == "soak_local"
    assert constructed == 0
    assert factory_calls == [()]

    with pytest.raises(ValueError, match="mutually required"):
        make_periodic_coordinator_factory(
            data_dir=tmp_path,
            archive_dir=tmp_path / "archive",
            _delivery_factory=lambda: local,
        )


@pytest.mark.parametrize(
    ("fingerprint", "kind", "message"),
    (
        ("bad", "soak_local", "fingerprint"),
        ("sha256:" + "d" * 64, "telegram", "must be soak_local"),
    ),
)
def test_invalid_local_destination_authority_never_invokes_factory(
    tmp_path: Path,
    fingerprint: str,
    kind: str,
    message: str,
) -> None:
    calls = 0

    def forbidden_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("invalid destination authority must fail first")

    with pytest.raises(ValueError, match=message):
        make_periodic_coordinator_factory(
            data_dir=tmp_path,
            archive_dir=tmp_path / "archive",
            _delivery_factory=forbidden_factory,
            _destination_fingerprint=fingerprint,
            _delivery_kind=kind,
        )
    assert calls == 0


def test_custom_session_is_acquired_only_after_coordinator_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    calls = 0

    def local_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("session lease must not be acquired")

    def failed_coordinator(**_kwargs):
        raise RuntimeError("late graph construction failed")

    monkeypatch.setattr(periodic_runtime, "PeriodicPngCoordinator", failed_coordinator)
    factory = make_periodic_coordinator_factory(
        data_dir=tmp_path,
        archive_dir=tmp_path / "archive",
        _delivery_factory=local_factory,
        _destination_fingerprint="sha256:" + "d" * 64,
        _delivery_kind="soak_local",
    )
    with pytest.raises(RuntimeError, match="late graph"):
        factory(_config())
    assert calls == 0


def test_custom_factory_returning_none_fails_during_construction_without_state(
    tmp_path: Path,
) -> None:
    calls = 0

    def empty_factory():
        nonlocal calls
        calls += 1
        return None

    factory = make_periodic_coordinator_factory(
        data_dir=tmp_path,
        archive_dir=tmp_path / "archive",
        _delivery_factory=empty_factory,  # type: ignore[arg-type]
        _destination_fingerprint="sha256:" + "d" * 64,
        _delivery_kind="soak_local",
    )
    with pytest.raises(TypeError, match="no session lease"):
        factory(_config())
    assert calls == 1
    assert not (tmp_path / "reporting" / "periodic_state.json").exists()


@pytest.mark.asyncio
async def test_bound_custom_session_closes_when_later_start_construction_fails(
    tmp_path: Path,
) -> None:
    class LocalDelivery:
        def __init__(self) -> None:
            self.closed = 0

        async def send_artifact(self, _photo, _caption, _context):
            raise AssertionError("start failure must precede delivery")

        async def close(self) -> None:
            self.closed += 1

    class FailedLive:
        async def start(self, _on_reading, _on_event) -> None:
            raise RuntimeError("live graph start failed")

        async def stop(self) -> None:
            return None

    local = LocalDelivery()
    factory = make_periodic_coordinator_factory(
        data_dir=tmp_path,
        archive_dir=tmp_path / "archive",
        _delivery_factory=lambda: local,
        _destination_fingerprint="sha256:" + "d" * 64,
        _delivery_kind="soak_local",
    )
    coordinator = factory(_config())
    coordinator._live = FailedLive()
    with pytest.raises(RuntimeError, match="live graph start"):
        await coordinator.start()
    assert local.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telegram_result", "outcome", "retryable"),
    (
        (
            TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 42, 200, None, None, ""),
            PeriodicDeliveryOutcome.ACCEPTED,
            False,
        ),
        (
            TelegramDeliveryResult(
                TelegramOutcome.REJECTED,
                None,
                500,
                None,
                "telegram_retryable_rejection",
                "Telegram rejected the report temporarily",
            ),
            PeriodicDeliveryOutcome.REJECTED,
            True,
        ),
        (
            TelegramDeliveryResult(
                TelegramOutcome.NOT_SENT,
                None,
                None,
                None,
                "telegram_connect_failed",
                "Telegram connection was not established",
            ),
            PeriodicDeliveryOutcome.NOT_SENT,
            True,
        ),
        (
            TelegramDeliveryResult(
                TelegramOutcome.UNKNOWN,
                None,
                None,
                None,
                "telegram_transport_unknown",
                "Telegram delivery outcome is unknown",
            ),
            PeriodicDeliveryOutcome.UNKNOWN,
            False,
        ),
    ),
)
async def test_telegram_adapter_preserves_delivery_classification(
    monkeypatch: pytest.MonkeyPatch,
    telegram_result: TelegramDeliveryResult,
    outcome: PeriodicDeliveryOutcome,
    retryable: bool,
) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    class Client:
        def __init__(self, _config) -> None:
            self.calls = 0
            self.closed = 0

        async def send_photo(self, photo: bytes, caption: str):
            self.calls += 1
            assert photo == b"x" * 33
            assert caption == "caption"
            return telegram_result

        async def close(self) -> None:
            self.closed += 1

    monkeypatch.setattr(periodic_runtime, "PeriodicTelegramClient", Client)
    adapter = periodic_runtime._TelegramPeriodicDelivery(_config())
    result = await adapter.send_artifact(b"x" * 33, "caption", _context())
    # The context hash deliberately disagrees, so no provider invocation is
    # allowed.  Rebuild the exact context and prove the classification next.
    assert result.error_code == "delivery_context_mismatch"
    assert adapter._client.calls == 0

    caption_mismatch = PeriodicDeliveryContext(
        HASH,
        TOKEN,
        "c" * 32,
        "sha256:" + hashlib.sha256(b"x" * 33).hexdigest(),
        33,
        "sha256:" + hashlib.sha256(b"different").hexdigest(),
        len(b"different"),
    )
    result = await adapter.send_artifact(b"x" * 33, "caption", caption_mismatch)
    assert result.error_code == "delivery_context_mismatch"
    assert adapter._client.calls == 0

    context = PeriodicDeliveryContext(
        HASH,
        TOKEN,
        "c" * 32,
        "sha256:" + hashlib.sha256(b"x" * 33).hexdigest(),
        33,
        CAPTION_HASH,
        7,
    )
    result = await adapter.send_artifact(b"x" * 33, "caption", context)
    assert result.outcome is outcome
    assert result.retryable is retryable
    assert adapter._client.calls == 1
    if outcome is PeriodicDeliveryOutcome.ACCEPTED:
        assert result.receipt == PeriodicDeliveryReceipt("telegram", "42", None)
    else:
        assert result.receipt is None
        assert result.error_code == telegram_result.error_code
        assert result.error_text == telegram_result.error_text
    await adapter.close()
    await adapter.close()
    assert adapter._client.closed == 1
