"""tools/mock_scenario.py — publish synthetic Reading streams for QA.

Runs as a standalone process; does NOT need the engine. Binds PUB on
``tcp://127.0.0.1:5555`` by default so the running GUI picks up the
synthetic stream directly. Stop the real engine first if it's
running — two PUB servers on the same port compete.

Scenarios:

- ``vacuum`` — pressure decays 1e-3 → 1e-7 mbar along an exponential;
  temperatures hold at 290 K.
- ``cooldown`` — T1..T3 decay 290 → 4 K along a tanh-smoothed curve;
  pressure holds at 1e-6 mbar.
- ``warmup`` — mirror of cooldown, 4 → 290 K over duration.
- ``measurement`` — R_thermal noise around 1.5e-3 K/W (±5 %); T ≈ 4 K;
  Keithley smua power holds at 0.5 W.
- ``cooldown_with_prediction`` — cooldown scenario plus
  ``analytics/cooldown_prediction`` readings carrying central /
  lower_ci / upper_ci metadata.

Usage::

    python -m tools.mock_scenario --scenario vacuum --duration 60
    python -m tools.mock_scenario --scenario cooldown --duration 600
    python -m tools.mock_scenario --scenario cooldown_with_prediction \\
        --duration 600 --ci-level 67

Flags: ``--dry-run`` prints the first 10 readings without binding the
port; ``--verbose`` logs every publish.
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from cryodaq.drivers.base import ChannelStatus, Reading
from tools._zmq_helpers import DEFAULT_PUB_ADDR, publish_reading, publisher_socket

logger = logging.getLogger("mock_scenario")

_SCENARIOS: tuple[str, ...] = (
    "vacuum",
    "cooldown",
    "warmup",
    "measurement",
    "cooldown_with_prediction",
)


def _reading(
    channel: str,
    value: float,
    unit: str,
    *,
    instrument_id: str = "mock",
    metadata: dict | None = None,
) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=float(value),
        unit=unit,
        status=ChannelStatus.OK,
        metadata=metadata or {},
    )


def _tanh_ramp(p: float, start: float, end: float) -> float:
    """Smoothed ramp from ``start`` to ``end`` as ``p`` goes 0→1.

    Uses tanh(4·(p-0.5)) remapped to [0, 1] so the midpoint derivative
    is large but the endpoints ease out — a reasonable cryostat
    cool/warm approximation without modelling real physics.
    """
    raw = (math.tanh(4.0 * (p - 0.5)) + 1.0) * 0.5
    return start + (end - start) * raw


def _exp_decay(p: float, start: float, end: float) -> float:
    """Log-linear interpolation from ``start`` to ``end`` as p goes 0→1.

    Suitable for pressure spanning many decades.
    """
    return start * (end / start) ** p


def _steps(duration_s: float, dt_s: float) -> int:
    """Clamp the tick count so dt_s=0 (used in tests) does not divide by zero.

    When dt_s <= 0 the generator emits ``max(1, int(duration_s))`` ticks
    back-to-back with no sleep — the callsite can iterate quickly in a
    test harness.
    """
    if dt_s <= 0:
        return max(1, int(duration_s))
    return max(1, int(duration_s / dt_s))


def _maybe_sleep(dt_s: float) -> None:
    if dt_s > 0:
        time.sleep(dt_s)


def generate_vacuum(duration_s: float, dt_s: float = 1.0) -> Iterator[Reading]:
    steps = _steps(duration_s, dt_s)
    for i in range(steps):
        p = i / max(steps - 1, 1)
        pressure = _exp_decay(p, 1e-3, 1e-7)
        yield _reading("VSP63D_1/pressure", pressure, "mbar")
        for idx in range(1, 4):
            yield _reading(
                f"T{idx}",
                290.0 + random.uniform(-0.05, 0.05),
                "K",
                instrument_id="LakeShore_1",
            )
        _maybe_sleep(dt_s)


def generate_cooldown(
    duration_s: float,
    dt_s: float = 1.0,
    *,
    include_prediction: bool = False,
    ci_level_pct: float = 67.0,
) -> Iterator[Reading]:
    steps = _steps(duration_s, dt_s)
    for i in range(steps):
        p = i / max(steps - 1, 1)
        t = _tanh_ramp(p, 290.0, 4.0)
        yield _reading("VSP63D_1/pressure", 1e-6, "mbar")
        for idx in range(1, 4):
            yield _reading(
                f"T{idx}",
                t + random.uniform(-0.1, 0.1),
                "K",
                instrument_id="LakeShore_1",
            )
        if include_prediction:
            # Emit a prediction reading every step so the forward
            # horizon updates continuously in the GUI.
            central = t
            spread = max(0.5, 0.05 * t)
            meta = {
                "kind": "cooldown_prediction",
                "ci_level_pct": ci_level_pct,
                "lower_ci": central - spread,
                "upper_ci": central + spread,
            }
            yield _reading(
                "analytics/cooldown_prediction",
                central,
                "K",
                instrument_id="analytics",
                metadata=meta,
            )
        _maybe_sleep(dt_s)


def generate_warmup(duration_s: float, dt_s: float = 1.0) -> Iterator[Reading]:
    steps = _steps(duration_s, dt_s)
    for i in range(steps):
        p = i / max(steps - 1, 1)
        t = _tanh_ramp(p, 4.0, 290.0)
        yield _reading("VSP63D_1/pressure", 1e-6, "mbar")
        for idx in range(1, 4):
            yield _reading(
                f"T{idx}",
                t + random.uniform(-0.1, 0.1),
                "K",
                instrument_id="LakeShore_1",
            )
        _maybe_sleep(dt_s)


def generate_measurement(duration_s: float, dt_s: float = 1.0) -> Iterator[Reading]:
    steps = _steps(duration_s, dt_s)
    for _ in range(steps):
        r_thermal = 1.5e-3 * (1.0 + random.uniform(-0.05, 0.05))
        yield _reading("analytics/r_thermal", r_thermal, "K/W", instrument_id="analytics")
        for idx in range(1, 4):
            yield _reading(
                f"T{idx}",
                4.0 + random.uniform(-0.02, 0.02),
                "K",
                instrument_id="LakeShore_1",
            )
        yield _reading("Keithley_1/smua/power", 0.5, "W", instrument_id="Keithley_1")
        _maybe_sleep(dt_s)


def generate(scenario: str, duration_s: float, *, ci_level_pct: float = 67.0) -> Iterator[Reading]:
    """Dispatch to the right scenario generator."""
    if scenario == "vacuum":
        yield from generate_vacuum(duration_s)
    elif scenario == "cooldown":
        yield from generate_cooldown(duration_s, include_prediction=False)
    elif scenario == "warmup":
        yield from generate_warmup(duration_s)
    elif scenario == "measurement":
        yield from generate_measurement(duration_s)
    elif scenario == "cooldown_with_prediction":
        yield from generate_cooldown(
            duration_s,
            include_prediction=True,
            ci_level_pct=ci_level_pct,
        )
    else:
        raise ValueError(f"unknown scenario: {scenario}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Публикация синтетических Reading для проверки analytics и phase-aware раскладок."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Сценарии:\n"
            "  vacuum                    — откачка 1e-3 → 1e-7 мбар\n"
            "  cooldown                  — охлаждение 290 → 4 K\n"
            "  warmup                    — отогрев 4 → 290 K\n"
            "  measurement               — стационар, R_thermal вокруг 1.5e-3\n"
            "  cooldown_with_prediction  — cooldown + прогноз CI\n\n"
            "Пример: python -m tools.mock_scenario --scenario cooldown --duration 600"
        ),
    )
    parser.add_argument(
        "--scenario",
        choices=_SCENARIOS,
        required=True,
        help="Какой сценарий публиковать.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Длительность сценария в секундах (default: 60).",
    )
    parser.add_argument(
        "--ci-level",
        type=float,
        default=67.0,
        help="Процент доверительного интервала для cooldown_with_prediction (default: 67).",
    )
    parser.add_argument(
        "--address",
        default=DEFAULT_PUB_ADDR,
        help=f"ZMQ PUB адрес (default: {DEFAULT_PUB_ADDR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не биндить сокет; вывести первые 10 Reading и выйти.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Логировать каждую публикацию.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    gen = generate(args.scenario, args.duration, ci_level_pct=args.ci_level)

    if args.dry_run:
        for i, reading in enumerate(gen):
            print(reading)
            if i >= 9:
                break
        return 0

    count = 0
    with publisher_socket(args.address) as sock:
        logger.info(
            "PUB bound to %s; scenario=%s duration=%.1fs",
            args.address,
            args.scenario,
            args.duration,
        )
        # Small sleep so late-joining subscribers don't miss the first
        # few readings due to the ZMQ slow-joiner problem.
        time.sleep(0.3)
        for reading in gen:
            publish_reading(sock, reading)
            count += 1
            if args.verbose:
                logger.debug("PUB %s %s=%s", reading.channel, reading.unit, reading.value)
    logger.info("Published %d readings.", count)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
