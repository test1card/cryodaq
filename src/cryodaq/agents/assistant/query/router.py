"""Router for F30 Live Query Agent — dispatches QueryIntent to ServiceAdapters."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import stat
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import (
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)
from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
from cryodaq.paths import get_config_dir

if TYPE_CHECKING:
    from cryodaq.core.channel_manager import ChannelManager

logger = logging.getLogger(__name__)


def _as_finite(value: Any) -> float | None:
    """A number that can be reported, or None. Booleans and NaN are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


class QueryUnavailableError(RuntimeError):
    """Raised when the router cannot establish an authoritative query result."""


#: Units a reading must already be in to become `VacuumETA.current_mbar`.
#:
#: A STOPGAP SPECIFIC TO THIS STAND, not a rule about what a channel is for.
#: The one vacuum gauge here reports in mbar and the one known atmospheric
#: channel, `MultiLine_1/env_pressure`, reports in hPa, so the unit happens to
#: separate them. It does not separate them in general: a barometer configured
#: in mbar would pass this filter and be reported as the chamber pressure.
#:
#: And the hPa case is not a units error — 1 hPa IS 1 mbar. The number is
#: converted correctly and still wrong, because room air is not the chamber.
#: Pa would be a genuine factor of 100; that is a different mistake and this
#: filter excludes it too.
#:
#: The authority for "which channel is the vacuum gauge" is the descriptor, and
#: it takes all three of `quantity: pressure`, `role: primary_measurement` and
#: `safety_class: safety_critical_input` to name it. The last two alone are not
#: enough — Т11 and Т12 carry them as well, so a replacement that followed a
#: shorter rule could make a temperature the chamber pressure. Nothing on this
#: path can read descriptors yet; until it can, this narrows one confirmed live
#: path and claims nothing more.
_VACUUM_UNITS = frozenset({"mbar", "мбар"})


def _reading_is_usable(reading: object) -> bool:
    """`Reading.is_usable()`, and False when the object cannot answer.

    Fails closed: a stand-in without the predicate must not pass for a good
    reading merely because it could not be asked.
    """
    predicate = getattr(reading, "is_usable", None)
    if not callable(predicate):
        return False
    try:
        return predicate() is True
    except Exception:  # noqa: BLE001 - an unanswerable reading is not a usable one
        return False


#: Configuration keys rendered as named fields rather than left in ``settings``.
#: Everything else is passed through AS PARSED -- not verbatim, since the loader
#: has already expanded groups and dropped keys -- because inventing a per-type
#: notion of "the threshold" is how a rate alarm's ``rate_threshold`` would get
#: reported as the pressure it is not.
_ALARM_NAMED_KEYS = frozenset({"level", "channels", "channel", "message"})


def _selectors(node: Any) -> list[str]:
    """The channel selector of one mapping, the way the evaluator resolves it.

    ``channel_group`` is already expanded into ``channels`` by the loader, so
    these two keys are the whole selector.
    """
    found: list[str] = []
    if not isinstance(node, dict):
        return found
    channel = node.get("channel")
    if isinstance(channel, str) and channel:
        found.append(channel)
    channels = node.get("channels")
    if isinstance(channels, list):
        for item in channels:
            if isinstance(item, str) and item and item not in found:
                found.append(item)
    return found


def _evaluated_channels(config: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Split an alarm's channel selectors into (top-level, condition, ignored).

    ONE place, because the boundary has two ends and fixing one end at a time is
    how the same defect arrived twice. Measured against the evaluator:

    - ``_eval_threshold`` (alarm_v2.py:294), ``_eval_rate`` (:548) and
      ``_eval_stale`` (:643) resolve the TOP-LEVEL selector of ``cfg``;
    - ``_eval_composite`` (:412) resolves the selector of each entry in
      ``conditions`` and NEVER the top-level one;
    - ``_eval_rate`` additionally reads ``additional_condition`` (:586);
    - ``_eval_condition`` descends into neither key.

    So a composite carrying a top-level ``channel`` names something the
    evaluator categorically ignores. It is reported as ignored rather than
    dropped: the file says it, and hiding it would be its own kind of lie.
    """
    alarm_type = config.get("alarm_type")
    top: list[str] = []
    conditional: list[str] = []
    ignored: list[str] = []

    if alarm_type in ("threshold", "rate", "stale"):
        top = _selectors(config)
    else:
        ignored = _selectors(config)

    if alarm_type == "composite":
        conditions = config.get("conditions")
        if isinstance(conditions, list):
            for entry in conditions:
                for channel in _selectors(entry):
                    if channel not in conditional:
                        conditional.append(channel)
    elif alarm_type == "rate":
        for channel in _selectors(config.get("additional_condition")):
            if channel not in conditional:
                conditional.append(channel)

    # NOT filtered against `top`, for the SAME reason the ignored list below is
    # not: a rate alarm whose top-level channel is P and whose
    # `additional_condition` also names P has TWO facts about P -- the evaluator
    # reads it in two separate roles -- and dropping the second one rendered
    # "каналы: P" with no mention that a condition reads it too. A reviewer
    # found that. Duplicates are removed WITHIN each role, never across roles.
    # NOT filtered against `conditional`: a composite naming channel A at the
    # top level AND inside a condition has TWO facts about A, and the ignored
    # one used to disappear because the other existed. A reviewer found that.
    # Only a channel the evaluator does read at the top level is not "ignored".
    ignored = [channel for channel in ignored if channel not in top]
    return top, conditional, ignored


def _describe_alarm(alarm: Any) -> dict[str, Any]:
    """Flatten one AlarmConfig into fields an answer can quote without guessing.

    The remaining configuration is passed through as PARSED ``settings`` -- the
    loader has already expanded channel groups and dropped keys, and neither the
    original number spelling nor the file's comments survive it. Naming "the
    threshold" here would mean deciding, per alarm type, which key it is: a rate
    alarm carries ``rate_threshold`` while a composite carries one per
    sub-condition. Passing the parsed settings through is the honest option; the
    answer prompt forbids rounding them.
    """
    config = getattr(alarm, "config", None)
    config = config if isinstance(config, dict) else {}
    # Sorted by the STRING form of the key: YAML admits `2026: обслуживание`,
    # the alarm loader accepts it, and sorting an int against a str raises --
    # losing the whole report over a key that was read successfully.
    settings = {
        key: value
        for key, value in sorted(config.items(), key=lambda item: str(item[0]))
        if key not in _ALARM_NAMED_KEYS
    }
    top_level, conditional, ignored = _evaluated_channels(config)
    message = config.get("message")
    return {
        "id": getattr(alarm, "alarm_id", None),
        "level": config.get("level"),
        # ``rstrip``, not ``strip``: the shipped configuration ends several
        # messages with a newline and the block would carry a stray `\n` for
        # each. A reviewer caught the earlier ``strip`` removing LEADING
        # whitespace too and erasing a whitespace-only message outright, which
        # is not trailing cleanup -- it is quietly editing the operator's text.
        # Breaks INSIDE the text are kept and escaped by the formatter.
        "message": message.rstrip() if isinstance(message, str) else message,
        "channels": top_level,
        # Named separately rather than merged into ``channels``: they are the
        # file's own words about WHERE the channel is bound, and a composite
        # alarm's condition channels are not interchangeable with a top-level
        # channel list.
        "condition_channels": conditional,
        # Written in the definition, read by nothing: a composite's top-level
        # selector, for instance. Reported as such rather than dropped.
        "ignored_channels": ignored,
        "phase_filter": list(getattr(alarm, "phase_filter", None) or []) or None,
        "notify": list(getattr(alarm, "notify", None) or []),
        "settings": settings,
    }


#: The one filename this category reads, kept beside the resolver so the two
#: never drift apart in a way a reader has to reconstruct.
_ALARM_CONFIG_FILENAME = "alarms_v3.yaml"


def _load_described_alarms(config_path: str) -> list[dict[str, Any]]:
    """Load one alarm configuration file and flatten it. Runs off the event loop.

    The missing-file case is separated here on purpose: ``load_alarm_config``
    raises ``AlarmConfigError`` for a file that is not there AND for one that is
    there and invalid, and those are different problems with different next
    steps for the operator. Telling them apart from the message text would mean
    matching on wording that also names alarms.
    """
    # ``os.stat``, NOT ``Path.is_file()``: that method answers False for a
    # permission error and for an I/O error just as it does for a file that is
    # not there, so a reviewer measured PermissionError and OSError both
    # arriving at the operator as "файл не найден" -- three different problems
    # with three different next steps, flattened into the wrong one.
    mode = os.stat(config_path).st_mode
    if not stat.S_ISREG(mode):
        raise IsADirectoryError(config_path) if stat.S_ISDIR(mode) else OSError(f"not a regular file: {config_path}")
    _engine_cfg, alarms = load_alarm_config(config_path)
    return [_describe_alarm(alarm) for alarm in alarms]


def _config_failure_kind(exc: BaseException) -> str:
    """The KIND of read failure, in words that name no alarm and no value.

    Ordered from the most specific OSError subclass outwards, because they are
    all OSError and the first match wins.
    """
    if isinstance(exc, FileNotFoundError):
        return "файл не найден"
    if isinstance(exc, PermissionError):
        return "нет доступа к файлу"
    if isinstance(exc, IsADirectoryError):
        return "по этому пути каталог, а не файл"
    if isinstance(exc, OSError):
        return "файл не читается"
    if isinstance(exc, AlarmConfigError):
        # Covers both "the YAML did not parse" and "it parsed and failed
        # validation": the loader raises this class for both, and telling them
        # apart is not worth naming the offending alarm to do it.
        return "конфигурация не прошла проверку загрузчика"
    return "неизвестный отказ при чтении"


#: How deep the canonical renderer descends before it stops describing and
#: says so. A YAML anchor graph can be deep, and a structure can be made to
#: refer to itself; neither may cost the answer.
_CANONICAL_MAX_DEPTH = 24


def _canonical_container(value: Any, depth: int = 0) -> str:
    """Render a list or mapping so that no two distinct values look the same.

    ``json.dumps(..., default=str)`` was what stood here, and a reviewer showed
    what it costs one level down: ``default=str`` reaches only the types JSON
    does not know, so a nested ``datetime.date(2026, 9, 10)`` and the STRING
    "2026-09-10" both came out as ``"2026-09-10"``. The top level had already
    been fixed by hand; the fix did not descend, which is exactly the shape of
    defect that comes back a third time if it is patched again by hand.

    So the rule is written ONCE and applied recursively, to keys as well as to
    values. Strings are quoted, numbers are not, and a type JSON has never heard
    of carries its type name -- `date:2026-09-10` -- which no quoted string can
    imitate.

    What this does NOT establish: two distinct objects of the SAME unknown type
    whose ``str`` agrees still render alike. Preserving that would mean ``repr``,
    and ``repr`` on a date is `datetime.date(2026, 9, 10)` -- unreadable in an
    answer whose purpose is to quote the file back to the operator.
    """
    if depth > _CANONICAL_MAX_DEPTH:
        # Not an exception: a structure this deep is still a structure the
        # loader accepted, and the operator is owed the rest of the report.
        return "<вложенность глубже допустимой>"
    if isinstance(value, dict):
        items = [(_canonical_scalar(key, depth + 1), _canonical_scalar(item, depth + 1)) for key, item in value.items()]
        # Sorted by the RENDERED key, which is total: sorting the keys
        # themselves raises the moment a mapping holds both `2026` and "2026",
        # and the alarm loader accepts exactly that.
        body = ", ".join(f"{key}: {item}" for key, item in sorted(items))
        return "{" + body + "}"
    if isinstance(value, (set, frozenset)):
        rendered = sorted(_canonical_scalar(item, depth + 1) for item in value)
        return f"{type(value).__name__}{{" + ", ".join(rendered) + "}"
    if isinstance(value, tuple):
        # TAGGED, because a tuple and a list are different values and `[a, b]`
        # for both would be one more collision of the kind this exists to end.
        return "tuple[" + ", ".join(_canonical_scalar(item, depth + 1) for item in value) + "]"
    return "[" + ", ".join(_canonical_scalar(item, depth + 1) for item in value) + "]"


def _canonical_scalar(value: Any, depth: int = 0) -> str:
    """The same contract as ``_render_alarm_setting``, one level down."""
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return _canonical_container(value, depth)
    return _render_alarm_setting(value)


def _render_alarm_identifier(value: Any) -> str:
    """Render an alarm id, a level or a settings key -- readably, and injectively.

    These sit where the operator READS them, so the common case must stay bare:
    `vacuum_high`, not `"vacuum_high"`. But bare is not enough on its own. A
    reviewer pointed out that one valid YAML mapping may carry both `0:` and
    `"0":` -- the loader keeps them as an int and a str -- and both rendered as
    `0`, two rows for two different definitions that a reader cannot tell apart.

    The rule: a string is shown as it is, unless it is EMPTY, shaped like the
    type tag below (`name:` at its start) or already begins with a quote, in which case
    it is quoted so it can impersonate neither a tag nor a quoted form. Anything
    that is not a string carries its type name.

    The second half of that condition is not decoration. A reviewer reproduced
    the collision it closes: the id `int:0` is tag-shaped, so it renders quoted
    as `"int:0"` -- and a DIFFERENT id whose own characters are `"int:0"`,
    quotes included, was left bare and produced the same six characters. Two
    parsed ids, two rows, byte-identical. The three forms are prefix-free now:
    a tag never starts with a quote, a quoted form always does, and a bare
    string does neither.
    """
    if isinstance(value, str):
        if not value or _TAG_SHAPED.match(value) or value.startswith('"'):
            # THE EMPTY STRING TOO. Bare, it renders as nothing at all -- an
            # alarm keyed `"":` produced `  [WARNING]`, a row with no visible
            # identifier, which is indistinguishable from every other way of
            # having none. Quoted, it is `""` and says exactly what the file
            # says.
            return json.dumps(value, ensure_ascii=False)
        return value
    rendered = _canonical_scalar(value)
    if _TAG_SHAPED.match(rendered):
        # ALREADY tagged by the setting rule -- a `datetime.date` renders as
        # `date:2026-09-10` there. Prefixing again gave `date:date:2026-09-10`,
        # which is not wrong so much as unreadable, and it made the two rules
        # disagree about what a tag looks like.
        return rendered
    return f"{type(value).__name__}:{rendered}"


#: A string that could be read as the `type:value` tag above.
_TAG_SHAPED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*:")


def _render_alarm_setting(value: Any) -> str:
    """Render one parsed configuration value without rounding it.

    The contract is the parsed NUMERIC VALUE, not the YAML spelling: by the time
    the loader is done, `1.0e-5` and `0.00001` are the same float and the source
    lexeme is gone. ``repr`` gives the shortest string that round-trips back to
    that float, so nothing is lost that survived parsing -- but a reader should
    not expect the file's own notation, and `1e-4` legitimately arrives as
    `0.0001`. A format spec would be the real hazard: it rounds silently.
    """
    if isinstance(value, str):
        # QUOTED, so a string cannot impersonate a number or a structure. A
        # reviewer showed `min_fault_count: {threshold: 999}` and the string
        # `'{"threshold": 999}'` rendering identically, and `3` beside `"3"`
        # likewise -- the evaluator compares those numerically and would not.
        # The type is part of the value; losing it here is losing information
        # before any escaping can help.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (bytes, bytearray)):
        return f"{type(value).__name__}:{value!r}"
    if not isinstance(value, (list, tuple, dict, set)):
        # A SCALAR of a type JSON does not know -- the loader produces
        # `datetime.date` for a bare `2026-09-10` -- rendered as `date:2026-09-10`
        # rather than through `default=str`, which made it identical to the
        # STRING "2026-09-10". A reviewer showed the two collapsing into one.
        return f"{type(value).__name__}:{value}"
    try:
        return _canonical_container(value)
    except Exception:  # noqa: BLE001 - see below; this must not be the failing step
        # The YAML loader produces types JSON does not know -- a reviewer
        # reproduced `maintenance_date: 2026-09-10` arriving as ``datetime.date``,
        # which the alarm loader accepts and this function then choked on,
        # taking the whole answer down with it. Rendering must not fail: the
        # configuration is written by hand and this code does not get to decide
        # which of its values are allowed to exist. ``default=str`` handles the
        # unknown types; ValueError covers a circular reference and mixed key
        # types under ``sort_keys``; RecursionError covers a deep anchor graph.
        # The catch is deliberately broad rather than a list of those three: a
        # reviewer noted ``default=str`` can itself raise from inside
        # ``json.dumps``, and a rendering helper that takes the answer down is
        # the one outcome this whole branch exists to prevent.
        try:
            return str(value)
        except Exception:  # noqa: BLE001 - a __str__ of its own may raise too
            return f"<значение типа {type(value).__name__} не отображается>"


class QueryRouter:
    """Dispatches a classified QueryIntent to the appropriate ServiceAdapter.

    Returns a category-specific data dict when dispatch succeeds, including
    authoritative empty results. Raises QueryUnavailableError when dispatch fails.
    The data dict is category-specific and is passed to the format LLM in Phase C.
    """

    def __init__(
        self,
        adapters: QueryAdapters,
        *,
        channel_manager: ChannelManager | None = None,
    ) -> None:
        self._adapters = adapters
        self._channel_manager = channel_manager

    async def _resolve_target_channels(self, intent: QueryIntent) -> list[str] | None:
        """Validate and resolve target_channels against current ChannelManager.

        Late binding: reads ChannelManager fresh on every call, picks up renames.
        """
        if not intent.target_channels:
            return None
        if self._channel_manager is None:
            return list(intent.target_channels)
        all_ids = set(self._channel_manager.get_all())
        resolved: list[str] = []
        for raw in intent.target_channels:
            raw_s = raw.strip()
            if raw_s in all_ids:
                resolved.append(raw_s)
                continue
            # Latin→Cyrillic normalization: "T12" → "Т12" (keyboard layout mismatch)
            norm_id = self._channel_manager.normalize_channel_id(raw_s)
            if norm_id != raw_s and norm_id in all_ids:
                resolved.append(norm_id)
                continue
            # F-ChannelLandmarks: consult landmark aliases (Т11/Т12) BEFORE
            # falling through to experiment-level name matching, so the
            # priority promised by the classifier prompt also holds at the
            # resolver layer when Gemma echoes an alias verbatim.
            landmark_id = self._channel_manager.find_by_landmark_alias(raw_s)
            if landmark_id:
                resolved.append(landmark_id)
                continue
            match_id = self._channel_manager.find_by_name(raw_s)
            if match_id:
                resolved.append(match_id)
                continue
            # Last: the channel may simply not be in channels.yaml. The gauge
            # and the source meter never have been, and the classifier is now
            # told they exist — so refusing them here would advertise a channel
            # and then drop it, which is what happened until 2026-09-07.
            snapshot = getattr(self._adapters, "broker_snapshot", None)
            if snapshot is not None and hasattr(snapshot, "knows"):
                try:
                    if await snapshot.knows(raw_s):
                        resolved.append(raw_s)
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - resolution must not fail a query
                    logger.debug("QueryRouter: live-channel check unavailable: %s", exc)
            logger.warning("QueryRouter: cannot resolve target_channel %r to known ID", raw)
        return resolved if resolved else None

    async def fetch(
        self,
        intent: QueryIntent,
        query: str,
    ) -> dict[str, Any]:
        """Fetch authoritative data for a classified intent.

        Returns a dict with category-specific fields. Out-of-scope and unknown
        categories return an empty dict (no data fetch needed — format LLM handles it).
        """
        cat = intent.category
        try:
            if cat == QueryCategory.CURRENT_VALUE:
                return await self._fetch_current_value(intent)
            if cat == QueryCategory.ETA_COOLDOWN:
                return await self._fetch_eta_cooldown()
            if cat == QueryCategory.ETA_VACUUM:
                return await self._fetch_eta_vacuum()
            if cat == QueryCategory.RANGE_STATS:
                return await self._fetch_range_stats(intent)
            if cat == QueryCategory.PHASE_INFO:
                return await self._fetch_phase_info()
            if cat == QueryCategory.ALARM_STATUS:
                return await self._fetch_alarm_status()
            if cat == QueryCategory.COMPOSITE_STATUS:
                return await self._fetch_composite()
            if cat == QueryCategory.SYSTEM_HEALTH:
                return await self._fetch_system_health()
            if cat == QueryCategory.ALARM_CONFIG:
                return await self._fetch_alarm_config()
            # F33 — read-only archive queries.
            if cat == QueryCategory.ARCHIVE_LIST:
                return await self._fetch_archive_list(intent)
            if cat == QueryCategory.ARCHIVE_DETAIL:
                return await self._fetch_archive_detail(intent, query)
            if cat == QueryCategory.ALARM_HISTORY:
                return await self._fetch_alarm_history(intent)
            # F32 Stage 2 (v0.55.7) — semantic search over RAG corpus.
            if cat == QueryCategory.KNOWLEDGE_QUERY:
                return await self._fetch_knowledge_query(intent, query)
            # Out-of-scope and unknown: no data needed
            return {}
        except Exception as exc:
            logger.warning("QueryRouter.fetch failed for %s: %s", cat.value, exc)
            raise QueryUnavailableError(f"{cat.value} query unavailable") from exc

    async def _fetch_current_value(self, intent: QueryIntent) -> dict[str, Any]:
        channels = await self._resolve_target_channels(intent) or []
        snapshot = self._adapters.broker_snapshot
        readings = {}
        for ch in channels:
            r = await snapshot.latest(ch)
            if r is not None:
                readings[ch] = r
        # Also include age
        ages = {}
        for ch in channels:
            age = await snapshot.latest_age_s(ch)
            if age is not None:
                ages[ch] = age
        return {"readings": readings, "ages_s": ages, "channels": channels}

    async def _fetch_eta_cooldown(self) -> dict[str, Any]:
        eta = await self._adapters.cooldown.eta()
        return {"cooldown_eta": eta}

    async def _fetch_eta_vacuum(self) -> dict[str, Any]:
        # Target comes from the engine's configuration, which is where the
        # gauge's range is accounted for. A pressure hardcoded here can
        # ask for something this stand cannot measure.
        eta = await self._adapters.vacuum.eta_to_target()
        # Also get current pressure from snapshot
        snapshot = self._adapters.broker_snapshot
        all_ch = await snapshot.latest_all()
        # THE NAME OF A CHANNEL IS NOT EVIDENCE OF WHAT IT MEASURES. Matching
        # "pressure" in the channel id admits `MultiLine_1/env_pressure` — the
        # room's air, declared `role: environment`, `safety_class:
        # observational` — and whichever pressure-like channel the snapshot
        # yielded first won. With the barometer publishing before the gauge,
        # the operator asking how long the pump-down has left was told the
        # chamber sat at 1013, with no fault anywhere to explain it. Measured
        # on the committed code, not supposed.
        #
        # The unit filter below narrows that confirmed path on THIS stand,
        # where the gauge is in mbar and the barometer in hPa. It is not a rule
        # about purpose: a barometer configured in mbar would still pass. See
        # `_VACUUM_UNITS`.
        #
        # THE STATUS DECIDES WHETHER TO USE IT. `Reading.is_usable()` is the
        # repository's one predicate for a reading worth acting on, and every
        # acting path gates on it — the interlock, the alarms, the safety
        # manager. This path answers "сколько ещё откачивать" and used to take
        # the value whatever the gauge said about itself, so a SENSOR_ERROR
        # reading came back as "Давление сейчас: 1.23e-04".
        #
        # An unusable gauge is skipped rather than ending the search, so it no
        # longer hides a good one behind it. Which gauge wins among several
        # usable ones in millibars is whatever order the snapshot yields, as it
        # always was; choosing an authoritative channel is its own question.
        current_p = None
        for reading in all_ch.values():
            if (getattr(reading, "unit", "") or "").strip().lower() not in _VACUUM_UNITS:
                continue
            if not _reading_is_usable(reading):
                continue
            current_p = reading.value
            if eta is not None:
                eta.current_mbar = current_p
            break
        return {"vacuum_eta": eta, "current_pressure": current_p}

    async def _fetch_range_stats(self, intent: QueryIntent) -> dict[str, Any]:
        channels = await self._resolve_target_channels(intent) or []
        window = intent.time_window_minutes or 60
        results = {}
        for ch in channels:
            stats = await self._adapters.sqlite.range_stats(ch, window)
            if stats is not None:
                results[ch] = stats
        # If no specific channels, try snapshot for pressure as default range
        if not channels:
            all_ch = await self._adapters.broker_snapshot.latest_all()
            for ch in all_ch:
                if "pressure" in ch.lower() or "mbar" in ch.lower():
                    stats = await self._adapters.sqlite.range_stats(ch, window)
                    if stats is not None:
                        results[ch] = stats
                    break
        return {"range_stats": results, "window_minutes": window}

    async def _fetch_phase_info(self) -> dict[str, Any]:
        status = await self._adapters.experiment.status()
        return {"experiment_status": status}

    async def _fetch_system_health(self) -> dict[str, Any]:
        """Report what the assistant OBSERVES, and mark everything else unknown.

        The assistant is a separate process that sees the bus and nothing else.
        Readings arriving proves the engine is publishing; it proves nothing
        about the writer, the disk, or the locks, which live on the other side
        of a process boundary this code cannot cross.

        Every field is a three-state value -- True, False, or None for "not
        established" -- and never an optimistic default. Two review rounds each
        found an unknown wearing a reassurance: first a missing field read as
        "да", then `available is not False` turning an unknown availability into
        a confident one. Neither is a detail; both are the failure this category
        exists to prevent.
        """
        status = await self._adapters.composite.status()

        def _tristate(name: str) -> bool | None:
            value = getattr(status, name, None)
            return value if isinstance(value, bool) else None

        # The adapter marks a status unavailable when it could not read the
        # snapshot, and stale when the values are cached rather than current.
        # Unknown stays unknown: a status object that does not say is not a
        # status object that says yes.
        available = _tristate("available")
        stale = _tristate("stale")
        readable = available if available is not None else None
        current = None if readable is not True or stale is None else not stale

        key_channels = getattr(status, "key_temperatures", None)
        if not isinstance(key_channels, dict) or readable is not True:
            with_values = None
            total = None
        else:
            with_values = sum(1 for value in key_channels.values() if _as_finite(value) is not None)
            if _as_finite(getattr(status, "current_pressure", None)) is not None:
                with_values += 1
            total = len(key_channels) + 1

        return {
            "status_readable": readable,
            "values_are_current": current,
            "unreadable_reason": getattr(status, "reason", None) if readable is not True else None,
            # Whether the cache holds anything AT ALL -- not whether anything is
            # arriving. The cache keeps its last values indefinitely.
            "cache_empty": _tristate("snapshot_empty") if readable is True else None,
            # Seconds since anything ARRIVED: the only field that separates a
            # live engine from the last words a stopped one left behind.
            "arrival_age_s": getattr(status, "snapshot_arrival_age_s", None) if readable is True else None,
            # Age of the OLDEST: answers whether some channel has gone quiet.
            "oldest_age_s": getattr(status, "snapshot_age_s", None) if readable is True else None,
            # Cached entries, NOT an inventory of enabled channels: a channel
            # that has never published contributes to neither number.
            "key_channels_with_values": with_values,
            "key_channels_total": total,
            "alarms_available": _tristate("alarms_available") if readable is True else None,
        }

    async def _fetch_alarm_config(self) -> dict[str, Any]:
        """Read the alarm configuration FILE, and claim nothing about the engine.

        There is no engine command for this. ``alarm_v2_status`` returns the
        alarms that are FIRING plus history; the configured set is not on the
        wire at all, and adding a command would be an engine change and an
        engine deploy. So the source is the file, and the reader is told so --
        the one thing this cannot establish is that the running engine loaded
        this file, and that boundary belongs in the answer rather than in a
        silent assumption.

        Disabling an alarm on this stand means COMMENTING IT OUT: measured on
        the shipped config, ``vacuum_stall`` was removed that way on the
        owner's ruling 2026-08-31, and ``load_alarm_config`` has no notion of
        an ``enabled`` flag. An id that is absent from the loaded set is absent
        from this file's alarm DEFINITIONS -- not "disabled", which would be a
        claim about a comment this code never reads.

        Loaded is NOT the same as enabled, and the answer must not say it is:
        commenting out is one removal mechanism among several. The evaluator
        also drops channels the operator hid in Settings from part of the
        alarms -- and only part, since conditions reading a channel directly
        bypass that filter -- and none of that is visible here.
        """
        # Resolved through the SAME helper the rest of the application uses, so
        # the file read here is the file a deployment configured. Measured by a
        # reviewer: ``alarm_config._find_default_config`` walks up from its own
        # module, so with ``CRYODAQ_ROOT`` pointing at a deployment tree it
        # resolves the SOURCE checkout's config while the engine loads the
        # deployment's -- and the assistant would have named the wrong file with
        # complete confidence. Resolved BEFORE the read, so a parse failure can
        # still say which file was attempted.
        config_path = str(get_config_dir() / _ALARM_CONFIG_FILENAME)

        try:
            described = await asyncio.to_thread(_load_described_alarms, config_path)
        except Exception as exc:  # noqa: BLE001 - a config read must not fail the query
            # Named, not swallowed: an unreadable configuration is the one
            # answer this category must never dress up as an empty one. "No
            # alarms are configured" and "I could not read the file" are
            # opposite facts and the operator has to be able to tell them apart.
            #
            # The KIND of failure reaches the answer; the loader's own words do
            # not. A reviewer reproduced a validation message reading
            # "alarm 'secret_alarm' ... requires a numeric 'threshold', got
            # 'not-a-number'" -- alarm ids, fields and values, landing inside a
            # block whose whole job is to make no claim about what is
            # configured. The detail belongs in the log, where diagnosis
            # happens, not in an answer that has just said it knows nothing.
            logger.warning(
                "alarm configuration unavailable (%s): %s: %s",
                config_path,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return {
                "config_readable": False,
                "config_error": _config_failure_kind(exc),
                "config_path": config_path,
                "alarms": [],
            }
        return {
            "config_readable": True,
            "config_error": None,
            "config_path": config_path,
            "alarms": described,
        }

    async def _fetch_alarm_status(self) -> dict[str, Any]:
        result = await self._adapters.alarms.active()
        return {"alarm_result": result}

    async def _fetch_composite(self) -> dict[str, Any]:
        composite = await self._adapters.composite.status()
        return {"composite_status": composite}

    # ------------------------------------------------------------------
    # F33 — archive queries
    # ------------------------------------------------------------------

    @staticmethod
    def _days_from_intent(intent: QueryIntent, default_days: int = 7) -> int:
        """Convert ``time_window_minutes`` (the IntentClassifier's only time
        knob) to whole days, defaulting to ``default_days`` when absent.
        Minimum window is 1 day so the LLM cannot ask for "0 days"."""
        win = intent.time_window_minutes
        if win is None or win <= 0:
            return default_days
        return max(1, int(win) // 1440 or 1)

    async def _fetch_archive_list(self, intent: QueryIntent) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"archive_list": None}
        days = self._days_from_intent(intent)
        result = await archive.list_recent(days=days)
        return {"archive_list": result}

    async def _fetch_archive_detail(self, intent: QueryIntent, query: str) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"archive_detail": None}
        # Heuristic: the IntentClassifier may surface an experiment id via
        # ``quantity`` or as the only entry in ``target_channels`` (the LLM
        # sometimes treats it as a "channel"). Pass an empty candidate to the
        # adapter so it returns a typed invalid request, not an absence.
        candidate = (intent.quantity or "").strip()
        if not candidate and intent.target_channels:
            candidate = intent.target_channels[0].strip()
        result = await archive.get_detail(candidate)
        return {"archive_detail": result, "experiment_id": candidate}

    async def _fetch_alarm_history(self, intent: QueryIntent) -> dict[str, Any]:
        archive = self._adapters.archive
        if archive is None:
            return {"alarm_history": None}
        days = self._days_from_intent(intent)
        result = await archive.alarm_history_summary(days=days)
        return {"alarm_history": result}

    # ------------------------------------------------------------------
    # F32 Stage 2 (v0.55.7) — knowledge query
    # ------------------------------------------------------------------

    async def _fetch_knowledge_query(self, intent: QueryIntent, query: str) -> dict[str, Any]:
        """Run semantic search over the RAG corpus.

        ``query`` is preferred over ``intent.quantity`` because the original
        operator phrasing carries far more retrieval signal than the
        classifier's brief paraphrase. ``target_source_kind`` (when present)
        narrows the LanceDB ``WHERE`` clause to a single corpus kind.
        """
        adapter = self._adapters.rag
        if adapter is None or not getattr(adapter, "is_available", False):
            return {"knowledge_query": None, "query": query}
        result = await adapter.search(
            query,
            source_kind=intent.target_source_kind,
        )
        return {"knowledge_query": result, "query": query}
