"""CompositeAdapter — parallel fetch of all engine state for composite_status."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.schemas import ChannelTrend, CompositeStatus

logger = logging.getLogger(__name__)

#: Landmark stages, by canonical id. The gauge is picked up by unit instead,
#: because its channel is not in channels.yaml and never has been.
_TREND_CHANNELS = frozenset({"Т11", "Т12"})
#: Six hours: long enough that a slow drift is visible, short enough that the
#: engine's 10000-sample reply still covers a useful part of it. The result
#: reports the span that actually arrived, not this number.
#: A DAY, not six hours. The question a pumped-down chamber raises — leak or
#: desorption — is answered by whether the rate decays, and six hours is not
#: enough to see that. It was six because ten thousand rows only reached back
#: five and a half hours anyway; with bucketing the window is real.
_TREND_WINDOW_MINUTES = 1440


class CompositeAdapter:
    """Parallel-fetches all adapters for composite_status queries.

    One failed adapter never blocks the others (return_exceptions=True).
    """

    def __init__(
        self,
        *,
        broker_snapshot,
        cooldown,
        vacuum,
        alarms,
        experiment,
        history=None,
    ) -> None:
        self._snapshot = broker_snapshot
        self._cooldown = cooldown
        self._vacuum = vacuum
        self._alarms = alarms
        self._experiment = experiment
        # Optional: the summary works without it and simply carries no trends.
        # Wired in 2026-09-07 so an answer can say where a number is going.
        self._history = history

    async def status(self) -> CompositeStatus:
        labeled_data, cd_eta, vac_eta, alarm_result, exp_status = await asyncio.gather(
            self._snapshot.latest_with_labels(),
            self._cooldown.eta(),
            # Configured target, not a hardcoded pressure — see VacuumAdapter.
            self._vacuum.eta_to_target(),
            self._alarms.active(),
            self._experiment.status(),
            return_exceptions=True,
        )

        snapshot_reason: str | None = None
        if isinstance(labeled_data, Exception):
            logger.warning("CompositeAdapter: snapshot failed: %s", labeled_data)
            snapshot_reason = f"live snapshot unavailable: {labeled_data}"
            labeled_data = {}
        elif not isinstance(labeled_data, dict):
            logger.warning("CompositeAdapter: snapshot had invalid type: %s", type(labeled_data).__name__)
            snapshot_reason = "live snapshot response is malformed"
            labeled_data = {}
        if isinstance(cd_eta, Exception):
            logger.warning("CompositeAdapter: cooldown failed: %s", cd_eta)
            cd_eta = None
        if isinstance(vac_eta, Exception):
            logger.warning("CompositeAdapter: vacuum failed: %s", vac_eta)
            vac_eta = None
        if isinstance(alarm_result, Exception):
            logger.warning("CompositeAdapter: alarms failed: %s", alarm_result)
            alarm_result = None
        if isinstance(exp_status, Exception):
            logger.warning("CompositeAdapter: experiment failed: %s", exp_status)
            exp_status = None

        snapshot_empty = len(labeled_data) == 0

        # Only channels the operator has switched on. Reported 2026-09-07:
        # asked "what is happening", the assistant listed Т17-Т24 (mirrors,
        # suspension, frame — `visible: false`, `thermal_zone:
        # disconnected_reserve`, all reading the Lakeshore no-sensor sentinel
        # -8.888e+88) and stated Т4 = 380.00 K as a temperature. Т4 is also
        # `visible: false`; the sensor sits at its rail.
        #
        # The rule already exists and two other consumers honour it —
        # intent_classifier.py and periodic_png.py both ask `is_visible`. This
        # loop was the one that did not, and its own comment said so: "from ALL
        # temperature channels". Unchecking a channel is the operator saying
        # this one is not part of the run; repeating it back as a reading is
        # not informing, it is noise that buries the four numbers that matter.
        #
        # Unknown channels stay visible, so derived and analytics channels,
        # which are not in channels.yaml, are unaffected.
        key_temps: dict[str, float | None] = {}
        current_pressure: float | None = None
        for ch, info in labeled_data.items():
            if info.get("visible") is False:
                continue
            unit = info.get("unit", "")
            val = info.get("value")
            display = info.get("display_name", ch)
            if unit == "K":
                key_temps[display] = val
            elif unit in ("mbar", "Pa") and current_pressure is None:
                current_pressure = val

        # Trends for the channels worth a derivative: the gauge, and the two
        # landmark stages. Not every channel — thirty slopes is noise, and the
        # cost is one history query each. Failures are contained per channel:
        # a trend that cannot be fetched is simply absent, never an exception
        # that costs the operator the whole summary.
        trends: dict[str, ChannelTrend] = {}
        if self._history is not None and labeled_data:
            wanted: list[tuple[str, str]] = []
            for ch, info in labeled_data.items():
                if info.get("visible") is False:
                    continue
                unit = info.get("unit", "")
                display = info.get("display_name", ch)
                if unit in ("mbar", "Pa") or ch in _TREND_CHANNELS or display in _TREND_CHANNELS:
                    wanted.append((ch, display))
            if wanted:
                fetched = await asyncio.gather(
                    *(self._history.trend(ch, _TREND_WINDOW_MINUTES) for ch, _ in wanted),
                    return_exceptions=True,
                )
                for (_, display), result in zip(wanted, fetched, strict=True):
                    if isinstance(result, Exception) or result is None:
                        continue
                    trends[display] = result

        active_alarms = getattr(alarm_result, "active", []) if alarm_result is not None else []

        if (
            vac_eta is not None
            and getattr(vac_eta, "available", True)
            and vac_eta.current_mbar is None
            and current_pressure is not None
        ):
            vac_eta.current_mbar = current_pressure

        # Snapshot age for defensive empty-snapshot messaging
        snapshot_age_s: float | None = None
        if hasattr(self._snapshot, "oldest_age_s"):
            try:
                snapshot_age_s = await self._snapshot.oldest_age_s()
            except Exception:
                pass

        return CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=exp_status,
            cooldown_eta=cd_eta,
            vacuum_eta=vac_eta,
            active_alarms=active_alarms,
            key_temperatures=key_temps,
            current_pressure=current_pressure,
            trends=trends,
            snapshot_empty=snapshot_empty,
            snapshot_age_s=snapshot_age_s,
            alarms_available=alarm_result is not None and getattr(alarm_result, "available", True),
            available=snapshot_reason is None,
            stale=snapshot_reason is not None,
            reason=snapshot_reason,
        )
