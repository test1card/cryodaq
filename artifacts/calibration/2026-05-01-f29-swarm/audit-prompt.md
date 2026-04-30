# F29 Cycle 1 audit — periodic narrative reports

## Context

CryoDAQ is a production cryogenic data-acquisition system. v0.46.0
ships F29: hourly Russian-language narrative summary of last-N-minutes
engine activity, dispatched to Telegram + operator log + GUI insight
panel.

This commit was already self-audited by Codex gpt-5.5 — that audit
found 2 real issues which were fixed before this audit. Your job
is independent verification: are there issues that Codex missed?

## Scope

Branch: feat/f29-periodic-reports
Final commit: ef0a1eb (release: v0.46.0)
Diff range: master..feat/f29-periodic-reports

## Files in scope

- src/cryodaq/engine.py — _periodic_report_tick coroutine, startup wiring
- src/cryodaq/agents/assistant/live/agent.py — _handle_periodic_report
- src/cryodaq/agents/assistant/live/context_builder.py — build_periodic_report_context, PeriodicReportContext
- src/cryodaq/agents/assistant/live/prompts.py — PERIODIC_REPORT_SYSTEM/USER
- src/cryodaq/agents/assistant/live/output_router.py — prefix_suffix support
- config/agent.yaml — triggers.periodic_report block
- tests/agents/assistant/test_engine_periodic_report_tick.py
- tests/agents/assistant/test_periodic_report_config.py
- tests/agents/assistant/test_periodic_report_context.py
- tests/agents/assistant/test_periodic_report_handler.py
- artifacts/scripts/smoke_f29_periodic_report.py
- CHANGELOG.md, ROADMAP.md, pyproject.toml (release bump)

## Already fixed in pre-audit pass (DO NOT report these as findings)

The following issues were caught by Codex self-audit and FIXED in
ef0a1eb. Reporting them again will be classified as
HALLUCINATION_ECHO and lower your score:

1. PERIODIC_REPORT_SYSTEM hardcoded "последний час" wording —
   FIXED to "заданное окно времени"
2. Calibration events bucketed into other-events instead of own
   section — FIXED with calibration_entries field + Калибровка:
   prompt section
3. Smoke harness fake timer sleep loop — FIXED with CancelledError
   on second sleep

## Your task

Independent review. Focus on:

1. **Engine integration** — _periodic_report_tick startup,
   shutdown, cancellation, exception handling. Could it crash
   the engine? Could it leak tasks? Could it block other
   periodic ticks?
2. **EventBus contract** — periodic_report_request payload schema.
   Does it match what handler expects? Is window_minutes int or
   float?
3. **Skip-if-idle correctness** — total_event_count threshold.
   Does it count what it should count? Could empty intervals
   slip through? Could populated intervals get suppressed?
4. **Rate limiter interaction** — periodic_report shares bucket
   with other triggers. Could a stuck periodic block other
   handlers? Could rate limit drop a periodic without
   acknowledgement?
5. **Russian prompt grounding** — does PERIODIC_REPORT_USER
   actually pass real data through? Could it hallucinate events?
   Could empty sections leak placeholders?
6. **Output dispatch path** — prefix_suffix passed to all 3
   channels (Telegram, log, GUI)? Could one fail silently?
7. **Test coverage gaps** — what scenarios are NOT tested?
   - Engine timer cancellation mid-inference
   - Concurrent periodic + alarm dispatch
   - Empty Ollama response handling
   - SQLite read failure during context build
   - Misconfigured interval (negative, zero, float)
8. **Russian quality regressions** — anything in PERIODIC_REPORT_*
   templates that could degrade quality vs F28 Slice A baseline?
9. **Markdown rendering in Telegram** — sample output contained
   `$\rightarrow$` (LaTeX). Does the prompt instruct against
   LaTeX? Does the output sanitizer strip it? This is a known
   architect concern not yet addressed.
10. **Locale / timezone** — do timestamps in summaries use
    consistent timezone? Could DST transition cause off-by-1h?

## Output format

Verdict: PASS / CONDITIONAL / FAIL

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- File:line reference (must exist in actual diff — verify)
- Description: what's wrong, in 1-3 sentences
- Why it matters: 1 sentence operational impact
- Recommended fix: 1-2 sentences

If no findings: brief explanation why confidence is high after
review.

## Constraints

- Be specific. Vague concerns ("may have issues") are not findings.
- Reference exact lines from the diff. Speculation about code not
  shown will be classified as hallucination.
- Keep response under 1500 words. Quality over quantity.
- Russian or English both fine. Russian preferred for findings
  about Russian prompt quality.
- DO NOT echo the 3 already-fixed findings in §"Already fixed".
