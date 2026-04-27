# Retroactive versioning plan — v0.33.0..HEAD

## Total commits in range

**50 commits** between v0.33.0 (`7b453d5` merge, 2026-04-14) and HEAD (`21a3a28`, 2026-04-27).

## Key finding: IV.4 + Phase III are pre-v0.33.0

The hints in the plan prompt (IV.4 Parquet/Debug/auto-report/shift-handover; Phase III.A/B/C UI rebuild) do NOT appear in `git log v0.33.0..HEAD`. They were committed and tagged in v0.33.0. The 50-commit range covers only post-v0.33.0 work (2026-04-20 through 2026-04-27).

## Proposed semantic batches

---

### Batch 1 — IV.6 ZMQ hardening + April-20 field fixes

- **Opening commit:** `2d3b504` docs: preserve pending untracked specs (2026-04-20 08:54)
- **Closing commit:** `256da7a` docs: sync B1 status and next-phase control (2026-04-20 12:27)
- **Commit count:** 10
- **Proposed tag:** `v0.34.0`
- **Suggested CHANGELOG title:** `[0.34.0] — 2026-04-20 — ZMQ cmd-plane hardening + field fixes`

**Key changes:**
IV.6 ZMQ ephemeral-REQ-per-command pattern + launcher command-watchdog (`be51a24`). xml_safe sanitizer for python-docx (`74dbbc7`). Thyracont validate_checksum wired through loader (`aabd75f`). Launcher port-wait before reconnect (`9b047a4`). Watchdog cooldown prevents restart storm (`af0b2a0`). Bridge restart diagnostics in GUI (`c3a4a49`). cooldown_stall threshold_error config mitigation (`747f80e`).

**Character:** First production wave after v0.33.0. The IV.6 ZMQ change is architecturally significant (canonical REQ/REP pattern). Field fixes address Ubuntu lab PC runtime issues discovered 2026-04-20 morning.

---

### Batch 2 — B1 diagnostic tooling

- **Opening commit:** `8b9ce4a` tools: add reusable B1 diagnostic helpers (authored 2026-04-21, merged April 24)
- **Closing commit:** `62314be` tools: record direct probe timeouts in B1 capture CLI (2026-04-21)
- **Commit count:** 5
- **Proposed tag:** `v0.35.0`
- **Suggested CHANGELOG title:** `[0.35.0] — 2026-04-21 (merged 2026-04-24) — B1 investigation tooling`

**Key changes:**
Reusable `_b1_diagnostics.py` helpers (`bridge_snapshot`, `direct_engine_probe`). Canonical B1 capture CLI `diag_zmq_b1_capture.py` with JSONL output. Two alignment passes to sync helpers and CLI with bridge API changes.

**Character:** Self-contained tooling batch. These commits have April-21 author timestamps but appear in master after the April-23 orchestration work — they were merged from the `codex/safe-merge-b1-truth-recovery` branch around April 24 (per `af77095` "recon: safe-merge branch commit classification"). No production engine code changes.

**Architect note:** This batch could alternatively be folded into Batch 1 (they support IV.6 investigation) or Batch 4 (they predate the R1 repair they enable). As a standalone "tooling" minor is also clean.

---

### Batch 3 — Orchestration infrastructure

- **Opening commit:** `adb49fe` docs: preserve 2026-04-20 session detail (2026-04-23 23:00)
- **Closing commit:** `af77095` recon: safe-merge branch commit classification (2026-04-24 10:21)
- **Commit count:** 17 (lines 11–27 inclusive in the log)
- **Proposed tag:** `v0.36.0`
- **Suggested CHANGELOG title:** `[0.36.0] — 2026-04-23 — Agent orchestration governance`

**Key changes:**
ORCHESTRATION.md v1.1 with STOP discipline + autonomy band (`5286fa2`). Gitignore for agent orchestration workspaces (`587bea8`). multi-model-consultation + negative-space skills (`9a1a100`). Version bump from stuck 0.13.0 → 0.34.0.dev0 (`5030682` — not a semantic bump, corrects stale pyproject.toml). Remaining 13 commits are session ledgers, handoffs, artifact archives, and model config updates.

**Character:** Governance and process infrastructure overhaul after the 2026-04-21 agent-swarm chaos (duplicate branches, root-level markdown flood, no-leader multi-agent drift). The ORCHESTRATION.md is a significant governance document. `9a1a100` adds workflow skills. Most of the 17 commits are infra/docs supporting this governance shift.

**Architect note (Q1):** This batch is the most debatable. Arguments for its own tag: ORCHESTRATION.md is a meaningful artifact that future agents reference at session start. Arguments against: almost no production code changed (only gitignore + CLAUDE.md skills), and it might read oddly as a public version bump. Alternative: fold into Batch 2 or Batch 4 as infra context.

---

### Batch 4 — D1 R1 probe repair + investigation artifacts

- **Opening commit:** `c3f4f86` fix(diag): bounded-backoff retry in B1 capture probe (2026-04-24 10:28)
- **Closing commit:** `cabd854` docs: Q4 equivalence check synthesis + D1 close (2026-04-24 22:16)
- **Commit count:** 4
- **Proposed tag:** `v0.37.0`
- **Suggested CHANGELOG title:** `[0.37.0] — 2026-04-24 — R1 probe retry repair`

**Key changes:**
`c3f4f86` — `_validate_bridge_startup()` with bounded-backoff retry in `diag_zmq_b1_capture.py`, fixing the b2b4fb5 race where the single-shot probe would reject a healthy ipc:// bridge during bind-startup. Remaining 3 commits are session ledger, D1 review handoff, and Q4 equivalence synthesis.

**Character:** Small but semantically significant patch. Repairs the b2b4fb5 misattribution that caused IV.7 to be blamed for what was actually a probe race. The fix itself is in a diagnostic tool (not production engine code).

**Architect note (Q2):** `c3f4f86` is in `tools/diag_zmq_b1_capture.py`, not in the production engine. If only production-code changes deserve version tags, this batch could be merged into Batch 3 or Batch 5. If diagnostic tooling is versioned (it is instrumentally important for lab operation), v0.37.0 stands.

---

### Batch 5 — Production hardening (Codex-03/04/05)

- **Opening commit:** `3215580` config: recover channels.yaml header (2026-04-27 12:04)
- **Closing commit:** `9a8412e` feat(launcher): SIGTERM/SIGINT handler (2026-04-27 12:35)
- **Commit count:** 5 (including `1c19b60` CLAUDE.md infra)
- **Proposed tag:** `v0.38.0`
- **Suggested CHANGELOG title:** `[0.38.0] — 2026-04-27 — Production hardening: alarms, drivers, launcher`

**Key changes:**
`1869910` — alarm_v2 threshold validation tightened (Codex-04). `7230c9f` — Thyracont V1 probe checksum-validates on connect (Codex-05). `9a8412e` — SIGTERM/SIGINT handler in launcher prevents engine orphan on systemd stop / Ctrl+C (Codex-03). `3215580` — channels.yaml header recovery (field config fix). `1c19b60` — CLAUDE.md Codex playbook bump (infra only).

**Character:** Clean production-hardening batch. All three `fix`/`feat` commits address real operator-visible issues: alarm config crashes, Thyracont NaN-forever on connect, engine orphan on stop. These were Codex-03/04/05 overnight batch results merged in one session.

---

### Batch 6 — H5 ZMQ fix (B1 investigation closed)

- **Opening commit:** `31d594a` docs: D2 H4 split-context experiment results (2026-04-27 13:03)
- **Closing commit:** `21a3a28` release: v0.34.0 (2026-04-27 21:41)
- **Commit count:** 10
- **Proposed tag:** `v0.39.0`
- **Suggested CHANGELOG title:** `[0.39.0] — 2026-04-27 — B1 ZMQ idle-death fixed (H5 confirmed)`

**Key changes:**
`5e7eeac` — `diag_zmq_direct_req.py` bypass tool (D3 experiment tooling). `1f88d2e` — `fix(zmq): replace cancellation polling with poll+recv in REP/SUB loops` — the B1 root-cause fix. `21a3a28` — release commit (CHANGELOG + pyproject.toml bump). Remaining 7 commits are investigation docs, artifact archive, gitignore chore, and B1 reconciliation.

**Character:** Closes the 7-day B1 investigation. `1f88d2e` is the primary production-code fix (touches `zmq_bridge.py`). The D3 direct-REQ tool (`5e7eeac`) is the diagnostic that proved engine-side causation. Investigation ledgers (`31d594a`, `e1fdf4b`, `9f5cea3`) document the hypothesis chain. Infrastructure cleanup (`9d6810e`, `f32aaf0`, `1dfb7d5`) is batch support.

---

## Boundary commits classified

```
2d3b504 2026-04-20 docs: preserve pending untracked specs        [BATCH-1/infra]
362431b 2026-04-20 docs: B1 Codex analysis + IV.6 fix spec       [BATCH-1/infra]
be51a24 2026-04-20 zmq: ephemeral REQ per command + watchdog     [BATCH-1/CORE]
74dbbc7 2026-04-20 reporting: xml_safe sanitizer                 [BATCH-1]
aabd75f 2026-04-20 engine: wire validate_checksum Thyracont      [BATCH-1]
9b047a4 2026-04-20 launcher: wait for engine port release        [BATCH-1]
af0b2a0 2026-04-20 launcher: watchdog cooldown prevents storm    [BATCH-1]
c3a4a49 2026-04-20 gui(zmq): bridge restart diagnostics          [BATCH-1]
747f80e 2026-04-20 config: cooldown_stall threshold_error fix    [BATCH-1]
256da7a 2026-04-20 docs: sync B1 status and next-phase          [BATCH-1/infra]

adb49fe 2026-04-23 docs: preserve 2026-04-20 session detail     [BATCH-3/infra]
1ea049d 2026-04-23 docs: archive 2026-04-21 agent-swarm review  [BATCH-3/infra]
587bea8 2026-04-23 gitignore: exclude agent orchestration dirs   [BATCH-3/CORE]
cfee680 2026-04-23 docs: preserve stray agent-swarm plan        [BATCH-3/infra]
9271e3c 2026-04-23 docs: session ledger 2026-04-23 cleanup      [BATCH-3/infra]
8ebc893 2026-04-23 artifacts: CC→architect handoff 2026-04-23   [BATCH-3/infra]
5286fa2 2026-04-23 docs: ORCHESTRATION.md v1.1                  [BATCH-3/CORE]
9a1a100 2026-04-23 skills: multi-model-consultation + neg-space [BATCH-3]
3ee2180 2026-04-23 docs: next-session entry card                 [BATCH-3/infra]
baa672f 2026-04-24 docs: b2b4fb5 hypothesis investigation — H3  [BATCH-3/infra]
a96436c 2026-04-24 artifacts: CC→architect handoff 2026-04-24   [BATCH-3/infra]
57ca565 2026-04-24 models: update Codex target to gpt-5.5       [BATCH-3/infra]
3a2f511 2026-04-24 docs: launch ledger overnight swarm          [BATCH-3/infra]
31bb51b 2026-04-24 artifacts: overnight swarm 2026-04-24 results [BATCH-3/infra]
5030682 2026-04-24 version: bump pyproject.toml 0.13.0→0.34.0  [BATCH-3/infra]
0a38f93 2026-04-24 models: update skill + overnight to Gemini   [BATCH-3/infra]
af77095 2026-04-24 recon: safe-merge branch classification       [BATCH-3/infra]

8b9ce4a 2026-04-21 tools: add reusable B1 diagnostic helpers    [BATCH-2/CORE]
cc090be 2026-04-21 tools: add canonical B1 capture CLI          [BATCH-2/CORE]
40553ea 2026-04-21 tools: align B1 diagnostic helpers           [BATCH-2]
033f87b 2026-04-21 tools: align B1 capture CLI with jsonl       [BATCH-2]
62314be 2026-04-21 tools: record direct probe timeouts in CLI   [BATCH-2]

c3f4f86 2026-04-24 fix(diag): bounded-backoff retry B1 probe    [BATCH-4/CORE]
a82d6bf 2026-04-24 docs: session ledger D4a + D1 close          [BATCH-4/infra]
680240a 2026-04-24 artifacts: D1 R1 repair review handoff       [BATCH-4/infra]
cabd854 2026-04-24 docs: Q4 equivalence check synthesis + D1    [BATCH-4/infra]

3215580 2026-04-27 config: recover channels.yaml header         [BATCH-5]
1c19b60 2026-04-27 docs: CLAUDE.md Codex playbook bump          [BATCH-5/infra]
1869910 2026-04-27 fix(alarms): alarm_v2 threshold validation   [BATCH-5/CORE]
7230c9f 2026-04-27 fix(thyracont): V1 probe TIGHTEN             [BATCH-5/CORE]
9a8412e 2026-04-27 feat(launcher): SIGTERM/SIGINT handler       [BATCH-5/CORE]

31d594a 2026-04-27 docs: D2 H4 split-context experiment results [BATCH-6/infra]
9d6810e 2026-04-27 chore: gitignore node_modules                [BATCH-6/infra]
f32aaf0 2026-04-27 artifacts: archive vault-build + audit       [BATCH-6/infra]
1dfb7d5 2026-04-27 docs: archive CC prompts                     [BATCH-6/infra]
9f5cea3 2026-04-27 docs: B1 reconciliation H4 falsified         [BATCH-6/infra]
5e7eeac 2026-04-27 feat(diag): direct REQ bypass tool D3        [BATCH-6]
e1fdf4b 2026-04-27 docs: D3 H5 direct-REQ experiment results   [BATCH-6/infra]
1f88d2e 2026-04-27 fix(zmq): replace cancellation polling       [BATCH-6/CORE]
21a3a28 2026-04-27 release: v0.34.0                             [BATCH-6/release]
```

## UNCLASSIFIED

None. All 50 commits classified.

**Infra-only commits by batch** (no production code, support material):

- BATCH-1: `2d3b504`, `362431b`, `256da7a` (3 commits)
- BATCH-3: `adb49fe`, `1ea049d`, `cfee680`, `9271e3c`, `8ebc893`, `3ee2180`, `baa672f`, `a96436c`, `57ca565`, `3a2f511`, `31bb51b`, `5030682`, `0a38f93`, `af77095` (14 commits — this batch is mostly infra)
- BATCH-4: `a82d6bf`, `680240a`, `cabd854` (3 commits)
- BATCH-5: `1c19b60` (1 commit)
- BATCH-6: `31d594a`, `9d6810e`, `f32aaf0`, `1dfb7d5`, `9f5cea3`, `e1fdf4b` (6 commits)

## Proposed tag placement summary

| Tag | Closing commit | Date | Core production changes |
|---|---|---|---|
| v0.34.0 | `256da7a` | 2026-04-20 | IV.6 zmq, xml_safe, thyracont, launcher fixes |
| v0.35.0 | `62314be` | 2026-04-21 | B1 diagnostic tooling (5 tool commits) |
| v0.36.0 | `af77095` | 2026-04-24 | ORCHESTRATION.md, gitignore, skills |
| v0.37.0 | `cabd854` | 2026-04-24 | R1 probe retry repair |
| v0.38.0 | `9a8412e` | 2026-04-27 | alarms, thyracont probe, SIGTERM handler |
| v0.39.0 | `21a3a28` | 2026-04-27 | H5 ZMQ fix (B1 closed), release artifacts |

**Note on git ordering:** BATCH-2 commits (`8b9ce4a`–`62314be`) have April-21 author timestamps but appear in the topological log AFTER the April-23 orchestration commits. They were merged from `codex/safe-merge-b1-truth-recovery` around April 24. If tags are placed on the commits in topological log order, v0.35.0 would land AFTER v0.36.0 chronologically — which is confusing. See Q3 below.

## Architect questions

**Q1 (Batch 3 necessity):** Batch 3 (Orchestration) is 17 commits but only 3 touch real code (`587bea8` gitignore, `5286fa2` ORCHESTRATION.md, `9a1a100` skills). The rest are session ledgers, handoff artifacts, model config. Should this be its own v0.36.0, or folded into Batch 2 (B1 tools) or Batch 4 (R1 repair)?

**Q2 (Diag tool versioning):** Batches 2, 4, and part of Batch 6 are diagnostic tooling changes — not production engine code. Should they get their own minor versions, or only production engine/launcher/config changes get tags (reducing to 3 tags: v0.34.0 IV.6, v0.38.0 hardening, v0.39.0 H5 fix)?

**Q3 (Topological vs chronological order):** BATCH-2 (v0.35.0) commits are authored before BATCH-3 (v0.36.0) commits but appear AFTER them in topological log order. Placing v0.35.0 tag on `62314be` and v0.36.0 on `af77095` means v0.36.0 is an ancestor of v0.35.0 in the commit graph — `git describe` would produce confusing output. Resolution options: (a) swap proposed v0.35.0 and v0.36.0 tag ordering, (b) fold both into one batch, (c) accept topological-not-chronological numbering and document it.

**Q4 (Tag on release commit vs closing production commit):** Current v0.34.0 sits on `21a3a28` (the release commit, which is just CHANGELOG + pyproject.toml). For the retroactive plan, should each tag sit on the LAST PRODUCTION CODE commit of the batch (e.g., `747f80e` for v0.34.0) or on any associated release/docs commit at the batch boundary?

**Q5 (Minimum viable plan):** If the full 6-tag plan feels over-engineered, a simpler 3-tag split would be:
- v0.34.0 → `c3a4a49` (IV.6 + field fixes, April 20)
- v0.35.0 → `9a8412e` (B1 tools + orchestration + R1 + hardening, April 21-27)
- v0.36.0 → `21a3a28` (H5 ZMQ fix, current HEAD)
This sacrifices semantic granularity for clean simplicity. Architect's call.
