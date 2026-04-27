# Vault audit findings — 2026-04-27

**Audit window:** 11:30:41 — 11:38:50 MSK (~8 min wall-clock, both verifiers parallel)
**Codex:** FAIL — 5 findings (CRITICAL=2 HIGH=2 MEDIUM=0 LOW=0 DEFERRED=1)
**Gemini:** DRIFT / INCONSISTENT / GAPS — 5 findings
**Dispatch:** spec-compliant, both via documented CLI patterns. Gemini hit
two 429 RESOURCE_EXHAUSTED retries against `gemini-3.1-pro-preview` early
(visible in response head), then succeeded; output table is at the bottom
of the response file.

## Summary table

| # | Source | Severity | Vault file | What's wrong | Suggested fix | CC pre-assessment |
|---|---|---|---|---|---|---|
| 1 | Codex 01 | CRITICAL | `00 Overview/Architecture overview.md:80-82` | Says "Engine runs ZMQ in a child subprocess (`core/zmq_subprocess.py`); engine main loop is shielded from ZMQ crashes." Source: `zmq_subprocess.py` docstring is "The GUI process never imports zmq." Subprocess isolation is **GUI-side**, not engine-side. | Replace with: GUI spawns `zmq_bridge_main()` from `core/zmq_subprocess.py`, owning GUI-side SUB/REQ; engine PUB/REP live in `core/zmq_bridge.py`. | AGREE — vault inverted the topology |
| 2 | Codex 02 | HIGH | `00 Overview/Architecture overview.md:52-54` | Says "Loopback-only deployment is the expected pattern (auth deferred to F7 / G.1)." Repo docs show `uvicorn --host 0.0.0.0`; PROJECT_STATUS lists G.1 (auth OR loopback-only default) as deferred — neither is the current default. | Replace with: docs launch uvicorn at `--host 0.0.0.0`; auth-or-loopback-default work is deferred under G.1, production exposure unresolved. | AGREE — overstates the default posture |
| 3 | Codex 03 | CRITICAL | `00 Overview/Hardware setup.md:43-46` | Says interlocks regex was "tightened from `Т[1-8] .*` to `Т(1\|2\|3\|5\|6\|7\|8) .*`". Source `interlocks.yaml:20` still has `channel_pattern: "Т[1-8] .*"`. Т4 exclusion exists only at alarm-group level (`alarms_v3.yaml:30-36`). | Update to current state: master interlock regex unchanged; Т4 excluded only via alarm-group exclusion. | AGREE — and this is a **regression** of the integration-loop fix that landed correctly in `30 Investigations/Cyrillic homoglyph in alarm config.md` but didn't propagate to Hardware setup |
| 4 | Codex 04 | HIGH | `30 Investigations/Plugin isolation rebuild.md:85` | Says "`config/plugins.yaml` controls which plugins are enabled". Source: `PluginPipeline.start()` loads every `*.py` in `plugins_dir` unconditionally; `config/plugins.yaml` configures the shipped analytics modules (sensor_diagnostics, vacuum_trend), not the plugin pipeline itself. | Replace with the same wording I applied to `10 Subsystems/Plugin architecture.md` during Phase 3 audit (filesystem loader is unconditional, plugins.yaml configures shipped analytics). | AGREE — Phase 3 fix on this same point landed in `10 Subsystems/Plugin architecture.md` but the parallel investigation note retained stale wording |
| 5 | Codex 05 | DEFERRED-COVERAGE | `50 Workflow/_index.md` (no matching note exists) | `.claude/skills/cryodaq-team-lead.md` has zero coverage in vault. Vault digests `multi-model-consultation` only. | Add `50 Workflow/CryoDAQ team lead skill.md` digest, or extend `_index.md` with explicit non-coverage note. | AGREE — extends the deferred-coverage list (now 5: Web / Cooldown / Experiment / Interlock / team-lead-skill) |
| 6 | Gemini 01 | MISLEADING | `10 Subsystems/Persistence-first.md` + `10 Subsystems/Plugin architecture.md` + `00 Overview/Architecture overview.md` | Combined reading: "DataBroker has a reading → SQLite has it" + "plugin metrics published back into DataBroker" wrongly implies synthetic plugin metrics are persisted. The persistence-first invariant applies only to raw driver readings. | Add caveat to Persistence-first scoping the invariant to raw driver readings; cross-reference `10 Subsystems/Plugin architecture.md` "SQLite persistence not wired" caveat. | AGREE — Plugin architecture has the caveat already; Persistence-first lacks the converse statement |
| 7 | Gemini 02 | DRIFT | `00 Overview/UI and design system.md` + `00 Overview/Architecture overview.md` | Claims legacy `MainWindow` and Phase-I widgets were "retired and deleted in Phase II.13"; Gemini cites README.md / older CHANGELOG that describe "dual-shell transition state". | Mark Phase II.13 retirement as planned/aspirational rather than complete. | DISPUTE — `CLAUDE.md` explicitly says "main_window_v2.py — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13"; CHANGELOG also lists Phase II.13 deletions under "Removed". README.md describing dual-shell is older v0.33.0 era. CLAUDE.md is canonical. CC overruled this same disagreement during Phase 2 audit. |
| 8 | Gemini 03 | INCONSISTENT | `20 Drivers/LakeShore 218S.md:94` + `00 Overview/Hardware setup.md` | LakeShore note's "See also" section says "Т1..Т8 are critical channels for rate-limit and overheat interlock"; Hardware setup note says Т4 is physically disconnected and excluded. | Either qualify the LakeShore "See also" line ("Т1..Т8, except disconnected Т4") or link to Hardware setup for the per-channel state. | AGREE — convergent with Codex 03 (both about Т4 status) |
| 9 | Gemini 04 | GAP | `10 Subsystems/` (no Reporting note) | `src/cryodaq/reporting/` (generator + sections + data) is heavily referenced (auto-report on finalize, F6, F9, GOST templates, `xml_safe` `74dbbc7` fix) but has no dedicated subsystem note. | Add `10 Subsystems/Reporting.md` to the deferred-coverage list. | AGREE — extends deferred-coverage list to 6 (Web / Cooldown / Experiment / Interlock / team-lead-skill / Reporting) |
| 10 | Gemini 05 | DEAD-END | `10 Subsystems/Safety FSM.md:67` + `_meta/glossary.md` | `[[_meta/glossary#FSM\|RateEstimator]]` — anchor `#FSM` exists but is the generic FSM definition, not RateEstimator; glossary has no RateEstimator entry. | Either fix anchor to point at a new `## RateEstimator` heading + add the entry, or drop the alias and use plain text. | AGREE — broken alias, easy fix |

## Convergent findings (high-confidence)

- **Convergent A — Т4 / interlock regex state.** Codex 03 (CRITICAL on
  Hardware setup) + Gemini 03 (INCONSISTENT on LakeShore See-also).
  Both verifiers independently flagged the Т4 exclusion mis-statement.
  CC corrected this during integration in the homoglyph note but missed
  Hardware setup and LakeShore "See also". **Highest-confidence finding.**
- **Convergent B — plugin pipeline configuration framing.** Codex 04
  (HIGH on Plugin isolation rebuild) + Gemini 01 (MISLEADING on
  Persistence + Plugin combined). Different angles on the same
  surface — `config/plugins.yaml` does not gate the filesystem
  pipeline, AND plugin metrics are not persisted. Phase 3 audit
  caught half of this; the other half (investigation note + persistence
  caveat) leaked through.

## CC dispute notes

**Dispute on Gemini 02 (Phase II.13 GUI retirement).**
This is the third round in a row Gemini flags this and CC overrules.
Source evidence:
- `CLAUDE.md` "Индекс модулей" → "main_window_v2.py — sole owner of
  shortcut bindings after the v1 `gui/main_window.py` was retired in
  Phase II.13"
- `CLAUDE.md` "ancillary widgets" section explicitly lists II.13 as
  "All `MainWindow`-era overlays … were deleted in II.13"
- `CHANGELOG.md` "Removed" section lists Phase II.13 widget deletions
  with file names

The README.md and the older Phase-II tracking table Gemini cites
predate II.13's close. CLAUDE.md is the canonical project overview;
README is operator-facing intro that lags. CC keeps the II.13-retired
phrasing.

## Top architect priorities

1. **Codex 03 — Hardware setup Т4 interlock regex (CRITICAL).** This is
   the most directly wrong sentence in the vault: it claims a master
   change that did not happen. Reader will form a wrong mental model
   of safety regression coverage. Same fix already applied in
   `30 Investigations/Cyrillic homoglyph in alarm config.md`; needs to
   propagate to Hardware setup.
2. **Codex 01 — Architecture overview ZMQ subprocess topology
   (CRITICAL).** Vault inverts which side runs the ZMQ subprocess.
   This is the kind of mistake that misleads someone debugging a
   future B1-class issue.
3. **Convergent A (Т4) + Codex 04 / Gemini 01 (plugin pipeline framing)
   together.** Both are propagation gaps from the integration loop —
   one note got fixed, the parallel notes carrying the same claim
   didn't. Suggests a "find-all-instances-of-this-claim" sweep
   pattern next time, not just per-file fix.

## What does NOT need architect attention

- LOW findings: zero from Codex, none from Gemini that were marked
  LOW. Bulk-accept not relevant this round.
- Already-deferred coverage gaps from overnight build (Web /
  Cooldown / Experiment / Interlock).
- Gemini 02 (Phase II.13 retirement) — CC overruled with source
  evidence; ledgered.

## Open architect decisions

1. **Six deferred subsystem notes** (was 4, now 6 — +Reporting +team-lead-skill).
   Should CC draft these in a follow-up session, or skip indefinitely?
   The team-lead skill is short and would slot under `50 Workflow/`;
   Reporting would be a full subsystem page comparable to
   `10 Subsystems/Calibration v2.md`.
2. **Approve fixes one-by-one, or batch by severity?** Recommended
   batch order if you want to act:
   - **Batch 1 (CRITICAL + convergent):** Codex 01 + 03 + Gemini 03
     (Т4 + ZMQ topology fixes — five-line edits across three notes,
     low risk, high impact).
   - **Batch 2 (HIGH):** Codex 02 + 04 + Gemini 01 (deployment caveat
     + plugin pipeline framing on the parallel notes — five-line
     edits, three more notes).
   - **Batch 3 (DEAD-END):** Gemini 05 (anchor fix + glossary add).
   - **Batch 4 (deferred-coverage list extension):** add Reporting +
     team-lead-skill to the deferred list; no edits, just ledgered.
3. **Сryodaq-team-lead skill placement.** If drafting:
   `50 Workflow/CryoDAQ team lead skill.md` digest, or merge as a
   subsection of `50 Workflow/Multi-model consultation.md`?
4. **Recurring pattern: integration-loop propagation gaps.** This
   round caught two cases where a Phase 3 fix landed in one note
   but not its peers (homoglyph fix → didn't reach Hardware setup;
   Plugin architecture fix → didn't reach Plugin isolation rebuild).
   Worth tightening the integration-loop process for next overnight
   build (e.g., grep-and-list-all-instances before fixing one)?

## Files

- Codex response (827 KB transcript, canonical findings at tail):
  `~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.response.md`
- Gemini response (table at bottom, retry banners at top):
  `~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.response.md`
- Briefs at the same directory.
