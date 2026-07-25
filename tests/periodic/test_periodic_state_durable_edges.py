from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_delivery import PeriodicDeliveryReceipt
from cryodaq.periodic_config import load_periodic_png_config
from cryodaq.periodic_state import (
    PeriodicArtifact,
    PeriodicContractError,
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
    mark_succeeded,
    mark_terminal_failure,
    periodic_state_path,
    rotate_terminal_active,
    set_periodic_health,
    supersede_active,
    write_periodic_state,
)

DISPLAY_TIME = "10.07.2026 04:05"


def _config(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "notifications.yaml").write_text(
        "telegram:\n"
        "  bot_token: '123456:abcdefghijklmnopqrstuvwxyzABCDE'\n"
        "  chat_id: -100123\n"
        "periodic_report:\n"
        "  enabled: true\n",
        encoding="utf-8",
    )
    loaded = load_periodic_png_config(config_dir)
    assert loaded.config is not None
    return loaded.config


def _variants(tmp_path: Path) -> dict[str, PeriodicStateDocument]:
    config = _config(tmp_path)
    empty = load_periodic_state(tmp_path / "absent")
    slot = latest_completed_slot(7_201.0, config.interval_s)
    pending = allocate_pending(
        empty,
        slot,
        config,
        generation_id="a" * 32,
        owner_token="b" * 32,
        display_time=DISPLAY_TIME,
        now=7_201.0,
    )
    rendering = mark_rendering(pending, slot_id=slot.slot_id, owner_token="b" * 32, now=7_202.0)
    ready = mark_ready(
        rendering,
        PeriodicArtifact(
            path=f"periodic/generations/{'a' * 32}/periodic.png",
            sha256="sha256:" + "a" * 64,
            size=1_024,
            width=1_200,
            height=800,
            mime="image/png",
        ),
        "caption",
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=7_203.0,
    )
    delivering = mark_delivering(ready, slot_id=slot.slot_id, owner_token="b" * 32, now=7_204.0)
    succeeded = mark_succeeded(
        delivering,
        receipt=PeriodicDeliveryReceipt("telegram", "42", None),
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=7_205.0,
    )
    unknown = mark_delivery_unknown(
        delivering,
        code="ambiguous",
        text="delivery outcome is ambiguous",
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=7_205.0,
    )
    failed = mark_retryable_failure(
        rendering,
        phase="render",
        certainty="not_applicable",
        code="render_failed",
        text="render failed",
        not_before=7_210.0,
        slot_id=slot.slot_id,
        owner_token="b" * 32,
        now=7_203.0,
    )
    none = rotate_terminal_active(succeeded, now=7_206.0)
    return {
        "NONE": none,
        "PENDING": pending,
        "RENDERING": rendering,
        "READY": ready,
        "DELIVERING": delivering,
        "SUCCEEDED": succeeded,
        "FAILED": failed,
        "DELIVERY_UNKNOWN": unknown,
    }


def _install(data_dir: Path, state: PeriodicStateDocument) -> None:
    reporting = data_dir / "reporting"
    reporting.mkdir(parents=True, exist_ok=True)
    periodic_state_path(data_dir).write_text(
        json.dumps(
            state.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _with_full_ledger(state: PeriodicStateDocument) -> PeriodicStateDocument:
    payload = copy.deepcopy(state.payload)
    payload["unresolved_delivery"] = []
    for index in range(1, 17):
        slot = latest_completed_slot(float(index), 1)
        payload["unresolved_delivery"].append(
            {
                "slot_id": slot.slot_id,
                "slot_end": slot.slot_end,
                "generation_id": f"{index:032x}",
                "destination_fingerprint": "sha256:" + f"{index:064x}",
                "artifact_sha256": "sha256:" + f"{index + 100:064x}",
                "ambiguity_at": float(index),
                "error_code": "historical_unknown",
                "error_text": "historical ambiguity evidence",
            }
        )
    return PeriodicStateDocument(payload)


def _write_edge(data_dir: Path, current: PeriodicStateDocument, candidate: PeriodicStateDocument) -> None:
    _install(data_dir, current)
    active = current.payload["active"]
    if isinstance(active, dict):
        write_periodic_state(
            data_dir,
            candidate,
            expected_slot_id=active["slot_id"],
            expected_owner_token=active["owner_token"],
            expected_status=PeriodicStatus(active["status"]),
        )
    else:
        write_periodic_state(data_dir, candidate)


_ALLOWED_STATUS_EDGES = {
    ("NONE", "NONE"),
    ("NONE", "PENDING"),
    ("PENDING", "PENDING"),
    ("PENDING", "RENDERING"),
    ("PENDING", "FAILED"),
    ("RENDERING", "RENDERING"),
    ("RENDERING", "READY"),
    ("RENDERING", "FAILED"),
    ("READY", "READY"),
    ("READY", "DELIVERING"),
    ("READY", "FAILED"),
    ("DELIVERING", "DELIVERING"),
    ("DELIVERING", "SUCCEEDED"),
    ("DELIVERING", "FAILED"),
    ("DELIVERING", "DELIVERY_UNKNOWN"),
    ("SUCCEEDED", "SUCCEEDED"),
    ("SUCCEEDED", "NONE"),
    ("FAILED", "FAILED"),
    ("FAILED", "PENDING"),
    ("FAILED", "READY"),
    ("FAILED", "DELIVERING"),
    ("FAILED", "NONE"),
    ("DELIVERY_UNKNOWN", "DELIVERY_UNKNOWN"),
    ("DELIVERY_UNKNOWN", "NONE"),
}


@pytest.mark.parametrize(
    ("old_status", "new_status"),
    [
        (old, new)
        for old in (
            "NONE",
            "PENDING",
            "RENDERING",
            "READY",
            "DELIVERING",
            "SUCCEEDED",
            "FAILED",
            "DELIVERY_UNKNOWN",
        )
        for new in (
            "NONE",
            "PENDING",
            "RENDERING",
            "READY",
            "DELIVERING",
            "SUCCEEDED",
            "FAILED",
            "DELIVERY_UNKNOWN",
        )
        if (old, new) not in _ALLOWED_STATUS_EDGES
    ],
)
def test_closed_durable_status_matrix_rejects_every_unlisted_edge(
    tmp_path: Path, old_status: str, new_status: str
) -> None:
    variants = _variants(tmp_path)
    with pytest.raises(PeriodicContractError):
        _write_edge(tmp_path / "data", variants[old_status], variants[new_status])


def test_forbidden_shortcuts_are_rejected_under_an_exact_current_fence(
    tmp_path: Path,
) -> None:
    variants = _variants(tmp_path)
    for old_status, new_status in (
        ("DELIVERING", "READY"),
        ("PENDING", "READY"),
        ("READY", "SUCCEEDED"),
    ):
        with pytest.raises(PeriodicContractError):
            _write_edge(
                tmp_path / f"{old_status}-{new_status}",
                variants[old_status],
                variants[new_status],
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_token", "c" * 32),
        ("config_fingerprint", "sha256:" + "c" * 64),
        ("destination_fingerprint", "sha256:" + "d" * 64),
        ("max_delivery_attempts", 6),
        ("caption", "rebound caption"),
    ],
)
def test_same_status_authority_rebinding_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    ready = _variants(tmp_path)["READY"]
    payload = copy.deepcopy(ready.payload)
    payload["active"][field] = value
    candidate = PeriodicStateDocument(payload)
    with pytest.raises(PeriodicContractError):
        _write_edge(tmp_path / "data", ready, candidate)


def test_unknown_evidence_is_bound_to_old_delivering_intent(tmp_path: Path) -> None:
    variants = _variants(tmp_path)
    delivering = variants["DELIVERING"]
    payload = copy.deepcopy(variants["DELIVERY_UNKNOWN"].payload)
    active = payload["active"]
    evidence = payload["unresolved_delivery"][0]
    active["config_fingerprint"] = "sha256:" + "c" * 64
    active["destination_fingerprint"] = "sha256:" + "d" * 64
    active["artifact"]["sha256"] = "sha256:" + "e" * 64
    evidence["destination_fingerprint"] = active["destination_fingerprint"]
    evidence["artifact_sha256"] = active["artifact"]["sha256"]
    rebound = PeriodicStateDocument(payload)
    with pytest.raises(PeriodicContractError):
        _write_edge(tmp_path / "data", delivering, rebound)


def test_mutating_each_active_field_cannot_bypass_unknown_edge_authority(
    tmp_path: Path,
) -> None:
    variants = _variants(tmp_path)
    current = variants["DELIVERING"]
    base = variants["DELIVERY_UNKNOWN"]
    active = base.payload["active"]
    assert isinstance(active, dict)
    for field in active:
        payload = copy.deepcopy(base.payload)
        candidate_active = payload["active"]
        value = candidate_active[field]
        if isinstance(value, bool):
            candidate_active[field] = not value
        elif isinstance(value, int):
            candidate_active[field] = value + 1
        elif isinstance(value, float):
            candidate_active[field] = value + 1.0
        elif isinstance(value, str):
            candidate_active[field] = value + "x"
        elif isinstance(value, dict):
            candidate_active[field] = {**value, "sha256": "sha256:" + "f" * 64}
        elif value is None:
            candidate_active[field] = 1
        else:  # pragma: no cover - closed active schema makes this unreachable
            raise AssertionError(field)
        try:
            candidate = PeriodicStateDocument(payload)
        except PeriodicContractError:
            continue
        with pytest.raises(PeriodicContractError, match="durable|helper|forbidden|evidence"):
            _write_edge(tmp_path / f"mutate-{field}", current, candidate)


def test_representative_legitimate_helper_edges_remain_persistable(tmp_path: Path) -> None:
    variants = _variants(tmp_path)
    for index, (current, candidate) in enumerate(
        (
            (variants["PENDING"], variants["RENDERING"]),
            (variants["RENDERING"], variants["READY"]),
            (variants["READY"], variants["DELIVERING"]),
            (variants["DELIVERING"], variants["SUCCEEDED"]),
            (variants["DELIVERING"], variants["DELIVERY_UNKNOWN"]),
            (variants["SUCCEEDED"], variants["NONE"]),
        )
    ):
        data = tmp_path / f"edge-{index}"
        _write_edge(data, current, candidate)
        assert load_periodic_state(data) == candidate

    retry_render = variants["FAILED"]
    config = _config(tmp_path / "retry")
    active = retry_render.payload["active"]
    assert isinstance(active, dict)
    slot = latest_completed_slot(float(active["slot_end"]), active["interval_s"])
    retried = allocate_pending(
        retry_render,
        slot,
        config,
        generation_id="c" * 32,
        owner_token="d" * 32,
        display_time=DISPLAY_TIME,
        now=active["not_before"],
    )
    _write_edge(tmp_path / "retry-edge", retry_render, retried)

    health = set_periodic_health(
        variants["READY"],
        status="degraded_test",
        code="test_health",
        text="test health transition",
        now=7_204.0,
    )
    _write_edge(tmp_path / "health-edge", variants["READY"], health)

    superseded = supersede_active(variants["READY"], newer_slot_end=9_000, now=7_204.0)
    _write_edge(tmp_path / "supersede-edge", variants["READY"], superseded)

    pending = variants["PENDING"]
    active = pending.payload["active"]
    assert isinstance(active, dict)
    pending_failed = mark_terminal_failure(
        pending,
        phase="render",
        certainty="not_applicable",
        code="invalid_input",
        text="input is invalid",
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_202.0,
    )
    _write_edge(tmp_path / "pending-failed", pending, pending_failed)

    rendering = variants["RENDERING"]
    active = rendering.payload["active"]
    assert isinstance(active, dict)
    render_retry = mark_retryable_failure(
        rendering,
        phase="render",
        certainty="not_applicable",
        code="render_io",
        text="render I/O failed",
        not_before=7_210.0,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_203.0,
    )
    _write_edge(tmp_path / "render-retry", rendering, render_retry)
    render_poison = mark_terminal_failure(
        render_retry,
        phase="render",
        certainty="not_applicable",
        code="render_exhausted",
        text="render retries exhausted",
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_211.0,
    )
    _write_edge(tmp_path / "render-poison", render_retry, render_poison)

    delivering = variants["DELIVERING"]
    active = delivering.payload["active"]
    assert isinstance(active, dict)
    delivery_retry = mark_retryable_failure(
        delivering,
        phase="delivery",
        certainty="not_sent",
        code="connect_failed",
        text="connection failed before send",
        not_before=7_210.0,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_205.0,
    )
    _write_edge(tmp_path / "delivery-retry", delivering, delivery_retry)
    redelivering = mark_delivering(
        delivery_retry,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_210.0,
    )
    _write_edge(tmp_path / "redelivering", delivery_retry, redelivering)
    delivery_poison = mark_terminal_failure(
        delivery_retry,
        phase="delivery",
        certainty="not_sent",
        code="delivery_exhausted",
        text="delivery retries exhausted",
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_210.0,
    )
    _write_edge(tmp_path / "delivery-poison", delivery_retry, delivery_poison)

    full_ready = _with_full_ledger(variants["READY"])
    active = full_ready.payload["active"]
    assert isinstance(active, dict)
    paused_ready = mark_delivering(
        full_ready,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_204.0,
    )
    _write_edge(tmp_path / "full-ready", full_ready, paused_ready)

    full_retry = _with_full_ledger(delivery_retry)
    active = full_retry.payload["active"]
    assert isinstance(active, dict)
    paused_retry = mark_delivering(
        full_retry,
        slot_id=active["slot_id"],
        owner_token=active["owner_token"],
        now=7_210.0,
    )
    _write_edge(tmp_path / "full-retry", full_retry, paused_retry)

    terminal_none = variants["NONE"]
    config = _config(tmp_path / "new-slot")
    newer_slot = latest_completed_slot(9_001.0, config.interval_s)
    newer_pending = allocate_pending(
        terminal_none,
        newer_slot,
        config,
        generation_id="e" * 32,
        owner_token="f" * 32,
        display_time=DISPLAY_TIME,
        now=9_001.0,
    )
    _write_edge(tmp_path / "new-slot-edge", terminal_none, newer_pending)


def test_writer_rejects_fabricated_display_time_change_on_render_retry(
    tmp_path: Path,
) -> None:
    current = _variants(tmp_path)["FAILED"]
    active = current.payload["active"]
    assert isinstance(active, dict)
    config = _config(tmp_path / "retry-display")
    slot = latest_completed_slot(float(active["slot_end"]), active["interval_s"])
    retried = allocate_pending(
        current,
        slot,
        config,
        generation_id="c" * 32,
        owner_token="d" * 32,
        display_time=DISPLAY_TIME,
        now=active["not_before"],
    )
    payload = copy.deepcopy(retried.payload)
    payload["active"]["display_time"] = "10.07.2026 05:05"
    fabricated = PeriodicStateDocument(payload)
    data = tmp_path / "fabricated-display"
    with pytest.raises(PeriodicContractError, match="display_time"):
        _write_edge(data, current, fabricated)
    assert load_periodic_state(data) == current


def test_direct_retryable_scheduler_and_config_documents_are_rejected(
    tmp_path: Path,
) -> None:
    pending = _variants(tmp_path)["PENDING"]
    for phase in ("scheduler", "config"):
        payload = copy.deepcopy(pending.payload)
        active = payload["active"]
        active.update(
            {
                "status": "FAILED",
                "failure_phase": phase,
                "retryable": True,
                "certainty": "not_applicable",
                "error_code": "retry_brick",
                "error_text": "retry brick",
                "not_before": 7_210.0,
            }
        )
        with pytest.raises(PeriodicContractError, match="render or delivery"):
            PeriodicStateDocument(payload)
