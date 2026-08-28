"""Operator-owned software-interlock optionality and provenance."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.core.command_authority import (
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_PROTOCOL_MAJOR,
)
from cryodaq.core.experiment import ExperimentManager
from cryodaq.core.interlock import (
    InterlockCondition,
    InterlockConfigError,
    InterlockEngine,
    InterlockState,
)
from cryodaq.core.operator_log import OperatorLogCommitResult, OperatorLogEntry
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine import EngineCommandContext, _handle_gui_command
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyBlocker,
)
from cryodaq.gui import theme
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth, SafetyLifecycle
from cryodaq.storage.sqlite_writer import OperatorLogPublicationOutboxRecord

_DEFAULT_SAFETY_MANAGER = object()


@pytest.fixture
def workspace_runtime_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def _managed_sandbox_threaded_write_workaround(monkeypatch: pytest.MonkeyPatch) -> None:
    """The managed test sandbox cannot settle threaded filesystem writes.

    Production retains ``asyncio.to_thread`` at both runtime write sites. This
    file executes the exact synchronous operation inline so behavioral tests
    can observe persistence without hanging on the sandbox mount adapter.
    """

    async def inline(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


def _condition(*, action: str = "emergency_off") -> InterlockCondition:
    return InterlockCondition(
        name="overheat_cryostat",
        description="Перегрев криостата",
        channel_ids=frozenset({"cryostat/t1"}),
        threshold=350.0,
        comparison=">",
        action=action,
        cooldown_s=10.0,
        operator_disableable=True,
        enabled_by_default=True,
    )


def _reading(value: float = 360.0) -> Reading:
    return Reading(
        timestamp=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        instrument_id="LS218_1",
        channel="cryostat/t1",
        value=value,
        unit="K",
        status=ChannelStatus.OK,
    )


def _commit_receipt(request_id: str) -> dict[str, object]:
    return {
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "entry_id": 1,
        "experiment_id": None,
        "committed": True,
    }


async def _toggle(engine: InterlockEngine, *, enabled: bool, request_id: str) -> dict[str, object]:
    notice = engine.prepare_operator_toggle("overheat_cryostat", enabled=enabled)
    return await engine.set_enabled(
        "overheat_cryostat",
        enabled=enabled,
        operator="Иван Петров",
        changed_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        request_id=request_id,
        notice=notice,
        commit_receipt=_commit_receipt(request_id),
    )


def test_tracked_policy_makes_every_row_optional_and_enabled_by_default() -> None:
    payload = yaml.safe_load(Path("config/interlocks.yaml").read_text(encoding="utf-8"))

    assert payload["operator_disableable"] is True
    assert payload["enabled_by_default"] is True
    assert all("operator_disableable" not in row and "enabled" not in row for row in payload["interlocks"])
    assert any(row["action"] == "emergency_off" for row in payload["interlocks"])

    instruments = {binding["instrument_id"] for row in payload["interlocks"] for binding in row["channel_bindings"]}
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock(), "stop_source": AsyncMock()},
    )
    engine.load_config(
        Path("config/interlocks.yaml"),
        poll_intervals_s_by_instrument={instrument_id: 2.0 for instrument_id in instruments},
    )
    states = engine.get_operator_state()
    assert len(states) == len(payload["interlocks"])
    assert all(state["operator_disableable"] is True and state["enabled"] is True for state in states)
    assert any(state["action"] == "emergency_off" for state in states)


@pytest.mark.asyncio
async def test_disabled_emergency_interlock_still_evaluates_warns_and_suppresses_action(
    workspace_runtime_root: Path,
) -> None:
    action = AsyncMock()
    warnings: list[str] = []

    async def warned(_condition, _reading, message: str) -> None:
        warnings.append(message)

    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": action},
        suppressed_handler=warned,
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())

    result = await _toggle(engine, enabled=False, request_id="a" * 32)
    await engine._process_reading(_reading())

    assert result["enabled"] is False
    action.assert_not_awaited()
    assert len(warnings) == 1
    warning = warnings[0]
    assert "overheat_cryostat" in warning
    assert "360" in warning
    assert "> 350" in warning
    assert "подавлена решением оператора" in warning
    assert engine.get_events()[-1].action_taken == "suppressed:emergency_off"


@pytest.mark.asyncio
async def test_disabled_interlock_does_not_escalate_its_dead_channel(
    workspace_runtime_root: Path,
) -> None:
    dead_channel = AsyncMock(return_value=True)
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        dead_channel_handler=dead_channel,
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    engine._nonusable_min_samples = 2
    engine._nonusable_min_duration_s = 1.0
    await _toggle(engine, enabled=False, request_id="1" * 32)

    for seconds in (0, 1):
        await engine._process_reading(
            Reading(
                timestamp=datetime(2026, 8, 28, 12, 0, seconds, tzinfo=UTC),
                instrument_id="LS218_1",
                channel="cryostat/t1",
                value=float("nan"),
                unit="K",
                status=ChannelStatus.SENSOR_ERROR,
            )
        )

    dead_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_reenable_fires_immediately_when_last_observation_is_still_true(
    workspace_runtime_root: Path,
) -> None:
    action = AsyncMock()
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": action},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    await _toggle(engine, enabled=False, request_id="b" * 32)
    await engine._process_reading(_reading())
    action.assert_not_awaited()

    await _toggle(engine, enabled=True, request_id="c" * 32)

    action.assert_awaited_once()
    assert engine.get_events()[-1].action_taken == "emergency_off"


@pytest.mark.asyncio
async def test_reenable_rearms_a_previously_tripped_row(
    workspace_runtime_root: Path,
) -> None:
    action = AsyncMock()
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": action},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    await engine._process_reading(_reading())
    await _toggle(engine, enabled=False, request_id="2" * 32)
    await engine._process_reading(_reading(300.0))

    await _toggle(engine, enabled=True, request_id="3" * 32)
    assert engine.get_state()["overheat_cryostat"] is InterlockState.ARMED
    await engine._process_reading(_reading())

    assert action.await_count == 2


@pytest.mark.asyncio
async def test_reenable_evaluates_latest_reading_for_every_bound_channel(
    workspace_runtime_root: Path,
) -> None:
    action = AsyncMock()
    condition = InterlockCondition(
        name="overheat_cryostat",
        description="Перегрев криостата",
        channel_ids=frozenset({"cryostat/t1", "cryostat/t2"}),
        threshold=350.0,
        comparison=">",
        action="emergency_off",
        cooldown_s=10.0,
    )
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": action},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(condition)
    await _toggle(engine, enabled=False, request_id="4" * 32)
    await engine._process_reading(_reading())
    await engine._process_reading(
        Reading(
            timestamp=datetime(2026, 8, 28, 12, 0, 1, tzinfo=UTC),
            instrument_id="LS218_1",
            channel="cryostat/t2",
            value=300.0,
            unit="K",
            status=ChannelStatus.OK,
        )
    )

    await _toggle(engine, enabled=True, request_id="5" * 32)

    action.assert_awaited_once()
    assert engine.get_events()[-1].channel == "cryostat/t1"


@pytest.mark.asyncio
async def test_disabled_state_survives_engine_reconstruction(workspace_runtime_root: Path) -> None:
    state_path = workspace_runtime_root / "interlock_operator_state.json"
    first = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    first.add_condition(_condition())
    await _toggle(first, enabled=False, request_id="d" * 32)

    restarted = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    restarted.add_condition(_condition())
    await restarted.restore_operator_state()

    assert restarted.disabled_interlocks() == ("overheat_cryostat",)
    restored = restarted.get_operator_state()[0]
    assert restored["enabled"] is False
    assert restored["disable_receipt"]["operator"] == "Иван Петров"
    assert restored["disable_receipt"]["notice"]


class _RequiredPublisher:
    def __init__(self) -> None:
        self.events: list[Reading] = []

    async def publish_required(self, event, *, request_id: str, request_fingerprint: str):
        self.events.append(event)
        return {
            "accepted": True,
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
        }

    async def publish(self, event) -> None:
        self.events.append(event)

    @staticmethod
    def validates_required_publication(receipt, *, request_id: str, request_fingerprint: str) -> bool:
        return receipt == {
            "accepted": True,
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
        }


class _NoopEventLogger:
    async def log_event(self, _category: str, _message: str) -> None:
        return None


class _ReceiptWriter:
    def __init__(self) -> None:
        self.entries: list[OperatorLogEntry] = []
        self.publications: dict[str, OperatorLogPublicationOutboxRecord] = {}

    async def find_operator_log_request(self, **_kwargs):
        return None

    async def append_operator_log(self, **kwargs) -> OperatorLogEntry:
        entry = OperatorLogEntry(
            id=len(self.entries) + 1,
            timestamp=datetime(2026, 8, 28, 12, len(self.entries), tzinfo=UTC),
            experiment_id=kwargs.get("experiment_id"),
            author=kwargs["author"],
            source=kwargs["source"],
            message=kwargs["message"],
            tags=tuple(kwargs["tags"]),
        )
        self.entries.append(entry)
        return entry

    async def append_operator_log_with_publication_intent(self, **kwargs):
        entry = OperatorLogEntry(
            id=len(self.entries) + 1,
            timestamp=datetime(2026, 8, 28, 12, len(self.entries), tzinfo=UTC),
            experiment_id=kwargs["experiment_id"],
            author=kwargs["author"],
            source=kwargs["source"],
            message=kwargs["message"],
            tags=tuple(kwargs["tags"]),
        )
        self.entries.append(entry)
        event = {"schema": "operator_log_commit_v1", "entry": entry.to_payload()}
        receipt = {
            "schema": "operator_log_commit_v1",
            "request_id": kwargs["request_id"],
            "entry_id": entry.id,
            "experiment_id": entry.experiment_id,
            "committed": True,
        }
        publication = OperatorLogPublicationOutboxRecord(
            request_id=kwargs["request_id"],
            request_fingerprint=kwargs["request_fingerprint"],
            state="intent",
            event=event,
            receipt=receipt,
        )
        self.publications[kwargs["request_id"]] = publication
        return OperatorLogCommitResult(entry=entry, replayed=False), publication

    async def publish_operator_log_publication_outbox(self, *, request_id: str, request_fingerprint: str):
        publication = self.publications[request_id]
        return OperatorLogPublicationOutboxRecord(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            state="published",
            event=publication.event,
            receipt=publication.receipt,
        )


def _command_context(
    *,
    manager: ExperimentManager,
    writer: _ReceiptWriter,
    broker: _RequiredPublisher,
    interlock_engine: InterlockEngine,
    safety_manager=_DEFAULT_SAFETY_MANAGER,
) -> EngineCommandContext:
    if safety_manager is _DEFAULT_SAFETY_MANAGER:
        verified_off = OperatorSafetySnapshot(
            revision=1,
            observed_monotonic_s=0.0,
            lifecycle=SafetyLifecycle.READY,
            readiness=ReadinessTruth.READY,
            off_tier="verified_off",
            channel_off_results=(("smua", "device_reported_off"), ("smub", "device_reported_off")),
            verified_off=True,
            blockers=(),
            plant_health=(
                PlantHealthFact(
                    "reviewed_source",
                    "Reviewed source",
                    OperatorPresentationState.OK,
                    "reviewed_source_verified_off",
                ),
            ),
        )
        safety_manager = SimpleNamespace(snapshot_operator_safety=lambda: verified_off)
    return EngineCommandContext(
        safety_manager=safety_manager,
        event_logger=_NoopEventLogger(),
        sink_registry=SimpleNamespace(sinks=[]),
        interlock_engine=interlock_engine,
        leak_rate_estimator=None,
        leak_cfg={},
        alarm_v2_state_mgr=None,
        alarm_ring=None,
        broker=broker,
        experiment_manager=manager,
        calibration_acquisition=SimpleNamespace(deactivate=lambda: None),
        event_bus=SimpleNamespace(publish=AsyncMock()),
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=None,
        writer=writer,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=None,
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        mutation_capability_token="interlock-test-capability",
    )


def _mutation(command: dict[str, object]) -> dict[str, object]:
    return {
        **command,
        "protocol_major": MUTATION_PROTOCOL_MAJOR,
        "mutation_capability": ENGINE_MUTATION_CAPABILITY,
        "capability_token": "interlock-test-capability",
    }


@pytest.mark.asyncio
async def test_suppressed_warning_uses_existing_operator_log_and_alarm_event_surfaces() -> None:
    from cryodaq.engine import _interlock_suppressed_handler, _InterlockHandlerContext

    writer = _ReceiptWriter()
    broker = _RequiredPublisher()
    event_bus = SimpleNamespace(events=[])

    async def publish(event) -> None:
        event_bus.events.append(event)

    event_bus.publish = publish
    context = _InterlockHandlerContext(
        safety_manager=None,
        writer=writer,
        broker=broker,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="exp-1"),
    )
    message = (
        "Блокировка 'overheat_cryostat' подавлена решением оператора: "
        "значение 360 K пересекло порог > 350; действие 'emergency_off' не выполнено."
    )

    await _interlock_suppressed_handler(_condition(), _reading(), message, context=context)

    assert writer.entries[0].message == message
    assert writer.entries[0].experiment_id == "exp-1"
    assert broker.events[0].channel == "analytics/operator_log_entry"
    alarm = event_bus.events[0]
    assert alarm.event_type == "alarm_fired"
    assert alarm.payload["level"] == "WARNING"
    assert alarm.payload["message"] == message


@pytest.mark.asyncio
async def test_suppressed_warning_retries_immediately_after_total_publication_failure(
    workspace_runtime_root: Path,
) -> None:
    warning_surface = AsyncMock(side_effect=[RuntimeError("all surfaces unavailable"), None])
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        suppressed_handler=warning_surface,
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    await _toggle(engine, enabled=False, request_id="6" * 32)

    await engine._process_reading(_reading())
    await engine._process_reading(_reading())

    assert warning_surface.await_count == 2


@pytest.mark.asyncio
async def test_toggle_commands_need_no_confirmation_write_two_receipts_and_run_interval(
    workspace_runtime_root: Path,
) -> None:
    writer = _ReceiptWriter()
    manager = ExperimentManager(
        workspace_runtime_root / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    experiment_id = manager.start_experiment("Опциональные блокировки", "Иван Петров", template_id="custom")
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    broker = _RequiredPublisher()
    context = _command_context(manager=manager, writer=writer, broker=broker, interlock_engine=engine)
    try:
        disabled = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": False,
                    "operator": "Иван Петров",
                    "request_id": "e" * 32,
                }
            ),
            context=context,
        )
        enabled = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": True,
                    "operator": "Иван Петров",
                    "request_id": "f" * 32,
                }
            ),
            context=context,
        )

        assert disabled["ok"] is True
        assert enabled["ok"] is True
        assert disabled["commit_receipt"]["request_id"] == "e" * 32
        assert enabled["commit_receipt"]["request_id"] == "f" * 32
        for result in (disabled, enabled):
            assert result["entry"]["author"] == "Иван Петров"
            assert result["entry"]["timestamp"]
            assert "overheat_cryostat" in result["entry"]["message"]
            assert result["entry"]["message"] == result["interlock"]["notice"]

        assert [entry.author for entry in writer.entries] == ["Иван Петров", "Иван Петров"]
        metadata_path = workspace_runtime_root / "experiment" / "experiments" / experiment_id / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        interval = metadata["interlock_disable_intervals"][0]
        assert interval["interlock_name"] == "overheat_cryostat"
        assert interval["disabled_at"] == disabled["entry"]["timestamp"]
        assert interval["reenabled_at"] == enabled["entry"]["timestamp"]
        assert interval["disable_receipt"]["commit_receipt"] == disabled["commit_receipt"]
        assert interval["reenable_receipt"]["commit_receipt"] == enabled["commit_receipt"]
    finally:
        context.experiment_commands_accepting = False


@pytest.mark.asyncio
async def test_delayed_toggle_replay_returns_original_result_without_reapplying_stale_state(
    workspace_runtime_root: Path,
) -> None:
    writer = _ReceiptWriter()
    manager = ExperimentManager(
        workspace_runtime_root / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    experiment_id = manager.start_experiment("Идемпотентность блокировок", "Иван Петров", template_id="custom")
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    context = _command_context(
        manager=manager,
        writer=writer,
        broker=_RequiredPublisher(),
        interlock_engine=engine,
    )
    disable_command = _mutation(
        {
            "cmd": "interlock_set_enabled",
            "interlock_name": "overheat_cryostat",
            "enabled": False,
            "operator": "Иван Петров",
            "request_id": "1" * 32,
        }
    )
    try:
        original = await _handle_gui_command(disable_command, context=context)
        reenabled = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": True,
                    "operator": "Иван Петров",
                    "request_id": "2" * 32,
                }
            ),
            context=context,
        )

        replayed = await _handle_gui_command(disable_command, context=context)

        assert original["interlock"] == replayed["interlock"]
        assert reenabled["interlock"]["enabled"] is True
        assert engine.disabled_interlocks() == ()
        assert len(writer.entries) == 2
        metadata = json.loads(
            (workspace_runtime_root / "experiment" / "experiments" / experiment_id / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert len(metadata["interlock_disable_intervals"]) == 1
        assert metadata["interlock_disable_intervals"][0]["reenabled_at"] == reenabled["entry"]["timestamp"]
    finally:
        context.experiment_commands_accepting = False


@pytest.mark.asyncio
async def test_toggle_provenance_remains_bound_to_logged_experiment_across_lifecycle_change(
    workspace_runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _ReceiptWriter()
    manager = ExperimentManager(
        workspace_runtime_root / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    experiment_a = manager.start_experiment("Эксперимент A", "Иван Петров", template_id="custom")
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    original_set_enabled = engine.set_enabled
    experiment_b: str | None = None

    async def change_lifecycle_after_state_commit(*args, **kwargs):
        nonlocal experiment_b
        result = await original_set_enabled(*args, **kwargs)
        manager.finalize_experiment(experiment_a)
        experiment_b = manager.start_experiment("Эксперимент B", "Иван Петров", template_id="custom")
        return result

    monkeypatch.setattr(engine, "set_enabled", change_lifecycle_after_state_commit)
    context = _command_context(
        manager=manager,
        writer=writer,
        broker=_RequiredPublisher(),
        interlock_engine=engine,
    )
    try:
        result = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": False,
                    "operator": "Иван Петров",
                    "request_id": "3" * 32,
                }
            ),
            context=context,
        )

        assert result["ok"] is True
        metadata_a = json.loads(
            (workspace_runtime_root / "experiment" / "experiments" / experiment_a / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        metadata_b = json.loads(
            (workspace_runtime_root / "experiment" / "experiments" / experiment_b / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert (
            metadata_a["interlock_disable_intervals"][0]["disable_receipt"]["commit_receipt"]["experiment_id"]
            == experiment_a
        )
        assert metadata_b.get("interlock_disable_intervals", []) == []
    finally:
        context.experiment_commands_accepting = False


@pytest.mark.asyncio
async def test_cancellation_settles_state_write_and_live_transition_before_propagating(
    workspace_runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = workspace_runtime_root / "interlock_operator_state.json"
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    engine.add_condition(_condition())
    write_started = asyncio.Event()
    allow_write = asyncio.Event()
    write_finished = asyncio.Event()

    async def retained_to_thread(function, /, *args, **kwargs):
        async def owner() -> None:
            write_started.set()
            await allow_write.wait()
            function(*args, **kwargs)
            write_finished.set()

        return await asyncio.shield(asyncio.create_task(owner()))

    monkeypatch.setattr(asyncio, "to_thread", retained_to_thread)
    task = asyncio.create_task(_toggle(engine, enabled=False, request_id="4" * 32))
    await asyncio.wait_for(write_started.wait(), timeout=5)

    task.cancel()
    allow_write.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(write_finished.wait(), timeout=5)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["interlocks"]["overheat_cryostat"]["enabled"] is False
    assert engine.disabled_interlocks() == ("overheat_cryostat",)


@pytest.mark.asyncio
async def test_restore_rejects_disabled_state_without_a_complete_receipt(
    workspace_runtime_root: Path,
) -> None:
    state_path = workspace_runtime_root / "interlock_operator_state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "interlocks": {
                    "overheat_cryostat": {
                        "enabled": False,
                        "receipt": {},
                        "pending_receipts": [],
                    }
                },
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    engine.add_condition(_condition())

    with pytest.raises(InterlockConfigError, match="invalid"):
        await engine.restore_operator_state()


@pytest.mark.asyncio
async def test_active_source_cannot_disable_emergency_interlock_through_mutation_endpoint(
    workspace_runtime_root: Path,
) -> None:
    writer = _ReceiptWriter()
    manager = ExperimentManager(
        workspace_runtime_root / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    manager.start_experiment("Активный источник", "Иван Петров", template_id="custom")
    active_snapshot = OperatorSafetySnapshot(
        revision=1,
        observed_monotonic_s=0.0,
        lifecycle=SafetyLifecycle.RUNNING,
        readiness=ReadinessTruth.BLOCKED,
        off_tier="command_only",
        channel_off_results=(("smua", "physical_state_unknown"), ("smub", "physical_state_unknown")),
        verified_off=False,
        blockers=(
            SafetyBlocker(
                "source_operation_active",
                OperatorPresentationState.WARNING,
                "A source operation is active",
                "Reach verified OFF before suppressing an interlock",
            ),
        ),
        plant_health=(
            PlantHealthFact(
                "reviewed_source",
                "Reviewed source",
                OperatorPresentationState.WARNING,
                "source_operation_active",
            ),
        ),
    )
    safety_manager = SimpleNamespace(snapshot_operator_safety=lambda: active_snapshot)
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    context = _command_context(
        manager=manager,
        writer=writer,
        broker=_RequiredPublisher(),
        interlock_engine=engine,
        safety_manager=safety_manager,
    )
    try:
        result = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": False,
                    "operator": "Иван Петров",
                    "request_id": "5" * 32,
                }
            ),
            context=context,
        )

        assert result["ok"] is False
        assert result["error_code"] == "interlock_disable_requires_verified_off"
        assert result["retry_safe"] is True
        assert writer.entries == []
        assert engine.disabled_interlocks() == ()
    finally:
        context.experiment_commands_accepting = False


@pytest.mark.asyncio
async def test_restore_rejects_disabled_receipt_after_interlock_policy_changes(
    workspace_runtime_root: Path,
) -> None:
    state_path = workspace_runtime_root / "interlock_operator_state.json"
    original = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    original.add_condition(_condition())
    await _toggle(original, enabled=False, request_id="6" * 32)

    changed = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    changed.add_condition(
        InterlockCondition(
            name="overheat_cryostat",
            description="Перегрев криостата",
            channel_ids=frozenset({"cryostat/t1"}),
            threshold=351.0,
            comparison=">",
            action="emergency_off",
            cooldown_s=10.0,
            operator_disableable=True,
            enabled_by_default=True,
        )
    )

    with pytest.raises(InterlockConfigError, match="policy"):
        await changed.restore_operator_state()


@pytest.mark.asyncio
async def test_toggle_history_survives_failed_provenance_until_restart_reconciliation(
    workspace_runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _ReceiptWriter()
    manager = ExperimentManager(
        workspace_runtime_root / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    experiment_id = manager.start_experiment("История блокировок", "Иван Петров", template_id="custom")
    reconcile = manager.sync_interlock_operator_provenance

    def fail_provenance(**_kwargs) -> bool:
        raise OSError("metadata unavailable")

    monkeypatch.setattr(manager, "record_interlock_operator_state", fail_provenance)
    state_path = workspace_runtime_root / "interlock_operator_state.json"
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=state_path,
    )
    engine.add_condition(_condition())
    context = _command_context(
        manager=manager,
        writer=writer,
        broker=_RequiredPublisher(),
        interlock_engine=engine,
    )
    try:
        disabled = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": False,
                    "operator": "Иван Петров",
                    "request_id": "7" * 32,
                }
            ),
            context=context,
        )
        enabled = await _handle_gui_command(
            _mutation(
                {
                    "cmd": "interlock_set_enabled",
                    "interlock_name": "overheat_cryostat",
                    "enabled": True,
                    "operator": "Иван Петров",
                    "request_id": "8" * 32,
                }
            ),
            context=context,
        )
        assert disabled["error_code"] == "interlock_toggle_reconciliation_failed"
        assert enabled["error_code"] == "interlock_toggle_reconciliation_failed"

        restarted = InterlockEngine(
            broker=None,  # type: ignore[arg-type]
            actions={"emergency_off": AsyncMock()},
            state_path=state_path,
        )
        restarted.add_condition(_condition())
        await restarted.restore_operator_state()
        assert reconcile(restarted.get_operator_state()) is True

        metadata_path = workspace_runtime_root / "experiment" / "experiments" / experiment_id / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        interval = metadata["interlock_disable_intervals"][0]
        assert interval["disabled_at"] == disabled["entry"]["timestamp"]
        assert interval["reenabled_at"] == enabled["entry"]["timestamp"]
        assert interval["disable_receipt"]["request_id"] == "7" * 32
        assert interval["reenable_receipt"]["request_id"] == "8" * 32
    finally:
        context.experiment_commands_accepting = False


@pytest.mark.asyncio
async def test_unsettled_toggle_history_is_bounded_fail_closed(
    workspace_runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.core.interlock as interlock_module

    monkeypatch.setattr(interlock_module, "_MAX_PENDING_OPERATOR_TRANSITIONS", 2)
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": AsyncMock()},
        state_path=workspace_runtime_root / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    await _toggle(engine, enabled=False, request_id="9" * 32)
    await _toggle(engine, enabled=True, request_id="a" * 32)

    with pytest.raises(RuntimeError, match="provenance backlog is full"):
        engine.prepare_operator_toggle("overheat_cryostat", enabled=False)


def test_bottom_bar_lists_currently_disabled_interlocks() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindowV2()
    try:
        window._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="safety_manager",
                channel="analytics/safety_state",
                value=0.0,
                unit="",
                metadata={
                    "state": "ready",
                    "reason": "",
                    "disabled_interlocks": ["overheat_compressor", "overheat_cryostat"],
                },
            )
        )
        bar = window._bottom_bar
        assert "overheat_compressor" in bar._interlock_label.text()
        assert "overheat_cryostat" in bar._interlock_label.text()
        assert theme.STATUS_WARNING in bar._interlock_label.styleSheet()
        assert "Отключённые программные блокировки" in bar._interlock_label.accessibleDescription()
    finally:
        for timer in window.findChildren(QTimer):
            timer.stop()
        window.close()
        app.processEvents()
