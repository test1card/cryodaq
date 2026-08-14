from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import openpyxl

from cryodaq.storage.xlsx_export import XLSXExporter


def _database(path: Path, *, channel: str, descriptor_hash: str | None, legacy: bool) -> None:
    columns = "timestamp REAL, instrument_id TEXT, channel TEXT, value REAL, unit TEXT, status TEXT"
    if not legacy:
        columns += ", descriptor_hash TEXT"
    values = (
        datetime.fromisoformat(path.stem.removeprefix("data_")).replace(tzinfo=UTC).timestamp(),
        "i",
        channel,
        1.0,
        "K",
        "ok",
    )
    if not legacy:
        values += (descriptor_hash,)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"CREATE TABLE readings ({columns})")
        conn.execute(f"INSERT INTO readings VALUES ({','.join('?' for _ in values)})", values)
        # closing() closes the handle; it does NOT commit.
        conn.commit()


def test_xlsx_exports_descriptor_hash_and_leaves_old_archive_empty(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    descriptor_hash = "sha256:" + "a" * 64
    _database(data_dir / "data_2026-03-14.db", channel="CH_NEW", descriptor_hash=descriptor_hash, legacy=False)
    _database(data_dir / "data_2026-03-15.db", channel="CH_OLD", descriptor_hash=None, legacy=True)

    output_path = tmp_path / "identity.xlsx"
    XLSXExporter(data_dir).export(output_path)

    ws = openpyxl.load_workbook(output_path)["Данные"]
    header = [cell.value for cell in ws[1]]
    assert header == [
        "Время",
        "CH_NEW",
        "CH_NEW descriptor_hash",
        "CH_OLD",
        "CH_OLD descriptor_hash",
    ], f"descriptor_hash export columns missing or misplaced: {header}"
    assert ws.cell(row=2, column=3).value == descriptor_hash
    assert ws.cell(row=3, column=5).value is None, "old archive descriptor_hash cell must be empty"
