# F29 Cycle 1 Audit Synthesis

Date: 2026-04-30  
Branch: `feat/f29-periodic-reports`  
Base SHA before Phase D local fixes: `be7eee6`

## Verifiers

| Verifier | Result |
|---|---|
| Codex gpt-5.5 | PASS after one MEDIUM and one LOW pre-audit fix |
| GLM-5.1 | NO RESULT — CCR dispatch hung and was terminated |

## Decisions

1. Fixed the hardcoded hourly wording in `PERIODIC_REPORT_SYSTEM`.
   - Root cause: system prompt said "последний час" even when the event payload
     carried a non-hourly `window_minutes`.
   - Evidence: real e2b smoke with a 15-minute timer produced "за последний час".
   - Fix: system prompt now says "заданное окно времени"; user prompt remains
     authoritative with `{window_minutes}`.

2. Fixed calibration prompt structure.
   - Root cause: `PeriodicReportContext` returned `calibration_section` as
     `"(нет)"` and classified calibration events as generic other events.
   - Fix: added `calibration_entries`, explicit calibration formatting, and
     `Калибровка:` block in `PERIODIC_REPORT_USER`.

3. Accepted residual smoke limitation.
   - The smoke is not a full `cryodaq-engine --mock` subprocess run.
   - It does exercise the F29-critical path directly:
     `_periodic_report_tick` -> EventBus -> AssistantLiveAgent -> real
     `gemma4:e2b` -> OutputRouter -> Telegram/log/GUI/audit mocks/events.

## Final Audit Verdict

CONDITIONAL PASS.

Codex audit issues were fixed and verified. GLM did not return, so the mandated
2-model dispatch was attempted but not completed. No known blocking code finding
remains from the available audit evidence.
