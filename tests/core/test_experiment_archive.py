from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.core.experiment import ExperimentManager
from cryodaq.report_state import (
    build_current_manifest,
    new_running_state,
    promote_generation,
    terminal_state,
    write_report_state,
)


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(
        yaml.dump({"instruments": [{"name": "k1", "type": "keithley_2604b", "resource": "MOCK"}]}),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def templates_dir(tmp_path: Path) -> Path:
    root = tmp_path / "experiment_templates"
    root.mkdir()
    (root / "thermal_conductivity.yaml").write_text(
        yaml.dump(
            {
                "id": "thermal_conductivity",
                "name": "Thermal Conductivity",
                "sections": ["setup"],
                "report_enabled": True,
                "report_sections": ["title_page"],
            }
        ),
        encoding="utf-8",
    )
    (root / "cooldown_test.yaml").write_text(
        yaml.dump(
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup"],
                "report_enabled": True,
                "report_sections": ["title_page"],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


async def test_archive_discovers_experiments(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_a = manager.start_experiment(
        name="Run A",
        title="Run A",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_a, end_time="2026-03-16T11:00:00+00:00")
    exp_b = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Run B",
        operator="Petrov",
        sample="Al",
        start_time="2026-03-15T10:00:00+00:00",
        end_time="2026-03-15T11:00:00+00:00",
    )

    entries = manager.list_archive_entries()

    ids = [entry.experiment_id for entry in entries]
    assert exp_a in ids
    assert exp_b.experiment_id in ids
    assert entries[0].start_time >= entries[-1].start_time


async def test_archive_excludes_active_experiment_card(manager: ExperimentManager) -> None:
    exp_id = manager.start_experiment(
        name="Run Active",
        title="Run Active",
        operator="Ivanov",
        template_id="thermal_conductivity",
        start_time="2026-03-16T10:00:00+00:00",
    )

    entries = manager.list_archive_entries()

    assert [entry.experiment_id for entry in entries] == []
    assert manager.get_archive_item(exp_id) is None


async def test_archive_filters_and_sorts(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_a = manager.start_experiment(
        name="Thermal",
        title="Thermal",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_a, end_time="2026-03-16T11:00:00+00:00")
    exp_b = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Cooldown",
        operator="Petrov",
        sample="Al",
        start_time="2026-03-15T10:00:00+00:00",
        end_time="2026-03-15T11:00:00+00:00",
    )
    report_path = tmp_path / "experiments" / exp_b.experiment_id / "reports"
    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "report_editable.docx").write_text("dummy", encoding="utf-8")

    entries = manager.list_archive_entries(template_id="cooldown_test", report_present=True)

    assert len(entries) == 1
    assert entries[0].experiment_id == exp_b.experiment_id
    assert entries[0].report_authority == "legacy"

    operator_sorted = manager.list_archive_entries(sort_by="operator", descending=False)
    assert [entry.operator for entry in operator_sorted] == ["Ivanov", "Petrov"]


async def test_archive_finalize_leaves_report_for_eventual_reconciliation(
    manager: ExperimentManager,
) -> None:
    exp_id = manager.start_experiment(
        name="No Report",
        title="No Report",
        operator="Sidorov",
        template_id="thermal_conductivity",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T11:00:00+00:00")

    entry = manager.list_archive_entries()[0]
    assert entry.report_present is False
    assert entry.docx_path is None
    assert entry.pdf_path is None
    assert entry.report_authority == "none"


async def test_archive_manifest_authority_ignores_stale_canonical_files(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Manifest authority",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    root = tmp_path / "experiments" / created.experiment_id
    generation_id = "generation-token-0001"
    staging = root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"selected")
    manifest = build_current_manifest(
        root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(root, generation_id, manifest)
    (root / "reports" / "report_editable.docx").write_bytes(b"stale")

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_authority == "manifest"
    assert entry.report_generation_id == generation_id
    assert entry.docx_path is not None
    assert "generations" in entry.docx_path.parts


async def test_archive_dangling_manifest_symlink_is_invalid_not_legacy(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Dangling manifest",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    reports = tmp_path / "experiments" / created.experiment_id / "reports"
    reports.mkdir()
    (reports / "report_editable.docx").write_bytes(b"stale")
    (reports / "current_report.json").symlink_to(reports / "missing.json")

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_authority == "invalid"
    assert entry.report_present is False
    assert entry.docx_path is None


async def test_archive_observed_manifest_pointer_race_remains_invalid(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Manifest race",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    monkeypatch.setattr("cryodaq.core.experiment.os.path.lexists", lambda _path: True)
    monkeypatch.setattr("cryodaq.core.experiment.load_current_manifest", lambda _root: None)

    entry = manager.get_archive_item(created.experiment_id)

    assert entry is not None
    assert entry.report_authority == "invalid"
    assert entry.report_present is False


async def test_archive_corrupt_report_state_keeps_card_and_disables_force(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Corrupt state",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    root = tmp_path / "experiments" / created.experiment_id
    state_path = root / "report_state.json"
    state_path.write_bytes(b"{broken")

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_state_status == "INVALID"
    assert entry.report_force_required is False
    assert entry.report_force_context is None
    assert state_path.read_bytes() == b"{broken"


async def test_archive_exposes_bounded_force_confirmation_context(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Poisoned report",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    root = tmp_path / "experiments" / created.experiment_id
    running = new_running_state(
        created.experiment_id,
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=5,
        max_attempts=5,
    )
    failed = terminal_state(
        running,
        owner_token="owner-token-valid-0001",
        succeeded=False,
        error_code="render_failed",
        error_text="failed",
    )
    write_report_state(root, failed)

    payload = manager.get_archive_item(created.experiment_id).to_payload()  # type: ignore[union-attr]
    assert payload["report_force_required"] is True
    assert len(payload["report_force_context"]) == 64
    assert "owner_token" not in payload
    assert "source_fingerprint" not in payload


def test_finalize_order_has_no_renderer_step(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp_id = manager.start_experiment(
        name="Ordered finalize",
        operator="Sidorov",
        template_id="thermal_conductivity",
        start_time="2026-03-16T10:00:00+00:00",
    )
    events: list[str] = []
    monkeypatch.setattr(manager, "list_run_records", lambda **_kwargs: [])
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
    monkeypatch.setattr(manager, "_write_end", lambda _finished: events.append("metadata"))
    monkeypatch.setattr(
        manager,
        "_write_artifact",
        lambda *_args, **_kwargs: events.append("archive"),
    )
    monkeypatch.setattr(manager, "_clear_active", lambda: events.append("clear"))
    parquet = types.ModuleType("cryodaq.storage.parquet_archive")
    parquet.export_experiment_readings_to_parquet = (  # type: ignore[attr-defined]
        lambda **_kwargs: events.append("parquet")
    )
    monkeypatch.setitem(sys.modules, "cryodaq.storage.parquet_archive", parquet)
    monkeypatch.setitem(sys.modules, "cryodaq.reporting.generator", None)

    finished = manager.finalize_experiment(
        exp_id,
        end_time="2026-03-16T11:00:00+00:00",
    )

    assert finished.experiment_id == exp_id
    # Terminal truth and authority release are committed before best-effort
    # derivative Parquet export. A slow or failed export must not leave the
    # experiment looking RUNNING after its terminal metadata was published.
    assert events == ["metadata", "archive", "clear", "parquet"]


async def test_archive_normalizes_none_text_fields(manager: ExperimentManager) -> None:
    artifact_dir = manager.data_dir / "experiments" / "exp-bad"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": None,
                    "title": None,
                    "template_id": None,
                    "operator": None,
                    "sample": None,
                    "status": None,
                    "start_time": "2026-03-16T10:00:00+00:00",
                    "end_time": None,
                    "notes": None,
                    "report_enabled": True,
                    "retroactive": False,
                },
                "template": {"id": None, "name": None},
            }
        ),
        encoding="utf-8",
    )

    entry = manager.list_archive_entries()[0]

    assert entry.experiment_id == ""
    assert entry.title == ""
    assert entry.template_id == ""
    assert entry.template_name == ""
    assert entry.operator == ""
    assert entry.sample == ""
    assert entry.status == ""
    assert entry.notes == ""


async def test_archive_rejects_symlinked_experiment_escape(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-experiment"
    reports = outside / "reports"
    reports.mkdir(parents=True)
    (reports / "report_editable.docx").write_bytes(b"outside")
    (outside / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": "evil",
                    "status": "COMPLETED",
                    "start_time": "2026-03-16T10:00:00+00:00",
                },
                "template": {},
            }
        ),
        encoding="utf-8",
    )
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    (experiments / "evil").symlink_to(outside, target_is_directory=True)

    assert all(entry.experiment_id != "evil" for entry in manager.list_archive_entries())


async def test_archive_rejects_symlinked_experiments_root(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-experiments-root"
    experiment = outside / "evil"
    reports = experiment / "reports"
    reports.mkdir(parents=True)
    (reports / "report_editable.docx").write_bytes(b"outside")
    (experiment / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": "evil",
                    "status": "COMPLETED",
                    "start_time": "2026-03-16T10:00:00+00:00",
                },
                "template": {},
            }
        ),
        encoding="utf-8",
    )
    experiments = tmp_path / "experiments"
    experiments.symlink_to(outside, target_is_directory=True)

    assert manager.list_archive_entries() == []


async def test_archive_rejects_escaping_current_manifest(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Unsafe manifest",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    reports = tmp_path / "experiments" / created.experiment_id / "reports"
    reports.mkdir(exist_ok=True)
    payload = {
        "schema": 1,
        "experiment_id": created.experiment_id,
        "generation_id": "generation-token-0001",
        "source_fingerprint": "sha256:" + "1" * 64,
        "created_at": 1.0,
        "report": {
            "docx_path": "../../outside.docx",
            "pdf_path": None,
            "assets_dir": "../../outside-assets",
            "sections": [],
            "skipped": False,
            "reason": "",
        },
        "artifacts": [],
    }
    atomic_write_text(reports / "current_report.json", json.dumps(payload))

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_present is False
    assert entry.docx_path is None
    assert entry.report_authority == "invalid"


async def test_archive_rejects_symlinked_canonical_report(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Unsafe canonical report",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"outside")
    reports = tmp_path / "experiments" / created.experiment_id / "reports"
    reports.mkdir()
    (reports / "report_editable.docx").symlink_to(outside)

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_present is False
    assert entry.docx_path is None


async def test_archive_rejects_symlinked_reports_directory(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    created = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Unsafe reports directory",
        operator="Operator",
        start_time="2026-03-16T10:00:00+00:00",
        end_time="2026-03-16T11:00:00+00:00",
    )
    outside = tmp_path / "outside-reports"
    outside.mkdir()
    (outside / "report_editable.docx").write_bytes(b"outside")
    experiment_root = tmp_path / "experiments" / created.experiment_id
    (experiment_root / "reports").symlink_to(outside, target_is_directory=True)

    entry = manager.get_archive_item(created.experiment_id)
    assert entry is not None
    assert entry.report_present is False
    assert entry.docx_path is None
