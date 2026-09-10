"""Every shutdown step must actually run, whatever shape it has.

MEASURED on lab53, 2026-09-10, in the assistant's own log after a redeploy:

    ERROR │ cryodaq.assistant │ Optional assistant cleanup failed: RAG searcher
    TypeError: 'NoneType' object can't be awaited

The step did ``await operation()``, and ``RagSearcher.close`` is SYNCHRONOUS --
it returns None.

The precise statement, after two reviewer corrections: when execution reached
``RagSearcher.close()`` and it returned None, the step logged a TypeError AFTER
the close had already run. So the pool was shut down and the report of failure
was false. Earlier versions of this file said the pool "was never released" and
that this happened "at every stop"; neither is supported -- an earlier
cancellation or a failed periodic task can end the sequence before it gets here.

Every other target in that sequence is a coroutine function, which made the odd
one out easy to miss. Why it stayed missed is not something this file can
establish.

The helper and the whole sequence were inline in the run function until this
change, so neither could be invoked DIRECTLY -- the parent does have a runtime
shutdown test, so "no test could reach it" would be false. These call the real
ones.
"""

from __future__ import annotations

import contextlib
import inspect
import logging

import pytest

from cryodaq.agents.assistant_main import _run_cleanup_step, _run_shutdown_sequence


@contextlib.contextmanager
def caplog_at_error():
    """Collect ERROR records without a fixture, so this file's async tests can
    use the same instrument as its synchronous ones."""
    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.ERROR:
                records.append(record)

    sink = _Sink()
    root = logging.getLogger()
    root.addHandler(sink)
    try:
        yield records
    finally:
        root.removeHandler(sink)


async def test_a_synchronous_step_runs_and_is_not_awaited(caplog) -> None:
    """The exact shape that failed: a close that returns None.

    Asserting only that the function RAN is not enough, and the negative control
    proved it: with `await operation()` restored, the synchronous close still
    runs — the TypeError happens after it returns, and the step swallows it. The
    defect's whole signature is that it looks like success. What has to hold is
    that the step reports NOTHING, because nothing went wrong.
    """
    calls: list[str] = []

    def sync_close() -> None:
        calls.append("sync")

    with caplog.at_level(logging.ERROR):
        await _run_cleanup_step("probe", sync_close)

    assert calls == ["sync"]
    # EVERY error record, not only the ones saying "cleanup failed": a reviewer
    # noted that an unrelated error-level message would have slipped through the
    # narrower check while the test still claimed the step "reports nothing".
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == [], (
        "a synchronous step produced an error record"
    )


async def test_an_asynchronous_step_is_awaited_to_completion() -> None:
    """The shape every other target has; it must keep working."""
    calls: list[str] = []

    async def async_close() -> None:
        calls.append("async")

    await _run_cleanup_step("probe", async_close)

    assert calls == ["async"]


async def test_a_step_returning_a_value_does_not_break_the_sequence(caplog) -> None:
    """A close that returns something other than None or an awaitable.

    The assertion is that NOTHING is reported. Without it the test was green
    under `if result is not None: await result` -- which raises a TypeError on
    42, catches it, and returns normally, reporting a failure that did not
    happen. A reviewer found that; it is the same shape as the defect this whole
    commit is about.
    """
    with caplog.at_level(logging.ERROR):
        await _run_cleanup_step("probe", lambda: 42)

    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == [], (
        "a step that simply returned a value was reported as a failure"
    )


async def test_a_raising_step_is_logged_and_does_not_stop_the_rest(caplog) -> None:
    """Shutdown steps are optional by design: one failure must not abort the
    others, and it must not vanish either."""

    def boom() -> None:
        raise RuntimeError("нет")

    with caplog.at_level(logging.ERROR):
        await _run_cleanup_step("проба", boom)

    assert any("проба" in record.message or "проба" in record.getMessage() for record in caplog.records), (
        "the failing step was not named in the log"
    )


async def test_a_step_whose_await_raises_is_logged_too(caplog) -> None:
    """The failure can also arrive AFTER the call returns.

    An earlier version of this test asserted nothing at all, so a mutation that
    logged synchronous failures and silently swallowed await-time ones survived
    it. A reviewer found that; the assertions below are the answer.
    """

    async def boom() -> None:
        raise RuntimeError("нет")

    with caplog.at_level(logging.ERROR):
        await _run_cleanup_step("поздняя-проба", boom)

    reported = [record for record in caplog.records if "cleanup failed" in record.getMessage()]
    assert reported, "a failure raised while awaiting was swallowed without a word"
    assert "поздняя-проба" in reported[0].getMessage()
    assert reported[0].exc_info is not None, "the exception itself was not recorded"


async def test_a_synchronous_factory_returning_a_future_is_awaited() -> None:
    """Why the branch tests the RESULT and not the operation.

    ``inspect.iscoroutine(result)`` passes every other test in this file while
    dropping a Future or Task returned by a synchronous factory -- a reviewer's
    mutation. ``isawaitable`` is what covers that shape.
    """
    import asyncio

    finished: list[str] = []

    async def _work() -> None:
        finished.append("awaited")

    def factory() -> asyncio.Task[None]:
        return asyncio.ensure_future(_work())

    await _run_cleanup_step("проба", factory)

    assert finished == ["awaited"], "a returned Task was never awaited to completion"


def test_rag_searcher_close_is_synchronous_and_that_is_the_point() -> None:
    """If this ever becomes a coroutine, the branch above stops covering
    anything, and the reason for it must not quietly evaporate."""
    from cryodaq.agents.rag.searcher import RagSearcher

    assert not inspect.iscoroutinefunction(RagSearcher.close), (
        "RagSearcher.close became a coroutine — revisit whether the step still needs its branch"
    )


#: EVERY target the shutdown sequence names, not a sample of them: a reviewer
#: pointed out that four of twelve was being described as "every".
_SHUTDOWN_TARGETS = [
    ("cryodaq.agents.assistant.query.agent", "AssistantQueryAgent", "close"),
    ("cryodaq.agents.assistant.live.agent", "AssistantLiveAgent", "stop"),
    ("cryodaq.agents.assistant.live.output_router", "OutputRouter", "close"),
    ("cryodaq.agents.assistant.shared.audit", "AuditLogger", "close"),
    ("cryodaq.core.zmq_bridge", "ZMQCommandServer", "stop"),
    ("cryodaq.core.zmq_bridge", "ZMQEventSubscriber", "stop"),
    ("cryodaq.agents.assistant.query.adapters.broker_snapshot", "BrokerSnapshot", "stop"),
    ("cryodaq.agents.assistant.shared.ollama_client", "OllamaClient", "close"),
    ("cryodaq.agents.rag.searcher", "RagSearcher", "close"),
    ("cryodaq.agents.rag.embeddings", "EmbeddingsClient", "close"),
    ("cryodaq.agents.assistant_main", "_RemoteEngineStateCache", "stop"),
    ("cryodaq.agents.assistant_main", "TelegramSender", "close"),
]


@pytest.mark.parametrize(("module_name", "class_name", "method_name"), _SHUTDOWN_TARGETS)
def test_every_named_shutdown_target_takes_no_arguments(module_name: str, class_name: str, method_name: str) -> None:
    """The step calls ``operation()`` with nothing.

    A target that grew a required argument would fail at CALL time -- loudly,
    not in the RAG one's quiet way -- but it would still stop that component
    from being closed, so the shape is pinned for every target the sequence
    names.
    """
    import importlib

    target = getattr(getattr(importlib.import_module(module_name), class_name), method_name)
    parameters = inspect.signature(target).parameters
    required = [
        name
        for name, parameter in parameters.items()
        if name != "self"
        and parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]

    assert required == [], f"{class_name}.{method_name} needs {required}, and the shutdown sequence passes nothing"


# ---------------------------------------------------------------------------
# The production sequence, not just the step it calls
# ---------------------------------------------------------------------------


class _SyncCloser:
    """A component whose close is SYNCHRONOUS, like the RAG searcher's."""

    def __init__(self, name: str, calls: list[str]) -> None:
        self._name = name
        self._calls = calls

    def close(self) -> None:
        self._calls.append(self._name)


class _AsyncCloser:
    def __init__(self, name: str, calls: list[str], method: str = "close") -> None:
        self._name = name
        self._calls = calls
        setattr(self, method, self._record)

    async def _record(self) -> None:
        self._calls.append(self._name)


async def test_the_production_sequence_survives_a_synchronous_close(caplog) -> None:
    """Reverting the RAG line here would restore the false error.

    A reviewer showed that every test in this file passed while the production
    sequence still did `await rag_searcher.close()`, because they all reached
    only the step helper. The sequence is module-level now, so this drives the
    same code the process runs.
    """
    calls: list[str] = []

    with caplog.at_level(logging.ERROR):
        await _run_shutdown_sequence(
            periodic_task=None,
            query_agent=_AsyncCloser("query", calls),
            live_agent=_AsyncCloser("live", calls, method="stop"),
            output_router=_AsyncCloser("router", calls),
            audit_logger=_AsyncCloser("audit", calls),
            cmd_server=None,
            event_sub=None,
            state_cache=None,
            broker_snapshot=None,
            ollama=_AsyncCloser("ollama", calls),
            rag_searcher=_SyncCloser("rag", calls),
            rag_emb_client=_AsyncCloser("embeddings", calls),
            telegram_sender=_AsyncCloser("telegram", calls),
        )

    assert "rag" in calls, "the synchronous close never ran"
    # And the steps AFTER it still ran: a failure there used to be swallowed,
    # which is exactly what made the defect invisible.
    assert calls[calls.index("rag") :] == ["rag", "embeddings", "telegram"]
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == [], (
        "the production sequence reported a failure that did not happen"
    )


async def test_a_component_that_never_started_is_skipped() -> None:
    """None means "never started" — the flags the call site used to carry."""
    calls: list[str] = []

    await _run_shutdown_sequence(
        periodic_task=None,
        query_agent=None,
        live_agent=_AsyncCloser("live", calls, method="stop"),
        output_router=_AsyncCloser("router", calls),
        audit_logger=_AsyncCloser("audit", calls),
        cmd_server=None,
        event_sub=None,
        state_cache=None,
        broker_snapshot=None,
        ollama=_AsyncCloser("ollama", calls),
        rag_searcher=None,
        rag_emb_client=None,
        telegram_sender=None,
    )

    assert calls == ["live", "router", "audit", "ollama"]


async def test_one_failing_step_does_not_stop_the_rest(caplog) -> None:
    """Shutdown steps are optional by design."""
    calls: list[str] = []

    class _Broken:
        async def close(self) -> None:
            raise RuntimeError("нет")

    with caplog.at_level(logging.ERROR):
        await _run_shutdown_sequence(
            periodic_task=None,
            query_agent=None,
            live_agent=_AsyncCloser("live", calls, method="stop"),
            output_router=_Broken(),
            audit_logger=_AsyncCloser("audit", calls),
            cmd_server=None,
            event_sub=None,
            state_cache=None,
            broker_snapshot=None,
            ollama=_AsyncCloser("ollama", calls),
            rag_searcher=_SyncCloser("rag", calls),
            rag_emb_client=None,
            telegram_sender=None,
        )

    assert calls == ["live", "audit", "ollama", "rag"]
    assert any("output router" in record.getMessage() for record in caplog.records)


async def test_the_whole_sequence_runs_in_order_when_everything_is_present() -> None:
    """Every step, with nothing passed as None.

    A reviewer got two mutations past the earlier cases -- deleting the
    command-server stop, and inverting the state-cache flag -- because those
    cases supplied None for exactly those components, so their absence was
    indistinguishable from their removal. This one supplies all of them and
    pins the complete ordered list.
    """
    calls: list[str] = []

    await _run_shutdown_sequence(
        periodic_task=None,
        query_agent=_AsyncCloser("query", calls),
        live_agent=_AsyncCloser("live", calls, method="stop"),
        output_router=_AsyncCloser("router", calls),
        audit_logger=_AsyncCloser("audit", calls),
        cmd_server=_AsyncCloser("command", calls, method="stop"),
        event_sub=_AsyncCloser("events", calls, method="stop"),
        state_cache=_AsyncCloser("state", calls, method="stop"),
        broker_snapshot=_AsyncCloser("broker", calls, method="stop"),
        ollama=_AsyncCloser("ollama", calls),
        rag_searcher=_SyncCloser("rag", calls),
        rag_emb_client=_AsyncCloser("embeddings", calls),
        telegram_sender=_AsyncCloser("telegram", calls),
    )

    assert calls == [
        "query",
        "live",
        "router",
        "audit",
        "command",
        "events",
        "state",
        "broker",
        "ollama",
        "rag",
        "embeddings",
        "telegram",
    ]


async def test_the_periodic_task_is_cancelled_before_anything_is_closed() -> None:
    """The first step of the sequence, and the only one that is not a cleanup.

    The sleep is SHORT on purpose. An earlier version parked the task on
    `asyncio.sleep(3600)`, so when the step failed to cancel it the test did not
    fail -- it hung for the full ten-minute timeout, and the negative control
    refused to run at all because its baseline was red. A test whose failure
    mode is a hang is worse than no test.
    """
    import asyncio

    order: list[str] = []

    async def _parked() -> None:
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            order.append("periodic-cancelled")
            raise
        order.append("periodic-finished-on-its-own")

    task = asyncio.ensure_future(_parked())
    await asyncio.sleep(0)

    await _run_shutdown_sequence(
        periodic_task=task,
        query_agent=None,
        live_agent=_AsyncCloser("live", order, method="stop"),
        output_router=_AsyncCloser("router", order),
        audit_logger=_AsyncCloser("audit", order),
        cmd_server=None,
        event_sub=None,
        state_cache=None,
        broker_snapshot=None,
        ollama=_AsyncCloser("ollama", order),
        rag_searcher=None,
        rag_emb_client=None,
        telegram_sender=None,
    )

    assert order[0] == "periodic-cancelled", f"the periodic task was not cancelled first: {order}"
    assert order[1:] == ["live", "router", "audit", "ollama"]


# ---------------------------------------------------------------------------
# The WIRING into the sequence, not only the sequence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query_enabled", [False, True], ids=["query-off", "query-on"])
async def test_the_runtime_hands_its_real_searcher_to_the_shutdown(monkeypatch, tmp_path, query_enabled) -> None:
    """`rag_searcher=rag_searcher` at the call site, not `None`.

    A reviewer mutated exactly that argument and every test still passed: they
    all drive `_run_shutdown_sequence` directly, and the two existing tests that
    drive `_run_llm_runtime` configure RAG as absent. So "the production path
    and the tested path are the same path" was true of the sequence and not of
    the wiring into it. This crosses the wiring.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import cryodaq.agents.assistant_main as assistant_main
    import cryodaq.agents.rag.embeddings as rag_embeddings
    import cryodaq.agents.rag.searcher as rag_searcher_module
    from cryodaq.agents.assistant.live.agent import AssistantConfig

    closed: list[str] = []

    class _SearcherWithSyncClose:
        def __init__(self, **_kwargs) -> None:
            pass

        def close(self) -> None:  # SYNCHRONOUS, like the real one
            closed.append("searcher")

    class _StartStop:
        def __init__(self, *_args, **_kwargs) -> None:
            self.start = AsyncMock()
            self.stop = AsyncMock()

    config = AssistantConfig(
        enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        query_enabled=query_enabled,
        periodic_report_enabled=False,
    )
    monkeypatch.setattr(assistant_main.AssistantConfig, "from_yaml_path", classmethod(lambda _cls, _path: config))

    state = _StartStop()
    state.active_experiment_id = None
    state.get_summary = MagicMock(return_value=None)

    def _named(name: str, method: str):
        """A stand-in that records its own shutdown under a name."""

        async def _record() -> None:
            closed.append(name)

        # `start` is an AsyncMock on every owner: the runtime awaits it before it
        # ever reaches shutdown.
        return MagicMock(start=AsyncMock(), **{method: _record})

    ollama = _named("ollama", "close")
    audit = _named("audit", "close")
    router = _named("router", "close")
    telegram = _named("telegram", "close")
    live = _named("live", "stop")
    events = _named("events", "stop")
    command = _named("command", "stop")

    async def _state_stop() -> None:
        closed.append("state")

    state.stop = _state_stop

    monkeypatch.setattr(assistant_main, "EngineQueryClient", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(assistant_main, "OllamaClient", lambda *_a, **_k: ollama)
    monkeypatch.setattr(assistant_main, "EngineContextReader", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(assistant_main, "ContextBuilder", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(assistant_main, "AuditLogger", lambda *_a, **_k: audit)
    monkeypatch.setattr(assistant_main, "OutputRouter", lambda **_k: router)
    monkeypatch.setattr(assistant_main, "AssistantLiveAgent", lambda **_k: live)
    monkeypatch.setattr(assistant_main, "_RemoteEngineStateCache", lambda *_a, **_k: state)
    monkeypatch.setattr(assistant_main, "_load_telegram_sender", lambda: telegram)
    monkeypatch.setattr(assistant_main, "ZMQEventSubscriber", lambda *_a, **_k: events)
    monkeypatch.setattr(assistant_main, "ZMQCommandServer", lambda **_k: command)

    # THE QUERY-ENABLED HALF. A reviewer found that running only with
    # `query_enabled=False` left two owners of the same call site unbuilt, so
    # `broker_snapshot=None` there was invisible while the comment above the
    # assertion claimed every owner was pinned. The broker keeps a ZMQ
    # subscriber task and socket; leaving it running through shutdown is the
    # cost. `ChannelManager` is stubbed because the construction below sits in a
    # try/except that SWALLOWS failures -- an unstubbed one would silently
    # produce `query_agent = None` and a test that proves nothing. The ordered
    # list is what makes that impossible to miss.
    if query_enabled:
        monkeypatch.setattr(assistant_main, "ChannelManager", lambda *_a, **_k: MagicMock())
        monkeypatch.setattr(assistant_main, "BrokerSnapshot", lambda *_a, **_k: _named("broker", "stop"))
        monkeypatch.setattr(assistant_main, "AssistantQueryAgent", lambda *_a, **_k: _named("query", "close"))

    # RAG PRESENT, which is the whole point.
    monkeypatch.setattr(
        assistant_main,
        "_resolve_rag_config",
        lambda: {"db_path": str(tmp_path), "table_name": "t", "_source": "probe"},
    )
    monkeypatch.setattr(rag_searcher_module, "RagSearcher", _SearcherWithSyncClose)
    monkeypatch.setattr(rag_embeddings, "make_embeddings_client", lambda _cfg: _named("embeddings", "close"))

    async def _parked_tick(*_args, **_kwargs) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(assistant_main, "_periodic_report_tick", _parked_tick)

    shutdown = asyncio.Event()
    shutdown.set()

    with caplog_at_error() as records:
        await assistant_main._run_llm_runtime(
            engine_cmd_addr="tcp://127.0.0.1:1",
            engine_pub_addr="tcp://127.0.0.1:2",
            assistant_cmd_addr="tcp://127.0.0.1:3",
            shutdown_event=shutdown,
        )

    # EVERY owner the call site maps, in order. Pinning two of them left
    # `cmd_server=None` -- and six more like it -- invisible: a reviewer found
    # that the helper-level ordered test cannot see the call site's mapping, and
    # no repository test driving the runtime asserted those stops. A second
    # reviewer found that "every" was still false while this ran in one
    # configuration only, which is why it now runs in both.
    assert closed == ([] if not query_enabled else ["query"]) + [
        "live",
        "router",
        "audit",
        "command",
        "events",
        "state",
        *([] if not query_enabled else ["broker"]),
        "ollama",
        "searcher",
        "embeddings",
        "telegram",
    ], f"the runtime's shutdown order or its wiring changed: {closed}"
    assert [r for r in records if "cleanup failed" in r.getMessage()] == [], (
        "the synchronous close was reported as a failure"
    )
