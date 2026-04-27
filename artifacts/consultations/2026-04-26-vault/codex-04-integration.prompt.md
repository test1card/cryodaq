Model: gpt-5.5
Reasoning effort: high

# Vault audit — Integration loop iter 1 (Codex literal verifier)

## Mission

Full-vault literal audit. The vault has gone through Phase 1
skeleton, Phase 2 reference seed, Phase 3 synthesis (already
audited), Phase 4 cross-link + source map, Phase 5 update protocol,
and a fix pass for both Phase 2 and Phase 3 audit findings. This is
the integration check.

You audited Phase 3 in the previous round and identified 17 findings
(verdict FAIL). All CRITICAL and HIGH findings have been addressed.
Verify the fixes hold and find any remaining line-level errors.

You are the literal verifier. Codex's job here is line-by-line
correctness, file:line precision. Gemini covers structural /
coherence in parallel — DO NOT duplicate that.

## Scope

All notes under `~/Vault/CryoDAQ/` — 45 markdown files. Re-audit any
note you previously flagged in Phase 3 to confirm the fix landed
correctly; spot-check the rest.

## Source files for verification (in `~/Projects/cryodaq/`)

Same source set as Phase 3 audit:

- `CLAUDE.md`, `README.md`, `PROJECT_STATUS.md`, `ROADMAP.md`,
  `CHANGELOG.md`
- `docs/ORCHESTRATION.md`, `docs/bug_B1_zmq_idle_death_handoff.md`
- `docs/decisions/*.md`
- `.claude/skills/multi-model-consultation.md`
- `src/cryodaq/core/*.py` (especially safety_manager,
  zmq_bridge, zmq_subprocess, scheduler, alarm_v2, alarm_providers,
  calibration_acquisition)
- `src/cryodaq/analytics/{base_plugin,plugin_loader,calibration,calibration_fitter}.py`
- `src/cryodaq/drivers/instruments/*.py`
- `src/cryodaq/storage/sqlite_writer.py`
- `config/instruments.yaml`, `config/alarms_v3.yaml`,
  `config/interlocks.yaml`, `config/plugins.yaml`

## What to flag (CRITICAL / HIGH / MEDIUM / LOW)

Same severity scale as Phase 3 audit. Be ruthless on regressions
(claim that was correct in Phase 3 audit but the fix introduced a
new error).

## What NOT to flag

- Stylistic preferences.
- Synthesis-vs-strict-mirror tension (vault is digest by design).
- "Coverage gap" — that's Gemini's domain.

## Output

Per finding: severity / vault file:line / source file:line /
proposed fix. Verdict: PASS / FAIL / CONDITIONAL. Cap 3000 words.

If your sandbox is read-only, just emit the response to stdout —
the wrapper redirect captures it. Don't try to write the response
file yourself.

## Response file

`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-04-integration.response.md`
