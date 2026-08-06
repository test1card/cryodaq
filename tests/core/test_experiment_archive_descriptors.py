"""OC-024 — a finalised archive row must carry its declared measurement identity.

The finalisation table carried only timestamp, instrument, channel, value, unit
and status.  The archive HAD already resolved a descriptor for each row --
`BoundedReadingRow.descriptor` -- and `_load_experiment_readings` dropped it one
statement before it would have been persisted.  So an archived record could not
later be attributed to a declared identity, and any downstream grouping had to
fall back to the channel SPELLING, which is the inference the descriptor spine
exists to remove.

Two properties are asserted, and the second matters as much as the first:

* identity that EXISTS is carried through, and
* identity that does NOT exist stays empty rather than being reconstructed from
  the channel string.  Back-filling from spelling would make the table look
  descriptor-backed while re-introducing the defect underneath.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.core.experiment import ExperimentManager

EXPECTED_HEADER = [
    "timestamp",
    "instrument_id",
    "channel",
    "value",
    "unit",
    "status",
    "channel_id",
    "descriptor_hash",
    "descriptor_revision",
]


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
        "instrument_id": "LS218_1",
        "channel": "Т12 Теплообменник 2",
        "value": 4.21,
        "unit": "K",
        "status": "ok",
        "channel_id": "cryostat.stage2.temperature",
        "descriptor_hash": "sha256:" + "a" * 64,
        "descriptor_revision": 3,
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, rows: list[dict[str, object]]) -> list[list[str]]:
    target = tmp_path / "measured_values.csv"
    ExperimentManager._write_measured_values_table(  # type: ignore[arg-type]
        ExperimentManager.__new__(ExperimentManager), target, rows
    )
    with target.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_the_finalisation_table_carries_declared_identity(tmp_path: Path) -> None:
    written = _write(tmp_path, [_row()])

    assert written[0] == EXPECTED_HEADER
    body = dict(zip(EXPECTED_HEADER, written[1], strict=True))
    assert body["channel_id"] == "cryostat.stage2.temperature"
    assert body["descriptor_hash"] == "sha256:" + "a" * 64
    assert body["descriptor_revision"] == "3"


def test_a_row_without_a_descriptor_stays_empty_and_is_not_inferred(tmp_path: Path) -> None:
    """Rows predating the descriptor catalog must not acquire an invented identity."""

    written = _write(
        tmp_path,
        [_row(channel_id=None, descriptor_hash=None, descriptor_revision=None)],
    )

    body = dict(zip(EXPECTED_HEADER, written[1], strict=True))
    assert body["channel_id"] == ""
    assert body["descriptor_hash"] == ""
    assert body["descriptor_revision"] == ""
    # The channel spelling is still recorded -- it is real data -- but it must
    # not have been promoted into the identity columns.
    assert body["channel"] == "Т12 Теплообменник 2"
    assert body["channel_id"] != body["channel"]


def test_the_six_legacy_columns_keep_their_positions(tmp_path: Path) -> None:
    """Identity is APPENDED, so a positional reader of the old table still works."""

    written = _write(tmp_path, [_row()])
    assert written[0][:6] == ["timestamp", "instrument_id", "channel", "value", "unit", "status"]
    assert written[1][1] == "LS218_1"
    assert written[1][2] == "Т12 Теплообменник 2"
    assert written[1][4] == "K"
    assert written[1][5] == "ok"


def test_a_non_finite_value_still_writes_an_empty_cell(tmp_path: Path) -> None:
    """Pre-existing NaN handling must survive the column change."""

    written = _write(tmp_path, [_row(value=float("nan"))])
    body = dict(zip(EXPECTED_HEADER, written[1], strict=True))
    assert body["value"] == ""
    assert body["channel_id"] == "cryostat.stage2.temperature"


@pytest.mark.parametrize("missing", ["channel_id", "descriptor_hash", "descriptor_revision"])
def test_a_reading_dict_lacking_the_identity_keys_does_not_crash(tmp_path: Path, missing: str) -> None:
    """Producers other than the archive loader may not supply these keys.

    The writer must degrade to an empty cell rather than raising, because a
    finalisation that fails outright loses the whole table -- a worse outcome
    than a row with unknown identity, which is at least honest about it.
    """

    row = _row()
    del row[missing]
    written = _write(tmp_path, [row])
    body = dict(zip(EXPECTED_HEADER, written[1], strict=True))
    assert body[missing] == ""
