from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

import cryodaq.periodic_state as periodic_state_module
from cryodaq.agents.assistant.periodic_delivery import PeriodicDeliveryReceipt
from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator
from cryodaq.agents.assistant.periodic_telegram import (
    TelegramDeliveryResult,
    TelegramOutcome,
)
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.periodic_state import (
    PERIODIC_RENDER_LOCK,
    PeriodicArtifact,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_delivering,
    mark_ready,
    mark_rendering,
    mark_succeeded,
    periodic_input_path,
    write_periodic_state,
)
from cryodaq.report_process import (
    PeriodicRenderResult,
    ReportProcessRunner,
    read_periodic_artifact_bytes,
    write_periodic_input_file,
)
from cryodaq.reporting.periodic_input import (
    read_periodic_input_file_fenced,
    verify_periodic_file_fence,
)
from tests.agents.assistant.test_periodic_png_coordinator import (
    DESTINATION_FINGERPRINT,
    Alarm,
    Archive,
    Clock,
    Live,
    Telegram,
    _config,
)

_GENERATION = "1" * 32
_OWNER = "2" * 32
_RETRY_GENERATION = "3" * 32
_RETRY_OWNER = "4" * 32
_NOW = 124.0


class SimulatedCrash(RuntimeError):
    """Test-only process-death boundary before one durable replace."""


class SimulatedProcessDeath(BaseException):
    """Uncatchable transport interruption used to model abrupt process loss."""


class CountingRunner:
    def __init__(self, data_dir: Path, *, real_recovery: bool = False) -> None:
        self.data_dir = data_dir
        self.real_recovery = real_recovery
        self.recover_result: PeriodicRenderResult | None = None
        self.recover_calls = 0
        self.generate_calls = 0
        self.generated_inputs: list[dict[str, object]] = []

    def result_from_active(self) -> PeriodicRenderResult:
        active = load_periodic_state(self.data_dir).payload["active"]
        assert isinstance(active, dict)
        generation = str(active["generation_id"])
        return PeriodicRenderResult(
            generation_id=generation,
            owner_token=str(active["owner_token"]),
            slot_id=str(active["slot_id"]),
            config_fingerprint=str(active["config_fingerprint"]),
            artifact=PeriodicArtifact(
                f"periodic/generations/{generation}/periodic.png",
                "sha256:" + "9" * 64,
                100,
                100,
                100,
                "image/png",
            ),
            caption="frozen caption",
        )

    def recover_periodic(self, generation_id: str, **kwargs: object) -> PeriodicRenderResult | None:
        self.recover_calls += 1
        if self.real_recovery:
            return ReportProcessRunner(self.data_dir).recover_periodic(generation_id, **kwargs)
        return self.recover_result

    def generate_periodic(
        self,
        generation_id: str,
        *,
        expected_slot_id: str,
        expected_owner_token: str,
        max_input_bytes: int,
    ) -> PeriodicRenderResult:
        self.generate_calls += 1
        path = periodic_input_path(self.data_dir, generation_id)
        frozen, fence = read_periodic_input_file_fenced(path, expected_max_input_bytes=max_input_bytes)
        raw = path.read_bytes()
        verify_periodic_file_fence(path, fence)
        self.generated_inputs.append(
            {
                "generation_id": frozen.generation_id,
                "owner_token": frozen.owner_token,
                "slot_id": frozen.slot.slot_id,
                "config_fingerprint": frozen.slot.config_fingerprint,
                "max_input_bytes": frozen.render.max_input_bytes,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_size": len(raw),
            }
        )
        assert frozen.generation_id == generation_id
        assert frozen.owner_token == expected_owner_token
        assert frozen.slot.slot_id == expected_slot_id
        assert frozen.render.max_input_bytes == max_input_bytes
        return self.result_from_active()


class CountingTelegram(Telegram):
    def __init__(
        self,
        result: TelegramDeliveryResult | None = None,
        *,
        failure: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.result = result or TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 77, 200, None, None, "")
        self.failure = failure
        self.calls = 0
        self.photos: list[bytes] = []
        self.captions: list[str] = []
        self.chat_id = _config().telegram_chat_id

    async def send_photo(self, photo: bytes, caption: str) -> TelegramDeliveryResult:
        self.calls += 1
        self.photos.append(photo)
        self.captions.append(caption)
        if self.failure is not None:
            raise self.failure
        return self.result


async def _inline(fn: Any, *args: object, **kwargs: object) -> Any:
    return fn(*args, **kwargs)


def _pending(
    data_dir: Path,
    *,
    generation: str = _GENERATION,
    owner: str = _OWNER,
) -> tuple[str, int]:
    config = _config()
    slot = latest_completed_slot(121.0, config.interval_s)
    pending = allocate_pending(
        load_periodic_state(data_dir),
        slot,
        config,
        generation_id=generation,
        owner_token=owner,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    write_periodic_state(data_dir, pending)
    return slot.slot_id, slot.slot_end


def _rendering(data_dir: Path) -> tuple[str, int]:
    slot_id, slot_end = _pending(data_dir)
    pending = load_periodic_state(data_dir)
    rendering = mark_rendering(
        pending,
        slot_id=slot_id,
        owner_token=_OWNER,
        now=122.0,
    )
    write_periodic_state(
        data_dir,
        rendering,
        expected_slot_id=slot_id,
        expected_owner_token=_OWNER,
        expected_status=PeriodicStatus.PENDING,
    )
    return slot_id, slot_end


def _artifact(generation: str = _GENERATION) -> PeriodicArtifact:
    return PeriodicArtifact(
        f"periodic/generations/{generation}/periodic.png",
        "sha256:" + "9" * 64,
        100,
        100,
        100,
        "image/png",
    )


def _ready(
    data_dir: Path,
    *,
    artifact: PeriodicArtifact | None = None,
    caption: str = "frozen caption",
) -> tuple[str, int]:
    slot_id, slot_end = _rendering(data_dir)
    rendering = load_periodic_state(data_dir)
    ready = mark_ready(
        rendering,
        artifact or _artifact(),
        caption,
        slot_id=slot_id,
        owner_token=_OWNER,
        now=123.0,
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=slot_id,
        expected_owner_token=_OWNER,
        expected_status=PeriodicStatus.RENDERING,
    )
    return slot_id, slot_end


def _ready_with_authoritative_png(
    data_dir: Path,
) -> tuple[str, int, PeriodicArtifact, bytes, str]:
    slot_id, slot_end = _rendering(data_dir)
    raw = _png()
    final = data_dir / "reporting" / "periodic" / "generations" / _GENERATION
    final.mkdir(parents=True)
    (final / "periodic.png").write_bytes(raw)
    artifact = PeriodicArtifact(
        f"periodic/generations/{_GENERATION}/periodic.png",
        "sha256:" + hashlib.sha256(raw).hexdigest(),
        len(raw),
        640,
        480,
        "image/png",
    )
    caption = "<b>Frozen READY authority</b>"
    rendering = load_periodic_state(data_dir)
    ready = mark_ready(
        rendering,
        artifact,
        caption,
        slot_id=slot_id,
        owner_token=_OWNER,
        now=123.0,
    )
    write_periodic_state(
        data_dir,
        ready,
        expected_slot_id=slot_id,
        expected_owner_token=_OWNER,
        expected_status=PeriodicStatus.RENDERING,
    )
    return slot_id, slot_end, artifact, raw, caption


def _delivering(data_dir: Path) -> tuple[str, int]:
    slot_id, slot_end = _ready(data_dir)
    ready = load_periodic_state(data_dir)
    delivering = mark_delivering(
        ready,
        slot_id=slot_id,
        owner_token=_OWNER,
        now=_NOW,
    )
    write_periodic_state(
        data_dir,
        delivering,
        expected_slot_id=slot_id,
        expected_owner_token=_OWNER,
        expected_status=PeriodicStatus.READY,
    )
    return slot_id, slot_end


def _succeeded(data_dir: Path) -> tuple[str, int]:
    slot_id, slot_end = _delivering(data_dir)
    delivering = load_periodic_state(data_dir)
    succeeded = mark_succeeded(
        delivering,
        receipt=PeriodicDeliveryReceipt("telegram", "77", None),
        slot_id=slot_id,
        owner_token=_OWNER,
        now=125.0,
    )
    write_periodic_state(
        data_dir,
        succeeded,
        expected_slot_id=slot_id,
        expected_owner_token=_OWNER,
        expected_status=PeriodicStatus.DELIVERING,
    )
    return slot_id, slot_end


def _input_payload(data_dir: Path) -> dict[str, object]:
    active = load_periodic_state(data_dir).payload["active"]
    assert isinstance(active, dict)
    config = _config()
    return {
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
            "max_points_per_channel": config.max_points_per_channel,
            "max_total_points": config.max_total_points,
            "max_input_bytes": config.max_input_bytes,
            "history_complete": True,
            "alarm_state_complete": True,
            "dropped_points": 0,
            "bad_points": 0,
            "source_errors": [],
        },
        "readings": [{"ts": 100.0, "iid": "ls", "ch": "T", "v": 1.0, "u": "K", "st": "ok"}],
        "alarms": [],
    }


def _write_orphan_input(data_dir: Path) -> tuple[Path, bytes]:
    config = _config()
    path = write_periodic_input_file(
        data_dir,
        _input_payload(data_dir),
        expected_max_input_bytes=config.max_input_bytes,
    )
    return path, path.read_bytes()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"crash-recovery")
        + _png_chunk(b"IEND", b"")
    )


def _install_promoted_final(data_dir: Path) -> None:
    active = load_periodic_state(data_dir).payload["active"]
    assert isinstance(active, dict)
    generation = str(active["generation_id"])
    final = data_dir / "reporting" / "periodic" / "generations" / generation
    final.mkdir(parents=True)
    raw = _png()
    (final / "periodic.png").write_bytes(raw)
    result = {
        "schema": 1,
        "ok": True,
        "generation_id": generation,
        "owner_token": active["owner_token"],
        "slot_id": active["slot_id"],
        "config_fingerprint": active["config_fingerprint"],
        "artifact": {
            "path": f"periodic/generations/{generation}/periodic.png",
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "width": 640,
            "height": 480,
            "mime": "image/png",
        },
        "caption": "frozen caption",
        "error_code": None,
        "error_text": "",
    }
    (final / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _coordinator(
    data_dir: Path,
    runner: CountingRunner,
    telegram: CountingTelegram,
    *,
    clock: Clock | None = None,
    artifact_reader: Any | None = None,
) -> PeriodicPngCoordinator:
    return PeriodicPngCoordinator(
        data_dir=data_dir,
        config=_config(),
        live_sources=Live(),
        alarm_query=Alarm(),
        archive_query=Archive(),
        runner=runner,
        delivery=telegram,
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        artifact_reader=(
            artifact_reader if artifact_reader is not None else lambda _data, _artifact: b"authorized-png"
        ),
        clock=clock or Clock(_NOW),
        generation_factory=lambda: _RETRY_GENERATION,
        owner_factory=lambda: _RETRY_OWNER,
        run_blocking=_inline,
    )


async def _run_pass(coordinator: PeriodicPngCoordinator) -> None:
    await coordinator.start()
    await coordinator.reconcile_once()


def _terminal_payload(data_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(load_periodic_state(data_dir).payload)
    observed = payload["last_terminal"] or payload["active"]
    assert isinstance(observed, dict)
    return payload, observed


@pytest.mark.asyncio
async def test_crash_before_pending_commit_is_safe_to_allocate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H3-CRASH-001: pre-replace death leaves no claim and one restart send."""

    config = _config()
    slot = latest_completed_slot(121.0, config.interval_s)
    candidate = allocate_pending(
        load_periodic_state(tmp_path),
        slot,
        config,
        generation_id=_GENERATION,
        owner_token=_OWNER,
        display_time="01.01.1970 00:02",
        now=121.0,
    )
    with monkeypatch.context() as crash:
        crash.setattr(
            periodic_state_module,
            "_atomic_write_state_strict",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(SimulatedCrash("before replace")),
        )
        with pytest.raises(SimulatedCrash):
            write_periodic_state(tmp_path, candidate)
    empty = load_periodic_state(tmp_path).payload
    assert empty["active"] is None and empty["high_water_slot_end"] is None

    runner = CountingRunner(tmp_path)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram)
    try:
        await _run_pass(coordinator)
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["status"] == "SUCCEEDED"
        assert payload["high_water_slot_end"] == slot.slot_end
        assert runner.generate_calls == telegram.calls == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_crash_after_pending_before_input_rebuilds_once(tmp_path: Path) -> None:
    """H3-CRASH-002: durable PENDING rebuilds one input/child without dual-send."""

    slot_id, slot_end = _pending(tmp_path)
    assert not periodic_input_path(tmp_path, _GENERATION).exists()
    runner = CountingRunner(tmp_path)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram)
    try:
        await _run_pass(coordinator)
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["slot_id"] == slot_id
        assert terminal["generation_id"] == _GENERATION
        assert terminal["status"] == "SUCCEEDED"
        assert payload["high_water_slot_end"] == slot_end
        assert runner.generate_calls == telegram.calls == 1
        assert len(runner.generated_inputs) == 1
        request = runner.generated_inputs[0]
        assert request == {
            "generation_id": _GENERATION,
            "owner_token": _OWNER,
            "slot_id": slot_id,
            "config_fingerprint": _config().config_fingerprint,
            "max_input_bytes": _config().max_input_bytes,
            "raw_sha256": request["raw_sha256"],
            "raw_size": request["raw_size"],
        }
        assert isinstance(request["raw_sha256"], str)
        assert len(request["raw_sha256"]) == 64
        assert isinstance(request["raw_size"], int) and request["raw_size"] > 0
        rebuilt = periodic_input_path(tmp_path, _GENERATION).read_bytes()
        assert request["raw_sha256"] == hashlib.sha256(rebuilt).hexdigest()
        assert request["raw_size"] == len(rebuilt)
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_orphan_input_before_rendering_is_validated_or_deleted(tmp_path: Path) -> None:
    """H3-CRASH-003: exact orphan input is reused once and never dual-renders."""

    _slot_id, slot_end = _pending(tmp_path)
    input_path, frozen = _write_orphan_input(tmp_path)
    runner = CountingRunner(tmp_path)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram)
    try:
        await _run_pass(coordinator)
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["generation_id"] == _GENERATION
        assert terminal["status"] == "SUCCEEDED"
        assert payload["high_water_slot_end"] == slot_end
        assert runner.generate_calls == telegram.calls == 1
        assert not input_path.exists() or input_path.read_bytes() == frozen
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_stale_rendering_without_child_retries_known_safe(tmp_path: Path) -> None:
    """H3-CRASH-004: free render lock makes known failure then one new attempt."""

    slot_id, slot_end = _rendering(tmp_path)
    clock = Clock(_NOW)
    runner = CountingRunner(tmp_path)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram, clock=clock)
    try:
        await _run_pass(coordinator)
        failed = load_periodic_state(tmp_path).payload["active"]
        assert failed["status"] == "FAILED"
        assert failed["retryable"] is True
        assert failed["error_code"] == "orphaned_rendering"
        assert failed["slot_id"] == slot_id
        assert runner.generate_calls == telegram.calls == 0

        clock.wall += 2.0
        clock.mono += 2.0
        await coordinator.reconcile_once()
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["slot_id"] == slot_id
        assert terminal["generation_id"] == _RETRY_GENERATION
        assert payload["high_water_slot_end"] == slot_end
        assert runner.generate_calls == telegram.calls == 1
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_artifact", [True, False], ids=["adopt", "retry"])
async def test_crash_during_child_waits_for_lock_then_adopts_or_retries_once(
    tmp_path: Path, valid_artifact: bool
) -> None:
    """H3-CRASH-005: held child lock prevents duplicates; release adopts/retries."""

    slot_id, slot_end = _rendering(tmp_path)
    fd = try_acquire_lock(PERIODIC_RENDER_LOCK, lock_dir=tmp_path)
    assert fd is not None
    clock = Clock(_NOW)
    runner = CountingRunner(tmp_path)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram, clock=clock)
    try:
        await _run_pass(coordinator)
        assert load_periodic_state(tmp_path).payload["active"]["status"] == "RENDERING"
        assert runner.generate_calls == telegram.calls == 0
        release_lock(fd, PERIODIC_RENDER_LOCK, unlink=False, lock_dir=tmp_path)
        fd = None

        if valid_artifact:
            runner.recover_result = runner.result_from_active()
            await coordinator.reconcile_once()
        else:
            await coordinator.reconcile_once()
            failed = load_periodic_state(tmp_path).payload["active"]
            assert failed["status"] == "FAILED" and failed["retryable"] is True
            clock.wall += 2.0
            clock.mono += 2.0
            await coordinator.reconcile_once()
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["status"] == "SUCCEEDED"
        assert terminal["slot_id"] == slot_id
        assert payload["high_water_slot_end"] == slot_end
        assert telegram.calls == 1
        assert runner.generate_calls == (0 if valid_artifact else 1)
    finally:
        if fd is not None:
            release_lock(fd, PERIODIC_RENDER_LOCK, unlink=False, lock_dir=tmp_path)
        await coordinator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_final", [True, False], ids=["promoted", "partial"])
async def test_crash_after_promotion_before_ready_adopts_valid_artifact(tmp_path: Path, valid_final: bool) -> None:
    """H3-CRASH-006: immutable final is adopted; partial staging is retried."""

    _slot_id, slot_end = _rendering(tmp_path)
    if valid_final:
        _install_promoted_final(tmp_path)
    else:
        staging = tmp_path / "reporting" / "periodic" / ".staging" / _GENERATION
        staging.mkdir(parents=True)
        (staging / "periodic.png").write_bytes(b"partial")
    clock = Clock(_NOW)
    runner = CountingRunner(tmp_path, real_recovery=True)
    telegram = CountingTelegram()
    coordinator = _coordinator(tmp_path, runner, telegram, clock=clock)
    try:
        await _run_pass(coordinator)
        if not valid_final:
            failed = load_periodic_state(tmp_path).payload["active"]
            assert failed["status"] == "FAILED"
            assert failed["generation_id"] == _GENERATION
            assert telegram.calls == 0
            clock.wall += 2.0
            clock.mono += 2.0
            await coordinator.reconcile_once()
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["status"] == "SUCCEEDED"
        assert payload["high_water_slot_end"] == slot_end
        assert telegram.calls == 1
        assert runner.generate_calls == (0 if valid_final else 1)
        if not valid_final:
            assert terminal["generation_id"] == _RETRY_GENERATION
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_crash_after_ready_resumes_one_exact_send(tmp_path: Path) -> None:
    """H3-CRASH-007: READY restart sends immutable authority exactly once."""

    slot_id, slot_end, artifact, raw, caption = _ready_with_authoritative_png(tmp_path)
    ready_active = load_periodic_state(tmp_path).payload["active"]
    assert isinstance(ready_active, dict)
    expected_destination = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "schema": "periodic-png-destination/v1",
                    "chat_id": _config().telegram_chat_id,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    assert ready_active["artifact"] == {
        "path": artifact.path,
        "sha256": artifact.sha256,
        "size": artifact.size,
        "width": artifact.width,
        "height": artifact.height,
        "mime": artifact.mime,
    }
    assert ready_active["caption"] == caption
    assert ready_active["destination_fingerprint"] == expected_destination
    telegram = CountingTelegram()
    first = _coordinator(
        tmp_path,
        CountingRunner(tmp_path),
        telegram,
        artifact_reader=read_periodic_artifact_bytes,
    )
    try:
        await _run_pass(first)
    finally:
        await first.stop()
    payload, terminal = _terminal_payload(tmp_path)
    assert terminal["status"] == "SUCCEEDED"
    assert terminal["slot_id"] == slot_id
    assert terminal["artifact_sha256"] == artifact.sha256
    assert terminal["destination_fingerprint"] == expected_destination
    assert payload["high_water_slot_end"] == slot_end
    assert telegram.calls == 1
    assert telegram.photos == [raw]
    assert telegram.captions == [caption]
    assert telegram.chat_id == _config().telegram_chat_id

    second = _coordinator(
        tmp_path,
        CountingRunner(tmp_path),
        telegram,
        artifact_reader=read_periodic_artifact_bytes,
    )
    try:
        await _run_pass(second)
        assert telegram.calls == 1
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_crash_after_delivering_before_http_is_unknown(tmp_path: Path) -> None:
    """H3-CRASH-008: stale DELIVERING becomes unknown with zero HTTP calls."""

    _slot_id, slot_end = _delivering(tmp_path)
    telegram = CountingTelegram()
    first = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    try:
        await _run_pass(first)
    finally:
        await first.stop()
    payload, terminal = _terminal_payload(tmp_path)
    assert terminal["status"] == "DELIVERY_UNKNOWN"
    assert payload["high_water_slot_end"] == slot_end
    assert len(payload["unresolved_delivery"]) == 1
    assert telegram.calls == 0

    second = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    try:
        await _run_pass(second)
        assert telegram.calls == 0
        assert len(load_periodic_state(tmp_path).payload["unresolved_delivery"]) == 1
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_crash_during_upload_or_response_is_unknown(tmp_path: Path) -> None:
    """H3-CRASH-009: interrupted DELIVERING is recovered fresh, never resent."""

    _slot_id, slot_end = _ready(tmp_path)
    telegram = CountingTelegram(failure=SimulatedProcessDeath("process died during upload/response"))
    interrupted = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    await interrupted.start()
    try:
        with pytest.raises(SimulatedProcessDeath):
            await interrupted.wait()
        assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
        assert telegram.calls == 1
    finally:
        await interrupted.stop()
    assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
    assert telegram.calls == 1

    replacement = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    try:
        await _run_pass(replacement)
    finally:
        await replacement.stop()
    payload, terminal = _terminal_payload(tmp_path)
    assert terminal["status"] == "DELIVERY_UNKNOWN"
    assert payload["high_water_slot_end"] == slot_end
    assert len(payload["unresolved_delivery"]) == 1
    assert telegram.calls == 1


@pytest.mark.asyncio
async def test_crash_after_telegram_accept_before_success_commit_is_unknown(
    tmp_path: Path,
) -> None:
    """H3-CRASH-010: accepted externally but uncommitted becomes unknown once."""

    _ready(tmp_path)
    telegram = CountingTelegram()
    crashed = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    original_persist = crashed._persist

    async def crash_before_success(before: Any, candidate: Any) -> None:
        active = candidate.payload["active"]
        if isinstance(active, dict) and active["status"] == "SUCCEEDED":
            raise SimulatedCrash("after Telegram accept")
        await original_persist(before, candidate)

    crashed._persist = crash_before_success  # type: ignore[method-assign]
    await crashed.start()
    try:
        with pytest.raises(SimulatedCrash):
            await crashed.wait()
        assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
        assert telegram.calls == 1
    finally:
        await crashed.stop()
    assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
    assert telegram.calls == 1

    replacement = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    try:
        await _run_pass(replacement)
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["status"] == "DELIVERY_UNKNOWN"
        assert len(payload["unresolved_delivery"]) == 1
        assert telegram.calls == 1
    finally:
        await replacement.stop()


@pytest.mark.asyncio
async def test_crash_after_succeeded_never_resends(tmp_path: Path) -> None:
    """H3-CRASH-011: durable SUCCEEDED/high-water survives every restart."""

    slot_id, slot_end = _succeeded(tmp_path)
    telegram = CountingTelegram()
    for _restart in range(2):
        coordinator = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
        try:
            await _run_pass(coordinator)
        finally:
            await coordinator.stop()
    payload, terminal = _terminal_payload(tmp_path)
    assert terminal["status"] == "SUCCEEDED"
    assert terminal["slot_id"] == slot_id
    assert terminal["receipt"] == {
        "kind": "telegram",
        "receipt_id": "77",
        "acknowledgement_sha256": None,
    }
    assert payload["high_water_slot_end"] == slot_end
    assert telegram.calls == 0


@pytest.mark.asyncio
async def test_crash_while_persisting_known_rejection_is_conservative_unknown(
    tmp_path: Path,
) -> None:
    """H3-CRASH-012: lost 429 commit reloads DELIVERING as unknown, no retry."""

    _ready(tmp_path)
    rejection = TelegramDeliveryResult(
        TelegramOutcome.REJECTED,
        None,
        429,
        2.0,
        "telegram_retryable_rejection",
        "Telegram rejected the report temporarily",
    )
    telegram = CountingTelegram(rejection)
    crashed = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    original_persist = crashed._persist

    async def crash_before_rejection(before: Any, candidate: Any) -> None:
        previous = before.payload["active"]
        active = candidate.payload["active"]
        if (
            isinstance(previous, dict)
            and previous["status"] == "DELIVERING"
            and isinstance(active, dict)
            and active["status"] == "FAILED"
        ):
            raise SimulatedCrash("while committing known rejection")
        await original_persist(before, candidate)

    crashed._persist = crash_before_rejection  # type: ignore[method-assign]
    await crashed.start()
    try:
        with pytest.raises(SimulatedCrash):
            await crashed.wait()
        assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
        assert telegram.calls == 1
    finally:
        await crashed.stop()
    assert load_periodic_state(tmp_path).payload["active"]["status"] == "DELIVERING"
    assert telegram.calls == 1

    replacement = _coordinator(tmp_path, CountingRunner(tmp_path), telegram)
    try:
        await _run_pass(replacement)
        payload, terminal = _terminal_payload(tmp_path)
        assert terminal["status"] == "DELIVERY_UNKNOWN"
        assert terminal["certainty"] == "unknown"
        assert len(payload["unresolved_delivery"]) == 1
        assert telegram.calls == 1
    finally:
        await replacement.stop()
