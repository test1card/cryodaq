# CryoDAQ — Retroactive Changelog Research

**Generated:** 2026-04-14  
**Commits covered:** 205 first-parent commits on `master` (234 total reachable commits)  
**Source data:** `git log --first-parent`, per-commit `git show --stat`, selected full commit messages/diffs, `docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`  
**Purpose:** source material for a rebuilt `CHANGELOG.md`. This is **not** the final changelog.

---

## How to use this document

This file is research output, not a polished release note. It is deliberately denser than a normal changelog because its audience is the future maintainer who needs to understand not just **what** changed, but also **why the work happened in that order**, which changes were operator-visible, and where the codebase’s current product shape actually came from.

The future `CHANGELOG.md` should be assembled from this document, not copied verbatim. Each section below groups commits into a **semantic cluster**: a coherent direction of work such as “GPIB recovery marathon” or “Calibration v2 rollout”. In the polished changelog, one cluster may collapse to one short bullet. Here it gets full context, file anchors, and a one-line explanation for every participating commit.

Version boundaries in this document are **proposals**. Only one real tag exists today, `v0.12.0` at `c22eca9`, so everything before and after it needs reconstruction. The proposal below is meant to make later assembly tractable: it gives a stable map of the history so that a human can decide where to compress and where to keep separation.

This document also preserves ambiguity honestly. Some early commits are “Add files via upload” task/docs drops rather than code changes. Some merge commits brought in whole feature branches as a single first-parent unit. Where intent is clear from commit body, I use it. Where intent is only inferable from ordering and diff shape, I say so.

The most important practical use is this: if someone six months from now asks “when did the project really become lab-usable?”, “why does `Reading.instrument_id` exist?”, “when did calibration v2 replace the old flow?”, or “why is `v0.12.0` not the same thing as current `0.13.0`?”, this document should answer that without re-reading 205 commits.

---

## Methodology

I walked the full first-parent history of `master` in chronological order. The current branch has **205** first-parent commits, not the **200** recorded in `docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`, because five documentation/audit commits landed after that archaeology pass. I used the archaeology document as the phase skeleton, then extended it with the extra five commits and with more detailed semantic grouping.

For small, self-describing commits, I relied on subject line plus `--stat`. For large commits, merge commits, safety-critical commits, or commits with generic titles, I inspected the full commit message and diff/stat. In practice this means I read full context for the major foundation drops (`603a472`, `9217489`, `dc2ea6a`, `445c056`) and merge commits, and lighter context for obviously narrow doc or chore commits.

In this document, a **cluster** means “a set of commits that together accomplish one logical goal”. A cluster can be one merge commit (`dc2ea6a`) or a marathon of eight iterative transport fixes (`5bc640c`..`7efb8b7`). Clusters are grouped into proposed versions so that the later polished changelog can say “this version introduced alarm v2” or “this version was mostly deployment hardening”, instead of reproducing the raw commit stream.

I deliberately did **not** use the stale `CHANGELOG.md` as a template. I read it only to confirm the prompt’s warning: it mixes retrospective guesses, duplicates some history, compresses unrelated work into single versions, and is no longer a trustworthy guide to how the code actually evolved.

Known limits:

- This is a first-parent narrative, not a full branch archaeology of every merged branch commit. For the four merge commits, the merge SHA is treated as the changelog unit, which is correct for operator-facing history but not for authorship archaeology.
- I did not inspect every large diff line by line. Some architectural intent inferences are still “inferred from context”.
- The proposed version scheme is practical, not canonical. It is designed to make later human assembly manageable while respecting the real `v0.12.0` tag.

---

## Version boundary proposal

**Proposal, not decision.** I recommend keeping the real `v0.12.0` tag exactly where it is, then reconstructing the rest of the history as a ladder of retroactive pre-`0.12.0` versions and untagged patch/minor releases after it. This keeps the current `pyproject.toml` claim of `0.13.0` intact, respects the one real historical anchor, and avoids pretending that the project had polished semver discipline during its initial 18-hour creation sprint.

The key principle behind this proposal is that the history has natural **release-quality plateaus**, not just dates:

- one sprint where the end-to-end system first existed at all
- one sprint where it became safer and lab-usable
- one integration point where the Codex RC branch redefined the product shape
- one real tagged production release
- then a sequence of post-tag field-hardening waves
- finally the structured Phase 2d/2e hardening track that justifies the current `0.13.0`

### Proposal table

| Version | Name | Date range | Commit count | Anchor commit | Rationale |
|---|---|---:|---:|---|---|
| 0.1.0 | Foundation | 2026-03-14..2026-03-14 | 41 | `9390419` | First complete end-to-end system: drivers, scheduler, storage, GUI, web, analytics, safety, cooldown, exports |
| 0.2.0 | Deployment Safeguards | 2026-03-14..2026-03-15 | 10 | `61dca77` | First audit/P0/P1 hardening wave; introduced first strong deployment contract changes |
| 0.3.0 | RC Convergence | 2026-03-17..2026-03-17 | 23 | `3b6a175` | Codex RC merge plus operator workflow, shift handover, calibration v2, phases, event logging |
| 0.12.0 | First Production Release | 2026-03-18 | 1 | `c22eca9` | Existing real tag; do not move it |
| 0.12.1 | Operational Surface Expansion | 2026-03-18..2026-03-19 | 31 | `7efb8b7` | Web/Telegram/pre-flight/alarm v2 plus first real hardware bring-up and GPIB recovery |
| 0.12.2 | Analytics and Safety Expansion | 2026-03-19..2026-03-21 | 15 | `1ec93a6` | Diagnostics, vacuum trend, safety phases 2–3, UI refactor merge |
| 0.12.3 | Integration Batch and Audit Merge | 2026-03-21..2026-03-23 | 25 | `29d2215` | Post-merge stabilization, final-batch merge, audit-v2 merge, Parquet v1, professional reporting |
| 0.12.4 | Deployment Hardening | 2026-03-23..2026-04-01 | 15 | `9feaf3e` | GPIB auto-recovery, GUI non-blocking fixes, launcher hardening, late audit cleanup |
| 0.12.5 | Audit Discovery and Pre-2d Hardening | 2026-04-08..2026-04-13 | 21 | `1d71ecc` | Structured Phase 1/2a/2b/2c hardening plus exhaustive audit/documentation rediscovery |
| 0.13.0 | Structured Hardening and Archive | 2026-04-13..2026-04-14 | 23 | `5b3ca29` | Phase 2d fail-closed/safety/persistence work, Phase 2e Parquet stage 1, and the audit corpus that validates it |

### Why this scheme

I rejected two alternatives:

1. **“Everything before `v0.12.0` should be 0.11.x or RC only.”**  
   This is too thin. It loses the meaningful distinction between “system exists”, “system became safer for the lab”, and “the RC merge changed the product surface”.

2. **“Treat `0.13.0` as only the Parquet work.”**  
   That would understate the actual significance of Phase 2d. The current `0.13.0` is semantically “structured safety and persistence hardening plus first archive stage”, not just one storage feature.

This proposal accepts that the numbering is retrospective and slightly irregular, but it makes the evolution readable. That is more important here than pretending the project followed a neat semver ritual from commit one.

---

## Version 0.1.0 — Foundation

### Rationale for this boundary

This version captures the initial creation burst on 2026-03-14: a single intense sprint in which CryoDAQ went from repository scaffold to a recognizable full-stack product. By the end of this version, the project already had the core technical identity it still has now: instrument drivers, SQLite persistence, ZMQ bridge, GUI, experiment lifecycle, safety architecture, analytics, and a cooldown predictor.

### Date range

2026-03-14..2026-03-14

### Commit range

`be52137`..`9390419`

### Themes in this version

- Foundation scaffolding and subsystem bootstrap (→ cluster 1.1)
- System completion: third instrument, operator tooling, launcher, conductivity chain (→ cluster 1.2)
- Safety foundation and persistence contract (→ cluster 1.3)
- Cooldown, overview, and export growth (→ cluster 1.4)

### Cluster 1.1 — Foundation scaffolding

**Commits:** `be52137`, `dea213f`, `f7cdc00`, `2882845`, `0c54010`, `577b02f`, `258f643`, `75ebdc1`, `e64b516`, `0b79fa1`, `baaec03`, `e4bbcb6`  
**Date range:** 2026-03-14 00:29..01:59  
**Files touched:** `pyproject.toml`, `CLAUDE.md`, `src/cryodaq/storage/sqlite_writer.py`, `src/cryodaq/core/scheduler.py`, `src/cryodaq/drivers/instruments/lakeshore_218s.py`, `src/cryodaq/drivers/instruments/keithley_2604b.py`, `src/cryodaq/engine.py`, `src/cryodaq/gui/main_window.py`, `src/cryodaq/core/experiment.py`, `src/cryodaq/web/server.py`  
**Size:** 61 files changed, 9721 insertions

**Context:** Before this cluster there was no CryoDAQ product, only an empty repo and a requirements/problem statement.

**Goal:** Create an end-to-end system fast enough to replace LabVIEW workflows in principle, even if many pieces were still rough.

**Approach:** The work moved breadth-first. Instead of perfecting one subsystem, Vladimir and Claude laid down all critical skeletons first: package metadata, driver abstraction, scheduler, broker, persistence, first real driver, power-source driver, alarm engine, GUI shell, experiment subsystem, notifications, and web monitoring. The architecture that later hardening work would refine is already visible here: engine as headless truth, GUI as client, ZMQ for IPC, SQLite for daily persistence, analytics as plugins, and Cryo-specific operator workflows on top.

**What changed:**
- Added: repository and package skeleton with driver ABC and `DataBroker` (`f7cdc00`)
- Added: `SQLiteWriter`, ZMQ bridge, and instrument scheduler (`2882845`)
- Added: LakeShore 218S driver and initial temperature GUI (`0c54010`)
- Added: Keithley 2604B TSP constant-power path, driver, and interlocks (`577b02f`)
- Added: first alarm engine and analytics plugin pipeline (`75ebdc1`)
- Added: engine/GUI entry points and main window shell (`0b79fa1`)
- Added: experiment lifecycle, replay/export, Telegram notifications (`baaec03`)
- Added: web dashboard and calibration stub (`e4bbcb6`)

**Breaking changes:** None yet. This is net-new surface creation.

**Operator-visible changes:** The first recognizable operator UI appeared here: live temperatures, alarms, instrument status, experiments, Telegram alerts, and early web monitoring.

**Config file changes:** Initial config set was born here: instruments, interlocks, alarms, notifications, and other core YAMLs began in this burst.

**API / contract changes:** Initial contracts only: `Reading`, driver interface, scheduler, ZMQ message flow, experiment manager, reporting hooks.

**Internal / architectural changes:** This is the real birth of the current architecture. Later phases mostly harden, refactor, and scope this shape rather than replace it wholesale.

**Why the order:** Breadth first was rational. A safety-critical DAQ is only meaningful if the whole data path exists: driver → scheduler → storage → broker → UI/notifications.

**Commit explanations (one line each):**
- `be52137`: added the first architecture/constraints document to keep subsequent work aligned
- `dea213f`: added the team-orchestration skill used in the early LLM-assisted workflow
- `f7cdc00`: created the Python package, source tree, base driver abstractions, and broker foundation
- `2882845`: added the first real persistence and polling loop architecture
- `0c54010`: brought in the first real instrument driver and its initial GUI surface
- `577b02f`: introduced Keithley power-source control and first-generation interlock logic
- `258f643`: expanded project rules with build commands and module index while the architecture was still forming
- `75ebdc1`: added the first analytics pipeline and alarm engine abstraction
- `e64b516`: deepened architecture docs and team-lead skill guidance
- `0b79fa1`: created the usable engine/GUI entry-point pairing and main operator shell
- `baaec03`: added experiments, archive/export, and Telegram-based operator workflows
- `e4bbcb6`: added web monitoring and the first calibration placeholder

### Cluster 1.2 — Foundation completion: third instrument, launcher, conductivity chain, connection settings

**Commits:** `33e51f3`, `e4546df`, `734f641`, `fdbeb95`, `3cb98dd`, `641f21e`, `167eb7d`, `3dbd222`, `da825f1`, `77638b0`, `dabce60`, `2f31378`, `84b01a7`, `b2b4d97`  
**Date range:** 2026-03-14 02:12..05:02  
**Files touched:** `src/cryodaq/gui/main_window.py`, `src/cryodaq/engine.py`, `src/cryodaq/gui/widgets/keithley_panel.py`, `config/instruments.yaml`, `config/notifications.yaml`, `create_shortcut.py`, `README.md`  
**Size:** 54 files changed, 9580 insertions, 272 deletions

**Context:** The first scaffold existed, but it still lacked the third physical instrument, operator documentation, launcher polish, conductivity workflow, and a serious test suite.

**Goal:** Turn the rough scaffold into a product-shaped lab application with all three hardware classes, a launcher, and broad regression coverage.

**Approach:** The work filled the missing edges: complete the hardware set (Thyracont), build the operator shell around the engine, add a conductivity workflow, then lock the emerging system down with a broad test drop.

**What changed:**
- Fixed: mock-mode and plugin init compatibility issues (`33e51f3`)
- Fixed: early timezone/WAL/test failures (`e4546df`)
- Added: 118-test comprehensive initial suite (`734f641`)
- Added: Keithley into `instruments.yaml` mock/dev path (`fdbeb95`)
- Fixed: Windows event-loop policy for pyzmq (`3cb98dd`)
- Added: Russian README and operator manual (`641f21e`, `3dbd222`)
- Added: Thyracont VSP63D driver, periodic reports, live web updates (`167eb7d`)
- Added: live Keithley, pressure, and analytics panels to make all tabs active (`da825f1`)
- Added: operator launcher and SQLite thread-safety fix (`77638b0`)
- Added: dual-channel Keithley control, Telegram commands, and portable deployment helpers (`dabce60`)
- Added: conductivity chain measurement and dedicated control surface (`2f31378`)
- Added: steady-state predictor and autosweep measurement panel (`84b01a7`)
- Added: channel manager and instrument connection settings UI (`b2b4d97`)

**Breaking changes:** None. This was still additive completion work.

**Operator-visible changes:** This cluster is where CryoDAQ stopped looking like a prototype and started looking like a lab workstation: launcher, all tabs live, pressure panel, conductivity measurement, connection settings, Russian-facing docs.

**Config file changes:** `instruments.yaml` and notification settings expanded; connection settings became user-facing.

**API / contract changes:** Notable new contracts include the early channel manager, connection settings surface, and dual-channel UI expectations.

**Internal / architectural changes:** The test suite arriving this early matters historically: a lot of the later hardening cadence depends on having a regression base already in place.

**Why the order:** Once all major contours existed, the highest-value next step was “finish the missing instrument and operator shell” rather than deep refactoring.

**Commit explanations:**
- `33e51f3`: fixed mock-mode and plugin-loader rough edges exposed by the first integrated runs
- `e4546df`: fixed five early test failures to stabilize the just-added core path
- `734f641`: established the first broad automated regression matrix
- `fdbeb95`: added Keithley to runtime instrument config for mock/dev workflows
- `3cb98dd`: fixed Windows/pyzmq compatibility via selector event loop
- `641f21e`: wrote the first substantial Russian README/status summary
- `167eb7d`: added the third real instrument plus periodic reporting and live web dashboard updates
- `3dbd222`: added a full Russian operator manual
- `da825f1`: made all major GUI tabs live rather than placeholders
- `77638b0`: added launcher behavior and fixed SQLite thread-safety assumptions
- `dabce60`: introduced dual-channel Keithley usage, Telegram command control, and portable deployment helpers
- `2f31378`: added the thermal conductivity measurement chain and its UI
- `84b01a7`: added steady-state prediction and autosweep workflow
- `b2b4d97`: added channel management and connection settings editing

### Cluster 1.3 — Safety foundation and persistence contract

**Commits:** `603a472`, `941d5e3`, `99df7eb`, `3f4b8fa`, `40b4ffb`, `efe16d3`, `dc5f3c6`, `a8e8bbf`  
**Date range:** 2026-03-14 13:29..18:18  
**Files touched:** `src/cryodaq/engine.py`, `src/cryodaq/core/safety_manager.py`, `src/cryodaq/core/safety_broker.py`, `src/cryodaq/storage/sqlite_writer.py`, `src/cryodaq/core/scheduler.py`, `CLAUDE.md`  
**Size:** 24 files changed, 3925 insertions, 455 deletions

**Context:** The morning foundation sprint had created a system, but it still did not encode the strongest lab-safety stance. Source-off as default and fail-on-silence had not yet become the governing rule.

**Goal:** Establish the first real safety architecture and define the persistence-before-publish invariant that later audits would treat as canonical.

**Approach:** The central move was `603a472`: add `SafetyManager`, `SafetyBroker`, explicit state transitions, fail-on-silence, recovery semantics, and engine wiring that routes source control through one authority. After that, audit fixes, updated docs, and explicit task documents captured the emerging doctrine. The cluster ends with `a8e8bbf`, which makes “disk before subscribers” explicit.

**What changed:**
- Added: `SafetyManager` FSM and `SafetyBroker` (`603a472`)
- Added: dedicated `safety.yaml` and operator manual safety section (`603a472`)
- Fixed: 13 early review issues around safety, tokens, thread-safety, and tests (`941d5e3`)
- Changed: project docs to reflect the new architecture (`99df7eb`)
- Added: task/design artifacts for team orchestration, persistence ordering, and cooldown integration (`3f4b8fa`, `40b4ffb`, `dc5f3c6`)
- Added: the large `cooldown_predictor.py` library file (`efe16d3`)
- Fixed: persistence-first ordering in scheduler path (`a8e8bbf`)

**Breaking changes:** Conceptually yes: source-off became the default and the engine started treating health proof as a prerequisite for source-on. For operators, that is a real behavioral break even if no API migration existed yet.

**Operator-visible changes:** Safety states, manual acknowledgment/recovery flow, and a stricter expectation that stale data means fault.

**Config file changes:** `config/safety.yaml` appears as a new control-plane config.

**API / contract changes:** This cluster is the birth of several enduring contracts: dedicated safety broker, source-control authority, persistence-first ordering, fault-latched semantics.

**Internal / architectural changes:** This is the deepest single architectural change before the Phase 2d hardening track.

**Why the order:** The team had already proven that the system could talk to hardware. The next rational step was making sure it failed conservatively rather than optimistically.

**Commit explanations:**
- `603a472`: introduced the six-state safety architecture and dedicated safety data channel
- `941d5e3`: applied a first broad review-fix pass across safety and concurrency concerns
- `99df7eb`: synchronized the docs with the newly changed safety and runtime reality
- `3f4b8fa`: rewrote the team-lead skill, reflecting the project’s first serious orchestration layer
- `40b4ffb`: added a dedicated persistence-ordering task/spec document
- `efe16d3`: dropped in the heavy cooldown-predictor library code used later by service/UI work
- `dc5f3c6`: added the cooldown-integration task/spec document
- `a8e8bbf`: explicitly enforced persistence-first ordering in the runtime path

### Cluster 1.4 — Cooldown and overview growth

**Commits:** `9217489`, `dd2dd2c`, `4dca478`, `b803967`, `7d8cc1f`, `68324c2`, `9390419`  
**Date range:** 2026-03-14 18:49..22:53  
**Files touched:** `src/cryodaq/analytics/cooldown_service.py`, `src/cryodaq/tools/cooldown_cli.py`, `src/cryodaq/engine.py`, `src/cryodaq/gui/widgets/analytics_panel.py`, `README.md`, `CLAUDE.md`  
**Size:** 23 files changed, 4679 insertions, 390 deletions

**Context:** Safety and persistence had just become explicit. The next gap was observability: predicting cooldown progress, surfacing overview status, and completing export/housekeeping UX.

**Goal:** Add higher-level operational intelligence on top of the raw acquisition engine.

**Approach:** Refactor the cooldown predictor into a reusable library, wrap it in a service, expose it in the GUI, then fill in the operator dashboard around it with overview panels, disk monitoring, and XLSX export.

**What changed:**
- Refactored and integrated cooldown prediction as service + GUI + CLI (`9217489`)
- Updated docs to treat cooldown integration and persistence-first as core system facts (`dd2dd2c`)
- Added safety-fix task capture (`4dca478`)
- Added overview dashboard, XLSX export, and disk monitor (`b803967`)
- Synced docs to the new overview/export shape (`7d8cc1f`)
- Added more uploaded task artifacts (`68324c2`, `9390419`)

**Breaking changes:** None.

**Operator-visible changes:** ETA/progress analytics, richer overview tab, spreadsheet export, disk-space visibility.

**Config file changes:** `config/cooldown.yaml` became part of the runtime contract.

**API / contract changes:** `CooldownService` and CLI tools were introduced; analytics became more service-oriented instead of script-oriented.

**Internal / architectural changes:** This cluster converted the project from “DAQ + UI” into “DAQ + UI + higher-level run-state analytics”.

**Why the order:** After basic safety was in place, operator value came from understanding long-running cooldowns and storage health rather than from adding yet another raw sensor panel.

**Commit explanations:**
- `9217489`: turned cooldown prediction from library draft into service, GUI, tests, and CLI
- `dd2dd2c`: updated architecture docs after cooldown integration and persistence-first work
- `4dca478`: added the safety-fix task note used for follow-on audit work
- `b803967`: added the overview dashboard, XLSX export, and disk monitoring
- `7d8cc1f`: synchronized docs to the overview/export state
- `68324c2`: added another uploaded planning artifact during the same sprint
- `9390419`: added another uploaded planning artifact closing out the foundation day

---

## Version 0.2.0 — Deployment Safeguards

### Rationale for this boundary

This version is the first disciplined corrective wave after the initial construction sprint. The system already existed; now the work turns to “what breaks before a first real lab run?” The answer yielded the first strong audit/P0/P1 cadence and the first intentionally breaking data-model change.

### Date range

2026-03-14..2026-03-15

### Commit range

`e9a538f`..`0078d57`

### Themes in this version

- Safety/P0/P1 hardening and the first breaking schema contract (→ cluster 2.1)
- Task capture for the next operator workflow and GUI passes (→ cluster 2.2)

### Cluster 2.1 — First audit wave, P0/P1 deployment fixes, and `instrument_id`

**Commits:** `e9a538f`, `678ff50`, `1bd6c4e`, `0f8dd59`, `de715dc`, `8d146bc`, `61dca77`  
**Date range:** 2026-03-14 23:17..2026-03-15 03:48  
**Files touched:** `src/cryodaq/core/safety_manager.py`, `src/cryodaq/storage/sqlite_writer.py`, `src/cryodaq/gui/widgets/keithley_panel.py`, `src/cryodaq/engine.py`, `README.md`, `CLAUDE.md`  
**Size:** 59 files changed, 3383 insertions, 316 deletions

**Context:** The system had breadth, but it had not survived a rigorous “would we trust this in the lab tomorrow?” pass.

**Goal:** Close the most dangerous correctness and deployment holes before serious lab use.

**Approach:** A layered hardening pattern emerged for the first time:

1. a broad safety fix sweep (`e9a538f`)
2. a named “P0 critical” wave (`1bd6c4e`)
3. a named “P1 lab deployment” wave (`de715dc`)
4. one breaking contract cleanup (`61dca77`)

The uploaded task documents around P0/P1 are historically important because they show the project already thinking in structured defect batches, not just opportunistic fixes.

**What changed:**
- Fixed: 14 safety review findings around latching, status checks, and heartbeat (`e9a538f`)
- Added: task note for P0 critical fixes (`678ff50`)
- Fixed: five critical issues including alarm pipeline, safety state publication, P/V/I limits, and latched emergency-off flag (`1bd6c4e`)
- Added: task note for P1 deployment fixes (`0f8dd59`)
- Fixed: eight deployment issues including async ZMQ, REAL timestamps, centralized paths, persistent aiohttp sessions (`de715dc`)
- Added: task notes for the next P2 items, including `instrument_id` (`8d146bc`)
- Breaking: promoted `Reading.instrument_id` to a first-class field (`61dca77`)

**Breaking changes:** Yes.

- `61dca77`: `Reading.instrument_id` became required/first-class. All driver output and downstream code had to adapt.

**Operator-visible changes:** More reliable alarms, safer Keithley limits, less blocking UI behavior, more robust experiment workflows.

**Config file changes:** Safety and deployment-related configs matured, but the biggest change was path/metadata discipline rather than new files.

**API / contract changes:** `Reading` changed in a way that affected all drivers and consumers.

**Internal / architectural changes:** This cluster is where CryoDAQ starts to look like a product that knows how to harden itself in named waves.

**Why the order:** The system was already broad enough that the next bottleneck was not missing features; it was correctness under real deployment pressure.

**Commit explanations:**
- `e9a538f`: applied the first named safety audit fix batch
- `678ff50`: captured P0 critical fixes as explicit task work
- `1bd6c4e`: closed five critical bugs in alarm, safety, and Keithley control paths
- `0f8dd59`: captured the P1 lab-deployment checklist as a task artifact
- `de715dc`: fixed eight deployment issues around async behavior, timestamps, paths, and session lifecycle
- `8d146bc`: documented the next contract cleanup work, especially `instrument_id`
- `61dca77`: made `instrument_id` part of the core `Reading` data model

### Cluster 2.2 — Task capture for the next operator workflow wave

**Commits:** `9d48c41`, `2afdbc1`, `0078d57`  
**Date range:** 2026-03-15 15:58..18:02  
**Files touched:** `task-gui-polish-phase3-close.md`, `task-dual-channel-smub.md`, `task-operator-workflow-calibration.md`  
**Size:** 3 files changed, 922 insertions

**Goal:** Freeze the next product-direction questions into explicit task artifacts before more code landed.

**Approach:** Instead of coding blindly, the project wrote down the next UI polish, dual-channel Keithley, and operator-workflow/calibration requirements.

**Why it mattered:** These commits are not operator-visible features, but they matter historically because they explain why the subsequent RC merge and post-merge work focused so heavily on dual-channel control, calibration, and operator workflow.

**Commit explanations:**
- `9d48c41`: documented the GUI polish and phase-3-close direction
- `2afdbc1`: documented the dual-channel `smub` work as an explicit task
- `0078d57`: documented operator workflow and calibration expectations

---

## Version 0.3.0 — RC Convergence

### Rationale for this boundary

This version is where the modern CryoDAQ product shape crystallized. The huge `dc2ea6a` merge imported the Codex RC branch, then the rest of the day was spent making that integrated product coherent: overview workflows, shift handover, calibration v2, experiment phases, auto-logging, and Russian-facing docs.

### Date range

2026-03-17..2026-03-17

### Commit range

`dc2ea6a`..`3b6a175`

### Themes in this version

- RC merge redefining the product surface (→ cluster 3.1)
- Overview/operator workflow maturation (→ cluster 3.2)
- Calibration v2 rollout (→ cluster 3.3)
- Experiment phases, event logging, and operator polish (→ cluster 3.4)

### Cluster 3.1 — Codex RC merge

**Commits:** `dc2ea6a`  
**Date range:** 2026-03-17 15:33  
**Files touched:** `src/cryodaq/analytics/calibration.py`, `src/cryodaq/core/experiment.py`, `src/cryodaq/core/housekeeping.py`, `src/cryodaq/engine.py`, `src/cryodaq/gui/widgets/archive_panel.py`, `src/cryodaq/gui/widgets/calibration_panel.py`, `src/cryodaq/gui/widgets/experiment_workspace.py`, `src/cryodaq/reporting/*`, `src/cryodaq/storage/sqlite_writer.py`  
**Size:** 83 files changed, 14690 insertions, 6632 deletions

**Goal:** Merge the CRYODAQ-CODEX RC branch into `master` and redefine the project around fuller operator workflows.

**Approach:** This merge did not just “add a feature”. It imported a large competing/productizing branch and made it the new mainline. The commit message names its semantic payload clearly: dual-channel Keithley, `CalibrationStore`, SRDG mode, experiment workspace, operator log, report generator, archive panel, calibration panel, adaptive throttle, retention policy.

**What changed:**
- Added: experiment/archive/report/operator-log workflow as first-class features
- Added: calibration backend and GUI as substantial product surface, not stub
- Added: housekeeping adaptive throttle and retention policy
- Changed: engine, scheduler, safety manager, Keithley driver, GUI, docs, tests, packaging metadata in one integration sweep
- Removed: a stack of task files that had been serving as branch-local planning artifacts

**Breaking changes:** Conceptually yes: the project’s center of gravity moved from “instrument dashboard” to “full experiment/report/archive workflow system”.

**Operator-visible changes:** Archive panel, calibration panel, richer experiment workspace, tray status, reporting, operator log, dual-channel Keithley behavior.

**Config file changes:** experiment templates, channels, housekeeping config, and other runtime YAMLs expanded to support the imported workflows.

**API / contract changes:** Many; this is the point where later `CLAUDE.md` descriptions start to resemble today’s product.

**Why the order:** The task-artifact cluster immediately before this merge shows why it happened when it did: the project had reached the point where a consolidated RC branch could redefine the mainline product.

**Commit explanations:**
- `dc2ea6a`: merged the Codex RC branch and changed CryoDAQ from a multi-panel lab UI into a full experiment/report/archive system

### Cluster 3.2 — Overview and operator workflow maturation

**Commits:** `29652a2`, `cdbba6c`, `b6ddb4e`, `f910c40`, `3dea162`, `a23ab92`, `dd663ae`, `a38154a`, `212e299`, `f4cb917`, `c848393`, `81c5a1d`, `2136623`  
**Date range:** 2026-03-17 16:00..19:16  
**Files touched:** `src/cryodaq/gui/widgets/overview_panel.py`, `src/cryodaq/launcher.py`, `src/cryodaq/gui/widgets/shift_handover.py`, `src/cryodaq/gui/main_window.py`  
**Size:** 16 files changed, 1427 insertions, 291 deletions

**Goal:** Make the new RC product usable by an operator, not just architecturally richer.

**Approach:** Most of this cluster is iterative UI and workflow shaping around `overview_panel.py`: add quick actions and quick log, structure shift handover, then repeatedly revise the two-column overview layout, plotting cadence, and card interaction until it feels operationally viable.

**What changed:**
- Added: dashboard hub with Keithley quick actions, quick log, experiment status (`b6ddb4e`)
- Added: structured shift handover workflow (`f910c40`)
- Changed: overview layout repeatedly toward a readable two-column, scrollable, splitter-based operator surface (`3dea162`, `a23ab92`, `dd663ae`, `f4cb917`, `c848393`)
- Fixed: launcher restored menu and `--mock` flag (`cdbba6c`)
- Improved: async ZMQ polling and plot-throttling to remove UI lag (`a38154a`, `212e299`)
- Fixed: tray duplicate and post-P0 audit leftovers (`81c5a1d`)
- Removed: dead `PressureStrip` class (`2136623`)

**Breaking changes:** None for external APIs. UX changed significantly.

**Operator-visible changes:** This is the cluster that made the overview tab into the dashboard hub operators would actually live in.

**Why the order:** Once the RC merge landed, there was no point in adding more deep backend features until the operator shell stopped fighting the operator.

**Commit explanations:**
- `29652a2`: cleaned merged branches and ignored local Claude workspace artifacts
- `cdbba6c`: restored launcher menu and added mock startup path
- `b6ddb4e`: turned overview into a dashboard hub with fast operator actions
- `f910c40`: added structured shift handover lifecycle
- `3dea162`: split overview and experiment workspace into clearer separate surfaces
- `a23ab92`: improved time axis readability and temperature card grid density
- `dd663ae`: reworked layout toward graph/info splitter behavior
- `a38154a`: moved overview polling onto async ZMQ worker pattern to remove lag
- `212e299`: reduced per-reading GUI work to improve plotting responsiveness
- `f4cb917`: synced temperature/pressure graphs and made cards clickable toggles
- `c848393`: tightened dynamic cards and experiment-form/button UX
- `81c5a1d`: fixed tray duplication and residual post-audit issues
- `2136623`: removed dead pressure-strip code and unused imports

### Cluster 3.3 — Calibration v2 rollout

**Commits:** `81ef8a6`, `e694d2d`, `38aca4f`, `98a5951`  
**Date range:** 2026-03-17 19:42..20:11  
**Files touched:** `src/cryodaq/core/calibration_acquisition.py`, `src/cryodaq/core/scheduler.py`, `src/cryodaq/analytics/calibration_fitter.py`, `src/cryodaq/gui/widgets/calibration_panel.py`, `src/cryodaq/engine.py`  
**Size:** 14 files changed, 1574 insertions, 1836 deletions

**Goal:** Replace the older calibration workflow with a more continuous and productized v2 path.

**Approach:** Break calibration into two halves:

- runtime continuous SRDG acquisition during calibration experiments
- post-run fitter pipeline that extracts, downsamples, breaks, and fits curves

Then expose that in a dedicated three-mode GUI and finally remove legacy session machinery so the new path becomes the default story.

**What changed:**
- Added: continuous SRDG acquisition during calibration experiments (`81ef8a6`)
- Added: post-run fitting pipeline (`e694d2d`)
- Added: three-mode calibration v2 GUI (`38aca4f`)
- Removed/cleaned: legacy sessions and docs for the old flow (`98a5951`)

**Breaking changes:** Effectively yes for workflow: the old calibration session path stopped being the primary route.

**Operator-visible changes:** Calibration became a real guided workflow instead of a loose collection of backend pieces.

**Config file changes:** calibration template and calibration-related docs evolved with this cluster.

**API / contract changes:** Calibration shifted toward SRDG capture + post-persist fit pipeline, a contract that later 2d hardening would refine.

**Why the order:** This had to come after the RC merge, because the RC merge provided the experiment/archive/reporting surfaces calibration v2 now plugs into.

**Commit explanations:**
- `81ef8a6`: introduced continuous SRDG acquisition during calibration experiments
- `e694d2d`: built the fitter pipeline for post-run extraction/downsample/breakpoints/fit
- `38aca4f`: added the three-mode calibration GUI
- `98a5951`: removed legacy session paths and synchronized docs to v2

### Cluster 3.4 — Experiment phases, event logging, and polish

**Commits:** `bc41589`, `aad5eab`, `d8421e6`, `7f0e5d1`, `3b6a175`  
**Date range:** 2026-03-17 20:36..22:06  
**Files touched:** `src/cryodaq/engine.py`, `src/cryodaq/core/experiment.py`, `src/cryodaq/core/event_logger.py`, GUI panels, docs  
**Size:** 30 files changed, 638 insertions, 69 deletions

**Goal:** Turn experiments into explicit phased workflows with better automatic logging and Russian-facing UI coherence.

**Approach:** Add phase tracking, automatic event logging and report generation on finalize, then follow with polish that makes those new workflows visually and linguistically coherent.

**What changed:**
- Fixed: DateAxisItem and Russian labels across the UI (`bc41589`)
- Added: experiment phase tracking from preparation to teardown (`aad5eab`)
- Added: automatic system event logging and auto-report on finalize (`d8421e6`)
- Fixed: audit/P1 polish around phase widget, empty states, and styling (`7f0e5d1`)
- Added: explicit calibration start button and Russian doc sync (`3b6a175`)

**Breaking changes:** None formal, but experiment handling became more structured and phase-driven.

**Operator-visible changes:** Phases, automatic event entries, better graph axes, cleaner Russian UI, easier calibration entry.

**Why the order:** Once calibration v2 and the new experiment workspace existed, it made sense to formalize phase transitions and automatic logging around them.

**Commit explanations:**
- `bc41589`: improved graph time axes and Russian-facing UI polish
- `aad5eab`: added explicit experiment phase lifecycle
- `d8421e6`: wired auto-logging and auto-report generation on finalize
- `7f0e5d1`: fixed the rough edges exposed by the new phase/event workflows
- `3b6a175`: added calibration-start affordance and synchronized docs

---

## Version 0.12.0 — First Production Release

### Rationale for this boundary

This version is defined by the **real tag** `v0.12.0` at `c22eca9`. It should remain a single-commit release marker in the rebuilt changelog, with the later same-day feature work treated as post-tag releases.

### Date range

2026-03-18

### Commit range

`c22eca9`..`c22eca9`

### Themes in this version

- Release cut and deployment checklist (→ cluster 4.1)

### Cluster 4.1 — Release cut for the first production release

**Commits:** `c22eca9`  
**Date range:** 2026-03-18 00:10  
**Files touched:** `pyproject.toml`, `README.md`, `CLAUDE.md`, `RELEASE_CHECKLIST.md`, `docs/first_deployment.md`, `CHANGELOG.md`  
**Size:** 9 files changed, 147 insertions, 20 deletions

**Goal:** Declare the first production release and align docs/checklists accordingly.

**Approach:** This is mostly metadata and deployment-doc work, which is exactly what a real release tag should look like.

**What changed:**
- Added: `docs/first_deployment.md`
- Changed: version markers and docs to reflect the release cut

**Operator-visible changes:** New deployment/first-deployment instructions.

**Why it mattered:** It is the one historical anchor that is not retrospective.

**Commit explanations:**
- `c22eca9`: created the `v0.12.0` release point and aligned project docs to it

---

## Version 0.12.1 — Operational Surface Expansion

### Rationale for this boundary

Immediately after the first production tag, the project expanded the operator/control surface and then hit real hardware. This version combines that same-day/same-next-day reality: new operational features, alarm v2, and the first intense bring-up cycle on real instruments.

### Date range

2026-03-18..2026-03-19

### Commit range

`7ee15de`..`7efb8b7`

### Themes in this version

- Web/Telegram/pre-flight/alarm v2 operator surfaces (→ cluster 5.1)
- Post-release stabilization (→ cluster 5.2)
- First hardware bring-up and protocol correction (→ cluster 5.3)
- GPIB recovery marathon (→ cluster 5.4)
- ZMQ subprocess isolation (→ cluster 5.5)

### Cluster 5.1 — Operator surfaces and alarm v2 rollout

**Commits:** `7ee15de`, `e553f11`, `ae70158`, `5678d96`, `4405348`, `88357b8`, `046ab6f`, `3f86b42`, `8070b2d`, `ac404db`, `d3b58bd`  
**Date range:** 2026-03-18 00:52..02:38  
**Files touched:** `src/cryodaq/notifications/telegram_commands.py`, `src/cryodaq/engine.py`, `src/cryodaq/core/alarm_v2.py`, `src/cryodaq/core/alarm_config.py`, `config/alarms_v3.yaml`, `src/cryodaq/gui/widgets/experiment_workspace.py`  
**Size:** 29 files changed, 4069 insertions, 43 deletions

**Goal:** Improve the operator control plane around the freshly tagged release.

**Approach:** Add monitoring surfaces and remote control first (web dashboard, Telegram bot v2, pre-flight checklist, autofill), then roll in the alarm v2 stack rapidly from foundation through UI.

**What changed:**
- Added: read-only monitoring web dashboard (`7ee15de`)
- Added: Telegram bot v2 commands and escalation chain (`e553f11`)
- Added: pre-flight checklist (`ae70158`)
- Added: experiment-form history autofill and suggested naming (`5678d96`)
- Fixed: Telegram polling startup bug (`4405348`)
- Added: alarm v2 foundation, evaluator, providers/config, engine integration, and GUI (`88357b8`, `046ab6f`, `3f86b42`, `8070b2d`, `d3b58bd`)
- Fixed: false undercool interlock and phase-gated detector warmup logic (`ac404db`)

**Breaking changes:** The main conceptual break is alarm-system complexity: the project now has a richer alarm v2 model alongside/over the simpler original alarm flow.

**Operator-visible changes:** This is a huge operator-facing cluster: web status page, Telegram commands, preflight checks, smarter experiment form, and a much richer alarm panel.

**Config file changes:** `alarms_v3.yaml` begins here.

**API / contract changes:** Alarm provider/setpoint/phase contracts emerge here; later phases harden them rather than invent them.

**Why the order:** The project had just declared “first production release”; the next practical step was to make it safer and more ergonomic to operate remotely and at startup.

**Commit explanations:**
- `7ee15de`: added the first read-only web monitoring surface
- `e553f11`: added Telegram bot v2 command and escalation behavior
- `ae70158`: added a formal pre-flight checklist before experiment start
- `5678d96`: added experiment form auto-fill and name suggestion based on history
- `4405348`: fixed bot polling startup/debug issues
- `88357b8`: introduced rate estimation and channel state tracking for alarm v2
- `046ab6f`: built the core evaluator for threshold/rate/stale/composite alarms
- `3f86b42`: added provider/config parsing layer for alarm v2
- `8070b2d`: integrated alarm v2 into engine runtime
- `ac404db`: fixed false detector/undercool logic after initial alarm v2 integration
- `d3b58bd`: exposed alarm v2 in the GUI and docs

### Cluster 5.2 — Post-release stabilization

**Commits:** `92e1369`, `e601ca9`, `c7ae2ed`  
**Date range:** 2026-03-18 10:45..10:59  
**Files touched:** `src/cryodaq/engine.py`, `src/cryodaq/core/rate_estimator.py`, `src/cryodaq/core/channel_state.py`, `src/cryodaq/web/server.py`, launcher/tray files  
**Size:** 11 files changed, 803 insertions, 64 deletions

**Goal:** Stop obvious post-release runtime leaks and reconnect glitches before deeper hardware bring-up.

**Approach:** Fix memory growth, rate-estimator/history caps, GUI reconnect plot emptiness, experiment status keys, and add tray-only monitoring.

**Commit explanations:**
- `92e1369`: fixed memory-leak patterns and bounded estimator/history state
- `e601ca9`: fixed empty plots after GUI reconnect and wrong experiment-status key
- `c7ae2ed`: added tray-only mode for headless engine monitoring

### Cluster 5.3 — First hardware bring-up and protocol correction

**Commits:** `d7c843f`, `4f717a5`, `8605a52`, `d0c40de`, `f3e62f5`, `d94e361`, `552f679`, `94ec2b6`, `1b5c099`  
**Date range:** 2026-03-18 17:12..2026-03-19 13:36  
**Files touched:** `src/cryodaq/drivers/instruments/keithley_2604b.py`, `src/cryodaq/drivers/instruments/thyracont_vsp63d.py`, `src/cryodaq/storage/sqlite_writer.py`, tests  
**Size:** 21 files changed, 1017 insertions, 192 deletions

**Context:** This is the first unmistakable “real hardware is exposing reality” cluster.

**Goal:** Make the instrument protocols and first deployment behavior match actual lab hardware rather than assumptions from mock mode.

**Approach:** Fix concrete bring-up failures: Thyracont turned out to require V1 probing instead of SCPI `*IDN?`; its pressure formula needed two successive corrections; Keithley source-off produced NaN that SQLite would not accept; safety rate checking needed to scope to critical channels; Keithley constant-power control moved from blocking TSP script to host-side loop.

**What changed:**
- Fixed: first hardware deployment batch across GPIB, Thyracont, Keithley source-off, alarms, pressure card, docs (`d7c843f`)
- Fixed: NaN source-off status crashing SQLite (`4f717a5`)
- Fixed: Thyracont connect probe and then formula/exponent decoding (`8605a52`, `d0c40de`, `f3e62f5`)
- Fixed: VISA bus lock for query termination race (`d94e361`)
- Fixed: rate check only for critical channels, excluding disconnected sensors (`552f679`)
- Changed: Keithley constant-power from blocking TSP script to host-side loop (`94ec2b6`)
- Added: live power-target update and stop-button repair (`1b5c099`)

**Breaking changes:** Yes, in implementation strategy: constant-power control migrated from embedded/blocking TSP behavior to host-side control loop.

**Operator-visible changes:** Better pressure readings, fewer crashes on source-off, live power-target update, more realistic safety rate behavior.

**Why the order:** The code had just met real instruments. This is the first history segment where the lab, not the design, clearly set the agenda.

**Commit explanations:**
- `d7c843f`: addressed the first concrete hardware deployment failures in one sweep
- `4f717a5`: fixed NaN-on-source-off persistence crash
- `8605a52`: changed Thyracont connect logic to V1 protocol probing
- `d0c40de`: corrected V1 pressure formula and Keithley parse edge cases
- `f3e62f5`: corrected the pressure value’s digit/exponent semantics again
- `d94e361`: added VISA bus locking against query-unterminated races
- `552f679`: restricted rate checks to truly critical channels
- `94ec2b6`: moved Keithley constant-power control to host side
- `1b5c099`: made power-target updates live and fixed stop behavior

### Cluster 5.4 — GPIB recovery marathon

**Commits:** `5bc640c`, `a0e9678`, `bb59488`, `946b454`, `fd229e9`, `31c4bae`, `5448f08`, `7efb8b7`  
**Date range:** 2026-03-19 14:05..16:21  
**Files touched:** `src/cryodaq/drivers/transport/gpib.py`, `src/cryodaq/drivers/instruments/lakeshore_218s.py`, `src/cryodaq/core/scheduler.py`, tests  
**Size:** 15 files changed, 783 insertions, 255 deletions

**Goal:** Make GPIB polling stable enough for real multi-instrument operation.

**Approach:** This cluster is iterative engineering under protocol stress. It tries several recovery models in sequence:

- widen lock coverage
- make open/query/verify atomic
- try open-per-query with IFC reset
- move to sequential polling by bus
- add and then remove `clear()` from the hot path
- correct KRDG query semantics
- finally settle on persistent sessions in a LabVIEW-like scheme

This is exactly the kind of cluster a polished changelog should compress to one bullet, but the research doc should preserve the iteration because it explains why the transport looks the way it does today.

**What changed:**
- Expanded: GPIB lock coverage around open/close and verify paths (`5bc640c`, `a0e9678`)
- Tried: open-per-query with IFC reset (`bb59488`)
- Refactored: sequential polling, one task per bus (`946b454`)
- Tried then backed off: `clear()` on every query (`fd229e9`, `31c4bae`)
- Fixed: KRDG command shape and GUI crash resilience (`5448f08`)
- Settled on: persistent sessions (`7efb8b7`)

**Breaking changes:** Internal transport semantics changed repeatedly; the external operator consequence was stability.

**Operator-visible changes:** Less hanging, fewer GPIB-induced freezes, more reliable LakeShore reads.

**Why the order:** This is classic hardware protocol stabilization: each step is a response to behavior observed under the previous step.

**Commit explanations:**
- `5bc640c`: widened the bus lock around resource lifecycle, not just query/write
- `a0e9678`: made open+verify atomic under the lock
- `bb59488`: tried open-per-query plus IFC reset for timeout recovery
- `946b454`: serialized polling per bus to avoid parallel bus contention
- `fd229e9`: added `clear()` to the hot path in search of robustness
- `31c4bae`: removed `clear()` from hot path and moved to write-delay-read
- `5448f08`: fixed KRDG query behavior and some GUI/ZMQ resilience issues
- `7efb8b7`: moved to persistent GPIB sessions in a LabVIEW-like open-once scheme

### Cluster 5.5 — ZMQ subprocess isolation

**Commits:** `f64d981`  
**Date range:** 2026-03-19 16:41  
**Files touched:** `src/cryodaq/core/zmq_subprocess.py`, `src/cryodaq/gui/zmq_client.py`, launcher/app files, tests  
**Size:** 6 files changed, 466 insertions, 120 deletions

**Goal:** Ensure the GUI never directly imports or lives inside ZMQ runtime assumptions that can destabilize it.

**Approach:** Move ZMQ handling into a subprocess boundary so the GUI process can stay cleaner and more restartable.

**Why it mattered:** This commit is a notable product-architecture stabilization point. Later GUI non-blocking and restart work builds on it.

**Commit explanations:**
- `f64d981`: isolated ZMQ into a subprocess so the GUI no longer imports `zmq` directly

---

## Version 0.12.2 — Analytics and Safety Expansion

### Rationale for this boundary

Once hardware bring-up stabilized enough, the project resumed expansion: richer analytics, more safety phases, and a feature-branch UI refactor merge. This version is about broadening operational intelligence rather than just patching hardware survival.

### Date range

2026-03-19..2026-03-21

### Commit range

`f64d981`..`1ec93a6`

### Themes in this version

- Diagnostics and vacuum analytics rollout (→ cluster 6.1)
- Safety phases 2–3 and review fixes (→ cluster 6.2)
- UI refactor merge (→ cluster 6.3)

### Cluster 6.1 — Diagnostics and vacuum analytics rollout

**Commits:** `856ad19`, `757f59e`, `6eb8dfe`, `b21bca1`, `5d7fe2b`, `c1b9eb5`, `50e30e3`  
**Date range:** 2026-03-20 13:04..14:39  
**Files touched:** `src/cryodaq/core/sensor_diagnostics.py`, `src/cryodaq/analytics/vacuum_trend.py`, `src/cryodaq/engine.py`, `config/plugins.yaml`, GUI panels and tests  
**Size:** 18 files changed, 3091 insertions, 15 deletions

**Goal:** Add higher-level sensor-health and vacuum-trend analytics, end to end.

**Approach:** Each feature arrived in a three-stage pattern:

- backend + tests
- engine/config integration
- GUI panel

This repeating rollout pattern is historically important because it becomes a standard project rhythm.

**What changed:**
- Added: Keithley safety slew/compliance plus ZMQ subprocess hardening (`856ad19`)
- Added: SensorDiagnostics backend, engine integration, GUI (`757f59e`, `6eb8dfe`, `b21bca1`)
- Added: VacuumTrend predictor backend, engine integration, GUI (`5d7fe2b`, `c1b9eb5`, `50e30e3`)

**Operator-visible changes:** New diagnostic and vacuum-prediction panels.

**Commit explanations:**
- `856ad19`: extended Keithley safety behavior and hardened the new subprocess ZMQ path
- `757f59e`: added sensor diagnostics backend with tests
- `6eb8dfe`: integrated sensor diagnostics into engine and config
- `b21bca1`: exposed diagnostics in the GUI and status summary
- `5d7fe2b`: added vacuum trend backend with tests
- `c1b9eb5`: integrated vacuum trend into engine and config
- `50e30e3`: exposed vacuum trend in the GUI

### Cluster 6.2 — Safety phases 2–3 and review fixes

**Commits:** `afabfe5`, `6ef43df`, `bbb5809`, `4b52de8`, `10d4d76`, `af94285`  
**Date range:** 2026-03-20 16:03..2026-03-21 00:39  
**Files touched:** `src/cryodaq/core/safety_manager.py`, `src/cryodaq/drivers/instruments/lakeshore_218s.py`, `plugins/phase_detector.py`, tests  
**Size:** 28 files changed, 1793 insertions, 131 deletions

**Goal:** Improve safety correctness and evolve the phase-detection story beyond the first implementation.

**Approach:** Mix targeted ZMQ serialization fixes with named safety phases 2 and 3, then sweep the fallout with a broader audit fix pass and GUI polish around adaptive liveness.

**What changed:**
- Fixed: datetime serialization and stuck REP socket behavior (`afabfe5`)
- Added: phase-2 safety hardening and tests (`6ef43df`)
- Added: phase-3 safety correctness/reliability plus phase detector (`bbb5809`)
- Fixed: deep review findings (`4b52de8`)
- Fixed: audit wave covering safety race, SQLite shutdown, Inf filter, phase reset, GPIB leak, deque cap (`10d4d76`)
- Fixed: CSV BOM, stretch/layout, report defaults, adaptive liveness (`af94285`)

**Operator-visible changes:** Better safety behavior, better exports, better dashboard liveness behavior.

**Commit explanations:**
- `afabfe5`: fixed ZMQ serialization and REP socket stuck-state edge cases
- `6ef43df`: applied the second named safety hardening wave
- `bbb5809`: applied the third named safety/correctness/reliability wave
- `4b52de8`: addressed deep-review issues with targeted fixes and tests
- `10d4d76`: closed a six-bug audit wave across safety, storage, and transport
- `af94285`: polished CSV, layout, report defaults, and adaptive liveness behavior

### Cluster 6.3 — UI refactor merge

**Commits:** `1ec93a6`  
**Date range:** 2026-03-21 02:39  
**Files touched:** `src/cryodaq/gui/widgets/conductivity_panel.py`, `src/cryodaq/gui/widgets/overview_panel.py`, startup scripts, minor analytics/config files  
**Size:** 20 files changed, 706 insertions, 147 deletions

**Goal:** Merge the UI refactor branch after the analytics/safety expansion work.

**Approach:** Bring in layout and launch-script changes that refine how the operator shell presents the richer backend introduced in the previous clusters.

**Why it mattered:** This merge closes one visible GUI evolution arc before the next post-merge stabilization batch begins.

**Commit explanations:**
- `1ec93a6`: merged `feature/ui-refactor` into `master`

---

## Version 0.12.3 — Integration Batch and Audit Merge

### Rationale for this boundary

This version is dominated by integration work: after the UI refactor merge, the project stabilizes the merged result, then folds in `final-batch`, then folds in `audit-v2`, and in the process grows Parquet and reporting substantially.

### Date range

2026-03-21..2026-03-23

### Commit range

`c427247`..`29d2215`

### Themes in this version

- Post-merge stabilization and audit wave 3 (→ cluster 7.1)
- Final-batch merge and follow-on fixes (→ cluster 7.2)
- Audit-v2 merge, Parquet v1, and reporting professionalization (→ cluster 7.3)

### Cluster 7.1 — Post-merge stabilization and audit wave 3

**Commits:** `c427247`, `a2f4bcd`, `1670bbe`, `2ab7283`, `dc84f0c`, `1dd7405`, `f08e6bb`  
**Date range:** 2026-03-21 02:54..12:35  
**Files touched:** docs, `src/cryodaq/gui/widgets/overview_panel.py`, `src/cryodaq/web/server.py`, `src/cryodaq/storage/sqlite_writer.py`, launcher and UI panels  
**Size:** 26 files changed, 279 insertions, 156 deletions

**Goal:** Get the freshly merged UI-refactor state back into a stable, documented, operator-safe shape.

**Approach:** Update documentation/versioning first, then fix safety, UI signal/layout/channel refresh issues, remove risky overview quick-start affordances, and do a compact audit-wave pass covering build ensemble, launcher ping, phase gap, and LakeShore raw-reading behavior.

**Commit explanations:**
- `c427247`: updated docs and version markers to the new mainline state
- `a2f4bcd`: fixed Thyracont fallback, SQLite read/write split, safety transition, Keithley disconnect path
- `1670bbe`: fixed UI card toggles, history loading, axis alignment, channel refresh
- `2ab7283`: cleaned defaults and deprecated `autosweep_panel`
- `dc84f0c`: removed overview quick-start buttons that could trigger unsafe `P=0` faults
- `1dd7405`: renamed Keithley tab and added time-window/forecast zone UI affordances
- `f08e6bb`: applied audit-wave fixes across forecast, launcher, phase gap, RDGST, and docs

### Cluster 7.2 — Final-batch merge and follow-on fixes

**Commits:** `9e2ce5b`, `7618031`, `4df40c3`, `0603110`, `9942da1`, `6d39a08`, `45ae750`, `031491a`, `dd42632`  
**Date range:** 2026-03-21 15:20..2026-03-22 00:25  
**Files touched:** `src/cryodaq/engine.py`, `src/cryodaq/launcher.py`, `src/cryodaq/gui/zmq_client.py`, `src/cryodaq/gui/widgets/overview_panel.py`  
**Size:** 16 files changed, 441 insertions, 183 deletions

**Goal:** Integrate the `final-batch` branch and repair the routing/single-instance/UI issues it exposed.

**Approach:** The merge itself is modest in diff size but big in semantic payload: single-instance guard, ML forecast integration, flight recorder, driver fixes. The follow-up commits then tighten the control plane: natural Telegram sorting, atomic single-instance lock, correlation IDs, future-per-request ZMQ routing, moving experiment I/O off the event loop, and more UI history-axis cleanup.

**Commit explanations:**
- `9e2ce5b`: merged `feature/final-batch`
- `7618031`: improved Telegram ordering/text and pressure chart limits
- `4df40c3`: made single-instance locking atomic with `O_CREAT|O_EXCL`
- `0603110`: added correlation IDs to command/reply routing
- `9942da1`: improved history loading and overview sync behavior
- `6d39a08`: moved experiment I/O to a thread and removed double report generation
- `45ae750`: introduced future-per-request ZMQ dispatcher with dedicated reply consumer
- `031491a`: polished labels, history channel passing, and polling resilience
- `dd42632`: snapped X-axis to data start across seven panels

### Cluster 7.3 — Audit-v2 merge, Parquet v1, and reporting professionalization

**Commits:** `0fdc507`, `fc1c61b`, `ccf98c9`, `f0c68c6`, `423c6d5`, `8dc07f7`, `a066cd7`, `b7265bb`, `29d2215`  
**Date range:** 2026-03-22 16:11..2026-03-23 00:37  
**Files touched:** `src/cryodaq/core/experiment.py`, `src/cryodaq/storage/parquet_archive.py`, `src/cryodaq/reporting/generator.py`, `src/cryodaq/reporting/sections.py`, `src/cryodaq/gui/widgets/preflight_dialog.py`  
**Size:** 32 files changed, 1616 insertions, 380 deletions

**Goal:** Merge the audit-v2 fix branch and then turn archive/reporting from MVP into something closer to a formal lab artifact pipeline.

**Approach:** The merge fixes 29 defects across engine, web, launcher, preflight, and docs. Immediately after that, the project adds a first Parquet archive path, CI, archive UI support for Parquet, and a major reporting makeover toward human-readable and then ГОСТ-styled outputs.

**What changed:**
- Merged: `fix/audit-v2` branch (`0fdc507`)
- Added: first Parquet experiment archive written on finalize (`fc1c61b`)
- Added: CI workflow (`ccf98c9`)
- Added/fixed: Parquet column and human-readable artifact handling in archive (`f0c68c6`)
- Fixed: archive date-range filtering and end-time column (`423c6d5`)
- Added: more professional human-readable report content (`8dc07f7`)
- Added: ГОСТ R 2.105-2019 formatting and graphs in all reports (`a066cd7`)
- Fixed: multi-channel graphs, heading styling, smart page breaks (`b7265bb`)
- Fixed: regression fallout across preflight severity, multi-day DB, overview resolver, Parquet docstrings (`29d2215`)

**Breaking changes:** Not formal API breaks, but reporting artifact expectations changed meaningfully here.

**Operator-visible changes:** Archive UI improved, reports became far more polished, Parquet became visible in archive workflows.

**Commit explanations:**
- `0fdc507`: merged audit-v2 fixes into master
- `fc1c61b`: added first Parquet archive writing path
- `ccf98c9`: added CI testing/lint workflow
- `f0c68c6`: added Parquet support in archive UI and fixed read behavior
- `423c6d5`: fixed archive end-date inclusivity and end-time visibility
- `8dc07f7`: upgraded reports toward operator/human readability
- `a066cd7`: moved reports toward ГОСТ-style formatting
- `b7265bb`: improved multi-channel graphs, headings, and page breaking
- `29d2215`: cleaned up regressions from the preceding archive/reporting changes

---

## Version 0.12.4 — Deployment Hardening

### Rationale for this boundary

This version is mostly about hardening the deployed product rather than expanding it: GPIB recovery, preflight severity semantics, GUI non-blocking behavior, launcher restart behavior, single-instance protection, and late audit cleanup.

### Date range

2026-03-23..2026-04-01

### Commit range

`ab57e01`..`9feaf3e`

### Themes in this version

- Recovery/preflight correctness (→ cluster 8.1)
- GUI non-blocking and deployment hardening (→ cluster 8.2)
- Late audit cleanup (→ cluster 8.3)

### Cluster 8.1 — Recovery and preflight fixes

**Commits:** `ab57e01`, `ea5a8da`, `86e8e8c`, `c10e617`, `dfd6021`  
**Date range:** 2026-03-23 14:59..2026-03-24 12:55  
**Files touched:** `src/cryodaq/core/scheduler.py`, `src/cryodaq/drivers/transport/gpib.py`, `src/cryodaq/gui/widgets/preflight_dialog.py`  
**Size:** 3 files changed, 197 insertions, 21 deletions

**Goal:** Make recovery and preflight behavior more truthful and less brittle.

**Approach:** Tighten GPIB recovery semantics, then make preflight sensor-health classification warning-level instead of hard error when appropriate, and teach scheduler to disconnect/reconnect standalone instruments after consecutive errors.

**Commit explanations:**
- `ab57e01`: added GPIB auto-recovery from hung instruments
- `ea5a8da`: escalated GPIB recovery with IFC reset and unaddressing
- `86e8e8c`: softened sensor-health preflight from error to warning
- `c10e617`: made scheduler disconnect/reconnect standalone instruments after repeated errors
- `dfd6021`: restored encoding and reaffirmed warning-level preflight sensor health

### Cluster 8.2 — GUI non-blocking and deployment hardening

**Commits:** `8bac038`, `6d0f5ba`, `bab4d8a`, `4eb5f1a`, `3c46dfb`, `e7d4fc5`, `f47762d`, `f217427`  
**Date range:** 2026-03-24 13:10..2026-03-25 12:59  
**Files touched:** `src/cryodaq/launcher.py`, `src/cryodaq/gui/zmq_client.py`, `src/cryodaq/instance_lock.py`, GUI panels, tests  
**Size:** 22 files changed, 570 insertions, 109 deletions

**Goal:** Remove remaining blocking GUI calls and harden process/instance behavior on operator PCs.

**Approach:** Convert alarm status polling and bridge health checks to non-blocking paths, add single-instance protection to launcher and standalone GUI, debounce live Keithley updates, fix 1080p experiment layout, harden launcher restart behavior, and fix shift modal/`--force` PermissionError edge cases.

**Commit explanations:**
- `8bac038`: made alarm-v2 status polling non-blocking in GUI
- `6d0f5ba`: fixed bridge-heartbeat false kills and launcher blocking `send_command`
- `bab4d8a`: added single-instance protection for launcher and standalone GUI
- `4eb5f1a`: fixed launcher bridge-health gap and conductivity-panel blocking calls
- `3c46dfb`: debounced Keithley spinboxes and made live updates non-blocking
- `e7d4fc5`: fixed experiment workspace layout for 1080p operator screens
- `f47762d`: made launcher engine restart non-blocking and hardened deployment path
- `f217427`: fixed shift modal re-entrancy and `engine --force` PermissionError

### Cluster 8.3 — Late audit cleanup

**Commits:** `9676165`, `9feaf3e`  
**Date range:** 2026-03-31..2026-04-01  
**Files touched:** `src/cryodaq/gui/widgets/experiment_workspace.py`, `src/cryodaq/gui/widgets/shift_handover.py`, `src/cryodaq/core/sensor_diagnostics.py`, `config/plugins.yaml`  
**Size:** 62 files changed, 906 insertions, 440 deletions

**Goal:** Clean up issues surfaced by Codex audit and reduce dead code / lingering blocking UI paths.

**Approach:** Fix concrete mismatches such as `plugins.yaml` Latin `T`, sensor-diagnostics resolution, and remaining GUI non-blocking holes, then do explicit dead-code cleanup.

**Commit explanations:**
- `9676165`: fixed Codex audit findings around plugin config, sensor diagnostics, and GUI non-blocking behavior
- `9feaf3e`: continued non-blocking send-command cleanup and dead code removal

---

## Version 0.12.5 — Audit Discovery and Pre-2d Hardening

### Rationale for this boundary

This version is unusual: it is less about end-user features and more about audit-driven rediscovery of the system before the structured Phase 2d program. It includes the Phase 1/2a/2b/2c hardening quartet, then a burst of deep audit documents, then a documentation-reality pass.

### Date range

2026-04-08..2026-04-13

### Commit range

`a60abc0`..`1d71ecc`

### Themes in this version

- Structured hardening phases 1/2a/2b/2c (→ cluster 9.1)
- Audit document burst and master triage (→ cluster 9.2)
- Reality-map rediscovery and CLAUDE refresh (→ cluster 9.3)

### Cluster 9.1 — Structured hardening phases 1, 2a, 2b, 2c

**Commits:** `a60abc0`, `0333e52`, `8a24ead`, `b185fd3`, `1698150`  
**Date range:** 2026-04-08 16:58..22:16  
**Files touched:** `src/cryodaq/engine.py`, `src/cryodaq/core/safety_manager.py`, `src/cryodaq/storage/sqlite_writer.py`, notifications, launcher, packaging files, docs  
**Size:** 70 files changed, 5279 insertions, 655 deletions

**Goal:** Run the first structured post-release hardening program before Phase 2d.

**Approach:** Instead of one-off fixes, the work is framed as named hardening passes:

- Phase 1 pre-deployment
- Phase 2a safety hardening
- Phase 2b observability/resilience
- Phase 2c final hardening before Phase 3

This cluster matters historically because it marks the transition from “fix issues as they appear” to “run planned safety/correctness phases”.

**Commit explanations:**
- `a60abc0`: fixed pre-deployment issues, especially around PyInstaller readiness
- `0333e52`: closed four high-severity safety findings in Phase 2a
- `8a24ead`: closed eight medium findings in Phase 2b around observability and resilience
- `b185fd3`: closed eight more findings in Phase 2c before the next planned phase
- `1698150`: small UI preset tweak (`Сутки` → `Всё`) landing at the end of the hardening burst

### Cluster 9.2 — Audit document burst and master triage

**Commits:** `380df96`, `fd99631`, `fd8c8bf`, `847095c`, `5d618db`, `10667df`, `31dbbe8`, `3e20e86`, `916fae4`, `a108519`, `24b928d`, `7aaeb2b`  
**Date range:** 2026-04-09 00:45..04:20  
**Files touched:** `DEEP_AUDIT_CC_POST_2C.md`, `DEEP_AUDIT_CODEX_POST_2C.md`, `HARDENING_PASS_CODEX.md`, `VERIFICATION_PASS_HIGHS.md`, `SAFETY_MANAGER_DEEP_DIVE.md`, `PERSISTENCE_INVARIANT_DEEP_DIVE.md`, `DRIVER_FAULT_INJECTION.md`, `DEPENDENCY_CVE_SWEEP.md`, `REPORTING_ANALYTICS_DEEP_DIVE.md`, `CONFIG_FILES_AUDIT.md`, `MASTER_TRIAGE.md`  
**Size:** 12 files changed, 9399 insertions

**Goal:** Generate a deep static-analysis corpus large enough to drive the next real hardening phase.

**Approach:** The project committed its audit trail into the repo rather than keeping it ephemeral. This is historically significant because the later Phase 2d/2e work clearly responds to this audit corpus.

**What changed:** one repo-internal audit dossier after another, culminating in `MASTER_TRIAGE.md`.

**Why it mattered:** A later maintainer will not be able to understand Phase 2d without this cluster.

**Commit explanations:**
- `380df96`: added CC deep audit pass after Phase 2c
- `fd99631`: added Codex deep audit pass after Phase 2c
- `fd8c8bf`: gitignored local audit artifacts
- `847095c`: cherry-picked the hardening-pass audit document from the UI branch
- `5d618db`: verified the five high-severity findings from hardening pass
- `10667df`: added exhaustive `SafetyManager` FSM analysis
- `31dbbe8`: added exhaustive persistence-invariant trace
- `3e20e86`: added driver failure-mode analysis
- `916fae4`: added dependency/CVE sweep
- `a108519`: added reporting/analytics/plugins deep dive
- `24b928d`: added config-file audit
- `7aaeb2b`: synthesized the entire audit history into master triage

### Cluster 9.3 — Reality-map rediscovery and CLAUDE refresh

**Commits:** `995f7bc`, `6eb7d3e`, `ddf6459`, `1d71ecc`  
**Date range:** 2026-04-12 23:25..2026-04-13 16:09  
**Files touched:** `DOC_REALITY_MAP.md`, `CLAUDE.md`, `.claude/skills/cryodaq-team-lead.md`  
**Size:** 3 files changed, 700 insertions, 270 deletions

**Goal:** Reconcile docs/spec/assistant guidance with the codebase that had actually emerged.

**Approach:** Build a “doc vs code reality map”, then rewrite the assistant skill and `CLAUDE.md` around the current system instead of the stale remembered one.

**Commit explanations:**
- `995f7bc`: built the doc-vs-code reality map
- `6eb7d3e`: rewrote the team-lead skill against current code reality
- `ddf6459`: filled missing config files into `CLAUDE.md`
- `1d71ecc`: expanded module index and corrected safety FSM/invariants in `CLAUDE.md`

---

## Version 0.13.0 — Structured Hardening and Archive

### Rationale for this boundary

This is the current unreleased line in `pyproject.toml`, and it has the right shape for it: not one feature, but a coordinated hardening campaign with named blocks, external review feedback loops, fail-closed config loading, persistence corrections, and the first streaming Parquet archive stage. The trailing audit/inventory docs on 2026-04-14 are part of this version’s evidence base even if they are not runtime code.

### Date range

2026-04-13..2026-04-14

### Commit range

`88feee5`..`5b3ca29`

### Themes in this version

- Phase 2d block A safety/alarm hardening (→ cluster 10.1)
- Phase 2d block B persistence hardening (→ cluster 10.2)
- Phase 2d closure and fail-closed completion (→ cluster 10.3)
- Phase 2e Parquet streaming stage 1 (→ cluster 10.4)
- Audit/inventory/documentation tail (→ cluster 10.5)

### Cluster 10.1 — Phase 2d block A: safety/alarm hardening

**Commits:** `88feee5`, `1446f48`, `ebac719`, `1b12b87`, `e068cbf`  
**Date range:** 2026-04-13 16:27..20:53  
**Files touched:** `src/cryodaq/core/safety_manager.py`, `src/cryodaq/core/alarm_v2.py`, `src/cryodaq/core/alarm_config.py`, `src/cryodaq/engine.py`, `config/alarms_v3.yaml`, tests, web XSS tests  
**Size:** 15 files changed, 757 insertions, 89 deletions

**Goal:** Close the highest-risk safety and alarm configuration findings discovered by the audit corpus.

**Approach:** Block A starts with a broad sweep (web XSS fix, `SafetyManager` hardening, `safety.yaml` fail-closed, Latin `T` regression). Two fix commits immediately follow to close findings discovered during review. Then block A.2 hardens alarm config and adds safety-to-operator-log bridging and acknowledge semantics, followed by another targeted fix commit.

**What changed:**
- Fixed: stored web XSS path and `SafetyManager` cancellation/state issues (`88feee5`)
- Fixed: `RUN_PERMITTED` heartbeat gap and introduced `SafetyConfigError` (`1446f48`)
- Fixed: coercion wrapping and critical-channel validation (`ebac719`)
- Added/hardened: `AlarmConfigError`, acknowledge implementation, safety→experiment/operator-log bridge (`1b12b87`)
- Fixed: block-A review fallout (`e068cbf`)

**Breaking changes:** Yes for config semantics: bad safety/alarm config now fails closed instead of limping onward.

**Operator-visible changes:** Better fault visibility, safer startup refusal on bad configs, corrected XSS behavior in web log rendering.

**Commit explanations:**
- `88feee5`: launched Phase 2d with web XSS fix and core `SafetyManager` hardening
- `1446f48`: closed the heartbeat/config-class gaps found in the first block-A review
- `ebac719`: tightened `SafetyConfigError` wrapping and validation
- `1b12b87`: hardened alarm config and bridged safety faults into experiment/operator context
- `e068cbf`: fixed the remaining issues exposed by review of `1b12b87`

### Cluster 10.2 — Phase 2d block B: persistence hardening

**Commits:** `d3abee7`, `5cf369e`, `104a268`, `21e9c40`, `23929ca`  
**Date range:** 2026-04-13 21:50..23:22  
**Files touched:** `src/cryodaq/storage/sqlite_writer.py`, `src/cryodaq/core/scheduler.py`, `src/cryodaq/core/experiment.py`, `src/cryodaq/core/calibration_acquisition.py`, tests  
**Size:** 13 files changed, 722 insertions, 46 deletions

**Goal:** Close data-integrity gaps in file writing, WAL verification, status persistence, calibration atomicity, and shutdown drain behavior.

**Approach:** First add atomic sidecar writes and explicit WAL verification, then apply a shielding follow-up, then land the main persistence-integrity batch: OVERRANGE persist, atomic KRDG/SRDG persistence, scheduler graceful drain. A quick fix follows to drop NaN-valued statuses from the persist set, and then the checkpoint commit records the block as complete.

**Commit explanations:**
- `d3abee7`: added atomic file writes and WAL verification
- `5cf369e`: followed up on post-fault cancellation shielding holes
- `104a268`: landed the main persistence-integrity batch
- `21e9c40`: dropped NaN-valued statuses from persistence to avoid NOT NULL failures
- `23929ca`: recorded the A+B checkpoint in `PROJECT_STATUS`

### Cluster 10.3 — Phase 2d closure and fail-closed completion

**Commits:** `efe6b49`, `f4c256f`, `74f6d21`, `89ed3c1`, `0cd8a94`  
**Date range:** 2026-04-14 01:14..02:36  
**Files touched:** `src/cryodaq/core/scheduler.py`, `src/cryodaq/core/safety_manager.py`, `src/cryodaq/core/interlock.py`, `src/cryodaq/core/calibration_acquisition.py`, `src/cryodaq/engine.py`  
**Size:** 131 files changed, 3360 insertions, 635 deletions

**Goal:** Close out Phase 2d cleanly, including the last config fail-closed and ordering/state-mutation gaps found by review.

**Approach:** Two chores clean up accumulated lint/log debris, then Jules round-2 fixes land the `_fault()` ordering and calibration-state deferral corrections, then block C-1 completes interlock/housekeeping/channels fail-closed loading and drain-timeout config, and finally `0cd8a94` declares Phase 2d complete.

**Breaking changes:** Yes for startup behavior: more configs now fail closed rather than silently defaulting.

**Commit explanations:**
- `efe6b49`: reduced accumulated lint debt
- `f4c256f`: removed accidentally committed logs and ignored them
- `74f6d21`: closed ordering and calibration state-mutation gaps
- `89ed3c1`: completed fail-closed loading for the remaining safety-adjacent configs and exposed drain-timeout config
- `0cd8a94`: declared Phase 2d complete and opened Phase 2e

### Cluster 10.4 — Phase 2e Parquet streaming stage 1

**Commits:** `445c056`  
**Date range:** 2026-04-14 02:55  
**Files touched:** `src/cryodaq/storage/parquet_archive.py`, `src/cryodaq/core/experiment.py`, Parquet tests  
**Size:** 4 files changed, 365 insertions, 228 deletions

**Goal:** Replace the earlier in-memory Parquet path with a streaming finalize-time archive writer.

**Approach:** Introduce a new streaming writer that walks daily SQLite files in chunks and writes `readings.parquet` via `pyarrow.ParquetWriter`, then hook it into experiment finalization as a best-effort artifact path.

**Operator-visible changes:** Archive generation becomes more scalable and produces `readings.parquet` as part of experiment finalization when archive extras are installed.

**Commit explanations:**
- `445c056`: added streaming Parquet export stage 1 and removed the older in-memory API

### Cluster 10.5 — Audit/inventory/documentation tail

**Commits:** `855870b`, `5ad0156`, `1c75967`, `66f9870`, `6535c9a`, `88c308c`, `5b3ca29`  
**Date range:** 2026-04-14 03:26..04:19  
**Files touched:** `docs/audits/BRANCH_INVENTORY.md`, `docs/audits/REPO_INVENTORY.md`, `docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`, `docs/audits/CODEX_ROUND_2_AUDIT.md`, `PROJECT_STATUS.md`  
**Size:** 13 files changed, 3870 insertions, 4 deletions

**Goal:** Preserve the state of the large three-track review program that accompanied the Phase 2d/2e closure.

**Approach:** Add branch inventory, repo inventory, dead-code and findings summary, Codex round-2 semantic audit, CC round-2 inventory, branch cleanup record, and a final `PROJECT_STATUS` update. The historical pre-Phase-2c audit artifacts are then committed as an explicit archival act.

**Why it mattered:** These are not runtime features, but they are part of the historical source material from which the current confidence in `0.13.0` is derived. A future maintainer reading the changelog should know that this version was not declared on intuition alone.

**Commit explanations:**
- `855870b`: added branch inventory for the three-track audit
- `5ad0156`: added repo inventory, dead-code scan, and CC findings summary
- `1c75967`: added Codex round-2 extended semantic audit
- `66f9870`: added CC round-2 extended inventory
- `6535c9a`: recorded remote branch cleanup
- `88c308c`: updated `PROJECT_STATUS` numbers after round-2 audit
- `5b3ca29`: committed historical pre-Phase-2c audit artifacts into the repo

---

## Cross-version patterns

### Pattern: Safety architecture evolution

The safety story has three clear eras.

1. **Birth of the architecture** — `603a472`  
   This is where `SafetyManager`, `SafetyBroker`, fail-on-silence, latched faults, and source-off-by-default enter the codebase as the governing model.

2. **Operational correction and scope refinement** — `e9a538f`, `1bd6c4e`, `552f679`, `6ef43df`, `bbb5809`, `10d4d76`  
   These commits do not replace the architecture; they tune it toward real deployment: status checks, heartbeat behavior, critical-channel scoping, phase detector, rate/Inf handling, and review-driven correctness fixes.

3. **Structured hardening and fail-closed discipline** — `88feee5`..`89ed3c1`  
   Phase 2d moves from ad hoc correctness to invariants: config files fail closed, cancellation paths are shielded, alarm acknowledge becomes explicit, calibration and fault-ordering semantics are reviewed externally.

The key historical point is that safety did not “arrive late”. It arrived early, then spent a month being made less accidental and more enforceable.

### Pattern: GPIB transport stabilization

GPIB is one of the clearest examples of why a research document is needed. A polished changelog would say “improved GPIB stability”. The real history is:

- first hardware run exposed bus/query termination problems (`d7c843f`, `d94e361`)
- the team tried wider locks (`5bc640c`, `a0e9678`)
- then open-per-query plus bus reset (`bb59488`)
- then sequential polling (`946b454`)
- then `clear()` in hot path (`fd229e9`)
- then removing `clear()` in hot path (`31c4bae`)
- then correcting KRDG command behavior (`5448f08`)
- finally settling on persistent sessions (`7efb8b7`)
- later adding escalated recovery and standalone reconnect (`ab57e01`, `ea5a8da`, `c10e617`)

This pattern matters because it explains both the complexity of the current transport layer and the strong project skepticism toward “simple” GPIB fixes.

### Pattern: Calibration evolution

Calibration moved through four distinct shapes:

1. **Stub presence** — `e4bbcb6`
2. **RC merge introduces real calibration store and GUI surface** — `dc2ea6a`
3. **Calibration v2 redesign** — `81ef8a6`, `e694d2d`, `38aca4f`, `98a5951`  
   continuous SRDG acquisition + post-run fitter + three-mode GUI replaces the old session story
4. **Hardening of calibration persistence semantics** — `104a268`, `74f6d21`  
   atomic KRDG/SRDG persistence and deferred state mutation after successful write

This pattern is essential for later changelog wording because “Calibration v2” is not one commit or one date; it is a multi-version arc.

### Pattern: Config loading discipline

Early CryoDAQ used configs, but it did not always enforce them strictly. The evolution is:

- configs appear early as operational necessities
- safety and alarm behavior become increasingly config-driven through `v0.12.1` and `v0.12.2`
- audits in `0.12.5` identify that several important files still fail open or fall back loosely
- Phase 2d in `0.13.0` makes fail-closed loading a named invariant for safety, alarms, interlocks, housekeeping, and channels

In other words, the project’s maturity is visible in how it treats bad config: from “best effort” to “refuse to start”.

### Pattern: Test coverage growth

Test coverage grows in waves rather than linearly:

- `734f641`: first large suite drop
- `dc2ea6a`: RC merge imports major new test surface
- analytics rollouts (`9217489`, diagnostics, vacuum trend) each bring bundled tests
- safety phases 2–3 and audit waves add focused regression packs
- `0.12.5` audit documents then start pointing out not just missing tests, but **wrong kinds of tests** (structural vs behavioral, stale APIs)

This is why the later audit documents belong in history: they changed the testing culture, not just the test count.

### Pattern: Product identity expansion

CryoDAQ does not evolve linearly from “DAQ” to “DAQ plus one more feature”. Instead it expands in concentric rings:

1. raw DAQ and safety
2. operator shell and launcher
3. experiment lifecycle / archive / reporting
4. remote/secondary surfaces: web, Telegram, tray
5. predictive analytics and diagnostics
6. structured hardening and artifact-quality output

That pattern is useful later when writing human-facing release notes: many changes make more sense as “the product gained a new ring” than as isolated features.

---

## Deprecations timeline

| Version | Item | Deprecated in | Removed in | Notes |
|---|---|---|---|---|
| 0.12.3 | `autosweep_panel` | `2ab7283` | not yet | Explicitly marked deprecated during post-UI-refactor cleanup |
| 0.13.0 | `CalibrationAcquisitionService.on_readings()` as primary API | `89ed3c1` | not yet | Migration path is split `prepare_srdg_readings()` + `on_srdg_persisted()` |
| 0.13.0 | old in-memory Parquet export API | `445c056` | `445c056` | Replaced by streaming finalize-time Parquet writer |

---

## Breaking changes timeline

| Version | Change | Commit | Affects | Migration |
|---|---|---|---|---|
| 0.2.0 | `Reading.instrument_id` becomes first-class/required | `61dca77` | All drivers, storage, broker, UI, exports | Populate `instrument_id` in every emitted `Reading` |
| 0.12.1 | Keithley constant-power control moves from blocking TSP path to host-side loop | `94ec2b6` | Keithley runtime semantics, safety behavior, expectations around instrument autonomy | Treat host runtime as authority for constant-power loop |
| 0.13.0 | safety/alarm/interlock/housekeeping/channels config loading becomes fail-closed | `88feee5`..`89ed3c1` | Startup behavior, deployment scripts, local overrides | Fix malformed/missing config instead of relying on fallback behavior |
| 0.13.0 | calibration acquisition API split into pre-persist and post-persist phases | `89ed3c1`, `74f6d21` | Calibration callers/tests | Use `prepare_srdg_readings()` and `on_srdg_persisted()`; `on_readings()` is compatibility-only |

---

## Operator-facing changes highlights

### Version 0.1.0

- First complete CryoDAQ surface: engine, GUI, web, storage, analytics, reporting scaffold
- LakeShore, Keithley, and later Thyracont support appear
- Overview/dashboard, conductivity, autosweep, connection settings, launcher, operator docs all emerge in one day
- Safety architecture and persistence-first ordering become visible

### Version 0.2.0

- Much safer first-lab behavior after audit/P0/P1 waves
- Safer limits, better alarm publication, non-blocking ZMQ direction, more stable timestamps/paths
- `instrument_id` becomes part of the data model

### Version 0.3.0

- Archive panel, report generation, operator log, experiment workspace, calibration panel become real product surfaces
- Shift handover, experiment phases, auto-logging, auto-reporting arrive
- Overview tab becomes the actual operational dashboard

### Version 0.12.0

- First formal production release with deployment/first-deployment documentation

### Version 0.12.1

- Web dashboard, Telegram bot v2, pre-flight checklist, smarter experiment form
- Alarm v2 stack arrives
- Hardware bring-up dramatically improves GPIB/Keithley/Thyracont realism and stability
- ZMQ subprocess isolation improves GUI/process boundary

### Version 0.12.2

- Sensor diagnostics and vacuum trend panels arrive
- Safety phases 2–3 add more reliability and phase-awareness
- UI refactor merge modernizes pieces of the shell

### Version 0.12.3

- Parquet archive v1 appears
- Reporting becomes much more formal and operator-friendly
- Single-instance and command-routing behavior harden further

### Version 0.12.4

- Better hung-instrument recovery
- Fewer blocking GUI actions
- Better launcher/standalone instance behavior on operator PCs

### Version 0.12.5

- Large audit corpus lands in-repo
- Structured hardening phases 1/2a/2b/2c prepare the project for the final safety push
- Docs/assistant rules are reconciled with actual code reality

### Version 0.13.0

- Phase 2d makes fail-closed config loading, cancellation shielding, and persistence corrections first-class invariants
- Phase 2e begins with streaming Parquet archive generation
- The repo now contains the audit evidence validating this state

---

## Open questions

1. Should `0.12.1` be split into two retroactive releases, one for operator surfaces/alarm v2 and another for hardware bring-up? The current proposal keeps them together because they are temporally continuous and both are “post-tag operationalization”.
2. Should the `0.12.5` boundary start at `9676165`/`9feaf3e` instead of `a60abc0`, making the late audit cleanup part of the pre-2d story rather than the end of deployment hardening?
3. Does the polished changelog want to mention the giant 2026-04-09 audit-document burst as a historical milestone, or compress it to one note such as “comprehensive external audits performed”?
4. Is `0.3.0` the right retroactive number for the RC convergence day, or would `0.11.0-rc1` be a better presentation layer while keeping this research document’s cluster boundaries unchanged?
5. Should `0.13.0` in the polished changelog stop at `445c056` and treat the following audit/inventory commits as “validation artifacts not part of the release narrative”, or is it more helpful to keep them attached to the version that they validate?
6. The unmerged UI branches (`feat/ui-phase-1`, `feat/ui-phase-1-v2`) are intentionally excluded here. If they merge later, should they become `0.14.0` or a separately named UI track?

---

## Appendix — Chronological first-parent inventory

This appendix is not the main narrative. It exists so a future maintainer can verify that the cluster coverage above really spans the whole first-parent chain.

| # | SHA | Date | Subject |
|---:|---|---|---|
| 1 | `be52137` | 2026-03-14T00:29:31+03:00 | Add CLAUDE.md with project architecture and constraints |
| 2 | `dea213f` | 2026-03-14T00:31:54+03:00 | Add cryodaq-team-lead skill for agent team orchestration |
| 3 | `f7cdc00` | 2026-03-14T00:35:21+03:00 | Add project foundation: pyproject.toml, directory structure, driver ABC, DataBroker |
| 4 | `2882845` | 2026-03-14T00:39:41+03:00 | Add SQLiteWriter, ZMQ bridge, and instrument Scheduler |
| 5 | `0c54010` | 2026-03-14T00:43:37+03:00 | Add LakeShore 218S driver, temperature panel GUI, and tests |
| 6 | `577b02f` | 2026-03-14T01:18:12+03:00 | Keithley 2604B: TSP P=const, driver, interlocks |
| 7 | `258f643` | 2026-03-14T01:19:37+03:00 | Update CLAUDE.md with build commands, data flow, and module index |
| 8 | `75ebdc1` | 2026-03-14T01:23:47+03:00 | Add AlarmEngine, analytics plugin pipeline, and two plugins |
| 9 | `e64b516` | 2026-03-14T01:25:46+03:00 | Add full architecture doc and team lead SKILL v2 |
| 10 | `0b79fa1` | 2026-03-14T01:48:48+03:00 | Engine + GUI: entry points, main window, alarm panel, instrument status |
| 11 | `baaec03` | 2026-03-14T01:53:55+03:00 | Experiment lifecycle, data export, replay, Telegram notifications |
| 12 | `e4bbcb6` | 2026-03-14T01:59:20+03:00 | Web dashboard, calibration stub, gitignore, updated docs |
| 13 | `33e51f3` | 2026-03-14T02:12:20+03:00 | Fix mock mode: stub interlock actions, plugin loader init compat |
| 14 | `e4546df` | 2026-03-14T02:15:32+03:00 | Fix 5 test failures: timezone, WAL check, mock range, timeout setup |
| 15 | `734f641` | 2026-03-14T02:27:30+03:00 | Add comprehensive test suite: 118 tests across all modules |
| 16 | `fdbeb95` | 2026-03-14T02:33:38+03:00 | Add Keithley 2604B to instruments.yaml (USB-TMC mock) |
| 17 | `3cb98dd` | 2026-03-14T02:41:18+03:00 | Fix Windows event loop: SelectorEventLoop for pyzmq compatibility |
| 18 | `641f21e` | 2026-03-14T02:42:39+03:00 | Add README.md: architecture, quick start, project status (Russian) |
| 19 | `167eb7d` | 2026-03-14T03:13:22+03:00 | Thyracont VSP63D driver, periodic reports, live web dashboard |
| 20 | `3dbd222` | 2026-03-14T03:18:47+03:00 | Add comprehensive operator manual in Russian (docs/operator_manual.md) |
| 21 | `da825f1` | 2026-03-14T03:27:55+03:00 | GUI: Keithley, pressure, analytics panels — all tabs now live |
| 22 | `77638b0` | 2026-03-14T03:40:26+03:00 | Operator launcher, SQLite thread-safety fix, aiohttp dependency |
| 23 | `dabce60` | 2026-03-14T03:56:52+03:00 | Keithley smua+smub, Telegram bot commands, portable deployment |
| 24 | `2f31378` | 2026-03-14T04:07:59+03:00 | Keithley control panel + thermal conductivity chain measurement |
| 25 | `84b01a7` | 2026-03-14T04:27:20+03:00 | Steady-state predictor + auto-sweep measurement panel |
| 26 | `b2b4d97` | 2026-03-14T05:02:57+03:00 | Channel manager + instrument connection settings UI |
| 27 | `603a472` | 2026-03-14T13:29:44+03:00 | Safety architecture: SafetyManager, SafetyBroker, fail-on-silence |
| 28 | `941d5e3` | 2026-03-14T16:31:42+03:00 | Code review: 13 fixes — token revocation, safety, thread-safety, tests |
| 29 | `99df7eb` | 2026-03-14T17:20:03+03:00 | Update CLAUDE.md and README.md to current project state |
| 30 | `3f4b8fa` | 2026-03-14T17:40:40+03:00 | Add files via upload |
| 31 | `40b4ffb` | 2026-03-14T17:56:34+03:00 | Add files via upload |
| 32 | `efe16d3` | 2026-03-14T18:12:48+03:00 | Add files via upload |
| 33 | `dc5f3c6` | 2026-03-14T18:13:22+03:00 | Add files via upload |
| 34 | `a8e8bbf` | 2026-03-14T18:18:02+03:00 | SAFETY: persistence-first ordering — disk before subscribers |
| 35 | `9217489` | 2026-03-14T18:49:09+03:00 | Cooldown predictor integration: library refactor, service, GUI, tests |
| 36 | `dd2dd2c` | 2026-03-14T18:59:53+03:00 | Update CLAUDE.md and README.md: cooldown integration, persistence-first, stats |
| 37 | `4dca478` | 2026-03-14T19:13:02+03:00 | Add files via upload |
| 38 | `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs |
| 39 | `7d8cc1f` | 2026-03-14T20:08:19+03:00 | Update CLAUDE.md and README.md: overview tab, XLSX, DiskMonitor, stats |
| 40 | `68324c2` | 2026-03-14T20:26:27+03:00 | Add files via upload |
| 41 | `9390419` | 2026-03-14T22:53:45+03:00 | Add files via upload |
| 42 | `e9a538f` | 2026-03-14T23:17:09+03:00 | SAFETY: 14 audit fixes — FAULT_LATCHED latch, status checks, heartbeat |
| 43 | `678ff50` | 2026-03-15T02:25:13+03:00 | Add files via upload |
| 44 | `1bd6c4e` | 2026-03-15T02:39:36+03:00 | P0: 5 critical fixes — alarm pipeline, safety state, P/V/I limits, latched flag |
| 45 | `0f8dd59` | 2026-03-15T02:44:01+03:00 | Add files via upload |
| 46 | `de715dc` | 2026-03-15T03:02:21+03:00 | P1: 8 lab deployment fixes — async ZMQ, REAL timestamps, paths, sessions |
| 47 | `8d146bc` | 2026-03-15T03:08:22+03:00 | Add files via upload |
| 48 | `61dca77` | 2026-03-15T03:48:26+03:00 | BREAKING: instrument_id is now a first-class field on Reading dataclass |
| 49 | `9d48c41` | 2026-03-15T15:58:53+03:00 | Add files via upload |
| 50 | `2afdbc1` | 2026-03-15T16:42:06+03:00 | Add files via upload |
| 51 | `0078d57` | 2026-03-15T18:02:34+03:00 | Add files via upload |
| 52 | `dc2ea6a` | 2026-03-17T15:33:46+03:00 | Merge CRYODAQ-CODEX RC into master (v0.11.0-rc1) |
| 53 | `29652a2` | 2026-03-17T16:00:30+03:00 | chore: delete merged branches, ignore .claude/ directory |
| 54 | `cdbba6c` | 2026-03-17T16:49:26+03:00 | fix: restore MainWindow menu in launcher, add --mock flag |
| 55 | `b6ddb4e` | 2026-03-17T17:03:03+03:00 | feat: dashboard hub — Keithley quick-actions, quick log, experiment status on Overview |
| 56 | `f910c40` | 2026-03-17T17:14:25+03:00 | feat: structured shift handover — start, periodic prompts, end summary |
| 57 | `3dea162` | 2026-03-17T17:40:09+03:00 | refactor: two-column Overview layout, move ExperimentWorkspace to separate tab |
| 58 | `a23ab92` | 2026-03-17T17:53:15+03:00 | fix: Overview — readable time axis, 8-per-row temp cards by instrument, scrollable panel |
| 59 | `dd663ae` | 2026-03-17T18:15:42+03:00 | fix: Overview layout — full-width temp cards, graph+info splitter |
| 60 | `a38154a` | 2026-03-17T18:27:37+03:00 | perf: async ZMQ polling in Overview widgets to eliminate UI lag |
| 61 | `212e299` | 2026-03-17T18:33:38+03:00 | perf: throttle plot updates, optimize pyqtgraph rendering, reduce UI work per reading |
| 62 | `f4cb917` | 2026-03-17T18:51:26+03:00 | refactor: Overview — cards on top, synced temp+pressure graphs, clickable channel toggle |
| 63 | `c848393` | 2026-03-17T19:00:51+03:00 | fix: dynamic temp cards, compact experiment form, unified button colors |
| 64 | `81c5a1d` | 2026-03-17T19:12:17+03:00 | fix: tray icon duplicate, post-P0 audit fixes |
| 65 | `2136623` | 2026-03-17T19:16:46+03:00 | chore: remove dead PressureStrip class and unused imports |
| 66 | `81ef8a6` | 2026-03-17T19:42:06+03:00 | feat: continuous SRDG acquisition during calibration experiments |
| 67 | `e694d2d` | 2026-03-17T19:52:16+03:00 | feat: calibration v2 post-run pipeline — extract, downsample, breakpoints, fit |
| 68 | `38aca4f` | 2026-03-17T19:57:30+03:00 | feat: calibration v2 GUI — three-mode panel with coverage and auto-fit |
| 69 | `98a5951` | 2026-03-17T20:11:32+03:00 | chore: calibration v2 cleanup — remove legacy sessions, update docs |
| 70 | `bc41589` | 2026-03-17T20:36:54+03:00 | fix: UX polish — DateAxisItem on all graphs, Russian labels, layout fixes |
| 71 | `aad5eab` | 2026-03-17T20:41:48+03:00 | feat: experiment phase tracking — preparation through teardown |
| 72 | `d8421e6` | 2026-03-17T20:53:12+03:00 | feat: auto-log system events, auto-generate report on finalize |
| 73 | `7f0e5d1` | 2026-03-17T21:11:40+03:00 | fix: P1 audit — phase widget, empty states, auto-entry styling, DateAxisItem everywhere |
| 74 | `3b6a175` | 2026-03-17T22:06:49+03:00 | feat: calibration start button, full docs sync to Russian |
| 75 | `c22eca9` | 2026-03-18T00:10:28+03:00 | release: v0.12.0 — first production release |
| 76 | `7ee15de` | 2026-03-18T00:52:04+03:00 | feat: web dashboard — read-only monitoring page with auto-refresh |
| 77 | `e553f11` | 2026-03-18T00:58:19+03:00 | feat: telegram bot v2 — /status, /log, /temps, /phase, escalation chain |
| 78 | `ae70158` | 2026-03-18T01:00:12+03:00 | feat: pre-flight checklist before experiment start |
| 79 | `5678d96` | 2026-03-18T01:04:28+03:00 | feat: experiment form auto-fill with history and name suggestion |
| 80 | `4405348` | 2026-03-18T01:30:25+03:00 | fix: telegram bot polling debug + ensure task started |
| 81 | `88357b8` | 2026-03-18T02:16:12+03:00 | feat: alarm v2 foundation — RateEstimator and ChannelStateTracker |
| 82 | `046ab6f` | 2026-03-18T02:22:14+03:00 | feat: alarm v2 evaluator — composite, rate, threshold, stale checks |
| 83 | `3f86b42` | 2026-03-18T02:26:02+03:00 | feat: alarm v2 providers and config parser |
| 84 | `8070b2d` | 2026-03-18T02:30:59+03:00 | feat: alarm v2 integration in engine with phase-dependent evaluation |
| 85 | `ac404db` | 2026-03-18T02:32:02+03:00 | fix: remove undercool_shield false interlock, phase-gate detector_warmup |
| 86 | `d3b58bd` | 2026-03-18T02:38:33+03:00 | feat: alarm v2 GUI panel and documentation |
| 87 | `92e1369` | 2026-03-18T10:45:37+03:00 | fix: memory leak — broadcast task explosion, rate estimator trim, history cap |
| 88 | `e601ca9` | 2026-03-18T10:55:32+03:00 | fix: empty plots after GUI reconnect, experiment status wrong key |
| 89 | `c7ae2ed` | 2026-03-18T10:59:53+03:00 | feat: tray-only mode for headless engine monitoring |
| 90 | `d7c843f` | 2026-03-18T17:12:19+03:00 | fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off, alarms, pressure card, docs |
| 91 | `4f717a5` | 2026-03-18T17:23:52+03:00 | fix: keithley source-off NaN → SQLite NOT NULL crash |
| 92 | `8605a52` | 2026-03-19T11:14:49+03:00 | fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN? |
| 93 | `d0c40de` | 2026-03-19T12:19:10+03:00 | fix: thyracont V1 pressure formula, keithley output float parse, pressure exponent format |
| 94 | `f3e62f5` | 2026-03-19T12:36:06+03:00 | fix: thyracont V1 value is 6 digits (4 mantissa + 2 exponent), formula (ABCD/1000)*10^(EF-20) |
| 95 | `d94e361` | 2026-03-19T12:41:31+03:00 | fix: VISA bus lock to prevent -420 Query UNTERMINATED race |
| 96 | `552f679` | 2026-03-19T12:58:57+03:00 | fix: rate check scoped to critical channels only, disconnected sensors excluded |
| 97 | `94ec2b6` | 2026-03-19T13:15:31+03:00 | refactor: keithley P=const host-side control loop, remove blocking TSP script |
| 98 | `1b5c099` | 2026-03-19T13:36:07+03:00 | feat: keithley live P_target update + fix stop button |
| 99 | `5bc640c` | 2026-03-19T14:05:52+03:00 | fix: GPIB bus lock covers open_resource() and close(), not just query/write |
| 100 | `a0e9678` | 2026-03-19T14:13:43+03:00 | fix: GPIB bus lock covers open_resource + verify query atomically |
| 101 | `bb59488` | 2026-03-19T14:29:07+03:00 | fix: GPIB open-per-query + IFC bus reset on timeout |
| 102 | `946b454` | 2026-03-19T14:50:20+03:00 | refactor: GPIB sequential polling — single task per bus, no parallel access |
| 103 | `fd229e9` | 2026-03-19T14:58:54+03:00 | fix: GPIB clear() before every query + IFC recovery on timeout |
| 104 | `31c4bae` | 2026-03-19T15:26:17+03:00 | fix: GPIB remove clear() from hot path, add write-delay-read |
| 105 | `5448f08` | 2026-03-19T16:00:56+03:00 | fix: GPIB KRDG? command + GUI visual fixes + ZMQ crash resilience |
| 106 | `7efb8b7` | 2026-03-19T16:21:12+03:00 | refactor: GPIB persistent sessions — LabVIEW-style open-once scheme |
| 107 | `f64d981` | 2026-03-19T16:41:46+03:00 | feat: isolate ZMQ into subprocess — GUI never imports zmq |
| 108 | `856ad19` | 2026-03-20T13:04:34+03:00 | feat: Keithley safety (slew rate, compliance) + ZMQ subprocess hardening |
| 109 | `757f59e` | 2026-03-20T13:22:39+03:00 | feat: SensorDiagnosticsEngine — backend + 20 unit tests (Stage 1) |
| 110 | `6eb8dfe` | 2026-03-20T13:33:19+03:00 | feat: SensorDiagnostics — engine integration + config (Stage 2) |
| 111 | `b21bca1` | 2026-03-20T13:45:37+03:00 | feat: SensorDiagnostics GUI panel + status bar summary (Stage 3) |
| 112 | `5d7fe2b` | 2026-03-20T13:56:47+03:00 | feat: VacuumTrendPredictor — backend + 20 unit tests (Stage 1) |
| 113 | `c1b9eb5` | 2026-03-20T14:30:15+03:00 | feat: VacuumTrendPredictor — engine integration + config (Stage 2) |
| 114 | `50e30e3` | 2026-03-20T14:39:47+03:00 | feat: VacuumTrendPredictor GUI panel on Analytics tab (Stage 3) |
| 115 | `afabfe5` | 2026-03-20T16:03:45+03:00 | fix: ZMQ datetime serialization + REP socket stuck on serialization error |
| 116 | `6ef43df` | 2026-03-20T20:12:35+03:00 | feat: Phase 2 safety hardening — tests + bugfixes + LakeShore RDGST? |
| 117 | `bbb5809` | 2026-03-20T20:42:47+03:00 | feat: Phase 3 — safety correctness, reliability, phase detector |
| 118 | `4b52de8` | 2026-03-20T21:16:28+03:00 | fix: deep review — 2 bugs fixed, 2 tests added |
| 119 | `10d4d76` | 2026-03-20T22:39:17+03:00 | fix(audit): 6 bugs — safety race, SQLite shutdown, Inf filter, phase reset, GPIB leak, deque cap |
| 120 | `af94285` | 2026-03-21T00:39:25+03:00 | fix(ui): CSV BOM, sensor diag stretch, calibration stretch, reports on, adaptive liveness |
| 121 | `1ec93a6` | 2026-03-21T02:39:16+03:00 | merge: feature/ui-refactor |
| 122 | `c427247` | 2026-03-21T02:54:30+03:00 | docs: update all documentation, changelog, and version for v0.13.0 |
| 123 | `a2f4bcd` | 2026-03-21T12:01:31+03:00 | fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect |
| 124 | `1670bbe` | 2026-03-21T12:01:44+03:00 | fix(ui): card toggle signals, history load on window change, axis alignment, channel refresh |
| 125 | `2ab7283` | 2026-03-21T12:01:52+03:00 | chore: fix default channels, web version, deprecate autosweep_panel |
| 126 | `dc84f0c` | 2026-03-21T12:35:27+03:00 | fix(ui): remove QuickStart buttons from overview (caused FAULT with P=0) |
| 127 | `1dd7405` | 2026-03-21T12:35:37+03:00 | feat(ui): rename Keithley tab, add time window buttons, forecast zone |
| 128 | `f08e6bb` | 2026-03-21T12:35:47+03:00 | fix: audit wave 3 — build_ensemble guard, launcher ping, phase gap, RDGST, docs |
| 129 | `9e2ce5b` | 2026-03-21T15:20:53+03:00 | merge: final-batch — single-instance, ML forecast, flight recorder, driver fixes |
| 130 | `7618031` | 2026-03-21T16:01:14+03:00 | fix(telegram): natural channel sort, compact text, pressure log-scale Y limits |
| 131 | `4df40c3` | 2026-03-21T16:15:04+03:00 | fix(critical): atomic single-instance lock via O_CREAT|O_EXCL |
| 132 | `0603110` | 2026-03-21T16:15:13+03:00 | fix(zmq): correlation ID for command-reply routing |
| 133 | `9942da1` | 2026-03-21T16:15:23+03:00 | fix(ui): proportional history load, overview plot sync, CSV BOM |
| 134 | `6d39a08` | 2026-03-21T17:34:43+03:00 | fix(critical): move experiment I/O to thread, remove double report generation |
| 135 | `45ae750` | 2026-03-21T17:39:02+03:00 | fix(zmq): Future-per-request dispatcher with dedicated reply consumer |
| 136 | `031491a` | 2026-03-21T17:42:38+03:00 | fix(ui): "Всё"→"Сутки", pass channels to history, poll_readings resilience |
| 137 | `dd42632` | 2026-03-22T00:25:10+03:00 | fix(ui): snap graph X-axis to data start across all 7 panels |
| 138 | `0fdc507` | 2026-03-22T16:11:11+03:00 | merge: audit-v2 fixes (29 defects, 9 commits) |
| 139 | `fc1c61b` | 2026-03-22T16:35:11+03:00 | feat(storage): Parquet experiment archive — write readings.parquet alongside CSV on finalize |
| 140 | `ccf98c9` | 2026-03-22T16:44:11+03:00 | Add CI workflow for CryoDAQ with testing and linting |
| 141 | `f0c68c6` | 2026-03-22T17:28:38+03:00 | feat(archive): Parquet column in table, human-readable artifacts, parquet read fix |
| 142 | `423c6d5` | 2026-03-22T19:05:13+03:00 | fix(archive): inclusive end-date filter, add end time column |
| 143 | `8dc07f7` | 2026-03-22T19:18:57+03:00 | feat(reporting): professional human-readable reports for all experiment types |
| 144 | `a066cd7` | 2026-03-22T20:51:11+03:00 | feat(reporting): ГОСТ Р 2.105-2019 formatting, all graphs in all reports |
| 145 | `b7265bb` | 2026-03-22T21:23:13+03:00 | fix(reporting): multi-channel graphs, black headings, smart page breaks |
| 146 | `29d2215` | 2026-03-23T00:37:57+03:00 | fix: audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring |
| 147 | `ab57e01` | 2026-03-23T14:59:57+03:00 | fix(gpib): auto-recovery from hung instruments — clear bus on timeout, preventive clear |
| 148 | `ea5a8da` | 2026-03-23T15:15:20+03:00 | fix(gpib): IFC bus reset, enable unaddressing, escalating recovery |
| 149 | `86e8e8c` | 2026-03-23T15:32:17+03:00 | fix(preflight): sensor health is warning not error |
| 150 | `c10e617` | 2026-03-24T12:50:45+03:00 | fix(scheduler): standalone instrument disconnect+reconnect on consecutive errors |
| 151 | `dfd6021` | 2026-03-24T12:55:26+03:00 | fix(preflight): restore encoding + sensor health warning not error |
| 152 | `8bac038` | 2026-03-24T13:10:40+03:00 | fix(gui): non-blocking alarm v2 status poll |
| 153 | `6d0f5ba` | 2026-03-24T14:08:20+03:00 | fix(gui): bridge heartbeat false kills + launcher blocking send_command |
| 154 | `bab4d8a` | 2026-03-24T14:15:39+03:00 | feat: single-instance protection for launcher and standalone GUI |
| 155 | `4eb5f1a` | 2026-03-24T14:27:27+03:00 | fix(gui): launcher bridge health gap + conductivity blocking send_command |
| 156 | `3c46dfb` | 2026-03-24T14:41:09+03:00 | fix(gui): keithley spinbox debounce + non-blocking live update |
| 157 | `e7d4fc5` | 2026-03-24T14:48:54+03:00 | fix(gui): experiment workspace 1080p layout — phase bar + passport forms |
| 158 | `f47762d` | 2026-03-24T15:02:22+03:00 | fix: launcher non-blocking engine restart + deployment hardening |
| 159 | `f217427` | 2026-03-25T12:59:26+03:00 | fix: shift modal re-entrancy + engine --force PermissionError |
| 160 | `9676165` | 2026-03-31T03:17:03+03:00 | fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking |
| 161 | `9feaf3e` | 2026-04-01T03:57:02+03:00 | fix: audit - GUI non-blocking send_command + dead code cleanup |
| 162 | `a60abc0` | 2026-04-08T16:58:28+03:00 | fix: Phase 1 pre-deployment — unblock PyInstaller build |
| 163 | `0333e52` | 2026-04-08T17:47:20+03:00 | fix: Phase 2a safety hardening — close 4 HIGH findings |
| 164 | `8a24ead` | 2026-04-08T21:17:52+03:00 | fix: Phase 2b observability & resilience — close 8 MEDIUM findings |
| 165 | `b185fd3` | 2026-04-08T21:58:00+03:00 | fix: Phase 2c final hardening — close 8 findings before Phase 3 |
| 166 | `1698150` | 2026-04-08T22:16:31+03:00 | ui: replace Overview "Сутки" preset with "Всё" |
| 167 | `380df96` | 2026-04-09T00:45:35+03:00 | audit: deep audit pass (CC) post-2c |
| 168 | `fd99631` | 2026-04-09T00:59:45+03:00 | audit: deep audit pass (Codex overnight) post-2c |
| 169 | `fd8c8bf` | 2026-04-09T02:23:44+03:00 | chore: gitignore local audit artifacts (DEEP_AUDIT_*.md, graphify-out/) |
| 170 | `847095c` | 2026-04-09T02:39:32+03:00 | audit: cherry-pick hardening pass document from feat/ui-phase-1 |
| 171 | `5d618db` | 2026-04-09T02:58:53+03:00 | audit: verification pass - re-check 5 HIGH findings from hardening pass |
| 172 | `10667df` | 2026-04-09T03:07:45+03:00 | audit: SafetyManager exhaustive FSM analysis |
| 173 | `31dbbe8` | 2026-04-09T03:14:45+03:00 | audit: persistence-first invariant exhaustive trace |
| 174 | `3e20e86` | 2026-04-09T03:26:43+03:00 | audit: driver layer fault injection scenarios |
| 175 | `916fae4` | 2026-04-09T03:54:17+03:00 | audit: full dependency CVE sweep with version verification |
| 176 | `a108519` | 2026-04-09T04:01:17+03:00 | audit: reporting + analytics + plugins deep dive |
| 177 | `24b928d` | 2026-04-09T04:09:48+03:00 | audit: configuration files security and consistency audit |
| 178 | `7aaeb2b` | 2026-04-09T04:20:34+03:00 | audit: master triage synthesis of all audit documents |
| 179 | `995f7bc` | 2026-04-12T23:25:19+03:00 | discovery: build doc-vs-code reality map (CC + Codex review) |
| 180 | `6eb7d3e` | 2026-04-13T01:04:14+03:00 | docs: rewrite cryodaq-team-lead skill against current code reality |
| 181 | `ddf6459` | 2026-04-13T16:01:32+03:00 | docs(CLAUDE.md): add missing config files to list |
| 182 | `1d71ecc` | 2026-04-13T16:09:28+03:00 | docs(CLAUDE.md): expand module index, fix safety FSM and invariants |
| 183 | `88feee5` | 2026-04-13T16:27:03+03:00 | phase-2d-a1: web XSS + SafetyManager hardening + T regression |
| 184 | `1446f48` | 2026-04-13T17:18:12+03:00 | phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class |
| 185 | `ebac719` | 2026-04-13T17:44:12+03:00 | phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError |
| 186 | `1b12b87` | 2026-04-13T18:07:45+03:00 | phase-2d-a2: alarm config hardening + safety->experiment bridge |
| 187 | `e068cbf` | 2026-04-13T20:53:40+03:00 | phase-2d-a2-fix: close Codex findings on 1b12b87 |
| 188 | `d3abee7` | 2026-04-13T21:50:34+03:00 | phase-2d-b1: atomic file writes + WAL verification |
| 189 | `5cf369e` | 2026-04-13T22:08:49+03:00 | phase-2d-a8-followup: shield post-fault cancellation paths |
| 190 | `104a268` | 2026-04-13T22:30:24+03:00 | phase-2d-b2: persistence integrity |
| 191 | `21e9c40` | 2026-04-13T22:46:17+03:00 | phase-2d-b2-fix: drop NaN-valued statuses from persist set |
| 192 | `23929ca` | 2026-04-13T23:22:40+03:00 | phase-2d: checkpoint — Block A+B complete, update PROJECT_STATUS |
| 193 | `efe6b49` | 2026-04-14T01:14:35+03:00 | chore: ruff --fix accumulated lint debt |
| 194 | `f4c256f` | 2026-04-14T01:14:55+03:00 | chore: remove accidentally committed logs/, add to .gitignore |
| 195 | `74f6d21` | 2026-04-14T01:44:41+03:00 | phase-2d-jules-r2-fix: close ordering and state mutation gaps |
| 196 | `89ed3c1` | 2026-04-14T02:18:37+03:00 | phase-2d-c1: config fail-closed completion + cleanup |
| 197 | `0cd8a94` | 2026-04-14T02:36:54+03:00 | phase-2d: declare COMPLETE, open Phase 2e |
| 198 | `445c056` | 2026-04-14T02:55:31+03:00 | phase-2e-parquet-1: experiment archive via Parquet at finalize |
| 199 | `855870b` | 2026-04-14T03:26:45+03:00 | docs(audits): add BRANCH_INVENTORY.md for three-track review input |
| 200 | `5ad0156` | 2026-04-14T03:31:22+03:00 | docs(audits): add repo inventory, dead code scan, and CC findings summary |
| 201 | `1c75967` | 2026-04-14T03:54:44+03:00 | docs/audits: Codex round 2 extended semantic audit |
| 202 | `66f9870` | 2026-04-14T03:56:15+03:00 | docs/audits: CC round 2 extended inventory |
| 203 | `6535c9a` | 2026-04-14T04:15:41+03:00 | docs/audits: record remote branch cleanup |
| 204 | `88c308c` | 2026-04-14T04:19:11+03:00 | docs: update PROJECT_STATUS.md numbers for round 2 audit state |
| 205 | `5b3ca29` | 2026-04-14T04:19:26+03:00 | chore: commit historical pre-Phase-2c audit artifacts |

---

## Confidence ratings

- **Commit coverage:** **HIGH** — all 205 first-parent commits are represented in the appendix and assigned to a thematic cluster.
- **Clustering accuracy:** **MEDIUM-HIGH** — the clusters line up well with phase documents and commit messages, but some early “Add files via upload” commits are necessarily interpreted from file names rather than prose.
- **Version boundary proposal:** **MEDIUM** — the proposed boundaries are practical and defensible, but only `v0.12.0` is historically real; the rest are retroactive packaging choices.
- **Context explanations:** **MEDIUM-HIGH** — strongest where commit bodies were rich (`603a472`, `dc2ea6a`, `445c056`), slightly weaker where I had to infer intent from sequence and file touch patterns.
- **Breaking change detection:** **MEDIUM** — the major ones are definitely surfaced (`instrument_id`, fail-closed configs, calibration API split, host-side Keithley loop), but pre-1.0 history always risks small implicit behavioral breaks that were never named as such.
