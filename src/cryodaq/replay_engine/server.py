"""Replay engine server — ZMQ-compatible replacement for cryodaq.engine in replay mode.

Binds PUB on 5555 (same as real engine) and REP on 5556.
The GUI's ZMQ bridge subprocess connects to these sockets unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import secrets
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.command_authority import (
    MUTATION_PROTOCOL_MAJOR,
    MUTATION_RECEIPT_SCHEMA,
    REPLAY_LOCAL_MUTATION_ACTIONS,
    REPLAY_MUTATION_CAPABILITY,
    is_exact_safe_direction_envelope,
    is_ordinary_command_endpoint_admitted,
    strip_mutation_envelope,
    valid_capability_token,
)
from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_SAFE_CMD_ADDR,
    CommandAuthorityRegistry,
    ZMQCommandIngressPair,
    ZMQCommandIngressTerminalFailure,
    ZMQCommandServer,
    ZMQPublisher,
)
from cryodaq.core.zmq_endpoints import require_distinct_loopback_tcp_endpoints
from cryodaq.drivers.base import Reading
from cryodaq.paths import get_config_dir, get_project_root
from cryodaq.replay_engine.sources import resolve_source

#: Sentinel channel for the test-only PUB-readiness probe
#: (:meth:`ReplayEngine.publish_readiness_probe`). Deliberately un-instrument-like
#: so it never collides with a real channel and is trivially filtered by SUBs.
READINESS_PROBE_CHANNEL = "__replay_pub_probe__"

logger = logging.getLogger("cryodaq.replay_engine")

_WATCHDOG_INTERVAL_S = 30.0
_REPLAY_READY_SCHEMA = "cryodaq.replay_ready.v2"
_REPLAY_CREATE_KEYS = frozenset(
    {"cmd", "title", "sample", "operator", "start_time", "description", "notes", "custom_fields"}
)
_REPLAY_ADVANCE_KEYS = frozenset({"cmd", "phase", "operator", "experiment_id", "expected_experiment_id"})
_REPLAY_TEXT_MAX = 4096
_REPLAY_CUSTOM_FIELDS_MAX_BYTES = 64 * 1024


def _check_port_available(addr: str, *, force: bool) -> None:
    """Refuse to start if a ZMQ TCP port is already bound (spec Q1).

    Without --force-replay, raises RuntimeError if another process holds the
    port.  This prevents the replay engine from silently stealing ports from
    a running real engine after it frees them via _bind_with_retry retries.
    Wildcard bind addresses (tcp://*:N, tcp://0.0.0.0:N) are normalized to
    127.0.0.1 for the connectivity check.
    """
    if force:
        return
    try:
        _, hostport = addr.rsplit("//", 1)
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
        # Normalize wildcard bind addresses → loopback for connectivity check.
        check_host = "127.0.0.1" if host in ("*", "", "0.0.0.0") else host
    except (ValueError, AttributeError):
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            in_use = sock.connect_ex((check_host, port)) == 0
    except OSError:
        return  # Resolution or network error — skip check, don't block startup
    if in_use:
        raise RuntimeError(
            f"[spec Q1] Port {port} ({addr}) is already in use — "
            f"another engine is likely running. "
            f"Stop the real engine first, or pass --force-replay to override."
        )


async def _await_settlement_task(task: asyncio.Task[Any]) -> bool:
    """Await one owner-settlement task to terminal despite repeated cancellation.

    Returns whether this waiter received cancellation while settlement was in
    progress. The caller can then propagate cancellation only after the owner
    task has either succeeded or raised a settlement failure.
    """

    cancellation_seen = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancellation_seen = True
    task.result()
    return cancellation_seen


# Commands that mutate hardware state — always rejected in replay mode.
_READONLY_PREFIXES: tuple[str, ...] = (
    "set_target",
    "keithley_",
    "experiment.",  # F30 query agent subspace (experiment.fetch / .list)
    "source_on",
    "source_off",
    "emergency_off",
    "safety_",
    "calibration_",
    "shift_",
    "operator_log_add",
)

# F-ReplayPhases (v0.55.9): experiment_* commands rejected by default in
# replay (they would create real artifacts on top of historical data),
# except for these phase-tracking commands which create only metadata
# markers. The blanket "experiment_" prefix that was previously in
# _READONLY_PREFIXES has been split out so the allowlist below can
# carve out the demo-friendly phase commands.
_REPLAY_ALLOWED_EXPERIMENT_CMDS: frozenset[str] = frozenset(
    {
        "experiment_create_retroactive",
        "experiment_advance_phase",
    }
)


def _is_command_blocked(cmd: str) -> bool:
    """Return True if ``cmd`` should be rejected in replay mode.

    Hard-rejected prefixes (all hardware-mutating) always block. The
    ``experiment_*`` namespace defaults to rejection except for the
    explicit allowlist of phase-tracking commands. Everything else
    falls through and is handled by the dispatcher (or rejected
    upstream if unknown).
    """
    if any(cmd.startswith(p) for p in _READONLY_PREFIXES):
        return True
    if cmd.startswith("experiment_"):
        return cmd not in _REPLAY_ALLOWED_EXPERIMENT_CMDS
    return False


def _configured_instrument_poll_intervals_s() -> dict[str, float]:
    """Each configured instrument's poll cadence, for replay publishing.

    The replay publisher stamps ``producer_interval_s`` on a raw driver feed
    that does not already carry its own declaration, exactly as the live engine
    does (engine.py configures ``configure_instrument_poll_intervals_s`` from
    the same instruments config). Replay reads the local override first, then
    the base file, and validates entries without constructing any driver. A
    missing or invalid config yields an empty mapping rather than blocking
    replay: the SQLite replay sources already declare cadence from the recorded
    data, so this layer only covers feeds that carry no declaration of their
    own.
    """
    from cryodaq.drivers.registry import validate_instrument_entries

    config_dir = get_config_dir()
    path = config_dir / "instruments.local.yaml"
    if not path.exists():
        path = config_dir / "instruments.yaml"
    try:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        entries = validate_instrument_entries(raw.get("instruments", []) if isinstance(raw, dict) else [])
    except Exception as exc:
        logger.warning(
            "replay instrument poll intervals unavailable (%s); replay sources keep declaring recorded cadence",
            type(exc).__name__,
        )
        return {}
    intervals: dict[str, float] = {}
    for config in entries:
        try:
            interval_s = float(config.values["poll_interval_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(interval_s) and interval_s > 0.0:
            intervals[config.name] = interval_s
    return intervals


def _configured_instrument_driver_types_s() -> dict[str, str]:
    """Each configured instrument's code-owned driver type, for replay publishing.

    The replay publisher stamps ``driver_type`` on a raw driver feed exactly as
    the live engine does (engine.py configures ``configure_instrument_driver_types_s``
    from the same instruments config). Replay reads the local override first,
    then the base file, and validates entries without constructing any driver. A
    missing or invalid config yields an empty mapping rather than blocking
    replay.
    """
    from cryodaq.drivers.registry import validate_instrument_entries

    config_dir = get_config_dir()
    path = config_dir / "instruments.local.yaml"
    if not path.exists():
        path = config_dir / "instruments.yaml"
    try:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        entries = validate_instrument_entries(raw.get("instruments", []) if isinstance(raw, dict) else [])
    except Exception as exc:
        logger.warning(
            "replay instrument driver types unavailable (%s); replay feeds carry no code-owned driver identity",
            type(exc).__name__,
        )
        return {}
    return {config.name: config.spec.type_name for config in entries}


class ReplayEngine:
    """Minimal engine replacement: PUB readings, REP commands (read-only).

    Usage::

        engine = ReplayEngine(Path("data.db"), speed=10.0)
        await engine.start()
        await engine.run_source()   # blocks until source exhausted or stop()
        await engine.stop()
    """

    def __init__(
        self,
        source_path: Path,
        *,
        speed: float = 10.0,
        phase: str = "cooldown",
        loop: bool = False,
        pub_addr: str = DEFAULT_PUB_ADDR,
        cmd_addr: str = DEFAULT_CMD_ADDR,
        safe_cmd_addr: str = DEFAULT_SAFE_CMD_ADDR,
        cold_channel: str = "Т12",
        warm_channel: str = "Т11",
        force: bool = False,
        channel_map: dict[str, str] | None = None,
        launcher_ready_nonce: str | None = None,
        launcher_session_id: str | None = None,
    ) -> None:
        if launcher_ready_nonce is not None and (
            type(launcher_ready_nonce) is not str or re.fullmatch(r"[0-9a-f]{64}", launcher_ready_nonce) is None
        ):
            raise ValueError("launcher_ready_nonce must be exactly 64 lowercase hexadecimal characters")
        if launcher_session_id is not None and (
            type(launcher_session_id) is not str or re.fullmatch(r"[0-9a-f]{32}", launcher_session_id) is None
        ):
            raise ValueError("launcher_session_id must be exactly 32 lowercase hexadecimal characters")
        if (launcher_ready_nonce is None) != (launcher_session_id is None):
            raise ValueError("launcher replay readiness authority must be complete")
        if type(speed) not in {int, float} or isinstance(speed, bool) or not math.isfinite(speed) or speed < 0:
            raise ValueError("replay speed must be one finite non-negative number")
        require_distinct_loopback_tcp_endpoints(
            pub=pub_addr,
            ordinary_command=cmd_addr,
            safe_command=safe_cmd_addr,
        )
        self._source_path = source_path
        self._speed = float(speed)
        self._phase = phase
        self._loop = loop
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._safe_cmd_addr = safe_cmd_addr
        self._cold_channel = cold_channel
        self._warm_channel = warm_channel
        self._force = force
        self._channel_map = channel_map or None
        self._launcher_ready_nonce = launcher_ready_nonce
        self._launcher_session_id = launcher_session_id
        self._mutation_capability_token = secrets.token_urlsafe(32)

        self._pub: ZMQPublisher | None = None
        self._cmd: ZMQCommandIngressPair | None = None
        self._pub_queue: asyncio.Queue[Reading] | None = None
        self._source = None
        self._source_quiesced = False
        self._session_start: float = 0.0
        self._readings_published: int = 0
        self._watchdog_task: asyncio.Task | None = None
        self._broker: DataBroker | None = None
        self._lifecycle_started = False
        # CooldownService instance once wired (Any to avoid eager import).
        self._cooldown_service: Any | None = None
        # F-ReplayPhases (v0.55.9): metadata-only experiment manager so
        # the operator can drive phase transitions during a replay
        # session without touching the live ExperimentManager.
        from cryodaq.paths import get_data_dir
        from cryodaq.replay_engine.replay_experiment_stub import (
            ReplayExperimentStub,
        )

        self._exp_stub = ReplayExperimentStub(get_data_dir())

    def _runtime_ownership_present(self) -> bool:
        return bool(getattr(self, "_lifecycle_started", False)) or any(
            getattr(self, owner_name, None) is not None
            for owner_name in (
                "_source",
                "_broker",
                "_pub_queue",
                "_pub",
                "_cmd",
                "_cooldown_service",
                "_watchdog_task",
            )
        )

    async def start(self) -> None:
        if self._runtime_ownership_present():
            raise RuntimeError("replay runtime ownership already exists")
        try:
            # Spec Q1: refuse if ports are already bound (another engine running).
            _check_port_available(self._pub_addr, force=self._force)
            _check_port_available(self._cmd_addr, force=self._force)
            _check_port_available(self._safe_cmd_addr, force=self._force)

            self._session_start = time.time()
            self._source = resolve_source(
                self._source_path,
                speed=self._speed,
                loop=self._loop,
                cold_channel=self._cold_channel,
                warm_channel=self._warm_channel,
                channel_map=self._channel_map,
            )
            self._source_quiesced = False

            # F-ReplayPredictor: insert DataBroker between source and PUB queue so
            # CooldownService can subscribe to readings and publish derived metrics
            # (analytics/cooldown_predictor/cooldown_eta) back into the same fan-out.
            self._broker = DataBroker()
            self._pub_queue = await self._broker.subscribe("zmq_pub", maxsize=10_000)

            publisher = ZMQPublisher(
                self._pub_addr,
                applied_cold_stage_channel=self._cold_channel,
            )
            self._pub = publisher
            publisher.configure_instrument_poll_intervals_s(_configured_instrument_poll_intervals_s())
            publisher.configure_instrument_driver_types_s(_configured_instrument_driver_types_s())
            await publisher.start(self._pub_queue)
            logger.info("Replay transport owner started; owner=publisher")

            command_authority_registry = CommandAuthorityRegistry()
            command_server = ZMQCommandServer(
                self._cmd_addr,
                handler=self._handle_command,
                authority_registry=command_authority_registry,
                accepted_command_predicate=is_ordinary_command_endpoint_admitted,
            )
            safe_command_server = ZMQCommandServer(
                self._safe_cmd_addr,
                handler=self._handle_command,
                authority_registry=command_authority_registry,
                accepted_actions=frozenset({"replay_ready", "keithley_emergency_off", "launcher_shutdown"}),
                accepted_command_predicate=self._safe_endpoint_command_is_admitted,
            )
            command_ingress = ZMQCommandIngressPair(ordinary=command_server, safe=safe_command_server)
            self._cmd = command_ingress
            await command_ingress.start()
            logger.info("Replay transport owner started; owner=command_ingress")

            # Predictor availability remains optional, but a partially started
            # predictor must settle exactly before startup may continue.
            await self._maybe_start_cooldown_service()

            self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="replay_watchdog")
            command_ingress.require_healthy()
            self._lifecycle_started = True
        except asyncio.CancelledError:
            rollback = asyncio.create_task(self.stop(), name="replay_start_rollback")
            try:
                await _await_settlement_task(rollback)
            except BaseException as settlement_exc:
                logger.error(
                    "Replay startup rollback failed during cancellation; settlement_exception=%s",
                    type(settlement_exc).__name__,
                )
                raise RuntimeError("replay startup ownership settlement is incomplete") from None
            raise
        except Exception as exc:
            failure_type = type(exc).__name__
            rollback = asyncio.create_task(self.stop(), name="replay_start_rollback")
            try:
                cancellation_seen = await _await_settlement_task(rollback)
            except BaseException as settlement_exc:
                logger.error(
                    "Replay startup rollback failed; startup_exception=%s settlement_exception=%s",
                    failure_type,
                    type(settlement_exc).__name__,
                )
                raise RuntimeError("replay startup ownership settlement is incomplete") from None
            if cancellation_seen:
                raise asyncio.CancelledError()
            logger.error("Replay startup failed; exception=%s", failure_type)
            raise RuntimeError("replay startup failed") from None

    async def run_source(self) -> None:
        """Feed readings from the source into the broker.  Blocks until done."""
        if self._source is None or self._broker is None:
            raise RuntimeError("ReplayEngine.start() must be called before run_source()")
        logger.info("Replay source task started")
        await self._source.run(self._publish_reading)
        logger.info(
            "Replay source finished: %d readings published",
            self._readings_published,
        )

    def require_command_ingress_healthy(self) -> None:
        """Refuse readiness after either replay REP endpoint became terminal."""

        command_ingress = self._cmd
        if command_ingress is None:
            raise RuntimeError("replay command ingress is not owned")
        command_ingress.require_healthy()

    @property
    def command_ingress_terminal_failure(self) -> ZMQCommandIngressTerminalFailure | None:
        """Expose sticky pair proof synchronously across terminal-task races."""

        command_ingress = self._cmd
        if command_ingress is None:
            return None
        return command_ingress.terminal_failure

    async def wait_command_ingress_failure(self) -> ZMQCommandIngressTerminalFailure:
        """Wait for sticky replay command-ingress terminal proof."""

        command_ingress = self._cmd
        if command_ingress is None:
            raise RuntimeError("replay command ingress is not owned")
        return await command_ingress.wait_terminal_failure()

    async def publish_readiness_probe(self) -> None:
        """TEST-ONLY: publish one sentinel reading through the normal
        source → broker → PUB path.

        Lets a subscriber prove its subscription is live before
        :meth:`run_source` begins, replacing the non-deterministic fixed-sleep
        slow-joiner mitigation: a test calls this in a loop until its SUB
        actually receives a ``readings``-topic message whose channel is
        :data:`READINESS_PROBE_CHANNEL`. Production never calls this, so the
        live publish stream is byte-for-byte unchanged. Requires
        :meth:`start` to have run.
        """
        if self._broker is None:
            raise RuntimeError("start() must be called before publish_readiness_probe()")
        await self._broker.publish(Reading.now(READINESS_PROBE_CHANNEL, 0.0, ""))
        await asyncio.sleep(0)

    async def stop(self) -> None:
        had_runtime = self._runtime_ownership_present()
        was_started = bool(getattr(self, "_lifecycle_started", False))
        if not had_runtime:
            return
        command_owner = getattr(self, "_cmd", None)
        freeze_admission = getattr(command_owner, "freeze_admission", None)
        if callable(freeze_admission):
            freeze_admission()
        if self._watchdog_task is not None:
            watchdog_task = self._watchdog_task
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(
                    "Replay terminal task failed; owner=watchdog exception=%s",
                    type(exc).__name__,
                )
            self._watchdog_task = None
        if self._source is not None and not self._source_quiesced:
            try:
                self._source.stop()
            except Exception as exc:
                logger.error(
                    "Replay shutdown owner failed; owner=source exception=%s",
                    type(exc).__name__,
                )
                raise RuntimeError("replay source settlement is incomplete") from None
            self._source_quiesced = True
        # Stop CooldownService BEFORE tearing down ZMQ so its tasks unwind
        # cleanly while the broker is still alive.
        if self._cooldown_service is not None:
            cooldown_service = self._cooldown_service
            try:
                await cooldown_service.stop()
            except Exception as exc:
                logger.error(
                    "Replay shutdown owner failed; owner=cooldown_service exception=%s",
                    type(exc).__name__,
                )
                raise RuntimeError("replay cooldown-service settlement is incomplete") from None
            self._cooldown_service = None
        if self._cmd is not None:
            command_server = self._cmd
            try:
                await command_server.stop()
            except Exception as exc:
                logger.error(
                    "Replay shutdown owner failed; owner=command_server exception=%s",
                    type(exc).__name__,
                )
                raise RuntimeError("replay command-server settlement is incomplete") from None
            self._cmd = None
        if self._pub is not None:
            publisher = self._pub
            try:
                await publisher.stop()
            except Exception as exc:
                logger.error(
                    "Replay shutdown owner failed; owner=publisher exception=%s",
                    type(exc).__name__,
                )
                raise RuntimeError("replay publisher settlement is incomplete") from None
            self._pub = None
        self._source = None
        self._source_quiesced = False
        self._pub_queue = None
        self._broker = None
        self._lifecycle_started = False
        if was_started:
            logger.info("ReplayEngine stopped")
        else:
            logger.info("Replay startup owners settled")

    async def _watchdog_loop(self) -> None:
        """Periodic HEARTBEAT log matching engine.py _watchdog cadence (30 s)."""
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_INTERVAL_S)
                uptime_s = time.time() - self._session_start
                hours, remainder = divmod(int(uptime_s), 3600)
                minutes, secs = divmod(remainder, 60)
                logger.info(
                    "HEARTBEAT | uptime=%02d:%02d:%02d | readings_published=%d | speed=%.1fx",
                    hours,
                    minutes,
                    secs,
                    self._readings_published,
                    self._speed,
                )
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish_reading(self, reading: Reading) -> None:
        # Route every reading through the broker; the "zmq_pub" subscription
        # forwards to ZMQPublisher, and CooldownService (if wired) consumes
        # T_cold/T_warm to compute cooldown_eta.
        assert self._broker is not None
        self._readings_published += 1
        await self._broker.publish(reading)
        # broker.publish is non-yielding (put_nowait); at speed=0.0 the source
        # loop has no internal sleeps, so without this yield ZMQPublisher and
        # SUB consumers can starve until the entire source drains.
        await asyncio.sleep(0)

    async def _maybe_start_cooldown_service(self) -> None:
        """Best-effort wire-up of CooldownService onto the replay broker.

        Activates only when ``config/cooldown.yaml`` declares
        ``cooldown.enabled: true`` AND the predictor model file exists.
        Any failure logs a warning and leaves ``self._cooldown_service`` None;
        the predictor is not load-bearing for replay mode.

        Channel-name override: ``cooldown.yaml`` ships with real-lab channel
        names (Т7/Т5) which differ from the canonical replay channels
        (Т12/Т11). We force the replay channels here so the predictor sees
        the same names the source publishes — without mutating the on-disk
        config used by the real engine.
        """
        try:
            cooldown_cfg_path = get_config_dir() / "cooldown.yaml"
            if not cooldown_cfg_path.exists():
                logger.info("Replay predictor disabled; reason=config_missing")
                return
            with cooldown_cfg_path.open(encoding="utf-8") as fh:
                cd_raw = yaml.safe_load(fh) or {}
            cd_cfg: dict[str, Any] = dict(cd_raw.get("cooldown", {}))
            if not cd_cfg.get("enabled", False):
                logger.info("cooldown.enabled=False — predictor disabled in replay")
                return

            # Channel override (replay is the authority on channel names here).
            prev_cold = cd_cfg.get("channel_cold")
            prev_warm = cd_cfg.get("channel_warm")
            cd_cfg["channel_cold"] = self._cold_channel
            cd_cfg["channel_warm"] = self._warm_channel
            if prev_cold and prev_cold != self._cold_channel:
                logger.info("Replay cooldown channel override applied; role=cold")
            if prev_warm and prev_warm != self._warm_channel:
                logger.info("Replay cooldown channel override applied; role=warm")

            model_dir_str = cd_cfg.get("model_dir", "data/cooldown_model")
            model_dir = Path(model_dir_str)
            if not model_dir.is_absolute():
                model_dir = get_project_root() / model_dir
            if not (model_dir / "predictor_model.json").exists():
                logger.info("Replay predictor disabled; reason=model_missing")
                return

            from cryodaq.analytics.cooldown_service import CooldownService

            assert self._broker is not None
            self._cooldown_service = CooldownService(
                broker=self._broker,
                config=cd_cfg,
                model_dir=model_dir,
            )
            await self._cooldown_service.start()
            logger.info("Replay optional owner started; owner=cooldown_service")
        except asyncio.CancelledError:
            cooldown_service = self._cooldown_service
            if cooldown_service is not None:
                rollback = asyncio.create_task(
                    cooldown_service.stop(),
                    name="replay_cooldown_start_rollback",
                )
                try:
                    await _await_settlement_task(rollback)
                except BaseException as settlement_exc:
                    logger.error(
                        "Replay optional-owner rollback failed; owner=cooldown_service settlement_exception=%s",
                        type(settlement_exc).__name__,
                    )
                    raise RuntimeError("replay cooldown-service startup settlement is incomplete") from None
                self._cooldown_service = None
            raise
        except Exception as exc:
            failure_type = type(exc).__name__
            cooldown_service = self._cooldown_service
            if cooldown_service is not None:
                rollback = asyncio.create_task(
                    cooldown_service.stop(),
                    name="replay_cooldown_start_rollback",
                )
                try:
                    cancellation_seen = await _await_settlement_task(rollback)
                except BaseException as settlement_exc:
                    logger.error(
                        "Replay optional-owner rollback failed; owner=cooldown_service settlement_exception=%s",
                        type(settlement_exc).__name__,
                    )
                    raise RuntimeError("replay cooldown-service startup settlement is incomplete") from None
                self._cooldown_service = None
                if cancellation_seen:
                    raise asyncio.CancelledError()
            logger.warning(
                "Replay construction degraded; owner=cooldown_service exception=%s",
                failure_type,
            )

    def _replay_ready_receipt(self) -> dict[str, Any] | None:
        nonce = self._launcher_ready_nonce
        session_id = self._launcher_session_id
        if nonce is None or session_id is None:
            return None
        return {
            "schema": _REPLAY_READY_SCHEMA,
            "nonce": nonce,
            "session_id": session_id,
            "mode": "replay",
            "source": str(self._source_path),
            "speed": self._speed,
            "pid": os.getpid(),
            "pub_addr": self._pub_addr,
            "cmd_addr": self._cmd_addr,
            "safe_cmd_addr": self._safe_cmd_addr,
        }

    def _replay_ready_response(self, cmd: dict[str, Any]) -> dict[str, Any]:
        receipt = self._replay_ready_receipt()
        if receipt is None:
            return {"ok": False, "error_code": "replay_ready_unavailable"}
        if type(cmd) is not dict or set(cmd) != ({"cmd"} | set(receipt)):
            return {"ok": False, "error_code": "replay_ready_invalid"}
        for key, expected in receipt.items():
            value = cmd.get(key)
            if type(value) is not type(expected) or value != expected:
                return {"ok": False, "error_code": "replay_ready_mismatch"}
        return {"ok": True, **receipt}

    def _safe_endpoint_command_is_admitted(self, cmd: dict[str, Any]) -> bool:
        """Admit only the exact session proof and exact safe-direction envelopes."""

        if type(cmd) is not dict:
            return False
        if cmd.get("cmd") == "replay_ready":
            return self._replay_ready_response(cmd).get("ok") is True
        return is_exact_safe_direction_envelope(cmd)

    async def _handle_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")

        if action == "replay_ready":
            return self._replay_ready_response(cmd)

        if action == "mutation_capabilities":
            if set(cmd) != {"cmd"}:
                return {
                    "ok": False,
                    "error_code": "mutation_protocol_incompatible",
                    "error": "replay compatibility discovery requires one exact command",
                }
            session_id = self._launcher_session_id
            token = self._mutation_capability_token
            accepted = session_id is not None and valid_capability_token(token)
            compatibility_receipt: dict[str, Any] = {
                "schema": MUTATION_RECEIPT_SCHEMA,
                "accepted": accepted,
                "server_protocol_major": MUTATION_PROTOCOL_MAJOR,
                "required_capability": REPLAY_MUTATION_CAPABILITY,
            }
            if accepted:
                compatibility_receipt.update(
                    {
                        "capability_token": token,
                        "mode": "replay",
                        "session_id": session_id,
                        "source": str(self._source_path),
                        "speed": self._speed,
                    }
                )
            return {"ok": True, "compatibility_receipt": compatibility_receipt}

        if action in REPLAY_LOCAL_MUTATION_ACTIONS:
            token = self._mutation_capability_token
            compatible = (
                self._launcher_session_id is not None
                and type(cmd.get("protocol_major")) is int
                and cmd.get("protocol_major") == MUTATION_PROTOCOL_MAJOR
                and cmd.get("mutation_capability") == REPLAY_MUTATION_CAPABILITY
                and type(cmd.get("capability_token")) is str
                and valid_capability_token(token)
                and secrets.compare_digest(cmd["capability_token"], token)
            )
            if not compatible:
                return {
                    "ok": False,
                    "error_code": "mutation_protocol_incompatible",
                    "error": "replay mutation requires this exact replay-session capability",
                    "retry_safe": True,
                }
            cmd = strip_mutation_envelope(cmd)

        if action == "safety_status":
            return {
                "ok": False,
                "available": False,
                "reason": "REPLAY_MODE_READONLY",
            }

        if action == "current_phase":
            # F-ReplayPhases: prefer the stub's phase when an active
            # replay experiment exists, falling back to the static
            # session phase otherwise.
            stub_phase = self._exp_stub.current_phase
            experiment_error = self._exp_stub.availability_error
            return {
                "ok": experiment_error is None,
                "error": experiment_error,
                "phase": stub_phase or self._phase,
                # The replay stub owns the authoritative transition instant;
                # a session-start fallback would misreport a phase that has
                # not yet transitioned (or has no active experiment).
                "phase_started_at": self._exp_stub.phase_started_at,
            }

        if action == "/status":
            experiment_error = self._exp_stub.availability_error
            reply = {
                "ok": True,
                "mode": "replay",
                "replay_source": str(self._source_path),
                "replay_speed": self._speed,
                # F-ReplayPhases (v0.55.9): expose the replay-experiment
                # stub's state so GUI / archive surfaces can render the
                # active retroactive experiment without polling
                # experiment_status separately.
                "active_experiment": self._exp_stub.active_experiment,
                "experiment_available": experiment_error is None,
                "experiment_error": experiment_error,
                "phases": self._exp_stub.phases,
                "current_phase": self._exp_stub.current_phase or self._phase,
                "temperature_targets": {},
                "safety_state": None,
                "safety_available": False,
                "safety_unavailable_reason": "REPLAY_MODE_READONLY",
                "alarms": None,
                "alarms_available": False,
                "alarms_unavailable_reason": "REPLAY_MODE_READONLY",
            }
            launcher_session_id = getattr(self, "_launcher_session_id", None)
            if launcher_session_id is not None:
                reply["launcher_session_id"] = launcher_session_id
            return reply

        if action == "experiment_status":
            experiment_error = self._exp_stub.availability_error
            return {
                "ok": experiment_error is None,
                "error": experiment_error,
                "app_mode": "replay",
                # F-ReplayPhases: surface the replay-stub state where
                # previously this returned None unconditionally.
                "active_experiment": self._exp_stub.active_experiment,
                "current_phase": self._exp_stub.current_phase or self._phase,
                "phase_started_at": self._exp_stub.phase_started_at,
                "phases": self._exp_stub.phases,
                "run_records": [],
                "templates": [],
                "replay_source": str(self._source_path),
                "replay_speed": self._speed,
                "replay_session_id": getattr(self, "_launcher_session_id", None),
            }

        if action == "cooldown_history_get":
            return {"ok": False, "reason": "predictor_unavailable_in_replay"}

        # F-ReplayPhases (v0.55.9): allow phase-tracking experiment
        # commands. ``_is_command_blocked`` rejects everything else
        # under the existing prefix policy.
        if action == "experiment_create_retroactive":
            if set(cmd) != _REPLAY_CREATE_KEYS:
                return {"ok": False, "error_code": "replay_mutation_schema_invalid"}
            text_fields = ("title", "sample", "operator", "start_time", "description", "notes")
            if (
                any(
                    type(cmd.get(key)) is not str or len(cmd[key]) > _REPLAY_TEXT_MAX or not cmd[key].isprintable()
                    for key in text_fields
                )
                or not cmd["title"].strip()
                or not cmd["operator"].strip()
                or not cmd["start_time"].strip()
            ):
                return {"ok": False, "error_code": "replay_mutation_schema_invalid"}
            try:
                start_time = datetime.fromisoformat(cmd["start_time"])
                custom_fields_wire = json.dumps(
                    cmd["custom_fields"],
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error_code": "replay_mutation_schema_invalid"}
            if (
                start_time.utcoffset() is None
                or type(cmd["custom_fields"]) is not dict
                or any(type(key) is not str for key in cmd["custom_fields"])
                or len(custom_fields_wire) > _REPLAY_CUSTOM_FIELDS_MAX_BYTES
            ):
                return {"ok": False, "error_code": "replay_mutation_schema_invalid"}
            if self._exp_stub.active_experiment is not None:
                return {
                    "ok": False,
                    "error_code": "replay_experiment_already_active",
                    "error": "A replay experiment is already active.",
                }
            try:
                result = self._exp_stub.create_retroactive(
                    title=cmd["title"],
                    sample=cmd["sample"],
                    operator=cmd["operator"],
                    start_time=cmd["start_time"],
                    description=cmd["description"],
                    notes=cmd["notes"],
                    custom_fields=cmd["custom_fields"],
                )
                return {"ok": True, "experiment": result}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Replay experiment creation failed: exception=%s",
                    type(exc).__name__,
                )
                return {
                    "ok": False,
                    "error_code": "replay_experiment_create_failed",
                    "error": "Replay experiment creation failed.",
                }

        if action == "experiment_advance_phase":
            if set(cmd) != _REPLAY_ADVANCE_KEYS or any(
                type(cmd.get(key)) is not str
                or not cmd[key].strip()
                or len(cmd[key]) > 256
                or not cmd[key].isprintable()
                for key in _REPLAY_ADVANCE_KEYS - {"cmd"}
            ):
                return {"ok": False, "error_code": "replay_mutation_schema_invalid"}
            if cmd["experiment_id"] != cmd["expected_experiment_id"]:
                return {"ok": False, "error_code": "replay_experiment_identity_conflict"}
            if self._exp_stub.active_experiment is None:
                return {
                    "ok": False,
                    "error_code": "replay_experiment_inactive",
                    "error": "No active replay experiment.",
                }
            try:
                result = self._exp_stub.advance_phase(
                    phase=cmd["phase"],
                    operator=cmd["operator"],
                    expected_experiment_id=cmd["expected_experiment_id"],
                )
                return {"ok": True, "experiment": result}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Replay phase transition failed: exception=%s",
                    type(exc).__name__,
                )
                return {
                    "ok": False,
                    "error_code": "replay_phase_transition_failed",
                    "error": "Replay phase transition was refused.",
                }

        if _is_command_blocked(action):
            return {"ok": False, "reason": "REPLAY_MODE_READONLY"}

        # Unknown commands — reject as readonly rather than error
        return {"ok": False, "reason": "REPLAY_MODE_READONLY"}
