Let me carefully analyze the diff provided, focusing on the specific areas outlined in the audit scope. I need to look for issues that the Codex self-audit missed.

Let me go through each file systematically.

### 1. Engine integration — `_periodic_report_tick`

Looking at the `_periodic_report_tick` function:

```python
async def _periodic_report_tick(
    agent_config: AssistantConfig,
    event_bus: EventBus,
    experiment_manager: ExperimentManager,
    *,
    sleep=asyncio.sleep,
) -> None:
    interval_s = float(agent_config.get_periodic_report_interval_s())
    if interval_s <= 0:
        logger.info("Periodic assistant reports disabled (interval=0)")
        return

    window_minutes = int(agent_config.periodic_report_interval_minutes)
    while True:
        await sleep(interval_s)
```

Wait, I need to see the full function. The diff is truncated. Let me work with what I can see.

The function sleeps first, then publishes. That means the first report comes after `interval_s` seconds, not immediately at startup. That's probably intentional (you don't want a report at t=0).

But wait - there's no try/except around the loop body. If `event_bus.publish` raises, the entire coroutine crashes. Let me check if there's exception handling...

The diff is truncated so I can't see the full function. But from the audit scope question "Could it crash the engine?" - if there's no try/except in the while loop, an exception in publish would kill the tick coroutine, meaning no more periodic reports until restart.

Actually, looking more carefully at the truncated diff, I see:
```
+async def _periodic_report_tick(
+    agent_config: AssistantConfig,
+    event_bus: EventBus,
+    experiment_manager: ExperimentManager,
+    *,
+    sleep=asyncio.sleep,
+) -> None:
+    """Publish periodic_report_request events on the assistant schedule."""
+    interval_s = float(agent_config.get_periodic_report_interval_s())
+    if interval_s <= 0:
+        logger.info("Periodic assistant reports disabled (interval=0)")
+        return
+
+    window_minutes = int(agent_config.periodic_report_interval_minutes)
+    while True:
+        await sleep(interval_s)
```

And then it's truncated. I can't see the rest of the function body. But the audit scope asks about exception handling, so this is worth noting if there's no try/except.

Wait, I need to be careful - the diff says "189 +++" for engine.py but only shows partial content. Let me focus on what I can actually see and verify.

### 2. EventBus contract — window_minutes type

```python
window_minutes = int(agent_config.periodic_report_interval_minutes)
```

This is cast to `int`. But what if the YAML config has a float like `interval_minutes: 90.5`? The `int()` truncation would make it 90, silently losing the fractional part. The `periodic_report_interval_minutes` field is typed as `int` in `AssistantConfig`, but YAML parsing could produce a float.

Actually, looking at `from_dict`:
```python
cfg.periodic_report_interval_minutes = ???
```

The `from_dict` method is truncated (701 lines truncated in agent.py). I can't verify if it validates the type. But the YAML has `interval_minutes: 60` which is an integer. If someone puts `60.5`, YAML would parse it as float, and `int()` would silently truncate.

This is a minor concern though.

### 3. Skip-if-idle correctness

Looking at the config:
```yaml
periodic_report:
  enabled: true
  interval_minutes: 60
  skip_if_idle: true
  min_events_for_dispatch: 1
```

And in AssistantConfig:
```python
periodic_report_min_events: int = 1
```

The question is: what counts as an "event"? If `min_events_for_dispatch: 1` and `skip_if_idle: true`, then even a single event triggers a report. But what counts toward `total_event_count`? I need to see the context builder code.

Looking at the context builder, I see `PeriodicReportContext` is mentioned but the code is truncated. I can't fully verify this.

### 4. Rate limiter interaction

The config shows:
```yaml
rate_limit:
  max_calls_per_hour: 60
  max_concurrent_inferences: 2
```

Periodic reports share this bucket. If the engine is in a busy state with many alarms, the periodic report could be rate-limited. But more critically, if a periodic report inference takes a long time (up to 60s timeout), it could consume one of the 2 concurrent inference slots, blocking alarm processing.

This is a design concern but may be intentional.

### 5. Russian prompt grounding

Looking at PERIODIC_REPORT_USER (truncated in the diff), I need to check if it passes real data. The prompt templates I can see (ALARM_SUMMARY_USER, etc.) use `{variable}` placeholders. If PERIODIC_REPORT_USER has sections with placeholder text that could be empty strings, the LLM might hallucinate content for those sections.

### 6. Output dispatch path

Looking at `OutputRouter.dispatch`:
```python
if target == OutputTarget.GUI_INSIGHT:
    ...
    await self._event_bus.publish(
        _EngineEvent(
            event_type="assistant_insight",
            timestamp=datetime.now(UTC),
            payload={
                "text": llm_output,  # Note: NOT prefixed
                "trigger_event_type": trigger_event.event_type,
                "audit_id": audit_id,
            },
            ...
        )
    )
```

Wait - for GUI_INSIGHT, the `text` field uses `llm_output` (without prefix), while for TELEGRAM and OPERATOR_LOG, it uses `prefixed`. This is actually probably intentional (GUI panel might add its own prefix), but it's worth noting.

Actually, looking more carefully:
- TELEGRAM: sends `prefixed` (with brand prefix)
- OPERATOR_LOG: sends `prefixed` (with brand prefix)  
- GUI_INSIGHT: sends `llm_output` (raw, without prefix)

This inconsistency might be intentional (GUI has its own header), but the `prefix_suffix` is only applied to the Telegram and log outputs, not to the GUI insight panel. The GUI panel doesn't get the "(отчёт за час)" suffix. This could be a minor issue.

### 7. Test coverage gaps

The audit scope lists specific scenarios to check. Without seeing the full test files, I can note that the test files exist but can't verify their coverage.

### 8. LaTeX in Telegram

This is explicitly called out as an architect concern. Looking at the prompts, I don't see any instruction to avoid LaTeX. The ALARM_SUMMARY_SYSTEM says "Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет)" but doesn't mention LaTeX. If the model outputs `$\rightarrow$` or other LaTeX, Telegram won't render it.

### 9. Locale/timezone

Looking at the context builder:
```python
from datetime import UTC, datetime, timedelta
```

It uses `datetime.now(UTC)` in the output router. But what about timestamps in the context builder? If SQLite stores timestamps in local time, there could be a mismatch.

### 10. The `_periodic_report_tick` exception handling

This is the most critical thing I need to verify. If the while loop has no try/except, any exception kills the periodic report tick permanently.

Let me look at what I can see of the engine.py changes more carefully.

The diff shows:
```
+async def _periodic_report_tick(
+    agent_config: AssistantConfig,
+    event_bus: EventBus,
+    experiment_manager: ExperimentManager,
+    *,
+    sleep=asyncio.sleep,
+) -> None:
+    """Publish periodic_report_request events on the assistant schedule."""
+    interval_s = float(agent_config.get_periodic_report_interval_s())
+    if interval_s <= 0:
+        logger.info("Periodic assistant reports disabled (interval=0)")
+        return
+
+    window_minutes = int(agent_config.periodic_report_interval_minutes)
+    while True:
+        await sleep(interval_s)
```

Then it's truncated. I need to infer what comes next. The function publishes a `periodic_report_request` event after each sleep. But without seeing the full body, I can't confirm exception handling.

However, the audit scope explicitly asks: "Could it crash the engine? Could it leak tasks?" - this suggests there might be an issue here.

Let me think about what I CAN verify from the diff and what findings I can make with confidence.

### Finding 1: No exception handling in _periodic_report_tick loop

From what I can see, the while loop in `_periodic_report_tick` doesn't have try/except. If `event_bus.publish()` raises an exception, the coroutine terminates and no more periodic reports are generated until engine restart.

Wait, but I can't see the full function body. The diff is truncated. I should be careful about claiming something I can't verify.

Actually, looking at the diff more carefully:

```
src/cryodaq/engine.py                              | 189 ++++-
```

And the shown changes include the function signature and beginning but not the full body. I need to be honest about what I can and can't see.

Let me focus on what I CAN verify from the visible diff.

### Finding: GUI_INSIGHT doesn't include prefix_suffix

Looking at the output_router.py code:

```python
async def dispatch(
    self,
    trigger_event: EngineEvent,
    llm_output: str,
    *,
    targets: list[OutputTarget],
    audit_id: str,
    prefix_suffix: str = "",
) -> list[str]:
    dispatched: list[str] = []
    if prefix_suffix:
        prefix = f"{self._brand_base} {prefix_suffix}:"
    else:
        prefix = self._prefix
    prefixed = f"{prefix} {llm_output}"

    for target in targets:
        try:
            if target == OutputTarget.TELEGRAM:
                if self._telegram is not None:
                    await self._telegram._send_to_all(prefixed)
                    dispatched.append("telegram")
                ...
            elif target == OutputTarget.OPERATOR_LOG:
                await self._event_logger.log_event(
                    "assistant",
                    prefixed,
                    ...
                )
                dispatched.append("operator_log")

            elif target == OutputTarget.GUI_INSIGHT:
                ...
                await self._event_bus.publish(
                    _EngineEvent(
                        event_type="assistant_insight",
                        timestamp=datetime.now(UTC),
                        payload={
                            "text": llm_output,  # RAW, not prefixed
                            "trigger_event_type": trigger_event.event_type,
                            "audit_id": audit_id,
                        },
                        ...
                    )
                )
                dispatched.append("gui_insight")
```

The GUI_INSIGHT target sends `llm_output` (raw) without the prefix or prefix_suffix. This means:
1. The GUI panel doesn't show "🤖 Гемма (отчёт за час):" prefix for periodic reports
2. The GUI panel doesn't show any brand identification

This is inconsistent - Telegram and operator_log get the prefix with suffix, but GUI doesn't. The `prefix_suffix` parameter was specifically added for periodic reports (the diff says "prefix_suffix support"), but it's not applied to the GUI channel.

Actually wait - maybe this is intentional. The GUI insight panel might have its own header rendering. But the `prefix_suffix` specifically identifies the report type, which would be useful in the GUI too.

Hmm, but this might be by design. Let me think about whether this is actually a bug or intentional.

Looking at the payload:
```python
payload={
    "text": llm_output,
    "trigger_event_type": trigger_event.event_type,
    "audit_id": audit_id,
}
```

The `trigger_event_type` would be "periodic_report_request" or similar, so the GUI could use that to add its own prefix. But the `prefix_suffix` text "(отчёт за час)" is lost to the GUI.

I think this is a MEDIUM finding - the prefix_suffix is not passed to the GUI channel, meaning GUI users can't distinguish periodic reports from other assistant insights by the text alone.

### Finding: LaTeX not prohibited in prompts

Looking at the prompt templates, ALARM_SUMMARY_SYSTEM says:
```
Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
```

But there's no instruction to avoid LaTeX notation like `$\rightarrow$`. The architect concern about LaTeX in Telegram is not addressed in the prompts. There's also no output sanitizer visible in the diff.

This is a MEDIUM finding - the prompts don't instruct the model to avoid LaTeX, and there's no output sanitizer to strip it.

### Finding: Periodic report first tick delay

The `_periodic_report_tick` function does `await sleep(interval_s)` BEFORE the first publish. This means the first periodic report comes `interval_minutes` after engine start, not at startup. If the engine starts at the beginning of a shift, the operator won't get a report until an hour later.

This might be intentional (you don't want a report at t=0 when there's no data yet), but it's worth noting.

Actually, this is probably intentional and not a bug. Skip.

### Finding: Rate limiter could silently drop periodic reports

The periodic report shares the rate limit bucket with other triggers. If the system is busy (many alarms), the periodic report could be rate-limited and silently dropped. There's no mention of queueing or retry for rate-limited periodic reports.

But I can't see the rate limiter code in the diff, so I can't verify this.

### Finding: window_minutes type mismatch potential

```python
window_minutes = int(agent_config.periodic_report_interval_minutes)
```

If `periodic_report_interval_minutes` is configured as a float in YAML (e.g., `90.5`), `int()` silently truncates to 90. The event payload would say `window_minutes: 90` but the actual sleep interval would be `90.5 * 60 = 5430` seconds. This creates a mismatch between the reported window and the actual window.

But `periodic_report_interval_minutes` is typed as `int` in `AssistantConfig`, so this would require a YAML misconfiguration. Low severity.

### Finding: No try/except in _periodic_report_tick

I need to be careful here. The diff is truncated and I can't see the full function body. But based on what's visible, the while loop doesn't show exception handling. If the publish call raises, the coroutine dies.

Actually, let me re-read the audit scope more carefully:

"Engine integration — _periodic_report_tick startup, shutdown, cancellation, exception handling. Could it crash the engine? Could it leak tasks? Could it block other periodic ticks?"

This is explicitly called out as a focus area. Let me look at what I can see:

```python
while True:
    await sleep(interval_s)
    # ... (truncated)
```

The sleep is injectable (via the `sleep` parameter), which is good for testing. But I can't see if there's a try/except around the publish.

Given the truncation, I should note this as a potential concern but acknowledge I can't fully verify it.

Wait, actually, looking at the test file:
```
tests/agents/assistant/test_engine_periodic_report_tick.py  |  107 +++
```

This exists and has 107 lines. The test might cover exception handling. But I can't see its contents.

Let me focus on findings I CAN verify from the visible diff.

### Finding: GUI insight payload missing prefix_suffix information

This is verifiable. The `dispatch` method accepts `prefix_suffix` but only applies it to Telegram and operator_log outputs. The GUI insight payload doesn't include any information about the prefix_suffix, so the GUI can't reconstruct it.

### Finding: No LaTeX prohibition in prompts

This is verifiable. Looking at the prompt templates, none of them instruct the model to avoid LaTeX notation. The architect concern about `$\rightarrow$` in Telegram output is not addressed.

### Finding: Output router catches exceptions per-target but doesn't report failures

Looking at the dispatch method:
```python
for target in targets:
    try:
        if target == OutputTarget.TELEGRAM:
            ...
        elif target == OutputTarget.OPERATOR_LOG:
            ...
        elif target == OutputTarget.GUI_INSIGHT:
            ...
    except Exception:
        ...
```

Wait, I can't see the except clause. The output_router.py shows 109 lines but some are truncated. Let me look at what's visible...

The visible code shows the try blocks but the except handling is in the truncated part. I can't verify this.

OK, let me be more systematic about what I can actually verify.

### Verified findings from visible diff:

1. **GUI_INSIGHT doesn't receive prefix or prefix_suffix** - The `text` field in the GUI insight payload uses raw `llm_output` without the brand prefix or prefix_suffix. This means periodic reports in the GUI panel lack the "(отчёт за час)" identification that Telegram and operator_log get.

2. **No LaTeX prohibition in prompt templates** - The prompt templates don't instruct the model to avoid LaTeX notation. Given that the architect has flagged `$\rightarrow$` appearing in output, and Telegram doesn't render LaTeX, this is a real quality issue.

3. **`window_minutes` silently truncated to int** - `int(agent_config.periodic_report_interval_minutes)` truncates any fractional value. If someone configures `interval_minutes: 90.5` in YAML, the window reported to the handler would be 90 minutes while the actual interval is 90.5 minutes.

Let me look more carefully at the diff for other issues...

### Looking at the context builder more carefully:

The context builder has:
```python
from datetime import UTC, datetime, timedelta
```

And uses `datetime.now(UTC)` in the output router. But I need to check what timezone the context builder uses for timestamps in the report context.

I can see the context builder imports `UTC, datetime, timedelta` but the actual timestamp handling is in the truncated code.

### Looking at the PERIODIC_REPORT prompts:

The diff shows 292 lines for prompts.py but truncates after about 100 lines. I can see ALARM_SUMMARY, EXPERIMENT_FINALIZE, and the beginning of CAMPAIGN_REPORT_INTRO, but the PERIODIC_REPORT prompts are in the truncated section.

However, the audit scope says the already-fixed issue #1 was "PERIODIC_REPORT_SYSTEM hardcoded 'последний час' wording — FIXED to 'заданное окно времени'". So the PERIODIC_REPORT prompts exist and were modified.

### Looking at the agent.py handler:

The `_handle_periodic_report` method is mentioned but in the truncated 701 lines. I can't verify its implementation.

### Looking at the engine.py startup wiring:

The diff shows imports being added and the `_periodic_report_tick` function, but the startup wiring (where the task is created) is in the truncated part.

Let me think about what other issues might exist based on the patterns I can see...

### Finding: `_periodic_report_tick` has no try/except in the loop

From the visible code:
```python
while True:
    await sleep(interval_s)
    # ... publish event (truncated)
```

If the event publish raises an exception, the entire coroutine terminates. This means:
- No more periodic reports until engine restart
- The exception would propagate to the task that created this coroutine

But I can't verify this because the full loop body is truncated. However, the audit scope explicitly asks about this, which suggests it might be an issue.

Actually, wait. Let me re-read the diff more carefully. The engine.py diff shows:

```
@@ -89,6 +95,42 @@ _LOG_GET_TIMEOUT_S = 1.5
+async def _periodic_report_tick(
...
+    window_minutes = int(agent_config.periodic_report_interval_minutes)
+    while True:
+        await sleep(interval_s)
```

Then it says "(more changes truncated)" and "+22 -0". So the function body after the sleep is in the truncated part. I genuinely can't see if there's exception handling.

But the audit scope says "Could it crash the engine?" - this is a specific question about a specific concern. Let me think about what the likely implementation is...

The function probably does something like:
```python
while True:
    await sleep(interval_s)
    await event_bus.publish(EngineEvent(
        event_type="periodic_report_request",
        timestamp=datetime.now(UTC),
        payload={"window_minutes": window_minutes},
        ...
    ))
```

If there's no try/except, any exception in publish kills the coroutine. This is a real risk.

But I can't verify this from the diff. I should note it as a concern but not claim it as a verified finding.

Hmm, but the instructions say "Reference exact lines from the diff. Speculation about code not shown will be classified as hallucination."

So I should only report findings I can verify from the visible diff.

Let me compile my verified findings:

1. **GUI_INSIGHT missing prefix/prefix_suffix** - Verifiable from output_router.py lines
2. **No LaTeX prohibition in prompts** - Verifiable from prompts.py
3. **window_minutes int truncation** - Verifiable from engine.py

Wait, let me look at the output_router.py more carefully for the exception handling...

The visible code shows:
```python
for target in targets:
    try:
        if target == OutputTarget.TELEGRAM:
            ...
        elif target == OutputTarget.OPERATOR_LOG:
            ...
        elif target == OutputTarget.GUI_INSIGHT:
            ...
```

But the except clause is truncated. I can see "...(9 lines truncated)" at the end. The except clause is probably there and handles exceptions per-target. So the dispatch method likely handles individual target failures gracefully.

But wait - if Telegram fails, the method continues to operator_log and gui_insight. That's good. But what about the return value? It returns `dispatched` which only contains successfully dispatched targets. The caller can check if all targets were dispatched.

OK, let me also look at a subtle issue...

### Finding: GUI insight payload uses `llm_output` without prefix

This is actually more significant than I initially thought. The GUI insight panel receives the raw LLM output without any brand identification. If the GUI panel doesn't add its own prefix, operators won't know the message is from the AI assistant. This is especially problematic for periodic reports where the prefix_suffix "(отчёт за час)" helps distinguish the report type.

But actually, the GUI insight payload includes `trigger_event_type` and `audit_id`, so the GUI can add its own identification. The question is whether the current GUI implementation does so. This might be intentional separation of concerns.

Let me reconsider... The `prefix_suffix` was specifically added for periodic reports. The fact that it's not passed to the GUI channel means the GUI can't display it. This is a design gap.

### Finding: Periodic report shares rate limit with alarms

From the config:
```yaml
rate_limit:
  max_calls_per_hour: 60
  max_concurrent_inferences: 2
```

With `max_concurrent_inferences: 2`, if a periodic report inference is running (up to 60s timeout) and an alarm fires, the alarm might have to wait. In a critical alarm scenario, this could delay alarm notification.

But I can't see the rate limiter implementation, so I can't verify if periodic reports have a separate bucket or priority.

### Let me look at the PERIODIC_REPORT prompts more carefully

The prompts.py file is truncated, but I can see the pattern from the other prompts. The ALARM_SUMMARY_SYSTEM says:
```
Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
```

If the PERIODIC_REPORT_SYSTEM doesn't have a similar instruction (or doesn't explicitly prohibit LaTeX), the model might output LaTeX.

The architect concern about `$\rightarrow$` suggests this has already happened. The fix should be either:
1. Add "Никакого LaTeX" to the prompt
2. Add an output sanitizer

Neither appears to be in the visible diff.

### Finding: Empty section placeholders could leak to LLM

Looking at the ALARM_SUMMARY_USER template:
```python
+ПОСЛЕДНИЕ ПОКАЗАНИЯ (последние {lookback_s}с) на затронутых каналах:
+{recent_readings}
+
+ПОСЛЕДНИЕ АЛАРМЫ (последний час):
+{recent_alarms}
```

If `recent_readings` or `recent_alarms` is an empty string, the LLM sees a section header with no content. This could cause the LLM to hallucinate content for that section.

But looking at the context builder, there are stub functions:
```python
recent_readings_text=_readings_stub(channels, lookback_s),
recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
```

The stubs might return "Нет данных" or similar. I can't verify without seeing the full code.

For PERIODIC_REPORT_USER, the same pattern likely applies. If a section (e.g., calibration events) is empty, the placeholder might be an empty string, causing the LLM to hallucinate.

But again, I can't verify this from the truncated diff.

### Let me focus on what I can definitively verify

**Finding 1: GUI insight channel doesn't receive prefix_suffix**

File: `src/cryodaq/agents/assistant/live/output_router.py`

The `dispatch` method constructs `prefixed` with the brand prefix and `prefix_suffix`, but the GUI_INSIGHT target sends raw `llm_output` without prefix or suffix:

```python
payload={
    "text": llm_output,  # No prefix, no prefix_suffix
    "trigger_event_type": trigger_event.event_type,
    "audit_id": audit_id,
},
```

While Telegram and operator_log get `prefixed`:
```python
await self._telegram._send_to_all(prefixed)  # Has prefix + prefix_suffix
await self._event_logger.log_event("assistant", prefixed, ...)  # Has prefix + prefix_suffix
```

Impact: GUI panel users can't identify periodic reports vs other assistant insights. The `prefix_suffix` "(отчёт за час)" is lost.

**Finding 2: No LaTeX prohibition in prompt templates**

File: `src/cryodaq/agents/assistant/live/prompts.py`

The ALARM_SUMMARY_SYSTEM mentions "Telegram-friendly Markdown" but doesn't prohibit LaTeX. The PERIODIC_REPORT prompts (in truncated section) likely have the same gap. The architect has flagged `$\rightarrow$` appearing in output.

Impact: Telegram renders LaTeX as raw text, degrading readability.

**Finding 3: window_minutes int truncation**

File: `src/cryodaq/engine.py`

```python
window_minutes = int(agent_config.periodic_report_interval_minutes)
```

If YAML contains a float value, `int()` silently truncates. The event payload would report a different window than the actual sleep interval.

Impact: Report says "last 90 minutes" but actually covers 90.5 minutes. Low severity since the field is typed as int.

Wait, actually this is really low severity. The field is `int` in the dataclass, and the YAML example uses an integer. This would only happen with a misconfigured YAML. Let me drop this one.

### Let me look for more substantive issues...

Actually, let me re-examine the `_periodic_report_tick` function more carefully.

```python
async def _periodic_report_tick(
    agent_config: AssistantConfig,
    event_bus: EventBus,
    experiment_manager: ExperimentManager,
    *,
    sleep=asyncio.sleep,
) -> None:
    """Publish periodic_report_request events on the assistant schedule."""
    interval_s = float(agent_config.get_periodic_report_interval_s())
    if interval_s <= 0:
        logger.info("Periodic assistant reports disabled (interval=0)")
        return

    window_minutes = int(agent_config.periodic_report_interval_minutes)
    while True:
        await sleep(interval_s)
```

The function takes `experiment_manager` as a parameter but doesn't appear to use it in the visible code. The event payload likely just contains `window_minutes`. The handler then uses `experiment_manager` to build context.

But wait - the function signature includes `experiment_manager` but the visible code doesn't use it. Is it passed to the event payload? Or is it unused?

If it's unused in the tick function, it's a code smell but not a bug. The handler gets it from elsewhere.

Actually, looking at the function more carefully, the `experiment_manager` parameter might be used in the truncated part of the function. Or it might be passed in the event payload. I can't tell.

### Let me think about the skip-if-idle logic

The config has:
```yaml
skip_if_idle: true
min_events_for_dispatch: 1
```

And in AssistantConfig:
```python
periodic_report_skip_if_idle: bool = True
periodic_report_min_events: int = 1
```

The skip-if-idle check happens in the handler (after the event is published). If `total_event_count < min_events_for_dispatch`, the report is skipped.

But what counts as an "event"? If the context builder counts alarm events but not sensor readings, a period with many sensor changes but no alarms would be considered "idle" and skipped. This could miss important context.

I can't verify this without seeing the full context builder code.

### Let me look at the output_router more carefully for silent failures

The dispatch method has a try/except per target. If Telegram fails (e.g., network error), the method logs the error and continues to other targets. But the method returns `dispatched` which only contains successful targets.

The caller (in agent.py, truncated) might not check if all targets were dispatched. If Telegram fails silently, the operator doesn't get the notification, and no one is alerted to the failure.

But this is a general issue, not specific to periodic reports.

### Let me think about DST transitions

The audit scope asks: "Could DST transition cause off-by-1h?"

The context builder uses `datetime.now(UTC)` which is timezone-aware and doesn't have DST issues. But if SQLite stores timestamps in local time, there could be a mismatch during DST transitions.

For example, if the window is "last 60 minutes" and a DST transition happened 30 minutes ago, the local time calculation could be off by an hour.

I can't verify this without seeing the full context builder code.

### Let me compile my final findings

Based on what I can verify from the visible diff:

1. **MEDIUM: GUI insight channel doesn't receive prefix_suffix** - output_router.py sends raw `llm_output` to GUI without brand prefix or prefix_suffix, while Telegram and operator_log get the prefixed version.

2. **MEDIUM: No LaTeX prohibition in prompt templates** - prompts.py doesn't instruct the model to avoid LaTeX notation, and there's no output sanitizer. This matches the architect's concern about `$\rightarrow$` in Telegram output.

3. **LOW: window_minutes int truncation** - engine.py uses `int()` which silently truncates float values, potentially creating a mismatch between reported and actual window.

Actually, wait. Let me look at the output_router.py one more time...

```python
elif target == OutputTarget.GUI_INSIGHT:
    from datetime import UTC, datetime

    from cryodaq.core.event_bus import EngineEvent as _EngineEvent

    await self._event_bus.publish(
        _EngineEvent(
            event_type="assistant_insight",
            timestamp=datetime.now(UTC),
            payload={
                "text": llm_output,
                "trigger_event_type": trigger_event.event_type,
                "audit_id": audit_id,
            },
            experiment_id=trigger_event.experiment_id,
        )
    )
    dispatched.append("gui_insight")
```

The GUI insight payload includes `trigger_event_type` which would be "periodic_report_request". So the GUI CAN distinguish periodic reports from other insights. But it can't reconstruct the prefix_suffix text "(отчёт за час)".

Actually, the GUI could infer the prefix_suffix from the trigger_event_type. If it's "periodic_report_request", add "(отчёт за час)". But this hardcodes the suffix in the GUI instead of using the one from the router.

Hmm, but this might be intentional. The GUI might have its own rendering logic. Let me not overthink this.

Let me also check: does the `prefix_suffix` get passed to the handler at all? Looking at the agent.py code (truncated), the handler probably calls `dispatch` with `prefix_suffix="(отчёт за час)"`. The router then applies it to Telegram and operator_log but not GUI.

This is a design inconsistency. The `prefix_suffix` feature was added specifically for periodic reports, but it's not fully applied.

OK, I think I have enough for a solid audit. Let me also think about whether there are any CRITICAL issues...

### Could the engine crash?

If `_periodic_report_tick` raises an unhandled exception, the asyncio task wrapping it would die. But the engine should handle task failures gracefully (log the exception and continue). Without seeing the engine startup code, I can't verify this.

But the audit scope asks "Could it crash the engine?" - if the tick task is created with `asyncio.create_task()` and the engine doesn't handle task exceptions, an unhandled exception could be logged but wouldn't crash the engine. However, if the engine awaits the tick task, an exception would propagate.

I can't verify this from the visible diff.

### Could it leak tasks?

If the engine creates the tick task but doesn't cancel it on shutdown, the task would leak. But this is standard asyncio lifecycle management. I can't verify from the visible diff.

### Could it block other periodic ticks?

The `_periodic_report_tick` is a separate coroutine with its own sleep loop. It shouldn't block other ticks unless it hogs the event loop. The `await sleep(interval_s)` yields control, so other coroutines can run. The `event_bus.publish()` is async and should also yield.

No blocking issue from what I can see.

### Final assessment

Let me compile my findings:

1. **MEDIUM: GUI insight channel missing prefix and prefix_suffix** - Verified from output_router.py
2. **MEDIUM: No LaTeX prohibition in prompts** - Verified from prompts.py
3. **LOW: window_minutes int truncation** - Verified from engine.py

Wait, I should also check if there's a more critical issue I'm missing...

Let me re-read the audit scope focus areas:

1. Engine integration - Can't fully verify (truncated)
2. EventBus contract - Can't fully verify (truncated)
3. Skip-if-idle - Can't fully verify (truncated)
4. Rate limiter - Can't fully verify (truncated)
5. Russian prompt grounding - Partially verified (no LaTeX prohibition)
6. Output dispatch path - Verified (GUI missing prefix)
7. Test coverage gaps - Can't verify (test files not shown)
8. Russian quality regressions - Can't fully verify (truncated)
9. Markdown/LaTeX in Telegram - Verified (no prohibition)
10. Locale/timezone - Can't fully verify (truncated)

OK, I think I have a solid set of findings. Let me write up the audit.

Actually, wait. Let me look one more time at the output_router.py for a potential issue I missed...

The `dispatch` method creates `prefixed` at the top:
```python
if prefix_suffix:
    prefix = f"{self._brand_base} {prefix_suffix}:"
else:
    prefix = self._prefix
prefixed = f"{prefix} {llm_output}"
```

Then for each target, it uses either `prefixed` or `llm_output`. The inconsistency is:
- TELEGRAM: `prefixed`
- OPERATOR_LOG: `prefixed`
- GUI_INSIGHT: `llm_output` (raw)

This means the GUI insight panel shows the raw LLM output without any identification. If the LLM output starts with a heading or list, it might not be clear that it's from the AI assistant.

But more importantly, for periodic reports specifically, the `prefix_suffix` is "(отчёт за час)" or similar. This context is completely lost in the GUI channel.

OK, I'm confident in this finding.

Let me also think about one more thing: the `_periodic_report_tick` function signature includes `experiment_manager` but the visible code doesn't use it. If it's not used in the truncated part either, it's a dead parameter. But this is very minor.

Actually, looking at the function again:
```python
async def _periodic_report_tick(
    agent_config: AssistantConfig,
    event_bus: EventBus,
    experiment_manager: ExperimentManager,
    *,
    sleep=asyncio.sleep,
) -> None:
```

The `experiment_manager` parameter is likely used in the truncated part to include experiment info in the event payload. Or it might be unused. I can't tell.

Let me finalize my audit now.

Hmm, actually I realize I should look more carefully at the prompts.py for the PERIODIC_REPORT templates. The file is 292 lines but truncated. Let me see what I can infer...

The visible part shows:
- ALARM_SUMMARY_SYSTEM/USER (Slice A)
- EXPERIMENT_FINALIZE_SYSTEM/USER (Slice A)
- CAMPAIGN_REPORT_INTRO_SYSTEM (Slice C, partially visible)

The PERIODIC_REPORT templates would be after these. They're in the truncated 192 lines.

From the already-fixed issues, we know:
1. PERIODIC_REPORT_SYSTEM was fixed to say "заданное окно времени" instead of "последний час"
2. Calibration entries were added with their own section

So the PERIODIC_REPORT templates exist and were modified. But I can't see them.

However, I can check the ALARM_SUMMARY_SYSTEM for the LaTeX issue:
```
Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
```

This mentions Markdown formatting but doesn't prohibit LaTeX. If PERIODIC_REPORT_SYSTEM has similar wording (or no formatting instruction at all), the LaTeX issue applies.

OK, let me write the final audit.

Actually, one more
