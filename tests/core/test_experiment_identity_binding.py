from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cryodaq.core.experiment import (
    ExperimentIdentityError,
    ExperimentManager,
)


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.safe_dump({"instruments": []}), encoding="utf-8")
    return path


@pytest.fixture()
def templates_dir(tmp_path: Path) -> Path:
    root = tmp_path / "templates"
    root.mkdir()
    (root / "custom.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "custom",
                "name": "Custom",
                "sections": ["setup"],
                "report_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


def _uuid(hex_value: str) -> SimpleNamespace:
    return SimpleNamespace(hex=hex_value)


def _assert_no_experiment_row(data_dir: Path, experiment_id: str) -> None:
    for db_path in data_dir.glob("data_*.db"):
        conn = sqlite3.connect(db_path)
        try:
            table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'experiments'").fetchone()
            if table is not None:
                count = conn.execute(
                    "SELECT COUNT(*) FROM experiments WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()[0]
                assert count == 0
        finally:
            conn.close()


def test_live_and_retroactive_creation_share_global_collision_reservation(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "1" * 32
    second = "2" * 32
    generated = iter((_uuid(first), _uuid(first), _uuid(second)))
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: next(generated))

    live_id = manager.start_experiment(
        "Live",
        "Operator",
        template_id="custom",
        start_time="2026-01-01T00:00:00+00:00",
    )
    retro = manager.create_retroactive_experiment(
        template_id="custom",
        title="Retro",
        operator="Operator",
        start_time="2026-02-01T00:00:00+00:00",
        end_time="2026-02-01T01:00:00+00:00",
    )

    assert live_id == first
    assert retro.experiment_id == second
    assert (manager.data_dir / "experiments" / first / "metadata.json").is_file()
    assert (manager.data_dir / "experiments" / second / "metadata.json").is_file()


def test_restart_retries_existing_identity_deterministically(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "a" * 32
    second = "b" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(first))
    initial = ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)
    initial.create_retroactive_experiment(
        template_id="custom",
        title="First",
        operator="Operator",
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T01:00:00+00:00",
    )

    generated = iter((_uuid(first), _uuid(second)))
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: next(generated))
    restarted = ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)
    created = restarted.create_retroactive_experiment(
        template_id="custom",
        title="Second",
        operator="Operator",
        start_time="2026-02-01T00:00:00+00:00",
        end_time="2026-02-01T01:00:00+00:00",
    )

    assert created.experiment_id == second
    assert {entry.experiment_id for entry in restarted.list_archive_entries()} == {first, second}


def test_collision_retry_is_bounded_and_leaves_no_new_authority(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision = "c" * 32
    occupied = manager.data_dir / "experiments" / collision
    occupied.mkdir(parents=True)
    marker = occupied / "owner.txt"
    marker.write_text("existing", encoding="utf-8")
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(collision))

    with pytest.raises(RuntimeError, match="32 attempts"):
        manager.start_experiment("Collision", "Operator", template_id="custom")

    assert marker.read_text(encoding="utf-8") == "existing"
    assert manager.active_experiment is None
    _assert_no_experiment_row(manager.data_dir, collision)


@pytest.mark.parametrize(
    "invalid_id",
    [
        None,
        True,
        1,
        b"a" * 32,
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "../" + "a" * 29,
        "a/b" + "a" * 29,
        "a\\b" + "a" * 29,
        "C:\\" + "a" * 29,
        "/" + "a" * 31,
        "a" * 31 + "\x00",
        "e\u0301" + "a" * 30,
        "\u0430" + "a" * 31,
    ],
)
def test_noncanonical_id_rejects_before_any_path_resolution(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
    invalid_id: object,
) -> None:
    monkeypatch.setattr(
        manager,
        "_trusted_artifacts_root",
        lambda **_kwargs: pytest.fail("path resolution ran before identity validation"),
    )

    with pytest.raises(ExperimentIdentityError, match="32 lowercase hexadecimal"):
        manager._artifact_dir(invalid_id)  # type: ignore[arg-type]


def test_state_directory_and_metadata_identity_must_match(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_id = "1" * 32
    metadata_id = "2" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(state_id))
    manager = ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)
    manager.start_experiment("Mismatch", "Operator", template_id="custom")
    metadata_path = tmp_path / "experiments" / state_id / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["experiment"]["experiment_id"] = metadata_id
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExperimentIdentityError, match="do not match"):
        ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


def test_archive_rejects_directory_a_metadata_b(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_id = "3" * 32
    payload_id = "4" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(directory_id))
    created = manager.create_retroactive_experiment(
        template_id="custom",
        title="Mismatch",
        operator="Operator",
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T01:00:00+00:00",
    )
    payload = json.loads(created.metadata_path.read_text(encoding="utf-8"))
    payload["experiment"]["experiment_id"] = payload_id
    created.metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    assert manager.list_archive_entries() == []


@pytest.mark.parametrize("boundary", ["_write_start", "_write_artifact", "_set_active"])
def test_live_creation_rolls_back_after_each_committed_mutation_boundary(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    experiment_id = "5" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(experiment_id))
    original = getattr(manager, boundary)

    def commit_then_fail(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        raise OSError(f"injected failure after {boundary}")

    monkeypatch.setattr(manager, boundary, commit_then_fail)
    with pytest.raises(OSError, match="injected failure"):
        manager.start_experiment("Failure", "Operator", template_id="custom")

    assert manager.active_experiment is None
    assert not (manager.data_dir / "experiments" / experiment_id).exists()
    assert not (manager.data_dir / "experiment_state.json").exists()
    _assert_no_experiment_row(manager.data_dir, experiment_id)


def test_retroactive_creation_rolls_back_after_end_update(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = "6" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(experiment_id))
    original = manager._write_end

    def commit_then_fail(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        raise OSError("injected failure after retroactive update")

    monkeypatch.setattr(manager, "_write_end", commit_then_fail)
    with pytest.raises(OSError, match="retroactive update"):
        manager.create_retroactive_experiment(
            template_id="custom",
            title="Failure",
            operator="Operator",
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T01:00:00+00:00",
        )

    assert not (manager.data_dir / "experiments" / experiment_id).exists()
    _assert_no_experiment_row(manager.data_dir, experiment_id)


def test_caller_supplied_artifact_path_cannot_escape_identity_root(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = "7" * 32
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(experiment_id))
    created = manager.create_experiment("Bound", "Operator", template_id="custom")
    outside = manager.data_dir / "outside"
    forged = replace(created, artifact_dir=outside, metadata_path=outside / "metadata.json")

    with pytest.raises(ExperimentIdentityError, match="artifact path"):
        manager._write_artifact(forged)
    with pytest.raises(ExperimentIdentityError, match="artifact path"):
        manager._build_archive_snapshot(forged, [])

    assert not outside.exists()


def test_symlinked_identity_collision_fails_loud(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = "8" * 32
    root = manager.data_dir / "experiments"
    root.mkdir()
    outside = manager.data_dir / "outside"
    outside.mkdir()
    try:
        (root / experiment_id).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable; no symlink coverage claimed: {exc}")
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(experiment_id))

    with pytest.raises(ExperimentIdentityError, match="reparse"):
        manager.start_experiment("Escape", "Operator", template_id="custom")

    assert not (outside / "metadata.json").exists()


def test_symlinked_artifacts_root_rejects_creation(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside-root"
    outside.mkdir()
    try:
        (tmp_path / "experiments").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable; no root-symlink coverage claimed: {exc}")
    manager = ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid("9" * 32))

    with pytest.raises(ExperimentIdentityError, match="non-reparse"):
        manager.start_experiment("Escape", "Operator", template_id="custom")

    assert list(outside.iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction semantics only")
def test_windows_junction_identity_collision_fails_loud(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = "d" * 32
    root = manager.data_dir / "experiments"
    root.mkdir()
    outside = manager.data_dir / "junction-target"
    outside.mkdir()
    junction = root / experiment_id
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation unavailable; no junction coverage claimed")
    monkeypatch.setattr("cryodaq.core.experiment.uuid.uuid4", lambda: _uuid(experiment_id))
    try:
        with pytest.raises(ExperimentIdentityError, match="reparse"):
            manager.start_experiment("Escape", "Operator", template_id="custom")
        assert not (outside / "metadata.json").exists()
    finally:
        os.rmdir(junction)
