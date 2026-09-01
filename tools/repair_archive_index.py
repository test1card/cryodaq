#!/usr/bin/env python3
"""Repair archive index entries that omit the operator-log field.

Rotation used to record nothing at all for a day that held no operator entries.
``ArchiveReader`` cannot tell that apart from an index written before the field
existed, so it refuses the whole read — correctly, because silently treating a
malformed index as an empty archive would hide real history from the operator
journal.

On 2026-09-01 rotation archived fifteen such days at 03:00 and every
operator-log read failed from then on: the log panel went blank, and each failed
read retained its materialised hot rows through the exception, leaking roughly
67 MB/h.

Fixing the writer only helps days rotated afterwards. This migrates entries
already on disk to the explicit form — a null path with a zero row count.

Refuses to touch any entry whose day actually has a sidecar on disk: that is a
genuinely under-recorded artifact, not an absence, and claiming absence would
hide archived entries permanently. Such entries are reported for a human.

    python tools/repair_archive_index.py --data-dir data            # report only
    python tools/repair_archive_index.py --data-dir data --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

# Every operator-log field. An entry is repairable only when ALL of them are
# absent: that is the exact shape rotation used to write for a day with no
# operator entries, and the only shape whose meaning is unambiguous.
OPERATOR_LOG_FIELDS = (
    "operator_log_path",
    "operator_log_rows",
    "operator_log_size_bytes",
    "operator_log_checksum_md5",
    "operator_log_schema",
)


def _sidecar_candidates(archive_dir: Path, entry: dict) -> list[Path]:
    """Where a sidecar for this entry would live, if one had been written."""
    archive_path = entry.get("archive_path")
    if not isinstance(archive_path, str) or not archive_path:
        return []
    base = archive_dir / archive_path
    stem = base.name.removesuffix(".parquet")
    return [
        base.with_name(f"{stem}.operator_log.parquet"),
        base.with_name(f"{stem}.db.operator_log.parquet"),
        base.with_name(f"{stem}.operator_log_v1.parquet"),
        base.with_name(f"{stem}.operator_log_v2.parquet"),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--apply", action="store_true", help="write the repair (default: report only)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    archive_dir = data_dir / "archive"
    index_path = archive_dir / "index.json"
    if not index_path.exists():
        print(f"no archive index at {index_path}: nothing to repair")
        return 0

    # The reader's own predicate decides what a complete declaration is, so
    # this tool cannot drift from the contract it is migrating towards.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from cryodaq.storage.archive_reader import operator_log_declared_absent

    document = json.loads(index_path.read_text(encoding="utf-8"))
    files = document.get("files")
    if not isinstance(files, list):
        print("index has no file list; refusing to touch it")
        return 2

    repairable: list[dict] = []
    conflicted: list[tuple[dict, Path]] = []
    partial: list[tuple[dict, tuple[str, ...]]] = []
    healthy = 0
    for entry in files:
        if not isinstance(entry, dict):
            continue
        present = tuple(name for name in OPERATOR_LOG_FIELDS if name in entry)
        # Two complete, meaningful shapes: a full sidecar proof, or an explicit
        # declaration of absence. Everything else carrying operator fields is
        # incomplete.
        if len(present) == len(OPERATOR_LOG_FIELDS) or operator_log_declared_absent(entry):
            healthy += 1
            continue
        if present:
            # Some operator fields were written and others were not. What that
            # day held is UNKNOWN, and this tool must not resolve an unknown by
            # deleting the evidence: erasing the partial fields to synthesise a
            # clean "empty" declaration would convert unknown history into
            # proven absence, permanently and silently. It stays unavailable
            # until a human decides.
            partial.append((entry, present))
            continue
        found = next((p for p in _sidecar_candidates(archive_dir, entry) if p.exists()), None)
        if found is not None:
            conflicted.append((entry, found))
        else:
            repairable.append(entry)

    print(f"index entries:        {len(files)}")
    print(f"  already explicit:   {healthy}")
    print(f"  repairable (all five fields absent, no sidecar on disk): {len(repairable)}")
    print(f"  PARTIAL (some fields written, some not): {len(partial)}")
    for entry, present in partial:
        print(f"    {entry.get('original_name')} has {', '.join(present)}")
    print(f"  CONFLICTED (sidecar exists but is unindexed): {len(conflicted)}")
    for entry, found in conflicted:
        print(f"    {entry.get('original_name')} -> {found.name}")
    if conflicted:
        print("\nRefusing to declare absence for conflicted entries: an unindexed sidecar")
        print("holds real archived entries, and declaring absence would hide them.")
    if partial:
        print("\nRefusing to touch partial entries: what that day held is unknown, and")
        print("removing the written fields would record the unknown as proven absence.")
        print("These need a human to inspect the day before anything is claimed.")

    if not repairable:
        return 1 if (conflicted or partial) else 0
    if not args.apply:
        print("\nreport only; re-run with --apply to write")
        for entry in repairable[:10]:
            print(f"    would repair: {entry.get('original_name')}")
        return 0

    for entry in repairable:
        # Only entries that carried no operator field at all reach here, so
        # this adds a complete declaration and deletes nothing.
        entry["operator_log_path"] = None
        entry["operator_log_rows"] = 0

    # Validate against the same authority the reader uses, before replacing a
    # file that both rotation and every read depend on.
    from cryodaq.storage.archive_reader import validate_archive_index_authority

    validate_archive_index_authority(document)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = index_path.with_name(f"index.json.pre-repair-{stamp}")
    shutil.copy2(index_path, backup)
    temporary = index_path.with_name("index.json.repair-tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(index_path)
    print(f"\nrepaired {len(repairable)} entries; previous index kept at {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
