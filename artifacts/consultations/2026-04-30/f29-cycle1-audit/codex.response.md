# F29 Cycle 1 Audit — Codex

Verdict: PASS after one pre-audit fix.

Scope reviewed:
- Phase A-C existing branch work
- Phase D engine timer and lifecycle wiring
- Phase E smoke harness and smoke artifact
- F29 prompt behavior under non-default window

## Findings

| Severity | File | Finding | Status |
|---|---|---|---|
| MEDIUM | `src/cryodaq/agents/assistant/live/prompts.py` | `PERIODIC_REPORT_SYSTEM` hardcoded "последний час", so a configured 15-minute smoke window produced a response saying "за последний час". This fought `PERIODIC_REPORT_USER.window_minutes` and could mislead operators if deployments choose non-hourly intervals. | Fixed. System prompt now says "заданное окно времени"; regression added in `test_periodic_report_prompt_does_not_hardcode_hour_window`. |
| LOW | `src/cryodaq/agents/assistant/live/context_builder.py` / `prompts.py` | Calibration entries were folded into "other events" while the F29 spec calls out calibration as a distinct category. Smoke still mentioned calibration, but the prompt contract was weaker than spec. | Fixed. Added `calibration_entries`, explicit `calibration_section`, and regression `test_periodic_report_context_formats_calibration_section`. |

## Remaining Risk

- Full process `cryodaq-engine --mock` smoke was not run; smoke directly exercised
  `_periodic_report_tick`, AssistantLiveAgent, real Ollama, EventBus, audit, and
  OutputRouter with mocked Telegram/operator-log endpoints.
- `periodic_report_tick_task` is created if config enables periodic reports even
  when `gemma_agent.start()` fails after construction. This is harmless
  (events have no assistant consumer) but could produce low-value EventBus
  traffic during an assistant startup failure. I did not classify this as a
  blocker because EventBus publish with no subscribers is explicitly no-op safe.

## Verification

- `uv run --extra dev python -m pytest tests/agents/assistant/test_periodic_report_config.py tests/agents/assistant/test_periodic_report_context.py tests/agents/assistant/test_periodic_report_handler.py tests/agents/assistant/test_engine_periodic_report_tick.py tests/gui/shell/views/test_assistant_insight_panel.py -q`
  - 34 passed in 1.71s
- `uv run --extra dev python artifacts/scripts/smoke_f29_periodic_report.py`
  - PASS, real `gemma4:e2b`
  - 19.2s wall latency, 18.879s audit latency
  - 94.8% Russian ratio
  - dispatched: telegram, operator_log, gui_insight
  - idle skip verified
