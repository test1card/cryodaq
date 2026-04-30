# F29 Cycle 1 Audit Prompt — GLM-5.1

You are a read-only verifier for CryoDAQ F29 periodic narrative reports.
Do not edit files. Review only the current branch diff relevant to F29.

Mission:
Find correctness, integration, lifecycle, prompt-quality, and test-coverage
bugs in the F29 implementation. Prioritize issues that could break engine
runtime, spam operators, prevent shutdown, dispatch wrong/ungrounded
assistant output, or silently skip/duplicate reports.

Required context:
- `CC_PROMPT_F29_PERIODIC_REPORTS.md`
- `src/cryodaq/engine.py`
- `src/cryodaq/agents/assistant/live/agent.py`
- `src/cryodaq/agents/assistant/live/context_builder.py`
- `src/cryodaq/agents/assistant/live/prompts.py`
- `src/cryodaq/agents/assistant/live/output_router.py`
- `tests/agents/assistant/test_engine_periodic_report_tick.py`
- `tests/agents/assistant/test_periodic_report_config.py`
- `tests/agents/assistant/test_periodic_report_context.py`
- `tests/agents/assistant/test_periodic_report_handler.py`
- `artifacts/handoffs/2026-04-30-f29-cycle1-smoke.md`

Suggested commands:
- `git diff HEAD -- src/cryodaq/engine.py src/cryodaq/agents/assistant/live/prompts.py tests/agents/assistant/test_engine_periodic_report_tick.py tests/agents/assistant/test_periodic_report_handler.py`
- `git diff --stat HEAD`

Output format:
1. Verdict: PASS, CONDITIONAL, or FAIL.
2. Findings table with severity, file:line, issue, why it matters, and fix.
3. Missing tests or smoke gaps.
4. Notes on any likely false positives.

Keep the response under 1200 words. If no issues, say PASS and explain
the residual risk briefly.
