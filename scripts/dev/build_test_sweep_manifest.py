"""Partition the whole test suite into priority-ordered batches of ~100 tests
(whole files, never split) for the Codex adversarial test-sweep loop.

Writes artifacts/test-sweep/manifest.json. Run from repo root:
    python scripts/dev/build_test_sweep_manifest.py
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

BATCH_TARGET = 100  # tests per batch (a single large file may exceed this)

# Priority tiers by path prefix — safety/correctness first, GUI last.
TIER_PREFIXES = [
    ("tests/core/", 0),
    ("tests/storage/", 0),
    ("tests/drivers/", 0),
    ("tests/analytics/", 1),
    ("tests/agents/", 1),
    ("tests/replay", 1),
    ("tests/notifications/", 1),
    ("tests/reporting/", 1),
    ("tests/web", 1),
    ("tests/tools/", 1),
    ("tests/gui/", 2),
]


def tier_of(path: str) -> int:
    for prefix, tier in TIER_PREFIXES:
        if path.startswith(prefix):
            return tier
    return 1  # default middle tier (root-level tests/ etc.)


def main() -> None:
    out = subprocess.run(
        ["python", "-m", "pytest", "tests/", "--co", "-q"],
        capture_output=True,
        text=True,
    ).stdout
    counts: Counter[str] = Counter()
    for line in out.splitlines():
        if "::" in line:
            counts[line.split("::", 1)[0]] += 1

    files = sorted(counts, key=lambda f: (tier_of(f), f))

    batches: list[dict] = []
    cur: list[str] = []
    cur_n = 0
    for f in files:
        n = counts[f]
        if cur and cur_n + n > BATCH_TARGET:
            batches.append({"files": cur, "test_count": cur_n})
            cur, cur_n = [], 0
        cur.append(f)
        cur_n += n
    if cur:
        batches.append({"files": cur, "test_count": cur_n})

    for i, b in enumerate(batches):
        b["id"] = i
        b["tier"] = min(tier_of(f) for f in b["files"])

    manifest = {
        "total_tests": sum(counts.values()),
        "total_files": len(files),
        "total_batches": len(batches),
        "batch_target": BATCH_TARGET,
        "batches": batches,
    }

    dest = Path("artifacts/test-sweep/manifest.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"tests={manifest['total_tests']} files={len(files)} batches={len(batches)}")
    for b in batches:
        print(f"  batch {b['id']:>2} | tier {b['tier']} | {b['test_count']:>3} tests | {len(b['files'])} files")


if __name__ == "__main__":
    main()
