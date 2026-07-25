"""CLI for CryoDAQ cross-experiment trend analytics (roadmap D3).

Two subcommands:

    cryodaq-trends scan  --data-dir DATA_DIR [--csv out.csv] [--json out.json]
        Per-experiment feature table (cooldown fingerprint, TIM/compressor
        proxies) across the archived experiment range.

    cryodaq-trends drift --data-dir DATA_DIR --metric FIELD --threshold X
        Chronological trend for one ExperimentSummary field; exits non-zero
        when the configured drift threshold is exceeded (the field names are
        the attributes on cryodaq.analytics.cross_experiment.ExperimentSummary,
        e.g. initial_cooldown_rate_k_per_h, steady_state_dT_k).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from cryodaq.analytics.cross_experiment import (
    DEFAULT_COLD_CHANNEL,
    DEFAULT_WARM_CHANNEL,
    compute_trend,
    export_summaries_csv,
    export_summaries_json,
    export_trend_json,
    format_summary_table,
    format_trend_report,
    scan_archive,
)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan_archive(
        Path(args.data_dir),
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        cold_channel=args.cold_channel,
        warm_channel=args.warm_channel,
    )
    print(format_summary_table(result.summaries))
    if result.skipped:
        print(f"\nПропущено: {len(result.skipped)}")
        for exp_id, reason in result.skipped:
            print(f"  {exp_id}: {reason}")
    if args.csv:
        export_summaries_csv(result.summaries, Path(args.csv))
        print(f"\nCSV: {args.csv}")
    if args.json:
        export_summaries_json(result.summaries, Path(args.json))
        print(f"JSON: {args.json}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    result = scan_archive(
        Path(args.data_dir),
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        cold_channel=args.cold_channel,
        warm_channel=args.warm_channel,
    )
    trend = compute_trend(
        result.summaries,
        args.metric,
        threshold=args.threshold,
        baseline_n=args.baseline_n,
        recent_n=args.recent_n,
    )
    print(format_trend_report(trend))
    if args.json:
        export_trend_json(trend, Path(args.json))
        print(f"\nJSON: {args.json}")
    # Non-zero exit on detected drift, mirroring monitoring-check convention —
    # lets a caller (cron/CI) alert on this without parsing stdout.
    return 1 if trend.drift_detected else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CryoDAQ: кросс-экспериментная аналитика Parquet-архива"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="Сводка по всем архивным экспериментам")
    p.add_argument("--data-dir", required=True, help="Корень данных (содержит experiments/)")
    p.add_argument("--start", help="ISO-дата начала диапазона (включительно)")
    p.add_argument("--end", help="ISO-дата конца диапазона (включительно)")
    p.add_argument("--cold-channel", default=DEFAULT_COLD_CHANNEL)
    p.add_argument("--warm-channel", default=DEFAULT_WARM_CHANNEL)
    p.add_argument("--csv", help="Путь для сохранения CSV")
    p.add_argument("--json", help="Путь для сохранения JSON")

    p = sub.add_parser("drift", help="Тренд одной метрики + флаг дрейфа")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--metric", required=True, help="Поле ExperimentSummary, например steady_state_dT_k")
    p.add_argument("--threshold", type=float, required=True)
    p.add_argument("--start", help="ISO-дата начала диапазона")
    p.add_argument("--end", help="ISO-дата конца диапазона")
    p.add_argument("--cold-channel", default=DEFAULT_COLD_CHANNEL)
    p.add_argument("--warm-channel", default=DEFAULT_WARM_CHANNEL)
    p.add_argument("--baseline-n", type=int, default=5, help="Число первых запусков для базового среднего")
    p.add_argument("--recent-n", type=int, default=5, help="Число последних запусков для текущего среднего")
    p.add_argument("--json", help="Путь для сохранения JSON тренда")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {"scan": cmd_scan, "drift": cmd_drift}
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
