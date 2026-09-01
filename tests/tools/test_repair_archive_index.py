"""The migration may declare absence only where absence is certain.

Rotation used to write nothing at all for a day that archived no operator
entries. That shape is unambiguous and is what this tool exists to migrate.

Anything else carrying operator fields is not. A half-written entry cannot be
told apart from one whose metadata was lost, and resolving it by deleting the
written fields would convert unknown history into proven absence -- silently,
permanently, and in the one file every read depends on.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "repair_archive_index.py"

BASE = {
    "original_name": "data_2026-05-08.db",
    "archive_path": "year=2026/month=05/data_2026-05-08.parquet",
    "rotated_at": "2026-09-01T03:00:35+00:00",
    "row_count": 10,
    "size_bytes_original": 1,
    "size_bytes_archive": 1,
    "checksum_md5": "0" * 32,
}


def _stand(tmp_path: Path, entry_extra: dict, *, sidecar: bool = False) -> Path:
    archive = tmp_path / "archive" / "year=2026" / "month=05"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "data_2026-05-08.parquet").write_bytes(b"parquet-stub")
    if sidecar:
        (archive / "data_2026-05-08.operator_log.parquet").write_bytes(b"sidecar-stub")
    index = tmp_path / "archive" / "index.json"
    index.write_text(json.dumps({"files": [{**BASE, **entry_extra}]}), encoding="utf-8")
    return index


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), "--data-dir", str(tmp_path), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _entry(index: Path) -> dict:
    return json.loads(index.read_text(encoding="utf-8"))["files"][0]


def test_an_entry_with_no_operator_fields_is_repaired(tmp_path):
    index = _stand(tmp_path, {})
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0, result.stdout
    entry = _entry(index)
    assert entry["operator_log_path"] is None
    assert entry["operator_log_rows"] == 0


@pytest.mark.parametrize(
    "partial",
    [
        {"operator_log_rows": 4},
        {"operator_log_path": "year=2026/month=05/data_2026-05-08.operator_log.parquet"},
        {"operator_log_rows": 4, "operator_log_schema": "operator_log_v2"},
        {"operator_log_checksum_md5": "1" * 32},
    ],
)
def test_a_partial_entry_is_never_declared_empty(tmp_path, partial):
    index = _stand(tmp_path, partial)
    before = _entry(index)
    result = _run(tmp_path, "--apply")
    assert "PARTIAL" in result.stdout
    assert _entry(index) == before, "the tool rewrote an entry whose history is unknown"


def test_an_unindexed_sidecar_is_reported_not_erased(tmp_path):
    index = _stand(tmp_path, {}, sidecar=True)
    before = _entry(index)
    result = _run(tmp_path, "--apply")
    assert "CONFLICTED" in result.stdout
    assert _entry(index) == before


def test_an_already_declared_entry_is_left_alone(tmp_path):
    index = _stand(tmp_path, {"operator_log_path": None, "operator_log_rows": 0})
    before = _entry(index)
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0, result.stdout
    assert "already explicit:   1" in result.stdout
    assert _entry(index) == before


def test_a_dry_run_writes_nothing(tmp_path):
    index = _stand(tmp_path, {})
    before = _entry(index)
    _run(tmp_path)
    assert _entry(index) == before
