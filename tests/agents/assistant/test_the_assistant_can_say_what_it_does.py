"""«Что ты умеешь?» — the one question that gates every other.

An operator who does not know what can be asked asks nothing. Measured
2026-09-10 by running the real classifier over 38 realistic operator questions:
"что ты умеешь?" fell to `out_of_scope_general`, so the assistant could not
introduce itself.

The listing is built from the category enum, not written out as prose. A
hand-written feature list is wrong the first time a category is added and
nobody remembers the list -- and an assistant that describes itself wrongly is
worse than one that says nothing, because the operator stops trusting the rest
of its answers.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.prompts import INTENT_CLASSIFIER_SYSTEM
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import (
    CAPABILITY_DESCRIPTIONS,
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)

#: Categories that are deliberately NOT capabilities to advertise: a greeting,
#: a refusal, or the self-description itself. Listing them here rather than
#: filtering by a rule is the point -- a new category must be consciously put on
#: one side or the other, and the test below fails until it is.
_NOT_A_CAPABILITY = frozenset(
    {
        QueryCategory.GREETING,
        QueryCategory.UNKNOWN,
        QueryCategory.OUT_OF_SCOPE_HISTORICAL,
        QueryCategory.OUT_OF_SCOPE_GENERAL,
        QueryCategory.CAPABILITIES,
    }
)


#: Every limitation the answer must state, in the words the prompt uses. A
#: reviewer removed all of them but one and every content assertion still
#: passed, because each test checked a single string.
_LIMITATIONS = (
    "не управляет стендом",
    "не остановит",
    "не сбросит тревогу",
    "не пишет в журнал оператора",
    "ни процессы, ни занятость диска, ни",
    "логи",
)


async def _answer() -> str:
    """Through the real router and the real dispatch, not the formatter directly.

    Asserting on `_fmt_capabilities` alone left the dispatch free to hand the
    category to any other formatter. Injecting `{}` in place of the fetch left a
    router that REFUSED the category free to do so unnoticed -- the category has
    no data to fetch, which is exactly why it is easy to skip and exactly why
    the fetch has to be exercised.
    """
    adapters = QueryAdapters(
        broker_snapshot=MagicMock(),
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=MagicMock(),
    )
    data = await QueryRouter(adapters).fetch(QueryIntent(category=QueryCategory.CAPABILITIES), "что ты умеешь?")
    agent = object.__new__(AssistantQueryAgent)
    return agent._build_format_user_prompt("что ты умеешь?", QueryCategory.CAPABILITIES, data)


# ---------------------------------------------------------------------------
# The listing cannot drift from what the assistant actually does
# ---------------------------------------------------------------------------


def test_every_category_is_either_described_or_deliberately_not() -> None:
    """The guard that makes this feature maintainable rather than a snapshot.

    Adding a category without deciding whether it is worth telling the operator
    about leaves the assistant claiming a smaller repertoire than it has, and
    nothing else would notice.
    """
    described = set(CAPABILITY_DESCRIPTIONS)
    accounted = described | _NOT_A_CAPABILITY

    assert set(QueryCategory) == accounted, (
        f"undecided categories: {sorted(c.value for c in set(QueryCategory) - accounted)}"
    )
    assert not (described & _NOT_A_CAPABILITY), "a category cannot be both"


async def test_the_answer_lists_every_described_capability() -> None:
    answer = await _answer()

    for category, text in CAPABILITY_DESCRIPTIONS.items():
        assert text in answer, f"{category.value} is described but not listed"


async def test_the_answer_names_a_real_channel_the_operator_would_recognise() -> None:
    """A listing full of abstractions teaches nobody what to type."""
    assert "Т12" in await _answer()


# ---------------------------------------------------------------------------
# It must not promise what it cannot do
# ---------------------------------------------------------------------------


async def test_the_answer_is_forbidden_to_invent_capabilities() -> None:
    answer = await _answer()

    assert "Ничего НЕ добавляй" in answer
    assert "помощник этого не умеет" in answer


async def test_the_answer_states_every_one_of_its_limits() -> None:
    """Control and journal writing are real requests that fall to unknown.

    Every limitation is asserted, not a representative one: removing all but a
    single line left the earlier version of this test green.
    """
    answer = await _answer()

    for limitation in _LIMITATIONS:
        assert limitation in answer, f"the answer no longer states {limitation!r}"


async def test_the_answer_does_not_deny_reading_the_archive_and_the_corpus() -> None:
    """A blanket "sees nothing outside the bus" would be false.

    Archive details read local metadata and knowledge queries search a
    disk-backed corpus -- which this very listing advertises. The limitation is
    about inspecting the machine, not about configured sources, and stating it
    too broadly would contradict the line above it.
    """
    answer = await _answer()

    assert "Архив экспериментов и проиндексированную документацию он читает" in answer


# ---------------------------------------------------------------------------
# The category has to be reachable
# ---------------------------------------------------------------------------


def test_the_classifier_is_told_the_category_exists() -> None:
    """Two places, and the category is unreachable if either is missing."""
    assert f"→ {QueryCategory.CAPABILITIES.value}." in INTENT_CLASSIFIER_SYSTEM

    union = INTENT_CLASSIFIER_SYSTEM.split("<one of:", 1)[1].split(">", 1)[0]
    assert QueryCategory.CAPABILITIES.value in union, "the category is not in the declared JSON union"


async def test_the_listing_follows_the_map_at_runtime(monkeypatch) -> None:
    """Derivation proved by changing the map and watching the answer follow.

    A literal listing that merely mentions CAPABILITY_DESCRIPTIONS somewhere
    satisfies a source guard. This does not: the answer has to contain a
    description that did not exist when the module was imported.
    """
    import cryodaq.agents.assistant.query.agent as agent_module

    monkeypatch.setattr(
        agent_module,
        "CAPABILITY_DESCRIPTIONS",
        {QueryCategory.PHASE_INFO: "выдуманная возможность для проверки"},
    )

    answer = await _answer()

    assert "выдуманная возможность для проверки" in answer
    assert "прогноз охлаждения" not in answer


async def test_the_classifier_really_sends_the_category_to_the_model() -> None:
    """The constant containing the word proves only that the file contains it."""
    from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier
    from cryodaq.agents.assistant.shared.ollama_client import OllamaClient

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(
        return_value={
            "model": "qwen38",
            "choices": [{"message": {"content": '{"category": "capabilities"}'}, "finish_reason": "stop"}],
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

    intent = await IntentClassifier(client).classify("что ты умеешь?")

    sent = "\n".join(str(m.get("content", "")) for m in session.post.call_args[1]["json"]["messages"])
    assert f"→ {QueryCategory.CAPABILITIES.value}." in sent
    union = sent.split("<one of:", 1)[1].split(">", 1)[0]
    assert QueryCategory.CAPABILITIES.value in union
    assert intent.category is QueryCategory.CAPABILITIES


def test_the_listing_is_built_from_the_map_not_pasted_in() -> None:
    """A source guard, and it proves nothing about runtime behaviour.

    It catches the one change that would make every other test here pass while
    the feature rotted: replacing the derived listing with a literal string that
    no longer follows the categories.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(AssistantQueryAgent._fmt_capabilities)))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert "CAPABILITY_DESCRIPTIONS" in names, "the listing no longer follows the categories"


def test_no_description_promises_an_action_the_assistant_cannot_take() -> None:
    """Enum membership proves a category exists, not that its blurb is true.

    The failure this feature exists to prevent is the assistant advertising
    something it cannot do, and the enum guard cannot see that: a description
    saying «сбрось тревогу» sits perfectly happily beside a category that only
    READS alarms. The query path has no control authority at all, so any
    imperative promising to change the stand's state is wrong by construction.
    """
    forbidden = (
        "сбрось",
        "останов",
        "запиши",
        "запишу",
        "включ",
        "выключ",
        "поставь метк",
        "измени",
        "перезапус",
    )

    for category, text in CAPABILITY_DESCRIPTIONS.items():
        lowered = text.casefold()
        for verb in forbidden:
            assert verb not in lowered, f"{category.value} promises an action: {text!r}"


def test_the_health_blurb_does_not_promise_the_verdict_its_own_prompt_forbids() -> None:
    """Descriptive truth cannot be guarded in general, but this case can.

    A blurb may not promise a stronger conclusion than its category's own answer
    prompt is allowed to draw. FORMAT_SYSTEM_HEALTH_USER says in as many words
    «НЕ выноси вердикт «движок жив» или «движок мёртв»» -- it reports what this
    process received and cannot tell a stopped engine from a broken link to a
    running one. Describing that as a health check puts the overstatement back
    in through the listing, which four review rounds had just taken out of the
    category itself. It passed every other test here when a reviewer tried it.
    """
    from cryodaq.agents.assistant.query.prompts import FORMAT_SYSTEM_HEALTH_USER

    assert "НЕ выноси вердикт" in FORMAT_SYSTEM_HEALTH_USER, "the prohibition this test rests on is gone"

    blurb = CAPABILITY_DESCRIPTIONS[QueryCategory.SYSTEM_HEALTH].casefold()
    for verdict_word in ("здоров", "жив", "работает", "в порядке", "исправ"):
        assert verdict_word not in blurb, f"the blurb promises a verdict: {verdict_word!r}"
