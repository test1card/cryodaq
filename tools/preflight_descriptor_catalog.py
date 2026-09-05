#!/usr/bin/env python
"""Refuse a deploy whose descriptor catalogue will not install.

On 2026-09-05 the stand came up and wrote NOTHING for two and a half minutes —
297 `Ошибка записи`, `written=0`, every reading refused — because a deploy
carried a changed descriptor at a revision the database already held:

    ChannelDescriptorError: changed canonical descriptor reuses an existing
    revision

`install_catalog` compares the whole canonical descriptor, presentation fields
included, so a change as small as `visible_by_default` needs a new
`descriptor_revision`. The failure is total rather than partial: catalogue
install raises, the writer never receives a channel map, and every channel goes
silent at once.

That error can only occur where a catalogue meets a database that already holds
the previous revision — which is exactly what a deploy onto a running stand is,
and precisely the situation no test can construct for itself.
`tests/channels/test_descriptor_revision_contract.py` pins the CONTRACT; this
pins THIS STAND, by running the real validator against the real day database
before anything is restarted.

Read-only. Opens the database with `mode=ro`, writes nothing, and starts no
engine. Safe to run while the stack is live — and that is the point, because
the answer is only useful before `kill -TERM`.

    python tools/preflight_descriptor_catalog.py [--root /home/lab53/cryodaq]

`--root` exists so the check can be run from a pristine worktree against the
LIVE stand's config and data, which is the arrangement the standing rules
require for anything executed while the stack is up.

Exit 0 = the catalogue installs. Exit 1 = it does not, and the message is the
refusal the engine would have raised after the stand was already down.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from cryodaq.channels.descriptors import (  # noqa: E402
    ChannelDescriptorError,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    validate_catalog_update,
)
from cryodaq.storage.channel_descriptors import (  # noqa: E402
    load_live_channel_descriptor_catalog,
)


def _descriptor_from_mapping(row: dict) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=row["schema_version"],
        channel_id=row["channel_id"],
        instrument_id=row["instrument_id"],
        source_key=row["source_key"],
        quantity=ChannelQuantity(row["quantity"]),
        unit=row["unit"],
        role=ChannelRole(row["role"]),
        safety_class=ChannelSafetyClass(row["safety_class"]),
        display_group=row["display_group"],
        display_name=row["display_name"],
        visible_by_default=row["visible_by_default"],
        display_order=row["display_order"],
        descriptor_revision=row["descriptor_revision"],
    )


def _persisted(db_path: Path) -> list[ChannelDescriptorV1]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT envelope_json FROM channel_descriptors").fetchall()
    finally:
        connection.close()
    return [_descriptor_from_mapping(json.loads(raw)["descriptor"]) for (raw,) in rows]


def _recency(database: Path) -> float:
    """Newest mtime across the database and its WAL sidecar.

    In WAL mode a commit lands in ``-wal``, and the main file's mtime can lag
    far behind the last committed row — so ranking day files by the main
    file's mtime alone can rank an actively-written database BELOW a quiescent
    older one. Review of 2026-09-05 reproduced exactly that in a disposable
    tree: a database accepting committed rows was passed over in favour of
    yesterday's file. Taking the max across the set the database is actually
    made of removes that blind spot.
    """

    newest = database.stat().st_mtime
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        try:
            newest = max(newest, sidecar.stat().st_mtime)
        except OSError:
            continue
    return newest


def _active_day_database(data_dir: Path) -> Path | None:
    """Best guess at the day file the engine is writing.

    A GUESS, and the caller says so. The day rolls at 03:00 rather than
    midnight, so today's date is not necessarily the open file, and recency
    cannot distinguish "being written now" from "written most recently".
    Pass --database to remove the guess entirely.
    """

    candidates = sorted(data_dir.glob("data_????-??-??.db"), key=_recency)
    return candidates[-1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=_ROOT,
        help="checkout whose config/ and data/ to inspect (default: this checkout)",
    )
    # --root binds BOTH sides to one tree, which is wrong for the check this
    # tool exists to perform. The question is "does the CANDIDATE catalogue
    # install against the LIVE database", and those live in different trees
    # during a deploy: running the candidate's script with --root pointed at
    # the live checkout validates the live catalogue against itself and always
    # passes. Review of 2026-09-05 named this. Either side can now be given
    # explicitly, and the report says which were chosen and which were guessed.
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=None,
        help="descriptor catalogue to validate (default: derived from --root)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="day database to validate against (default: guessed from --root/data)",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    config = root / "config"
    data_dir = root / "data"

    if arguments.catalogue is not None:
        catalogue_path = arguments.catalogue.resolve()
        catalogue_chosen = "explicit"
        if not catalogue_path.is_file():
            print(f"catalogue not found: {catalogue_path}")
            return 2
    else:
        instruments_local = config / "instruments.local.yaml"
        local_catalogue = config / "channel_descriptors.local.yaml"
        if instruments_local.is_file() and local_catalogue.is_file():
            catalogue_path = local_catalogue
        else:
            catalogue_path = config / "channel_descriptors.yaml"
        catalogue_chosen = "derived from --root"

    if arguments.database is not None:
        database = arguments.database.resolve()
        database_chosen = "explicit"
        if not database.is_file():
            print(f"database not found: {database}")
            return 2
    else:
        database = _active_day_database(data_dir)
        database_chosen = "GUESSED by recency"
        if database is None:
            print(f"no day database under {data_dir} — nothing to validate against")
            return 0

    print(f"catalogue: {catalogue_path}  ({catalogue_chosen})")
    print(f"database:  {database}  (mode=ro, {database_chosen})")
    if database_chosen != "explicit" or catalogue_chosen != "explicit":
        print(
            "note: an input was inferred rather than given. This check is only "
            "as good as those choices — pass --catalogue and --database to "
            "state them."
        )

    existing = _persisted(database)
    proposed = load_live_channel_descriptor_catalog(catalogue_path).storage_catalog_snapshot().descriptors
    print(f"persisted: {len(existing)} descriptors    proposed: {len(proposed)} descriptors")

    try:
        validate_catalog_update(existing, proposed)
    except ChannelDescriptorError as exc:
        print()
        print(f"REFUSED: {exc}")
        print()
        by_revision = {(d.channel_id, d.descriptor_revision): d.canonical_json for d in existing}
        for descriptor in proposed:
            key = (descriptor.channel_id, descriptor.descriptor_revision)
            held = by_revision.get(key)
            if held is not None and held != descriptor.canonical_json:
                print(f"  {descriptor.channel_id} rev {descriptor.descriptor_revision} differs from what is stored:")
                stored = json.loads(held)
                incoming = json.loads(descriptor.canonical_json)
                for field in sorted(set(stored) | set(incoming)):
                    if stored.get(field) != incoming.get(field):
                        print(f"      {field}: stored={stored.get(field)!r} -> catalogue={incoming.get(field)!r}")
                print("      fix: give it a new descriptor_revision")
        return 1

    print()
    print("OK — this catalogue installs against the live database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
