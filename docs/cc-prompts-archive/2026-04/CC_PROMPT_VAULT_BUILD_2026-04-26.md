# CC overnight task — build CryoDAQ knowledge base in Obsidian vault

**Authored:** 2026-04-26 by Vladimir + web Claude (architect).
**Target:** Obsidian vault at `~/Vault/`. Top-level folder `CryoDAQ/`.
**Pattern:** self-recurring loop (seed → audit → fix → audit → ... → quiescence → polish).
**Models:** Sonnet for mechanical phases, Opus for synthesis phases.
Verifiers: Codex (`gpt-5.5 high`) AND Gemini (`gemini-3.1-pro-preview`)
in parallel — both are paid, both should work nights, no point letting
either idle. If either or both unavailable: continue without that
verifier, mark affected phases UNVERIFIED-by-X in ledger.
**Duration cap:** 8 hours wall-clock. Hard stop at 06:00 Moscow even if
loop hasn't quiesced. **The whole point is filling overnight hours
productively** — keep working as long as anything useful is being produced.

---

## 0. Pre-flight checks (10 min, must pass)

Before any vault writes:

- Verify Obsidian MCP tools available. Test: list top-level vault contents.
  Expected: folders (`Soban Soundbar`, `Tags`, `projects`) + `README.md`.
  If tools missing → STOP, write `~/Projects/cryodaq/artifacts/vault-build/0-preflight-fail.md`
  describing what's missing.

- Verify `~/Vault/CryoDAQ/` does NOT exist yet. If it does, list its contents
  and STOP with `0-preflight-collision.md`. Architect decides whether to
  merge, archive, or rename.

- Verify Codex available. Run `codex exec -m gpt-5.5 -c model_reasoning_effort=high`
  with trivial probe ("respond OK"). If Codex unavailable → continue without
  Codex audits, mark phase outputs UNVERIFIED-by-Codex in ledger.

- Verify Gemini available. Run `gemini -m gemini-3.1-pro-preview -p "respond OK"`.
  If Gemini unavailable → continue without Gemini audits, mark
  UNVERIFIED-by-Gemini. **If both Codex AND Gemini unavailable**:
  continue building without verification, mark all phases UNVERIFIED,
  produce vault content anyway. Architect validates morning.

- Verify Filesystem MCP can read `~/Projects/cryodaq/`. Test: `list_directory`
  on `src/cryodaq/`. Required because vault notes synthesize from repo.

If all checks complete: log `~/Projects/cryodaq/artifacts/vault-build/0-preflight-ok.md`
with timestamp + tool inventory + Codex/Gemini availability flags,
proceed to Phase 1.

---

## 1. Skeleton creation (Sonnet, ~15 min)

`/model claude-sonnet-4-6` (or current Sonnet identifier)

Create the following directory structure under `~/Vault/CryoDAQ/`:

```
CryoDAQ/
├── README.md
├── 00 Overview/
├── 10 Subsystems/
├── 20 Drivers/
├── 30 Investigations/
├── 40 Decisions/
├── 50 Workflow/
├── 60 Roadmap/
├── 90 Archive/
└── _meta/
```

Use Obsidian MCP tools (`obsidian:create_file` with empty stub or
folder-creation equivalent). One file per directory to make the folder
exist if folder-only creation isn't supported — name them `_index.md`
with single line: `# <Folder name>` and a TODO comment.

Write `~/Vault/CryoDAQ/README.md`:

```markdown
# CryoDAQ knowledge base

Source-of-truth synthesis of the CryoDAQ project (Millimetron / АКЦ ФИАН
cryogenic laboratory instrument stack). Authoritative repository lives
at `~/Projects/cryodaq/`. This vault is a derived integration layer:
narrative explainers, investigation history, decision rationale, glossary.

If this vault and the repo conflict — the repo wins. Vault notes carry
a `source:` and `last_synced:` header to make staleness visible.

## Navigation

- `00 Overview/` — what is CryoDAQ, who, why, hardware
- `10 Subsystems/` — engine, GUI, ZMQ, safety, calibration, alarms
- `20 Drivers/` — instrument-specific notes (LakeShore, Keithley, Thyracont)
- `30 Investigations/` — bug histories with hypothesis trees (B1, b2b4fb5)
- `40 Decisions/` — ADRs (architectural decision records)
- `50 Workflow/` — orchestration contract, multi-model consultation, calibration loops
- `60 Roadmap/` — versions, F-table backlog, open questions
- `90 Archive/` — superseded designs, dropped hypotheses, pre-rewrite LabVIEW
- `_meta/` — glossary, source map, update protocol

Built by Claude Code overnight 2026-04-26 from CC_PROMPT_VAULT_BUILD_2026-04-26.md.
```

Write `~/Vault/CryoDAQ/_meta/glossary.md` with seed entries (will be
expanded in Phase 2):

- B1 — ZMQ command channel idle-death bug, ~80s uptime, cmd plane only
- IV.N — Investigation/Infrastructure batch number N (IV.4..IV.7 known)
- F1..F18 — Feature numbers from ROADMAP.md F-table
- H1..H5 — Hypotheses for B1 root cause (H1, H2, H3 falsified; H4
  partially consistent; H5 untested)
- ADR — Architecture Decision Record
- FSM — Finite State Machine (specifically SafetyManager's 6-state)
- SRDG — Sensor Raw Data Grabbing (calibration v2 acquisition mode)
- KRDG — Kelvin Reading (LakeShore command for calibrated temperature)

After skeleton landed, log `~/Projects/cryodaq/artifacts/vault-build/1-skeleton-ok.md`.

**No verifier audit on Phase 1** — pure mechanical. Skip directly to Phase 2.

---

## 2. Reference page seed (Sonnet, ~45 min)

These pages mirror existing repo content with light reformatting.

### 2.1 — `00 Overview/Hardware setup.md`

Source: `CLAUDE.md` "Физическая установка" + `config/instruments.yaml`.

- Table: Instrument | Interface | Channels | Driver file
- One paragraph per instrument with `[[20 Drivers/...]]` link

Header:

```yaml
---
source: CLAUDE.md, config/instruments.yaml
last_synced: 2026-04-26
status: synthesized
---
```

### 2.2 — `00 Overview/What is CryoDAQ.md`

Source: `CLAUDE.md` opening + `README.md` + `PROJECT_STATUS.md`.

Sections: What it is / What it does / Where it runs / Who maintains
it / Scale (LOC, tests, instruments — pull current numbers via
`pytest --collect-only` and `wc -l`).

### 2.3 — `00 Overview/Architecture overview.md`

Source: `CLAUDE.md` "Архитектура" + `PROJECT_STATUS.md` "Архитектура".

Three runtime contours (engine / GUI / web) with ZMQ topology.
Persistence-first ordering diagram verbatim. Cross-link to subsystem
pages.

### 2.4 — `60 Roadmap/Versions.md`

Source: git tags + `CHANGELOG.md` + `PROJECT_STATUS.md`.

Table: Version | Date | Status | Scope summary | Closing commit.

Note pending retroactive tags (v0.34.0..v0.38.0 plan from
`docs/decisions/2026-04-23-cleanup-baseline.md`).

### 2.5 — `60 Roadmap/F-table backlog.md`

Source: `ROADMAP.md` F-table. Render as table with status emoji.
F1, F2, F6, F11 = ✅ shipped in IV.4. Rest = ⬜ queued or 🔬 research.

### 2.6 — `40 Decisions/` — one ADR per existing decision file

Source: `docs/decisions/*.md`. Render in standard ADR format:

```markdown
---
source: docs/decisions/<original-name>.md
adr_id: ADR-NNN
date: <from filename>
status: accepted | superseded | proposed
---

# ADR-NNN — <title>

## Context
## Decision
## Consequences
## Status
```

Don't invent ADRs. One file in repo → one ADR in vault.

After 2.x complete: log `2-reference-ok.md`.

**Audit gate after Phase 2** — Codex + Gemini parallel, see Section 6.

---

## 3. Synthesis pages (Opus, ~90 min)

`/model claude-opus-4-7` (or current Opus identifier)

These pages require judgment. Not pure mirror.

### 3.1 — `10 Subsystems/Safety FSM.md`

Source: `src/cryodaq/core/safety_manager.py`, `CLAUDE.md` safety section,
`PROJECT_STATUS.md` invariants.

Cover: problem solved (single authority for source on/off) / 6 states
with transitions / fail-on-silence mechanism / rate limit (5 K/min) /
crash-recovery guard at Keithley connect / what's NOT here (no firmware
TSP watchdog, planned future).

### 3.2 — `10 Subsystems/ZMQ bridge.md`

Source: `src/cryodaq/core/zmq_bridge.py`, `core/zmq_subprocess.py`,
`CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `docs/bug_B1_zmq_idle_death_handoff.md`.

Cover: PUB/SUB :5555 / REP/REQ :5556 / subprocess isolation (engine
survives GUI crash) / IV.6 ephemeral REQ / watchdog with 60s cooldown /
TCP_KEEPALIVE only on data-plane SUB / IV.7 ipc:// experiment outcome /
B1 status link.

### 3.3 — `10 Subsystems/Persistence-first.md`

Source: `CLAUDE.md` persistence section, `core/scheduler.py`,
`PROJECT_STATUS.md` invariant 2.

Cover: invariant in plain English / why it matters (post-mortem
reconstruction) / implementation / GUI latency tradeoff / WAL
verification on startup.

### 3.4 — `10 Subsystems/Calibration v2.md`

Source: `analytics/calibration.py`, `analytics/calibration_fitter.py`,
`core/calibration_acquisition.py`, `CLAUDE.md` calibration, README.

Cover: three-mode flow / continuous SRDG acquisition / extract →
downsample → breakpoints → Chebyshev fit pipeline / output formats:

  - `.330` and `.340` — both LakeShore controller calibration table
    formats. Both contain sampled curve breakpoints, NOT polynomial
    coefficients.
  - JSON — internal CryoDAQ format with Chebyshev coefficients per
    zone, metrics, source session IDs, metadata.
  - **Pending**: `.cof` format for raw Chebyshev coefficient export
    (architect-decided 2026-04-25, not yet implemented; `.330` to be
    removed when `.cof` lands).

Runtime apply policy (per-channel inherit/off/on).

### 3.5 — `10 Subsystems/Alarm engine v2.md`

Source: `core/alarm_v2.py`, `core/alarm_config.py`, `config/alarms_v3.yaml`.

Cover: YAML-driven config / phase-aware / composite conditions /
Cyrillic Т homoglyph regression (link to investigation page) / known
issue: `cooldown_stall` `threshold` KeyError (Codex-04 patch pending).

### 3.6 — `10 Subsystems/Plugin architecture.md`

Source: `analytics/base_plugin.py`, `analytics/plugin_loader.py`.

Cover: AnalyticsPlugin ABC / hot-reload from `plugins/` / exception
isolation / history (original direct-import → plugin crash → rebuild
with isolation, link to investigation page).

### 3.7..3.9 — `20 Drivers/<instrument>.md` (3 pages)

LakeShore 218S, Keithley 2604B, Thyracont VSP63D.

Per driver: interface / channels / protocol style / reconnect strategy /
notable quirks (Thyracont V1/V2 checksum, Keithley `\x00` in VISA,
LakeShore daisy-chain) / crash-recovery (Keithley OUTPUT_OFF on connect).

### 3.10..3.15 — `30 Investigations/` (6 pages)

Each: timeline + hypothesis tree + current status.

- `B1 ZMQ idle-death.md` — primary big bug. Source:
  `docs/bug_B1_zmq_idle_death_handoff.md`. H1 falsified, H2 falsified
  (IV.6 fixed shared REQ but bug remained), H3 partial (ipc:// works
  briefly but B1 still fires after ~80s), H4 partially consistent
  (D2 experiment pending), H5 untested.

- `b2b4fb5 hardening race.md` — misattribution story. Source:
  `docs/decisions/2026-04-24-b2b4fb5-investigation.md`. IV.7 was blamed
  for runtime failure actually caused by b2b4fb5 hardened probe racing
  engine bind. R1 bounded-backoff retry was fix.

- `Cyrillic homoglyph in alarm config.md` — short story. LLM generated
  YAML with Latin "T" instead of Cyrillic "Т". Tests passed (logic
  was correct). Caught by second-model audit. Regression test added.

- `Codex H2 wrong hypothesis.md` — adversarial review counter-example.
  Codex confidently identified shared REQ state with file:line refs.
  Implementation = IV.6. Bug stayed. Hypothesis was wrong despite clean
  reasoning. Diagnostic re-run falsified. Lesson: tests > model
  confidence.

- `Plugin isolation rebuild.md` — original direct-import architecture
  led to engine crash when plugin threw. Rebuilt with ABC + try-except.

- `IV.6 cmd plane hardening.md` — what shipped + what it didn't fix.
  Source: `CHANGELOG.md` + commit `be51a24`.

### 3.16..3.18 — Three new ADRs

`40 Decisions/ADR-001 Persistence-first invariant.md`,
`ADR-002 R1 bounded-backoff probe retry.md`,
`ADR-003 Plugin isolation via ABC.md`.

Synthesized from history because no committed ADR exists yet.

### 3.19 — `50 Workflow/ORCHESTRATION contract.md`

Source: `docs/ORCHESTRATION.md` v1.1. Digest version — section headers
+ 1-paragraph summary per section. Detail goes to repo doc.

### 3.20 — `50 Workflow/Multi-model consultation.md`

Source: `.claude/skills/multi-model-consultation.md`. Same digest pattern.

### 3.21 — `50 Workflow/Overnight swarm pattern.md`

Source: `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md` + outcome
(`docs/decisions/2026-04-24-overnight-swarm-launch.md` + synthesis files).

When pattern fits, sample task structure, what worked 2026-04-24
(10/10 jobs), what didn't (Gemini parallel hit quota, serial chain
workaround).

### 3.22 — `50 Workflow/Calibration loops history.md`

Meta-narrative: how prompts and CC behavior evolved from "lots of
stops" to "autonomy band". Source: `docs/decisions/` ledgers from
2026-04-23 onward, ORCHESTRATION.md §12 + §13.

5-6 calibration loops:
1. STOP discipline (stops on every mismatch → autonomy band)
2. Recon before plan
3. Model version drift (hardcoded → fallback rules)
4. Tool call budget (web Claude editing files → CC owns edits)
5. Skill loading lifecycle (mid-session add → manual Read workaround)

After 3.x complete: log `3-synthesis-ok.md`.

**Audit gate after Phase 3** — Codex + Gemini parallel.

---

## 4. Cross-link pass (Sonnet, ~30 min)

`/model claude-sonnet-4-6`

Goals:
- Every `[[wikilink]]` resolves to existing note
- Every note has at least one inbound link
- Glossary terms linked at first use per note

Steps:
1. List all notes via Obsidian MCP. Build link graph.
2. Find broken `[[wikilinks]]`. Either fix link to match existing, or
   add to deferred list if target genuinely missing.
3. Find isolated notes. Add reverse links from index notes.
4. Grep glossary terms across notes, replace unlinked first occurrence
   with `[[_meta/glossary#<term>|<term>]]`.

Output: `_meta/source map.md` listing every note with file path /
source files in repo / last sync date / inbound link count / outbound
link count.

After complete: log `4-crosslink-ok.md`.

**Audit gate after Phase 4** — Codex + Gemini parallel.

---

## 5. Update protocol document (Opus, ~15 min)

`/model claude-opus-4-7`

Write `_meta/update protocol.md`:

When CC should update vault from CC sessions:
- TRIGGER: CLAUDE.md modified → update affected `00 Overview/` or `10 Subsystems/`
- TRIGGER: New file in `docs/decisions/` → create `40 Decisions/` ADR
- TRIGGER: Investigation closes → create or update `30 Investigations/`
- TRIGGER: ROADMAP F-table status change → update `60 Roadmap/F-table backlog.md`
- TRIGGER: New skill in `.claude/skills/` → digest into `50 Workflow/`
- NOT a trigger: every commit (too noisy)
- NOT a trigger: personal session ledgers (those stay in repo)

Specify staleness check: every note's `last_synced:` should be within
30 days of relevant repo changes. Older = stale flag in source map.

After complete: log `5-protocol-ok.md`.

---

## 6. Audit gates — Codex AND Gemini in parallel (run after Phase 2, 3, 4)

**Two verifiers, different strengths, dispatched in parallel:**

- **Codex (gpt-5.5 high)** — literal verifier. Checks claims-vs-source
  with file:line precision. Strong on factual correctness, narrow
  contradictions, technical accuracy. Tends to be very literal — that
  literalism can conflict with vault's digest-style writing. CC owns
  override decision.

- **Gemini (3.1-pro-preview)** — wide-context auditor. 1M context
  reads many notes at once, checks cross-note inconsistencies,
  doc-vs-code drift, structural gaps. Strong on "is the picture
  coherent" rather than "is this exact line correct." Verbose — needs
  output cap.

Both dispatched simultaneously via `nohup ... &`. Don't wait for one
before launching other. CC reads both responses when they land.

### 6.1 — Codex audit dispatch

Brief at:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-NN-<phase>.prompt.md`

```markdown
Model: gpt-5.5
Reasoning effort: high

# Vault audit — Phase N (Codex literal verifier)

## Mission
Verify factual accuracy of vault notes created in Phase N. Read each
note + cross-reference against source files declared in note headers.
Flag what's wrong.

## Notes to audit
<list of paths in ~/Vault/CryoDAQ/>

## Source files for verification
<list of paths in ~/Projects/cryodaq/>

## What to flag (CRITICAL/HIGH/MEDIUM/LOW)
- CRITICAL: claim contradicts source code or repo doc (homoglyph-class)
- HIGH: claim is overstatement vs what source supports
- MEDIUM: claim is true but missing important caveat
- LOW: minor wording/clarity

## What NOT to flag
- Stylistic preferences
- Information density (vault is digest by design)
- Structural choices (CC's domain)
- Things "you would have written differently" — only WRONG things

## Output
- Per finding: severity / vault file:line / source file:line / fix
- Verdict: PASS / FAIL / CONDITIONAL
- Max 3000 words

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-NN-<phase>.response.md
```

Dispatch:
```bash
nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox workspace-read \
  < <prompt-file> > <response-file> 2>&1 &
```

### 6.2 — Gemini audit dispatch (parallel with Codex)

Brief at:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/gemini-NN-<phase>.prompt.md`

```markdown
Model: gemini-3.1-pro-preview

# Vault audit — Phase N (Gemini wide-context auditor)

## Mission
Read all vault notes from Phase N + skim repo source for context.
Find STRUCTURAL issues: cross-note inconsistencies, gaps where notes
should link but don't, drift between vault claims and repo state,
areas where the picture-as-a-whole is misleading even if individual
statements are technically correct.

This complements Codex's line-by-line check. Don't repeat Codex.
Look at coherence and completeness.

## Notes to read (use 1M context generously)
<list of vault paths>

## Repo files for context
<list of repo paths — feel free to read whole src/cryodaq tree>

## What to flag
- Cross-note contradiction (Note A says X, Note B says ~X)
- Missing link (Note A clearly references concept Y, no link to its note)
- Coverage gap (subsystem visible in repo, no note in vault)
- Misleading picture (each statement defensible, combined effect wrong)
- Outdated claim (vault says X about repo, repo currently shows ~X)

## What NOT to flag
- Per-note line-level factual errors (Codex covers those)
- Style/voice preferences
- Information density
- Structural choices CC made deliberately

## Output format
- Single markdown table: Issue type | Notes affected | What's wrong | Suggested fix
- Max 2000 words. NO long prose intro. Table-first.
- Verdict at end: COHERENT / GAPS / DRIFT

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/gemini-NN-<phase>.response.md
```

Dispatch:
```bash
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat <prompt-file>)" > <response-file> 2>&1 &
```

(Gemini --yolo: auto-approve tool use. Vault audit doesn't need
interactive gates.)

### 6.3 — CC reads BOTH responses, decides

Wait for both to land (or 45min timeout each, whichever first). Read
Codex via `tail -300`, Gemini via full read.

For each finding from either model:

**CRITICAL** (Codex): fix immediately. Edit note, update `last_synced:`.

**HIGH** (Codex) or **DRIFT** (Gemini structural): fix if defensible.
If model's claim is questionable or matter-of-judgment, document
disagreement in loop ledger, move on. Skill §13.5 autonomy applies.

**MEDIUM** (Codex) or **GAPS** (Gemini): fix if quick. Defer if requires
restructuring.

**LOW**: ignore unless cluster suggests pattern.

**Convergence signal:** if Codex and Gemini independently flag same
issue from different angles → high confidence, prioritize fix.

**Divergence signal:** if Codex says "line X wrong" but Gemini says
structure around X is fine → CC reads source to break tie. Default:
Codex wins on factual contradictions, Gemini wins on structural
judgments.

Codex sometimes is "technically correct, point missed" — CC may
override. Architect noted: "ему нужна абсолютная буквальность" —
Codex demands literal precision; can conflict with vault's "synthesis
digest" purpose. Balance is CC's job.

Gemini sometimes wants notes more comprehensive than digest justifies.
Same override pattern.

### 6.4 — Loop ledger entry per audit cycle

Append to `~/Vault/CryoDAQ/_meta/build log.md`:

```markdown
## Phase N audit — <HH:MM>
Codex verdict: PASS | FAIL | CONDITIONAL | TIMEOUT
Gemini verdict: COHERENT | GAPS | DRIFT | TIMEOUT
Codex findings: CRITICAL=A HIGH=B MEDIUM=C LOW=D
Gemini findings: <table row counts by category>
Convergent findings (both flagged): <count>
Fixes applied: <count>
Disputes (CC overruled): <count, one-line reason each>
Build log: <CC's brief reflection>
```

---

## 7. Loop logic — repeat until quiescent or time runs out

After Phase 5, run **integration audit loop** with parallel verifiers
until quiescent OR remaining time better spent on Phase 8.

```
loop iteration N:
  dispatch Codex full-vault audit (parallel)
  dispatch Gemini full-vault audit (parallel)
  wait for both (or 45min each)
  CC reads, classifies findings
  if any CRITICAL or HIGH or DRIFT:
    CC fixes
    if iteration > 5: hard stop, ledger and exit
    repeat loop
  elif MEDIUM > 10 or GAPS > 5:
    CC fixes top 10 by impact
    repeat loop
  else:
    quiescent — exit loop, proceed to Phase 8
```

**Quiescence criteria:**
- 0 CRITICAL findings
- 0 HIGH findings
- 0 DRIFT findings
- ≤10 MEDIUM, ≤5 GAPS
- LOW ignored
- OR 5 iterations completed

After quiescence: proceed to Phase 8.

---

## 8. Vault polish (any model, until time runs out)

Architect explicitly authorized: "пусть подтюнит тему плагин граф,
если что исправим или удалим." Use remaining hours productively.
Anything in this phase can be reverted morning.

### 8.1 — Theme tuning (10-15 min)

Default theme is fine. CC may:
- Switch to a clean built-in theme (look up bundled themes, pick
  readable, avoid flashy/experimental)
- CSS snippet for code-block readability if default poor
- Dark mode default (Vladimir's preference per design system context)

Document changes in `_meta/build log.md` so architect can reverse.
**Do NOT install third-party themes from URLs.** Bundled/core only.

### 8.2 — Core plugins (15-30 min)

Enable Obsidian core plugins (already shipped):
- Graph view (already core, ensure enabled)
- Backlinks
- Outgoing links
- Tag pane
- Page preview
- Quick switcher
- Search
- Templates (might use later)

**Do NOT install community/third-party plugins.** Trust surface +
breakage risk. Core only.

### 8.3 — Graph view tuning (15-20 min)

- Color groups by folder prefix (00, 10, 20, 30, 40, 50, 60, 90, _meta)
- Filter to hide attachments / orphans optional
- Readable default zoom
- Save graph filter as default workspace state

Document settings in build log.

### 8.4 — Templates folder (optional, 10 min)

If time remains, create `_meta/templates/`:
- `ADR template.md` — Context / Decision / Consequences / Status
- `Investigation template.md` — Story / Hypotheses / Status / Lessons
- `Subsystem template.md` — Purpose / Mechanism / Invariants / Edges

Future-Vladimir uses these via Obsidian template insert. Only create
if integration loop quiesced cleanly and ≥1h wall-clock remains.

### 8.5 — Quality polish until time runs out

If wall-clock remains AFTER all polish steps:
- Re-read each Subsystem note, look for places where 1-2 example
  sentences would clarify
- Re-read each Investigation note, ensure timeline is clear
- Add concrete examples where notes are abstract
- Cross-link more aggressively where natural

Log every change. **Never make changes you can't justify in build
log.** "Filling time with edits" is bad — only edits that improve
a note belong here.

If nothing more to improve and wall-clock has time: STOP. Sitting
idle is fine. Don't manufacture work.

---

## 9. Hard stops and escape hatches

CC stops AND wakes architect (writes prominent file at
`~/Projects/cryodaq/artifacts/vault-build/STOP.md`) if:

- Obsidian MCP returns errors > 3x in a row
- BOTH Codex AND Gemini return garbage 3x in a row (one verifier
  dying is OK; both dying simultaneously suggests network issue)
- File loss detected (note disappears between phases)
- Cyclic correction: same finding flagged → fixed → flagged again 3x
  (CC and verifier disagree on what "correct" looks like)
- Wall-clock exceeds 7h (1h before hard cap)
- Filesystem MCP loses connection to `~/Projects/cryodaq/`

If hard stop: STOP file describes situation, log files preserved,
no rollback. Architect decides next morning whether resume / retry /
revert.

---

## 10. Final morning report

After Phase 8 OR wall-clock cap:

Write `~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md`:

```markdown
# Vault build overnight 2026-04-26→27

## Outcome
Quiescent after N loop iterations / hit wall-clock cap at HH:MM

## Vault state
- M notes total
- K total wikilinks
- L Codex findings surfaced; X fixed; Y disputed
- Q Gemini findings surfaced; X fixed; Y disputed
- Z convergent findings (both verifiers flagged)

## Polish applied (Phase 8)
- Theme: <name>
- Core plugins enabled: <list>
- Graph view: <settings summary>
- Templates: <count if any>

## What worked
- ...

## What didn't
- ...

## Open questions for architect
- <subjective scope decisions verifiers flagged that CC ignored>
- <structural choices that became questionable mid-build>

## Next architect actions suggested
- Review _meta/build log.md for full audit history
- Spot-check 5-10 notes you'd expect to know best
- If accepting current state: just close this handoff
- If revising: list specific notes for CC to redo

## Wall-clock metrics
- Total time: H:MM
- Phase breakdown
- Loop iterations: N
- Codex calls: K
- Gemini calls: K
```

---

## 11. Things explicitly NOT in scope

CC must NOT:

- Modify any file in `~/Projects/cryodaq/` source tree. Read-only there.
  Vault writes go to `~/Vault/CryoDAQ/`. Exceptions: CC's own logs to
  `artifacts/vault-build/` and `artifacts/consultations/2026-04-26-vault/`.

- Push commits to git. None of this work is committed to repo. Vault
  is separate location. Vault may have its own git (Obsidian pattern) —
  DO NOT touch it.

- Move or delete existing vault content (`Soban Soundbar/`, `Tags/`,
  `projects/`, `README.md`). Only create new under `CryoDAQ/`.

- Invent content. If claim isn't grounded in repo file, don't make it.
  Better thin note than fabrication.

- Install third-party / community Obsidian plugins or themes requiring
  download. Core only — those bundled with Obsidian itself.

- Touch Vladimir's personal vault content outside `CryoDAQ/`.

---

## 12. Architect contact during run

CC operates fully autonomously through the night. No human approval
gates between phases. Audit gates are verifier-driven, not architect-
driven.

If situation unclear: log to STOP.md (Section 9), do not page architect
in real-time. Architect reads in morning.

---

## 13. Summary execution order

```
Pre-flight (10 min) →
  Phase 1 skeleton (Sonnet, 15 min) →
  Phase 2 reference seed (Sonnet, 45 min) →
  Audit gate 2: Codex + Gemini parallel (~45 min wall) →
  CC reads both, fixes →
  Phase 3 synthesis (Opus, 90 min) →
  Audit gate 3: Codex + Gemini parallel (~45 min wall) →
  CC reads both, fixes →
  Phase 4 cross-link (Sonnet, 30 min) →
  Audit gate 4: Codex + Gemini parallel (~45 min wall) →
  CC reads both, fixes →
  Phase 5 update protocol (Opus, 15 min) →
  Integration audit loop (parallel verifiers, until quiescent or 5 iter) →
  Phase 8 vault polish (theme, plugins, graph, templates) →
  Continue until quiescent + nothing more to improve, OR wall-clock cap →
  Final morning report
```

Total estimate: 5-7h with parallel verifiers. 8h cap is buffer.
Fill the night productively.

---

*Spec written 2026-04-26 by web Claude (architect) at Vladimir's request.
Designed for unattended overnight execution. CC starts whenever Vladimir
hands off — typical evening dispatch.*
