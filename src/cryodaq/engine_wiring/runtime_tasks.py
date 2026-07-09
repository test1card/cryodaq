"""Долгоживущие рантайм-задачи движка, вынесенные из ``_run_engine``.

Каждый feed/tick-цикл был вложенным замыканием ``_run_engine``, захватывавшим
локальные переменные движка. Здесь это модульные функции, берущие зависимости
явно, — импортируемые и тестируемые в изоляции. Логгер — тот же
``cryodaq.engine``, чтобы вывод в лог не менялся. Модуль не импортирует
``engine`` (без циклов) и не тянет ``cryodaq.agents``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from cryodaq.core.alarm_v2 import tick_alarm
from cryodaq.core.event_bus import EngineEvent
from cryodaq.drivers.base import Reading
from cryodaq.storage.cold_rotation import seconds_until_next

logger = logging.getLogger("cryodaq.engine")


# ─────────────────────── Alarm-v2 feed + ring buffer ──────────────────────


async def _alarm_v2_feed_loop(
    queue: asyncio.Queue[Reading],
    state_tracker: Any,
    rate_estimator: Any,
) -> None:
    """Feed alarm-v2 channel_state + rate_estimator from a DataBroker queue.

    A2(a): a single malformed reading raising inside ``state_tracker.update``
    (or the rate push) must NOT kill the whole feed task — that silently
    blinds alarm-v2 until restart. Guard per iteration: log and move on. The
    outer ``CancelledError`` handler keeps clean-shutdown semantics intact.
    """
    try:
        while True:
            reading = await queue.get()
            try:
                state_tracker.update(reading)
                # NaN-доктрина (HI-2): годно ⇔ статус OK-класса И значение
                # конечно; не годное показание (flapping sensor: NaN/inf или
                # статус ошибки) не отравляет OLS-окно rate-оценщика.
                if reading.is_usable():
                    rate_estimator.push(
                        reading.channel,
                        reading.timestamp.timestamp(),
                        reading.value,
                    )
            except Exception:
                logger.exception(
                    "Alarm v2 feed: ошибка обработки показания %s",
                    getattr(reading, "channel", "?"),
                )
    except asyncio.CancelledError:
        return


class _AlarmRingBuffer:
    """In-memory ring buffer of recent ``alarm_fired`` events (A3b sound).

    Feeds the GUI's ``recent_alarms`` poll — the GUI has no other way to
    see engine-side alarm_fired events since only Readings cross the ZMQ
    PUB stream. Bounded: the GUI polls every ~2s and only ever needs
    "what's new since my last seq", so a small history is enough and
    memory can't grow unbounded through a busy alarm episode.
    """

    def __init__(self, maxlen: int = 50) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = 0

    def record(self, event: EngineEvent) -> None:
        """Append an ``alarm_fired`` EngineEvent, assigning the next seq."""
        self._seq += 1
        payload = event.payload
        self._entries.append(
            {
                "seq": self._seq,
                "alarm_id": str(payload.get("alarm_id", "")),
                "level": str(payload.get("level", "")),
                "message": str(payload.get("message", "")),
                "ts": event.timestamp.timestamp(),
            }
        )

    def since(self, since_seq: int) -> dict[str, Any]:
        """Return the current head seq plus every entry newer than *since_seq*.

        Ring-buffer semantics: if *since_seq* predates the oldest retained
        entry (buffer wrapped while the GUI wasn't polling), only what's
        still retained comes back — treated by the GUI the same as "no new
        alarms", which is fine: anything that fell off was already old.
        """
        return {
            "seq": self._seq,
            "alarms": [e for e in self._entries if e["seq"] > since_seq],
        }


async def _alarm_ring_buffer_loop(
    queue: asyncio.Queue[EngineEvent],
    ring: _AlarmRingBuffer,
) -> None:
    """Drain *queue* onto *ring*, one ``alarm_fired`` event at a time (A3b).

    Mirrors ``_alarm_v2_feed_loop``: queue and buffer passed in so this is
    unit-testable without engine wiring, per-event guarded so one bad event
    can't kill the feed the GUI sound poller depends on.
    """
    try:
        while True:
            event = await queue.get()
            if event.event_type != "alarm_fired":
                continue
            try:
                ring.record(event)
            except Exception:
                logger.exception("Alarm ring buffer: ошибка записи события")
    except asyncio.CancelledError:
        return


def _format_diag_telegram_messages(
    new_events: list[Any],
    aggregation_threshold: int = 3,
) -> list[tuple[str, str]]:
    """Build the Telegram dispatch ``(task_name, message)`` pairs for a batch
    of sensor-diagnostic events.

    F10/F20: extracted from the ``_sensor_diag_tick`` closure so the message
    formatting — including the F20 aggregation rule (more than
    *aggregation_threshold* simultaneous events collapse into one batch
    summary; otherwise one message per event) — is unit-testable without the
    engine loop. Returns pairs in dispatch order (empty when nothing to send).
    Behaviour-preserving, including the asyncio task names.
    """
    if not new_events:
        return []
    if len(new_events) > aggregation_threshold:
        criticals = [e for e in new_events if e.level == "CRITICAL"]
        warnings = [e for e in new_events if e.level == "WARNING"]
        parts: list[str] = []
        if criticals:
            names = ", ".join(
                e.channels[0] if e.channels else e.alarm_id for e in criticals
            )
            parts.append(f"{len(criticals)} channels critical: {names}")
        if warnings:
            names = ", ".join(
                e.channels[0] if e.channels else e.alarm_id for e in warnings
            )
            parts.append(f"{len(warnings)} channels warning: {names}")
        return [("diag_tg_batch", "⚠ Diagnostic alarm batch:\n" + "\n".join(parts))]
    return [
        (
            f"diag_tg_{event.alarm_id}",
            f"⚠ [{event.level}] {event.alarm_id}\n{event.message}",
        )
        for event in new_events
    ]


# ─────────────────────────── Runtime task loops ───────────────────────────


async def cold_rotation_scheduler(cold_rotation_service: Any, cold_rotation_schedule: Any) -> None:
    """Run rotation once per day at cold_rotation.schedule_time."""
    assert cold_rotation_service is not None
    while True:
        await asyncio.sleep(seconds_until_next(cold_rotation_schedule, datetime.now(UTC)))
        try:
            rotated = await cold_rotation_service.run_once()
            if rotated:
                logger.info(
                    "ColdRotation: вытеснено %d суточных файлов в холодное хранилище",
                    len(rotated),
                )
        except Exception:
            logger.exception("ColdRotation: проход ротации завершился ошибкой")


async def track_runtime_signals(broker: Any, adaptive_throttle: Any) -> None:
    queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
    try:
        while True:
            adaptive_throttle.observe_runtime_signal(await queue.get())
    except asyncio.CancelledError:
        return


async def alarm_v2_feed_readings(broker: Any, state_tracker: Any, rate_estimator: Any) -> None:
    """Подписаться на DataBroker и кормить v2 channel_state + rate_estimator."""
    queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
    # A2(a): loop body extracted to the importable, per-reading-guarded
    # _alarm_v2_feed_loop so a single bad reading can't kill the feed.
    await _alarm_v2_feed_loop(queue, state_tracker, rate_estimator)


async def alarm_ring_feed(event_bus: Any, alarm_ring: _AlarmRingBuffer) -> None:
    """Подписаться на EventBus и наполнять A3b-буфер тревог для GUI-звука."""
    queue = await event_bus.subscribe("alarm_ring_buffer", maxsize=200)
    await _alarm_ring_buffer_loop(queue, alarm_ring)


async def _alarm_v2_tick_configs(
    *,
    configs: Any,
    phase_provider: Any,
    evaluator: Any,
    state_mgr: Any,
    telegram_bot: Any,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    event_bus: Any,
    experiment_manager: Any,
) -> None:
    # A2(a): guard the once-per-tick phase lookup — a raise here (it sits
    # outside the per-alarm try below) would kill the whole tick task.
    try:
        current_phase = phase_provider.get_current_phase()
    except Exception as exc:
        logger.error("Alarm v2 tick: ошибка получения фазы: %s", exc)
        return
    for alarm_cfg in configs:
        try:
            # Phase-filter -> evaluate -> process. Shared with tests via
            # cryodaq.core.alarm_v2.tick_alarm so suppression is covered
            # by the real production logic. Out-of-phase returns
            # (None, None) after clearing, so nothing dispatches below.
            event, transition = tick_alarm(
                alarm_cfg, current_phase, evaluator, state_mgr
            )
            if transition == "TRIGGERED" and event is not None:
                # GUI polls via alarm_v2_status command; optionally notify via Telegram
                if "telegram" in alarm_cfg.notify and telegram_bot is not None:
                    msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                    t = asyncio.create_task(
                        telegram_bot._send_to_all(msg),
                        name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
                    )
                    alarm_dispatch_tasks.add(t)
                    t.add_done_callback(alarm_dispatch_tasks.discard)
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_fired",
                        timestamp=datetime.now(UTC),
                        payload={
                            "alarm_id": event.alarm_id,
                            "level": event.level,
                            "message": event.message,
                            "channels": event.channels,
                            "values": event.values,
                        },
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )
            elif transition == "CLEARED":
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_cleared",
                        timestamp=datetime.now(UTC),
                        payload={"alarm_id": alarm_cfg.alarm_id},
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )
        except Exception as exc:
            logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)


async def alarm_v2_tick(
    *,
    engine_cfg: Any,
    configs: Any,
    phase_provider: Any,
    evaluator: Any,
    state_mgr: Any,
    broker: Any,
    telegram_bot: Any,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    event_bus: Any,
    experiment_manager: Any,
) -> None:
    """Периодически вычислять алармы v2 и диспетчеризировать события."""
    poll_s = engine_cfg.poll_interval_s
    while True:
        await asyncio.sleep(poll_s)
        if configs:
            await _alarm_v2_tick_configs(
                configs=configs,
                phase_provider=phase_provider,
                evaluator=evaluator,
                state_mgr=state_mgr,
                telegram_bot=telegram_bot,
                alarm_dispatch_tasks=alarm_dispatch_tasks,
                event_bus=event_bus,
                experiment_manager=experiment_manager,
            )
        # B2: republish the total active-alarm count every poll cycle
        # (not just when configs is non-empty) — this feeds
        # AdaptiveThrottle.observe_runtime_signal via the
        # "analytics/alarm_count" channel, which AlarmEngine v1 used to
        # own exclusively. Without this the throttle never learns an
        # alarm is active and keeps thinning archived data during a
        # fault. Counts alarms from ALL v2 sources sharing
        # state_mgr (global/phase alarms here, plus
        # CooldownAlarm/VacuumGuard/diagnostic alarms ticked elsewhere).
        await broker.publish(
            Reading.now(
                channel="analytics/alarm_count",
                value=float(len(state_mgr.get_active())),
                unit="",
                instrument_id="alarm_v2",
            )
        )


async def sensor_diag_feed(sensor_diag: Any, broker: Any) -> None:
    """Feed readings into SensorDiagnosticsEngine buffers."""
    if sensor_diag is None:
        return
    queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
    try:
        while True:
            reading: Reading = await queue.get()
            # NaN-доктрина: годно ⇔ статус OK-класса И значение конечно;
            # не годное показание не отравляет буферы диагностики.
            if reading.is_usable():
                sensor_diag.push(
                    reading.channel,
                    reading.timestamp.timestamp(),
                    reading.value,
                )
    except asyncio.CancelledError:
        return


async def sensor_diag_tick(
    *,
    sensor_diag: Any,
    sd_cfg: dict[str, Any],
    telegram_bot: Any,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    event_bus: Any,
    experiment_manager: Any,
) -> None:
    """Periodically recompute sensor diagnostics and dispatch alarm notifications."""
    if sensor_diag is None:
        return
    interval = sd_cfg.get("update_interval_s", 10)
    # v0.55.5: default False — sensor-health alarms route to GUI only
    # by policy; the hourly periodic_report carries a digest section.
    _notify_telegram = sd_cfg.get("notify_telegram", False)
    while True:
        await asyncio.sleep(interval)
        try:
            new_events = sensor_diag.update()
            if _notify_telegram and telegram_bot is not None and new_events:
                aggregation_threshold = sd_cfg.get("aggregation_threshold", 3)
                # F20 aggregation handled by _format_diag_telegram_messages.
                for _tg_name, _tg_msg in _format_diag_telegram_messages(
                    new_events, aggregation_threshold
                ):
                    t = asyncio.create_task(
                        telegram_bot._send_to_all(_tg_msg),
                        name=_tg_name,
                    )
                    alarm_dispatch_tasks.add(t)
                    t.add_done_callback(alarm_dispatch_tasks.discard)
            for _sd_ev in new_events:
                if _sd_ev.level.upper() == "CRITICAL":
                    await event_bus.publish(
                        EngineEvent(
                            event_type="sensor_anomaly_critical",
                            timestamp=datetime.now(UTC),
                            payload={
                                "alarm_id": _sd_ev.alarm_id,
                                "level": _sd_ev.level,
                                "channels": _sd_ev.channels,
                                "values": _sd_ev.values,
                                "message": _sd_ev.message,
                            },
                            experiment_id=experiment_manager.active_experiment_id,
                        )
                    )
        except Exception as exc:
            logger.error("SensorDiagnostics tick error: %s", exc)


async def vacuum_trend_feed(vacuum_trend: Any, vt_cfg: dict[str, Any], broker: Any) -> None:
    """Feed pressure readings into VacuumTrendPredictor."""
    if vacuum_trend is None:
        return
    pressure_channel = vt_cfg.get("pressure_channel", "")
    queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
    try:
        while True:
            reading: Reading = await queue.get()
            # Accept readings from the pressure channel or any mbar-unit reading
            if pressure_channel and reading.channel != pressure_channel:
                if reading.unit != "mbar":
                    continue
            elif not pressure_channel and reading.unit != "mbar":
                continue
            # NaN-доктрина: годно ⇔ статус OK-класса И значение конечно.
            # push сохраняет свою доменную защиту P <= 0 (log₁₀ не определён).
            if reading.is_usable():
                vacuum_trend.push(reading.timestamp.timestamp(), reading.value)
    except asyncio.CancelledError:
        return


async def vacuum_trend_tick(vacuum_trend: Any, vt_cfg: dict[str, Any]) -> None:
    """Periodically recompute vacuum trend prediction."""
    if vacuum_trend is None:
        return
    interval = vt_cfg.get("update_interval_s", 30)
    while True:
        await asyncio.sleep(interval)
        try:
            vacuum_trend.update()
        except Exception as exc:
            logger.error("VacuumTrendPredictor tick error: %s", exc)


async def leak_rate_feed(
    *,
    vt_cfg: dict[str, Any],
    broker: Any,
    leak_rate_estimator: Any,
    event_logger: Any,
) -> None:
    """Feed pressure readings into LeakRateEstimator; auto-finalize on window expiry."""
    pressure_channel = vt_cfg.get("pressure_channel", "")
    queue = await broker.subscribe("leak_rate_feed", maxsize=500)
    try:
        while True:
            reading: Reading = await queue.get()
            if pressure_channel and reading.channel != pressure_channel:
                continue
            if reading.unit != "mbar":
                continue
            if not leak_rate_estimator.is_active:
                continue
            leak_rate_estimator.add_sample(reading.timestamp, reading.value)
            if leak_rate_estimator.should_finalize():
                try:
                    result = leak_rate_estimator.finalize()
                    await event_logger.log_event(
                        "leak_rate",
                        f"Leak rate (auto): {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
                    )
                except (ValueError, Exception) as exc:  # noqa: BLE001
                    logger.error("Leak rate auto-finalize failed: %s", exc)
    except asyncio.CancelledError:
        return


async def cooldown_alarm_tick_loop(
    *,
    cooldown_cfg: dict[str, Any],
    cooldown_alarm: Any,
    state_mgr: Any,
    telegram_bot: Any,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    event_bus: Any,
    experiment_manager: Any,
) -> None:
    """Independent tick for CooldownAlarm at its own configured cadence (F-X v3)."""
    interval = float(cooldown_cfg.get("eval_interval_s", 30))
    _last_triggered_id = "cooldown_alarm"
    while True:
        await asyncio.sleep(interval)
        try:
            transition = await cooldown_alarm.tick()
        except Exception as exc:
            logger.error("CooldownAlarm tick error: %s", exc)
            continue
        if transition == "TRIGGERED":
            _active = state_mgr.get_active()
            # CooldownAlarm fires under "cooldown_alarm" OR "cooldown_watchdog"
            _ev = _active.get("cooldown_alarm") or _active.get("cooldown_watchdog")
            if _ev is not None:
                _last_triggered_id = _ev.alarm_id
                if telegram_bot is not None:
                    _pt = asyncio.create_task(
                        telegram_bot._send_to_all(
                            f"⚠ [{_ev.level}] {_ev.alarm_id}\n{_ev.message}"
                        ),
                        name=f"phys_alarm_tg_{_ev.alarm_id}",
                    )
                    alarm_dispatch_tasks.add(_pt)
                    _pt.add_done_callback(alarm_dispatch_tasks.discard)
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_fired",
                        timestamp=datetime.now(UTC),
                        payload={
                            "alarm_id": _ev.alarm_id,
                            "level": _ev.level,
                            "message": _ev.message,
                            "channels": _ev.channels,
                            "values": _ev.values,
                        },
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )
        elif transition == "CLEARED":
            await event_bus.publish(
                EngineEvent(
                    event_type="alarm_cleared",
                    timestamp=datetime.now(UTC),
                    payload={"alarm_id": _last_triggered_id},
                    experiment_id=experiment_manager.active_experiment_id,
                )
            )


async def vacuum_guard_tick_loop(
    *,
    vacuum_cfg: dict[str, Any],
    vacuum_guard: Any,
    state_mgr: Any,
    telegram_bot: Any,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    event_bus: Any,
    experiment_manager: Any,
) -> None:
    """Independent tick for VacuumGuard at its own configured cadence (F-X v3)."""
    interval = float(vacuum_cfg.get("eval_interval_s", 30))
    while True:
        await asyncio.sleep(interval)
        try:
            transition = await vacuum_guard.tick()
        except Exception as exc:
            logger.error("VacuumGuard tick error: %s", exc)
            continue
        if transition == "TRIGGERED":
            _active = state_mgr.get_active()
            _ev = _active.get("vacuum_guard")
            if _ev is not None:
                if telegram_bot is not None:
                    _pt = asyncio.create_task(
                        telegram_bot._send_to_all(
                            f"⚠ [{_ev.level}] {_ev.alarm_id}\n{_ev.message}"
                        ),
                        name="phys_alarm_tg_vacuum_guard",
                    )
                    alarm_dispatch_tasks.add(_pt)
                    _pt.add_done_callback(alarm_dispatch_tasks.discard)
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_fired",
                        timestamp=datetime.now(UTC),
                        payload={
                            "alarm_id": _ev.alarm_id,
                            "level": _ev.level,
                            "message": _ev.message,
                            "channels": _ev.channels,
                            "values": _ev.values,
                        },
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )
        elif transition == "CLEARED":
            await event_bus.publish(
                EngineEvent(
                    event_type="alarm_cleared",
                    timestamp=datetime.now(UTC),
                    payload={"alarm_id": "vacuum_guard"},
                    experiment_id=experiment_manager.active_experiment_id,
                )
            )


async def assistant_event_relay_loop(
    queue: asyncio.Queue[EngineEvent],
    zmq_pub: Any,
    relay_event_types: frozenset[str],
) -> None:
    while True:
        event = await queue.get()
        if event.event_type not in relay_event_types:
            continue
        await zmq_pub.publish_event(
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload,
            experiment_id=event.experiment_id,
        )
