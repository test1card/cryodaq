# Codex Self-Review Loop — Canonical Playbook

**Audience:** Claude Code during Phase II/III block implementation.
**Purpose:** Standardize the post-commit Codex review cycle so every
block lands with an independent verification pass before hand-off to
Vladimir. Eliminates the «copy prompt to separate terminal» manual
step that slowed prior blocks.

---

## How `/codex` works — DO NOT over-engineer this

**`/codex` is a slash command. Just type it. That's it.**

Do NOT:
- Search `~/.claude/commands/` for a file named `codex`.
- Search `plugins/` for a codex directory.
- Grep the filesystem trying to «find where /codex is installed».
- Run `/codex --help` looking for syntax before invoking.
- Assume absence of a visible command file means absence of the
  command.

DO:
- At the CC prompt line, write `/codex` followed by the prompt body
  (starting with `Model: gpt-5.4` and `Reasoning effort: high` on
  the first two lines).
- Send. Wait for response. Read verdict.

If the command returns «unknown command» or errors out:
- Record the failure in the block's final report.
- Skip Stage 6 for this block only: push the code commit anyway
  with «/codex review deferred: plugin unavailable» in commit body.
- Move to the next block. Do NOT spend time debugging the plugin.

The model / reasoning flags can be passed two ways — use BOTH:
1. Inline CLI-style after the command (if the plugin accepts them):
   `/codex --model gpt-5.4 --reasoning high`
2. As first two lines of the prompt body:
   ```
   Model: gpt-5.4
   Reasoning effort: high
   ```
Belt + suspenders. Codex honors whichever gets parsed.

After the response arrives, verify the response header reports the
actual model used was `gpt-5.4` (NOT `o3`). If the response says o3:
- Retry once with the flags clearly specified.
- If still o3: record «Codex stuck on o3 — verdict unreliable» in
  the block's report and treat the review as DEFERRED (push commit,
  move on).

---

## Autonomy mode — Claude Code is the driver

This is a **full-automation** workflow. CC drives every stage
end-to-end without waiting for `continue` acknowledgements:

- Stage 0 reads → CC analyzes and decides, does NOT stop for
  architect confirmation unless there's a genuine architectural
  fork (e.g. discovering a duplicate backend module, finding an
  engine API that doesn't exist, legacy file with no drop-in
  replacement path). Surface-level findings like «v1 uses legacy
  tokens» or «CoverageBar has hardcoded hex» are NOT forks —
  those are expected and CC proceeds through Stage 1.
- Stage 1-4 implementation → autonomous.
- Stage 5 commit + push → autonomous.
- Stage 6 `/codex` self-review → autonomous. CC invokes Codex,
  reads verdict, decides amend or close per rules below.
- Amend cycles → autonomous up to the 3-cycle limit.

**CC stops and surfaces to architect ONLY when:**

1. Genuine architectural ambiguity requires a design decision
   (e.g. «should accent be wine or blue» — Codex-style FAIL on
   design, not on implementation).
2. 3 Codex amend cycles elapsed without PASS — something structural
   is off, not fixable at the code level.
3. Codex finding would require touching files or scope outside the
   block's explicit spec (e.g. «this engine handler needs a new
   parameter» — that's a separate block, architect call).
4. Pre-commit gates fail in ways CC can't understand (ruff error
   in a file CC didn't touch, test collection error from a
   pre-existing problem).

In all other cases CC proceeds. Vladimir reviews the final SHA
and Codex PASS report at the end of the session, not during it.

---

## When to invoke Codex self-review

**ALWAYS** at the end of these commit types:

- **Initial block commit** — new overlay / major feature / engine
  command wiring. Codex reviews the whole shipped block.
- **Codex-driven amend commit** — after fixing a prior FAIL, ALWAYS
  re-review the amend for regressions or incomplete fixes.

**NEVER** invoke Codex for:

- Doc-only commits (roadmap sync, CHANGELOG, operator manual) — no
  code to review.
- Dead-branch cleanup or git hygiene commits.
- Theme / config / data-file landing commits (e.g. YAML drops).
- Codex already PASSED in this block's current session — don't burn
  a second review on unchanged code.

---

## The loop

```
1. CC finishes block implementation (Stage 1-4).
2. CC runs pre-commit gates (ruff, forbidden-token grep, emoji scan,
   hex-color scan, targeted tests).
3. CC commits + pushes.
4. CC invokes /codex with the canonical prompt (template below),
   substituting commit SHA and block-specific focus.
5. CC reads verdict:
   - PASS → report SHA + verdict summary to chat. Block closed for
     this session. (If residual risks are listed, surface them in
     the report — architect decides whether to fix now or track as
     follow-up in a separate commit.)
   - FAIL → CC reads findings, severity-sorts them:
     - CRITICAL / HIGH → autonomous amend in same session. Loop to
       step 4.
     - MEDIUM → autonomous amend if fix is small (<3 files, clearly
       scoped). If fix requires judgment call or touches wide scope,
       surface to architect.
     - LOW → autonomous amend if trivial; otherwise add to residual
       risks and proceed to PASS-equivalent close.
     - Design-decision FAIL (e.g. «should accent be olive or blue»)
       → STOP, surface to architect, do NOT amend unilaterally.
6. Max 3 amend cycles per block. If Codex still FAILs after 3
   rounds, STOP and surface — something structural is off.
```

**Decision tree for FAIL findings:**

```
FAIL finding arrives →
  Is it CRITICAL or HIGH?
    YES → amend autonomously, re-review.
    NO → 
      Is it MEDIUM with fix <3 files and clearly-scoped?
        YES → amend autonomously, re-review.
        NO (MEDIUM with broader scope OR LOW non-trivial) →
          Is it a design decision (wine vs blue, layout choice)?
            YES → STOP, surface to architect.
            NO → amend if trivial, else track as residual risk.
```

The goal: CC handles 80-90% of Codex findings without architect
involvement. Architect sees only (a) final PASS report, (b) design
decisions, (c) 3-cycle failures.

---

## Canonical /codex prompt template

CC formats this with block-specific values. Keep the structure —
Codex expects the `Invariants / Focus / Process / Output format`
skeleton.

```
Working dir: /Users/vladimir/Projects/cryodaq
Role: read-only code review. Do NOT modify files.

Review HEAD commit <SHA> — <block short title, e.g. "Phase II.7 
CalibrationOverlay rebuild + command wiring">.

Context: <one paragraph describing what the block does, what it 
replaces, and what scope changes. Copy from block spec's Goal section.>

Project invariants that MUST hold:
1. No blocking I/O on GUI thread. <block-specific example>.
2. SafetyManager authority unchanged. <if applicable>.
3. Russian operator text throughout overlay.
4. UTF-8 without BOM in source (per CLAUDE.md «Кодировка файлов»); 
   utf-8-sig allowed for CSV exports only.
5. DS v1.0.1 tokens only. Zero hits for TEXT_PRIMARY / TEXT_SECONDARY 
   / TEXT_MUTED / TEXT_DISABLED / TEXT_ACCENT, apply_panel_frame_style 
   / apply_button_style / apply_status_label_style / 
   apply_group_box_style, PanelHeader / StatusBanner / 
   build_action_row / create_panel_root / setup_standard_table.
6. No emoji (RULE-COPY-005). No hardcoded hex colors outside 
   PLOT_LINE_PALETTE indexing.
7. <block-specific invariant — e.g. "Keithley command payloads match 
   engine.py:91 shapes">.

Focus questions:

1. **DS compliance.** Grep-verify zero hits for legacy tokens and 
   helper functions inside <overlay file path>. Grep-verify zero 
   emoji codepoints (U+1F300–U+1FAFF, U+2600–U+27BF, ✓ U+2713). 
   Grep-verify no raw hex colors outside PLOT_LINE_PALETTE context.

2. **<Block-specific: functional preservation / new wiring 
   correctness>.** <Walk through what to check. E.g. for II.7: 
   import / export / runtime-apply buttons all dispatch real engine 
   commands. For II.5 amend: empty-state gate only fires on 
   temperature readings.>

3. **Host Integration Contract.** Verify three hook points in 
   MainWindowV2:
   (a) _tick_status() mirror for set_connected.
   (b) _dispatch_reading() state sinks (if applicable).
   (c) _ensure_overlay() replay on lazy open.

4. **Test coverage structure.** Overlay tests: ≥N cases covering 
   <list block-specific coverage categories>. Wiring tests: ≥M cases 
   covering connection mirror + readings routing + lazy replay. 
   Tests use plain-Python stubs for ZmqCommandWorker + mocked 
   backends (no MagicMock across Qt signal boundary — lesson from 
   II.2 segfault).

5. **<Block-specific safety-relevant question if applicable>.**

6. **Legacy disposition.** Verify legacy v1 widget has DEPRECATED 
   docstring marker.

Process:
- git show HEAD to see full diff
- Read touched files fully: <list file paths>
- Cross-reference <relevant backend / engine files>
- Grep for legacy tokens, emoji, hex colors

Output format:
- First line: PASS or FAIL
- Findings by severity: CRITICAL / HIGH / MEDIUM / LOW with 
  file:line + one-sentence reason + suggested fix direction
- If PASS, list residual risks worth tracking

Do not create new tests or propose refactors. <N>-minute cap.
```

The VERY FIRST two lines of the prompt body (before "Working dir:")
must be:

```
Model: gpt-5.4
Reasoning effort: high
```

This belt-and-suspenders ensures Codex uses the strong reasoning
path even if the CLI flags don't get parsed as intended.

---

## Invocation pattern

See the «How `/codex` works» section at the top of this document
for the authoritative invocation rules. Do NOT duplicate them here.

Short reminder:
- `/codex` is a slash command. Just type it followed by the prompt.
- First two lines of prompt body: `Model: gpt-5.4` + `Reasoning
  effort: high`. Plus inline flags if the plugin accepts them.
- Do NOT search the filesystem for the command.
- Do NOT run `/codex --help` — don't fish for flag syntax; set the
  override in the prompt body itself.
- If plugin fails or returns o3 despite retry: DEFER the review,
  push the commit, move on. Architect runs Codex manually later.

### Example invocation (CC-side)

```
/codex --model gpt-5.4 --reasoning high

Model: gpt-5.4
Reasoning effort: high

Working dir: /Users/vladimir/Projects/cryodaq
Role: read-only code review. Do NOT modify files.

Review HEAD commit abc12345 — Phase II.7 CalibrationOverlay rebuild.

[full prompt body from template above, with SHA + block title + 
focus questions filled in]
```

If the plugin ignores `--model` / `--reasoning` CLI flags, Codex
will still read the `Model:` / `Reasoning effort:` lines in the
prompt body. Belt + suspenders. Don't worry about which path works;
provide both.

CC reads Codex's response inline, parses the first-line verdict,
confirms the response header reports gpt-5.4 (NOT o3), and proceeds
per the loop rules above. If the response came from o3, retry once
with the override. If still o3: treat as DEFERRED, push the commit,
move on.

---

## Fix-amend prompt template (for Codex FAIL remediation)

When amending for a Codex-identified fix, the next /codex call uses
a SHORTER prompt focused only on the residual check:

```
Model: gpt-5.4
Reasoning effort: high

Working dir: /Users/vladimir/Projects/cryodaq
Role: read-only code review. Do NOT modify files.

Review HEAD commit <new amended SHA> — amended <block> after Codex 
<prior verdict SHA> returned FAIL with:

<bullet list of prior findings, one line each>

Verify each finding is CLOSED:

1. <finding 1 title>
   Claimed fix: <one sentence from CC's amend>.
   Verify: <what to check in code / tests>.

2. <finding 2 title>
   Claimed fix: <...>
   Verify: <...>

Confirm no regressions to previously-closed areas:
- <short list of previously-PASS areas that touch the same files>.

Output format:
- First line: PASS or FAIL
- For each prior finding: status CLOSED or STILL OPEN with evidence
- Any fresh findings (CRITICAL / HIGH / MEDIUM / LOW)
- If PASS, confirm block is ready to close

5-minute cap.
```

---

## Anti-patterns — what NOT to do

1. **Don't run full test suite AFTER Codex PASS just to confirm.**
   Wasteful — architect runs full suite in parallel terminal per CI
   budget rule. Targeted tests already passed before commit.

2. **Don't amend unilaterally on design-decision FAILs.**
   E.g. Codex says «accent color collision with STATUS» — STOP and
   surface. Architect decides whether it's a real bug or a known
   trade-off (remember warm_stone FU-THEME-1).

3. **Don't skip Codex because «the diff looks clean».**
   The whole point is independent verification. If CC is confident
   the code is right, Codex will confirm fast. If it's wrong, Codex
   catches it before Vladimir has to.

4. **Don't re-review unchanged SHAs.**
   If Codex PASSed on commit X and X is still HEAD, a second
   /codex call is pure token waste.

5. **Don't exceed 3 amend cycles on one block.**
   If 4th cycle would start, STOP and surface. Something is off at
   the spec / architecture level, not at the code level.

---

## Self-review for THIS document

When a new block type emerges that the template doesn't cover (e.g.
«engine-side backend module», «safety-critical kernel change»), add a
new section here rather than improvising the Codex prompt.
