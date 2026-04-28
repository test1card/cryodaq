# CC task — full vault audit pass (Codex + Gemini, architect-reviewed)

**Authored:** 2026-04-27 by Vladimir + web Claude (architect).
**Target:** `~/Vault/CryoDAQ/` as it currently exists (49 notes, 303 wikilinks per
overnight build handoff).
**Pattern:** parallel adversarial audit by Codex AND Gemini → CC consolidates →
architect reviews findings → architect decides per-finding (fix / dispute / defer).
**NOT this session:** autonomous fixes. CC presents findings, architect drives action.
**Duration estimate:** 60-90 min.

---

## 0. Pre-flight (5 min)

- Verify vault exists: `obsidian:list_files` on `CryoDAQ/`. Expect 9 folders + README.
- Verify Codex available: `codex --version` (expect 0.124.0+).
- Verify Gemini available: `gemini --version` (expect 0.38.2+).
- Read overnight handoff:
  `~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md`
  for context on what was built and what was deferred.
- Read vault build log:
  `~/Vault/CryoDAQ/_meta/build log.md`
  for the 1-iter quiescence history.

If any pre-flight fails: STOP, write
`~/Projects/cryodaq/artifacts/vault-audit/2026-04-27/0-preflight-fail.md`.

---

## 1. Dispatch Codex (literal verifier) — parallel with Phase 2

Brief: `~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.prompt.md`

```markdown
Model: gpt-5.5
Reasoning effort: high

# Full-vault audit — Codex literal verifier (post-build)

## Mission
Read every markdown note under ~/Vault/CryoDAQ/ except `_meta/`. For each
factual claim that has a `source:` reference in the note's frontmatter,
cross-reference the claim against the actual repo file. Flag what's
factually wrong.

This is post-build verification. The vault was built overnight 2026-04-26
and passed self-driven audit gates during build. This pass is independent
adversarial review on the full integrated artifact.

## Scope of vault to audit
- ~/Vault/CryoDAQ/00 Overview/*.md (3 notes)
- ~/Vault/CryoDAQ/10 Subsystems/*.md (6 notes — Web/Cooldown/Experiment/Interlock deferred, not present)
- ~/Vault/CryoDAQ/20 Drivers/*.md (3 notes)
- ~/Vault/CryoDAQ/30 Investigations/*.md (6 notes)
- ~/Vault/CryoDAQ/40 Decisions/*.md (~7 notes)
- ~/Vault/CryoDAQ/50 Workflow/*.md (4 notes)
- ~/Vault/CryoDAQ/60 Roadmap/*.md (2-3 notes)
- ~/Vault/CryoDAQ/README.md
- skip 90 Archive/ (intentionally empty)
- skip _meta/ (build log + glossary + source map are CC-internal)

## Source files in repo for cross-reference
- ~/Projects/cryodaq/CLAUDE.md
- ~/Projects/cryodaq/PROJECT_STATUS.md
- ~/Projects/cryodaq/ROADMAP.md
- ~/Projects/cryodaq/CHANGELOG.md
- ~/Projects/cryodaq/docs/decisions/*.md
- ~/Projects/cryodaq/docs/ORCHESTRATION.md
- ~/Projects/cryodaq/.claude/skills/*.md
- ~/Projects/cryodaq/src/cryodaq/core/safety_manager.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py
- ~/Projects/cryodaq/src/cryodaq/analytics/base_plugin.py
- ~/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_v2.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_config.py
- ~/Projects/cryodaq/config/instruments.yaml
- ~/Projects/cryodaq/config/alarms_v3.yaml
- ~/Projects/cryodaq/config/safety.yaml
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/keithley_2604b.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
- (read additional files as cited by individual notes' source: headers)

## Severity scale (use exactly these labels)
- CRITICAL: claim contradicts source code or repo doc
  (homoglyph-class — actively wrong)
- HIGH: claim is overstatement vs source
  (technically partial-true but reader will draw wrong conclusion)
- MEDIUM: claim is true but missing important caveat
- LOW: minor wording / clarity / style
- DEFERRED-COVERAGE: source declares something exists that vault has
  zero mention of (only when totally absent — for partial coverage use HIGH)

## What NOT to flag
- Stylistic preferences (prose density, paragraph length, voice)
- Information density: vault is digest by design, not exhaustive mirror
- Structural choices (folder layout, ADR template choice — CC's domain)
- "I would have written it differently" — only flag what's WRONG
- Coverage gaps already deferred per
  ~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md
  §"Deferred coverage gaps" (4 specific notes — Web/Cooldown/Experiment/Interlock)

## Output format

```
## Finding NN
**Severity:** CRITICAL | HIGH | MEDIUM | LOW | DEFERRED-COVERAGE
**Vault file:** path/to/note.md
**Vault line(s):** line numbers (or section heading)
**Source file:** ~/Projects/cryodaq/path/to/source
**Source line(s):** line numbers
**Claim in vault:** "exact quote from vault"
**What source says:** "exact quote from source OR plain statement of source state"
**Why this is wrong:** 1-2 sentences
**Suggested fix:** specific text replacement OR "remove sentence" OR "add caveat: ..."
```

After all findings:

```
## Verdict
- Total findings: N
- By severity: CRITICAL=A HIGH=B MEDIUM=C LOW=D DEFERRED=E
- PASS / FAIL / CONDITIONAL with one-sentence reason

## Confidence notes
- Areas where you weren't sure / source was ambiguous / 30-second-rule cases
```

Hard cap: **5000 words total**. Prefer specificity over volume —
better 10 well-cited findings than 30 noise.

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.response.md
```

Dispatch:
```bash
mkdir -p ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit
nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox read-only --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.prompt.md \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.response.md 2>&1 &
echo "Codex PID: $!"
```

(Same flag pattern that worked overnight per build log.)

---

## 2. Dispatch Gemini (structural auditor) — parallel with Phase 1

Brief: `~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.prompt.md`

```markdown
Model: gemini-3.1-pro-preview

# Full-vault audit — Gemini structural auditor (post-build)

## Mission
Read all 49 notes under ~/Vault/CryoDAQ/ in 1M-context single pass.
Skim repo source tree at ~/Projects/cryodaq/ for context. Find
STRUCTURAL issues across the whole vault: cross-note inconsistencies,
gaps where notes should link but don't, drift between vault claims
and current repo state, areas where the picture-as-a-whole is
misleading even if individual statements are technically correct.

This complements Codex's line-by-line check. DO NOT repeat Codex's
work. Look at coherence, completeness, and the overall picture.

## Notes to read (use 1M generously)
All ~49 notes under ~/Vault/CryoDAQ/. Skip _meta/build log.md
(self-referential — describes the build, not the project).

## Repo for context
- ~/Projects/cryodaq/CLAUDE.md (canonical project overview)
- ~/Projects/cryodaq/PROJECT_STATUS.md (current status snapshot)
- ~/Projects/cryodaq/ROADMAP.md (planned work + F-table)
- ~/Projects/cryodaq/CHANGELOG.md (history)
- ~/Projects/cryodaq/src/cryodaq/ (full tree, read what looks relevant)
- ~/Projects/cryodaq/docs/decisions/ (full directory)
- ~/Projects/cryodaq/.claude/skills/

## Severity scale (use exactly these labels)
- DRIFT: vault claims about the repo's current state are out-of-date
  (repo evolved, vault didn't catch up)
- INCONSISTENT: Note A says X, Note B says ~X (internal contradiction)
- GAP: a subsystem clearly visible in repo source has zero or near-zero
  mention in vault (NOT one of the 4 already-deferred notes —
  Web/Cooldown/Experiment/Interlock)
- MISLEADING: each individual statement is defensible, but combined
  reading of multiple notes paints a wrong picture
- DEAD-END: a wikilink resolves but the target note is empty / stub /
  obviously incomplete

## What NOT to flag
- Per-note line-level factual errors (Codex covers those)
- Style / voice / wording preferences
- Information density (vault is digest by design)
- Structural choices CC made deliberately (folder layout, ADR template)
- The 4 already-deferred subsystem notes per overnight handoff §"Deferred coverage gaps"

## Output format
**Single markdown table, no preamble.**

| # | Type | Notes affected | What's wrong | Suggested fix |
|---|---|---|---|---|

After table, 3-5 sentences max:
- Coherence verdict: COHERENT / GAPS / DRIFT / INCONSISTENT
- Top 3 most important findings (rank by how much they hurt KB usability)
- Anything CC did exceptionally well that should be repeated in future builds

Hard cap: **2000 words total**. Table-first. NO long prose intro.
NO "I will analyze..." preamble. Start with the table.

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.response.md
```

Dispatch:
```bash
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.prompt.md)" \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.response.md 2>&1 &
echo "Gemini PID: $!"
```

---

## 3. Wait + monitor (15-30 min)

Both verifiers running in background. Wait up to 45min for both. Monitor:

```bash
# Periodically check sizes
ls -la ~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/
```

If a response file stops growing for 5 min after >2 min runtime → likely
done. Check tail to confirm structured output present.

If 45 min elapsed and one still running:
- Check process: `ps aux | grep -E "codex|gemini"`
- If alive but unresponsive: kill, mark TIMEOUT, proceed with whichever
  finished
- If both timeout: write `1-both-timeout.md` with debug info, STOP

---

## 4. CC consolidation (Sonnet OK, ~15 min)

Once both responses landed:

Read Codex response via `tail -300` (per skill §1 response-size gotcha).
Read Gemini response in full (compact format).

Build consolidation file:
`~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-audit-handoff.md`

Structure:

```markdown
# Vault audit findings — 2026-04-27

**Audit window:** HH:MM — HH:MM
**Codex:** PASS / FAIL / CONDITIONAL — N findings (CRITICAL=A HIGH=B MEDIUM=C LOW=D)
**Gemini:** COHERENT / GAPS / DRIFT / INCONSISTENT — M findings

## Summary table

For each finding from Codex AND Gemini, single row:

| # | Source | Severity | Vault file | What's wrong | Suggested fix | CC pre-assessment |
|---|---|---|---|---|---|---|

CC pre-assessment column: one of
- "AGREE" — finding looks correct on its face, fix should land
- "PARTIAL" — finding has merit but suggested fix may overshoot, needs architect call
- "DISPUTE" — CC reads source differently from verifier, evidence inline
- "DEFERRED" — finding matches a coverage gap already deferred, mark and move on
- "OUT-OF-SCOPE" — finding is style/density/structural preference, not actionable

## Convergent findings (both verifiers flagged same issue)

If Codex finding #X and Gemini finding #Y address the same vault problem
from different angles → high confidence, list separately:

- Convergent #1: <description> — Codex #X (CRITICAL) + Gemini #Y (DRIFT)
- ...

## CC dispute notes

Per finding marked DISPUTE, one paragraph explaining what CC found in
the source that contradicts the verifier's reading. With file:line refs.

## Top architect priorities

CC's read on what architect should fix first, ordered:

1. <highest-impact finding> — <one-sentence why>
2. ...
3. ...

## What does NOT need architect attention

- LOW findings (architect can decide bulk-accept or bulk-ignore)
- Already-deferred coverage gaps

## Open architect decisions

Specific decisions CC can't make alone:
- <decision 1> — <options>
- ...
```

Hard cap: **2000 words** for the handoff itself. Findings table is the
primary content; CC commentary should be compact.

---

## 5. Wait — do NOT fix (architect-driven from here)

After consolidation handoff written:

CC sends final report:
- Audit complete
- Handoff path
- Counts (Codex N, Gemini M, convergent K)
- Top 3 architect priorities (1-line each)
- Question to architect: "Approve fixes one-by-one, or batch by severity?"

Then **STOP**. No vault edits this session. Architect decides next steps:
- Fix specific findings → new prompt with fix list
- Dispute findings → architect ledgers the disagreement
- Defer everything → close handoff, move on
- Trigger deferred 4 subsystem notes draft → separate prompt

---

## 6. Hard stops

CC stops AND wakes architect (writes
`~/Projects/cryodaq/artifacts/vault-audit/2026-04-27/STOP.md`) if:

- Codex returns slop (per skill §4.2: <500 words actual content,
  no file:line refs, evades severity rubric)
- Gemini returns prose-wall instead of table after explicit instruction
- Both verifiers timeout simultaneously (suggests env issue, not audit issue)
- Vault state changed mid-audit (note count shifts, wikilinks break) —
  someone else editing vault, abort
- Findings count exceeds 100 from either verifier — likely audit went
  off the rails, abort and re-brief

---

## 7. NOT in scope this session

- No vault edits
- No fixing findings
- No commits to repo
- No drafting deferred subsystem notes (Web/Cooldown/Experiment/Interlock)
- No re-running of overnight build phases
- No skill / ORCHESTRATION updates (architect's domain)
- No git operations

---

## 8. Summary execution order

```
Pre-flight (5 min) →
  Phase 1 + Phase 2 PARALLEL dispatch (Codex + Gemini)
  Wait 15-30 min for both responses
  Phase 4: CC consolidation (~15 min)
  Phase 5: STOP, await architect decision
```

Total estimate: 60-90 min wall-clock, with most of that being
verifier runtime in parallel.

---

*Spec written 2026-04-27 by web Claude (architect). Verifier-driven
audit, architect-driven action. Pure verification this session.*
