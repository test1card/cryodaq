"""«Движок жив? Запись идёт?» — the operator's own hourly checklist.

Measured 2026-09-10 by running the real intent classifier over realistic
operator questions: "движок жив?" fell to unknown, "сколько осталось места на
диске?" to out_of_scope_general, "когда последний раз перезапускался движок?" to
out_of_scope_historical. Those are exactly the questions the operator currently
has to answer by hand, so the assistant learns the ones it can honestly answer.

What it can honestly answer is narrow, and that narrowness is the point. The
assistant is a separate process that sees the bus. Readings arriving proves the
engine is publishing. It proves NOTHING about the writer, the disk, the locks or
the logs, which sit on the other side of a process boundary this code cannot
cross -- so the answer prompt is required to name those as unknowable rather
than to infer them from the one signal it does have.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.prompts import INTENT_CLASSIFIER_SYSTEM
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import QueryAdapters, QueryCategory, QueryIntent

_QUESTION = "движок жив?"


def _adapters(**status_fields) -> QueryAdapters:
    status = MagicMock()
    status.snapshot_empty = status_fields.get("snapshot_empty", False)
    status.snapshot_age_s = status_fields.get("snapshot_age_s", 3.0)
    status.snapshot_arrival_age_s = status_fields.get("snapshot_arrival_age_s", 2.0)
    status.alarms_available = status_fields.get("alarms_available", True)
    status.available = status_fields.get("available", True)
    status.stale = status_fields.get("stale", False)
    status.reason = status_fields.get("reason", None)
    status.key_temperatures = status_fields.get("key_temperatures", {"Т12": 271.0, "Т1": 4.2})
    status.current_pressure = status_fields.get("current_pressure", 3e-2)
    composite = MagicMock()
    composite.status = AsyncMock(return_value=status)
    return QueryAdapters(
        broker_snapshot=MagicMock(),
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=composite,
    )


async def _answer_prompt(**status_fields) -> str:
    """Through the real router and the real dispatch, not a hand-built payload."""
    data = await QueryRouter(_adapters(**status_fields)).fetch(
        QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION
    )
    # A real instance without __init__: passing MagicMock() as self would send
    # the call to a mocked _format_dispatch and every assertion below would be
    # made against a mock's repr instead of the prompt. Method resolution has
    # to be real for this to test the dispatch at all.
    agent = object.__new__(AssistantQueryAgent)
    return agent._build_format_user_prompt(_QUESTION, QueryCategory.SYSTEM_HEALTH, data)


# ---------------------------------------------------------------------------
# The category has to be reachable at all
# ---------------------------------------------------------------------------


def test_the_classifier_is_told_the_category_exists() -> None:
    """An enum member the classifier was never taught is a silent no-op.

    The category can only ever be produced by the model, so adding it to the
    enum and the router while forgetting the prompt would wire a branch that
    nothing can reach -- and every other test here would still pass.
    """
    # Two separate places, and the category is unreachable if EITHER is missing.
    # The rule tells the model when to choose it; the declared JSON union tells
    # it the value is legal at all. A token-only assertion passes when either
    # one is deleted, because the other still contains the word.
    assert f"→ {QueryCategory.SYSTEM_HEALTH.value}:" in INTENT_CLASSIFIER_SYSTEM

    union = INTENT_CLASSIFIER_SYSTEM.split("<one of:", 1)[1].split(">", 1)[0]
    assert QueryCategory.SYSTEM_HEALTH.value in union, "the category is not in the declared JSON union"


async def test_the_router_answers_the_category_instead_of_falling_through() -> None:
    """Unrouted categories return {} and the answer is written from nothing."""
    data = await QueryRouter(_adapters()).fetch(QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION)

    assert data != {}
    assert data["cache_empty"] is False
    assert data["key_channels_with_values"] == 3
    assert data["key_channels_total"] == 3
    # The two ages answer different questions and must both survive the fetch.
    assert data["arrival_age_s"] == 2.0
    assert data["oldest_age_s"] == 3.0


async def test_a_key_channel_without_a_value_is_not_counted_as_publishing() -> None:
    """Present in the summary and holding None are different things."""
    data = await QueryRouter(_adapters(key_temperatures={"Т12": 271.0, "Т1": None})).fetch(
        QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION
    )

    assert data["key_channels_with_values"] == 2
    assert data["key_channels_total"] == 3


async def test_the_number_is_not_presented_as_an_inventory_or_a_driver_check() -> None:
    """An operator with twelve channels must not read "3 из 3" as the whole bus.

    Nor as proof that every driver is connected: a channel that is switched on
    but has never published appears in neither the numerator nor the
    denominator, so the fraction cannot speak for it.
    """
    prompt = await _answer_prompt()

    assert "3 из 3" in prompt
    # The label itself, not only the disclaimer under it. Relabelling the line
    # "всего каналов шины со значением" while keeping the disclaimer produces a
    # prompt that contradicts itself, and an assertion on the disclaimer alone
    # cannot see that.
    assert "ключевых каналов со значением" in prompt
    assert "НЕ инвентарь каналов и НЕ проверка драйверов" in prompt
    assert "НЕЛЬЗЯ сказать, что" in prompt


async def test_the_answer_refuses_to_certify_that_every_driver_is_connected() -> None:
    """The classifier sends "всё ли на связи" here, and the data cannot answer it.

    key_temperatures is built from readings ALREADY in the snapshot, so a
    channel whose driver has never published is absent from both numerator and
    denominator. "3 из 3" can therefore be true while an enabled driver is
    silent -- which is precisely the question the operator asked.
    """
    prompt = await _answer_prompt()

    assert "НЕ может подтвердить, что все драйверы на связи" in prompt
    assert "полноту проверить нельзя" in prompt


# ---------------------------------------------------------------------------
# What it reports
# ---------------------------------------------------------------------------


async def test_flowing_readings_are_reported_as_flowing() -> None:
    prompt = await _answer_prompt(snapshot_arrival_age_s=2.0, stale=False)

    assert "последнее показание пришло: 2 c назад" in prompt
    assert "2 c" in prompt


async def test_a_stale_cache_is_not_reported_as_a_live_stream() -> None:
    """The defect this whole category exists to avoid, in its purest form.

    BrokerSnapshot keeps its last values indefinitely, so an engine that stopped
    an hour ago leaves a full cache behind. An earlier version read that cache's
    non-emptiness as "показания приходят: да" and printed the age beside it.
    """
    prompt = await _answer_prompt(snapshot_arrival_age_s=3600.0, snapshot_age_s=3600.0, stale=False)

    assert "последнее показание пришло: 3600 c назад" in prompt
    assert "3600 c назад" in prompt
    assert "«не пуст» НЕ" in prompt


async def test_one_quiet_channel_is_not_a_stopped_stream() -> None:
    """The oldest age answers a different question from the newest.

    Reading the OLDEST age as the flow signal would call a live stream dead the
    moment any single channel went quiet.
    """
    prompt = await _answer_prompt(snapshot_arrival_age_s=2.0, snapshot_age_s=3600.0, stale=False)

    assert "последнее показание пришло: 2 c назад" in prompt
    assert "3600 c назад" in prompt


async def test_cached_values_are_not_a_live_stream() -> None:
    """available=True with stale=True is schema-valid and means "from cache"."""
    prompt = await _answer_prompt(stale=True, reason="cached")

    assert "свежесть не установлена" in prompt


async def test_an_empty_bus_is_reported_as_empty() -> None:
    prompt = await _answer_prompt(
        snapshot_empty=True, key_temperatures={}, current_pressure=None, snapshot_arrival_age_s=None
    )

    # NOT "there is nothing on the bus": this process has received nothing,
    # which is also what a freshly restarted assistant sees.
    assert "этот помощник ещё ничего не получал" in prompt


@pytest.mark.parametrize("age", [None, float("nan"), float("inf"), -5.0, True, "3"])
async def test_an_unusable_age_is_reported_as_unknown(age: object) -> None:
    """Unknown, nonsense and negative ages are all "not established".

    A negative age is a paired-clock violation, not a reading from the future,
    and rendering it as a small number would make it the strongest possible
    evidence of freshness.
    """
    prompt = await _answer_prompt(snapshot_arrival_age_s=age, stale=False)

    assert "последнее показание пришло: неизвестно" in prompt


async def test_unreadable_alarms_are_not_reported_as_no_alarms() -> None:
    prompt = await _answer_prompt(alarms_available=False)

    assert "НЕТ — прочитать не удалось" in prompt


# ---------------------------------------------------------------------------
# What it must refuse to infer
# ---------------------------------------------------------------------------


async def test_the_answer_is_told_which_questions_it_cannot_answer() -> None:
    """Without this the format model will helpfully invent a disk check.

    The assertion carries the negation, not just the nouns. Asserting that the
    word "диске" appears would survive turning "Ему НЕ видны" into "Ему видны"
    -- an inversion that reverses the whole contract while every noun stays put.
    """
    prompt = await _answer_prompt()

    assert "Ему НЕ видны" in prompt
    for unknowable in ("процесс", "блокировк", "записи в базу", "место на диске", "логов"):
        assert unknowable in prompt, f"the prompt does not disclaim {unknowable!r}"


async def test_the_answer_is_forbidden_to_infer_writes_from_readings() -> None:
    """Readings and persistence are different subsystems; one can fail alone."""
    prompt = await _answer_prompt()

    assert "НЕ выводи" in prompt
    assert "разные подсистемы" in prompt


async def test_an_unknown_is_not_allowed_to_be_rewritten_as_fine() -> None:
    prompt = await _answer_prompt()

    assert "Где написано «неизвестно» — так и говори: не знаю" in prompt
    assert "Не заменяй это на «всё в" in prompt


# ---------------------------------------------------------------------------
# An unknown must never render as a reassurance
# ---------------------------------------------------------------------------


async def test_a_status_without_the_fields_is_unknown_not_healthy() -> None:
    """The failure a reviewer reproduced: a missing field read as "да"."""
    bare = MagicMock()
    del bare.snapshot_empty
    del bare.alarms_available
    bare.available = True
    bare.key_temperatures = {}
    bare.current_pressure = None
    bare.snapshot_age_s = 3.0
    composite = MagicMock()
    composite.status = AsyncMock(return_value=bare)
    adapters = QueryAdapters(
        broker_snapshot=MagicMock(),
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=composite,
    )
    data = await QueryRouter(adapters).fetch(QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION)
    prompt = object.__new__(AssistantQueryAgent)._build_format_user_prompt(_QUESTION, QueryCategory.SYSTEM_HEALTH, data)

    # Either wording is honest; what must never appear is an affirmation.
    assert "последнее показание пришло" in prompt
    assert "тревог читается: неизвестно" in prompt


async def test_a_failed_read_is_not_reported_as_an_empty_bus() -> None:
    """Failing to observe is not observing an absence."""
    prompt = await _answer_prompt(available=False, stale=True, reason="снимок недоступен")

    assert "прочитать не удалось" in prompt
    assert "снимок недоступен" in prompt
    # Failing to observe must not be rendered as observing an absence.
    assert "ещё ничего не получал" not in prompt


async def test_a_nan_reading_does_not_count_as_a_present_value() -> None:
    data = await QueryRouter(
        _adapters(key_temperatures={"Т12": float("nan"), "Т1": 4.2}, current_pressure=float("nan"))
    ).fetch(QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION)

    assert data["key_channels_with_values"] == 1
    assert data["key_channels_total"] == 3


# ---------------------------------------------------------------------------
# The production path, not just the pieces
# ---------------------------------------------------------------------------


async def test_the_classifier_really_sends_the_category_to_the_model() -> None:
    """Through IntentClassifier over a real client and a mocked transport.

    The prompt constant containing "system_health" proves only that the string
    exists in the file. What matters is that it reaches the model: a caller that
    trimmed or rewrote the system prompt would leave the constant untouched and
    the category permanently unreachable.
    """
    from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier
    from cryodaq.agents.assistant.shared.ollama_client import OllamaClient

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(
        return_value={
            "model": "qwen38",
            "choices": [{"message": {"content": '{"category": "system_health"}'}, "finish_reason": "stop"}],
        }
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = AsyncMock()
    session.closed = False
    session.post = MagicMock(return_value=cm)

    client = OllamaClient(base_url="http://127.0.0.1:11434", default_model="qwen38", api="openai")
    client._session = session

    intent = await IntentClassifier(client).classify("движок жив?")

    sent = session.post.call_args[1]["json"]["messages"]
    system_text = "\n".join(str(m.get("content", "")) for m in sent if m.get("role") == "system")

    # Both places, for the same reason the constant test checks both: the rule
    # tells the model when to choose the category, the declared union tells it
    # the value is legal at all, and a caller that strips either one leaves the
    # other's copy of the word behind for a token-only assertion to find.
    assert f"→ {QueryCategory.SYSTEM_HEALTH.value}:" in system_text
    union = system_text.split("<one of:", 1)[1].split(">", 1)[0]
    assert QueryCategory.SYSTEM_HEALTH.value in union, "the sent prompt does not declare the category"
    assert intent.category is QueryCategory.SYSTEM_HEALTH


def test_the_answer_is_built_for_the_category_that_was_classified() -> None:
    """A source guard, and it proves nothing about runtime behaviour.

    Standing up the whole query path would mean faking the engine, ZMQ and
    Telegram. This checks the one thing that would otherwise fail silently: the
    production caller passing a LITERAL category instead of the classified one
    would route every question to a single formatter while every unit test here
    kept passing.
    """
    import ast
    import inspect

    from cryodaq.agents.assistant.query import agent as agent_module

    tree = ast.parse(inspect.getsource(agent_module))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_build_format_user_prompt"
    ]

    assert calls, "the answer is no longer built through _build_format_user_prompt"
    for call in calls:
        category_arg = call.args[1] if len(call.args) > 1 else None
        assert isinstance(category_arg, ast.Attribute) and category_arg.attr == "category", (
            "the formatter must be given the classified category, not a literal"
        )


async def test_a_boolean_masquerading_as_a_reading_is_not_counted() -> None:
    """bool is an int subclass, so a truthy flag would count as a value."""
    data = await QueryRouter(_adapters(key_temperatures={"Т12": True, "Т1": 4.2})).fetch(
        QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION
    )

    assert data["key_channels_with_values"] == 2
    assert data["key_channels_total"] == 3


async def test_an_absent_availability_field_is_unknown_not_available() -> None:
    """`available is not False` turned an unknown into a confident yes.

    A status object that does not say whether it is available is not a status
    object that says it is. The earlier missing-fields test kept available=True
    and so could not see this.
    """
    bare = MagicMock()
    del bare.available
    bare.stale = False
    bare.reason = None
    bare.snapshot_empty = False
    bare.snapshot_age_s = 3.0
    bare.snapshot_arrival_age_s = 2.0
    bare.alarms_available = True
    bare.key_temperatures = {"Т12": 271.0}
    bare.current_pressure = 3e-2
    composite = MagicMock()
    composite.status = AsyncMock(return_value=bare)
    adapters = QueryAdapters(
        broker_snapshot=MagicMock(),
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=composite,
    )
    data = await QueryRouter(adapters).fetch(QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION)
    prompt = object.__new__(AssistantQueryAgent)._build_format_user_prompt(_QUESTION, QueryCategory.SYSTEM_HEALTH, data)

    assert data["status_readable"] is None
    assert "прочитать не удалось" in prompt
    assert "прочитать не удалось" in prompt


@pytest.mark.parametrize("available", ["yes", 1, object()])
async def test_a_non_boolean_availability_is_unknown(available: object) -> None:
    prompt = await _answer_prompt(available=available)

    assert "прочитать не удалось" in prompt


# ---------------------------------------------------------------------------
# From the real broker through the real adapter, because the mock hid the bug
# ---------------------------------------------------------------------------


async def _answer_from_real_broker(snapshot) -> str:
    """BrokerSnapshot -> real CompositeAdapter -> real router -> real dispatch.

    Every test above hands both ages to a mocked status, which is exactly why
    three separate defects in how those ages are PRODUCED survived: the mock
    could not have the bug. A reviewer demonstrated that `min` becoming `max`
    in the broker, or the adapter passing None, left all thirty tests green.
    """
    from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
    from cryodaq.agents.assistant.query.schemas import AlarmStatusResult

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=AlarmStatusResult())
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)
    adapter = CompositeAdapter(
        broker_snapshot=snapshot,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )
    adapters = QueryAdapters(
        broker_snapshot=snapshot,
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=adapter,
    )
    data = await QueryRouter(adapters).fetch(QueryIntent(category=QueryCategory.SYSTEM_HEALTH), _QUESTION)
    return object.__new__(AssistantQueryAgent)._build_format_user_prompt(_QUESTION, QueryCategory.SYSTEM_HEALTH, data)


def _reading(channel: str, value: float, *, ts_offset_s: float = 0.0):
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading

    return Reading(
        timestamp=datetime.now(UTC) + timedelta(seconds=ts_offset_s),
        instrument_id="ls218",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
    )


async def test_a_reading_stamped_in_the_future_does_not_make_the_stream_live() -> None:
    """The clock-skew defect: a future timestamp read as fresh once time caught up.

    Arrival is on the monotonic clock, so a producer's wall clock -- however
    wrong -- cannot make a stopped stream look live.
    """
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т12", 271.0, ts_offset_s=3600.0))

    prompt = await _answer_from_real_broker(snapshot)

    # It arrived just now, so flow is real; the future stamp must not have
    # turned the age negative or unknown.
    assert "последнее показание пришло: 0 c назад" in prompt


async def test_a_broker_that_has_received_nothing_does_not_claim_flow() -> None:
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    prompt = await _answer_from_real_broker(BrokerSnapshot())

    assert "этот помощник ещё ничего не получал" in prompt
    assert "кэш последних значений: пуст" in prompt


async def test_the_arrival_age_comes_from_arrival_not_from_the_timestamp() -> None:
    """Directly on the broker: a past-stamped reading has just arrived."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т12", 271.0, ts_offset_s=-3600.0))

    arrival = await snapshot.arrival_age_s()
    oldest = await snapshot.oldest_age_s()

    assert arrival is not None and arrival < 1.0, "arrival must not follow the producer's clock"
    assert oldest is not None and oldest > 3000.0, "the timestamp age must still report the stale stamp"


async def test_the_broker_reports_the_most_recent_arrival_not_the_first() -> None:
    """`max` instead of `min` upstream would restore the oldest-as-flow defect."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т1", 4.2, ts_offset_s=-3600.0))
    await snapshot._on_reading(_reading("Т12", 271.0))

    prompt = await _answer_from_real_broker(snapshot)

    assert "последнее показание пришло: 0 c назад" in prompt


async def test_unknown_counts_are_not_rendered_as_zero() -> None:
    """A zero reads as a fact; "неизвестно" is the truth when nothing is known.

    Exercised on the READABLE path, where the rendering actually happens: an
    unreadable status returns early with a hardcoded "неизвестно", so testing
    it there cannot see a defect in how counts are formatted.
    """
    prompt = await _answer_prompt(key_temperatures="не словарь", stale=False)

    assert "ключевых каналов со значением: неизвестно" in prompt
    assert "0 из 0" not in prompt


# ---------------------------------------------------------------------------
# The claim itself is bounded
# ---------------------------------------------------------------------------


async def test_the_answer_passes_no_verdict_on_the_engine() -> None:
    """Arrival establishes recent LOCAL RECEIPT, and nothing further.

    Four review rounds each found the answer claiming more than its signal could
    carry. The signal is now the best available and it still cannot tell a
    stopped engine from a broken link to a running one, so the claim is bounded
    in the prompt rather than left for the model to infer.
    """
    prompt = await _answer_prompt()

    assert "не проверка" in prompt
    assert "остановку движка и обрыв связи с работающим" in prompt
    assert "НЕ выноси вердикт" in prompt


async def test_every_arrival_updates_the_clock_not_only_the_first() -> None:
    """Recording only the first arrival would freeze the age at the first frame."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т1", 4.2))
    snapshot._newest_arrival -= 3600.0  # pretend that first frame was an hour ago
    stale = await snapshot.arrival_age_s()

    await snapshot._on_reading(_reading("Т12", 271.0))
    fresh = await snapshot.arrival_age_s()

    assert stale is not None and stale > 3000.0
    assert fresh is not None and fresh < 1.0, "a later arrival must move the clock"


async def test_an_old_arrival_is_reported_as_old() -> None:
    """A constant zero, or a clock that never advances, would read as fresh."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т12", 271.0))
    snapshot._newest_arrival -= 3600.0

    prompt = await _answer_from_real_broker(snapshot)

    assert "последнее показание пришло: 3600 c назад" in prompt


async def test_a_backwards_clock_is_unknown_rather_than_fresh() -> None:
    """Clamping a negative interval to zero would make a broken invariant
    the strongest possible evidence of freshness."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т12", 271.0))
    snapshot._newest_arrival += 3600.0  # as if the clock had jumped backwards

    assert await snapshot.arrival_age_s() is None


async def test_the_oldest_age_still_reports_the_oldest() -> None:
    """`max` becoming `min` upstream would silently rename the other question."""
    from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т1", 4.2, ts_offset_s=-3600.0))
    await snapshot._on_reading(_reading("Т12", 271.0))

    oldest = await snapshot.oldest_age_s()

    assert oldest is not None and oldest > 3000.0


@pytest.mark.parametrize("stale", [None, "нет", 0, object()])
async def test_an_unestablished_staleness_is_not_an_established_freshness(stale: object) -> None:
    """`is False` was not enough: only an explicit False means "current".

    A status whose `stale` field is missing or is not a boolean has not told us
    it is current, and rejecting only the explicit False let that unknown reach
    the age line as though the value had been read just now.
    """
    prompt = await _answer_prompt(stale=stale, snapshot_arrival_age_s=2.0)

    assert "свежесть не установлена" in prompt
    assert "последнее показание пришло: 2 c назад" not in prompt
