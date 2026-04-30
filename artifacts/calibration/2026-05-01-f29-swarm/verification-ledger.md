# F29 swarm audit — verification ledger
Session: 2026-05-01-f29-swarm
Branch: feat/f29-periodic-reports @ ef0a1eb (v0.46.0)
Architect classification: 2026-05-01

## Process note: rtk diff compression

The `git diff` command run during Phase 2 was intercepted by the rtk proxy hook and
compressed. The resulting `/tmp/f29-diff.patch` (523 lines, 20KB) contained only partial
file content for large files — specifically:
- `agent.py` (801 lines added): ~100 lines visible, 701 truncated
- `context_builder.py` (547 lines added): ~100 lines visible, 447 truncated
- `prompts.py` (292 lines added): ~100 lines visible, PERIODIC_REPORT templates not shown
- `engine.py` exception handling block: not visible (truncated after `while True: await sleep`)

**Impact:** All Chutes models (GLM, Qwen, Kimi, MiniMax, R1, Chimera) received this
truncated diff. Their findings about code NOT visible in the diff are classified as
TRUNCATED_DIFF_ARTIFACT (not hallucinations — plausible concerns from partial view —
but not findings against actual code).

**Codex exception:** Codex ran in `workspace-write` sandbox with git access and read
actual branch files via shell commands. Codex findings are against actual code.
Codex is the authoritative verifier for this session.

---

## Per-model summary

| Model | Latency | Verdict | Crit | High | Med | Low | Real | Halluc | TDA | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| Codex fresh | ~2min | CONDITIONAL | 0 | 0 | 2 | 3 | 5 | 0 | 0 | Read actual files; authoritative |
| GLM-5.1 | ~90s | NO_VERDICT | 0 | 0 | 0 | 2 | 2 | 0 | 1 | Truncated before formal verdict; 37KB |
| Qwen3-Coder-Next | ~90s | CONDITIONAL | 0 | 1 | 2 | 1+24loop | 3 | 0 | 1 | Severe loop: Finding 5 repeated 24× with wrong path src/cryq/ |
| Kimi-K2.6 | ~3min | CONDITIONAL | 0 | 0 | 0 | 2 | 2 | 0 | 1 | Excellent truncation-awareness; explicitly refused to hallucinate |
| Gemini-2.5-Pro | ~106s | CONDITIONAL | 0 | 1 | 1 | 0 | 0 | 0 | 2 | Both findings TRUNCATED_DIFF_ARTIFACT |
| R1-0528 | ~90s | TRUNCATED | — | — | — | — | — | — | — | 107B output; jq extraction cut off; no usable content |
| MiniMax-M2.5 | ~90s | JUNK | — | — | — | — | — | — | — | Returned tool-call JSON instead of review |
| Chimera-R1T2 | <5s | API_ERROR | — | — | — | — | — | — | — | "Infrastructure at maximum capacity" |

TDA = Truncated Diff Artifact (plausible concern from truncated diff, but actual code
addresses it — not a finding against real code)

---

## Per-finding classification

### Codex fresh (independent — reads actual files)

#### F-CF-1 [MEDIUM] Rate limit race condition
- **File:line claimed:** `src/cryodaq/agents/assistant/live/agent.py:297`
- **Architect verified:** REAL
- **Reasoning:** `_check_rate_limit()` is called before `async with self._semaphore`. Multiple
  concurrent events can all pass the rate limit check simultaneously, then each waits for the
  semaphore and appends to `_call_timestamps` on entry. With `max_concurrent_inferences=2`,
  up to 2 calls can exceed `max_calls_per_hour` in a burst. Confirmed at lines 288-308 of
  actual agent.py.
- **Severity:** MEDIUM (low operational impact at max_calls_per_hour=60; burst overshoot is
  max 2 calls)
- **Action:** Optional fix — log at warning level when this occurs; or move check+append
  inside semaphore. Non-blocking for master merge.

#### F-CF-2 [MEDIUM] SQLite failure swallowed → idle-skip treats fault as empty window
- **File:line claimed:** `src/cryodaq/agents/assistant/live/context_builder.py:130`
- **Architect verified:** REAL
- **Reasoning:** `get_operator_log()` failure is caught at DEBUG level, entries stays `[]`,
  `total_event_count=0`. Handler then applies `skip_if_idle` check, suppresses the report,
  and produces NO audit record. Operator cannot distinguish "quiet hour" from "storage fault
  during reporting hour." Confirmed at context_builder.py lines 125-132.
- **Severity:** MEDIUM
- **Action:** Consider before merge — change `logger.debug` to `logger.warning` and/or
  skip the idle check when context build failed (use a context error flag). See
  ARCHITECT DECISION NEEDED below.

#### F-CF-3 [LOW] Phase tag mismatch: "phase" logged, "phase_transition" expected
- **File:line claimed:** `src/cryodaq/agents/assistant/live/context_builder.py:134`
- **Architect verified:** REAL
- **Reasoning:** Engine logs phase transitions at `engine.py:1724` with tag "phase":
  `await event_logger.log_event("phase", f"Фаза: → {phase}")`. Context builder filters
  for `"phase_transition"` in e.tags. These don't match. Phase section in periodic
  report will always show "(нет)" even during active phase transitions.
- **Severity:** LOW (report is degraded but functional)
- **Action:** Fix recommended before merge — 1-line change in context_builder.py:
  `phase_entries = [e for e in entries if "phase_transition" in e.tags or "phase" in e.tags]`

#### F-CF-4 [LOW] GUI insight receives raw llm_output, not prefixed
- **File:line claimed:** `src/cryodaq/agents/assistant/live/output_router.py:87`
- **Architect verified:** REAL
- **Reasoning:** output_router.py builds `prefixed = f"{prefix} {llm_output}"` which includes
  the brand prefix + `prefix_suffix` (e.g., "(отчёт за час)"). Telegram and operator_log
  receive `prefixed`. GUI_INSIGHT event publishes `"text": llm_output` (raw). The "(отчёт за
  час)" label is lost to the GUI panel. Confirmed at output_router.py lines 87-95.
- **Severity:** LOW (cosmetic — GUI panel still shows content, just without report-type label)
- **Action:** ARCHITECT DECISION NEEDED — intentional (GUI adds own header) or oversight?

#### F-CF-5 [LOW] LaTeX not prohibited in PERIODIC_REPORT prompts
- **File:line claimed:** `src/cryodaq/agents/assistant/live/prompts.py:247`
- **Architect verified:** REAL (confirmed architect concern not yet addressed)
- **Reasoning:** PERIODIC_REPORT_SYSTEM instructs "Telegram-friendly Markdown" but does not
  explicitly prohibit LaTeX (`$...$`, `\rightarrow`, etc.). OutputRouter has no sanitization
  layer. This was a known architect concern (in audit scope §9) from sample output containing
  `$\rightarrow$`.
- **Severity:** LOW (UX degradation, not operational failure)
- **Action:** Add one instruction line: `Не используй LaTeX, формулы ($...$), стрелки LaTeX.
  Для стрелок используй →, ↑, ↓.` Optionally add sanitizer regex in OutputRouter.

---

### GLM-5.1

#### F-GLM-1 [LOW] GUI insight missing prefix_suffix
- **Architect verified:** REAL (duplicate of CF-4)
- **Notes:** GLM identified this from visible output_router.py diff. Correctly noted it.

#### F-GLM-2 [LOW] LaTeX concern from ALARM_SUMMARY prompt
- **Architect verified:** REAL (partially — applies to periodic prompt too, CF-5)
- **Notes:** GLM referenced ALARM_SUMMARY_SYSTEM line ~28; correctly extrapolated to
  periodic report. Conservative and accurate.

#### F-GLM-TDA-1 [HIGH→TDA] Exception handling in _periodic_report_tick
- **Architect verified:** TRUNCATED_DIFF_ARTIFACT
- **Reasoning:** Actual code has `except Exception as exc: logger.error(...)` inside while
  loop (engine.py lines 128-130). Not visible in truncated diff.

#### Notes: GLM response truncated before formal verdict (37KB file, ends mid-sentence
"Actually, one more"). No formal PASS/CONDITIONAL/FAIL stated. Response shows careful
analysis and correctly identified the most important visible findings.

---

### Qwen3-Coder-Next

#### F-Q-1 [HIGH→TDA] Exception handling missing
- **Architect verified:** TRUNCATED_DIFF_ARTIFACT (same as GLM-TDA-1)

#### F-Q-2 [MEDIUM] window_minutes int truncation
- **Architect verified:** AMBIGUOUS (LOW)
- **Reasoning:** `int(agent_config.periodic_report_interval_minutes)` cast is visible. If
  config has `60.9`, window would be 60 vs sleep 61.8min. Config field typed `int`, YAML
  `60` is YAML int, from_dict likely validates type. Theoretical edge case, not a real risk.
  Rate-as LOW if architect wants to track.

#### F-Q-3 [MEDIUM] Concurrent alarm + periodic race (test coverage gap)
- **Architect verified:** AMBIGUOUS
- **Reasoning:** `OutputRouter.dispatch` is async but not locked. Concurrent calls from alarm
  + periodic could interleave if Telegram bot isn't re-entrant. However: asyncio is
  single-threaded; `_send_to_all` calls sequential `await self._send(chat_id, ...)`.
  Interleaving is possible between awaits but messages would be separate, not corrupt.
  Framing as test gap is reasonable but finding overstates the severity.

#### F-Q-5+ [LOW→HALLUCINATION] prefix_suffix space before colon (looped 24+ times)
- **Architect verified:** HALLUCINATION + LOOP MALFUNCTION
- **Reasoning:** Finding references `src/cryq/...` (wrong path, missing `odaq`). The concern
  about `prefix = f"{self._brand_base} {prefix_suffix}:"` when prefix_suffix="" producing
  "Гемма :" — but actual code has `if prefix_suffix: ... else: prefix = self._prefix` guard
  so empty prefix_suffix falls back to stored self._prefix. The loop behavior (repeating
  identical finding 24+ times) is a catastrophic quality failure.

---

### Kimi-K2.6

#### F-K-1 [LOW] GUI insight missing prefix_suffix
- **Architect verified:** REAL (duplicate of CF-4)
- **Notes:** Kimi identified this while explicitly noting the diff was truncated. Excellent.

#### F-K-2 [LOW] window_minutes int truncation concern
- **Architect verified:** AMBIGUOUS/LOW (same as Q-2 assessment)

#### F-K-TDA-1 [→TDA] Exception handling concern
- **Architect verified:** TRUNCATED_DIFF_ARTIFACT
- **Notes:** Kimi explicitly flagged it could not see the full function body and marked
  this as "uncertain" rather than a confirmed finding. Best truncation-awareness behavior
  in this session.

---

### Gemini-2.5-Pro

#### F-G-1 [HIGH→TDA] Exception handling missing in _periodic_report_tick
- **Architect verified:** TRUNCATED_DIFF_ARTIFACT
- **Reasoning:** Code has `except Exception as exc: logger.error(...)` inside while loop.
  Not visible in truncated diff. Gemini hallucinated absence from partial view.

#### F-G-2 [MEDIUM→TDA] No LIMIT on DB queries in build_periodic_report_context
- **Architect verified:** TRUNCATED_DIFF_ARTIFACT
- **Reasoning:** Code has `limit=50` at context_builder.py:128. Not visible in truncated
  diff. Gemini hallucinated absence from partial view.

---

### R1-0528
- **Verdict:** TRUNCATED — 107B response, cut off at "src/cryodaq/agents/ass". Raw JSON
  file not present in .swarm/tmp (likely timing issue). No usable content.

### MiniMax-M2.5
- **Verdict:** JUNK — returned tool-call JSON instead of text review. Model attempted to
  call `read_file` tools which are not available in the Chutes invocation context.

### Chimera-R1T2
- **Verdict:** API_ERROR — "Infrastructure is at maximum capacity, try again later"

---

## Convergent findings (>1 model identified)

- **GUI_INSIGHT missing prefix_suffix** (CF-4): Codex, GLM, Qwen, Kimi all identified.
  REAL finding, confirmed. 4/7 valid models.
- **Exception handling concern** (TDA): Gemini, Qwen, Kimi, GLM all flagged.
  TRUNCATED_DIFF_ARTIFACT — code addresses it. Mass false positive from truncated diff.
- **LaTeX/Telegram concern** (CF-5): Codex, GLM flagged. REAL, architect-known issue.

---

## Unique findings (only Codex, based on file reads)

- CF-1: Rate limit race (MEDIUM) — requires reading actual agent.py logic
- CF-2: SQLite failure silent suppression (MEDIUM) — requires reading context_builder.py
- CF-3: Phase tag mismatch (LOW) — requires reading engine.py:1724

---

## HALLUCINATION_ECHO findings (re-reporting already-fixed)

None. All 7 valid models respected the stop-list and did not re-report the 3 pre-fixed
issues (hardcoded "последний час", calibration bucketing, smoke CancelledError).
Stop-list compliance: 7/7 valid models.

---

## Notable model behaviors this session

- **Kimi-K2.6**: Contrary to ORCHESTRATION §17.4 ("Skip in routine dispatch"), Kimi
  responded with 35KB in ~3min. Long-prompt instability appears improved. Positive signal.
- **Qwen3-Coder-Next**: Severe loop malfunction — Finding 5 (prefix_suffix) repeated
  24 times with degrading file path (src/cryq/... instead of src/cryodaq/...). This is a
  new negative pattern not previously observed. Quality has deteriorated since pilot T3.
- **GLM-5.1**: Response truncated before formal verdict. With max_tokens=8192, still ran
  out of tokens for a 37KB response. Needs higher budget for this task class.
- **Gemini-2.5-Pro**: Both findings were TRUNCATED_DIFF_ARTIFACT. Gemini's structural
  analysis strength was limited by the truncated diff — it extrapolated from partial view
  rather than speculating broadly. Behavior is principled but input was insufficient.
- **R1-0528**: API response truncated to 107B. Raw JSON file missing. Infrastructure
  issue at dispatch time.
- **rtk diff compression**: IMPORTANT — rtk hook intercepted `git diff` and produced
  ~20KB compressed output instead of ~125KB full patch. This caused mass TRUNCATED_DIFF_ARTIFACT
  findings across all Chutes models. Future audit sessions should use
  `rtk proxy git diff ...` or write diff from `.worktrees/` directly to bypass rtk.

---

## ARCHITECT DECISION NEEDED markers

### ADB-1: CF-2 fix scope before merge?
Context: SQLite failure during context build suppresses the hourly report silently.
Options:
  A. Fix before merge — change logger.debug → logger.warning + skip idle-check on context error
  B. Track as post-merge improvement — accept that storage faults silence the report for now
  C. Minimal fix — logger.warning only, keep idle-skip behavior
Default if no response: B (accept for now, track)
Urgency: Non-blocking

### ADB-2: CF-3 fix scope before merge?
Context: Phase tag mismatch means phase section always empty. 1-line fix.
Options:
  A. Fix before merge — add "phase" to phase_entries filter in context_builder.py
  B. Accept as low-pri — phase section is new feature, "(нет)" is acceptable for now
Default if no response: A (fix — it's trivial)
Urgency: Non-blocking

### ADB-3: CF-4 intentional or oversight?
Context: GUI insight panel receives raw llm_output without brand prefix or "(отчёт за час)" label.
Options:
  A. Intentional — GUI panel has its own header rendering from event_type field
  B. Oversight — fix by passing `prefixed` to GUI payload
Default if no response: A (likely intentional per prior GUI design)
Urgency: Non-blocking

---

## Architect verdict on F29 ratification

**PASS_RATIFIED**

Reasoning: No architect-verified CRITICAL or HIGH findings beyond the 3 pre-audit
self-audit fixes. Codex (the authoritative verifier reading actual files) found:
- 2 MEDIUM issues (rate limit race, SQLite silent suppression)
- 3 LOW issues (phase tag, GUI prefix, LaTeX)

None of these block correctness of the feature. F29 ships correctly for the happy path
(hourly report generated, dispatched to Telegram + log + GUI when events present).
The identified issues are quality/reliability improvements suitable for post-merge cycle.

EXCEPTION: If architect chooses to fix CF-3 (phase tag) before merge — that's a
1-line fix and recommended. No re-audit needed for a single-line tag addition.
