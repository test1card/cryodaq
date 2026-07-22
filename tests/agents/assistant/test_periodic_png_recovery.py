from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_png import (
    PeriodicContractError,
    PeriodicPngCoordinator,
)
from cryodaq.agents.assistant.periodic_telegram import (
    TelegramDeliveryResult,
    TelegramOutcome,
)
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.periodic_state import (
    MAX_UNRESOLVED_DELIVERIES,
    PERIODIC_RENDER_LOCK,
    PeriodicArtifact,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_delivering,
    mark_delivery_unknown,
    mark_ready,
    mark_rendering,
    mark_retryable_failure,
    mark_terminal_failure,
    rotate_terminal_active,
    write_periodic_state,
)
from cryodaq.report_process import ReportProcessError, write_periodic_input_file
from tests.agents.assistant.test_periodic_png_coordinator import (
    DESTINATION_FINGERPRINT,
    Alarm,
    Archive,
    Clock,
    Live,
    Runner,
    SuccessfulRunner,
    Telegram,
    _config,
)


async def _load_stable(data_dir: Path):
    """Retry only the expected inode-fence race during atomic state replacement."""

    last_error: PeriodicContractError | None = None
    for _ in range(100):
        try:
            return load_periodic_state(data_dir)
        except PeriodicContractError as exc:
            last_error = exc
            await asyncio.sleep(0)
    assert last_error is not None
    raise last_error


def _persist_ready(data_dir: Path, config=None) -> None:
    config = config or _config()
    state = load_periodic_state(data_dir)
    pending = allocate_pending(
        state,
        latest_completed_slot(121.0, 60),
        config,
        generation_id="1" * 32,
        owner_token="2" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(data_dir, pending)
    rendering = mark_rendering(
        pending,
        slot_id=str(pending.payload["active"]["slot_id"]),
        owner_token="2" * 32,
        now=122.0,
    )
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=str(pending.payload["active"]["slot_id"]),
        expected_owner_token="2" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    ready = mark_ready(
        rendering,
        PeriodicArtifact(
            "periodic/generations/" + "1" * 32 + "/periodic.png",
            "sha256:" + "3" * 64,
            100,
            100,
            100,
            "image/png",
        ),
        "caption",
        slot_id=str(pending.payload["active"]["slot_id"]),
        owner_token="2" * 32,
        now=123.0,
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=str(pending.payload["active"]["slot_id"]),
        expected_owner_token="2" * 32,
        expected_status=PeriodicStatus.RENDERING,
    )


def _persist_delivering(data_dir: Path, config=None) -> None:
    _persist_ready(data_dir, config)
    ready = load_periodic_state(data_dir)
    active = ready.payload["active"]
    delivering = mark_delivering(
        ready,
        slot_id=str(active["slot_id"]),
        owner_token="2" * 32,
        now=124.0,
    )
    write_periodic_state(
        data_dir,
        delivering,
        expected_slot_id=str(active["slot_id"]),
        expected_owner_token="2" * 32,
        expected_status=PeriodicStatus.READY,
    )


@pytest.mark.asyncio
async def test_recovered_delivering_becomes_unknown_without_sender_call(tmp_path: Path) -> None:
    _persist_delivering(tmp_path)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("stale DELIVERING must not send")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(130.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        state = load_periodic_state(tmp_path)
        assert state.payload["active"]["status"] == "DELIVERY_UNKNOWN"
        assert len(state.payload["unresolved_delivery"]) == 1
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_artifact_reader_runs_before_delivering_and_failure_sends_nothing(tmp_path: Path) -> None:
    _persist_ready(tmp_path)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("artifact failure must not send")

    telegram.send_photo = forbidden

    def failed_reader(data_dir: Path, _artifact: PeriodicArtifact) -> bytes:
        assert load_periodic_state(data_dir).payload["active"]["status"] == "READY"
        raise OSError("hostile replacement")

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=failed_reader,
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        state = load_periodic_state(tmp_path).payload
        terminal = state["last_terminal"] or state["active"]
        assert terminal["failure_phase"] == "scheduler"
        assert terminal["error_code"] == "periodic_artifact_unavailable"
        assert telegram.calls == 0
        assert terminal.get("delivery_attempt_count", 0) == 0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_non_bytes_artifact_reader_terminalizes_ready_without_send(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("non-bytes artifact must not send")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: bytearray(b"mutable"),
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["last_terminal"] is not None:
                break
            await asyncio.sleep(0.001)
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal["status"] == "FAILED"
        assert terminal["failure_phase"] == "scheduler"
        assert terminal["error_code"] == "periodic_artifact_unavailable"
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


def _persist_due_delivery_failure(data_dir: Path) -> None:
    _persist_ready(data_dir)
    ready = load_periodic_state(data_dir)
    active = ready.payload["active"]
    delivering = mark_delivering(
        ready,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=124.0,
    )
    write_periodic_state(
        data_dir,
        delivering,
        expected_slot_id=active["slot_id"],
        expected_owner_token=active["owner_token"],
        expected_status=PeriodicStatus.READY,
    )
    failed = mark_retryable_failure(
        delivering,
        phase="delivery",
        certainty="not_sent",
        code="telegram_connect_failed",
        text="Telegram connection was not established",
        not_before=124.0,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=124.0,
    )
    write_periodic_state(
        data_dir,
        failed,
        expected_slot_id=active["slot_id"],
        expected_owner_token=active["owner_token"],
        expected_status=PeriodicStatus.DELIVERING,
    )


@pytest.mark.asyncio
async def test_due_delivery_failure_artifact_loss_preserves_phase_and_settles(
    tmp_path: Path,
) -> None:
    _persist_due_delivery_failure(tmp_path)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("unavailable retry artifact must not send")

    telegram.send_photo = forbidden

    def missing_artifact(_data_dir: Path, _artifact: PeriodicArtifact) -> bytes:
        raise OSError("artifact disappeared")

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=missing_artifact,
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["last_terminal"] is not None:
                break
            await asyncio.sleep(0.001)
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal["status"] == "FAILED"
        assert terminal["failure_phase"] == "delivery"
        assert terminal["certainty"] == "not_sent"
        assert terminal["error_code"] == "periodic_artifact_unavailable"
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_config_change_terminalizes_retryable_failed_without_rewriting_phase(
    tmp_path: Path,
) -> None:
    config = _config()
    state = load_periodic_state(tmp_path)
    slot = latest_completed_slot(121.0, 60)
    pending = allocate_pending(
        state,
        slot,
        config,
        generation_id="6" * 32,
        owner_token="7" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(tmp_path, pending)
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token="7" * 32, now=122.0)
    write_periodic_state(
        tmp_path,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token="7" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    failed = mark_retryable_failure(
        rendering,
        phase="render",
        certainty="not_applicable",
        code="render_failed",
        text="failed",
        not_before=200.0,
        slot_id=slot.slot_id,
        owner_token="7" * 32,
        now=123.0,
    )
    write_periodic_state(
        tmp_path,
        failed,
        expected_slot_id=slot.slot_id,
        expected_owner_token="7" * 32,
        expected_status=PeriodicStatus.RENDERING,
    )
    changed = replace(config, config_fingerprint="sha256:" + "e" * 64)
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=changed,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(130.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            state = (await _load_stable(tmp_path)).payload
            if state["last_terminal"] is not None:
                break
            await asyncio.sleep(0.001)
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal["failure_phase"] == "render"
        assert terminal["certainty"] == "not_applicable"
        assert terminal["error_code"] == "periodic_config_changed"
    finally:
        await coordinator.stop()


def _persist_pre_delivery_status(data_dir: Path, config, status: PeriodicStatus) -> None:
    state = load_periodic_state(data_dir)
    slot = latest_completed_slot(121.0, 60)
    pending = allocate_pending(
        state,
        slot,
        config,
        generation_id="a" * 32,
        owner_token="b" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(data_dir, pending)
    if status is PeriodicStatus.PENDING:
        return
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token="b" * 32, now=122.0)
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token="b" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    if status is PeriodicStatus.RENDERING:
        return
    ready = mark_ready(
        rendering,
        PeriodicArtifact(
            "periodic/generations/" + "a" * 32 + "/periodic.png",
            "sha256:" + "c" * 64,
            100,
            100,
            100,
            "image/png",
        ),
        "caption",
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=123.0,
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=slot.slot_id,
        expected_owner_token="b" * 32,
        expected_status=PeriodicStatus.RENDERING,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", (PeriodicStatus.PENDING, PeriodicStatus.RENDERING, PeriodicStatus.READY))
async def test_config_change_terminalizes_each_pre_delivery_status(tmp_path: Path, status: PeriodicStatus) -> None:
    original = _config()
    _persist_pre_delivery_status(tmp_path, original, status)
    changed = replace(original, config_fingerprint="sha256:" + "e" * 64)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("config change must not deliver old evidence")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=changed,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        # Deterministic barrier: racing the background _run_loop left
        # last_terminal unset within the poll window on the Windows runner.
        await coordinator.reconcile_once()
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal is not None
        assert terminal["status"] == "FAILED"
        assert terminal["failure_phase"] == "config"
        assert terminal["certainty"] == "not_applicable"
        assert terminal["error_code"] == "periodic_config_changed"
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_config_change_during_delivering_preserves_unknown_no_resend(
    tmp_path: Path,
) -> None:
    original = _config()
    _persist_delivering(tmp_path, original)
    changed = replace(original, config_fingerprint="sha256:" + "e" * 64)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("recovered DELIVERING must never be resent")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=changed,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(130.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            active = (await _load_stable(tmp_path)).payload["active"]
            if active["status"] == "DELIVERY_UNKNOWN":
                break
            await asyncio.sleep(0.001)
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active["status"] == "DELIVERY_UNKNOWN"
        assert active["error_code"] == "coordinator_recovered_delivering"
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


_DELIVERY_CASES = (
    (
        TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 9, 200, None, None, ""),
        "SUCCEEDED",
        False,
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
        "DELIVERY_UNKNOWN",
        False,
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
        "FAILED",
        True,
    ),
    (
        TelegramDeliveryResult(
            TelegramOutcome.NOT_SENT,
            None,
            None,
            None,
            "invalid_photo",
            "periodic PNG is invalid",
        ),
        "FAILED",
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
        "FAILED",
        True,
    ),
    (
        TelegramDeliveryResult(
            TelegramOutcome.REJECTED,
            None,
            400,
            None,
            "telegram_permanent_rejection",
            "Telegram rejected the report",
        ),
        "FAILED",
        False,
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("result", "expected_status", "retryable"), _DELIVERY_CASES)
async def test_sender_four_outcomes_map_to_exact_durable_state(
    tmp_path: Path,
    result: TelegramDeliveryResult,
    expected_status: str,
    retryable: bool,
) -> None:
    _persist_ready(tmp_path)

    class ResultTelegram(Telegram):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def send_photo(self, _photo: bytes, _caption: str):
            self.calls += 1
            return result

    telegram = ResultTelegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            active = payload["active"]
            terminal = payload["last_terminal"]
            if terminal is not None or (isinstance(active, dict) and active["status"] == "FAILED"):
                break
            await asyncio.sleep(0.001)
        payload = (await _load_stable(tmp_path)).payload
        observed = payload["last_terminal"] or payload["active"]
        assert observed["status"] == expected_status
        if expected_status == "FAILED":
            if retryable:
                assert observed["retryable"] is True
                assert payload["active"] is observed
            elif payload["active"] is observed:
                assert observed["retryable"] is False
            else:
                assert observed["finished_at"] is not None
        assert telegram.calls == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_delivery_attempt_exhaustion_is_terminal(tmp_path: Path) -> None:
    config = replace(_config(), max_delivery_attempts=1)
    _persist_ready(tmp_path, config)

    class Rejected(Telegram):
        async def send_photo(self, _photo: bytes, _caption: str):
            return TelegramDeliveryResult(
                TelegramOutcome.REJECTED,
                None,
                500,
                None,
                "telegram_retryable_rejection",
                "Telegram rejected the report temporarily",
            )

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=config,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Rejected(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["last_terminal"] is not None:
                break
            await asyncio.sleep(0.001)
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal["status"] == "FAILED"
        assert terminal["certainty"] == "rejected"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_sender_exception_after_invocation_becomes_delivery_unknown(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)

    class ExplodingTelegram(Telegram):
        async def send_photo(self, _photo: bytes, _caption: str):
            raise RuntimeError("socket vanished after request bytes")

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=ExplodingTelegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            observed = payload["last_terminal"] or payload["active"]
            if observed is not None and observed["status"] == "DELIVERY_UNKNOWN":
                break
            await asyncio.sleep(0.001)
        payload = (await _load_stable(tmp_path)).payload
        observed = payload["last_terminal"] or payload["active"]
        assert observed["status"] == "DELIVERY_UNKNOWN"
        assert observed["error_code"] == "delivery_internal_unknown"
        assert observed["certainty"] == "unknown"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_malformed_provider_result_after_invocation_becomes_delivery_unknown(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)

    class MalformedDelivery(Telegram):
        async def send_artifact(self, _photo, _caption, _context):
            return object()

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=MalformedDelivery(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        payload = (await _load_stable(tmp_path)).payload
        observed = payload["last_terminal"] or payload["active"]
        assert observed is not None
        assert observed["status"] == "DELIVERY_UNKNOWN"
        assert observed["error_code"] == "delivery_internal_unknown"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expected_kind", "receipt"),
    (
        (
            "telegram",
            PeriodicDeliveryReceipt("soak_local", "g1:s1", "sha256:" + "a" * 64),
        ),
        ("soak_local", PeriodicDeliveryReceipt("telegram", "42", None)),
    ),
)
async def test_accepted_cross_kind_receipt_is_durable_unknown(
    tmp_path: Path,
    expected_kind: str,
    receipt: PeriodicDeliveryReceipt,
) -> None:
    _persist_ready(tmp_path)

    class CrossKindDelivery(Telegram):
        async def send_artifact(self, _photo, _caption, _context):
            return PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.ACCEPTED,
                receipt,
                False,
                None,
                None,
                "",
            )

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=CrossKindDelivery(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind=expected_kind,
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        payload = (await _load_stable(tmp_path)).payload
        observed = payload["last_terminal"] or payload["active"]
        assert observed is not None
        assert observed["status"] == "DELIVERY_UNKNOWN"
        assert observed["error_code"] == "delivery_receipt_kind_mismatch"
        assert observed["receipt"] is None
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ("result", "receipt"))
async def test_post_construction_delivery_result_corruption_is_unknown(
    tmp_path: Path,
    corrupt: str,
) -> None:
    _persist_ready(tmp_path)

    class CorruptDelivery(Telegram):
        async def send_artifact(self, _photo, _caption, _context):
            receipt = PeriodicDeliveryReceipt("telegram", "42", None)
            result = PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.ACCEPTED,
                receipt,
                False,
                None,
                None,
                "",
            )
            if corrupt == "result":
                object.__setattr__(result, "retryable", True)
            else:
                object.__setattr__(receipt, "acknowledgement_sha256", "sha256:" + "a" * 64)
            return result

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=CorruptDelivery(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            observed = payload["last_terminal"] or payload["active"]
            if observed is not None and observed["status"] == "DELIVERY_UNKNOWN":
                break
            await asyncio.sleep(0.001)
        assert observed["status"] == "DELIVERY_UNKNOWN"
        assert observed["error_code"] == "delivery_internal_unknown"
        assert observed["receipt"] is None
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_retry_after_is_used_as_exact_durable_delivery_deadline(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)

    class RetryAfterTelegram(Telegram):
        async def send_photo(self, _photo: bytes, _caption: str):
            return TelegramDeliveryResult(
                TelegramOutcome.REJECTED,
                None,
                429,
                7.5,
                "telegram_retryable_rejection",
                "Telegram rejected the report temporarily",
            )

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=RetryAfterTelegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            observed = payload["last_terminal"] or payload["active"]
            if observed is not None and observed["status"] == "FAILED":
                break
            await asyncio.sleep(0.001)
        payload = (await _load_stable(tmp_path)).payload
        active = payload["active"]
        assert active is not None, payload
        assert active["status"] == "FAILED"
        assert active["retryable"] is True
        assert active["not_before"] == 131.5
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_blocked_sender_heartbeats_at_30_and_60_with_one_call(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)

    class PulseClock(Clock):
        def __init__(self) -> None:
            super().__init__(124.0)
            self.sleepers: list[asyncio.Event] = []

        async def sleep(self, _seconds: float) -> None:
            event = asyncio.Event()
            self.sleepers.append(event)
            await event.wait()

        def advance(self, seconds: float) -> None:
            self.mono += seconds
            self.wall += seconds
            sleepers, self.sleepers = self.sleepers, []
            for event in sleepers:
                event.set()

    class BlockingTelegram(Telegram):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send_photo(self, _photo: bytes, _caption: str):
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 81, 200, None, None, "")

    clock = PulseClock()
    telegram = BlockingTelegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=clock,
    )
    await coordinator.start()
    try:
        await telegram.entered.wait()
        previous = (await _load_stable(tmp_path)).payload["health"]["updated_at"]
        for tick in (30, 60):
            for _ in range(100):
                if clock.sleepers:
                    break
                await asyncio.sleep(0.001)
            clock.advance(30.0)
            for _ in range(100):
                current = (await _load_stable(tmp_path)).payload["health"]["updated_at"]
                if current > previous:
                    break
                await asyncio.sleep(0.001)
            assert current > previous, tick
            previous = current
            assert telegram.calls == 1
        telegram.release.set()
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["last_terminal"] is not None:
                break
            await asyncio.sleep(0.001)
        assert payload["last_terminal"]["status"] == "SUCCEEDED"
        assert telegram.calls == 1
    finally:
        telegram.release.set()
        await coordinator.stop()


@pytest.mark.asyncio
async def test_send_return_racing_heartbeat_orders_before_success_persist(
    tmp_path: Path,
) -> None:
    _persist_ready(tmp_path)

    class PulseClock(Clock):
        def __init__(self) -> None:
            super().__init__(124.0)
            self.sleepers: list[asyncio.Event] = []

        async def sleep(self, _seconds: float) -> None:
            event = asyncio.Event()
            self.sleepers.append(event)
            await event.wait()

        def advance(self, seconds: float) -> None:
            self.mono += seconds
            self.wall += seconds
            sleepers, self.sleepers = self.sleepers, []
            for event in sleepers:
                event.set()

    class RacingTelegram(Telegram):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send_photo(self, _photo: bytes, _caption: str):
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 82, 200, None, None, "")

    clock = PulseClock()
    telegram = RacingTelegram()
    pause_health_load = False
    paused_once = False
    load_entered = asyncio.Event()
    load_release = asyncio.Event()

    async def pausing_blocking(fn, *args, **kwargs):
        nonlocal paused_once
        if pause_health_load and not paused_once and fn.__name__ == "load_periodic_state":
            paused_once = True
            load_entered.set()
            await load_release.wait()
        return await asyncio.to_thread(fn, *args, **kwargs)

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=clock,
        run_blocking=pausing_blocking,
    )
    await coordinator.start()
    try:
        await telegram.entered.wait()
        pause_health_load = True
        for _ in range(100):
            if clock.sleepers:
                break
            await asyncio.sleep(0.001)
        clock.advance(30.0)
        await load_entered.wait()
        telegram.release.set()
        await asyncio.sleep(0)
        load_release.set()
        deadline = asyncio.get_running_loop().time() + 5.0
        while True:
            payload = (await _load_stable(tmp_path)).payload
            if payload["last_terminal"] is not None:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError("periodic recovery did not reach a terminal state before the deadline")
            await asyncio.sleep(min(0.01, remaining))
        assert payload["last_terminal"]["status"] == "SUCCEEDED"
        assert telegram.calls == 1
        assert coordinator._loop_task is not None
        assert not coordinator._loop_task.done()
    finally:
        telegram.release.set()
        load_release.set()
        await coordinator.stop()


def _append_unknown_slot(data_dir: Path, config, end: int, index: int) -> None:
    state = load_periodic_state(data_dir)
    slot = latest_completed_slot(float(end + 1), 60)
    generation = f"{index + 10:032x}"
    owner = f"{index + 100:032x}"
    pending = allocate_pending(
        state,
        slot,
        config,
        generation_id=generation,
        owner_token=owner,
        display_time=datetime.fromtimestamp(end).strftime("%d.%m.%Y %H:%M"),
        now=float(end + 1),
    )
    write_periodic_state(data_dir, pending)
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token=owner, now=float(end + 2))
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.PENDING,
    )
    ready = mark_ready(
        rendering,
        PeriodicArtifact(
            f"periodic/generations/{generation}/periodic.png",
            "sha256:" + f"{index + 1:064x}",
            100,
            100,
            100,
            "image/png",
        ),
        "caption",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(end + 3),
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.RENDERING,
    )
    delivering = mark_delivering(ready, slot_id=slot.slot_id, owner_token=owner, now=float(end + 4))
    write_periodic_state(
        data_dir,
        delivering,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.READY,
    )
    unknown = mark_delivery_unknown(
        delivering,
        code="telegram_transport_unknown",
        text="delivery outcome is unknown",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(end + 5),
    )
    write_periodic_state(
        data_dir,
        unknown,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.DELIVERING,
    )
    rotated = rotate_terminal_active(unknown, now=float(end + 6))
    write_periodic_state(
        data_dir,
        rotated,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.DELIVERY_UNKNOWN,
    )


@pytest.mark.asyncio
async def test_full_unknown_ledger_pauses_ready_and_never_calls_sender(tmp_path: Path) -> None:
    config = _config()
    _append_end = _persist_full_unknown_ledger_ready(tmp_path, config)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("full ledger must pause")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=config,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(float(_append_end + 4)),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["health"]["status"] == "paused_unknown_capacity":
                break
            await asyncio.sleep(0.001)
        payload = (await _load_stable(tmp_path)).payload
        assert payload["health"]["status"] == "paused_unknown_capacity"
        assert payload["active"]["status"] == "READY"
        assert len(payload["unresolved_delivery"]) == MAX_UNRESOLVED_DELIVERIES
        assert telegram.calls == 0
        coordinator._clock.mono = 30.0
        assert coordinator._reconcile_lock is not None
        async with coordinator._reconcile_lock:
            await coordinator._refresh_periodic_authority_if_due()
        assert (await _load_stable(tmp_path)).payload["health"]["status"] == ("paused_unknown_capacity")
    finally:
        await coordinator.stop()


def _persist_full_unknown_ledger_ready(data_dir: Path, config) -> int:
    for index in range(MAX_UNRESOLVED_DELIVERIES):
        _append_unknown_slot(data_dir, config, 120 + index * 60, index)
    _append_end = 120 + MAX_UNRESOLVED_DELIVERIES * 60
    _persist_ready_for_end(data_dir, config, _append_end)
    return _append_end


@pytest.mark.asyncio
async def test_newer_slot_with_full_ledger_persists_pause_without_send(
    tmp_path: Path,
) -> None:
    config = _config()
    active_end = _persist_full_unknown_ledger_ready(tmp_path, config)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError("newer slot cannot bypass full-ledger pause")

    telegram.send_photo = forbidden
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=config,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(float(active_end + config.interval_s + 4)),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            payload = (await _load_stable(tmp_path)).payload
            if payload["health"]["status"] == "paused_unknown_capacity":
                break
            await asyncio.sleep(0.001)
        payload = (await _load_stable(tmp_path)).payload
        assert payload["health"]["status"] == "paused_unknown_capacity"
        assert payload["active"]["status"] == "READY"
        assert payload["active"]["slot_end"] == active_end
        assert len(payload["unresolved_delivery"]) == MAX_UNRESOLVED_DELIVERIES
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


def _persist_ready_for_end(data_dir: Path, config, end: int) -> None:
    state = load_periodic_state(data_dir)
    slot = latest_completed_slot(float(end + 1), 60)
    generation = "f" * 32
    owner = "e" * 32
    pending = allocate_pending(
        state,
        slot,
        config,
        generation_id=generation,
        owner_token=owner,
        display_time=datetime.fromtimestamp(end).strftime("%d.%m.%Y %H:%M"),
        now=float(end + 1),
    )
    write_periodic_state(data_dir, pending)
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token=owner, now=float(end + 2))
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.PENDING,
    )
    ready = mark_ready(
        rendering,
        PeriodicArtifact(
            f"periodic/generations/{generation}/periodic.png",
            "sha256:" + "f" * 64,
            100,
            100,
            100,
            "image/png",
        ),
        "caption",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(end + 3),
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=slot.slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.RENDERING,
    )


@pytest.mark.asyncio
async def test_state_fence_change_during_artifact_read_prevents_send(tmp_path: Path) -> None:
    _persist_ready(tmp_path)
    telegram = Telegram()
    telegram.calls = 0

    async def forbidden(*_args):
        telegram.calls += 1
        raise AssertionError

    telegram.send_photo = forbidden

    def racing_reader(data_dir: Path, _artifact: PeriodicArtifact) -> bytes:
        state = load_periodic_state(data_dir)
        active = state.payload["active"]
        failed = mark_terminal_failure(
            state,
            phase="scheduler",
            certainty="not_applicable",
            code="fence_test",
            text="state changed",
            slot_id=active["slot_id"],
            owner_token=active["owner_token"],
            now=124.0,
        )
        write_periodic_state(
            data_dir,
            failed,
            expected_slot_id=active["slot_id"],
            expected_owner_token=active["owner_token"],
            expected_status=PeriodicStatus.READY,
        )
        return b"authorized"

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=racing_reader,
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        assert telegram.calls == 0
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_cancel_after_delivering_waits_for_result_persistence(tmp_path: Path) -> None:
    class SleepingClock(Clock):
        def __init__(self) -> None:
            super().__init__(1.0)
            self.sleep_entered = asyncio.Event()

        async def sleep(self, _seconds: float) -> None:
            self.sleep_entered.set()
            await asyncio.Event().wait()

    clock = SleepingClock()

    class BlockingTelegram(Telegram):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send_photo(self, _photo: bytes, _caption: str):
            self.entered.set()
            await self.release.wait()
            return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 42, 200, None, None, "")

    telegram = BlockingTelegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=clock,
    )
    await coordinator.start()
    await clock.sleep_entered.wait()
    _persist_ready(tmp_path)
    clock.wall = 124.0
    task = asyncio.create_task(coordinator.reconcile_once())
    await telegram.entered.wait()
    assert (await _load_stable(tmp_path)).payload["active"]["status"] == "DELIVERING"
    task.cancel()
    telegram.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _load_stable(tmp_path)).payload["active"]["status"] == "SUCCEEDED"
    await coordinator.stop()


def _persist_rendering(data_dir: Path) -> None:
    config = _config()
    slot = latest_completed_slot(121.0, 60)
    pending = allocate_pending(
        load_periodic_state(data_dir),
        slot,
        config,
        generation_id="8" * 32,
        owner_token="9" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(data_dir, pending)
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token="9" * 32, now=122.0)
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot.slot_id,
        expected_owner_token="9" * 32,
        expected_status=PeriodicStatus.PENDING,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_site", ("recover", "generate", "post_recover"))
async def test_state_and_fence_render_authority_errors_abort_without_attempt(tmp_path: Path, failure_site: str) -> None:
    if failure_site == "recover":
        _persist_rendering(tmp_path)
    else:
        _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)

    class AuthorityRunner(Runner):
        def recover_periodic(self, *_args, **_kwargs):
            if failure_site in {"recover", "post_recover"}:
                raise ReportProcessError("periodic_fence_mismatch", "durable periodic fence changed")
            return None

        def generate_periodic(self, *_args, **_kwargs):
            if failure_site == "post_recover":
                raise ReportProcessError("render_failed", "periodic renderer failed")
            raise ReportProcessError("periodic_state_unavailable", "periodic state is unavailable")

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=AuthorityRunner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        with pytest.raises(ReportProcessError):
            await coordinator.wait()
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active["status"] == "RENDERING"
        assert active["render_attempt_count"] == 1
        assert active["failure_phase"] is None
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("ordinary_error", (OSError("popen failed"), RuntimeError("boom")))
async def test_ordinary_generate_failure_recovers_then_consumes_fixed_attempt(
    tmp_path: Path, ordinary_error: Exception
) -> None:
    _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)

    class OrdinaryFailureRunner(Runner):
        def generate_periodic(self, *_args, **_kwargs):
            raise ordinary_error

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=OrdinaryFailureRunner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active is not None
        assert active["status"] == "FAILED"
        assert active["retryable"] is True
        assert active["error_code"] == "render_failed"
        assert active["render_attempt_count"] == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_ordinary_generate_failure_adopts_promoted_final_before_retry(
    tmp_path: Path,
) -> None:
    _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)
    promoted = SuccessfulRunner(tmp_path)

    class PromotedFinalRunner(Runner):
        def generate_periodic(self, *_args, **_kwargs):
            raise OSError("child exit observation raced final promotion")

        def recover_periodic(self, generation_id: str, **kwargs):
            return promoted.generate_periodic(generation_id, **kwargs)

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=PromotedFinalRunner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=lambda _data, _artifact: b"authorized",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        await coordinator.reconcile_once()
        terminal = (await _load_stable(tmp_path)).payload["last_terminal"]
        assert terminal is not None
        assert terminal["status"] == "SUCCEEDED"
        assert promoted.statuses == ["RENDERING"]
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_blocked_render_keeps_strict_heartbeat_and_240s_alarm_refresh(
    tmp_path: Path,
) -> None:
    _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)

    class PulseClock(Clock):
        def __init__(self) -> None:
            super().__init__(124.0)
            self.sleepers: list[asyncio.Event] = []

        async def sleep(self, _seconds: float) -> None:
            event = asyncio.Event()
            self.sleepers.append(event)
            await event.wait()

        def advance(self, seconds: float) -> None:
            self.mono += seconds
            self.wall += seconds
            sleepers, self.sleepers = self.sleepers, []
            for event in sleepers:
                event.set()

    class CountingAlarm(Alarm):
        def __init__(self) -> None:
            super().__init__()
            self.snapshots = 0

        async def snapshot(self):
            self.snapshots += 1
            return await super().snapshot()

    class BlockingRunner(Runner):
        pass

    clock = PulseClock()
    alarm = CountingAlarm()
    runner = BlockingRunner()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_seam(fn, *args, **kwargs):
        if fn == runner.generate_periodic:
            entered.set()
            await release.wait()
            raise ReportProcessError("busy", "periodic renderer lock is already held")
        return await asyncio.to_thread(fn, *args, **kwargs)

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=alarm,
        archive_query=Archive(),
        runner=runner,
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=clock,
        run_blocking=blocking_seam,
    )
    await coordinator.start()
    try:
        await entered.wait()
        previous = (await _load_stable(tmp_path)).payload["health"]["updated_at"]
        baseline_snapshots = alarm.snapshots
        assert baseline_snapshots >= 1
        for tick in range(1, 9):
            for _ in range(100):
                if clock.sleepers:
                    break
                await asyncio.sleep(0.001)
            clock.advance(30.0)
            for _ in range(100):
                current = (await _load_stable(tmp_path)).payload["health"]["updated_at"]
                if current > previous:
                    break
                await asyncio.sleep(0.001)
            assert current > previous, tick
            previous = current
        assert alarm.snapshots == baseline_snapshots + 1
        release.set()
        for _ in range(100):
            if not coordinator._loop_task or coordinator._loop_task.done():
                break
            if clock.sleepers:
                break
            await asyncio.sleep(0.001)
    finally:
        release.set()
        await coordinator.stop()


@pytest.mark.asyncio
async def test_closed_input_publication_failure_consumes_known_render_attempt(
    tmp_path: Path,
) -> None:
    _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)

    async def authority_blocking(fn, *args, **kwargs):
        if fn.__name__ == "write_periodic_input_file":
            raise ReportProcessError("unsafe_periodic_input", "periodic input path is unsafe")
        return await asyncio.to_thread(fn, *args, **kwargs)

    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
        run_blocking=authority_blocking,
    )
    await coordinator.start()
    try:
        for _ in range(100):
            active = (await _load_stable(tmp_path)).payload["active"]
            if active["status"] == "FAILED":
                break
            await asyncio.sleep(0.001)
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active["status"] == "FAILED"
        assert active["retryable"] is True
        assert active["render_attempt_count"] == 1
        assert active["failure_phase"] == "render"
        assert active["error_code"] == "periodic_input_unavailable"
    finally:
        await coordinator.stop()


def _install_structurally_valid_mismatched_input(data_dir: Path, mismatch: str) -> None:
    active = load_periodic_state(data_dir).payload["active"]
    payload = {
        "schema": 1,
        "generation_id": active["generation_id"],
        "owner_token": active["owner_token"],
        "slot": {
            "slot_id": active["slot_id"],
            "slot_start": active["slot_start"],
            "slot_end": active["slot_end"],
            "window_start": active["window_start"],
            "window_end": active["window_end"],
            "config_fingerprint": active["config_fingerprint"],
        },
        "render": {
            "display_time": active["display_time"],
            "include_channels": None,
            "max_points_per_channel": 100,
            "max_total_points": 200,
            "max_input_bytes": 65_536,
            "history_complete": True,
            "alarm_state_complete": True,
            "dropped_points": 0,
            "bad_points": 0,
            "source_errors": [],
        },
        "readings": [{"ts": 100.0, "iid": "ls", "ch": "T", "v": 1.0, "u": "K", "st": "ok"}],
        "alarms": [],
    }
    if mismatch == "window":
        payload["slot"]["window_start"] = 1
    elif mismatch == "include":
        payload["render"]["include_channels"] = ["T"]
    elif mismatch == "points":
        payload["render"]["max_total_points"] = 199
    elif mismatch == "bytes":
        payload["render"]["max_input_bytes"] = 131_072
    else:
        raise AssertionError(mismatch)
    write_periodic_input_file(
        data_dir,
        payload,
        expected_max_input_bytes=payload["render"]["max_input_bytes"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ("window", "include", "points", "bytes"))
async def test_existing_input_reuse_requires_every_deterministic_binding(tmp_path: Path, mismatch: str) -> None:
    _persist_pre_delivery_status(tmp_path, _config(), PeriodicStatus.PENDING)
    _install_structurally_valid_mismatched_input(tmp_path, mismatch)
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            active = (await _load_stable(tmp_path)).payload["active"]
            if active["status"] == "FAILED":
                break
            await asyncio.sleep(0.001)
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active["status"] == "FAILED"
        assert active["error_code"] == "periodic_input_unavailable"
        assert active["render_attempt_count"] == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_rendering_without_live_owner_becomes_retryable_orphan_failure(
    tmp_path: Path,
) -> None:
    _persist_rendering(tmp_path)
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    await coordinator.start()
    try:
        for _ in range(100):
            active = (await _load_stable(tmp_path)).payload["active"]
            if active["status"] == "FAILED":
                break
            await asyncio.sleep(0.001)
        active = (await _load_stable(tmp_path)).payload["active"]
        assert active["status"] == "FAILED"
        assert active["retryable"] is True
        assert active["failure_phase"] == "render"
        assert active["error_code"] == "orphaned_rendering"
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_rendering_with_held_lock_waits_without_state_mutation(tmp_path: Path) -> None:
    other = tmp_path / "rendering"
    other.mkdir()
    config = _config()
    _persist_rendering(other)
    fd = try_acquire_lock(PERIODIC_RENDER_LOCK, lock_dir=other)
    assert fd is not None
    coordinator = PeriodicPngCoordinator(
        data_dir=other,
        config=config,
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=Runner(),
        delivery=Telegram(),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    try:
        await coordinator.start()
        await coordinator.reconcile_once()
        assert load_periodic_state(other).payload["active"]["status"] == "RENDERING"
    finally:
        await coordinator.stop()
        release_lock(fd, PERIODIC_RENDER_LOCK, unlink=False, lock_dir=other)


@pytest.mark.asyncio
async def test_corrupt_state_is_preserved_and_start_fails_closed(tmp_path: Path) -> None:
    reporting = tmp_path / "reporting"
    reporting.mkdir()
    path = reporting / "periodic_state.json"
    raw = b'{"schema":1,"broken":true}\n'
    path.write_bytes(raw)
    live = Live()
    alarm = Alarm()
    telegram = Telegram()
    coordinator = PeriodicPngCoordinator(
        data_dir=tmp_path,
        config=_config(),
        live_sources=live,
        alarm_query=alarm,
        archive_query=Archive(),
        runner=Runner(),
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=Clock(124.0),
    )
    with pytest.raises(PeriodicContractError):
        await coordinator.start()
    assert path.read_bytes() == raw
    assert live.stopped == 1
    assert alarm.closed == 1
    assert telegram.closed == 1
