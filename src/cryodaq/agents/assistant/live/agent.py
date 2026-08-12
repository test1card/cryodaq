"""AssistantLiveAgent — local LLM agent observing engine events.

Service named Гемма (after the underlying Gemma 4 model via Ollama).
Subscribes to EventBus, generates Russian-language operator insights,
dispatches to Telegram + operator log + GUI insight panel.

Constraints (docs/ORCHESTRATION.md, "Product assistant boundary"):
- Uses only exact allowlisted read-only queries; never mutates engine state.
- Text-only output channels (Telegram, log, GUI).
- Fails gracefully if Ollama is unavailable — engine continues.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryodaq.agents.assistant.live.context_builder import ContextBuilder, normalize_sensor_health_summary
from cryodaq.agents.assistant.live.output_router import OutputRouter, OutputTarget, _is_delivered_outcome
from cryodaq.agents.assistant.live.prompts import (
    ALARM_SUMMARY_SYSTEM,
    ALARM_SUMMARY_USER,
    DIAGNOSTIC_SUGGESTION_SYSTEM,
    DIAGNOSTIC_SUGGESTION_USER,
    EXPERIMENT_FINALIZE_SYSTEM,
    EXPERIMENT_FINALIZE_USER,
    PERIODIC_REPORT_SYSTEM,
    PERIODIC_REPORT_USER,
    SENSOR_ANOMALY_SYSTEM,
    SENSOR_ANOMALY_USER,
    SHIFT_HANDOVER_SYSTEM,
    SHIFT_HANDOVER_USER,
    format_with_brand,
)
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaClient,
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.core.event_bus import EngineEvent, EventBus

logger = logging.getLogger(__name__)

_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class AssistantConfig:
    enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "gemma4:e4b"
    timeout_s: float = 60.0
    temperature: float = 0.3
    max_tokens: int = 2048  # gemma4:e4b is thinking-first; needs 2048+ for thought + response
    max_concurrent_inferences: int = 2
    max_calls_per_hour: int = 60
    alarm_fired_enabled: bool = True
    alarm_min_level: str = "WARNING"
    experiment_finalize_enabled: bool = True
    sensor_anomaly_critical_enabled: bool = True
    shift_handover_request_enabled: bool = True
    slice_a_notification: bool = True
    slice_b_suggestion: bool = False
    slice_c_campaign_report: bool = False
    output_telegram: bool = True
    output_operator_log: bool = True
    output_gui_insight: bool = True
    audit_enabled: bool = True
    audit_retention_days: int = 90
    num_ctx: int | None = None  # Ollama context window override; None = use model default
    audit_dir: Path = field(default_factory=lambda: Path("data/agents/assistant/audit"))
    brand_name: str = "Гемма"
    brand_emoji: str = "🤖"
    periodic_report_enabled: bool = True
    periodic_report_interval_minutes: int = 60
    periodic_report_skip_if_idle: bool = True
    periodic_report_min_events: int = 1
    query_enabled: bool = False
    query_intent_model: str | None = None
    query_format_model: str | None = None
    query_intent_temperature: float = 0.1
    query_format_temperature: float = 0.3
    query_intent_timeout_s: float = 20.0
    query_format_timeout_s: float = 40.0
    query_max_per_chat_per_hour: int = 60

    def get_periodic_report_interval_s(self) -> float:
        """Return interval in seconds, or 0 if periodic reports are disabled."""
        if not self.periodic_report_enabled:
            return 0.0
        return float(self.periodic_report_interval_minutes * 60)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssistantConfig:
        """Build from agent.yaml agent section dict."""
        cfg = cls()
        cfg.enabled = bool(d.get("enabled", True))
        ollama = d.get("ollama", {})
        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
        _num_ctx = ollama.get("num_ctx")
        cfg.num_ctx = int(_num_ctx) if _num_ctx is not None else None
        rl = d.get("rate_limit", {})
        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
        cfg.max_concurrent_inferences = int(rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences))
        triggers = d.get("triggers", {})
        alarm_t = triggers.get("alarm_fired", {})
        if isinstance(alarm_t, dict):
            cfg.alarm_fired_enabled = bool(alarm_t.get("enabled", cfg.alarm_fired_enabled))
            raw_level = str(alarm_t.get("min_level", cfg.alarm_min_level)).upper()
            if raw_level not in _MIN_LEVELS:
                raise ValueError(f"alarm_min_level must be one of {list(_MIN_LEVELS)}, got {raw_level!r}")
            cfg.alarm_min_level = raw_level
        exp_t = triggers.get("experiment_finalize", {})
        if isinstance(exp_t, dict):
            cfg.experiment_finalize_enabled = bool(exp_t.get("enabled", cfg.experiment_finalize_enabled))
        sa_t = triggers.get("sensor_anomaly_critical", {})
        if isinstance(sa_t, dict):
            cfg.sensor_anomaly_critical_enabled = bool(sa_t.get("enabled", cfg.sensor_anomaly_critical_enabled))
        sh_t = triggers.get("shift_handover_request", {})
        if isinstance(sh_t, dict):
            cfg.shift_handover_request_enabled = bool(sh_t.get("enabled", cfg.shift_handover_request_enabled))
        pr_t = triggers.get("periodic_report", {})
        if isinstance(pr_t, dict):
            cfg.periodic_report_enabled = bool(pr_t.get("enabled", cfg.periodic_report_enabled))
            cfg.periodic_report_interval_minutes = int(
                pr_t.get("interval_minutes", cfg.periodic_report_interval_minutes)
            )
            cfg.periodic_report_skip_if_idle = bool(pr_t.get("skip_if_idle", cfg.periodic_report_skip_if_idle))
            cfg.periodic_report_min_events = int(pr_t.get("min_events_for_dispatch", cfg.periodic_report_min_events))
        outputs = d.get("outputs", {})
        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
        slices = d.get("slices", {})
        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
        cfg.slice_c_campaign_report = bool(slices.get("c_campaign_report", cfg.slice_c_campaign_report))
        audit = d.get("audit", {})
        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
        cfg.brand_name = str(d.get("brand_name", cfg.brand_name))
        cfg.brand_emoji = str(d.get("brand_emoji", cfg.brand_emoji))
        q = d.get("query", {})
        if isinstance(q, dict):
            cfg.query_enabled = bool(q.get("enabled", cfg.query_enabled))
            _im = q.get("intent_model")
            if _im:
                cfg.query_intent_model = str(_im)
            _fm = q.get("format_model")
            if _fm:
                cfg.query_format_model = str(_fm)
            cfg.query_intent_temperature = float(q.get("intent_temperature", cfg.query_intent_temperature))
            cfg.query_format_temperature = float(q.get("format_temperature", cfg.query_format_temperature))
            cfg.query_intent_timeout_s = float(q.get("intent_timeout_s", cfg.query_intent_timeout_s))
            cfg.query_format_timeout_s = float(q.get("format_timeout_s", cfg.query_format_timeout_s))
            _rl = q.get("rate_limit", {})
            if isinstance(_rl, dict):
                cfg.query_max_per_chat_per_hour = int(
                    _rl.get("max_queries_per_chat_per_hour", cfg.query_max_per_chat_per_hour)
                )
        return cfg

    @classmethod
    def from_yaml_string(cls, content: str) -> AssistantConfig:
        """Load from YAML string; handles agent.* and legacy gemma.* namespaces."""
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load(content) or {}
        return cls._from_raw(raw)

    @classmethod
    def from_yaml_path(cls, path: Path) -> AssistantConfig:
        """Load from agent.yaml file; handles agent.* and legacy gemma.* namespaces."""
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict) -> AssistantConfig:
        if "agent" in raw:
            return cls.from_dict(raw["agent"])
        if "gemma" in raw:
            logger.warning(
                "AssistantConfig: legacy gemma.* config namespace detected; "
                "please migrate to agent.*. Backward compatibility removed in v0.46.0."
            )
            return cls.from_dict(raw["gemma"])
        return cls()


class _EventDedup:
    """Drop duplicate events that fall inside a sliding ``window_s`` window.

    F-BotPolish: an alarm that briefly clears (stale-data → fresh → stale
    again) re-fires the ``alarm_fired`` event repeatedly. Without dedup,
    Gemma issues a fresh narrative on every re-fire, flooding Telegram
    with near-identical bullets. A *sliding* window is the right semantics
    here: a flapping alarm produces exactly one narrative for the duration
    of the flap-burst, and only after the alarm has been quiet for the
    full window does the next genuine re-fire produce a fresh response.

    OC-028 — the sliding window had no floor, and that is the opposite failure.
    ``_seen`` was refreshed on every attempt INCLUDING suppressed ones, so the
    "quiet for a full window" condition can never be reached while the alarm
    keeps firing: a continuously flapping CRITICAL was narrated exactly ONCE,
    for as long as it lasted.  Two bounds now break that silence, per the owner
    decision of 2026-08-05 recorded in ``docs/DECISIONS.md``:

    * **A re-narration that never reached the operator buys no silence -- but
      it buys no licence either.**  The ledger suppresses duplicates of what
      was DELIVERED, not of what was attempted.  A failed attempt therefore
      re-arms the alarm, and the retry is admitted once ``window_s`` has
      elapsed since that attempt -- NOT on the very next event.  The
      unconditional version of this rule was reviewed out: during a transport
      outage it turns every refire into another generation and send, which is
      the same storm the window exists to prevent, arriving by the recovery
      path.  Allowing an attempt also CLEARS the failure marker, so the bound
      is measured against the attempt in flight rather than against one that
      has already been superseded.
    * **A CRITICAL that stays active is re-narrated every**
      ``escalate_after_s``.  This is ELAPSED TIME since suppression began, not
      a count of suppressed events: an alarm re-firing every second would reach
      any event count almost immediately, which is not what "after N windows"
      means to an operator.

    Only CRITICAL ``alarm_fired`` events reach this gate -- ``_should_handle``
    filters the rest -- so there is no lower severity here to treat differently.
    """

    def __init__(self, window_s: float = 30.0, escalate_after_s: float = 300.0) -> None:
        self._window_s = window_s
        self._escalate_after_s = escalate_after_s
        self._seen: dict[str, float] = {}
        self._activity: dict[str, float] = {}
        self._last_allowed: dict[str, float] = {}
        self._undelivered: set[str] = set()
        self._suppressed: set[str] = set()
        # An outcome belongs to the ATTEMPT that produced it, not to the alarm.
        # With `timeout_s: 120` and two concurrent inferences, attempt B can be
        # admitted and delivered while attempt A is still pending; A's late
        # failure must not re-arm an alarm B has already narrated.  `_attempt`
        # is the sequence number of the newest admission; `_settled` is the
        # attempt whose outcome has already been recorded, so a second report
        # for the same attempt -- a cancellation arriving after a successful
        # send, say -- cannot overwrite the first.
        # Attempt ids are drawn from ONE monotonic counter for the whole agent,
        # never a per-alarm sequence.  A per-alarm counter is pruned with its
        # alarm, and the delivery path has no end-to-end bound -- so an attempt
        # still pending past the prune horizon, on an alarm that has stopped
        # firing, would see the next occurrence of that alarm numbered `1` again
        # and could settle it with an outcome belonging to the old task.  A
        # counter that never rewinds cannot collide.
        self._next_attempt = 0
        self._attempt: dict[str, int] = {}
        # Settled attempt IDS, not per-alarm state.  Because ids are globally
        # unique this single set answers both "has this attempt reported?" for
        # the current attempt and for a superseded one, which is what makes a
        # stale report idempotent instead of applying twice.
        # Settled attempts are DERIVED, not stored.  Every id this ledger has
        # ever issued is in exactly one of three states -- not yet issued,
        # pending, or settled -- so "has it settled?" is
        # `issued and not pending`, and the only thing worth keeping is the
        # PENDING set.
        #
        # Two earlier shapes were wrong in opposite directions.  A set of
        # settled ids bounded by distance evicted an old attempt's first report
        # and accepted its second.  A watermark plus an out-of-order remainder
        # fixed that but grew with LIFETIME ADMISSIONS whenever one attempt
        # stayed pending, because the clamp that protected it also stopped the
        # watermark advancing past everything after it.  Deriving the answer has
        # neither failure: memory is exactly the in-flight set, and idempotence
        # is exact for every id.
        self._pending: set[int] = set()
        # Which alarm each outstanding attempt belongs to.  The exemption
        # below needs it: a first sighting is exempt because the queued
        # attempts belong to OTHER alarms, and that reason fails when one of
        # them belongs to this one.
        self._pending_alarm: dict[int, str] = {}
        # The attempt id at which each alarm's CURRENT occurrence began -- reset
        # whenever the alarm is admitted with no prior state, i.e. after a prune.
        # A success from before that line describes a different occurrence and
        # must not suppress this one.
        self._generation: dict[str, int] = {}
        # When the CURRENT attempt was admitted, and when the operator was last
        # confirmed to have been told.  Kept apart from `_last_allowed` because
        # a failure must not re-arm an alarm that a DIFFERENT attempt narrated
        # after this one was admitted.
        self._admitted_at: dict[str, float] = {}
        self._last_told: dict[str, float] = {}
        # Attempts whose OCCURRENCE has been dropped -- retired here or pruned
        # on the horizon -- and which therefore can no longer narrate anything:
        # the generation check refuses their outcomes as belonging to a previous
        # occurrence.  Freeing their queue slot is not enough, because the work
        # itself is still queued; whoever owns the tasks drains this list and
        # cancels them.  The ledger cannot, because it does not own them.
        # Drained on every dispatch, so it holds at most one dispatch's worth.
        self._abandoned: list[int] = []

    def _prune(self, now: float) -> None:
        """Drop bookkeeping for alarms that have stopped firing.

        Pruned on the ESCALATION horizon, not the dedup window: an entry has to
        outlive ``window_s`` for the escalation to be reachable at all.
        """

        horizon = now - max(self._window_s, self._escalate_after_s)
        self._activity = {key: stamp for key, stamp in self._activity.items() if stamp >= horizon}
        self._seen = {key: stamp for key, stamp in self._seen.items() if key in self._activity}
        self._last_allowed = {key: stamp for key, stamp in self._last_allowed.items() if key in self._activity}
        self._undelivered &= set(self._activity)
        self._suppressed &= set(self._activity)
        # PRUNING DOES NOT ABANDON.  It is tempting -- the ids it leaves in
        # `_pending` are orphans -- but a pruned alarm's attempt may be SLOW
        # rather than dead: the alarm fired once, its narration is still queued,
        # and the operator has not been told.  Releasing it here would let the
        # owner of the tasks cancel work that is the operator's only notice of
        # that alarm.  The orphan is instead cleared at the moment the same
        # alarm is admitted again, in `_allow`, where a replacement narration
        # provably exists.
        self._attempt = {key: seq for key, seq in self._attempt.items() if key in self._activity}
        self._admitted_at = {key: stamp for key, stamp in self._admitted_at.items() if key in self._activity}
        self._last_told = {key: stamp for key, stamp in self._last_told.items() if key in self._activity}
        # The generation marker is pruned WITH its alarm.  Left behind, it still
        # names the retired occurrence's attempt, so a success from that
        # occurrence arriving BEFORE the alarm fires again compares equal and is
        # accepted -- recreating `_seen` and `_last_allowed` and suppressing the
        # new occurrence's first event.
        self._generation = {key: seq for key, seq in self._generation.items() if key in self._activity}
        # `_settled_below` and `_settled_above` are pruned as they are written;
        # see `_mark_settled`.  Nothing to do here.
        return

    def _abandon(self, event_id: str) -> None:
        """Release the queue slot held by one alarm's outstanding attempt.

        Used by both paths that end an occurrence -- `_retire` for the alarm
        currently firing, `_prune` for alarms that have stopped -- because the
        consequence is identical either way: the attempt cannot narrate the next
        occurrence, so holding a slot for it refuses live alarms on behalf of
        dead work.
        """

        outstanding = self._attempt.pop(event_id, None)
        if outstanding is None:
            return
        self._pending.discard(outstanding)
        self._pending_alarm.pop(outstanding, None)
        self._abandoned.append(outstanding)

    def take_abandoned(self) -> list[int]:
        """Hand over the attempts whose occurrence has ended, and forget them."""

        drained, self._abandoned = self._abandoned, []
        return drained

    def _retire(self, event_id: str) -> None:
        """Drop one alarm's occurrence state so the next admission starts fresh.

        Everything `_prune` would remove for an alarm that has gone quiet, but
        applied to a single id at a moment `_prune` cannot see.
        """

        self._activity.pop(event_id, None)
        self._seen.pop(event_id, None)
        self._last_allowed.pop(event_id, None)
        self._admitted_at.pop(event_id, None)
        self._last_told.pop(event_id, None)
        # RETIREMENT FREES THE QUEUE SLOT.  The retired attempt can no longer
        # narrate this alarm -- the generation check in `note_outcome` treats
        # its eventual success as belonging to the previous occurrence and
        # refuses it -- so holding a backpressure slot for it is doubly wrong:
        # the slot never releases, and it would refuse the new occurrence's only
        # event on the strength of work that cannot speak for it.
        self._abandon(event_id)
        self._generation.pop(event_id, None)
        self._undelivered.discard(event_id)
        self._suppressed.discard(event_id)

    def _allow(self, event_id: str, now: float) -> bool:
        fresh_occurrence = event_id not in self._attempt
        if fresh_occurrence:
            # CLEAR THIS ALARM'S ORPHANS, and do it HERE rather than in `_retire`
            # or `_prune`, because here a replacement narration provably exists:
            # the admission on this very line.  An orphan is an attempt from a
            # previous occurrence, left pending when that occurrence was retired
            # or pruned; the generation check refuses its outcome as stale, so
            # it can no longer narrate anything, yet it held a queue slot for
            # ever and its coroutine stayed alive waiting for an inference slot.
            # That is how one alarm clearing and returning past each horizon
            # added a pending id and a live task on every cycle.
            for orphan in [seq for seq, alarm in self._pending_alarm.items() if alarm == event_id]:
                self._pending.discard(orphan)
                del self._pending_alarm[orphan]
                self._abandoned.append(orphan)
        self._last_allowed[event_id] = now
        self._seen[event_id] = now
        self._activity[event_id] = now
        self._admitted_at[event_id] = now
        self._next_attempt += 1
        self._attempt[event_id] = self._next_attempt
        self._pending.add(self._next_attempt)
        self._pending_alarm[self._next_attempt] = event_id
        if fresh_occurrence:
            # No prior state: either the first ever admission for this alarm, or
            # the first after `_prune` dropped it.  Everything before this line
            # belongs to a different occurrence.
            self._generation[event_id] = self._next_attempt
        # Allowing an attempt CLEARS the failure marker; `note_outcome` re-adds
        # it only if this attempt actually fails.  Leaving it set makes the
        # marker describe an attempt that is already superseded: the retry
        # branch above fires on `_undelivered` plus one elapsed window, and the
        # default Ollama timeout is longer than the 30 s window, so a refire
        # arriving while the fresh narration is still IN FLIGHT would start yet
        # another retry on the strength of a failure that has been answered.
        # Allowing an attempt CLEARS the failure marker; `note_outcome` re-adds
        # it only if this attempt actually fails.  Leaving it set makes the
        # marker describe an attempt that is already superseded: the retry
        # branch fires on `_undelivered` plus one elapsed window, and the
        # default Ollama timeout is longer than the 30 s window, so a refire
        # arriving while the fresh narration is still IN FLIGHT would start yet
        # another retry on the strength of a failure that has been answered.
        self._undelivered.discard(event_id)
        self._suppressed.discard(event_id)
        return True

    def should_dispatch(self, event_id: str) -> bool:
        now = time.monotonic()
        last_seen = self._seen.get(event_id)
        last_activity = self._activity.get(event_id)
        last_allowed = self._last_allowed.get(event_id)

        # RETIRE THIS ALARM'S OWN STALE STATE FIRST.  `_prune` runs after
        # `_seen` is refreshed, so it can never retire the alarm currently
        # firing -- and a lone CRITICAL, the only one qualifying, therefore kept
        # its `_attempt` and `_generation` across an arbitrarily long silence.
        # A success from that retired occurrence then passed the generation
        # check and cleared the CURRENT occurrence's failure marker.  Retiring
        # here uses the PRE-REFRESH timestamp, which is the only moment the
        # gap is visible.
        if last_activity is not None and last_activity < now - max(self._window_s, self._escalate_after_s):
            self._retire(event_id)
            # CLEAR THE LOCAL FIRST-SIGHTING STATE TOO.  `_retire` drops the
            # stored state, but this local still held the old timestamp -- so
            # the backpressure check below saw a refire and refused the FIRST
            # event of the new occurrence.  Production sources publish only on
            # transition, so nothing later repairs that: the narration is lost,
            # not delayed.  After retirement this event IS a first sighting and
            # must be treated as one everywhere.
            last_seen = None
            last_allowed = None

        self._activity[event_id] = now
        self._prune(now)

        # SCOPED TO THE CURRENT OCCURRENCE.  Asking only "does this alarm own a
        # queued attempt?" counts ORPHANS -- attempts left pending when a
        # previous occurrence was pruned, which the generation check has already
        # disqualified from narrating anything.  A pruned alarm that returned
        # was then refused on the strength of work that could not speak for it,
        # and production publishes only that returning `TRIGGERED` transition,
        # so the narration was lost rather than delayed.  No generation means no
        # current occurrence, which is exactly the returning case.
        generation = self._generation.get(event_id)
        already_queued = generation is not None and any(
            self._pending_alarm.get(seq) == event_id and seq >= generation for seq in self._pending
        )
        if (last_seen is not None or already_queued) and len(self._pending) >= _MAX_OUTSTANDING_ATTEMPTS:
            # BACKPRESSURE AT THE GATE, ahead of every admitting branch -- a
            # check placed after them never applies to a repeat admission, which
            # is where the growth comes from.
            #
            # A FIRST SIGHTING IS REFUSED ONLY IF THIS ALARM ALREADY HAS AN
            # ATTEMPT OUTSTANDING.  The exemption exists because the queued
            # attempts belong to OTHER alarms and will not narrate this one --
            # and that reason fails when one of them belongs to this alarm.
            # Without the `already_queued` term, an alarm that clears and
            # retriggers past each prune horizon is retired and exempted every
            # time, so pending ids and queued handler tasks grow without bound
            # through the very hole the cap exists to close.  Production
            # sources publish on transition (`engine_wiring/runtime_tasks.py`
            # only on `TRIGGERED`), so a condition that stays active and never
            # transitions again would lose its narration permanently.  Losing an
            # alarm entirely is a worse failure than an unbounded queue, and the
            # bound that remains -- one outstanding first sighting per distinct
            # alarm id -- is set by the rig's alarm inventory rather than by
            # refire rate, which is the term that ran away.
            #
            # With both inference slots stuck in an unbounded dispatch or audit
            # operation, every escalation admitted another attempt and created
            # another handler task. A queued task neither consumes rate-limit
            # capacity -- the timestamp is appended only after the semaphore is
            # acquired -- nor settles its id, so a continuously refiring
            # CRITICAL grew `_handler_tasks` and the pending set without bound
            # until shutdown.
            #
            # Refusing trades a narration for a bound, and that is the right way
            # round: the attempts already queued will narrate when they drain,
            # so this does not silence the alarm. It declines to tell the
            # operator a 65th time by a system that has not managed to tell them
            # once.
            return False

        if (last_seen is None or last_seen < now - self._window_s) and event_id not in self._suppressed:
            # Genuinely quiet for a full window: the original semantics.
            return self._allow(event_id, now)
        if last_allowed is None:
            return self._allow(event_id, now)
        if event_id in self._undelivered and now - last_allowed >= self._window_s:
            # A narration that reached nobody buys no silence -- but it buys no
            # LICENCE either.  Without the window bound here, a transport outage
            # turns every refire during an in-flight retry into another
            # generation and send, which is the same storm the window exists to
            # prevent, arriving through the recovery path instead.
            return self._allow(event_id, now)
        if now - last_allowed >= self._escalate_after_s:
            # Anchored at the LAST NARRATION, not at the first suppressed
            # refire.  Anchoring at the suppression start adds the refire
            # interval to every silence: an alarm re-firing every 29.9 s would
            # first suppress at 29.9 s and only escalate at 329.9 s.
            #
            # "Last narration" means the last CONFIRMED DELIVERY where one is
            # known -- `note_outcome(delivered=True)` moves this stamp forward.
            #
            # WHAT THIS BOUNDS, AND WHAT IT DOES NOT.  This class bounds the
            # interval between ADMISSIONS at `escalate_after_s` plus one refire
            # interval, measured from the last confirmed delivery where there is
            # one.  It does NOT bound the interval between narrations the
            # operator RECEIVES, and two earlier versions of this comment
            # claimed that it did.  Between admission and delivery lie terms
            # this gate neither owns nor observes:
            #
            #   * the hourly rate limit, which can REJECT an admitted escalation
            #     outright until the bucket drains -- up to an hour;
            #   * waiting on `_semaphore` behind other inferences;
            #   * context assembly and audit-intent persistence;
            #   * generation, bounded by `timeout_s` only because Ollama is
            #     asked to stop, not because anything downstream is;
            #   * sequential per-recipient transport acknowledgements.
            #
            # A rejected or slow attempt reports `delivered=False`, so the alarm
            # re-arms and is retried ON THE NEXT REFIRE -- and only then.
            # `engine_wiring/runtime_tasks.py` publishes `alarm_fired` on a
            # TRIGGERED transition and nothing consumes `_undelivered` on a
            # timer, so a CRITICAL whose sole transition was rejected by the
            # hourly rate limit and which then stays active without
            # transitioning again is NEVER NARRATED AT ALL.  Saying silence is
            # not permanent, unqualified, was false.  And no end-to-end deadline
            # exists, so no received-to-received maximum can be stated here.  Enforcing one would need a deadline that
            # spans this whole path, which is a design change beyond OC-028.
            return self._allow(event_id, now)
        if event_id not in self._undelivered and last_allowed is not None:
            self._suppressed.add(event_id)
        return False

    def _has_settled(self, attempt: int) -> bool:
        """True when ``attempt`` was issued and is no longer in flight.

        No history is consulted, so a report arriving arbitrarily late is still
        recognised as a duplicate -- which matters because the delivery path has
        no end-to-end bound.
        """

        return attempt <= self._next_attempt and attempt not in self._pending

    def _mark_settled(self, attempt: int) -> None:
        self._pending.discard(attempt)
        self._pending_alarm.pop(attempt, None)

    def current_attempt(self, event_id: str) -> int:
        """The sequence number of the newest admission for ``event_id``.

        Read immediately after a ``True`` from `should_dispatch`, by the single
        task that owns the gate, and carried through the handler so the outcome
        can be attributed to the attempt that produced it.
        """

        return self._attempt.get(event_id, 0)

    def note_outcome(self, event_id: str, *, delivered: bool, attempt: int | None = None) -> None:
        """Record whether the narration for ``event_id`` reached any target.

        This is the input the ledger never had.  ``mark_delivered`` existed but
        was called only by tests -- production never reported an outcome, so a
        narration lost to a broken transport still bought a full window of
        silence.

        ``attempt`` scopes the report, and two orderings make that necessary
        rather than tidy:

        * **A late failure must not undo a newer success.**  Two inferences can
          run concurrently and each may take up to ``timeout_s``, so attempt B
          can be admitted, delivered and settled while attempt A is still
          pending.  Without scoping, A's eventual failure re-arms an alarm the
          operator has already been told about, and the next refire narrates a
          third time.
        * **An attempt settles ONCE.**  A cancellation arriving after the
          summary was delivered -- ``stop()`` during the optional Slice B
          follow-up, for instance -- would otherwise overwrite a confirmed
          delivery with a failure.

        A report carrying no ``attempt`` is accepted unconditionally; that is
        the pre-existing test-facing behaviour and is deliberately unchanged.
        """

        now = time.monotonic()

        if attempt is None:
            # AN UNSCOPED REPORT STILL SETTLES THE ALARM'S CURRENT ATTEMPT.
            # Without this the issued id is never removed from `_pending`, so
            # every unscoped caller -- including `mark_delivered` -- leaves a
            # phantom in flight, and after `_MAX_OUTSTANDING_ATTEMPTS` such
            # alarms the backpressure check refuses every later admission
            # forever with no work actually running.  A leak that silences the
            # rig is a worse outcome than the double-report scoping prevents.
            attempt = self._attempt.get(event_id)

        if attempt is not None:
            # ONE settle per attempt, current or superseded.  Without this a
            # superseded attempt reports twice -- once from the router callback
            # at the real acknowledgement, once again after `_audit.complete` --
            # and the second report drags the clock from the moment of delivery
            # to the moment the audit write finished, postponing the next
            # admission by however long the filesystem took.
            if self._has_settled(attempt):
                return
            self._mark_settled(attempt)

        if delivered and attempt is not None and event_id not in self._attempt:
            # The alarm has been RETIRED -- its state was pruned and it has not
            # fired since.  A success arriving now belongs to that retired
            # occurrence, and applying it would recreate `_seen` and
            # `_last_allowed` out of nothing, so the next occurrence's FIRST
            # event would be suppressed as a duplicate of a narration about
            # something else.  This is the mirror of the check below: there the
            # alarm had already re-fired, here it has not re-fired yet.
            return

        if delivered and attempt is not None and attempt < self._generation.get(event_id, 0):
            # A success from BEFORE this alarm's current occurrence began -- the
            # old state was pruned and the id was re-admitted since.  That
            # narration described a different occurrence, possibly a different
            # experiment, so letting it clear `_undelivered` and advance the
            # clocks would suppress the CURRENT alarm for a full escalation
            # interval on the strength of something nobody was told about it.
            return

        if delivered:
            self._undelivered.discard(event_id)
            # A CONFIRMED DELIVERY IS ALSO A FRESH OBSERVATION OF THIS ALARM.
            # Without this, a delivery slower than `window_s` leaves `_seen` at
            # the admission, so the very next refire takes the "quiet for a full
            # window" branch -- which is evaluated BEFORE the delivery clock --
            # and narrates again seconds after the operator was told.  The
            # corrected clock below is useless if an earlier branch never
            # consults it.
            self._seen[event_id] = now
            # THE ESCALATION CLOCK STARTS WHEN THE OPERATOR WAS TOLD, not when
            # the gate admitted the attempt.  Generation can take up to
            # ``timeout_s``, and stamping at admission makes the silence the
            # operator experiences depend on how long the PREVIOUS narration
            # took to generate -- a quantity the bound never accounted for.
            # `now` is always >= the admission stamp, so this is a forward move.
            self._last_told[event_id] = now
            self._last_allowed[event_id] = now
            return

        if attempt is not None and attempt != self._attempt.get(event_id):
            # A SUPERSEDED attempt FAILING is noise: the newer attempt is the
            # live one, and re-arming on an obsolete failure is what attempt
            # scoping exists to stop.  (A superseded attempt SUCCEEDING is not
            # noise, and is handled above -- the operator really did read it.)
            return

        if self._last_told.get(event_id, float("-inf")) >= self._admitted_at.get(event_id, float("inf")):
            # THE OPERATOR HAS BEEN TOLD SINCE THIS ATTEMPT WAS ADMITTED, by a
            # different attempt that was still in flight when this one started.
            # Re-arming now would resend a narration they have already read --
            # the inverse ordering of the case above, and the one that survived
            # the first version of attempt scoping.
            return

        self._undelivered.add(event_id)

    def mark_delivered(self, event_id: str) -> None:
        """Backwards-compatible alias for a successful delivery.

        THE CLOCKS ARE MOVED BY `note_outcome`, NOT HERE.  Stamping first let an
        arbitrarily late compatibility report -- a legacy caller arriving after
        the scoped router callback had already settled, or the alias called
        twice -- advance `_seen` and `_last_allowed` before settle-once could
        reject it, postponing the next escalation on a duplicate.  Settlement
        decides whether the clocks may move.
        """

        self.note_outcome(event_id, delivered=True)


def _reached_any_recipient(outcomes: dict[str, Any]) -> bool:
    """True when at least one recipient of any target accepted the narration.

    Deliberately weaker than ``_is_delivered_outcome``, which requires every
    recipient of a target to succeed.  That strictness is right for the AUDIT
    trail and wrong for suppression: a narration that reached one of two
    Telegram chats HAS been seen, and resending it because the other chat is
    broken spams the operator who is already reading it.
    """

    for state in outcomes.values():
        if state == "delivered":
            return True
        if isinstance(state, dict) and any(recipient == "delivered" for recipient in state.values()):
            return True
    return False


# How many narration attempts may be in flight at once before the gate refuses
# to admit more.  Far above any healthy load -- two inference slots and a 30 s
# window cannot produce this many outstanding attempts unless the dispatch path
# has stopped completing -- so reaching it is a symptom, and the bound exists so
# the symptom does not become an unbounded task and id accumulation.
_MAX_OUTSTANDING_ATTEMPTS = 64


def _event_dedup_id(event: EngineEvent) -> str | None:
    """Compute a dedup key for ``event`` or ``None`` when dedup does not apply.

    Cycle-2 fix from commit 53981a1: the previous
    implementation derived the bucket from ``time.monotonic() // window_s``,
    which let an alarm at ``t=29.9 s`` and a re-fire at ``t=30.1 s`` produce
    different bucket ids (0 then 1) and pass through despite being 0.2 s
    apart. The dedup key is now stable per alarm — the rolling-window
    timestamp logic lives entirely in :class:`_EventDedup`.

    Only ``alarm_fired`` is deduped today; other event types are rare by
    construction and pass through untouched.
    """
    if event.event_type != "alarm_fired":
        return None
    alarm_id = str(event.payload.get("alarm_id", "unknown"))
    return f"alarm:{alarm_id}"


class AssistantLiveAgent:
    """Local LLM agent. Operator-facing brand: Гемма."""

    def __init__(
        self,
        *,
        config: AssistantConfig,
        event_bus: EventBus,
        ollama_client: OllamaClient,
        context_builder: ContextBuilder,
        audit_logger: AuditLogger,
        output_router: OutputRouter,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._ollama = ollama_client
        self._ctx_builder = context_builder
        self._audit = audit_logger
        self._router = output_router

        self._semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
        self._call_timestamps: deque[float] = deque()
        self._handler_tasks: set[asyncio.Task] = set()
        # Which task is doing the work of which attempt, and which attempts have
        # actually STARTED -- i.e. hold an inference slot.  Both are keyed by
        # attempt id and dropped when the task finishes, so they are bounded by
        # the work in flight rather than by lifetime admissions.
        self._attempt_tasks: dict[int, asyncio.Task] = {}
        self._started_attempts: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[EngineEvent] | None = None
        # F-BotPolish: drop duplicate alarm_fired events inside a 30 s window
        # so re-firing alarms (stale → fresh → stale) don't flood Telegram
        # with near-identical Gemma narratives.
        # OC-028: 30 s dedup window, and a 300 s floor after which a CRITICAL
        # that is still firing is re-narrated rather than silenced forever.
        self._dedup = _EventDedup(window_s=30.0, escalate_after_s=300.0)

    async def start(self) -> None:
        """Subscribe to EventBus and begin event processing."""
        if not self._config.enabled:
            logger.info("AssistantLiveAgent (Гемма): отключён в конфигурации")
            return
        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
        logger.info(
            "AssistantLiveAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
            self._config.default_model,
            self._config.timeout_s,
        )

    async def stop(self) -> None:
        """Cancel the event loop and in-flight handlers, release resources."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Cancel in-flight inference tasks to avoid racing with shutdown
        for t in list(self._handler_tasks):
            t.cancel()
        for t in list(self._handler_tasks):
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self._queue is not None:
            self._bus.unsubscribe("gemma_agent")
            self._queue = None
        await self._ollama.close()
        logger.info("AssistantLiveAgent (Гемма): остановлен")

    async def _dispatch_with_audit(
        self,
        *,
        event: EngineEvent,
        audit_id: str,
        payload: dict[str, Any],
        context_assembled: str,
        prompt_template: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        tokens: dict[str, int],
        latency_s: float,
        errors: list[str],
        targets: list[OutputTarget],
        prefix_suffix: str = "",
        allow_dispatch: bool = True,
        on_outcomes: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        """Persist intent, dispatch, and persist exact per-target settlement.

        ``on_outcomes`` is invoked the moment the router reports, BEFORE the
        audit settlement write.  The window matters: ``stop()`` can cancel this
        coroutine while ``_audit.complete`` is awaiting its shielded filesystem
        write, in which case this function never returns and the caller never
        learns that the narration was delivered -- so the cancellation fallback
        would settle a delivered attempt as undelivered and the next refire
        would resend a narration the operator has already read.
        """
        trigger_event = {
            "event_type": event.event_type,
            "payload": payload,
            "experiment_id": event.experiment_id,
        }
        intent_path = await self._audit.prepare(
            audit_id=audit_id,
            trigger_event=trigger_event,
            context_assembled=context_assembled,
            prompt_template=prompt_template,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            tokens=tokens,
            latency_s=latency_s,
            errors=errors,
        )
        if intent_path is None:
            errors.append("audit_intent_persist_failed")
            logger.error("AssistantLiveAgent: output blocked before durable intent (audit_id=%s)", audit_id)
            return [], {"audit": "failed"}

        outcomes: dict[str, Any] = {}
        if allow_dispatch and not errors and response.strip():
            outcomes = await self._router.dispatch_detailed(
                event,
                response,
                targets=targets,
                audit_id=audit_id,
                prefix_suffix=prefix_suffix,
            )
            if on_outcomes is not None:
                on_outcomes(outcomes)
            for target, state in outcomes.items():
                if not _is_delivered_outcome(state):
                    errors.append(f"output_{target}_{state}")

        dispatched = [target for target, state in outcomes.items() if _is_delivered_outcome(state)]
        if (
            await self._audit.complete(
                audit_id=audit_id,
                outputs_dispatched=dispatched,
                output_outcomes=outcomes,
                errors=errors,
            )
            is None
        ):
            errors.append("audit_settlement_persist_failed")
        return dispatched, outcomes

    async def _event_loop(self) -> None:
        """Drain the EventBus queue and dispatch handlers."""
        assert self._queue is not None
        while True:
            try:
                event = await self._queue.get()
                if self._should_handle(event):
                    # F-BotPolish: pre-invocation dedup gate — slice handler
                    # logic itself is unchanged.
                    dedup_id = _event_dedup_id(event)
                    admitted = True
                    if dedup_id is not None:
                        admitted = self._dedup.should_dispatch(dedup_id)
                        # DRAIN WHETHER OR NOT THIS EVENT WAS ADMITTED.  A
                        # refused refire still runs `_prune`, which is where most
                        # occurrences end; skipping the drain on the refused path
                        # would leave that dead work queued for ever.
                        self._cancel_abandoned_handlers()
                    if not admitted:
                        logger.debug(
                            "AssistantLiveAgent: dropping duplicate event %s",
                            dedup_id,
                        )
                        continue
                    attempt = None if dedup_id is None else self._dedup.current_attempt(dedup_id)
                    t = asyncio.create_task(
                        self._safe_handle(event, dedup_id=dedup_id, attempt=attempt),
                        name=f"gemma_{event.event_type}",
                    )
                    self._handler_tasks.add(t)
                    t.add_done_callback(self._handler_tasks.discard)
                    if attempt is not None:
                        self._attempt_tasks[attempt] = t
                        t.add_done_callback(
                            lambda _done, seq=attempt: (
                                self._attempt_tasks.pop(seq, None),
                                self._started_attempts.discard(seq),
                            )
                        )
                    if dedup_id is not None:
                        # Backstop for the one cancellation the handler cannot
                        # see: a task cancelled BEFORE its coroutine first runs
                        # never enters any `except`, yet the gate has already
                        # advanced.  `note_outcome` settles an attempt once, so
                        # this is a no-op whenever the handler already reported.
                        t.add_done_callback(
                            lambda done, key=dedup_id, seq=attempt: (
                                self._dedup.note_outcome(key, delivered=False, attempt=seq)
                                if done.cancelled()
                                else None
                            )
                        )
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("AssistantLiveAgent: event loop error", exc_info=True)

    def _should_handle(self, event: EngineEvent) -> bool:
        if not self._config.slice_a_notification:
            return False
        if event.event_type == "alarm_fired":
            if not self._config.alarm_fired_enabled:
                return False
            # v0.55.5 — Гемма proactive narrative is reserved for physics
            # CRITICAL events; sensor-health alarms (sensor_fault*, diag:*)
            # carry no operator-actionable narrative beyond the deterministic
            # GUI/digest paths and previously caused Telegram spam on
            # flapping diagnostics. Hourly summary captures non-CRITICAL.
            alarm_id = str(event.payload.get("alarm_id", ""))
            if alarm_id.startswith("sensor_fault") or alarm_id.startswith("diag:"):
                return False
            level = str(event.payload.get("level", "INFO")).upper()
            if _MIN_LEVELS.get(level, 0) < _MIN_LEVELS.get("CRITICAL", 2):
                return False
            return True
        if event.event_type in {"experiment_finalize", "experiment_stop", "experiment_abort"}:
            return self._config.experiment_finalize_enabled
        if event.event_type == "sensor_anomaly_critical":
            # v0.55.5 — sensor diagnostics CRITICAL is not a physics signal;
            # operator already sees it on the Diagnostics tab. Hourly digest
            # surfaces aggregated counts without burning the LLM budget.
            return False
        if event.event_type == "shift_handover_request":
            return self._config.shift_handover_request_enabled
        if event.event_type == "periodic_report_request":
            return self._config.periodic_report_enabled
        return False

    def _check_rate_limit(self) -> bool:
        """True if we can make a call now (hourly bucket)."""
        now = time.monotonic()
        cutoff = now - 3600.0
        while self._call_timestamps and self._call_timestamps[0] < cutoff:
            self._call_timestamps.popleft()
        return len(self._call_timestamps) < self._config.max_calls_per_hour

    def _cancel_abandoned_handlers(self) -> None:
        """Cancel queued work whose occurrence has ended.

        Freeing the ledger slot bounds the ADMISSION queue; it does nothing
        about the coroutine, which stays alive waiting for an inference slot
        that may never free. An alarm clearing and returning past every horizon
        therefore added one live task per cycle -- linear growth through the
        hole the cap exists to close.

        ONLY WORK THAT HAS NOT STARTED IS CANCELLED. An attempt holding an
        inference slot may be mid-generation or mid-send, and cancelling it
        would lose a narration in flight to save a task -- the wrong trade in a
        lab where a lost CRITICAL is never repaired. Started work needs no cap
        anyway: the semaphore already bounds it at `max_concurrent_inferences`.
        """

        for seq in self._dedup.take_abandoned():
            task = self._attempt_tasks.pop(seq, None)
            if task is None or task.done() or seq in self._started_attempts:
                continue
            task.cancel()
        # `_started_attempts` is cleared by each task's own done-callback, not
        # here: this method must not forget that a still-running attempt holds
        # a slot.

    async def _safe_handle(
        self,
        event: EngineEvent,
        *,
        dedup_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        """Handle one event with rate-limit + semaphore + error isolation.

        ``dedup_id`` carries the ledger key so the delivery OUTCOME can be
        reported back (OC-028), and ``attempt`` scopes that outcome to the
        admission that produced it.  Every path that ends without a delivered
        narration -- rate limit, generation failure, empty response, refused
        transport, cancellation -- must report ``delivered=False``, or a
        narration the operator never saw would buy a full window of silence.
        """

        if not self._check_rate_limit():
            logger.warning(
                "AssistantLiveAgent: rate limit reached (%d/hr), dropping %s",
                self._config.max_calls_per_hour,
                event.event_type,
            )
            if dedup_id is not None:
                self._dedup.note_outcome(dedup_id, delivered=False, attempt=attempt)
            return

        # The cancellation handler wraps the semaphore ACQUISITION, not just the
        # work.  With every inference slot occupied, an admitted CRITICAL can be
        # cancelled by `stop()` while it is still queued for a slot -- the gate
        # has advanced but nothing has been generated, and a handler that only
        # catches cancellation after acquiring would never report it.
        try:
            async with self._semaphore:
                # PAST THIS LINE THE WORK IS NO LONGER CANCELLABLE ON THE
                # LEDGER'S SAY-SO: generation or a send may be under way, and
                # `_cancel_abandoned_handlers` must not trade a narration in
                # flight for a queue slot.
                if attempt is not None:
                    self._started_attempts.add(attempt)
                self._call_timestamps.append(time.monotonic())
                try:
                    if event.event_type in {
                        "experiment_finalize",
                        "experiment_stop",
                        "experiment_abort",
                    }:
                        await self._handle_experiment_finalize(event)
                    elif event.event_type == "sensor_anomaly_critical":
                        await self._handle_sensor_anomaly(event)
                    elif event.event_type == "shift_handover_request":
                        await self._handle_shift_handover(event)
                    elif event.event_type == "periodic_report_request":
                        await self._handle_periodic_report(event)
                    else:
                        await self._handle_alarm_fired(event, dedup_id=dedup_id, attempt=attempt)
                except (OllamaUnavailableError, OllamaModelMissingError) as exc:
                    if dedup_id is not None:
                        self._dedup.note_outcome(dedup_id, delivered=False, attempt=attempt)
                    logger.warning("AssistantLiveAgent: Ollama недоступен — %s", exc)
                except Exception:
                    if dedup_id is not None:
                        self._dedup.note_outcome(dedup_id, delivered=False, attempt=attempt)
                    logger.warning("AssistantLiveAgent: ошибка обработки %s", event.event_type, exc_info=True)
        except asyncio.CancelledError:
            # CancelledError is a BaseException, so it passes straight through
            # the handlers above.  Reporting it as undelivered is safe even when
            # the summary already succeeded: `note_outcome` settles an attempt
            # ONCE, so a cancellation during the optional Slice B follow-up
            # cannot overwrite a delivery the operator already received.
            if dedup_id is not None:
                self._dedup.note_outcome(dedup_id, delivered=False, attempt=attempt)
            raise

    async def _handle_alarm_fired(
        self,
        event: EngineEvent,
        *,
        dedup_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_alarm_context(payload)
        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
        age_str = _format_age(ctx.experiment_age_s)

        user_prompt = ALARM_SUMMARY_USER.format(
            alarm_id=ctx.alarm_id,
            level=ctx.level,
            channels=channels_str,
            values=values_str,
            phase=ctx.phase or "—",
            experiment_id=ctx.experiment_id or "—",
            experiment_age=age_str,
            target_temp=ctx.target_temp if ctx.target_temp is not None else "—",
            interlocks=", ".join(ctx.active_interlocks) if ctx.active_interlocks else "нет",
            lookback_s=60,
            recent_readings=ctx.recent_readings_text,
            recent_alarms=ctx.recent_alarms_text,
        )

        system_prompt = format_with_brand(ALARM_SUMMARY_SYSTEM, self._config.brand_name)
        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: ответ обрезан по истечении времени ожидания (audit_id=%s)", audit_id)  # noqa: E501 — single RU log call, splitting hurts grep-ability

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning(
                "AssistantLiveAgent: пустой ответ, dispatch пропущен (truncated=%s, audit_id=%s)",
                result.truncated,
                audit_id,
            )
        # Settle-once makes a second report harmless, but "harmless" depends on
        # the settled id still being remembered when it arrives.  Not making the
        # second report at all is the structural fix; the ledger's idempotence
        # is then a backstop rather than the mechanism.
        reported_early = False

        def record_outcome(reported: dict[str, Any]) -> None:
            nonlocal reported_early
            reported_early = True
            self._dedup.note_outcome(
                dedup_id,  # type: ignore[arg-type]
                delivered=_reached_any_recipient(reported),
                attempt=attempt,
            )

        dispatched, outcomes = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=payload,
            context_assembled=user_prompt,
            prompt_template="alarm_summary",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            allow_dispatch=not result.truncated and bool(result.text.strip()),
            # Record the outcome the INSTANT the router reports it, not after
            # the audit settlement write.  `stop()` landing inside
            # `_audit.complete` would otherwise mean this coroutine never
            # returns, the assignment below never runs, and the cancellation
            # fallback settles a DELIVERED attempt as undelivered -- so the
            # next refire resends a narration the operator has already read.
            on_outcomes=None if dedup_id is None else record_outcome,
        )

        if dedup_id is not None and not reported_early:
            # Only when the router callback did NOT run -- dispatch skipped for a
            # truncated or empty generation, or refused before it began.  When it
            # did run, the outcome is already recorded at the real acknowledgement
            # and reporting again here would settle the same attempt twice.
            #
            # OC-028: the ledger suppresses duplicates of what the operator
            # RECEIVED, so nothing accepted means the next occurrence must not
            # be silenced by a narration nobody saw.
            #
            # `dispatched` is the wrong test on its own: `_is_delivered_outcome`
            # requires EVERY recipient of a target to succeed, so one broken chat
            # among several marks the whole target undelivered even though an
            # operator did read it.  Suppression asks "did this reach anybody",
            # which is weaker than the audit's "did this reach everybody".
            # Answering the audit's question here resends to people who already
            # have it whenever a sibling destination is down.
            self._dedup.note_outcome(
                dedup_id,
                delivered=_reached_any_recipient(outcomes),
                attempt=attempt,
            )

        logger.info(
            "AssistantLiveAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
            audit_id,
            result.latency_s,
            dispatched,
        )
        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
            # Slice B is an OPTIONAL follow-up.  Its failure must not reach
            # _safe_handle's handler, which would mark this alarm's dedup id
            # undelivered AFTER the summary above already reached the operator --
            # and the next refire inside the window would then resend a narration
            # they have read, because a diagnostic extra failed.
            try:
                await self._generate_diagnostic_suggestion(event, payload)
            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
                logger.warning("AssistantLiveAgent: Slice B недоступен - %s", exc)
            except Exception:
                logger.warning("AssistantLiveAgent: ошибка Slice B", exc_info=True)

    async def _generate_diagnostic_suggestion(self, event: EngineEvent, alarm_payload: dict[str, Any]) -> None:
        """Generate and dispatch Slice B diagnostic suggestion (second LLM call).

        Records a separate rate-limit timestamp so each Ollama call counts
        toward the hourly budget (Slice B makes 2 calls per alarm event).
        """
        # Count diagnostic as a separate call toward the hourly rate limit
        self._call_timestamps.append(time.monotonic())
        audit_id = self._audit.make_audit_id()
        ctx = await self._ctx_builder.build_diagnostic_suggestion_context(alarm_payload)
        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"

        user_prompt = DIAGNOSTIC_SUGGESTION_USER.format(
            alarm_id=ctx.alarm_id,
            channels=channels_str,
            values=values_str,
            lookback_min=ctx.lookback_min,
            channel_history=ctx.channel_history,
            recent_alarms=ctx.recent_alarms,
            past_cooldowns=ctx.past_cooldowns,
            pressure_trend=ctx.pressure_trend,
        )

        system_prompt = format_with_brand(DIAGNOSTIC_SUGGESTION_SYSTEM, self._config.brand_name)
        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: diagnostic ответ обрезан (audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой diagnostic ответ (audit_id=%s)", audit_id)
        dispatched_diag, _ = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=alarm_payload,
            context_assembled=user_prompt,
            prompt_template="diagnostic_suggestion",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            allow_dispatch=not result.truncated and bool(result.text.strip()),
        )
        logger.info(
            "AssistantLiveAgent: diagnostic_suggestion dispatched (audit_id=%s, latency=%.1fs)",
            audit_id,
            result.latency_s,
        )

    async def _handle_experiment_finalize(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_experiment_finalize_context(payload)
        _action_labels = {
            "experiment_finalize": "Завершён штатно",
            "experiment_stop": "Остановлен",
            "experiment_abort": "Прерван аварийно",
        }
        user_prompt = EXPERIMENT_FINALIZE_USER.format(
            experiment_id=ctx.experiment_id or "—",
            name=ctx.name,
            duration=ctx.duration_str,
            status=_action_labels.get(ctx.action, ctx.action),
            phases=ctx.phases_text,
            alarms_summary=ctx.alarms_summary_text,
        )

        system_prompt = format_with_brand(EXPERIMENT_FINALIZE_SYSTEM, self._config.brand_name)
        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: ответ обрезан (experiment_finalize, audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой ответ experiment_finalize (audit_id=%s)", audit_id)
        dispatched, _ = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=payload,
            context_assembled=user_prompt,
            prompt_template="experiment_finalize",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            allow_dispatch=not result.truncated and bool(result.text.strip()),
        )
        logger.info(
            "AssistantLiveAgent: %s обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
            event.event_type,
            audit_id,
            result.latency_s,
            dispatched,
        )

    async def _handle_sensor_anomaly(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_sensor_anomaly_context(payload)
        user_prompt = SENSOR_ANOMALY_USER.format(
            channel=ctx.channel,
            alarm_id=ctx.alarm_id,
            level=ctx.level,
            message=ctx.message,
            health_score=ctx.health_score,
            fault_flags=ctx.fault_flags,
            current_value=ctx.current_value,
            experiment_id=ctx.experiment_id or "—",
            phase=ctx.phase or "—",
        )

        system_prompt = format_with_brand(SENSOR_ANOMALY_SYSTEM, self._config.brand_name)
        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: ответ обрезан (sensor_anomaly, audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой ответ sensor_anomaly (audit_id=%s)", audit_id)
        dispatched_sa, _ = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=payload,
            context_assembled=user_prompt,
            prompt_template="sensor_anomaly",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            allow_dispatch=not result.truncated and bool(result.text.strip()),
        )
        logger.info(
            "AssistantLiveAgent: sensor_anomaly_critical обработан (audit_id=%s, latency=%.1fs, channel=%s)",
            audit_id,
            result.latency_s,
            ctx.channel,
        )
        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
            await self._generate_diagnostic_suggestion(event, payload)

    async def _handle_shift_handover(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_shift_handover_context(payload)
        if ctx.context_unavailable:
            await self._dispatch_unavailable_context(
                event=event,
                audit_id=audit_id,
                payload=payload,
                kind="shift_handover",
                message="Сводка смены не сформирована: данные тревог или событий недоступны.",
            )
            return
        user_prompt = SHIFT_HANDOVER_USER.format(
            experiment_id=ctx.experiment_id or "нет активного эксперимента",
            phase=ctx.phase or "—",
            experiment_age=ctx.experiment_age,
            active_alarms=ctx.active_alarms,
            recent_events=ctx.recent_events,
            shift_duration_h=ctx.shift_duration_h,
        )

        system_prompt = format_with_brand(SHIFT_HANDOVER_SYSTEM, self._config.brand_name)
        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: ответ обрезан (shift_handover, audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой ответ shift_handover (audit_id=%s)", audit_id)
        dispatched_sh, _ = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=payload,
            context_assembled=user_prompt,
            prompt_template="shift_handover",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            allow_dispatch=not result.truncated and bool(result.text.strip()),
        )
        logger.info(
            "AssistantLiveAgent: shift_handover_request обработан (audit_id=%s, latency=%.1fs)",
            audit_id,
            result.latency_s,
        )

    async def _handle_periodic_report(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        window_minutes = int(event.payload.get("window_minutes", 60))

        ctx = await self._ctx_builder.build_periodic_report_context(
            window_minutes=window_minutes,
        )
        sensor_health_summary = normalize_sensor_health_summary(ctx.sensor_health_summary)

        if ctx.context_read_failed or (ctx.sensor_health_summary is not None and sensor_health_summary is None):
            await self._dispatch_unavailable_context(
                event=event,
                audit_id=audit_id,
                payload=event.payload,
                kind="periodic_report",
                message="Периодический отчёт не сформирован: данные за интервал недоступны.",
            )
            return
        elif (
            self._config.periodic_report_skip_if_idle
            and ctx.total_event_count < self._config.periodic_report_min_events
            and not ctx.source_saturated
            and (sensor_health_summary is None or sensor_health_summary.critical == 0)
        ):
            logger.debug(
                "AssistantLiveAgent: periodic report skipped (idle: %d events < min=%d)",
                ctx.total_event_count,
                self._config.periodic_report_min_events,
            )
            return

        template_dict = ctx.to_template_dict()
        user_prompt = PERIODIC_REPORT_USER.format(
            window_minutes=window_minutes,
            **template_dict,
        )
        system_prompt = format_with_brand(PERIODIC_REPORT_SYSTEM, self._config.brand_name)

        result = await self._ollama.generate(
            user_prompt,
            system=system_prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("AssistantLiveAgent: periodic report обрезан (audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой periodic report (audit_id=%s)", audit_id)
        dispatched_pr, _ = await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=event.payload,
            context_assembled=user_prompt,
            prompt_template="periodic_report",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            errors=errors,
            targets=targets,
            prefix_suffix=f"(отчёт {_report_window_label(window_minutes)})",
            allow_dispatch=not result.truncated and bool(result.text.strip()),
        )
        logger.info(
            "AssistantLiveAgent: periodic_report_request обработан "
            "(audit_id=%s, latency=%.1fs, events=%d, dispatched=%s)",
            audit_id,
            result.latency_s,
            ctx.total_event_count,
            dispatched_pr,
        )

    async def _dispatch_unavailable_context(
        self,
        *,
        event: EngineEvent,
        audit_id: str,
        payload: dict[str, Any],
        kind: str,
        message: str,
    ) -> None:
        logger.warning("AssistantLiveAgent: %s context unavailable (audit_id=%s)", kind, audit_id)
        await self._dispatch_with_audit(
            event=event,
            audit_id=audit_id,
            payload=payload,
            context_assembled=message,
            prompt_template=f"{kind}_context_unavailable",
            model="deterministic",
            system_prompt="",
            user_prompt=message,
            response=message,
            tokens={"in": 0, "out": 0},
            latency_s=0.0,
            errors=[],
            targets=_build_targets(self._config),
        )


def _build_targets(config: AssistantConfig) -> list[OutputTarget]:
    targets = []
    if config.output_telegram:
        targets.append(OutputTarget.TELEGRAM)
    if config.output_gui_insight:
        targets.append(OutputTarget.GUI_INSIGHT)
    return targets


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Russian numeral agreement: 1 → *one*, 2-4 → *few*, else *many*,
    with the 11-14 teens exception (always *many*)."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _report_window_label(window_minutes: int) -> str:
    """Russian label for a periodic-report time window, used as the dispatch
    ``prefix_suffix`` so the operator sees the *actual* window instead of a
    hardcoded "за час": 60 → "за час", 30 → "за 30 минут", 120 → "за 2 часа"."""
    if window_minutes > 0 and window_minutes % 60 == 0:
        hours = window_minutes // 60
        if hours == 1:
            return "за час"
        return f"за {hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"
    return f"за {window_minutes} {_plural_ru(window_minutes, 'минуту', 'минуты', 'минут')}"


def _format_age(age_s: float | None) -> str:
    if age_s is None:
        return "неизвестно"
    h, rem = divmod(int(age_s), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"













