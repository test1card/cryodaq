"""EngineQueryClient — read-only ZMQ REQ client for the assistant process.

B1 (agents/ process extraction): query adapters that used to hold direct
in-process references to live engine objects (``ExperimentManager``,
``AlarmStateManager``, ``CooldownService``, ...) now call the engine's
existing read-only REP command surface instead — the exact same commands
the GUI already uses to render state (``experiment_status``,
``alarm_v2_status``, ``get_vacuum_trend``, ``readings_history``, ...).

Ephemeral REQ-per-call, mirroring ``core/zmq_subprocess.py``'s
``cmd_forward_loop`` (the ZeroMQ Guide ch.4 "poll / timeout / close /
reopen" reliable request-reply pattern used everywhere else this codebase
talks REQ/REP): no shared REQ socket state to corrupt across calls.

Read-only by construction: every call here is one of the engine's existing
*query* actions (same vocabulary the GUI's ``send_command`` already uses);
nothing in this module ever sends a control/write command. That is what
keeps the assistant process's write path into the engine at zero, per the
ORCHESTRATION text-only/no-commands constraint — there is no auth token and
no mutating action name this client is ever asked to send.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import zmq
import zmq.asyncio

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_CMD_ADDR = "tcp://127.0.0.1:5556"
# Generous vs. the GUI's own 65 s outer budget (gui/zmq_client.py
# _CMD_REPLY_TIMEOUT_S) — assistant queries hit fast read-only commands,
# not experiment_finalize / report generation, so they don't need the
# slow-command envelope.
_DEFAULT_TIMEOUT_MS = 10_000


class EngineQueryClient:
    """Ephemeral REQ-per-call client for the engine's read-only REP commands."""

    def __init__(
        self,
        address: str = DEFAULT_ENGINE_CMD_ADDR,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._address = address
        self._timeout_ms = timeout_ms
        self._ctx = zmq.asyncio.Context.instance()

    async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Send one command, return the reply dict.

        Never raises — a transport failure (engine down, timeout, bad
        JSON) comes back as ``{"ok": False, "error": ...}`` so adapters
        can treat it exactly like an engine-side "no data" reply and
        degrade gracefully, matching the original adapters' own
        try/except-and-return-None contract.
        """
        sock = self._ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, self._timeout_ms)
        try:
            sock.connect(self._address)
            await sock.send_string(json.dumps(cmd))
            reply_raw = await sock.recv_string()
            reply = json.loads(reply_raw)
            return reply if isinstance(reply, dict) else {"ok": False, "error": "non-dict reply"}
        except Exception as exc:  # noqa: BLE001 — transport failure, not a bug
            logger.debug("EngineQueryClient: %s failed: %s", cmd.get("cmd"), exc)
            return {"ok": False, "error": str(exc)}
        finally:
            sock.close(linger=0)
