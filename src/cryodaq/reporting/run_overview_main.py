"""Child entry point that renders the whole-run overview PNG.

The assistant process must never import matplotlib: rendering is heavy, and a
long-lived supervisor that has loaded a plotting stack is exactly what the H3
import closure exists to prevent. So the companion chart is produced the same
way the scheduled report is — in a short-lived child that exits when it is
done — and the parent only ever handles bytes.

Writes the PNG to ``--out`` and prints ``{"caption": ...}`` on stdout.

Exit codes:
  0  rendered
  3  nothing to chart (no active run, or no data in it) — not a failure
  1  the render failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOTHING_TO_CHART = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the whole-run vacuum/temperature overview")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    # Imported here, not at module scope: this module is also the process
    # boundary, and nothing above it should pay for matplotlib.
    from cryodaq.reporting.run_overview import RunOverviewError, build_run_overview_png

    try:
        png, caption = build_run_overview_png(Path(args.data_dir))
    except RunOverviewError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_NOTHING_TO_CHART
    except Exception as exc:  # noqa: BLE001 - report to the parent, never traceback-crash
        print(f"run overview render failed: {exc}", file=sys.stderr)
        return EXIT_FAILED

    try:
        Path(args.out).write_bytes(png)
    except OSError as exc:
        print(f"cannot write run overview: {exc}", file=sys.stderr)
        return EXIT_FAILED

    sys.stdout.write(json.dumps({"caption": caption}, ensure_ascii=False))
    sys.stdout.flush()
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
