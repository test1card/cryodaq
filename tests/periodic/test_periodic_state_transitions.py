from __future__ import annotations

import copy
from pathlib import Path

import pytest

from cryodaq.periodic_config import load_periodic_png_config
from cryodaq.periodic_state import (
    MAX_UNRESOLVED_DELIVERIES,
    PeriodicArtifact,
    PeriodicContractError,
    PeriodicStateDocument,
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
    rotate_terminal_active,
    set_periodic_health,
    supersede_active,
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


def _allocate(tmp_path: Path, state=None, *, slot_end: int = 7_200, serial: int = 1):
    config = _config(tmp_path)
    if state is None:
        state = load_periodic_state(tmp_path / "data")
    slot = latest_completed_slot(float(slot_end), config.interval_s)
    generation = f"{serial:032x}"
    owner = f"{serial + 1000:032x}"
    state = allocate_pending(
        state,
        slot,
        config,
        generation_id=generation,
        owner_token=owner,
        display_time=DISPLAY_TIME,
        now=float(slot_end + 1),
    )
    return state, slot, owner, generation


def _artifact(generation: str) -> PeriodicArtifact:
    return PeriodicArtifact(
        path=f"periodic/generations/{generation}/periodic.png",
        sha256="sha256:" + "a" * 64,
        size=1_024,
        width=1_200,
        height=800,
        mime="image/png",
    )


def _ready(tmp_path: Path, state=None, *, slot_end: int = 7_200, serial: int = 1):
    state, slot, owner, generation = _allocate(
        tmp_path, state, slot_end=slot_end, serial=serial
    )
    state = mark_rendering(
        state, slot_id=slot.slot_id, owner_token=owner, now=float(slot_end + 2)
    )
    state = mark_ready(
        state,
        _artifact(generation),
        "Периодический отчёт",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(slot_end + 3),
    )
    return state, slot, owner


def test_render_and_success_transitions_are_owner_status_fenced(tmp_path: Path) -> None:
    state, slot, owner, generation = _allocate(tmp_path)
    with pytest.raises(PeriodicContractError, match="owner"):
        mark_rendering(state, slot_id=slot.slot_id, owner_token="f" * 32, now=7_202)
    state = mark_rendering(state, slot_id=slot.slot_id, owner_token=owner, now=7_202)
    active = state.payload["active"]
    assert active["status"] == "RENDERING"
    assert active["render_attempt_count"] == 1
    state = mark_ready(
        state,
        _artifact(generation),
        "caption",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_203,
    )
    state = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_204)
    assert state.payload["active"]["delivery_attempt_count"] == 1
    state = mark_succeeded(
        state, message_id=42, slot_id=slot.slot_id, owner_token=owner, now=7_205
    )
    assert state.payload["active"]["status"] == "SUCCEEDED"
    state = rotate_terminal_active(state, now=7_206)
    assert state.payload["active"] is None
    assert "display_time" not in state.payload["last_terminal"]
    assert state.payload["last_terminal"]["telegram_message_id"] == 42
    assert state.payload["high_water_slot_end"] == 7_200
    malformed = copy.deepcopy(state.payload)
    malformed["last_terminal"]["certainty"] = "rejected"
    with pytest.raises(PeriodicContractError, match="inconsistent"):
        PeriodicStateDocument(malformed)


def test_retryable_render_failure_reallocates_same_slot_only_when_due(tmp_path: Path) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    state = mark_rendering(state, slot_id=slot.slot_id, owner_token=owner, now=7_202)
    state = mark_retryable_failure(
        state,
        phase="render",
        certainty="not_applicable",
        code="renderer_failed",
        text="renderer exited with a known failure",
        not_before=7_210,
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_203,
    )
    config = _config(tmp_path)
    with pytest.raises(PeriodicContractError):
        allocate_pending(
            state,
            slot,
            config,
            generation_id="c" * 32,
            owner_token="d" * 32,
            display_time=DISPLAY_TIME,
            now=7_209,
        )
    with pytest.raises(PeriodicContractError, match="durable slot identity"):
        allocate_pending(
            state,
            slot,
            config,
            generation_id="c" * 32,
            owner_token="d" * 32,
            display_time="10.07.2026 05:05",
            now=7_210,
        )
    assert state.payload["active"]["display_time"] == DISPLAY_TIME
    retried = allocate_pending(
        state,
        slot,
        config,
        generation_id="c" * 32,
        owner_token="d" * 32,
        display_time=DISPLAY_TIME,
        now=7_210,
    )
    assert retried.payload["active"]["status"] == "PENDING"
    assert retried.payload["active"]["render_attempt_count"] == 1
    assert retried.payload["active"]["display_time"] == DISPLAY_TIME
    assert retried.payload["high_water_slot_end"] == 7_200


def test_pending_render_failures_consume_attempts_and_exhaust(tmp_path: Path) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    config = _config(tmp_path)
    for attempt in range(1, config.max_render_attempts):
        state = mark_retryable_failure(
            state,
            phase="render",
            certainty="not_applicable",
            code="input_io",
            text="input construction failed",
            not_before=7_201 + attempt * 2,
            slot_id=slot.slot_id,
            owner_token=owner,
            now=7_200 + attempt * 2,
        )
        assert state.payload["active"]["render_attempt_count"] == attempt
        owner = f"{2_000 + attempt:032x}"
        state = allocate_pending(
            state,
            slot,
            config,
            generation_id=f"{100 + attempt:032x}",
            owner_token=owner,
            display_time=DISPLAY_TIME,
            now=7_201 + attempt * 2,
        )

    with pytest.raises(PeriodicContractError, match="exhausted"):
        mark_retryable_failure(
            state,
            phase="render",
            certainty="not_applicable",
            code="input_io",
            text="input construction failed",
            not_before=7_220,
            slot_id=slot.slot_id,
            owner_token=owner,
            now=7_219,
        )
    terminal = mark_terminal_failure(
        state,
        phase="render",
        certainty="not_applicable",
        code="input_io_exhausted",
        text="input construction retries exhausted",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_219,
    )
    assert terminal.payload["active"]["render_attempt_count"] == config.max_render_attempts
    assert terminal.payload["active"]["retryable"] is False


@pytest.mark.parametrize("phase", ["scheduler", "config"])
def test_scheduler_and_config_failures_cannot_create_retryable_bricks(
    tmp_path: Path, phase: str
) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    with pytest.raises(PeriodicContractError, match="cannot be retryable"):
        mark_retryable_failure(
            state,
            phase=phase,
            certainty="not_applicable",
            code="transient",
            text="transient failure",
            not_before=7_210,
            slot_id=slot.slot_id,
            owner_token=owner,
            now=7_202,
        )


def test_failure_phase_and_certainty_pairs_are_exact(tmp_path: Path) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    with pytest.raises(PeriodicContractError, match="invalid certainty"):
        mark_retryable_failure(
            state,
            phase="render",
            certainty="rejected",
            code="bad_pair",
            text="bad pair",
            not_before=7_210,
            slot_id=slot.slot_id,
            owner_token=owner,
            now=7_202,
        )


def test_loaded_status_requires_attempt_evidence(tmp_path: Path) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    rendering = mark_rendering(
        state, slot_id=slot.slot_id, owner_token=owner, now=7_202
    )
    payload = copy.deepcopy(rendering.payload)
    payload["active"]["render_attempt_count"] = 0
    with pytest.raises(PeriodicContractError, match="render-attempt evidence"):
        PeriodicStateDocument(payload)

    delivering, slot, owner = _ready(tmp_path / "delivery")
    delivering = mark_delivering(
        delivering, slot_id=slot.slot_id, owner_token=owner, now=7_204
    )
    payload = copy.deepcopy(delivering.payload)
    payload["active"]["delivery_attempt_count"] = 0
    with pytest.raises(PeriodicContractError, match="delivery-attempt evidence"):
        PeriodicStateDocument(payload)


def test_terminal_failure_rotates_without_lowering_high_water(tmp_path: Path) -> None:
    state, slot, owner, _generation = _allocate(tmp_path)
    state = mark_terminal_failure(
        state,
        phase="render",
        certainty="not_applicable",
        code="invalid_input",
        text="input contract rejected",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_202,
    )
    state = rotate_terminal_active(state, now=7_203)
    assert state.payload["high_water_slot_end"] == 7_200
    assert state.payload["last_terminal"]["status"] == "FAILED"


def test_unknown_transition_appends_evidence_atomically_and_never_retries(tmp_path: Path) -> None:
    state, slot, owner = _ready(tmp_path)
    state = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_204)
    state = mark_delivery_unknown(
        state,
        code="response_ambiguous",
        text="delivery outcome could not be proven",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_205,
    )
    assert state.payload["active"]["status"] == "DELIVERY_UNKNOWN"
    assert len(state.payload["unresolved_delivery"]) == 1
    evidence = dict(state.payload["unresolved_delivery"][0])
    with pytest.raises(PeriodicContractError):
        mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_206)
    state = rotate_terminal_active(state, now=7_206)
    assert state.payload["unresolved_delivery"][0] == evidence


def test_stale_delivering_uses_same_unknown_transition(tmp_path: Path) -> None:
    state, slot, owner = _ready(tmp_path)
    stale = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_204)
    recovered = mark_delivery_unknown(
        stale,
        code="stale_delivering",
        text="delivery was in flight when the coordinator stopped",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_300,
    )
    assert recovered.payload["active"]["status"] == "DELIVERY_UNKNOWN"
    assert recovered.payload["unresolved_delivery"][0]["error_code"] == "stale_delivering"


def test_unknown_rotation_allows_strictly_newer_slot_and_preserves_evidence(tmp_path: Path) -> None:
    state, slot, owner = _ready(tmp_path)
    state = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_204)
    state = mark_delivery_unknown(
        state,
        code="unknown",
        text="ambiguous result",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=7_205,
    )
    state = rotate_terminal_active(state, now=7_206)
    evidence = dict(state.payload["unresolved_delivery"][0])
    state, newer, _owner, _generation = _allocate(
        tmp_path, state, slot_end=9_000, serial=2
    )
    assert state.payload["high_water_slot_end"] == newer.slot_end
    assert state.payload["unresolved_delivery"][0] == evidence


def test_full_unknown_ledger_pauses_ready_without_eviction_or_supersession(tmp_path: Path) -> None:
    state = None
    for index in range(MAX_UNRESOLVED_DELIVERIES):
        slot_end = 7_200 + index * 1_800
        state, slot, owner = _ready(
            tmp_path, state, slot_end=slot_end, serial=index + 1
        )
        state = mark_delivering(
            state, slot_id=slot.slot_id, owner_token=owner, now=slot_end + 4
        )
        state = mark_delivery_unknown(
            state,
            code="ambiguous",
            text="ambiguous result",
            slot_id=slot.slot_id,
            owner_token=owner,
            now=slot_end + 5,
        )
        state = rotate_terminal_active(state, now=slot_end + 6)
    assert len(state.payload["unresolved_delivery"]) == MAX_UNRESOLVED_DELIVERIES
    first_evidence = dict(state.payload["unresolved_delivery"][0])
    slot_end = 7_200 + MAX_UNRESOLVED_DELIVERIES * 1_800
    state, slot, owner = _ready(
        tmp_path, state, slot_end=slot_end, serial=MAX_UNRESOLVED_DELIVERIES + 1
    )
    paused = mark_delivering(
        state, slot_id=slot.slot_id, owner_token=owner, now=slot_end + 4
    )
    assert paused.payload["active"]["status"] == "READY"
    assert paused.payload["health"]["status"] == "paused_unknown_capacity"
    assert len(paused.payload["unresolved_delivery"]) == MAX_UNRESOLVED_DELIVERIES
    assert paused.payload["unresolved_delivery"][0] == first_evidence
    still_paused = supersede_active(paused, newer_slot_end=slot_end + 1_800, now=slot_end + 5)
    assert still_paused.payload["active"]["status"] == "READY"


def test_supersession_is_terminal_but_never_interrupts_delivering(tmp_path: Path) -> None:
    state, slot, owner = _ready(tmp_path)
    superseded = supersede_active(state, newer_slot_end=9_000, now=7_204)
    assert superseded.payload["active"]["status"] == "FAILED"
    assert superseded.payload["active"]["error_code"] == "superseded_by_newer_slot"

    state, slot, owner = _ready(tmp_path / "inflight")
    state = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=7_204)
    with pytest.raises(PeriodicContractError, match="in-flight"):
        supersede_active(state, newer_slot_end=9_000, now=7_205)
    for phase in ("scheduler", "config"):
        with pytest.raises(PeriodicContractError, match="in-flight delivery"):
            mark_terminal_failure(
                state,
                phase=phase,
                certainty="not_applicable",
                code="unsafe_exit",
                text="unsafe in-flight exit",
                slot_id=slot.slot_id,
                owner_token=owner,
                now=7_205,
            )


def test_health_transition_is_pure_bounded_and_secret_rejecting(tmp_path: Path) -> None:
    state, _slot, _owner, _generation = _allocate(tmp_path)
    changed = set_periodic_health(
        state,
        status="degraded_config",
        code="invalid_config",
        text="periodic configuration is invalid",
        now=7_202,
    )
    assert state.payload["health"]["status"] == "starting"
    assert changed.payload["health"]["status"] == "degraded_config"
    with pytest.raises(PeriodicContractError, match="sensitive"):
        set_periodic_health(
            state,
            status="degraded_config",
            code="invalid_config",
            text="https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyzABCDE/sendPhoto",
            now=7_202,
        )
