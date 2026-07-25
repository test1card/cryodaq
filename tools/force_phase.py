"""tools/force_phase.py — push an experiment phase transition to the engine.

Discovers the live engine's mutation capability, then dispatches one
``experiment_advance_phase`` command with the canonical ``phase`` and exact
``experiment_id`` over the engine's REQ/REP command port (5556 by default).
The engine must be running — this tool does NOT fake phase state, it pokes the
real state machine so phase-aware AnalyticsView / PhaseAwareWidget swap their
layouts for real. A rejected mutation is never replayed automatically.

Canonical phase names match ``cryodaq.core.experiment.ExperimentPhase``:

- ``preparation``
- ``vacuum``
- ``cooldown``
- ``measurement``
- ``warmup``
- ``teardown``    (the enum's name for the disassembly phase)

Usage::

    python -m tools.force_phase cooldown --expected-experiment-id <id>
    python -m tools.force_phase measurement --expected-experiment-id <id>
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from cryodaq.core.command_authority import (
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_PROTOCOL_MAJOR,
    MUTATION_RECEIPT_SCHEMA,
    valid_capability_token,
)
from cryodaq.core.experiment import ExperimentPhase
from tools._zmq_helpers import DEFAULT_CMD_ADDR, send_command

logger = logging.getLogger("force_phase")

_VALID_PHASES: tuple[str, ...] = tuple(p.value for p in ExperimentPhase)
_MUTATION_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "accepted",
        "server_protocol_major",
        "required_capability",
        "capability_token",
    }
)


def _mutation_envelope(response: object) -> dict[str, Any]:
    """Validate one live-engine capability receipt and return its envelope."""

    if type(response) is not dict or response.get("ok") is not True:
        raise ValueError("mutation capability discovery failed")
    receipt = response.get("compatibility_receipt")
    if type(receipt) is not dict or set(receipt) != _MUTATION_RECEIPT_KEYS:
        raise ValueError("mutation capability receipt is malformed")
    token = receipt.get("capability_token")
    if (
        receipt.get("schema") != MUTATION_RECEIPT_SCHEMA
        or receipt.get("accepted") is not True
        or type(receipt.get("server_protocol_major")) is not int
        or receipt.get("server_protocol_major") != MUTATION_PROTOCOL_MAJOR
        or receipt.get("required_capability") != ENGINE_MUTATION_CAPABILITY
        or not valid_capability_token(token)
    ):
        raise ValueError("mutation capability receipt is incompatible")
    return {
        "protocol_major": MUTATION_PROTOCOL_MAJOR,
        "mutation_capability": ENGINE_MUTATION_CAPABILITY,
        "capability_token": token,
    }


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
    parser.add_argument(
        "--expected-experiment-id",
        required=True,
        help="Exact active experiment identity required by the engine.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    try:
        discovery = send_command(
            {"cmd": "mutation_capabilities"},
            address=args.address,
            timeout_s=args.timeout,
        )
        envelope = _mutation_envelope(discovery)
        cmd = {
            "cmd": "experiment_advance_phase",
            "phase": args.phase,
            "experiment_id": args.expected_experiment_id,
            **envelope,
        }
        reply = send_command(cmd, address=args.address, timeout_s=args.timeout)
    except TimeoutError as exc:
        logger.error("%s", exc)
        return 1
    except ValueError as exc:
        logger.error("Engine mutation capability rejected: %s", exc)
        return 2
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
