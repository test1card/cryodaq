"""cryodaq-replay-curve — extract and transform a reference curve for replay.

Usage::

    cryodaq-replay-curve --model cooldown_v5/predictor_model.json \\
        --curve "МТО_11-16" --transform compress=2.0 \\
        --transform raise_floor=0.5,2.0 --output /tmp/mto.db

Transforms (--transform, multiple allowed, applied left-to-right):
  compress=FACTOR              compress_time(factor=FACTOR)
  raise_floor=DK_COLD,DK_WARM  raise_floor(delta_K_cold, delta_K_warm)
  perturb=SCALE,T_MAX_H        perturb_early_phase(scale, max_t_h)
  noise=SIGMA[,SEED]           add_noise(sigma_K, seed)

Output (auto-detected from --output suffix):
  *.json  → cooldown_v5 schema
  *.db    → SQLite (for replay_session.py)

--replay flag: write *.db then immediately spawn replay_session.py.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np


def _parse_transform(spec: str) -> tuple[str, list[str]]:
    """Split 'name=arg1,arg2' into ('name', ['arg1', 'arg2'])."""
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"Неверный формат трансформации: '{spec}' (нужно name=args)"
        )
    name, _, args_str = spec.partition("=")
    return name.strip(), [a.strip() for a in args_str.split(",")]


def _apply_transforms(
    curve: dict,
    transforms: list[str],
) -> dict:
    from cryodaq.replay.curve_transforms import (
        add_noise,
        compress_time,
        perturb_early_phase,
        raise_floor,
    )

    t = np.array(curve["t_hours"], dtype=float)
    tc = np.array(curve["T_cold"], dtype=float)
    tw = np.array(curve["T_warm"], dtype=float)

    for spec in transforms:
        name, args = _parse_transform(spec)
        if name == "compress":
            if len(args) != 1:
                raise ValueError(f"compress: ожидается 1 аргумент, получено {args}")
            t, tc, tw = compress_time(t, tc, tw, float(args[0]))
        elif name == "raise_floor":
            if len(args) not in (1, 2):
                raise ValueError(f"raise_floor: ожидается 1-2 аргумента, получено {args}")
            dk_c = float(args[0])
            dk_w = float(args[1]) if len(args) > 1 else 0.0
            t, tc, tw = raise_floor(t, tc, tw, dk_c, dk_w)
        elif name == "perturb":
            if len(args) not in (1, 2):
                raise ValueError(f"perturb: ожидается 1-2 аргумента, получено {args}")
            scale = float(args[0])
            max_t = float(args[1]) if len(args) > 1 else 1.5
            t, tc, tw = perturb_early_phase(t, tc, tw, scale, max_t)
        elif name == "noise":
            if len(args) not in (1, 2):
                raise ValueError(f"noise: ожидается 1-2 аргумента, получено {args}")
            sigma = float(args[0])
            seed = int(args[1]) if len(args) > 1 else None
            t, tc, tw = add_noise(t, tc, tw, sigma, seed)
        else:
            raise ValueError(f"Неизвестная трансформация: '{name}'")

    result = dict(curve)
    result["t_hours"] = t.tolist()
    result["T_cold"] = tc.tolist()
    result["T_warm"] = tw.tolist()
    result["duration_hours"] = float(t[-1]) if len(t) else curve.get("duration_hours", 0.0)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Извлечь и трансформировать опорную кривую охлаждения для воспроизведения.",
    )
    parser.add_argument("--model", type=Path, required=True, help="Путь к predictor_model.json")
    parser.add_argument(
        "--curve", required=True, help="Подстрока имени кривой (регистр игнорируется)"
    )
    parser.add_argument(
        "--transform",
        action="append",
        default=[],
        metavar="SPEC",
        help="compress=F, raise_floor=DKc,DKw, perturb=S,T, noise=σ[,seed]. Повторяется.",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Путь вывода (*.json или *.db)"
    )
    parser.add_argument(
        "--replay", action="store_true", help="Запустить replay_session.py после записи .db"
    )
    parser.add_argument(
        "--speed", type=float, default=10.0, help="Скорость воспроизведения (default: 10)"
    )
    parser.add_argument(
        "--cold-channel", default="Т12", help="Имя холодного канала в SQLite (default: Т12)"
    )
    parser.add_argument(
        "--warm-channel", default="Т11", help="Имя тёплого канала в SQLite (default: Т11)"
    )
    args = parser.parse_args(argv)

    from cryodaq.replay.curve_transforms import (
        curve_to_sqlite,
        load_curve_from_model,
        write_curve_json,
    )

    # Load curve from model
    try:
        curve = load_curve_from_model(args.model, args.curve)
    except KeyError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    # Apply transforms
    try:
        curve = _apply_transforms(curve, args.transform)
    except (ValueError, argparse.ArgumentTypeError) as e:
        print(f"Ошибка трансформации: {e}", file=sys.stderr)
        return 1

    # Write output
    suffix = args.output.suffix.lower()
    if suffix == ".json":
        write_curve_json(curve, args.output)
        print(f"Записано: {args.output}")
    elif suffix == ".db":
        curve_to_sqlite(
            curve, args.output,
            cold_channel=args.cold_channel,
            warm_channel=args.warm_channel,
        )
        print(f"Записано: {args.output}")
    else:
        print(
            f"Ошибка: неизвестный формат вывода '{suffix}' (нужно .json или .db)",
            file=sys.stderr,
        )
        return 1

    # Optionally launch replay_session.py
    if args.replay:
        db_path = args.output if suffix == ".db" else args.output.with_suffix(".db")
        if suffix != ".db":
            curve_to_sqlite(
                curve, db_path,
                cold_channel=args.cold_channel,
                warm_channel=args.warm_channel,
            )
        cmd = [
            sys.executable, "-m", "tools.replay_session",
            "--db", str(db_path),
            "--speed", str(args.speed),
        ]
        print(f"Запуск: {' '.join(cmd)}")
        subprocess.run(cmd)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
