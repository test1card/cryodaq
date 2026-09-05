"""The pre-deploy check must fail on the deploy that actually broke the stand.

`tests/channels/test_descriptor_revision_contract.py` pins the CONTRACT — a
changed descriptor at a reused revision is refused. This pins the TOOL that
applies it to a real stand: reading persisted envelopes out of a day database,
choosing the catalogue the engine would choose, and reporting the offending
field rather than only the exception.

A tool consulted immediately before `kill -TERM` is trusted at the worst
possible moment, so it gets both directions asserted, not just the happy one.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "preflight_descriptor_catalog.py"
_BASE_CATALOGUE = _ROOT / "config" / "channel_descriptors.yaml"


def _write_database(path: Path, descriptors: list[dict]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE channel_descriptors ("
            "descriptor_hash TEXT, channel_id TEXT, instrument_id TEXT, "
            "source_key TEXT, descriptor_revision INTEGER, envelope_json BLOB)"
        )
        for entry in descriptors:
            envelope = {
                "channel_id": entry["channel_id"],
                "descriptor": entry,
                "descriptor_hash": "sha256:unused-by-the-check",
                "descriptor_revision": entry["descriptor_revision"],
                "instrument_id": entry["instrument_id"],
                "schema_version": entry["schema_version"],
                "source_key": entry["source_key"],
            }
            connection.execute(
                "INSERT INTO channel_descriptors VALUES (?,?,?,?,?,?)",
                (
                    envelope["descriptor_hash"],
                    entry["channel_id"],
                    entry["instrument_id"],
                    entry["source_key"],
                    entry["descriptor_revision"],
                    json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _stand(tmp_path: Path, *, mutate=None) -> Path:
    """A root with config/ and data/ shaped the way the tool expects."""

    document = yaml.safe_load(_BASE_CATALOGUE.read_text(encoding="utf-8"))
    persisted = [dict(entry) for entry in document["descriptors"]]

    root = tmp_path / "stand"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    _write_database(root / "data" / "data_2026-09-05.db", persisted)

    if mutate is not None:
        mutate(document)
    (root / "config" / "channel_descriptors.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_TOOL), "--root", str(root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_an_unchanged_catalogue_is_admitted(tmp_path: Path) -> None:
    result = _run(_stand(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_the_deploy_that_broke_the_stand_is_refused(tmp_path: Path) -> None:
    """Т8 visibility flipped, revision left alone — 2026-09-05, 01:33."""

    def flip(document: dict) -> None:
        for entry in document["descriptors"]:
            if entry["channel_id"] == "Т8":
                entry["visible_by_default"] = not entry["visible_by_default"]
                return
        raise AssertionError("Т8 is not in the shipped catalogue")

    result = _run(_stand(tmp_path, mutate=flip))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "reuses an existing revision" in result.stdout
    # The exception alone is not enough; an operator at 01:33 needs the field.
    assert "visible_by_default" in result.stdout
    assert "Т8" in result.stdout
    assert "new descriptor_revision" in result.stdout


def test_the_same_change_one_revision_forward_is_admitted(tmp_path: Path) -> None:
    """The remedy the failing message names must actually work."""

    def flip_and_bump(document: dict) -> None:
        for entry in document["descriptors"]:
            if entry["channel_id"] == "Т8":
                entry["visible_by_default"] = not entry["visible_by_default"]
                entry["descriptor_revision"] += 1
                return

    result = _run(_stand(tmp_path, mutate=flip_and_bump))
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_stand_with_no_day_database_is_not_an_error(tmp_path: Path) -> None:
    """A first-ever start has nothing to conflict with, and must not block."""

    root = tmp_path / "empty"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "config" / "channel_descriptors.yaml").write_text(
        _BASE_CATALOGUE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing to validate against" in result.stdout


@pytest.mark.parametrize("flag", ["--root"])
def test_the_tool_never_opens_the_database_read_write(flag: str) -> None:
    """mode=ro is the whole reason this is safe to run against a live stand."""

    source = _TOOL.read_text(encoding="utf-8")
    assert "mode=ro" in source
    assert 'sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)' in source


# ---------------------------------------------------------------------------
# Identity of what is being certified — review of 2026-09-05
# ---------------------------------------------------------------------------


def _run_explicit(
    *, catalogue: Path | None = None, database: Path | None = None, root: Path
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(_TOOL), "--root", str(root)]
    if catalogue is not None:
        argv += ["--catalogue", str(catalogue)]
    if database is not None:
        argv += ["--database", str(database)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)


def test_an_actively_written_database_outranks_a_quiescent_newer_file(
    tmp_path: Path,
) -> None:
    """WAL commits need not touch the main file, so mtime alone can mislead.

    Reproduces the review finding: a database still accepting committed rows
    was passed over in favour of yesterday's file, because yesterday's got a
    final checkpoint and today's commits were sitting in the -wal.
    """
    import os

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quiescent = data_dir / "data_2026-09-04.db"
    active = data_dir / "data_2026-09-05.db"
    _write_database(quiescent, [])
    _write_database(active, [])

    # The active database's own mtime is OLDER than the quiescent one's...
    os.utime(active, (1_000_000, 1_000_000))
    os.utime(quiescent, (2_000_000, 2_000_000))
    # ...but its WAL carries the recent commits.
    wal = active.with_name(active.name + "-wal")
    wal.write_bytes(b"")
    os.utime(wal, (3_000_000, 3_000_000))

    sys.path.insert(0, str(_ROOT / "tools"))
    try:
        import importlib

        module = importlib.import_module("preflight_descriptor_catalog")
        importlib.reload(module)
        chosen = module._active_day_database(data_dir)
    finally:
        sys.path.pop(0)

    assert chosen == active, (
        f"chose {chosen.name if chosen else None}; the database with live WAL "
        "commits must not lose to a quiescent file with a newer main mtime"
    )


def test_explicit_inputs_are_used_verbatim(tmp_path: Path) -> None:
    """--root binds both sides to one tree; a deploy needs them decoupled."""
    live = tmp_path / "live"
    (live / "config").mkdir(parents=True)
    (live / "data").mkdir()
    _write_database(live / "data" / "data_2026-09-05.db", [])

    candidate_catalogue = tmp_path / "candidate.yaml"
    candidate_catalogue.write_text(_BASE_CATALOGUE.read_text(encoding="utf-8"), encoding="utf-8")

    result = _run_explicit(
        catalogue=candidate_catalogue,
        database=live / "data" / "data_2026-09-05.db",
        root=live,
    )
    assert "candidate.yaml  (explicit)" in result.stdout, result.stdout
    assert "data_2026-09-05.db  (mode=ro, explicit)" in result.stdout, result.stdout
    # Nothing was inferred, so the tool must not hedge.
    assert "an input was inferred" not in result.stdout


def test_an_inferred_input_is_declared_as_a_guess(tmp_path: Path) -> None:
    """The final OK line must not read as stronger than its inputs allow."""
    root = tmp_path / "stand"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "config" / "channel_descriptors.yaml").write_text(
        _BASE_CATALOGUE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write_database(root / "data" / "data_2026-09-05.db", [])

    result = _run(root)
    assert "GUESSED by recency" in result.stdout, result.stdout
    assert "an input was inferred" in result.stdout, result.stdout


def test_a_missing_explicit_input_is_refused_not_silently_replaced(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stand"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    _write_database(root / "data" / "data_2026-09-05.db", [])

    result = _run_explicit(catalogue=tmp_path / "absent.yaml", root=root)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "catalogue not found" in result.stdout
