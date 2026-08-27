from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

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
    writer = ConductivityRunWriter(
        path,
        run_id="run-1",
        started_at=started_at,
        parameters={"power_values_w": [0.012]},
    )
    record = manager.attach_run_record(
        experiment_id=experiment.experiment_id,
        source_tab="conductivity",
        source_module="conductivity_panel",
        run_type="autosweep",
        status="RUNNING",
        source_run_id="run-1",
        started_at=started_at,
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
    assert restarted._collect_conductivity_rows(restored_records) == [
        {
            "temperature_k": 105.0,
            "conductance_wk": 0.0012,
            "resistance_kw": pytest.approx(10.0 / 0.012),
        }
    ]


def _autosweep_record(
    path,
    *,
    source_run_id: str,
    status: str,
    point_count: int | None,
    record_id: str = "experiment:run",
    experiment_id: str = "experiment-a",
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
        result_summary=summary,
        artifact_paths=(str(path),),
        experiment_context={"experiment_id": experiment_id},
    )


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
        parameters={},
    )
    first.append_binding("experiment-a")
    first.append_point(_point())
    first.append_terminal("COMPLETED", finished_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC))
    valid = _autosweep_record(first_path, source_run_id="run-1", status="COMPLETED", point_count=1)
    expected = [
        {
            "temperature_k": 105.0,
            "conductance_wk": 0.0012,
            "resistance_kw": pytest.approx(10.0 / 0.012),
        }
    ]
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
        parameters={},
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
        parameters={},
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
        parameters={},
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
