"""CLI for CryoDAQ cooldown predictor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from cryodaq.analytics.cooldown_predictor import (
    T_PHASE_BOUNDARY,
    ReferenceCurve,
    build_ensemble,
    format_prediction,
    ingest_curve,
    load_curves,
    load_model,
    plot_ensemble,
    plot_prediction,
    plot_validation,
    predict,
    prepare_all,
    save_model,
    validate_loo,
)

# ============================================================================
# Synthetic curve generation (for demo/testing only)
# ============================================================================


def generate_synthetic_curves(
    model_path: Path,
    n_curves: int = 9,
    seed: int = 42,
) -> list[ReferenceCurve]:
    """Generate synthetic cooldown curves from model statistics.

    Double-exponential + sigmoid S-bend matching GM cryocooler physics.
    """
    stats = json.loads(model_path.read_text(encoding="utf-8"))["statistics"]
    rng = np.random.RandomState(seed)

    dur_mean = stats["total_duration_hours"]["mean"]
    dur_std = stats["total_duration_hours"]["std"]
    ph1_mean = stats["phase1_hours"]["mean"]
    ph1_std = stats["phase1_hours"]["std"]
    tc_base_mean = stats["T_cold_baseline"]["mean"]
    tc_base_std = stats["T_cold_baseline"]["std"]
    tw_base_mean = stats["T_warm_baseline"]["mean"]
    tw_base_std = stats["T_warm_baseline"]["std"]

    curves = []
    for i in range(n_curves):
        duration = max(15.0, rng.normal(dur_mean, dur_std))
        phase1 = max(5.0, min(duration - 5, rng.normal(ph1_mean, ph1_std)))
        T_cold_final = max(3.5, rng.normal(tc_base_mean, tc_base_std))
        T_warm_final = max(70.0, min(110.0, rng.normal(tw_base_mean, tw_base_std)))

        dt_h = 10.0 / 3600.0
        t = np.arange(0, duration + dt_h, dt_h)
        n = len(t)

        # Cold: double exponential + S-bend
        T_start = 280 + rng.uniform(-15, 15)
        tau1 = phase1 / 2.5 + rng.normal(0, 0.2)
        tau2 = (duration - phase1) / 2.0 + rng.normal(0, 0.3)
        A1 = (T_start - 50) * 0.6
        A2 = (50 - T_cold_final) * 1.0

        T_cold = T_cold_final + A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2)

        # S-bend (Cu conductivity peak)
        t_bend = phase1 + (duration - phase1) * 0.3
        bend_w = 1.5 + rng.uniform(-0.3, 0.3)
        bend_a = 8.0 + rng.normal(0, 2)
        sigmoid = bend_a / (1 + np.exp(-(t - t_bend) / bend_w))
        mask = (T_cold > 10) & (T_cold < 80)
        T_cold[mask] += sigmoid[mask] * 0.3

        T_cold = np.maximum.accumulate(T_cold[::-1])[::-1]
        T_cold = np.clip(T_cold, T_cold_final, T_start + 10)
        T_cold += rng.normal(0, 0.1, n)
        T_cold = np.clip(T_cold, T_cold_final * 0.95, 400)

        # Warm: single exponential
        T_start_w = T_start + rng.uniform(-5, 5)
        tau_w = duration / 3.0 + rng.normal(0, 0.3)
        T_warm = T_warm_final + (T_start_w - T_warm_final) * np.exp(-t / tau_w)
        T_warm += rng.normal(0, 0.2, n)
        T_warm = np.clip(T_warm, T_warm_final * 0.9, 400)

        cross_idx = np.searchsorted(-T_cold, -T_PHASE_BOUNDARY)
        actual_ph1 = float(t[min(cross_idx, n - 1)])

        rc = ReferenceCurve(
            name=f"synthetic_{i + 1:02d}",
            date=f"2025-{6 + i:02d}-01",
            t_hours=t,
            T_cold=T_cold,
            T_warm=T_warm,
            duration_hours=float(t[-1]),
            phase1_hours=actual_ph1,
            phase2_hours=float(t[-1]) - actual_ph1,
            T_cold_final=float(np.min(T_cold)),
            T_warm_final=float(np.min(T_warm)),
        )
        curves.append(rc)

    print(f"Generated {len(curves)} synthetic curves")
    return curves


# ============================================================================
# CLI commands
# ============================================================================


def cmd_build(args):
    curves = load_curves(Path(args.data))
    if not curves:
        sys.exit("No curves loaded")
    curves = prepare_all(curves)
    model = build_ensemble(curves)
    out = Path(args.output)
    save_model(model, out)
    plot_ensemble(model, out / "ensemble_overview.png")
    print(
        f"\nModel: {model.n_curves} curves, {model.duration_mean:.1f}+/-{model.duration_std:.1f} h"
    )


def cmd_predict(args):
    model = load_model(Path(args.model))
    rate_c = args.rate_cold if hasattr(args, "rate_cold") else None
    rate_w = args.rate_warm if hasattr(args, "rate_warm") else None
    pred = predict(
        model,
        args.T_cold,
        args.T_warm,
        args.t_elapsed,
        observed_rate_cold=rate_c,
        observed_rate_warm=rate_w,
    )
    print(format_prediction(pred))
    if args.output:
        plot_prediction(model, pred, args.T_cold, args.T_warm, args.t_elapsed, Path(args.output))


def cmd_validate(args):
    curves = load_curves(Path(args.data))
    if len(curves) < 3:
        sys.exit(f"Need >=3 curves, got {len(curves)}")
    curves = prepare_all(curves)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    results = validate_loo(curves)
    if results:
        plot_validation(results, out / "loo_validation.png")
        summary = [
            {
                "curve": vr.curve_name,
                "mae_h": float(np.mean(np.abs(vr.t_remaining_err))),
                "rmse_h": float(np.sqrt(np.mean(vr.t_remaining_err**2))),
                "max_err_h": float(np.max(np.abs(vr.t_remaining_err))),
            }
            for vr in results
        ]
        (out / "loo_results.json").write_text(json.dumps(summary, indent=2))
    print(f"\nValidation: {len(results)} folds")


def cmd_demo(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    mp = Path(args.model_json) if args.model_json else None
    if mp and mp.exists():
        curves = generate_synthetic_curves(mp)
    else:
        default = {
            "statistics": {
                "total_duration_hours": {"mean": 19.3, "std": 1.0, "min": 17.7, "max": 21.0},
                "phase1_hours": {"mean": 8.0, "std": 0.5, "min": 7.0, "max": 9.0},
                "T_cold_baseline": {"mean": 4.7, "std": 1.5, "min": 4.0, "max": 9.0},
                "T_warm_baseline": {"mean": 87.0, "std": 6.0, "min": 78.0, "max": 98.0},
            }
        }
        tmp = out / "_tmp.json"
        tmp.write_text(json.dumps(default))
        curves = generate_synthetic_curves(tmp)
        tmp.unlink()

    curves = prepare_all(curves)
    model = build_ensemble(curves)
    save_model(model, out)
    plot_ensemble(model, out / "ensemble_overview.png")

    print("\n" + "=" * 60 + "\nDEMO PREDICTIONS\n" + "=" * 60)
    demos = [
        ("early_2h", 200.0, 260.0, 2.0),
        ("phase1_mid", 100.0, 200.0, 5.0),
        ("50K_crossing", 50.0, 140.0, 8.0),
        ("S_bend_30K", 30.0, 110.0, 12.0),
        ("phase2_10K", 10.0, 95.0, 16.0),
        ("near_end_5K", 5.0, 88.0, 18.0),
    ]
    for label, Tc, Tw, t_el in demos:
        pred = predict(model, Tc, Tw, t_el)
        h, m = int(pred.t_remaining_hours), int((pred.t_remaining_hours % 1) * 60)
        print(f"\n  {label}: Tc={Tc:.0f}K, Tw={Tw:.0f}K, t={t_el:.1f}h")
        print(f"    -> {h}h{m:02d}m left (p={pred.progress:.1%}, {pred.phase})")
        plot_prediction(model, pred, Tc, Tw, t_el, out / f"pred_{label}.png")

    print("\n" + "=" * 60 + "\nLOO VALIDATION\n" + "=" * 60)
    val = validate_loo(curves)
    if val:
        plot_validation(val, out / "loo_validation.png")
    print(f"\nDemo complete -> {out}/")


def cmd_update(args):
    """CLI: add a new curve to existing model."""
    model_dir = Path(args.model)
    curve_path = Path(args.curve)

    if not curve_path.exists():
        sys.exit(f"Curve file not found: {curve_path}")

    ok, msg, model = ingest_curve(model_dir, curve_path, force=args.force)
    print(msg)

    if ok and model:
        plot_ensemble(model, model_dir / "ensemble_overview.png")

    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description="CryoDAQ Cooldown Predictor")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build")
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("predict")
    p.add_argument("--model", required=True)
    p.add_argument("--T_cold", type=float, required=True)
    p.add_argument("--T_warm", type=float, required=True)
    p.add_argument("--t_elapsed", type=float, default=0.0)
    p.add_argument("--output")
    p.add_argument(
        "--rate_cold", type=float, default=None, help="Observed dT_cold/dt [K/h] (negative=cooling)"
    )
    p.add_argument("--rate_warm", type=float, default=None, help="Observed dT_warm/dt [K/h]")

    p = sub.add_parser("validate")
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("demo")
    p.add_argument("--output", default="demo_output")
    p.add_argument("--model-json", dest="model_json")

    p = sub.add_parser("update", help="Add new curve to existing model")
    p.add_argument("--model", required=True, help="Model directory")
    p.add_argument("--curve", required=True, help="New cooldown JSON file")
    p.add_argument("--force", action="store_true", help="Skip quality gate")

    args = parser.parse_args()
    {
        "build": cmd_build,
        "predict": cmd_predict,
        "validate": cmd_validate,
        "demo": cmd_demo,
        "update": cmd_update,
    }[args.command](args)


if __name__ == "__main__":
    main()
