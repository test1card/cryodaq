"""The hourly bulletin must have room to finish its answer.

Reported by the operator on 2026-09-12: the summary was not arriving. It had not
been arriving since 2026-09-11, the day the stand moved to vLLM and `qwen38`, and
nothing told anyone — the only trace was a WARNING per hour in the assistant log.

THE CAUSE, read out of the audit ledger rather than guessed: every report from
11.09 onward recorded `tokens.out` of exactly 2048 — the whole budget — with an
EMPTY response. The model spent the allowance on reasoning and never reached the
answer, so the report was marked truncated and dispatched nowhere. Twenty-nine
reports over two days, all silent. 2048 was sized for `gemma4:e4b` on Ollama, and
the comment beside it said as much.

Measured on 2026-09-12 against the real prompt from the ledger (4,041 prompt
tokens), on the live endpoint:

    max_tokens=2048     finish=length, out=2048, NO answer      41.6 s
    max_tokens=8192     finish=stop,   out=4763, 660 chars      93.2 s
    max_tokens=100000   finish=stop,   out=2868, 612 chars      56.9 s

AND THE KEY WAS NOT READABLE. `AssistantConfig.from_dict` read every other bound
in the `ollama` section and not this one, so `max_tokens:` in agent.yaml did
nothing at all. A fix applied to the config alone would have left the bulletin
exactly as empty, which is why one of these tests reads the tracked file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine

#: What the measurement above says one bulletin can need. A configuration that
#: allows less than this is one the stand has already been observed to defeat.
_MEASURED_NEED = 4763

#: Sentinels for the call-site tests, ABOVE the deployed 8192 on purpose. A
#: reviewer showed why: with a sentinel below it, `min(self._config.max_tokens,
#: 8192)` silently caps every shared answer and every test stays green. Above it,
#: any cap or clamp shows up as a different number.
_SHARED_SENTINEL = 123_457
_BULLETIN_SENTINEL = 31_337


def _deployed_config(*, substitute_budgets: bool = True, **overrides: Any) -> AssistantConfig:
    """The configuration this stand actually runs, with only the budgets swapped.

    BUILT FROM THE TRACKED FILE, not from dataclass defaults, because a reviewer
    showed what the gap permits. The defaults are `api=ollama`, `gemma4:e4b`,
    `slice_b_suggestion=False`; the deployment is `openai`, `qwen38`,
    `slice_b_suggestion=True`. A production line reading

        generate = self._ollama.generate if self._config.default_model == "qwen38" else self._generate_tracked

    therefore took the boundary in every test and bypassed it on the stand,
    carrying the right budget and skipping the recovery signal. A test that asserts
    about a configuration nobody runs is a test about nothing.
    """

    config = AssistantConfig.from_yaml_path(Path("config/agent.yaml"))
    if substitute_budgets:
        config.max_tokens = _SHARED_SENTINEL
        config.periodic_report_max_tokens = _BULLETIN_SENTINEL
    config.output_telegram = False
    config.output_operator_log = True
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _rollback_config(*, substitute_budgets: bool = True, **overrides: Any) -> AssistantConfig:
    """The Ollama rollback the config documents, so the guard covers it too.

    agent.yaml carries a commented rollback to :11437 / qwen3.8:27b / api ollama,
    and a switch that is documented but never exercised is a switch that does not
    work -- the same reasoning a test in this repository already applies to that
    very block.
    """

    return _deployed_config(
        substitute_budgets=substitute_budgets,
        llm_api="ollama",
        default_model="qwen3.8:27b",
        ollama_base_url="http://100.87.73.25:11437",
        **overrides,
    )


def test_the_token_budget_is_readable_from_the_configuration_file() -> None:
    """Every other bound in that section is configurable; this one was not."""
    config = AssistantConfig.from_yaml_string(
        "agent:\n  ollama:\n    max_tokens: 12345\n    periodic_report_max_tokens: 54321\n"
    )

    assert config.max_tokens == 12345, "max_tokens in agent.yaml is ignored"
    assert config.periodic_report_max_tokens == 54321, "periodic_report_max_tokens in agent.yaml is ignored"


def test_the_tracked_configuration_leaves_room_for_a_whole_answer() -> None:
    """The file this stand actually runs on, not a fixture.

    A budget documented in a comment and never set is a budget that does not
    apply; the same reasoning the rollback note in this file already carries.
    """
    config = AssistantConfig.from_yaml_path(Path("config/agent.yaml"))

    assert config.periodic_report_max_tokens > _MEASURED_NEED, (
        f"the tracked bulletin budget is {config.periodic_report_max_tokens} tokens; "
        f"one measured bulletin needed {_MEASURED_NEED}"
    )


def test_the_tracked_configuration_carries_the_budget_the_operator_chose() -> None:
    """The number itself, not just "enough".

    The test above only requires more than one measured bulletin, so it stays
    green at 8192 -- and a reviewer noted that this loses the operator's actual
    decision of 2026-09-12, which was additional headroom for a generation that
    terminates on its own. A value chosen for a reason is a value worth pinning;
    changing it should mean changing this line and reading why.
    """
    config = AssistantConfig.from_yaml_path(Path("config/agent.yaml"))

    assert config.periodic_report_max_tokens == 100_000, (
        f"the tracked bulletin budget is {config.periodic_report_max_tokens}; the operator chose 100000 on 2026-09-12"
    )


async def test_the_periodic_report_asks_for_the_budget_it_was_configured_with(tmp_path: Path) -> None:
    """The call site, not the config object.

    Reading the value into a dataclass proves nothing about the request that
    reaches the server: the defect lived in what `_handle_periodic_report` passed
    to `generate`, and a test that stopped at the config would have stayed green
    through the whole outage.
    """
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(text="сводка", tokens_in=4041, tokens_out=2868, latency_s=57.0, model="qwen38")
    )
    ollama.close = AsyncMock()

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    reader.read_readings_history = AsyncMock(return_value={"Т12": [[0.0, 298.6], [3600.0, 298.7]]})
    builder = ContextBuilder(reader, None, sensor_diag_provider=SensorDiagnosticsEngine().get_summary)
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(return_value=SimpleNamespace(active=[]))

    bus = EventBus()
    # A SENTINEL, NOT THE DEPLOYED VALUE. Configuring exactly 100000 would keep
    # this test green against a call site that hardcodes 100000 -- a reviewer
    # pointed that out, and it is the same false-green shape as testing the
    # config object instead of the call. 31337 is a number no production line
    # would plausibly carry.
    config = AssistantConfig(
        max_tokens=_SHARED_SENTINEL,
        periodic_report_max_tokens=_BULLETIN_SENTINEL,
        output_telegram=False,
        output_operator_log=True,
    )
    agent = AssistantLiveAgent(
        config=config,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=builder,
        audit_logger=AuditLogger(tmp_path / "audit", enabled=True),
        output_router=OutputRouter(telegram_bot=None, event_bus=bus),
    )

    await agent._handle_periodic_report(
        EngineEvent(
            event_type="periodic_report_request",
            timestamp=datetime.now(UTC),
            payload={"window_minutes": 60, "trigger": "scheduled"},
        )
    )

    ollama.generate.assert_awaited()
    asked = ollama.generate.await_args.kwargs.get("max_tokens")
    assert asked == _BULLETIN_SENTINEL, f"the bulletin asked the server for {asked}, not {_BULLETIN_SENTINEL}"


def test_alarm_narration_is_not_left_on_the_budget_that_silenced_the_bulletin() -> None:
    """The part that matters more than the bulletin.

    The same `max_tokens` feeds alarm narration, and measured on 2026-09-12
    against the real alarm-summary prompt (a CRITICAL Т12 overtemperature) the old
    2048 produced `finish=length`, 2048 tokens out and NO answer -- while 8192
    answered in 688 characters. No alarm has fired since the model changed on
    11.09, which is the only reason the audit ledger does not show it: had one
    fired, the operator would have been told nothing about it.

    PINNED EXACTLY, not as a range. A reviewer pointed out that "at least 8192"
    accepts 99,999 as well, which would hand alarm narration the bulletin's
    ceiling and with it the bulletin's share of the two inference permits -- the
    very thing the split exists to prevent.
    """
    config = AssistantConfig.from_yaml_path(Path("config/agent.yaml"))

    assert config.max_tokens == 8192, (
        f"shared answers get {config.max_tokens} tokens; 2048 was measured to return an EMPTY alarm summary, "
        "and anything larger hands alarm narration the bulletin's latency"
    )
    assert config.max_tokens < config.periodic_report_max_tokens, (
        "the shared budget is no smaller than the bulletin's, so the split buys nothing"
    )


async def test_the_alarm_narration_asks_for_the_shared_budget(tmp_path: Path) -> None:
    """And the alarm CALL SITE, because the config alone proved nothing.

    A reviewer showed the previous version of this file stayed green with
    `max_tokens=2048` written back into `_handle_alarm_fired` -- every test
    inspected configuration, and the defect lived in what the handler passed. The
    two sentinels differ so that neither a hardcode nor a mix-up with the
    bulletin's budget can pass.
    """
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(text="тревога", tokens_in=200, tokens_out=300, latency_s=55.0, model="qwen38")
    )
    ollama.close = AsyncMock()

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    reader.read_readings_history = AsyncMock(return_value={"Т12": [[0.0, 271.0], [3600.0, 271.4]]})
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="preparation")
    em.get_phase_history = MagicMock(return_value=[])
    builder = ContextBuilder(reader, em, sensor_diag_provider=SensorDiagnosticsEngine().get_summary)
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(return_value=SimpleNamespace(active=[]))

    bus = EventBus()
    config = AssistantConfig(
        max_tokens=_SHARED_SENTINEL,
        periodic_report_max_tokens=_BULLETIN_SENTINEL,
        output_telegram=False,
        output_operator_log=True,
        slice_b_suggestion=False,
    )
    agent = AssistantLiveAgent(
        config=config,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=builder,
        audit_logger=AuditLogger(tmp_path / "audit", enabled=True),
        output_router=OutputRouter(telegram_bot=None, event_bus=bus),
    )

    await agent._handle_alarm_fired(
        EngineEvent(
            event_type="alarm_fired",
            timestamp=datetime.now(UTC),
            payload={
                "alarm_id": "T12_OVERTEMP",
                "level": "CRITICAL",
                "channels": ["Т12"],
                "values": {"Т12": 271.4},
                "message": "выше порога",
            },
            experiment_id="exp-001",
        )
    )

    ollama.generate.assert_awaited()
    asked = ollama.generate.await_args.kwargs.get("max_tokens")
    assert asked == _SHARED_SENTINEL, f"alarm narration asked the server for {asked}, not {_SHARED_SENTINEL}"


@pytest.mark.parametrize("budgets", ["exact", "sentinel"])
@pytest.mark.parametrize("deployment", ["tracked", "rollback"])
@pytest.mark.parametrize(
    "handler",
    [
        "_handle_alarm_fired",
        "_generate_diagnostic_suggestion",
        "_handle_experiment_finalize",
        "_handle_sensor_anomaly",
        "_handle_shift_handover",
        "_handle_periodic_report",
    ],
)
async def test_every_generating_path_goes_through_the_boundary(
    tmp_path: Path, handler: str, deployment: str, budgets: str
) -> None:
    """Every path that shares the budget, observed at the server rather than in source.

    A reviewer defeated three successive source-shape guards over this property and
    then named the repair: behavioural sentinel coverage for each path. A spelling
    cannot hide from this -- whatever syntax the handler uses, the request either
    carries the shared sentinel or it does not.

    The two sentinels differ so that a hardcode, a mix-up with the bulletin's
    budget, and a fall back to the client's own default are three distinct failures.
    """
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(text="ответ", tokens_in=100, tokens_out=200, latency_s=30.0, model="qwen38")
    )
    ollama.close = AsyncMock()

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    reader.read_readings_history = AsyncMock(return_value={"Т12": [[0.0, 271.0], [3600.0, 271.4]]})
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="preparation")
    em.get_phase_history = MagicMock(return_value=[])
    builder = ContextBuilder(reader, em, sensor_diag_provider=SensorDiagnosticsEngine().get_summary)
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(return_value=SimpleNamespace(active=[]))

    bus = EventBus()
    # TWO BUDGET SHAPES, and the reason is a mutation a reviewer wrote after the
    # deployment dimension was added: `self._ollama.generate if
    # self._config.max_tokens == 8192 else self._generate_tracked`. With sentinels
    # substituted, every test took the boundary and the stand bypassed it -- the
    # same false green as building from dataclass defaults, one level in. The exact
    # variant catches a bypass that keys on the configured VALUE; the sentinel
    # variant catches a hardcode, a swap between the two budgets, and a silent clamp.
    build = _deployed_config if deployment == "tracked" else _rollback_config
    config = build(
        substitute_budgets=budgets == "sentinel",
        sensor_anomaly_critical_enabled=True,
        experiment_finalize_enabled=True,
        shift_handover_request_enabled=True,
    )
    agent = AssistantLiveAgent(
        config=config,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=builder,
        audit_logger=AuditLogger(tmp_path / "audit", enabled=True),
        output_router=OutputRouter(telegram_bot=None, event_bus=bus),
    )

    alarm_payload = {
        "alarm_id": "T12_OVERTEMP",
        "level": "CRITICAL",
        "channels": ["Т12"],
        "values": {"Т12": 271.4},
        "message": "выше порога",
    }
    event = EngineEvent(
        event_type="alarm_fired", timestamp=datetime.now(UTC), payload=alarm_payload, experiment_id="exp-001"
    )

    # THE BOUNDARY IS SPIED, NOT THE CLIENT, and the client is asserted UNTOUCHED.
    # That pair is what makes the property unspellable-around: a fourth bypass
    # reached the client as `getattr(self, "_ollama").generate(...)`, carrying the
    # right budget, and every source scan and every client-side assertion I had
    # stayed green -- while `_note_model_available` was silently skipped, which is
    # the recovery signal the boundary exists for.
    asked: list[Any] = []
    real_boundary = agent._generate_tracked

    async def _spy(*args: Any, max_tokens: int, **kwargs: Any) -> Any:
        # A WRAPPER, not a replacement, and a reviewer showed why it has to be.
        # Replacing the boundary meant a mutation INSIDE it --
        # `max_tokens=(2048 if self._config.llm_api == "openai" else max_tokens)` --
        # passed all thirty-one cases while forwarding 2,048 for a bulletin
        # configured for 100,000. Running the real boundary and then reading what
        # the CLIENT received closes that: the handler's argument and the server's
        # argument are checked separately, and they are different things.
        asked.append(max_tokens)
        return await real_boundary(*args, max_tokens=max_tokens, **kwargs)

    agent._generate_tracked = _spy  # type: ignore[method-assign]

    if handler == "_generate_diagnostic_suggestion":
        await agent._generate_diagnostic_suggestion(event, alarm_payload)
    elif handler == "_handle_periodic_report":
        await agent._handle_periodic_report(
            EngineEvent(
                event_type="periodic_report_request",
                timestamp=datetime.now(UTC),
                payload={"window_minutes": 60, "trigger": "scheduled"},
            )
        )
    else:
        await getattr(agent, handler)(event)

    # THE BULLETIN IS IN THIS SET TOO. It was covered only by a test that watched
    # the client, so replacing its own call with a direct one passed -- a reviewer
    # found it after the other five were closed. Its budget is the OTHER one.
    expected = config.periodic_report_max_tokens if handler == "_handle_periodic_report" else config.max_tokens
    assert asked, f"{handler} did not generate through the tracked boundary at all"
    assert all(value == expected for value in asked), f"{handler} asked for {asked}, not {expected}"
    # AND WHAT THE CLIENT RECEIVED, which is not the same question. The boundary now
    # really runs, so the budget can still be altered inside it.
    ollama.generate.assert_awaited()
    delivered = [call.kwargs.get("max_tokens") for call in ollama.generate.await_args_list]
    assert all(value == expected for value in delivered), (
        f"{handler} passed {expected} to the boundary and the server received {delivered}"
    )


async def test_the_tracked_boundary_refuses_a_generation_with_no_budget(tmp_path: Path) -> None:
    """The keyword has no default, and that is the property, not the signature.

    Giving it one back is harmless on its own -- every call site still passes a
    value -- and harmless only until a call ALSO omits the keyword in a spelling no
    source scan recognises. This is the half that can be pinned behaviourally:
    without a budget the call does not reach the server at all.

    (Deleted once by accident while the guard above it was being rewritten, and the
    negative control caught its absence in the next run. That is what the control is
    for.)
    """
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(text="x", tokens_in=1, tokens_out=1, latency_s=0.1, model="qwen38")
    )
    ollama.close = AsyncMock()
    bus = EventBus()
    agent = AssistantLiveAgent(
        config=AssistantConfig(output_telegram=False),
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ContextBuilder(MagicMock(), None),
        audit_logger=AuditLogger(tmp_path / "audit", enabled=True),
        output_router=OutputRouter(telegram_bot=None, event_bus=bus),
    )

    with pytest.raises(TypeError, match="max_tokens"):
        await agent._generate_tracked(system_prompt="", user_prompt="x", model="qwen38")

    ollama.generate.assert_not_awaited()
