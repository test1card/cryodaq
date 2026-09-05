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
    assert "sqlite3.connect(f\"file:{db_path}?mode=ro\", uri=True)" in source
