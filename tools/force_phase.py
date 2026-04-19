"""tools/force_phase.py — push an experiment phase transition to the engine.

Dispatches ``{"cmd": "experiment_advance_phase", "target": "<name>"}``
over the engine's REQ/REP command port (5556 by default). The engine
must be running — this tool does NOT fake phase state, it pokes the
real state machine so phase-aware AnalyticsView / PhaseAwareWidget
swap their layouts for real.

Canonical phase names match ``cryodaq.core.experiment.ExperimentPhase``:

- ``preparation``
- ``vacuum``
- ``cooldown``
- ``measurement``
- ``warmup``
- ``teardown``    (the enum's name for the disassembly phase)

Usage::

    python -m tools.force_phase cooldown
    python -m tools.force_phase measurement
"""

from __future__ import annotations

import argparse
import logging
import sys

from cryodaq.core.experiment import ExperimentPhase
from tools._zmq_helpers import DEFAULT_CMD_ADDR, send_command

logger = logging.getLogger("force_phase")

_VALID_PHASES: tuple[str, ...] = tuple(p.value for p in ExperimentPhase)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Принудительный переход в указанную фазу эксперимента через "
            "ZMQ REQ на порт engine (5556). Требует запущенного engine."
        ),
        epilog=("Пример: python -m tools.force_phase cooldown\nValid: " + ", ".join(_VALID_PHASES)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "phase",
        choices=_VALID_PHASES,
        help="Имя фазы (из ExperimentPhase).",
    )
    parser.add_argument(
        "--address",
        default=DEFAULT_CMD_ADDR,
        help=f"ZMQ REQ адрес engine (default: {DEFAULT_CMD_ADDR}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Сколько секунд ждать ответ engine (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    cmd = {"cmd": "experiment_advance_phase", "target": args.phase}
    try:
        reply = send_command(cmd, address=args.address, timeout_s=args.timeout)
    except TimeoutError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error: %s", exc)
        return 1

    if not isinstance(reply, dict) or not reply.get("ok", False):
        logger.error("Engine отклонил переход: %s", reply)
        return 2
    logger.info("Phase → %s OK (%s)", args.phase, reply)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
