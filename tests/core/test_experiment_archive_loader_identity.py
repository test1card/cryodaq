"""OC-024 — the LOADER half: identity must survive the trip out of the archive.

`tests/core/test_experiment_archive_descriptors.py` drives
`_write_measured_values_table` with synthetic dictionaries.  That guards the
writer and nothing else: if `_load_experiment_readings` stopped copying
`row.descriptor`, production finalisation would still emit nine columns with
every identity cell empty, and all seven of those nodes would stay green.
Codex named that hole on `d2fa199e` and it was real.

So these nodes build a REAL archive on disk -- a descriptor catalog plus rows
that reference it -- and read it back through `ArchiveReader`, the same object
production uses.  Two properties:

* a row whose `descriptor_hash` resolves against the catalog reaches the
  finalisation dict with that declared identity; and
* a row written BEFORE the catalog existed reaches it with the identity cells
  EMPTY.

The second is the sharper one, and it is not the obvious case.  The bounded
readers never report absent identity as ``None``: `_read_sqlite_bounded` and
`_read_parquet_bounded` call `resolve_legacy_descriptor` whenever the stored
hash is NULL, so `row.descriptor` is a synthetic ``legacy=True`` object whose
`channel_id` is ``legacy:<digest of the channel spelling>``.  A loader that
tests only ``descriptor is None`` therefore persists a manufactured identity
derived from the very spelling OC-024 exists to stop trusting -- unattributable
history rendered as descriptor-backed.  `legacy` is already this repository's
marker for absent identity (`reporting/sections.py::_reading_series_key` and
`_visible_quantity` both refuse it); the finalisation loader now agrees.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.experiment import ExperimentInfo, ExperimentManager, ExperimentStatus
from cryodaq.storage.channel_descriptors import initialize_descriptor_storage, install_catalog
from cryodaq.storage.sqlite_writer import SCHEMA_READINGS

START = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
END = START + timedelta(minutes=5)
LEGACY_INSTRUMENT = "LS218_1"
LEGACY_SPELLING = "Т12 Теплообменник 2"


def _descriptor() -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id="cryostat.stage2.temperature",
        instrument_id="LS218_1",
        source_key="input.2.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Теплообменник 2",
        visible_by_default=True,
        display_order=2,
        descriptor_revision=3,
    )


def _archive(data_dir: Path, *, descriptor: ChannelDescriptorV1 | None) -> None:
    """Write one hot-tier day file holding a single reading.

    ``descriptor=None`` writes the pre-catalog shape: a `readings` table with a
    NULL `descriptor_hash` and no `channel_descriptors` table at all.
    """

    data_dir.mkdir(parents=True, exist_ok=True)
    # `ArchiveReader` discovers hot-tier days by the exact glob
    # `data_????-??-??.db`; a differently-spelled name is silently invisible and
    # yields an empty, ISSUE-FREE result -- a fixture that measures nothing while
    # looking like a clean read.
    connection = sqlite3.connect(data_dir / f"data_{START:%Y-%m-%d}.db")
    try:
        connection.execute(SCHEMA_READINGS)
        when = (START + timedelta(minutes=1)).timestamp()
        if descriptor is None:
            # The pre-catalog shape is the ABSENCE of the column, not a NULL in
            # it: `descriptor_hash` is added by `initialize_descriptor_storage`.
            # Here the `channel` column holds the operator SPELLING, which is
            # all a pre-catalog row ever had.
            connection.execute(
                "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
                (when, LEGACY_INSTRUMENT, LEGACY_SPELLING, 4.21, "K", "ok"),
            )
        else:
            # A descriptor-bearing row is REQUIRED to agree with its descriptor:
            # `archive_reader.py:1371-1376` refuses the read with
            # DESCRIPTOR_READING_MISMATCH unless instrument, channel and unit all
            # match, so here the `channel` column carries the declared channel_id
            # rather than a spelling.  That is exactly why the finalisation table
            # needs its own `channel_id` column: the `channel` column means
            # different things in the two eras, and only the new column says
            # which era a row belongs to.
            initialize_descriptor_storage(connection)
            install_catalog(connection, ChannelCatalog([descriptor]))
            connection.execute(
                "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status,descriptor_hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    when,
                    descriptor.instrument_id,
                    descriptor.channel_id,
                    4.21,
                    descriptor.unit,
                    "ok",
                    descriptor.descriptor_hash,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _load(data_dir: Path) -> list[dict[str, object]]:
    manager = ExperimentManager.__new__(ExperimentManager)
    manager._data_dir = data_dir  # type: ignore[attr-defined]
    info = ExperimentInfo(
        experiment_id="exp-oc024",
        name="oc024",
        title="OC-024 loader guard",
        template_id="default",
        operator="",
        cryostat="",
        sample="",
        description="",
        notes="",
        start_time=START,
        end_time=END,
        status=ExperimentStatus.COMPLETED,
    )
    snapshot = manager._load_experiment_readings(info)  # type: ignore[attr-defined]
    return list(snapshot.rows)


def test_a_declared_identity_survives_the_archive_round_trip(tmp_path: Path) -> None:
    """The production path, not a synthetic dict: catalog -> ArchiveReader -> row."""

    descriptor = _descriptor()
    _archive(tmp_path, descriptor=descriptor)

    rows = _load(tmp_path)

    assert len(rows) == 1, f"expected one archived row, got {len(rows)}"
    row = rows[0]
    assert row["channel_id"] == "cryostat.stage2.temperature"
    assert row["descriptor_hash"] == descriptor.descriptor_hash
    assert row["descriptor_revision"] == 3


def test_a_pre_catalog_row_arrives_with_no_identity_rather_than_a_synthetic_one(tmp_path: Path) -> None:
    """The synthetic-legacy trap.

    The reader hands the loader a ``legacy=True`` descriptor here, NOT ``None``.
    Persisting it would write ``legacy:<digest>`` into `channel_id` and a hash
    computed from the channel string -- an inference wearing a declaration's
    clothes.
    """

    _archive(tmp_path, descriptor=None)

    rows = _load(tmp_path)

    assert len(rows) == 1, f"expected one archived row, got {len(rows)}"
    row = rows[0]
    assert row["channel_id"] is None
    assert row["descriptor_hash"] is None
    assert row["descriptor_revision"] is None


def test_the_reader_really_does_synthesize_a_legacy_descriptor_here(tmp_path: Path) -> None:
    """Premise check for the node above -- otherwise it could pass vacuously.

    If the bounded reader ever started reporting absent identity as ``None``,
    the previous test would still pass while no longer exercising the trap it
    was written for.  Assert the trap is present.
    """

    from cryodaq.storage.archive_reader import ArchiveReader

    _archive(tmp_path, descriptor=None)
    result = ArchiveReader(tmp_path, tmp_path / "archive").query_reading_rows_bounded(
        start=START,
        end=END,
        channels=None,
        max_channels=64,
        max_points_per_channel=100,
        max_total_points=100,
        max_retained_bytes=1 << 20,
        deadline_monotonic=time.monotonic() + 30.0,
    )

    assert len(result.rows) == 1
    descriptor = result.rows[0].descriptor
    assert descriptor is not None, "premise broken: the reader now reports absent identity as None"
    assert descriptor.legacy is True
    assert descriptor.channel_id.startswith("legacy:")


def test_the_retained_byte_budget_charges_for_the_identity_it_retains() -> None:
    """What is retained must be budgeted.

    The 32 MiB accumulator is what stands between a large experiment and memory
    exhaustion.  Each row now carries three identity values -- roughly 200 bytes
    for a maximum-length channel_id -- and charging only the original
    instrument/channel/unit/status projection lets a long finalisation hold and
    write substantially more than the cap allows.

    Asserted on the accounting directly rather than by building an archive large
    enough to approach the cap.  Inline, that was the ONLY way to reach it, and
    no guard did -- so dropping the identity terms left every mapped guard
    green. Codex found that on `9893a65c`.
    """

    from cryodaq.core.experiment import _retained_identity, _retained_row_bytes

    class _Row:
        instrument_id = "LS218_1"
        channel = "cryostat.stage2.temperature"
        unit = "K"
        status = "ok"

    row = _Row()
    descriptor = _descriptor()
    resolved = SimpleNamespace(
        channel_id=descriptor.channel_id,
        descriptor_hash=descriptor.descriptor_hash,
        descriptor_revision=descriptor.descriptor_revision,
        legacy=False,
    )
    legacy = SimpleNamespace(
        channel_id="legacy:" + "f" * 64,
        descriptor_hash="sha256:" + "e" * 64,
        descriptor_revision=1,
        legacy=True,
    )

    without = _retained_row_bytes(row, None)
    with_identity = _retained_row_bytes(row, _retained_identity(resolved))

    expected = (
        len(resolved.channel_id.encode("utf-8"))
        + len(resolved.descriptor_hash.encode("utf-8"))
        + len(str(resolved.descriptor_revision).encode("utf-8"))
    )
    assert with_identity - without == expected, (
        "the identity columns are retained but not charged against the memory bound"
    )
    assert with_identity > without

    # A legacy descriptor is not persisted, so it must not be charged either --
    # the budget has to agree with what the writer actually stores.
    assert _retained_identity(legacy) is None
    assert _retained_row_bytes(row, _retained_identity(legacy)) == without


def test_the_loader_charges_the_budget_with_the_identity_it_persists(tmp_path: Path, monkeypatch) -> None:
    """Guard the WIRING, not just the arithmetic.

    Extracting `_retained_row_bytes` made the accounting assertable and left its
    CALL unguarded: Codex replaced the `identity` argument with `None` at the
    call site and all 14 nodes stayed green, so the helper could remain correct
    in isolation while production stopped charging for what it persists.

    This drives the real `_load_experiment_readings` and asserts the argument it
    passes, so a miswired call fails here rather than at 32 MiB in a lab.
    """

    from cryodaq.core import experiment as experiment_module

    descriptor = _descriptor()
    _archive(tmp_path, descriptor=descriptor)

    charged: list[object] = []
    real = experiment_module._retained_row_bytes

    def recording(row: object, identity: object) -> int:
        charged.append(identity)
        return real(row, identity)

    monkeypatch.setattr(experiment_module, "_retained_row_bytes", recording)

    rows = _load(tmp_path)
    assert len(rows) == 1, "premise: the archive must yield exactly one row"
    assert len(charged) == 1, f"the budget was consulted {len(charged)} times for one row"

    identity = charged[0]
    assert identity is not None, "the loader charged the budget as though the row carried no identity"
    assert identity.channel_id == descriptor.channel_id
    assert identity.descriptor_hash == descriptor.descriptor_hash

    # And the value actually persisted agrees with what was charged for.
    assert rows[0]["channel_id"] == identity.channel_id
    assert rows[0]["descriptor_hash"] == identity.descriptor_hash


def test_the_loader_charges_nothing_for_a_legacy_row(tmp_path: Path, monkeypatch) -> None:
    """The mirror: what is not persisted must not be charged.

    A budget that over-charges is a different defect from one that under-charges
    but it is still a wrong bound, and the legacy filter runs before the call --
    so this asserts the two agree at the call site rather than by inspection.
    """

    from cryodaq.core import experiment as experiment_module

    _archive(tmp_path, descriptor=None)

    charged: list[object] = []
    real = experiment_module._retained_row_bytes

    def recording(row: object, identity: object) -> int:
        charged.append(identity)
        return real(row, identity)

    monkeypatch.setattr(experiment_module, "_retained_row_bytes", recording)

    rows = _load(tmp_path)
    assert len(rows) == 1
    assert charged == [None], "a legacy row was charged for identity it does not persist"
    assert rows[0]["channel_id"] is None


@pytest.mark.parametrize("field_name", ["channel_id", "descriptor_hash", "descriptor_revision"])
def test_every_identity_column_is_populated_from_the_archive(tmp_path: Path, field_name: str) -> None:
    """Assert each column positively.

    A file-wide assertion that "identity is carried" can stay satisfied by one
    populated column while another silently reverts -- the one-row-away hole
    that `ARCHIVE-FINALISATION-IDENTITY-DISCARDED-318` records.
    """

    _archive(tmp_path, descriptor=_descriptor())
    row = _load(tmp_path)[0]
    assert row[field_name] not in (None, ""), f"{field_name} was not carried out of the archive"
