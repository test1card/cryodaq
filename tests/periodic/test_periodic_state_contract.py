from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import pytest

import cryodaq.periodic_state as periodic_state_module
from cryodaq.periodic_config import load_periodic_png_config
from cryodaq.periodic_state import (
    PeriodicArtifact,
    PeriodicContractError,
    PeriodicIOError,
    PeriodicStateDocument,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_delivering,
    mark_delivery_unknown,
    mark_ready,
    mark_rendering,
    mark_retryable_failure,
    periodic_generation_dir,
    periodic_input_path,
    periodic_staging_dir,
    periodic_state_path,
    write_periodic_state,
)

TOKEN = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
DISPLAY_TIME = "10.07.2026 04:05"


def _config(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "notifications.yaml").write_text(
        f"telegram:\n  bot_token: {TOKEN!r}\n  chat_id: -100123\nperiodic_report:\n  enabled: true\n",
        encoding="utf-8",
    )
    loaded = load_periodic_png_config(config_dir)
    assert loaded.config is not None
    return loaded.config


def _pending(tmp_path: Path) -> PeriodicStateDocument:
    config = _config(tmp_path)
    slot = latest_completed_slot(7_201.0, config.interval_s)
    return allocate_pending(
        load_periodic_state(tmp_path / "data"),
        slot,
        config,
        generation_id="a" * 32,
        owner_token="b" * 32,
        display_time=DISPLAY_TIME,
        now=7_201.0,
    )


def _unknown(tmp_path: Path) -> PeriodicStateDocument:
    state = _pending(tmp_path)
    active = state.payload["active"]
    assert isinstance(active, dict)
    slot_id = active["slot_id"]
    owner = active["owner_token"]
    generation = active["generation_id"]
    state = mark_rendering(state, slot_id=slot_id, owner_token=owner, now=7_202)
    state = mark_ready(
        state,
        PeriodicArtifact(
            path=f"periodic/generations/{generation}/periodic.png",
            sha256="sha256:" + "a" * 64,
            size=1_024,
            width=1_200,
            height=800,
            mime="image/png",
        ),
        "caption",
        slot_id=slot_id,
        owner_token=owner,
        now=7_203,
    )
    state = mark_delivering(state, slot_id=slot_id, owner_token=owner, now=7_204)
    return mark_delivery_unknown(
        state,
        code="ambiguous",
        text="ambiguous result",
        slot_id=slot_id,
        owner_token=owner,
        now=7_205,
    )


def test_empty_state_is_pure_and_not_written(tmp_path: Path) -> None:
    data = tmp_path / "data"
    state = load_periodic_state(data)
    assert state.payload["schema"] == 2
    assert state.payload["high_water_slot_end"] is None
    assert state.payload["active"] is None
    assert not periodic_state_path(data).exists()


def test_periodic_paths_are_derived_from_validated_generation(tmp_path: Path) -> None:
    data = tmp_path / "data"
    generation = "a" * 32
    assert periodic_input_path(data, generation).as_posix().endswith(f"reporting/periodic/inputs/{generation}.json")
    assert periodic_staging_dir(data, generation).as_posix().endswith(f"reporting/periodic/.staging/{generation}")
    assert periodic_generation_dir(data, generation).as_posix().endswith(f"reporting/periodic/generations/{generation}")
    for unsafe in ("../escape", "/absolute", "A" * 32, "a" * 31):
        with pytest.raises(PeriodicContractError):
            periodic_input_path(data, unsafe)


def test_derived_paths_reject_symlinked_periodic_subtree(tmp_path: Path) -> None:
    data = tmp_path / "data"
    reporting = data / "reporting"
    reporting.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (reporting / "periodic").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(PeriodicContractError):
        periodic_input_path(data, "a" * 32)


def test_write_reload_and_exact_fence(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pending = _pending(tmp_path)
    write_periodic_state(data, pending)
    loaded = load_periodic_state(data)
    assert loaded == pending
    active = pending.payload["active"]
    assert isinstance(active, dict)
    write_periodic_state(
        data,
        pending,
        expected_slot_id=active["slot_id"],
        expected_owner_token=active["owner_token"],
        expected_status=PeriodicStatus.PENDING,
    )
    with pytest.raises(PeriodicContractError, match="changed"):
        write_periodic_state(
            data,
            pending,
            expected_slot_id=active["slot_id"],
            expected_owner_token="c" * 32,
            expected_status=PeriodicStatus.PENDING,
        )


def test_incomplete_write_fence_is_rejected(tmp_path: Path) -> None:
    state = _pending(tmp_path)
    with pytest.raises(PeriodicContractError, match="requires"):
        write_periodic_state(tmp_path / "data", state, expected_slot_id="sha256:" + "0" * 64)

    active = state.payload["active"]
    assert isinstance(active, dict)
    with pytest.raises(PeriodicContractError, match="status is invalid"):
        write_periodic_state(
            tmp_path / "typed-data",
            state,
            expected_slot_id=active["slot_id"],
            expected_owner_token=active["owner_token"],
            expected_status="PENDING",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.__setitem__("future", 1),
        lambda p: p.__setitem__("schema", 3),
        lambda p: p.__setitem__("high_water_slot_end", True),
        lambda p: p.__setitem__("unknown_overflow_count", False),
        lambda p: p.__setitem__("updated_at", float("nan")),
        lambda p: p["health"].__setitem__("extra", 1),
        lambda p: p["active"].pop("display_time"),
        lambda p: p["active"].__setitem__("interval_s", True),
        lambda p: p["active"].__setitem__("display_time", "31.02.2026 04:05"),
        lambda p: p["active"].__setitem__("status", "FUTURE"),
        lambda p: p["active"].__setitem__("owner_token", "../escape"),
        lambda p: p["active"].__setitem__("updated_at", float("inf")),
    ],
)
def test_exact_state_schema_rejects_invalid_types_and_keys(tmp_path: Path, mutator) -> None:
    payload = copy.deepcopy(_pending(tmp_path).payload)
    mutator(payload)
    with pytest.raises(PeriodicContractError):
        PeriodicStateDocument(payload)


def test_loader_rejects_duplicate_keys_and_nonfinite_json(tmp_path: Path) -> None:
    data = tmp_path / "data"
    state = _pending(tmp_path)
    write_periodic_state(data, state)
    path = periodic_state_path(data)
    path.write_text('{"schema":1,"schema":1}', encoding="utf-8")
    with pytest.raises(PeriodicContractError):
        load_periodic_state(data)
    path.write_text('{"schema":NaN}', encoding="utf-8")
    with pytest.raises(PeriodicContractError):
        load_periodic_state(data)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema":' + "9" * 5_000 + "}",
        '{"schema":1,"nested":' + "[" * 2_000 + "0" + "]" * 2_000 + "}",
    ],
)
def test_hostile_bounded_state_json_normalizes_parser_failures(tmp_path: Path, raw: str) -> None:
    data = tmp_path / "data"
    reporting = data / "reporting"
    reporting.mkdir(parents=True)
    periodic_state_path(data).write_text(raw, encoding="utf-8")
    with pytest.raises(PeriodicContractError):
        load_periodic_state(data)


def test_programmatic_huge_timestamp_normalizes_float_overflow(tmp_path: Path) -> None:
    payload = copy.deepcopy(_pending(tmp_path).payload)
    huge = 10**5_000
    payload["updated_at"] = huge
    payload["active"]["updated_at"] = huge
    with pytest.raises(PeriodicContractError, match="finite timestamp"):
        PeriodicStateDocument(payload)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "oversized", "future"])
def test_loader_rejects_unsafe_state_file(tmp_path: Path, kind: str) -> None:
    data = tmp_path / "data"
    state = _pending(tmp_path)
    write_periodic_state(data, state)
    path = periodic_state_path(data)
    if kind == "symlink":
        target = path.with_suffix(".target")
        path.replace(target)
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(path, path.with_suffix(".hardlink"))
    elif kind == "oversized":
        path.write_bytes(b" " * (128 * 1024 + 1))
    else:
        future = time.time() + 301
        os.utime(path, (future, future))
    with pytest.raises(PeriodicContractError):
        load_periodic_state(data)


def test_loader_rejects_symlinked_reporting_parent(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (data / "reporting").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(PeriodicContractError):
        load_periodic_state(data)


def test_state_mutation_during_read_is_rejected(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    write_periodic_state(data, _pending(tmp_path))
    path = periodic_state_path(data)
    real_read = periodic_state_module.os.read
    changed = False

    def mutating_read(fd: int, size: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            future = time.time() + 3_600
            os.utime(path, (future, future))
        return real_read(fd, size)

    monkeypatch.setattr(periodic_state_module.os, "read", mutating_read)
    with pytest.raises(PeriodicContractError, match="changed while reading"):
        load_periodic_state(data)


def test_loader_retries_transient_windows_access_denial(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    expected = _pending(tmp_path)
    write_periodic_state(data, expected)
    real_open = periodic_state_module.os.open
    calls = 0

    def transient_denial(path, flags, *args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError(13, "sharing violation")
        return real_open(path, flags, *args)

    monkeypatch.setattr(periodic_state_module, "_STATE_READ_ATTEMPTS", 3)
    monkeypatch.setattr(periodic_state_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(periodic_state_module.os, "open", transient_denial)

    assert load_periodic_state(data) == expected
    assert calls == 2


def test_loader_fails_closed_after_persistent_windows_access_denial(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    write_periodic_state(data, _pending(tmp_path))
    calls = 0

    def persistent_denial(_path, _flags, *_args):
        nonlocal calls
        calls += 1
        raise PermissionError(13, "sharing violation")

    monkeypatch.setattr(periodic_state_module, "_STATE_READ_ATTEMPTS", 3)
    monkeypatch.setattr(periodic_state_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(periodic_state_module.os, "open", persistent_denial)

    with pytest.raises(PeriodicIOError, match="cannot be read safely") as raised:
        load_periodic_state(data)
    assert isinstance(raised.value.__cause__, PermissionError)
    assert calls == 3


def test_encoded_state_bound_is_enforced(tmp_path: Path) -> None:
    payload = copy.deepcopy(_pending(tmp_path).payload)
    payload["health"]["error_text"] = "x" * (128 * 1024)
    with pytest.raises(PeriodicContractError):
        PeriodicStateDocument(payload)


def test_slot_identity_uses_only_utc_epoch_and_interval() -> None:
    first = latest_completed_slot(7_299.9, 1_800)
    restarted = latest_completed_slot(7_201.0, 1_800)
    assert first == restarted
    assert first.slot_start == 5_400
    assert first.slot_end == 7_200
    assert first.slot_id.startswith("sha256:")
    with pytest.raises(PeriodicContractError):
        latest_completed_slot(7_201, True)


def test_high_water_advances_atomically_with_pending(tmp_path: Path) -> None:
    pending = _pending(tmp_path)
    active = pending.payload["active"]
    assert isinstance(active, dict)
    assert pending.payload["high_water_slot_end"] == active["slot_end"]
    config = _config(tmp_path / "second")
    same = latest_completed_slot(active["slot_end"], config.interval_s)
    with pytest.raises(PeriodicContractError, match="advance"):
        allocate_pending(
            PeriodicStateDocument({**pending.payload, "active": None}),
            same,
            config,
            generation_id="c" * 32,
            owner_token="d" * 32,
            display_time=DISPLAY_TIME,
            now=active["updated_at"],
        )


@pytest.mark.parametrize(
    "display_time",
    [
        None,
        True,
        "",
        "10.7.2026 04:05",
        "31.02.2026 04:05",
        "10.07.2026 24:00",
        "１０.07.2026 04:05",
        "10.07.2026 04:05\n",
    ],
)
def test_allocation_rejects_noncanonical_or_invalid_display_time(tmp_path: Path, display_time: object) -> None:
    config = _config(tmp_path)
    slot = latest_completed_slot(7_201.0, config.interval_s)
    with pytest.raises(PeriodicContractError, match="display_time"):
        allocate_pending(
            load_periodic_state(tmp_path / "data"),
            slot,
            config,
            generation_id="a" * 32,
            owner_token="b" * 32,
            display_time=display_time,  # type: ignore[arg-type]
            now=7_201.0,
        )


def test_display_time_round_trips_across_restart_and_render_retry(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    config = _config(tmp_path)
    slot = latest_completed_slot(7_201.0, config.interval_s)
    pending = allocate_pending(
        load_periodic_state(data),
        slot,
        config,
        generation_id="a" * 32,
        owner_token="b" * 32,
        display_time=DISPLAY_TIME,
        now=7_201.0,
    )
    write_periodic_state(data, pending)
    restarted = load_periodic_state(data)
    assert restarted.payload["active"]["display_time"] == DISPLAY_TIME

    failed = mark_retryable_failure(
        restarted,
        phase="render",
        certainty="not_applicable",
        code="render_io",
        text="render I/O failed",
        not_before=7_203.0,
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=7_202.0,
    )
    write_periodic_state(
        data,
        failed,
        expected_slot_id=slot.slot_id,
        expected_owner_token="b" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    restarted = load_periodic_state(data)
    retried = allocate_pending(
        restarted,
        slot,
        config,
        generation_id="c" * 32,
        owner_token="d" * 32,
        display_time=DISPLAY_TIME,
        now=7_203.0,
    )
    write_periodic_state(
        data,
        retried,
        expected_slot_id=slot.slot_id,
        expected_owner_token="b" * 32,
        expected_status=PeriodicStatus.FAILED,
    )
    final = load_periodic_state(data)
    assert final.payload["active"]["display_time"] == DISPLAY_TIME


def test_state_never_contains_secret_token(tmp_path: Path) -> None:
    state = _pending(tmp_path)
    encoded = json.dumps(state.payload)
    assert TOKEN not in encoded
    assert TOKEN not in repr(state)


def test_unknown_evidence_must_exactly_match_active_and_terminal(tmp_path: Path) -> None:
    state = _unknown(tmp_path)
    assert "display_time" not in state.payload["unresolved_delivery"][0]
    for field, value in (
        ("generation_id", "c" * 32),
        ("artifact_sha256", "sha256:" + "d" * 64),
        ("error_code", "different"),
        ("ambiguity_at", 7_204.0),
    ):
        payload = copy.deepcopy(state.payload)
        payload["unresolved_delivery"][0][field] = value
        with pytest.raises(PeriodicContractError, match="does not match"):
            PeriodicStateDocument(payload)

    rotated = periodic_state_module.rotate_terminal_active(state, now=7_206)
    payload = copy.deepcopy(rotated.payload)
    payload["unresolved_delivery"][0]["error_text"] = "different"
    with pytest.raises(PeriodicContractError, match="does not match"):
        PeriodicStateDocument(payload)


def test_writer_rejects_high_water_advance_without_matching_pending(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pending = _pending(tmp_path)
    write_periodic_state(data, pending)
    payload = copy.deepcopy(pending.payload)
    payload["active"] = None
    payload["high_water_slot_end"] = 9_000
    payload["updated_at"] = 7_202.0
    with pytest.raises(PeriodicContractError, match="matching new PENDING"):
        write_periodic_state(data, PeriodicStateDocument(payload))


def test_initial_writer_rejects_fabricated_history(tmp_path: Path) -> None:
    with pytest.raises(PeriodicContractError, match="fabricated history"):
        write_periodic_state(tmp_path / "data", _unknown(tmp_path))


def test_writer_rejects_fabricated_ledger_growth(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pending = _pending(tmp_path)
    write_periodic_state(data, pending)
    older = latest_completed_slot(5_401.0, 1_800)
    payload = copy.deepcopy(pending.payload)
    payload["unresolved_delivery"].append(
        {
            "slot_id": older.slot_id,
            "slot_end": older.slot_end,
            "generation_id": "c" * 32,
            "destination_fingerprint": "sha256:" + "d" * 64,
            "artifact_sha256": "sha256:" + "e" * 64,
            "ambiguity_at": 5_402.0,
            "error_code": "fabricated",
            "error_text": "fabricated evidence",
        }
    )
    with pytest.raises(PeriodicContractError, match="DELIVERING recovery"):
        write_periodic_state(data, PeriodicStateDocument(payload))


def test_file_fsync_failure_is_not_reported_as_durable(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"

    def fail_fsync(_fd: int) -> None:
        raise OSError("simulated file fsync failure")

    monkeypatch.setattr(periodic_state_module.os, "fsync", fail_fsync)
    with pytest.raises(PeriodicIOError, match="could not be persisted"):
        write_periodic_state(data, _pending(tmp_path))
    assert not periodic_state_path(data).exists()


def test_directory_fsync_failure_surfaces_after_valid_replace(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    real_fsync = periodic_state_module.os.fsync
    calls = 0

    def fail_second_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(periodic_state_module.os, "fsync", fail_second_fsync)
    with pytest.raises(PeriodicIOError, match="could not be persisted"):
        write_periodic_state(data, _pending(tmp_path))
    assert calls == 2
    assert load_periodic_state(data).payload["active"] is not None


def test_directory_open_failure_is_not_silenced(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    reporting = data / "reporting"
    real_open = periodic_state_module.os.open

    def fail_directory_open(path, flags, *args, **kwargs):
        if Path(path) == reporting and flags == os.O_RDONLY:
            raise OSError("simulated directory open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(periodic_state_module.os, "open", fail_directory_open)
    with pytest.raises(PeriodicIOError, match="could not be persisted"):
        write_periodic_state(data, _pending(tmp_path))
    assert periodic_state_path(data).exists()


def test_writer_refuses_high_water_rollback(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pending = _pending(tmp_path)
    write_periodic_state(data, pending)
    payload = copy.deepcopy(pending.payload)
    payload["active"] = None
    payload["high_water_slot_end"] = None
    with pytest.raises(PeriodicContractError, match="cannot decrease"):
        write_periodic_state(data, PeriodicStateDocument(payload))


def test_writer_refuses_unresolved_evidence_eviction(tmp_path: Path) -> None:
    data = tmp_path / "data"
    state = _pending(tmp_path)
    active = state.payload["active"]
    assert isinstance(active, dict)
    slot_id = active["slot_id"]
    owner = active["owner_token"]
    generation = active["generation_id"]
    write_periodic_state(data, state)
    state = mark_rendering(state, slot_id=slot_id, owner_token=owner, now=7_202)
    write_periodic_state(
        data,
        state,
        expected_slot_id=slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.PENDING,
    )
    state = mark_ready(
        state,
        PeriodicArtifact(
            path=f"periodic/generations/{generation}/periodic.png",
            sha256="sha256:" + "a" * 64,
            size=1024,
            width=1200,
            height=800,
            mime="image/png",
        ),
        "caption",
        slot_id=slot_id,
        owner_token=owner,
        now=7_203,
    )
    write_periodic_state(
        data,
        state,
        expected_slot_id=slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.RENDERING,
    )
    state = mark_delivering(state, slot_id=slot_id, owner_token=owner, now=7_204)
    write_periodic_state(
        data,
        state,
        expected_slot_id=slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.READY,
    )
    state = mark_delivery_unknown(
        state,
        code="ambiguous",
        text="ambiguous result",
        slot_id=slot_id,
        owner_token=owner,
        now=7_205,
    )
    write_periodic_state(
        data,
        state,
        expected_slot_id=slot_id,
        expected_owner_token=owner,
        expected_status=PeriodicStatus.DELIVERING,
    )
    payload = copy.deepcopy(state.payload)
    payload["unresolved_delivery"] = []
    payload["active"] = None
    with pytest.raises(PeriodicContractError, match="immutable"):
        write_periodic_state(data, PeriodicStateDocument(payload))
