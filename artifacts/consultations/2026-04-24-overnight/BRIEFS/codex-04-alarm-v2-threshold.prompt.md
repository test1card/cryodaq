Model: gpt-5.5
Reasoning effort: high

# Bug fix — alarm_v2 KeyError for cooldown_stall

## Mission

`src/cryodaq/core/alarm_v2.py::_eval_condition` raises
`KeyError: 'threshold'` when evaluating the `cooldown_stall`
composite alarm defined in `config/alarms_v3.yaml`. This does not
crash the engine (exception is caught and logged), but produces
log spam roughly every 2 s while the alarm is active. Small-scope,
known bug. Produce a specific patch plus a regression test.

## Context files

- `src/cryodaq/core/alarm_v2.py` — focus on `_eval_condition` and
  its caller, plus the composite-condition branch
- `src/cryodaq/core/alarm_config.py` — alarm config loader / parser
- `config/alarms_v3.yaml` — specifically the `cooldown_stall`
  definition (grep for it)
- `tests/core/test_alarm_v2*.py` if any — to match test style

## Specific questions

1. Root cause: is this a missing field in the YAML (config bug), a
   code-config contract mismatch in how composite vs threshold
   alarms are parsed, or a stale feature flag path?
2. Fix preference: tighten config (add `threshold` to
   `cooldown_stall` YAML) OR make code defensive with
   `cond.get("threshold")`? This is an ALARM — we warn operators
   about real conditions. We do NOT want to silently swallow what
   might be a genuine config error, so the fix should surface
   config mistakes loudly.
3. Show the exact patch: either a YAML change with `-` and `+`
   lines, or a unified diff of `alarm_v2.py`. Under 50 diff lines
   total.
4. Regression test: a new test that fails on current code and passes
   after the fix. Under 30 lines. Use existing test patterns in
   `tests/core/test_alarm_v2*.py` if available.

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root-cause paragraph (≤ 120 words)
- Unified diff patch (under 50 lines)
- Test case (under 30 lines) with file path it would live in
- Max 1500 words total

## Scope fence

- Do not refactor `alarm_v2.py` beyond the direct fix.
- Do not redesign the alarm schema.
- Do not comment on v3 config format vs legacy v1 alarm engine.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-04-alarm-v2-threshold.response.md`
