from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime

import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.experiment import ExperimentManager, RunRecord
from cryodaq.storage import conductivity_run as module
from cryodaq.storage.conductivity_run import (
    ConductivityRunFormatError,
    ConductivityRunWriter,
    read_conductivity_run,
)


def _point() -> dict[str, float | str]:
    return {
        "timestamp_utc": "2026-08-27T12:00:00+00:00",
        "P_W": 0.012,
        "T_hot_K": 110.0,
        "T_cold_K": 100.0,
        "T_avg_K": 105.0,
        "dT_K": 10.0,
        "R_KW": 10.0 / 0.012,
        "G_WK": 0.0012,
        "settled_pct": 99.0,
    }


def _bound_parameters() -> dict[str, object]:
    def _descriptor(
        channel_id: str,
        instrument_id: str,
        source_key: str,
        quantity: ChannelQuantity,
        unit: str,
        role: ChannelRole,
        safety_class: ChannelSafetyClass,
        display_order: int,
    ) -> dict[str, object]:
        descriptor = ChannelDescriptorV1(
            schema_version=1,
            channel_id=channel_id,
            instrument_id=instrument_id,
            source_key=source_key,
            quantity=quantity,
            unit=unit,
            role=role,
            safety_class=safety_class,
            display_group="test",
            display_name=channel_id,
            visible_by_default=True,
            display_order=display_order,
            descriptor_revision=1,
        )
        return json.loads(PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json)

    return {
        "power_values_w": [0.012],
        "power_channel": "Keithley_1/smua/power",
        "temperature_channels": ["Т1", "Т2"],
        "bound_descriptors": {
            "power": _descriptor(
                "Keithley_1/smua/power",
                "Keithley_1",
                "smua.power",
                ChannelQuantity.POWER,
                "W",
                ChannelRole.SOURCE_READBACK,
                ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK,
                2,
            ),
            "temperatures": [
                _descriptor(
                    "Т1",
                    "LakeShore_1",
                    "input.1.temperature",
                    ChannelQuantity.TEMPERATURE,
                    "K",
                    ChannelRole.PRIMARY_MEASUREMENT,
                    ChannelSafetyClass.OBSERVATIONAL,
                    0,
                ),
                _descriptor(
                    "Т2",
                    "LakeShore_1",
                    "input.2.temperature",
                    ChannelQuantity.TEMPERATURE,
                    "K",
                    ChannelRole.PRIMARY_MEASUREMENT,
                    ChannelSafetyClass.OBSERVATIONAL,
                    1,
                ),
            ],
        },
    }


def _identified_row() -> dict[str, object]:
    parameters = _bound_parameters()
    bound = parameters["bound_descriptors"]
    assert isinstance(bound, dict)
    power = bound["power"]
    temperatures = bound["temperatures"]
    assert isinstance(power, dict)
    assert isinstance(temperatures, list)
    hot, cold = temperatures
    return {
        "temperature_k": 105.0,
        "conductance_wk": 0.0012,
        "resistance_kw": pytest.approx(10.0 / 0.012),
        "power_channel_id": power["descriptor"]["channel_id"],
        "power_instrument_id": power["descriptor"]["instrument_id"],
        "power_source_key": power["descriptor"]["source_key"],
        "power_descriptor_hash": power["descriptor_hash"],
        "power_descriptor_revision": power["descriptor"]["descriptor_revision"],
        "hot_channel_id": hot["descriptor"]["channel_id"],
        "hot_instrument_id": hot["descriptor"]["instrument_id"],
        "hot_source_key": hot["descriptor"]["source_key"],
        "hot_descriptor_hash": hot["descriptor_hash"],
        "hot_descriptor_revision": hot["descriptor"]["descriptor_revision"],
        "cold_channel_id": cold["descriptor"]["channel_id"],
        "cold_instrument_id": cold["descriptor"]["instrument_id"],
        "cold_source_key": cold["descriptor"]["source_key"],
        "cold_descriptor_hash": cold["descriptor_hash"],
        "cold_descriptor_revision": cold["descriptor"]["descriptor_revision"],
    }


def test_point_row_and_checkpoint_have_separate_fsync_boundaries(tmp_path, monkeypatch) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={"power_values_w": [0.012]},
    )
    real_fsync = os.fsync
    snapshots: list[str] = []

    def _fsync_and_capture(fd: int) -> None:
        real_fsync(fd)
        snapshots.append(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(module.os, "fsync", _fsync_and_capture)
    writer.append_point(_point())

    assert len(snapshots) == 2
    assert "0.012" in snapshots[0]
    assert "conductivity_run_checkpoint" not in snapshots[0]
    assert '"accepted_point_count":1' in snapshots[1]

    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    snapshot = read_conductivity_run(path)
    assert snapshot.raw_row_count == 1
    assert snapshot.rows == (
        {
            "temperature_k": 105.0,
            "conductance_wk": 0.0012,
            "resistance_kw": pytest.approx(10.0 / 0.012),
        },
    )
    assert snapshot.terminal is not None
    assert snapshot.terminal["status"] == "COMPLETED"


def test_durable_file_without_terminal_exposes_recoverable_checkpoint_prefix(tmp_path) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_point(_point())
    writer.close()

    snapshot = read_conductivity_run(path)
    assert snapshot.durable_format is True
    assert snapshot.raw_row_count == 1
    assert snapshot.rows == (
        {
            "temperature_k": 105.0,
            "conductance_wk": 0.0012,
            "resistance_kw": pytest.approx(10.0 / 0.012),
        },
    )
    assert snapshot.terminal is None

    assert snapshot.run_id == "run-1"
    assert snapshot.status == "RUNNING"
    assert snapshot.accepted_point_count == 1
    assert snapshot.checkpoint_count == 1
    assert snapshot.recovery_required is True


def test_completed_terminal_rejects_unaccepted_trailing_row(tmp_path) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("2026-08-27T12:00:00+00:00,0.012,110,100,105,10,833.3,0.0012,99\n")

    with pytest.raises(ConductivityRunFormatError, match="unaccepted trailing"):
        read_conductivity_run(path)


def test_terminal_cannot_publish_row_without_checkpoint(tmp_path) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_point(_point())
    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if "run_checkpoint" not in line]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ConductivityRunFormatError, match="without its durable checkpoint"):
        read_conductivity_run(path)


def test_durable_header_without_start_cannot_fall_back_to_legacy(tmp_path) -> None:
    path = tmp_path / "run.csv"
    path.write_text(
        "timestamp_utc,P_W,T_hot_K,T_cold_K,T_avg_K,dT_K,R_KW,G_WK,settled_pct\n"
        "2026-08-27T12:00:00+00:00,0.012,110,100,105,10,833.3,0.0012,99\n",
        encoding="utf-8",
    )

    with pytest.raises(ConductivityRunFormatError, match="no start authority"):
        read_conductivity_run(path)


def test_binding_snapshot_distinguishes_exact_experiment_from_explicit_absence(tmp_path) -> None:
    bound_path = tmp_path / "bound.csv"
    bound = ConductivityRunWriter(
        bound_path,
        run_id="bound-run",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    bound.append_binding("experiment-a")
    bound.close()

    bound_snapshot = read_conductivity_run(bound_path)
    assert bound_snapshot.binding_recorded is True
    assert bound_snapshot.bound_experiment_id == "experiment-a"

    unbound_path = tmp_path / "unbound.csv"
    unbound = ConductivityRunWriter(
        unbound_path,
        run_id="unbound-run",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    unbound.append_binding(None)
    unbound.close()

    unbound_snapshot = read_conductivity_run(unbound_path)
    assert unbound_snapshot.binding_recorded is True
    assert unbound_snapshot.bound_experiment_id is None


def test_writer_refuses_binding_after_a_point_append_started(tmp_path) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_point(_point())

    with pytest.raises(RuntimeError, match="after a point append has started"):
        writer.append_binding("experiment-a")


def test_reader_and_manager_reject_binding_forged_after_first_point(tmp_path) -> None:
    path = tmp_path / "forged.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_binding("experiment-a")
    writer.append_point(_point())
    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))

    lines = path.read_text(encoding="utf-8").splitlines()
    binding = next(line for line in lines if "conductivity_run_binding" in line)
    lines.remove(binding)
    checkpoint_index = next(index for index, line in enumerate(lines) if "conductivity_run_checkpoint" in line)
    lines.insert(checkpoint_index + 1, binding)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ConductivityRunFormatError, match="must precede every point effect"):
        read_conductivity_run(path)

    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    record = _autosweep_record(
        path,
        source_run_id="run-1",
        status="COMPLETED",
        point_count=1,
        experiment_id="experiment-a",
    )

    assert manager._collect_conductivity_rows([record]) == []


def test_checkpoint_real_fsync_then_raise_keeps_point_unaccepted(tmp_path, monkeypatch) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    real_fsync = os.fsync
    fsync_calls = 0

    def _fail_after_checkpoint_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        real_fsync(fd)
        if fsync_calls == 2:
            raise OSError("deterministic post-checkpoint-fsync failure")

    monkeypatch.setattr(module.os, "fsync", _fail_after_checkpoint_fsync)
    with pytest.raises(OSError, match="post-checkpoint-fsync"):
        writer.append_point(_point())

    assert writer.accepted_point_count == 0
    assert "0.012" in path.read_text(encoding="utf-8")
    assert '"accepted_point_count":1' in path.read_text(encoding="utf-8")

    monkeypatch.setattr(module.os, "fsync", real_fsync)
    writer.append_terminal(
        "FAILED",
        finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC),
        error="checkpoint acknowledgement unavailable",
        trailing_write_outcome="indeterminate",
    )
    snapshot = read_conductivity_run(path)
    assert snapshot.raw_row_count == 1
    assert snapshot.checkpoint_count == 1
    assert snapshot.accepted_point_count == 0
    assert snapshot.rows == ()
    assert snapshot.status == "FAILED"


def test_accepted_count_moves_only_after_checkpoint_fsync(tmp_path, monkeypatch) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    real_fsync = os.fsync
    observed_counts: list[int] = []

    def _observe_count(fd: int) -> None:
        observed_counts.append(writer.accepted_point_count)
        real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", _observe_count)
    writer.append_point(_point())

    assert observed_counts == [0, 0]
    assert writer.accepted_point_count == 1
    writer.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor semantics")
def test_writer_fsyncs_parent_directory_after_file_creation(tmp_path, monkeypatch) -> None:
    path = tmp_path / "new-parent" / "nested" / "run.csv"
    real_fsync = os.fsync
    effects: list[str] = []

    def _observe_descriptor(fd: int) -> None:
        effects.append("dir" if module.stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", _observe_descriptor)
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.close()

    assert effects[-2:] == ["file", "dir"]
    assert effects.count("dir") >= 3


@pytest.mark.skipif(os.name != "nt", reason="Windows directory fsync compatibility")
def test_directory_fsync_is_a_safe_noop_on_windows(tmp_path, monkeypatch) -> None:
    def _unexpected_open(*_args, **_kwargs):
        raise AssertionError("Windows must not try to open a directory descriptor")

    monkeypatch.setattr(module.os, "open", _unexpected_open)
    module._fsync_directory(tmp_path)


def test_running_attachment_and_checkpoint_survive_manager_restart(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    experiment = manager.create_experiment("Thermal run", "Operator")
    started_at = datetime(2026, 8, 27, 12, tzinfo=UTC)
    path = tmp_path / "run.csv"
    parameters = _bound_parameters()
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=started_at,
        parameters=parameters,
    )
    record = manager.attach_run_record(
        experiment_id=experiment.experiment_id,
        source_tab="conductivity",
        source_module="conductivity_panel",
        run_type="autosweep",
        status="RUNNING",
        source_run_id="run-1",
        started_at=started_at,
        parameters=parameters,
        result_summary={"point_count": 0, "recovery_required": True},
        artifact_paths=[str(path)],
    )
    assert record is not None
    writer.append_binding(experiment.experiment_id)
    writer.append_point(_point())
    writer.close()

    restarted = ExperimentManager(manager_root, instruments)
    restored_records = restarted.list_run_records(experiment_id=experiment.experiment_id)
    assert len(restored_records) == 1
    assert restored_records[0].status == "RUNNING"
    snapshot = read_conductivity_run(path)
    assert snapshot.status == "RUNNING"
    assert snapshot.recovery_required is True
    assert snapshot.accepted_point_count == 1
    assert snapshot.bound_experiment_id == experiment.experiment_id
    assert restarted._collect_conductivity_rows(restored_records) == [_identified_row()]


def _autosweep_record(
    path,
    *,
    source_run_id: str,
    status: str,
    point_count: int | None,
    record_id: str = "experiment:run",
    experiment_id: str = "experiment-a",
    parameters: dict[str, object] | None = None,
) -> RunRecord:
    summary = {} if point_count is None else {"point_count": point_count}
    return RunRecord(
        record_id=record_id,
        source_run_id=source_run_id,
        source_tab="conductivity",
        source_module="conductivity_panel",
        run_type="autosweep",
        status=status,
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC),
        parameters=dict(_bound_parameters() if parameters is None else parameters),
        result_summary=summary,
        artifact_paths=(str(path),),
        experiment_context={"experiment_id": experiment_id},
    )


def test_manager_requires_matching_descriptor_identity_and_keeps_it_in_derived_table(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    parameters = _bound_parameters()
    path = tmp_path / "identified.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="identified-run",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=parameters,
    )
    writer.append_binding("experiment-a")
    writer.append_point(_point())
    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    record = _autosweep_record(
        path,
        source_run_id="identified-run",
        status="COMPLETED",
        point_count=1,
        parameters=parameters,
    )

    rows = manager._collect_conductivity_rows([record])
    assert len(rows) == 1
    assert rows[0]["power_instrument_id"] == "Keithley_1"
    assert rows[0]["power_channel_id"] == "Keithley_1/smua/power"
    assert rows[0]["hot_instrument_id"] == "LakeShore_1"
    assert rows[0]["hot_channel_id"] == "Т1"
    assert rows[0]["cold_channel_id"] == "Т2"
    assert rows[0]["power_descriptor_hash"].startswith("sha256:")
    assert rows[0]["hot_descriptor_revision"] == 1

    table = tmp_path / "conductivity.csv"
    manager._write_conductivity_table(table, rows)
    header, values = list(csv.reader(table.open(encoding="utf-8", newline="")))
    assert "power_descriptor_hash" in header
    assert "hot_descriptor_hash" in header
    assert "cold_descriptor_hash" in header
    assert values[header.index("hot_channel_id")] == "Т1"

    tampered = json.loads(json.dumps(parameters, ensure_ascii=False))
    tampered["bound_descriptors"]["temperatures"][0]["descriptor_hash"] = "sha256:" + "0" * 64
    mismatched = _autosweep_record(
        path,
        source_run_id="identified-run",
        status="COMPLETED",
        point_count=1,
        parameters=tampered,
    )
    assert manager._collect_conductivity_rows([mismatched]) == []


def test_manager_rejects_non_descriptor_parameter_mismatch(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    parameters = _bound_parameters()
    path = tmp_path / "parameter-mismatch.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="parameter-mismatch-run",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=parameters,
    )
    writer.append_binding("experiment-a")
    writer.append_point(_point())
    writer.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    record_parameters = json.loads(json.dumps(parameters, ensure_ascii=False))
    record_parameters["power_values_w"] = [0.024]
    mismatched = _autosweep_record(
        path,
        source_run_id="parameter-mismatch-run",
        status="COMPLETED",
        point_count=1,
        parameters=record_parameters,
    )

    assert manager._collect_conductivity_rows([mismatched]) == []


def test_manager_skips_csv_parser_error_without_aborting_other_artifacts(tmp_path, caplog) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    malformed = tmp_path / "oversized.csv"
    malformed.write_text(
        "T_avg_K,G_WK,R_KW\n" + "9" * 128 + ",0.0012,833.3\n",
        encoding="utf-8",
    )
    record = _autosweep_record(
        malformed,
        source_run_id="legacy-parser-error",
        status="COMPLETED",
        point_count=1,
    )
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(32)
        assert manager._collect_conductivity_rows([record]) == []
    finally:
        csv.field_size_limit(previous_limit)
    assert "Failed to parse autosweep artifact" in caplog.text


def test_manager_rejects_durable_identity_status_count_and_duplicate_conflicts(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)

    first_path = tmp_path / "first.csv"
    first = ConductivityRunWriter(
        first_path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=_bound_parameters(),
    )
    first.append_binding("experiment-a")
    first.append_point(_point())
    first.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    valid = _autosweep_record(first_path, source_run_id="run-1", status="COMPLETED", point_count=1)
    expected = [_identified_row()]
    assert manager._collect_conductivity_rows([valid]) == expected
    assert manager._collect_conductivity_rows([valid, valid]) == expected

    identity_mismatch = _autosweep_record(
        first_path,
        source_run_id="other-run",
        status="COMPLETED",
        point_count=1,
    )
    status_mismatch = _autosweep_record(
        first_path,
        source_run_id="run-1",
        status="FAILED",
        point_count=1,
    )
    count_mismatch = _autosweep_record(
        first_path,
        source_run_id="run-1",
        status="COMPLETED",
        point_count=0,
    )
    assert manager._collect_conductivity_rows([identity_mismatch]) == []
    assert manager._collect_conductivity_rows([status_mismatch]) == []
    assert manager._collect_conductivity_rows([count_mismatch]) == []

    second_path = tmp_path / "second.csv"
    second = ConductivityRunWriter(
        second_path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=_bound_parameters(),
    )
    second.append_binding("experiment-a")
    second.append_point(_point())
    second.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    duplicate_identity = _autosweep_record(
        second_path,
        source_run_id="run-1",
        status="COMPLETED",
        point_count=1,
        record_id="experiment:duplicate",
    )
    assert manager._collect_conductivity_rows([valid, duplicate_identity]) == expected


def test_manager_rejects_missing_or_cross_experiment_durable_binding(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)

    bound_path = tmp_path / "bound.csv"
    bound = ConductivityRunWriter(
        bound_path,
        run_id="run-bound",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=_bound_parameters(),
    )
    bound.append_binding("experiment-a")
    bound.append_point(_point())
    bound.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    cross_experiment = _autosweep_record(
        bound_path,
        source_run_id="run-bound",
        status="COMPLETED",
        point_count=1,
        experiment_id="experiment-b",
    )

    unbound_path = tmp_path / "unbound.csv"
    unbound = ConductivityRunWriter(
        unbound_path,
        run_id="run-unbound",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters=_bound_parameters(),
    )
    unbound.append_point(_point())
    unbound.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    missing_binding = _autosweep_record(
        unbound_path,
        source_run_id="run-unbound",
        status="COMPLETED",
        point_count=1,
        experiment_id="experiment-a",
    )

    assert manager._collect_conductivity_rows([cross_experiment]) == []
    assert manager._collect_conductivity_rows([missing_binding]) == []


def test_manager_legacy_csv_rule_is_finite_rows_with_resolved_path_dedupe(tmp_path) -> None:
    manager_root = tmp_path / "manager"
    manager_root.mkdir()
    instruments = manager_root / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_root, instruments)
    path = tmp_path / "legacy.csv"
    path.write_text(
        "T_avg_K,G_WK,R_KW\n105.0,0.0012,833.3333333333334\nnan,0.0012,833.3333333333334\n",
        encoding="utf-8",
    )
    legacy = _autosweep_record(
        path,
        source_run_id="legacy-identity-is-not-asserted",
        status="COMPLETED",
        point_count=99,
    )
    expected = [
        {
            "temperature_k": 105.0,
            "conductance_wk": 0.0012,
            "resistance_kw": pytest.approx(833.3333333333334),
        }
    ]
    assert manager._collect_conductivity_rows([legacy]) == expected
    assert manager._collect_conductivity_rows([legacy, legacy]) == expected


def test_checkpoint_before_its_row_is_not_a_recoverable_prefix(tmp_path) -> None:
    path = tmp_path / "run.csv"
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
        parameters={},
    )
    writer.append_point(_point())
    writer.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    checkpoint = next(line for line in lines if "conductivity_run_checkpoint" in line)
    row = next(line for line in lines if line.startswith("2026-08-27T12:00:00"))
    reordered = [line for line in lines if line not in {checkpoint, row}]
    reordered.extend([checkpoint, row])
    path.write_text("\n".join(reordered) + "\n", encoding="utf-8")

    snapshot = read_conductivity_run(path)
    assert snapshot.status == "RUNNING"
    assert snapshot.recovery_required is True
    assert snapshot.raw_row_count == 1
    assert snapshot.checkpoint_count == 0
    assert snapshot.accepted_point_count == 0
    assert snapshot.rows == ()
