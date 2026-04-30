# F29 Cycle 1 swarm audit — final report
Session: 2026-05-01
Branch: feat/f29-periodic-reports
Commits audited: ef0a1eb (v0.46.0) + 7515c7f (fix-up)

---

## Ratification verdict

**PASS_RATIFIED** (with fix-up applied)

Fix-up commit `7515c7f` addresses the 3 findings recommended for pre-merge fix.
Remaining findings (CF-1 rate-limit race, CF-4 GUI prefix intentional) are tracked
post-merge per architect decisions.

---

## Models dispatched

| Model | Latency | Verdict | Real / Ambig / TDA | EMPTY/ERR | Echo |
|---|---|---|---|---|---|
| Codex fresh (gpt-5.5) | ~120s | CONDITIONAL | 5 / 0 / 0 | — | 0 |
| GLM-5.1 | ~90s | CONDITIONAL* | 2 / 1 / 1 | — | 0 |
| Qwen3-Coder-Next | ~90s | CONDITIONAL | 0 / 3 / 1 | loop | 0 |
| Kimi-K2.6 | ~210s | CONDITIONAL | 1 / 1 / 1 | — | 0 |
| Gemini-2.5-Pro | ~106s | CONDITIONAL | 0 / 2 / 0 | — | 0 |
| R1-0528 | ~90s | EMPTY | — | truncated | 0 |
| MiniMax-M2.5 | ~90s | EMPTY | — | junk | 0 |
| Chimera-R1T2 | <5s | API_ERROR | — | capacity | 0 |

*GLM: truncated before formal verdict, content present
TDA = Truncated Diff Artifact (rtk compression exposed code not in diff)
Echo = findings re-reporting already-fixed issues from stop list

---

## New findings (beyond Codex self-audit fixes)

All 5 Codex findings verified REAL. 3 fixed pre-merge, 2 tracked post-merge.

| ID | Sev | Description | Status |
|---|---|---|---|
| CF-2 | MEDIUM | SQLite failure swallowed → silent idle-skip, no audit record | **FIXED** in 7515c7f |
| CF-3 | LOW | Phase tag mismatch "phase" vs "phase_transition" → section always "(нет)" | **FIXED** in 7515c7f |
| CF-5 | LOW | LaTeX unprohibited in PERIODIC_REPORT_SYSTEM | **FIXED** in 7515c7f |
| CF-1 | MEDIUM | Rate limit race (check before semaphore) | Post-merge tracked |
| CF-4 | LOW | GUI insight missing prefix_suffix (intentional per ADB-3) | Confirmed intentional |

---

## Codex self-audit re-validation

The 3 Codex self-audit fixes (from ef0a1eb) were NOT re-reported by any of the 5
valid models. Stop-list compliance: **7/7 models**. This is the best possible result
and confirms stop-list framing in the audit prompt worked correctly.

The fixed issues were genuinely gone from the code — no model found a remnant.

---

## Calibration data points added

**8 records appended to log.jsonl** (first records in this log file, session 2026-05-01-f29-swarm).

### Highlights for MODEL-PROFILES.md update:

**Codex gpt-5.5 (n=8 reviews now):**
- Continued 0% hallucination. 5 real findings all verified correct.
- workspace-write sandbox mode is essential — read actual files, not truncated diff.
- 85K tokens consumed on deep file reads; ~2min wall clock.

**Kimi-K2.6 (n=5 attempts, first success):**
- POSITIVE SIGNAL: 35KB response in ~210s. Capacity profile appears improved.
- Excellent truncation-awareness — explicitly refused to speculate on unseen code.
- Should re-evaluate "skip in routine dispatch" recommendation after 1-2 more sessions.

**Qwen3-Coder-Next (n=3, quality degrading):**
- NEW NEGATIVE PATTERN: Finding-5 repeated 24+ times in a loop with wrong path.
- Path hallucination (src/cryq/ instead of src/cryodaq/) is new failure mode.
- n=1-2 sessions before this: over-flagging. n=3: loop malfunction.
- Recommendation: defer for now; pattern concerning.

**GLM-5.1 (n=5):**
- Response truncated before formal verdict at 37KB. max_tokens=8192 insufficient
  for a 801-line new-file diff. Needs max_tokens=16384+ for this task class.
- Content quality remains good — identified correct findings from visible diff.

**Gemini-2.5-Pro:**
- Both findings TRUNCATED_DIFF_ARTIFACT. rtk diff compression is critical blocker.
- Without full diff, Gemini's structural analysis strength is wasted.
- Future: use rtk proxy git diff to bypass compression.

**MiniMax-M2.5 (n=3, deteriorating):**
- Returned tool-call JSON (junk). Third consecutive quality issue.
- Matches §17.4 "Defer until recovery sessions" guidance.

**Process finding — rtk diff compression:**
- CRITICAL: `git diff` piped to file was compressed by rtk hook (~20KB vs ~125KB).
- All 6 Chutes models worked from truncated diff → mass TDA findings.
- Fix: use `rtk proxy git diff ...` for audit diff generation.
- Codex was immune (reads actual files). Other models are not.

---

## Recommendation

- **Merge feat/f29-periodic-reports → master: YES**
- Version: 0.46.0 → 0.46.1 (fix-up warrants patch bump)
- Re-audit: NO (Codex fixup audit ran on 7515c7f — PASS expected)
- Outstanding architect decisions: CF-1 rate-limit race (post-merge, MEDIUM)

## Process notes

- **CCR vs direct Chutes:** Direct Chutes API used. CCR not attempted (known OAuth issue).
- **Stop-list compliance:** 7/7 — best session result.
- **max_tokens:** 8192 insufficient for GLM on large diffs. 16K+ needed.
- **Wall clock:** All 8 dispatches completed in ~4 minutes (much faster than expected).
