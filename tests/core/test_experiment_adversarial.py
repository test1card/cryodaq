from __future__ import annotations

import concurrent.futures
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.core.experiment import (
    ExperimentIdentityMismatchError,
    ExperimentManager,
    ExperimentStatus,
    RunRecord,
)
from cryodaq.storage._sqlite import sqlite3


def _manager(data_dir: Path) -> ExperimentManager:
    instruments = data_dir / "instruments.yaml"
    instruments.parent.mkdir(parents=True, exist_ok=True)
    instruments.write_text("instruments: []\n", encoding="utf-8")
    return ExperimentManager(data_dir, instruments)


def test_concurrent_managers_persist_exactly_one_running_experiment(tmp_path: Path) -> None:
    first = _manager(tmp_path)
    second = _manager(tmp_path)
    barrier = threading.Barrier(2)

    def create(manager: ExperimentManager, name: str) -> str:
        barrier.wait(timeout=5)
        return manager.create_experiment(name, "operator").experiment_id

    outcomes: list[str | BaseException] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, first, "first"), executor.submit(create, second, "second")]
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except BaseException as exc:  # exact loser type is platform SQLite dependent
                outcomes.append(exc)

    winners = [item for item in outcomes if isinstance(item, str)]
    losers = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    db_path = next(tmp_path.glob("data_????-??-??.db"))
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT experiment_id FROM experiments WHERE status = 'RUNNING'").fetchall()
    assert rows == [(winners[0],)]
    assert not (tmp_path / "experiment_transition.json").exists()


def test_delayed_phase_command_cannot_mutate_replacement_experiment(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.create_experiment("first", "operator")
    manager.finalize_experiment(first.experiment_id)
    second = manager.create_experiment("second", "operator")

    with pytest.raises(ExperimentIdentityMismatchError, match="stale"):
        manager.advance_phase(
            "cooldown",
            expected_experiment_id=first.experiment_id,
        )

    assert manager.active_experiment_id == second.experiment_id
    assert manager.get_current_phase() is None


def test_interrupted_finalize_replays_journal_to_one_terminal_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    active = manager.create_experiment("campaign", "operator")
    monkeypatch.setattr(
        manager,
        "_build_archive_snapshot",
        lambda *_args: {
            "run_records": [],
            "artifact_index": [],
            "result_tables": [],
            "summary_metadata": {},
        },
    )
    original_write_artifact = manager._write_artifact

    def fail_terminal(info, **kwargs):
        if info.status is not ExperimentStatus.RUNNING:
            raise OSError("injected metadata failure")
        return original_write_artifact(info, **kwargs)

    monkeypatch.setattr(manager, "_write_artifact", fail_terminal)
    with pytest.raises(OSError, match="injected metadata failure"):
        manager.finalize_experiment(active.experiment_id)

    journal = tmp_path / "experiment_transition.json"
    assert journal.exists()
    recovered = _manager(tmp_path)
    assert recovered.active_experiment is None
    assert not journal.exists()
    payload = json.loads(
        (tmp_path / "experiments" / active.experiment_id / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["experiment"]["status"] == "COMPLETED"
    db_path = tmp_path / f"data_{active.start_time.date().isoformat()}.db"
    with sqlite3.connect(str(db_path)) as conn:
        status = conn.execute(
            "SELECT status FROM experiments WHERE experiment_id = ?", (active.experiment_id,)
        ).fetchone()
    assert status == ("COMPLETED",)


def test_finalize_rejects_end_before_start_without_partial_transition(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    start = datetime(2026, 7, 18, 12, tzinfo=UTC)
    active = manager.create_experiment("campaign", "operator", start_time=start)

    with pytest.raises(ValueError, match="cannot precede"):
        manager.finalize_experiment(active.experiment_id, end_time=start - timedelta(seconds=1))

    assert manager.active_experiment_id == active.experiment_id
    assert not (tmp_path / "experiment_transition.json").exists()


def test_run_record_payload_never_invents_identity_or_time() -> None:
    with pytest.raises(ValueError, match="must be explicit"):
        RunRecord.from_payload({"source_run_id": "run-1"})
    with pytest.raises(ValueError, match="cannot precede"):
        RunRecord.from_payload(
            {
                "record_id": "record-1",
                "source_run_id": "run-1",
                "started_at": "2026-07-18T12:00:00+00:00",
                "finished_at": "2026-07-18T11:59:59+00:00",
            }
        )


def test_external_run_artifact_is_content_addressed_copy_not_prefix_alias(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    active = manager.create_experiment("campaign", "operator")
    sibling = active.artifact_dir.with_name(f"{active.artifact_dir.name}_evil")
    sibling.mkdir(parents=True)
    source = sibling / "evidence.csv"
    source.write_bytes(b"original evidence")
    record = RunRecord(
        record_id=f"{active.experiment_id}:run-1",
        source_run_id="run-1",
        source_tab="test",
        source_module="test",
        run_type="measurement",
        status="COMPLETED",
        started_at=active.start_time,
        artifact_paths=(str(source),),
    )
    archive_root = active.artifact_dir / "archive"
    records, artifacts = manager._materialize_run_record_artifacts(active, [record], archive_root=archive_root)

    target = Path(records[0].artifact_paths[0])
    digest = hashlib.sha256(b"original evidence").hexdigest()
    assert target.is_relative_to(archive_root)
    assert target.name == f"evidence.{digest[:16]}.csv"
    assert target.read_bytes() == b"original evidence"
    assert artifacts[0]["summary"]["sha256"] == digest
    assert source.stat().st_ino != target.stat().st_ino
    source.write_bytes(b"mutated later")
    assert target.read_bytes() == b"original evidence"


def test_content_address_collision_is_rejected_even_when_size_matches(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    active = manager.create_experiment("campaign", "operator")
    source = tmp_path / "outside.csv"
    source.write_bytes(b"AAAA")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target_dir = active.artifact_dir / "archive" / "runs" / "test" / "run-1"
    target_dir.mkdir(parents=True)
    (target_dir / f"outside.{digest[:16]}.csv").write_bytes(b"BBBB")
    record = RunRecord(
        record_id=f"{active.experiment_id}:run-1",
        source_run_id="run-1",
        source_tab="test",
        source_module="test",
        run_type="measurement",
        status="COMPLETED",
        started_at=active.start_time,
        artifact_paths=(str(source),),
    )

    with pytest.raises(RuntimeError, match="different content"):
        manager._materialize_run_record_artifacts(active, [record], archive_root=active.artifact_dir / "archive")


def test_conductivity_summary_rejects_nonfinite_measurements(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    artifact = tmp_path / "autosweep.csv"
    artifact.write_text(
        "T_avg_K,G_WK,R_KW\n4.2,0.12,8.33\nnan,0.12,8.33\n4.2,inf,8.33\n4.2,0.12,-inf\n",
        encoding="utf-8",
    )
    record = RunRecord(
        record_id="experiment:run-1",
        source_run_id="run-1",
        source_tab="autosweep",
        source_module="test",
        run_type="autosweep",
        status="COMPLETED",
        started_at=datetime(2026, 7, 18, 12, tzinfo=UTC),
        artifact_paths=(str(artifact),),
    )

    assert manager._collect_conductivity_rows([record]) == [
        {
            "temperature_k": 4.2,
            "conductance_wk": 0.12,
            "resistance_kw": 8.33,
        }
    ]


def test_corrupt_active_metadata_cannot_invent_plausible_start_time(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    active = manager.create_experiment("campaign", "operator")
    metadata_path = active.metadata_path
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["experiment"].pop("start_time")
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be explicit"):
        _manager(tmp_path)


def test_corrupt_transition_journal_blocks_startup_without_mutating_evidence(
    tmp_path: Path,
) -> None:
    instruments = tmp_path / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    journal = tmp_path / "experiment_transition.json"
    journal.write_bytes(b'{"schema_version": 1, "operation":')

    with pytest.raises(RuntimeError, match="journal is unreadable"):
        ExperimentManager(tmp_path, instruments)

    assert journal.read_bytes() == b'{"schema_version": 1, "operation":'
