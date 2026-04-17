# CryoDAQ — Retroactive Changelog Research v2

**Generated:** 2026-04-14  
**Commits covered:** 205 first-parent commits on `master` (234 total reachable commits)  
**Source data:** `git log --first-parent`, per-commit `git show --stat`, selected full commit messages/diffs, `docs/changelog/RETRO_ANALYSIS.md`, `docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`, `docs/audits/BRANCH_INVENTORY.md`, `docs/audits/BRANCH_INTEGRATION_VERIFICATION.md`  
**Purpose:** source material for a rebuilt `CHANGELOG.md`. This is **not** the final changelog.

---

## How to use this document

This file is the second-pass research document for the changelog rebuild. It supersedes `docs/changelog/RETRO_ANALYSIS.md` as the primary source material because it uses a finer version density and no longer treats the experimental `v0.12.0` tag as a hard anchor. The v1 document still matters: it contains useful prose, cluster context, and a coarser narrative that can still help a human writer decide where to compress or expand the final `CHANGELOG.md`.

This is still a research artifact, not a polished release note. It intentionally keeps material that a normal changelog would compress away: false starts, “Add files via upload” task snapshots, merge commits that imported whole feature branches, audit-document waves, and debugging sessions that only make sense when seen in sequence.

The later polished `CHANGELOG.md` should be assembled from this document, not copied verbatim. Each proposed version below is meant to be “one coherent release note worth of work”, usually 4-14 commits. That is much closer to how a human would talk about the project’s evolution than the 10-version v1 layout, which often compressed two or three distinct release-worthy waves into one bucket.

Version boundaries in this document are still retrospective proposals. There are currently no version tags in the repository, and that is useful: it removes anchor bias and lets the history be partitioned according to actual changes in work direction rather than a historical artifact. The numbering chosen here is a practical proposal for human assembly, not a claim that the repository followed this exact semver path at the time.

The key practical use is traceability. If a maintainer needs to know when the project first became end-to-end usable, when alarm v2 arrived, when GPIB stabilization stopped being ad hoc, when Phase 2d became the dominant effort, or why the audit corpus itself deserves a changelog entry, this document should answer that without another full walk through 205 commits.

---

## Methodology

I started from the v1 research output and the CC archaeology documents, then re-walked the first-parent history with a different question: “where does the direction of work genuinely change enough that a reader would expect a new release note?” That is the core difference from v1. The cluster concept survives from v1, but versions are now narrower and more release-shaped.

I verified that the repository currently has no `v0.12.0` tag locally or on origin before starting this pass. That matters because v1’s structure was strongly biased by the old real tag. In v2 the old `c22eca9` release commit still remains a meaningful historical event, but it is treated as evidence, not as a forced boundary.

For every proposed version I looked at four things:

1. commit density and time range
2. thematic cohesion
3. whether the work changed operator-visible behavior
4. whether the next few commits clearly pivoted to a different problem

I reused v1’s semantic clusters where they were already good, but I split several of them into smaller versions. The biggest split happened at the front of the history: v1’s broad “Foundation” is now six versions, because the repository clearly moved through distinct states in the first day: scaffold, core instruments, workflow shell, operator shell, safety architecture, then overview/cooldown intelligence.

I kept first-parent semantics. The four merge commits remain atomic changelog units rather than invitations to walk every side-branch commit individually. That is the right choice for a changelog research document: the point is to explain what landed on `master`, not to reconstruct every private iteration that happened before merge.

Known limitations:

- some “Add files via upload” commits have minimal message signal; where necessary I infer intent from neighboring commits and file-level context
- the version names are interpretive; they are chosen to be useful to a future changelog writer, not to reproduce any names used at the time
- the current head includes audit/documentation commits after the archaeology pass, so this v2 document necessarily covers a slightly longer history than the older audit timeline

---

## Version boundary proposal

I recommend a pure minor-version ladder with no patch releases in the retroactive reconstruction: `0.1.0`, `0.2.0`, ..., `0.25.0-pre`. This is the cleanest fit for the history. The repository did not evolve by stable base plus tiny patches; it evolved by intense bursts of directionally coherent work. Treating each of those bursts as a minor version is both simpler and more honest.

I do **not** recommend introducing `1.0.0` in this reconstruction. The project is too young, the audit history is too recent, and both Tier 1 fixes and GUI integration work are still pending. Staying in `0.x` communicates the truth better than pretending a major-stability threshold has already been crossed.

The old `v0.12.0` release commit still matters historically. In this proposal it remains `0.12.0`, but now because it is the natural “first lab-usable release” cut, not because a tag forced every surrounding version decision.

| Version | Name | Date range | Commit count | First commit | Last commit | Rationale |
|---|---|---|---:|---|---|---|
| `0.1.0` | Initial Scaffolding | 2026-03-14 00:29..2026-03-14 00:39 | 4 | `be52137` | `2882845` | Project skeleton, driver/data abstractions, scheduler, SQLite writer, and first IPC path appear together; this is the minimum coherent “project exists” cut. |
| `0.2.0` | Instrument Foundations | 2026-03-14 00:43..2026-03-14 01:23 | 4 | `0c54010` | `75ebdc1` | Direction shifts from generic scaffold to real hardware and first alarm/analytics plumbing. |
| `0.3.0` | Workflow Skeleton | 2026-03-14 01:25..2026-03-14 01:59 | 4 | `e64b516` | `e4bbcb6` | Engine/GUI entry points, experiments, notifications, and web monitoring turn the driver stack into a usable workflow shell. |
| `0.4.0` | Operator Shell Completion | 2026-03-14 02:12..2026-03-14 05:02 | 14 | `33e51f3` | `b2b4d97` | Third instrument, live tabs, launcher, docs, conductivity workflow, and first large tests make the product feel complete enough to operate. |
| `0.5.0` | Safety Architecture | 2026-03-14 13:29..2026-03-14 18:18 | 8 | `603a472` | `a8e8bbf` | This is the first governing-safety pivot: `SafetyManager`, `SafetyBroker`, fail-on-silence, and persistence-first all arrive here. |
| `0.6.0` | Cooldown and Overview Intelligence | 2026-03-14 18:49..2026-03-14 22:53 | 7 | `9217489` | `9390419` | The project pivots from pure control to observability and prediction via cooldown forecasting, overview dashboarding, and export tooling. |
| `0.7.0` | Deployment Fix Waves | 2026-03-14 23:17..2026-03-15 18:02 | 10 | `e9a538f` | `0078d57` | First audit/P0/P1 fix session and the `instrument_id` breaking change make this a distinct deployment-hardening release. |
| `0.8.0` | RC Merge | 2026-03-17 15:33..2026-03-17 15:33 | 1 | `dc2ea6a` | `dc2ea6a` | The RC merge is itself the historical event; later work only makes sense after this convergence point. |
| `0.9.0` | Dashboard Hub and Shift Workflow | 2026-03-17 16:00..2026-03-17 19:16 | 13 | `29652a2` | `2136623` | Post-RC focus shifts to overview UX, shift handover, and pyqtgraph/operator ergonomics. |
| `0.10.0` | Calibration V2 | 2026-03-17 19:42..2026-03-17 20:11 | 4 | `81ef8a6` | `98a5951` | Calibration v2 is a tight backend→pipeline→GUI rollout and reads naturally as its own release. |
| `0.11.0` | Phased Experiments and Auto Reports | 2026-03-17 20:36..2026-03-17 22:06 | 5 | `bc41589` | `3b6a175` | Experiment phases, auto-logging, and auto-report generation formalize the lifecycle beyond raw data capture. |
| `0.12.0` | First Lab-Usable Release | 2026-03-18 00:10..2026-03-18 00:10 | 1 | `c22eca9` | `c22eca9` | Even without the deleted tag, this explicit release commit remains the clearest “first lab-usable” boundary in history. |
| `0.13.0` | Remote Ops and Alarm V2 | 2026-03-18 00:52..2026-03-18 02:38 | 11 | `7ee15de` | `d3b58bd` | Web monitoring, Telegram v2, pre-flight checks, and alarm v2 arrive as one coherent operator/safety-surface expansion. |
| `0.14.0` | Post-Release Stabilization | 2026-03-18 10:45..2026-03-18 10:59 | 3 | `92e1369` | `c7ae2ed` | Immediate post-release leak/reconnect fixes plus tray-only mode form a compact stabilization release. |
| `0.15.0` | First Hardware Deployment | 2026-03-18 17:12..2026-03-19 13:36 | 9 | `d7c843f` | `1b5c099` | Real hardware forces corrections to Thyracont, Keithley, GPIB, pressure parsing, and critical-channel safety semantics. |
| `0.16.0` | GPIB Stabilization and ZMQ Isolation | 2026-03-19 14:05..2026-03-19 16:41 | 9 | `5bc640c` | `f64d981` | A concentrated transport marathon rewrites bus locking/recovery strategy, then isolates ZMQ from the GUI process. |
| `0.17.0` | Diagnostics and Safety Expansion | 2026-03-20 13:04..2026-03-21 00:39 | 13 | `856ad19` | `af94285` | Sensor diagnostics, vacuum trend, Keithley safety, and audit-driven safety deepening all land in one sustained wave. |
| `0.18.0` | UI Refactor Merge and Post-Merge Cleanup | 2026-03-21 02:39..2026-03-21 12:35 | 8 | `1ec93a6` | `f08e6bb` | The UI refactor merge and its immediate fallout are best understood as one release chapter. |
| `0.19.0` | Final-Batch Integration | 2026-03-21 15:20..2026-03-22 00:25 | 9 | `9e2ce5b` | `dd42632` | Single-instance locking, ZMQ reply routing, experiment I/O deblocking, and overview/history cleanup form a tight integration batch. |
| `0.20.0` | Audit-v2, Parquet v1, and Reporting | 2026-03-22 16:11..2026-03-23 00:37 | 9 | `0fdc507` | `29d2215` | Audit-v2 merge, first Parquet archive work, CI, and professional reporting all push the project toward operational credibility. |
| `0.21.0` | Recovery and Deployment Hardening | 2026-03-23 14:59..2026-03-25 12:59 | 13 | `ab57e01` | `f217427` | Deployment stress drives GPIB recovery escalation, reconnect logic, non-blocking GUI/launcher behavior, and singleton protections. |
| `0.22.0` | Pre-Phase-2d Hardening Prep | 2026-03-31 03:17..2026-04-08 22:16 | 7 | `9676165` | `1698150` | This is the explicit staging area before structured Phase 2d work: audit cleanup, PyInstaller unblock, and Phase 1/2a/2b/2c closure blocks. |
| `0.23.0` | Audit Corpus and Reality Map | 2026-04-09 00:45..2026-04-13 16:09 | 16 | `380df96` | `1d71ecc` | The repository spends a whole chapter auditing itself and reconciling docs with code reality; that deserves its own historical version. |
| `0.24.0` | Phase 2d Safety and Persistence | 2026-04-13 16:27..2026-04-13 23:22 | 10 | `88feee5` | `23929ca` | Structured hardening lands as disciplined blocks: safety, alarm config, file atomicity/WAL, and persistence integrity. |
| `0.25.0-pre` | Current Hardening Line | 2026-04-14 01:14..2026-04-14 04:19 | 13 | `efe6b49` | `5b3ca29` | Late 2d closure, fail-closed config completion, Phase 2e Parquet stage 1, and round-2 audit material define the current unreleased line. |

### Scheme rationale

The cadence here is intentionally denser than v1. A typical version in this reconstruction covers one sustained push: “alarm v2 rollout”, “GPIB stabilization marathon”, “final-batch integration”, “audit corpus”, “Phase 2d safety and persistence”, and so on. That makes the later human-written changelog much easier to assemble, because each version already reads like a release note topic instead of a quarter of the project.

This also better matches the way CryoDAQ was actually built. The project did not move in broad quarterly themes. It moved in highly focused waves: intense creation, hardware-driven correction, deployment-specific rewrites, then audit-driven hardening. The version model should mirror that.

---

## Version 0.1.0 — Initial Scaffolding

### Rationale for this boundary

This is the minimal coherent “project exists” cut. Before `be52137` there is nothing. After `2882845` there is enough architecture to talk about CryoDAQ as a real software system: package skeleton, project constraints, driver abstractions, first broker, first scheduler, first SQLite writer, and the first IPC bridge.

### Date range

2026-03-14 00:29..00:39

### Commit range

`be52137..2882845`

### Themes in this version

- repository and rules scaffold
- first driver/data abstractions
- first persistence and polling pipeline

### Cluster 0.1.1 — Repository bootstrap

**Commits:** `be52137`, `dea213f`, `f7cdc00`, `2882845`  
**Goal:** create the package, architecture contract, and first end-to-end technical skeleton.  
**Approach:** start with explicit project rules, then add the base source tree and immediately wire persistence, scheduling, and ZMQ so later work grows on a real data path instead of on stubs.

**What changed (Added / Changed / Fixed / Deprecated / Removed):**
- Added: architecture and constraints baseline in `CLAUDE.md` (`be52137`)
- Added: early agent workflow support used during the creation sprint (`dea213f`)
- Added: Python package scaffold, driver ABC, `DataBroker`, and repository structure (`f7cdc00`)
- Added: `SQLiteWriter`, scheduler, and ZMQ bridge (`2882845`)

**Breaking changes:** None, this is net-new surface creation.

**Operator-visible changes:** None yet. This is infrastructure only.

**Config file changes:** `pyproject.toml` and the first config-bearing structure arrived here.

**API / contract changes:** First `Reading`/driver/scheduler/broker contracts were born here.

**Internal / architectural changes:** The core architectural triangle of CryoDAQ is already visible: poll hardware, persist locally, broadcast to clients.

**Why the order:** The author chose breadth over polish first. That was the right move: without a scheduler, persistence, and IPC, nothing else would have real integration meaning.

**Commit explanations (one line each):**
- `be52137`: defined the architecture and constraints before the main code drop started
- `dea213f`: added the orchestration skill that helped drive the unusually fast initial build
- `f7cdc00`: created the actual Python project foundation
- `2882845`: made the scaffold operational by adding storage, scheduling, and IPC

---

## Version 0.2.0 — Instrument Foundations

### Rationale for this boundary

The direction changes from “software exists” to “real lab hardware model exists”. This version is separated from `0.1.0` because it introduces the first concrete instrument drivers and the first domain-specific analytics/alarm pipeline, which is a different milestone from generic scaffolding.

### Date range

2026-03-14 00:43..01:23

### Commit range

`0c54010..75ebdc1`

### Themes in this version

- first real LakeShore driver and GUI
- first Keithley constant-power path
- first alarm/analytics plugin abstractions

### Cluster 0.2.1 — Core instrument bring-up

**Commits:** `0c54010`, `577b02f`, `258f643`, `75ebdc1`  
**Goal:** move from generic framework to CryoDAQ-specific hardware control.  
**Approach:** implement the temperature controller first, then the power source, then define the first analytics/alarm path around them.

**What changed:**
- Added: LakeShore 218S driver, temperature panel, and tests (`0c54010`)
- Added: Keithley 2604B TSP constant-power driver and first interlock ideas (`577b02f`)
- Changed: project rules and module index to reflect the now-real data path (`258f643`)
- Added: first alarm engine and analytics plugin pipeline (`75ebdc1`)

**Breaking changes:** None.

**Operator-visible changes:** The first live temperature UI and the first visible Keithley integration appeared here.

**Config file changes:** initial instrument/alarm-related configuration expectations became real.

**API / contract changes:** drivers stopped being abstract placeholders and became concrete instrument contracts.

**Internal / architectural changes:** the plugin idea arrives very early, which matters later when analytics and alarms become much richer.

**Why the order:** Once scaffolding existed, the fastest path to value was to stand up the two most important hardware classes, not to overdesign the framework.

**Commit explanations:**
- `0c54010`: turned the repository into a real cryogenic DAQ by adding the first production-relevant instrument
- `577b02f`: added the source-measure unit and the first safety-sensitive control flow
- `258f643`: synchronized the living architecture document with the rapidly changing code
- `75ebdc1`: made alarms and analytics first-class rather than future TODOs

---

## Version 0.3.0 — Workflow Skeleton

### Rationale for this boundary

This version is where CryoDAQ becomes more than a set of drivers and a scheduler. The focus turns to workflows: entry points, experiment lifecycle, notifications, web monitoring, and the first calibration placeholder. That is a clear thematic pivot from the driver-centric `0.2.0`.

### Date range

2026-03-14 01:25..01:59

### Commit range

`e64b516..e4bbcb6`

### Themes in this version

- engine/GUI pairing
- experiment lifecycle and export
- notifications and web surface

### Cluster 0.3.1 — End-to-end workflow shell

**Commits:** `e64b516`, `0b79fa1`, `baaec03`, `e4bbcb6`  
**Goal:** define how operators actually use the system end to end.  
**Approach:** bind the engine and GUI together, add experiments and export, then add operator-facing remote surfaces.

**What changed:**
- Added: fuller architecture doc and operator/team workflow guidance (`e64b516`)
- Added: engine and GUI entry points, main window, alarm panel, instrument status (`0b79fa1`)
- Added: experiment lifecycle, replay/export, Telegram notifications (`baaec03`)
- Added: web dashboard, calibration stub, and updated docs (`e4bbcb6`)

**Breaking changes:** None.

**Operator-visible changes:** This is the first version where an operator can plausibly imagine running a session through the software.

**Config file changes:** notification and web-facing settings became relevant for real use.

**API / contract changes:** experiment subsystem and remote-surface contracts are born here.

**Internal / architectural changes:** the later “engine as source of truth, GUI/web/Telegram as clients” pattern is already visible.

**Why the order:** Hardware and storage were already present. The next limiting factor was operator workflow.

**Commit explanations:**
- `e64b516`: documented the architecture in more detail before the surface area widened further
- `0b79fa1`: created the first actual operator shell
- `baaec03`: introduced experiment lifecycle and notification-oriented operational flow
- `e4bbcb6`: extended the shell to web monitoring and calibration placeholders

---

## Version 0.4.0 — Operator Shell Completion

### Rationale for this boundary

This version is a broad but coherent completion wave: all three instrument classes, launcher polish, Russian docs, conductivity workflow, connection settings, and the first substantial test suite. It is separate because the project’s direction changes from “workflow skeleton” to “make the product feel complete enough to operate”.

### Date range

2026-03-14 02:12..05:02

### Commit range

`33e51f3..b2b4d97`

### Themes in this version

- third instrument and live tabs
- launcher and deployment helpers
- operator documentation
- first broad tests

### Cluster 0.4.1 — Product-shape completion wave

**Commits:** `33e51f3`, `e4546df`, `734f641`, `fdbeb95`, `3cb98dd`, `641f21e`, `167eb7d`, `3dbd222`, `da825f1`, `77638b0`, `dabce60`, `2f31378`, `84b01a7`, `b2b4d97`

**Goal:** turn the rough skeleton into a tool-shaped application with all major lab-facing surfaces present.

**Approach:** fix early integration issues, add tests, complete the remaining instrument and live tabs, then add the launcher, measurement workflows, and connection management.

**What changed:**
- Fixed: mock mode and plugin init compatibility (`33e51f3`)
- Fixed: timezone/WAL/mock-range/timeout test issues (`e4546df`)
- Added: first large automated test suite (`734f641`)
- Added: Keithley mock config path (`fdbeb95`)
- Fixed: Windows pyzmq event-loop compatibility (`3cb98dd`)
- Added: Russian README and operator manual (`641f21e`, `3dbd222`)
- Added: Thyracont VSP63D driver and periodic/live web reporting (`167eb7d`)
- Added: Keithley, pressure, and analytics tabs as live surfaces (`da825f1`)
- Added: launcher and SQLite thread-safety adjustments (`77638b0`)
- Added: dual-channel Keithley, Telegram commands, deployment helpers (`dabce60`)
- Added: conductivity chain measurement and steady-state/auto-sweep tools (`2f31378`, `84b01a7`)
- Added: channel manager and connection settings UI (`b2b4d97`)

**Breaking changes:** None.

**Operator-visible changes:** This is the first version that clearly feels like a complete operator workstation rather than a developer tool.

**Config file changes:** instrument config, notifications, and connection settings became richer and more user-facing.

**API / contract changes:** channel manager and dual-channel expectations start to matter here.

**Internal / architectural changes:** the early presence of broad tests becomes a recurring enabler for later hardening.

**Why the order:** The project needed completeness before it needed deeper hardening.

**Commit explanations:**
- `33e51f3`: stabilized early mock/plugin behavior
- `e4546df`: cleaned up the immediate fallout from rapid early integration
- `734f641`: established a meaningful regression floor
- `fdbeb95`: made Keithley visible in configured runtime paths
- `3cb98dd`: fixed Windows event loop behavior for pyzmq
- `641f21e`: created the first operator-readable Russian project summary
- `167eb7d`: completed the core hardware set with Thyracont and live reporting
- `3dbd222`: added a proper operator manual
- `da825f1`: made all major GUI tabs live
- `77638b0`: added launcher behavior and storage/thread adjustments
- `dabce60`: expanded Keithley and Telegram capabilities
- `2f31378`: introduced conductivity measurement workflow
- `84b01a7`: added steady-state prediction and auto-sweep tools
- `b2b4d97`: brought channel and connection management into the UI

---

## Version 0.5.0 — Safety Architecture

### Rationale for this boundary

This is the first major architectural safety pivot. The morning foundation made the system functional; this afternoon wave makes it safety-shaped. It deserves a separate version because the project’s central invariant language appears here: `SafetyManager`, `SafetyBroker`, fail-on-silence, and then persistence-first ordering.

### Date range

2026-03-14 13:29..18:18

### Commit range

`603a472..a8e8bbf`

### Themes in this version

- first real safety state machine
- fail-on-silence contract
- persistence-first contract

### Cluster 0.5.1 — Safety foundation and persistence contract

**Commits:** `603a472`, `941d5e3`, `99df7eb`, `3f4b8fa`, `40b4ffb`, `efe16d3`, `dc5f3c6`, `a8e8bbf`

**Goal:** define the first explicit safety architecture for unattended cryogenic operation.

**Approach:** introduce dedicated safety ownership, review and fix the first exposed hazards, then codify the persistence-before-publish rule.

**What changed:**
- Added: `SafetyManager`, `SafetyBroker`, and fail-on-silence behavior (`603a472`)
- Fixed: first broad review findings around safety and thread-safety (`941d5e3`)
- Changed: docs to describe the new governing contracts (`99df7eb`)
- Added: several task/upload snapshots from the same safety work session (`3f4b8fa`, `40b4ffb`, `efe16d3`, `dc5f3c6`)
- Added: persistence-first ordering as a first-class invariant (`a8e8bbf`)

**Breaking changes:** Implicitly yes at architectural level, but not a public API break. The system’s governing behavior changed.

**Operator-visible changes:** Operators would mostly experience safer default behavior, not a new surface.

**Config file changes:** safety and persistence rules became much more central, even if the exact schema was still evolving.

**API / contract changes:** this is the birth of the most important contracts later audits keep referring to.

**Internal / architectural changes:** arguably the most important version boundary in the whole early history.

**Why the order:** The author first proved the system could run, then immediately encoded the rules needed to trust it around hardware.

**Commit explanations:**
- `603a472`: introduced the core safety architecture
- `941d5e3`: closed the first batch of issues exposed by that new architecture
- `99df7eb`: synchronized docs with the sharper safety stance
- `3f4b8fa`: task snapshot from the same safety hardening session
- `40b4ffb`: task snapshot from the same safety hardening session
- `efe16d3`: task snapshot from the same safety hardening session
- `dc5f3c6`: task snapshot from the same safety hardening session
- `a8e8bbf`: codified persistence-first as the central data-integrity rule

---

## Version 0.6.0 — Cooldown and Overview Intelligence

### Rationale for this boundary

The work shifts again from core safety to operator intelligence: cooldown prediction, dashboarding, export polish, and disk awareness. This is not just more UI; it is the first version where CryoDAQ becomes observability-rich rather than merely controllable.

### Date range

2026-03-14 18:49..22:53

### Commit range

`9217489..9390419`

### Themes in this version

- cooldown forecasting
- overview dashboard
- export and disk monitoring

### Cluster 0.6.1 — Insight-oriented operator tooling

**Commits:** `9217489`, `dd2dd2c`, `4dca478`, `b803967`, `7d8cc1f`, `68324c2`, `9390419`

**Goal:** make the system informative, not just interactive.

**Approach:** add a cooldown predictor end to end, then build the overview/dashboard/export surface around it and document the result.

**What changed:**
- Added: cooldown predictor service, GUI, tests, and refactor support (`9217489`)
- Changed: docs to reflect cooldown integration and persistence-first framing (`dd2dd2c`, `7d8cc1f`)
- Added: task snapshots around the same integration wave (`4dca478`, `68324c2`, `9390419`)
- Added: overview dashboard, XLSX export, disk monitor, and finished export TODOs (`b803967`)

**Breaking changes:** None.

**Operator-visible changes:** Operators got the first serious overview/dashboard experience and predictive cooldown intelligence.

**Config file changes:** runtime stats/overview expectations became more explicit in docs.

**API / contract changes:** cooldown-related services and dashboard hooks became part of the mental model.

**Internal / architectural changes:** the system’s role expands from recorder/controller to predictor/observer.

**Why the order:** With safety architecture in place, the next value move was insight and observability.

**Commit explanations:**
- `9217489`: landed the cooldown predictor stack
- `dd2dd2c`: updated docs to keep up with the new predictor and stats story
- `4dca478`: session snapshot during the same integration push
- `b803967`: added overview, XLSX, and disk monitoring
- `7d8cc1f`: synced docs with the new overview/export surface
- `68324c2`: session snapshot around that same push
- `9390419`: final upload snapshot closing the version

---

## Version 0.7.0 — Deployment Fix Waves

### Rationale for this boundary

This is the first truly deployment-driven hardening wave. The software already exists and has safety architecture, but now the work shifts to audit fixes, P0/P1 operational blockers, and one of the earliest explicit breaking contract changes: `instrument_id` becomes first-class on `Reading`.

### Date range

2026-03-14 23:17..2026-03-15 18:02

### Commit range

`e9a538f..0078d57`

### Themes in this version

- first audit-driven safety fixes
- P0/P1 deployment unblockers
- `Reading.instrument_id` breaking change

### Cluster 0.7.1 — First deployment hardening session

**Commits:** `e9a538f`, `678ff50`, `1bd6c4e`, `0f8dd59`, `de715dc`, `8d146bc`, `61dca77`, `9d48c41`, `2afdbc1`, `0078d57`

**Goal:** close the most dangerous gaps exposed when the code was judged against real deployment expectations.

**Approach:** apply safety audit fixes first, then P0/P1 blockers, then formalize data identity with `instrument_id`.

**What changed:**
- Fixed: first 14 safety/audit issues around latching, status, heartbeat (`e9a538f`)
- Added: task snapshots documenting the same fix session (`678ff50`, `0f8dd59`, `8d146bc`, `9d48c41`, `2afdbc1`, `0078d57`)
- Fixed: five critical P0 issues (`1bd6c4e`)
- Fixed: eight P1 lab deployment issues around async ZMQ, timestamps, paths, sessions (`de715dc`)
- Breaking: `Reading.instrument_id` promoted to first-class field (`61dca77`)

**Breaking changes:** Yes. All driver output and downstream logic now had to treat `instrument_id` as required.

**Operator-visible changes:** Mostly negative-space improvements: fewer unsafe or confusing failure modes.

**Config file changes:** deployment/path/session assumptions became tighter.

**API / contract changes:** `Reading.instrument_id` is the main one and deserves to remain in the breaking-change timeline.

**Internal / architectural changes:** the project stops behaving like a fresh prototype and starts behaving like software being prepared for real use.

**Why the order:** This follows the standard path of any real lab system: first make it exist, then let reality force stronger contracts.

**Commit explanations:**
- `e9a538f`: first wide safety hardening pass
- `678ff50`: task snapshot from that hardening session
- `1bd6c4e`: closed the P0 blocker set
- `0f8dd59`: task snapshot from the P0/P1 session
- `de715dc`: closed the P1 deployment blocker set
- `8d146bc`: task snapshot from the same deployment push
- `61dca77`: introduced the first explicit data-model breaking change
- `9d48c41`: task upload from the continuing stabilization work
- `2afdbc1`: task upload from the continuing stabilization work
- `0078d57`: final upload snapshot closing the first deployment-fix wave

---

## Version 0.8.0 — RC Merge

### Rationale for this boundary

This version is a single merge commit because that merge is itself the meaningful release event. It pulled the RC branch into `master` and reset the project’s surface area in one shot. Treating it as anything other than its own version would blur a real historical pivot.

### Date range

2026-03-17 15:33..15:33

### Commit range

`dc2ea6a..dc2ea6a`

### Themes in this version

- RC branch convergence
- foundation for the next operator/UI/phase/calibration waves

### Cluster 0.8.1 — Master absorbs the RC branch

**Commits:** `dc2ea6a`

**Goal:** converge the main development line onto the RC branch’s product shape.

**Approach:** merge the branch atomically instead of replaying its internal history on first-parent.

**What changed:**
- Changed: `master` absorbed the CRYODAQ-CODEX RC branch (`dc2ea6a`)

**Breaking changes:** Implicitly yes at product shape level, but the merge commit is the right changelog unit.

**Operator-visible changes:** The next several versions make sense only because this merge happened first.

**Config file changes:** inherited from the branch content.

**API / contract changes:** inherited from the branch content.

**Internal / architectural changes:** this is a history-shaping merge, not a small code change.

**Why the order:** The following versions are all post-RC convergence refinements.

**Commit explanations:**
- `dc2ea6a`: merged the RC branch and established the next era of work

---

## Version 0.9.0 — Dashboard Hub and Shift Workflow

### Rationale for this boundary

This is the first clear post-RC user-experience wave. The focus is the overview/dashboard as operator control center, structured shift handover, and performance/layout refinement. That is a tighter and more recognizable release than the coarse v1 bucket that mixed it with calibration and phases.

### Date range

2026-03-17 16:00..19:16

### Commit range

`29652a2..2136623`

### Themes in this version

- overview as operator hub
- shift handover workflow
- pyqtgraph/UI performance and layout cleanup

### Cluster 0.9.1 — Overview and handover maturation

**Commits:** `29652a2`, `cdbba6c`, `b6ddb4e`, `f910c40`, `3dea162`, `a23ab92`, `dd663ae`, `a38154a`, `212e299`, `f4cb917`, `c848393`, `81c5a1d`, `2136623`

**Goal:** make the overview screen the real operational center of the application.

**Approach:** add quick actions and shift workflow, then iteratively refine layout, data density, and rendering cost until the screen is usable under live load.

**What changed:**
- Added: dashboard hub with Keithley quick actions and quick log (`b6ddb4e`)
- Added: structured shift handover workflow (`f910c40`)
- Fixed/refactored: repeated overview layout and rendering improvements (`3dea162`, `a23ab92`, `dd663ae`, `a38154a`, `212e299`, `f4cb917`, `c848393`)
- Fixed: launcher menu/mock flag and post-P0 tray duplication issues (`cdbba6c`, `81c5a1d`)
- Removed: dead pressure-strip UI leftovers (`2136623`)

**Breaking changes:** None.

**Operator-visible changes:** Very high. This is a distinctly different operator experience from the previous versions.

**Config file changes:** None material.

**API / contract changes:** Mostly UI-internal.

**Internal / architectural changes:** shows the project beginning to optimize live refresh cost, not just add features.

**Why the order:** Once the RC merge landed, overview ergonomics and shift workflow became the highest-leverage operator-facing work.

**Commit explanations:**
- `29652a2`: cleaned branch artifacts before the new wave of UX work
- `cdbba6c`: fixed launcher/menu ergonomics after RC merge
- `b6ddb4e`: introduced the dashboard hub concept
- `f910c40`: added structured shift handover
- `3dea162`: reorganized overview layout around operator workflow
- `a23ab92`: improved time axis readability and card density
- `dd663ae`: refined graph/info layout proportions
- `a38154a`: moved overview polling async to reduce UI lag
- `212e299`: optimized rendering and plot update rate
- `f4cb917`: introduced synced temp/pressure graph behavior and toggle model
- `c848393`: tightened cards, experiment form, and button styling
- `81c5a1d`: fixed tray duplication and a few lingering regressions
- `2136623`: removed dead UI leftovers after the refactor

---

## Version 0.10.0 — Calibration V2

### Rationale for this boundary

Calibration v2 is a coherent subsystem rollout and deserves to stand alone. It is more specific than “analytics expansion” and more operator-visible than a background refactor. This boundary is one of the clearest examples of why v2 is better than v1.

### Date range

2026-03-17 19:42..20:11

### Commit range

`81ef8a6..98a5951`

### Themes in this version

- continuous SRDG capture
- post-run extraction/downsampling/fitting
- three-mode calibration UI

### Cluster 0.10.1 — Calibration v2 rollout

**Commits:** `81ef8a6`, `e694d2d`, `38aca4f`, `98a5951`

**Goal:** replace the rough calibration placeholder with a real workflow.

**Approach:** start by capturing SRDG continuously, then add post-run extraction and fitting, then expose the whole flow through a dedicated GUI.

**What changed:**
- Added: continuous SRDG acquisition during calibration experiments (`81ef8a6`)
- Added: post-run pipeline for extraction, downsampling, breakpointing, and fitting (`e694d2d`)
- Added: three-mode calibration GUI (`38aca4f`)
- Changed: cleaned legacy calibration sessions and synchronized docs (`98a5951`)

**Breaking changes:** Softly yes at workflow level: calibration expectations changed substantially.

**Operator-visible changes:** High for calibration operators.

**Config file changes:** calibration-related expectations became more concrete.

**API / contract changes:** calibration pipeline and outputs matured significantly.

**Internal / architectural changes:** calibration becomes a first-class subsystem, not a stub.

**Why the order:** The project had enough operational surface by now to support a specialized workflow like calibration v2.

**Commit explanations:**
- `81ef8a6`: made calibration collection continuous and usable
- `e694d2d`: added the real post-run fitter pipeline
- `38aca4f`: exposed calibration v2 through a purpose-built UI
- `98a5951`: cleaned up legacy calibration artifacts and docs

---

## Version 0.11.0 — Phased Experiments and Auto Reports

### Rationale for this boundary

The theme here is experiment discipline: phases, auto-logging, auto-report generation, and polish around those flows. It is separate from calibration v2 because it changes the general experiment lifecycle rather than a specialized subsystem.

### Date range

2026-03-17 20:36..22:06

### Commit range

`bc41589..3b6a175`

### Themes in this version

- experiment phase tracking
- automatic operator/system logging
- automatic report generation

### Cluster 0.11.1 — Lifecycle formalization

**Commits:** `bc41589`, `aad5eab`, `d8421e6`, `7f0e5d1`, `3b6a175`

**Goal:** make experiment execution explicitly phased and self-documenting.

**Approach:** improve the UI baseline, add formal phases, add auto-log/report behavior, then polish the resulting workflow and docs.

**What changed:**
- Fixed: date axes, Russian labels, layout polish (`bc41589`)
- Added: experiment phase tracking from preparation to teardown (`aad5eab`)
- Added: auto-log system events and auto-generate reports on finalize (`d8421e6`)
- Fixed: phase-widget and empty-state issues exposed by that rollout (`7f0e5d1`)
- Added: calibration start integration and Russian docs sync (`3b6a175`)

**Breaking changes:** None at API level, but the operator lifecycle changed meaningfully.

**Operator-visible changes:** Very high. This is where the software begins to lead operators through named phases rather than leaving the lifecycle implicit.

**Config file changes:** None major.

**API / contract changes:** experiment phase semantics become part of the system vocabulary.

**Internal / architectural changes:** logging/reporting become lifecycle-coupled instead of ad hoc.

**Why the order:** Once calibration and overview were in place, formalizing experiment lifecycle was the natural next stabilizer.

**Commit explanations:**
- `bc41589`: polished the visible graphing/UI baseline first
- `aad5eab`: introduced the phase model
- `d8421e6`: automated logging and reporting around that model
- `7f0e5d1`: cleaned up the rough edges exposed by rollout
- `3b6a175`: connected calibration-start workflow and synced docs

---

## Version 0.12.0 — First Lab-Usable Release

### Rationale for this boundary

Even without the deleted tag, `c22eca9` still deserves its own version boundary. It is the explicit “first production release” commit and is the clearest candidate for “first lab-usable release” in the history.

### Date range

2026-03-18 00:10..00:10

### Commit range

`c22eca9..c22eca9`

### Themes in this version

- first explicit release cut

### Cluster 0.12.1 — First release marker

**Commits:** `c22eca9`

**Goal:** declare that the product had crossed from intense build-out into something release-shaped.

**Approach:** cut an explicit release commit.

**What changed:**
- Added: release marker for the first production/lab-usable cut (`c22eca9`)

**Breaking changes:** None.

**Operator-visible changes:** This is more about project state than feature surface.

**Config file changes:** None.

**API / contract changes:** None.

**Internal / architectural changes:** Serves as the clean separation between “initial construction” and “post-release expansion/hardening”.

**Why the order:** The preceding versions collectively formed the first lab-usable system.

**Commit explanations:**
- `c22eca9`: declared the first release-worthy state of the project

---

## Version 0.13.0 — Remote Ops and Alarm V2

### Rationale for this boundary

This version is a concentrated operator-surface and safety-surface expansion: web monitoring, Telegram v2, pre-flight checks, alarm v2 backend, and alarm v2 GUI. That is a coherent release and much tighter than v1’s broader “operational surface expansion”.

### Date range

2026-03-18 00:52..02:38

### Commit range

`7ee15de..d3b58bd`

### Themes in this version

- read-only web monitoring
- Telegram bot v2 and escalation
- pre-flight checklist
- alarm v2 rollout

### Cluster 0.13.1 — Remote ops and alarm engine rewrite

**Commits:** `7ee15de`, `e553f11`, `ae70158`, `5678d96`, `4405348`, `88357b8`, `046ab6f`, `3f86b42`, `8070b2d`, `ac404db`, `d3b58bd`

**Goal:** make the system operable and monitorable beyond the desktop UI while upgrading alarm semantics.

**Approach:** widen the operational surface first, then replace the alarm core with v2 and wire it through engine and GUI.

**What changed:**
- Added: read-only web monitoring (`7ee15de`)
- Added: Telegram bot v2 with richer commands and escalation (`e553f11`)
- Added: pre-flight checklist and experiment form assistance (`ae70158`, `5678d96`)
- Fixed: Telegram polling startup/debug (`4405348`)
- Added: alarm v2 foundation, evaluator, providers/config parser, engine integration, and GUI (`88357b8`, `046ab6f`, `3f86b42`, `8070b2d`, `d3b58bd`)
- Fixed: removed a false interlock and gated `detector_warmup` correctly (`ac404db`)

**Breaking changes:** Alarm behavior changed significantly enough that it counts as a semantic breaking change for operators.

**Operator-visible changes:** Very high.

**Config file changes:** alarm configuration discipline deepened and became more powerful.

**API / contract changes:** alarm provider/evaluator/config parser contracts arrive here.

**Internal / architectural changes:** this is a major safety-surface expansion, not just UI growth.

**Why the order:** After a first release, the natural next step was remote operability and better alarm semantics.

**Commit explanations:**
- `7ee15de`: added the first lightweight monitoring web page
- `e553f11`: expanded Telegram into a real remote-ops surface
- `ae70158`: added pre-flight workflow discipline
- `5678d96`: reduced experiment-form friction with history-driven defaults
- `4405348`: stabilized Telegram polling startup
- `88357b8`: laid the alarm v2 backend foundations
- `046ab6f`: added composite/rate/threshold/stale alarm evaluation
- `3f86b42`: added alarm providers and config parser
- `8070b2d`: wired alarm v2 into engine behavior
- `ac404db`: fixed a false interlock and phase gating issue
- `d3b58bd`: made alarm v2 visible and operable in the GUI/docs

---

## Version 0.14.0 — Post-Release Stabilization

### Rationale for this boundary

This is a small but coherent stabilization release immediately after the remote ops/alarm v2 surge. Memory leaks, reconnect behavior, and headless tray-only monitoring belong together as a “make the just-expanded system livable” version.

### Date range

2026-03-18 10:45..10:59

### Commit range

`92e1369..c7ae2ed`

### Themes in this version

- memory leak fix
- GUI reconnect fix
- headless tray-only monitoring

### Cluster 0.14.1 — Post-release repair

**Commits:** `92e1369`, `e601ca9`, `c7ae2ed`

**Goal:** stabilize the newly expanded operator surface after first real use.

**Approach:** fix the worst immediate regressions, then add a deployment-friendly headless mode.

**What changed:**
- Fixed: broadcast-task memory leak, rate estimator trim, history cap (`92e1369`)
- Fixed: empty plots after reconnect and wrong experiment-status key (`e601ca9`)
- Added: tray-only mode for headless engine monitoring (`c7ae2ed`)

**Breaking changes:** None.

**Operator-visible changes:** Headless/tray-only mode is visible; the rest are “things stop breaking”.

**Config file changes:** None.

**API / contract changes:** None material.

**Internal / architectural changes:** shows the first true stabilization reflex after release.

**Why the order:** This is the expected “immediately fix what production shape exposed” release.

**Commit explanations:**
- `92e1369`: fixed the first serious post-release resource leak
- `e601ca9`: fixed reconnect and status-key regressions
- `c7ae2ed`: added a headless monitoring mode for real deployments

---

## Version 0.15.0 — First Hardware Deployment

### Rationale for this boundary

This is a hardware-reality release. The software meets real instruments and begins getting corrected by them: Thyracont protocol handling, Keithley behavior, pressure parsing, GPIB query races, and critical-channel rate semantics. This is one of the most important field-driven boundaries in the history.

### Date range

2026-03-18 17:12..2026-03-19 13:36

### Commit range

`d7c843f..1b5c099`

### Themes in this version

- first real hardware deployment fixes
- Thyracont V1 semantics
- Keithley and GPIB field corrections

### Cluster 0.15.1 — Hardware reality arrives

**Commits:** `d7c843f`, `4f717a5`, `8605a52`, `d0c40de`, `f3e62f5`, `d94e361`, `552f679`, `94ec2b6`, `1b5c099`

**Goal:** correct the software against what the actual lab hardware really does.

**Approach:** fix field failures first, then refine protocol and control semantics until the main hardware paths behave under real conditions.

**What changed:**
- Fixed: broad first hardware deployment issues spanning GPIB, Thyracont, Keithley, alarms, pressure card, docs (`d7c843f`)
- Fixed: Keithley source-off NaN → SQLite crash (`4f717a5`)
- Fixed: Thyracont probing and V1 protocol assumptions (`8605a52`, `d0c40de`, `f3e62f5`)
- Fixed: VISA bus lock and Query UNTERMINATED race (`d94e361`)
- Fixed: rate checks now only apply to critical channels and exclude disconnected sensors (`552f679`)
- Refactored: moved Keithley constant-power control loop host-side, away from blocking TSP script (`94ec2b6`)
- Added: live `P_target` updates and stop-button correction (`1b5c099`)

**Breaking changes:** Softly yes at device-behavior expectations.

**Operator-visible changes:** High for anyone using the real hardware stack.

**Config file changes:** critical-channel semantics and protocol expectations became sharper.

**API / contract changes:** instrument behavior contracts changed to reflect real devices, not assumptions.

**Internal / architectural changes:** field deployment begins to shape the code as strongly as design intent.

**Why the order:** Real devices are the fastest source of truth. Once they were in the loop, protocol and safety assumptions had to adapt quickly.

**Commit explanations:**
- `d7c843f`: first big field-deployment correction sweep
- `4f717a5`: fixed a real crash caused by Keithley source-off NaN
- `8605a52`: corrected Thyracont connect logic toward V1 semantics
- `d0c40de`: refined pressure formula and float parsing
- `f3e62f5`: corrected the exact V1 value format
- `d94e361`: fixed a real VISA bus race
- `552f679`: tightened rate checks around critical channels
- `94ec2b6`: moved power control to a more robust host-side loop
- `1b5c099`: made target power live-adjustable and stop behavior saner

---

## Version 0.16.0 — GPIB Stabilization and ZMQ Isolation

### Rationale for this boundary

This is one of the clearest iterative engineering marathons in the history. It stays a single version because the nine commits are all the same story: GPIB correctness under real conditions, then isolating ZMQ away from the GUI.

### Date range

2026-03-19 14:05..16:41

### Commit range

`5bc640c..f64d981`

### Themes in this version

- bus locking discipline
- timeouts/clear/IFC recovery strategy
- persistent sessions
- ZMQ subprocess isolation

### Cluster 0.16.1 — Transport stabilization marathon

**Commits:** `5bc640c`, `a0e9678`, `bb59488`, `946b454`, `fd229e9`, `31c4bae`, `5448f08`, `7efb8b7`, `f64d981`

**Goal:** make GPIB transport behavior reliable enough for continuous unattended polling.

**Approach:** repeatedly tighten bus-lock boundaries and recovery semantics until the protocol assumptions match reality, then isolate ZMQ from the GUI process.

**What changed:**
- Fixed: lock scope around open/close/query paths (`5bc640c`, `a0e9678`)
- Fixed/refactored: open-per-query, IFC reset, sequential polling, and hot-path clear strategy (`bb59488`, `946b454`, `fd229e9`, `31c4bae`)
- Fixed: command details like `KRDG?` plus GUI/ZMQ resilience (`5448f08`)
- Refactored: moved to persistent GPIB sessions in LabVIEW-like style (`7efb8b7`)
- Added: ZMQ subprocess isolation so GUI no longer imports `zmq` directly (`f64d981`)

**Breaking changes:** Transport behavior changed enough that this counts as an internal breaking rewrite.

**Operator-visible changes:** Mostly “the system stops hanging or glitching under load”.

**Config file changes:** None major.

**API / contract changes:** GPIB transport expectations changed materially.

**Internal / architectural changes:** one of the project’s most important reliability marathons.

**Why the order:** This is what happens when a real hardware bus refuses to tolerate naive assumptions.

**Commit explanations:**
- `5bc640c`: widened the bus lock
- `a0e9678`: made verify/query atomic under the lock
- `bb59488`: explored open-per-query plus bus reset recovery
- `946b454`: serialized polling on the bus
- `fd229e9`: tried aggressive clear/IFC recovery
- `31c4bae`: backed `clear()` out of the hot path and refined timing
- `5448f08`: corrected the command and stabilized a few visible regressions
- `7efb8b7`: switched to persistent sessions
- `f64d981`: isolated ZMQ into a subprocess so GUI stayed lighter and safer

---

## Version 0.17.0 — Diagnostics and Safety Expansion

### Rationale for this boundary

This release expands the system’s self-observation and deepens safety. Sensor diagnostics, vacuum trend prediction, Keithley safety, phase 2/3 safety work, audit-driven fixes, and ZMQ serialization corrections all belong to the same “make the system smarter and safer” wave.

### Date range

2026-03-20 13:04..2026-03-21 00:39

### Commit range

`856ad19..af94285`

### Themes in this version

- diagnostics subsystem rollout
- vacuum trend subsystem rollout
- deeper safety work
- audit-driven fixes

### Cluster 0.17.1 — Smarter analytics, deeper safety

**Commits:** `856ad19`, `757f59e`, `6eb8dfe`, `b21bca1`, `5d7fe2b`, `c1b9eb5`, `50e30e3`, `afabfe5`, `6ef43df`, `bbb5809`, `4b52de8`, `10d4d76`, `af94285`

**Goal:** improve both diagnostic intelligence and safety correctness in one coordinated wave.

**Approach:** roll out diagnostics and vacuum trend in staged backend→engine→GUI fashion, while simultaneously tightening safety and clearing audit findings.

**What changed:**
- Added: Keithley safety around slew rate/compliance and ZMQ subprocess hardening (`856ad19`)
- Added: SensorDiagnostics backend, engine integration, and GUI (`757f59e`, `6eb8dfe`, `b21bca1`)
- Added: VacuumTrendPredictor backend, engine integration, and GUI (`5d7fe2b`, `c1b9eb5`, `50e30e3`)
- Fixed: ZMQ datetime serialization and REP socket error handling (`afabfe5`)
- Added: Phase 2 and Phase 3 safety/correctness work (`6ef43df`, `bbb5809`)
- Fixed: deep review and audit findings (`4b52de8`, `10d4d76`)
- Fixed: assorted UI/CSV/adaptive-liveness/report toggles after rollout (`af94285`)

**Breaking changes:** Not a clean API break, but significant operational semantics changed.

**Operator-visible changes:** High on the analytics side, moderate on safety side.

**Config file changes:** diagnostics and vacuum trend config entered the project here.

**API / contract changes:** staged analytics subsystems became first-class contracts.

**Internal / architectural changes:** this version demonstrates the project’s preferred rollout style: backend first, then engine, then GUI.

**Why the order:** After hardware stabilization, the next leverage point was richer analytics plus another deeper safety pass.

**Commit explanations:**
- `856ad19`: tightened Keithley safety and hardened the ZMQ subprocess line
- `757f59e`: introduced SensorDiagnostics backend
- `6eb8dfe`: wired SensorDiagnostics into runtime config/engine
- `b21bca1`: exposed diagnostics in the GUI
- `5d7fe2b`: introduced VacuumTrend backend
- `c1b9eb5`: wired VacuumTrend into engine/config
- `50e30e3`: exposed VacuumTrend in the GUI
- `afabfe5`: fixed ZMQ serialization/reply handling edge cases
- `6ef43df`: opened the next safety-hardening phase
- `bbb5809`: deepened safety/correctness again
- `4b52de8`: closed review findings with targeted fixes/tests
- `10d4d76`: closed a larger audit bug batch
- `af94285`: cleaned up rollout regressions and UI/reporting fallout

---

## Version 0.18.0 — UI Refactor Merge and Post-Merge Cleanup

### Rationale for this boundary

This is another merge-shaped release. The `feature/ui-refactor` merge imported a substantial UI reshaping, and the following commits are the immediate cleanup necessary to make that merge viable on `master`.

### Date range

2026-03-21 02:39..12:35

### Commit range

`1ec93a6..f08e6bb`

### Themes in this version

- UI refactor merge
- post-merge safety/UI cleanup
- deprecation of old autosweep panel

### Cluster 0.18.1 — Refactor lands, fallout gets cleaned

**Commits:** `1ec93a6`, `c427247`, `a2f4bcd`, `1670bbe`, `2ab7283`, `dc84f0c`, `1dd7405`, `f08e6bb`

**Goal:** absorb the UI refactor branch and fix the regressions it surfaced.

**Approach:** merge first, then patch the obvious safety, data-split, channel/default, and control-surface issues immediately.

**What changed:**
- Changed: merged `feature/ui-refactor` into `master` (`1ec93a6`)
- Changed: updated docs/changelog/version around the merge (`c427247`)
- Fixed: safety, Thyracont fallback, SQLite read/write split, Keithley disconnect behavior (`a2f4bcd`)
- Fixed: UI card toggle/history/axis/channel refresh issues (`1670bbe`)
- Changed: default channels/web version and deprecated `autosweep_panel` (`2ab7283`)
- Fixed: removed QuickStart buttons causing `FAULT` with `P=0` (`dc84f0c`)
- Added: Keithley tab rename, time window buttons, forecast zone (`1dd7405`)
- Fixed: third audit wave issues (`f08e6bb`)

**Breaking changes:** UI behavior and some safety/runtime behaviors changed materially.

**Operator-visible changes:** High.

**Config file changes:** default channels and version strings shifted.

**API / contract changes:** read/write split and deprecations matter to developers and tests.

**Internal / architectural changes:** shows that merge commits often need their own cleanup release note.

**Why the order:** merge first, then stabilize the integrated state.

**Commit explanations:**
- `1ec93a6`: merged the UI refactor branch
- `c427247`: synchronized docs/version metadata with the new post-merge state
- `a2f4bcd`: fixed a mixed bag of important safety/runtime issues uncovered by merge
- `1670bbe`: fixed UI interaction fallout
- `2ab7283`: corrected defaults and marked obsolete UI surface for deprecation
- `dc84f0c`: removed a control that could trigger unsafe behavior
- `1dd7405`: rounded out the new UI surface with better naming/time controls
- `f08e6bb`: closed the immediate audit fallout

---

## Version 0.19.0 — Final-Batch Integration

### Rationale for this boundary

This release is another integration wave, but different from the UI merge. It is about joining a “final batch” of critical runtime fixes: single-instance lock, ZMQ request/reply routing, experiment I/O threading, and several overview/history fixes. It reads like one release note and deserves to stand alone.

### Date range

2026-03-21 15:20..2026-03-22 00:25

### Commit range

`9e2ce5b..dd42632`

### Themes in this version

- final-batch merge
- atomic single-instance guard
- ZMQ command/reply cleanup
- experiment I/O deblocking

### Cluster 0.19.1 — Integration hardening after UI refactor

**Commits:** `9e2ce5b`, `7618031`, `4df40c3`, `0603110`, `9942da1`, `6d39a08`, `45ae750`, `031491a`, `dd42632`

**Goal:** consolidate a batch of must-have runtime fixes before further feature work.

**Approach:** merge the batch, then tighten critical runtime guarantees and polish the affected operator surfaces.

**What changed:**
- Changed: merged final-batch branch with single-instance/ML/flight-recorder/driver work (`9e2ce5b`)
- Fixed: Telegram text sorting/compactness and pressure log-scale handling (`7618031`)
- Fixed: atomic single-instance lock (`4df40c3`)
- Fixed: correlation IDs and dedicated reply-consumer routing for ZMQ (`0603110`, `45ae750`)
- Fixed: proportional history load and plot sync (`9942da1`, `031491a`, `dd42632`)
- Fixed: experiment I/O moved off blocking path, removed double report generation (`6d39a08`)

**Breaking changes:** Single-instance semantics and ZMQ command flow changed materially.

**Operator-visible changes:** Moderate to high, especially in reliability and history behavior.

**Config file changes:** None significant.

**API / contract changes:** command/reply routing and experiment I/O assumptions changed.

**Internal / architectural changes:** shows a growing sensitivity to “anything blocking the operator path”.

**Why the order:** This kind of batch belongs before another large feature wave.

**Commit explanations:**
- `9e2ce5b`: brought in the final-batch integration branch
- `7618031`: polished Telegram output semantics
- `4df40c3`: made single-instance locking atomic
- `0603110`: added correlation IDs to command/reply flow
- `9942da1`: improved history load proportionality and plot sync
- `6d39a08`: moved experiment I/O off blocking path
- `45ae750`: finished ZMQ reply routing cleanup
- `031491a`: corrected time-window and history behavior
- `dd42632`: made graph axes snap consistently to data start

---

## Version 0.20.0 — Audit-v2, Parquet v1, and Reporting

### Rationale for this boundary

This is a “quality and artifacts” release: audit-v2 merge, first Parquet archive work, CI, and a professional reporting push. Those are all part of the same broad goal: make the system operationally credible, export-capable, and report-capable.

### Date range

2026-03-22 16:11..2026-03-23 00:37

### Commit range

`0fdc507..29d2215`

### Themes in this version

- audit-v2 merge
- Parquet archive v1
- CI workflow
- professional reporting

### Cluster 0.20.1 — Artifact and quality surface expansion

**Commits:** `0fdc507`, `fc1c61b`, `ccf98c9`, `f0c68c6`, `423c6d5`, `8dc07f7`, `a066cd7`, `b7265bb`, `29d2215`

**Goal:** widen the project’s operational credibility through artifact quality, CI, and audit-driven fixes.

**Approach:** absorb the audit-v2 fix batch, add Parquet export, add CI, then raise reporting quality substantially.

**What changed:**
- Changed: merged audit-v2 fixes (`0fdc507`)
- Added: first Parquet archive export on finalize and archive-table integration (`fc1c61b`, `f0c68c6`)
- Added: CI workflow (`ccf98c9`)
- Fixed: archive end-date and end-time semantics (`423c6d5`)
- Added: professional human-readable reporting and later ГОСТ formatting (`8dc07f7`, `a066cd7`)
- Fixed: reporting layout/graph/page-break issues (`b7265bb`)
- Fixed: audit regressions touching preflight, multi-day DB, overview resolver, parquet docs (`29d2215`)

**Breaking changes:** Reporting/archive behavior changed meaningfully but not via hard API break.

**Operator-visible changes:** High for reports and archive artifacts.

**Config file changes:** None major.

**API / contract changes:** archive/reporting outputs became more formalized.

**Internal / architectural changes:** the system stops being “just a DAQ” and becomes an evidence/report producer.

**Why the order:** after runtime integration stabilized, artifact quality became the next obvious professionalization step.

**Commit explanations:**
- `0fdc507`: merged the audit-v2 fix wave
- `fc1c61b`: introduced Parquet alongside CSV at finalize
- `ccf98c9`: added GitHub Actions CI
- `f0c68c6`: made Parquet visible in archive metadata and table views
- `423c6d5`: corrected archive end-date semantics
- `8dc07f7`: introduced polished report generation
- `a066cd7`: pushed reports toward ГОСТ-compliant formatting
- `b7265bb`: fixed multi-channel and pagination issues in reports
- `29d2215`: cleaned the regressions exposed by the new artifact/reporting work

---

## Version 0.21.0 — Recovery and Deployment Hardening

### Rationale for this boundary

This is a classic “everything discovered in deployment keeps getting hardened” release. GPIB recovery, scheduler reconnect, preflight severity tuning, non-blocking GUI/launcher behavior, single-instance enforcement beyond the engine, and deployment-specific fixes all belong together.

### Date range

2026-03-23 14:59..2026-03-25 12:59

### Commit range

`ab57e01..f217427`

### Themes in this version

- GPIB recovery escalation
- reconnect logic
- GUI/launcher non-blocking fixes
- standalone single-instance protection

### Cluster 0.21.1 — Deployment hardening marathon

**Commits:** `ab57e01`, `ea5a8da`, `86e8e8c`, `c10e617`, `dfd6021`, `8bac038`, `6d0f5ba`, `bab4d8a`, `4eb5f1a`, `3c46dfb`, `e7d4fc5`, `f47762d`, `f217427`

**Goal:** harden the system against the sort of issues that only show up once it is run like a lab tool, not a developer app.

**Approach:** escalate bus recovery, tune preflight semantics, then make GUI/launcher interactions non-blocking and singleton-safe.

**What changed:**
- Fixed: GPIB auto-recovery and escalating IFC/unaddressing reset (`ab57e01`, `ea5a8da`)
- Fixed: preflight sensor health from hard error to warning and encoding restoration (`86e8e8c`, `dfd6021`)
- Fixed: standalone instrument disconnect/reconnect after consecutive errors (`c10e617`)
- Fixed: non-blocking alarm v2 status polling and bridge health issues (`8bac038`, `6d0f5ba`, `4eb5f1a`)
- Added: standalone GUI/launcher single-instance protection (`bab4d8a`)
- Fixed: debounce/live-update/workspace layout/engine restart/permission edge cases (`3c46dfb`, `e7d4fc5`, `f47762d`, `f217427`)

**Breaking changes:** None hard, but deployment semantics improved materially.

**Operator-visible changes:** High in terms of “it behaves sanely under deployment stress”.

**Config file changes:** preflight severity semantics shifted.

**API / contract changes:** recovery expectations and singleton behavior matured.

**Internal / architectural changes:** this is the clearest pre-audit example of deployment realities pushing the architecture.

**Why the order:** once real deployment stress surfaced, hardening that stress path had to outrank new features.

**Commit explanations:**
- `ab57e01`: introduced aggressive GPIB timeout recovery
- `ea5a8da`: escalated the GPIB recovery ladder further
- `86e8e8c`: softened sensor-health preflight from error to warning
- `c10e617`: added disconnect/reconnect logic in scheduler
- `dfd6021`: restored encoding and retained warning semantics
- `8bac038`: removed blocking from alarm v2 status polling
- `6d0f5ba`: fixed bridge heartbeat false kills and blocking command path
- `bab4d8a`: enforced single-instance beyond just the engine
- `4eb5f1a`: fixed more launcher bridge/command blocking gaps
- `3c46dfb`: added debounce and non-blocking Keithley live update
- `e7d4fc5`: fixed experiment workspace layout at 1080p
- `f47762d`: made launcher restarts non-blocking
- `f217427`: fixed shift modal re-entrancy and `--force` PermissionError handling

---

## Version 0.22.0 — Pre-Phase-2d Hardening Prep

### Rationale for this boundary

This is the explicit pre-2d cleanup wave. It is not yet the big structured hardening effort, but it clears ground for it: audit fixes, GUI non-blocking cleanup, PyInstaller unblock, Phase 1/2a/2b/2c fix blocks, and one late UI preset tweak.

### Date range

2026-03-31 03:17..2026-04-08 22:16

### Commit range

`9676165..1698150`

### Themes in this version

- audit-driven prep fixes
- PyInstaller unblock
- pre-Phase-2d fix blocks

### Cluster 0.22.1 — Get ready for structured hardening

**Commits:** `9676165`, `9feaf3e`, `a60abc0`, `0333e52`, `8a24ead`, `b185fd3`, `1698150`

**Goal:** close enough obvious issues that the subsequent structured hardening can focus on deeper invariants rather than surface noise.

**Approach:** apply targeted audit fixes, unblock the build, then run Phase 1/2a/2b/2c closure blocks in sequence.

**What changed:**
- Fixed: audit findings around `plugins.yaml`, `sensor_diagnostics`, GUI non-blocking (`9676165`, `9feaf3e`)
- Fixed: PyInstaller build blocker (`a60abc0`)
- Fixed: Phase 1, 2a, 2b, and 2c pre-deployment/hardening findings (`0333e52`, `8a24ead`, `b185fd3`)
- Changed: one overview preset label from `"Сутки"` to `"Всё"` (`1698150`)

**Breaking changes:** None major.

**Operator-visible changes:** Mostly negative-space improvements plus one preset rename.

**Config file changes:** cleanup around plugins/config references.

**API / contract changes:** little direct API churn, more closure of known issues.

**Internal / architectural changes:** this is the staging ground for Phase 2d.

**Why the order:** the team is clearly preparing for a more formal hardening campaign.

**Commit explanations:**
- `9676165`: closed several Codex-found prep issues
- `9feaf3e`: cleaned remaining GUI non-blocking and dead-code issues
- `a60abc0`: unblocked PyInstaller builds
- `0333e52`: landed Phase 2a safety fixes
- `8a24ead`: landed Phase 2b observability/resilience fixes
- `b185fd3`: landed Phase 2c final hardening before Phase 3
- `1698150`: adjusted the overview preset naming

---

## Version 0.23.0 — Audit Corpus and Reality Map

### Rationale for this boundary

This release is unusual and deserves to stay unusual in the changelog research. The product itself changes relatively little here; what changes is the project’s self-understanding. Massive audit artifacts, verification passes, deep dives, dependency sweeps, and documentation-reality reconciliation all arrive together. That is absolutely a release-worthy historical chapter.

### Date range

2026-04-09 00:45..2026-04-13 16:09

### Commit range

`380df96..1d71ecc`

### Themes in this version

- exhaustive audit corpus
- verification and deep dives
- docs vs code reconciliation

### Cluster 0.23.1 — The project audits itself

**Commits:** `380df96`, `fd99631`, `fd8c8bf`, `847095c`, `5d618db`, `10667df`, `31dbbe8`, `3e20e86`, `916fae4`, `a108519`, `24b928d`, `7aaeb2b`, `995f7bc`, `6eb7d3e`, `ddf6459`, `1d71ecc`

**Goal:** build a high-confidence map of what the software actually is, what remains wrong, and what the docs falsely claim.

**Approach:** run multiple deep audit passes, then synthesize and fold the results back into project docs and workflow rules.

**What changed:**
- Added: CC and Codex deep audit passes and verification artifacts (`380df96`, `fd99631`, `5d618db`, `10667df`, `31dbbe8`, `3e20e86`, `916fae4`, `a108519`, `24b928d`, `7aaeb2b`)
- Added: hardening-pass doc imported from branch and audit artifact ignore rules (`847095c`, `fd8c8bf`)
- Added: doc-vs-code reality map (`995f7bc`)
- Changed: `CLAUDE.md` and team-lead guidance to match the audited code reality (`6eb7d3e`, `ddf6459`, `1d71ecc`)

**Breaking changes:** Not code-level, but it changes the governance of future work.

**Operator-visible changes:** Minimal directly, but this release is what made the later hardening targeted instead of intuitive.

**Config file changes:** documentation around config coverage and module inventory was corrected here.

**API / contract changes:** not code APIs, but architectural contracts were rewritten more precisely.

**Internal / architectural changes:** the project becomes self-auditing and evidence-driven.

**Why the order:** all of Phase 2d is easier to understand as a response to this version.

**Commit explanations:**
- `380df96`: added CC deep audit pass
- `fd99631`: added Codex deep audit pass
- `fd8c8bf`: ignored local audit artifacts in git
- `847095c`: imported hardening-pass document from side branch
- `5d618db`: re-verified the prior HIGH findings
- `10667df`: produced exhaustive SafetyManager analysis
- `31dbbe8`: traced persistence-first invariant end to end
- `3e20e86`: deep-dived drivers and transport failure modes
- `916fae4`: performed dependency/CVE sweep
- `a108519`: audited reporting/analytics/plugins
- `24b928d`: audited config files as safety surface
- `7aaeb2b`: synthesized the whole audit corpus into a master triage
- `995f7bc`: built a doc-vs-code reality map
- `6eb7d3e`: rewrote team-lead guidance against current reality
- `ddf6459`: filled missing config references in docs
- `1d71ecc`: expanded module index and corrected safety invariants in docs

---

## Version 0.24.0 — Phase 2d Safety and Persistence

### Rationale for this boundary

This is the major structured hardening release proper. It is the cleanest example of a version that should exist as its own release note: Block A safety work, alarm config hardening, fail-closed coercion, atomic file writes, shield follow-up, persistence integrity, NaN-state fix, and checkpoint status.

### Date range

2026-04-13 16:27..23:22

### Commit range

`88feee5..23929ca`

### Themes in this version

- Block A safety hardening
- alarm config hardening
- atomic file writes and WAL verification
- persistence integrity

### Cluster 0.24.1 — Structured hardening lands

**Commits:** `88feee5`, `1446f48`, `ebac719`, `1b12b87`, `e068cbf`, `d3abee7`, `5cf369e`, `104a268`, `21e9c40`, `23929ca`

**Goal:** close the highest-value audit findings in a disciplined, block-structured way.

**Approach:** tackle safety, then config typing, then alarm config/safety bridge, then atomic file writes/WAL, then persistence integrity and state-value filtering.

**What changed:**
- Fixed: web XSS and `SafetyManager` hardening, plus a `T` regression (`88feee5`)
- Fixed: heartbeat gap in `RUN_PERMITTED` and safer config error handling (`1446f48`, `ebac719`)
- Fixed: alarm config hardening and safety→experiment bridge (`1b12b87`, `e068cbf`)
- Added: atomic file writes and WAL verification (`d3abee7`)
- Fixed: post-fault cancellation shielding holes (`5cf369e`)
- Fixed: persistence integrity, including later NaN-valued status filtering (`104a268`, `21e9c40`)
- Changed: project status checkpoint for Block A+B complete (`23929ca`)

**Breaking changes:** Safety/config/persistence semantics got stricter.

**Operator-visible changes:** Mostly invisible, but this is exactly the kind of release that changes whether the system deserves trust.

**Config file changes:** fail-closed and stricter config behavior is a major theme.

**API / contract changes:** several core invariants became enforceable in code, not just in docs.

**Internal / architectural changes:** arguably the strongest hardening step in the whole repository history.

**Why the order:** this is the direct code response to the audit-corpus version.

**Commit explanations:**
- `88feee5`: landed the first 2d safety/XSS hardening block
- `1446f48`: closed the RUN_PERMITTED heartbeat hole
- `ebac719`: made `SafetyConfig` coercion fail-closed
- `1b12b87`: hardened alarm config and linked safety into experiment state
- `e068cbf`: corrected issues exposed immediately after `1b12b87`
- `d3abee7`: made file writes atomic and verified WAL mode
- `5cf369e`: tightened shielding in post-fault cleanup
- `104a268`: landed the main persistence-integrity block
- `21e9c40`: filtered NaN-valued statuses out of the persist set
- `23929ca`: recorded the completion checkpoint for A+B

---

## Version 0.25.0-pre — Current Hardening Line

### Rationale for this boundary

This is the unreleased current line. It is no longer “Phase 2d proper”; it is the closure and aftermath: lint cleanup, Jules R2 fixes, config fail-closed completion, declaration of 2d completion, first Phase 2e Parquet-finalize integration, and the round-2 audit/inventory docs that validate the new state.

### Date range

2026-04-14 01:14..04:19

### Commit range

`efe6b49..5b3ca29`

### Themes in this version

- late 2d closure fixes
- config fail-closed completion
- Phase 2e Parquet stage 1
- round-2 audit documentation

### Cluster 0.25.1 — Hardening closure and archive line

**Commits:** `efe6b49`, `f4c256f`, `74f6d21`, `89ed3c1`, `0cd8a94`, `445c056`, `855870b`, `5ad0156`, `1c75967`, `66f9870`, `6535c9a`, `88c308c`, `5b3ca29`

**Goal:** finish the remaining 2d contract closures, open Phase 2e, add Parquet finalize export, and preserve the second-round audit state.

**Approach:** clean incidental debt, fix the late ordering/state gaps, complete fail-closed config work, declare 2d complete, then begin archive stage 1 and preserve the audit context around it.

**What changed:**
- Changed: accumulated lint/log cleanup (`efe6b49`, `f4c256f`)
- Fixed: Jules round-2 ordering and state-mutation gaps (`74f6d21`)
- Fixed: fail-closed config completion and cleanup (`89ed3c1`)
- Changed: declared Phase 2d complete and opened Phase 2e (`0cd8a94`)
- Added: Parquet archive at finalize (`445c056`)
- Added: round-2 audit/inventory/reference docs (`855870b`, `5ad0156`, `1c75967`, `66f9870`, `6535c9a`, `88c308c`, `5b3ca29`)

**Breaking changes:** Config strictness increased; archive surface expanded.

**Operator-visible changes:** mostly invisible, except for archive output and some cleaner runtime behavior.

**Config file changes:** fail-closed completion is the headline.

**API / contract changes:** archive/finalize contract now includes Parquet stage 1.

**Internal / architectural changes:** this version is best seen as the final closure of the hardening cycle plus the first archive-forward step.

**Why the order:** it naturally follows the A+B checkpoint and begins the next work line without pretending the project is stable enough for `1.0.0`.

**Commit explanations:**
- `efe6b49`: cleaned accumulated lint debt
- `f4c256f`: removed accidentally committed logs and hardened ignore rules
- `74f6d21`: closed late ordering/state-mutation gaps found by Jules
- `89ed3c1`: completed fail-closed config work
- `0cd8a94`: declared Phase 2d complete
- `445c056`: started Phase 2e with Parquet-at-finalize
- `855870b`: added branch inventory doc for three-track audit input
- `5ad0156`: added repo/dead-code/CC findings summaries
- `1c75967`: recorded Codex round-2 semantic audit
- `66f9870`: recorded CC round-2 inventory
- `6535c9a`: recorded remote branch cleanup
- `88c308c`: updated project-status numbers for audit round 2
- `5b3ca29`: preserved historical pre-Phase-2c audit artifacts

---

## Cross-version patterns

### Pattern: Safety architecture evolution

The safety story has a clear arc. `0.5.0` creates `SafetyManager`, `SafetyBroker`, and the fail-on-silence stance. `0.7.0` adds the first broad audit/P0/P1 hardening around that model. `0.15.0` and `0.17.0` then let real hardware and deeper review reshape details such as critical-channel rate semantics and additional correctness phases. `0.23.0` turns safety into an object of exhaustive study, and `0.24.0` converts those findings into structured hardening. The important historical point is that CryoDAQ’s safety posture was not born complete; it was created early, then repeatedly sharpened by audits and hardware contact.

### Pattern: GPIB transport stabilization

The GPIB story is a textbook example of reality forcing protocol discipline. Early versions assumed more than the bus would tolerate. `0.15.0` exposes the first true field failures. `0.16.0` is then a concentrated stabilization marathon: lock scope, query atomicity, reset strategy, sequential polling, hot-path clear removal, persistent sessions. `0.21.0` adds recovery escalation. For a future maintainer, the key lesson is that the final transport design is the result of repeated empirical correction, not theoretical elegance.

### Pattern: Calibration evolution

Calibration begins as a stub in `0.3.0`, becomes visibly important in `0.10.0` with continuous SRDG and the v2 fitter pipeline, is integrated into broader lifecycle/documentation work in `0.11.0`, and later becomes one of the central audit targets in `0.23.0` and `0.24.0`. The calibration story is also one of moving from “one-off tool” to “stateful subsystem with persistence and invariants”.

### Pattern: Config loading discipline

Early versions assume configuration exists and is roughly correct. The first release waves focus on functionality, not loader discipline. The audit corpus in `0.23.0` reframes configs as safety surfaces, and `0.24.0` plus `0.25.0-pre` move the project toward typed fail-closed loading for the safety-critical configs. That shift is one of the most important cross-version architectural improvements.

### Pattern: Reporting and archive maturity

Experiments and export appear early in `0.3.0`, but artifact quality only becomes a sustained theme later. `0.20.0` adds Parquet v1, CI, and serious report formatting. `0.24.0` hardens persistence/file-write semantics, and `0.25.0-pre` begins the next archive step by writing Parquet at finalize. The reporting/archive story is therefore not “one feature landed”; it is a progression from raw data export to professional artifacts.

### Pattern: Test and audit growth

The first big test suite arrives shockingly early in `0.4.0`. That foundation enables later aggressive changes. Review- and audit-driven fix waves appear in `0.5.0`, `0.7.0`, `0.17.0`, `0.20.0`, and `0.22.0`, then culminate in the dedicated audit corpus of `0.23.0`. This is unusual and worth preserving in the changelog story: the repository’s maturity is as much about learning to verify itself as it is about adding features.

---

## Deprecations timeline

| Version | Item | Deprecated in | Removed in | Notes |
|---|---|---|---|---|
| `0.18.0` | `autosweep_panel` | `2ab7283` | not yet | Explicitly marked deprecated after UI refactor merge |
| `0.18.0` | old default-channel assumptions | `2ab7283` | not yet | Default handling changed during post-merge cleanup |
| `0.23.0` | inaccurate `CLAUDE.md` module/config inventory | `6eb7d3e`, `ddf6459`, `1d71ecc` | not applicable | Governance/documentation deprecation rather than code API |
| `0.24.0` | silent/loose safety-config assumptions | `88feee5`, `1446f48`, `ebac719`, `1b12b87` | ongoing | Replaced by fail-closed typed loading and stricter coercion |
| `0.25.0-pre` | accidentally committed runtime logs in repo | `f4c256f` | `f4c256f` | Operational hygiene cleanup |

---

## Breaking changes timeline

| Version | Change | Commit | Affects | Migration |
|---|---|---|---|---|
| `0.7.0` | `Reading.instrument_id` becomes first-class and required | `61dca77` | drivers, storage, consumers | ensure every driver populates `instrument_id`; update downstream assumptions |
| `0.13.0` | alarm engine semantics shift to alarm v2 | `88357b8`, `046ab6f`, `3f86b42`, `8070b2d` | engine, GUI, operators | migrate configs and operator expectations to v2 semantics |
| `0.15.0` | Keithley constant-power control moves host-side | `94ec2b6` | Keithley runtime behavior | review assumptions about TSP-side control ownership |
| `0.16.0` | GPIB transport behavior rewritten around sequential/persistent sessions | `946b454`, `7efb8b7` | transport layer | treat old open-per-query assumptions as obsolete |
| `0.18.0` | UI refactor merge changes control surface and default assumptions | `1ec93a6`, `2ab7283` | operators, tests | update UI expectations and remove reliance on old defaults |
| `0.19.0` | single-instance locking becomes atomic and mandatory | `4df40c3` | launcher/engine startup | rely on lock semantics instead of ad hoc coexistence |
| `0.24.0` | safety/alarm config handling becomes stricter and more fail-closed | `1446f48`, `ebac719`, `1b12b87` | config authors | invalid or loosely typed configs no longer limp through |
| `0.25.0-pre` | fail-closed config completion tightens remaining config paths | `89ed3c1` | deployment config authors | validate config more carefully before startup |

---

## Operator-facing changes highlights

### `0.1.0`
- no direct operator surface yet; this is infrastructure birth

### `0.2.0`
- first live temperature GUI and Keithley integration appear

### `0.3.0`
- engine/GUI entry points, experiments, notifications, and web monitoring become real

### `0.4.0`
- all main tabs go live, Russian docs/manual arrive, launcher appears, conductivity workflow becomes usable

### `0.5.0`
- safety behavior becomes more authoritative and less permissive

### `0.6.0`
- operators get overview dashboard, XLSX export, disk monitor, and cooldown prediction

### `0.7.0`
- fewer dangerous edge cases; less visible feature growth, more trust-building fixes

### `0.8.0`
- RC merge resets the product baseline for everything that follows

### `0.9.0`
- overview becomes a real dashboard hub; shift handover becomes structured

### `0.10.0`
- calibration becomes a proper multi-step workflow with dedicated GUI

### `0.11.0`
- experiments get named phases, automatic logs, and automatic reports

### `0.12.0`
- first explicit lab-usable release cut

### `0.13.0`
- web monitoring, Telegram v2, pre-flight checks, and alarm v2 become operator-visible

### `0.14.0`
- headless tray-only monitoring appears; some painful regressions disappear

### `0.15.0`
- real hardware behavior gets corrected; pressure and Keithley interaction become more trustworthy

### `0.16.0`
- operators mostly notice that GPIB polling behaves better and GUI/ZMQ separation is more robust

### `0.17.0`
- diagnostics and vacuum trend panels arrive; safety behavior deepens again

### `0.18.0`
- UI refactor changes control surface; some risky controls are removed

### `0.19.0`
- single-instance protection and command routing become more reliable; overview history behavior improves

### `0.20.0`
- Parquet appears in archive artifacts; reports look professional

### `0.21.0`
- deployment behavior becomes less blocking, more recoverable, and more singleton-safe

### `0.22.0`
- mostly a hardening-prep release, plus one overview preset rename

### `0.23.0`
- little direct operator change, but this release produces the audit evidence that drives later trust improvements

### `0.24.0`
- operators mostly notice fewer invisible integrity and safety failure modes

### `0.25.0-pre`
- archive output expands again via Parquet finalize export; config failures become stricter and earlier

---

## Open questions

- Is `0.12.0` the best number for the “first lab-usable release”, or should the eventual polished changelog renumber that boundary to a smaller minor number since the old tag is gone?
- Are the “Add files via upload” task snapshots in `0.5.0`, `0.6.0`, and `0.7.0` worth mentioning in the final changelog at all, or should the polished changelog collapse them into neighboring narrative without explicit bullets?
- Should `0.8.0` remain a single-version merge release in the polished changelog, or should the final writer absorb it into `0.9.0` to reduce visual fragmentation?
- Does the human-facing changelog need separate “hardware deployment” and “transport stabilization” versions (`0.15.0` and `0.16.0`), or should they merge into one operator-facing note with two subsections?
- Is `0.23.0` too unusual to present as a normal release in the final changelog, and would a special “Audit and verification epoch” framing serve readers better?
- Should `0.25.0-pre` remain explicitly pre-release in the final numbering until Tier 1 fixes and GUI merge land?

---

## Chronological appendix

All 205 first-parent commits on `master`, assigned to the proposed v2 version scheme.

| SHA | Date | Subject | Assigned version |
|---|---|---|---|
| `be52137` | 2026-03-14T00:29:31+03:00 | Add CLAUDE.md with project architecture and constraints | `0.1.0` |
| `dea213f` | 2026-03-14T00:31:54+03:00 | Add cryodaq-team-lead skill for agent team orchestration | `0.1.0` |
| `f7cdc00` | 2026-03-14T00:35:21+03:00 | Add project foundation: pyproject.toml, directory structure, driver ABC, DataBroker | `0.1.0` |
| `2882845` | 2026-03-14T00:39:41+03:00 | Add SQLiteWriter, ZMQ bridge, and instrument Scheduler | `0.1.0` |
| `0c54010` | 2026-03-14T00:43:37+03:00 | Add LakeShore 218S driver, temperature panel GUI, and tests | `0.2.0` |
| `577b02f` | 2026-03-14T01:18:12+03:00 | Keithley 2604B: TSP P=const, driver, interlocks | `0.2.0` |
| `258f643` | 2026-03-14T01:19:37+03:00 | Update CLAUDE.md with build commands, data flow, and module index | `0.2.0` |
| `75ebdc1` | 2026-03-14T01:23:47+03:00 | Add AlarmEngine, analytics plugin pipeline, and two plugins | `0.2.0` |
| `e64b516` | 2026-03-14T01:25:46+03:00 | Add full architecture doc and team lead SKILL v2 | `0.3.0` |
| `0b79fa1` | 2026-03-14T01:48:48+03:00 | Engine + GUI: entry points, main window, alarm panel, instrument status | `0.3.0` |
| `baaec03` | 2026-03-14T01:53:55+03:00 | Experiment lifecycle, data export, replay, Telegram notifications | `0.3.0` |
| `e4bbcb6` | 2026-03-14T01:59:20+03:00 | Web dashboard, calibration stub, gitignore, updated docs | `0.3.0` |
| `33e51f3` | 2026-03-14T02:12:20+03:00 | Fix mock mode: stub interlock actions, plugin loader init compat | `0.4.0` |
| `e4546df` | 2026-03-14T02:15:32+03:00 | Fix 5 test failures: timezone, WAL check, mock range, timeout setup | `0.4.0` |
| `734f641` | 2026-03-14T02:27:30+03:00 | Add comprehensive test suite: 118 tests across all modules | `0.4.0` |
| `fdbeb95` | 2026-03-14T02:33:38+03:00 | Add Keithley 2604B to instruments.yaml (USB-TMC mock) | `0.4.0` |
| `3cb98dd` | 2026-03-14T02:41:18+03:00 | Fix Windows event loop: SelectorEventLoop for pyzmq compatibility | `0.4.0` |
| `641f21e` | 2026-03-14T02:42:39+03:00 | Add README.md: architecture, quick start, project status (Russian) | `0.4.0` |
| `167eb7d` | 2026-03-14T03:13:22+03:00 | Thyracont VSP63D driver, periodic reports, live web dashboard | `0.4.0` |
| `3dbd222` | 2026-03-14T03:18:47+03:00 | Add comprehensive operator manual in Russian (docs/operator_manual.md) | `0.4.0` |
| `da825f1` | 2026-03-14T03:27:55+03:00 | GUI: Keithley, pressure, analytics panels — all tabs now live | `0.4.0` |
| `77638b0` | 2026-03-14T03:40:26+03:00 | Operator launcher, SQLite thread-safety fix, aiohttp dependency | `0.4.0` |
| `dabce60` | 2026-03-14T03:56:52+03:00 | Keithley smua+smub, Telegram bot commands, portable deployment | `0.4.0` |
| `2f31378` | 2026-03-14T04:07:59+03:00 | Keithley control panel + thermal conductivity chain measurement | `0.4.0` |
| `84b01a7` | 2026-03-14T04:27:20+03:00 | Steady-state predictor + auto-sweep measurement panel | `0.4.0` |
| `b2b4d97` | 2026-03-14T05:02:57+03:00 | Channel manager + instrument connection settings UI | `0.4.0` |
| `603a472` | 2026-03-14T13:29:44+03:00 | Safety architecture: SafetyManager, SafetyBroker, fail-on-silence | `0.5.0` |
| `941d5e3` | 2026-03-14T16:31:42+03:00 | Code review: 13 fixes — token revocation, safety, thread-safety, tests | `0.5.0` |
| `99df7eb` | 2026-03-14T17:20:03+03:00 | Update CLAUDE.md and README.md to current project state | `0.5.0` |
| `3f4b8fa` | 2026-03-14T17:40:40+03:00 | Add files via upload | `0.5.0` |
| `40b4ffb` | 2026-03-14T17:56:34+03:00 | Add files via upload | `0.5.0` |
| `efe16d3` | 2026-03-14T18:12:48+03:00 | Add files via upload | `0.5.0` |
| `dc5f3c6` | 2026-03-14T18:13:22+03:00 | Add files via upload | `0.5.0` |
| `a8e8bbf` | 2026-03-14T18:18:02+03:00 | SAFETY: persistence-first ordering — disk before subscribers | `0.5.0` |
| `9217489` | 2026-03-14T18:49:09+03:00 | Cooldown predictor integration: library refactor, service, GUI, tests | `0.6.0` |
| `dd2dd2c` | 2026-03-14T18:59:53+03:00 | Update CLAUDE.md and README.md: cooldown integration, persistence-first, stats | `0.6.0` |
| `4dca478` | 2026-03-14T19:13:02+03:00 | Add files via upload | `0.6.0` |
| `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs | `0.6.0` |
| `7d8cc1f` | 2026-03-14T20:08:19+03:00 | Update CLAUDE.md and README.md: overview tab, XLSX, DiskMonitor, stats | `0.6.0` |
| `68324c2` | 2026-03-14T20:26:27+03:00 | Add files via upload | `0.6.0` |
| `9390419` | 2026-03-14T22:53:45+03:00 | Add files via upload | `0.6.0` |
| `e9a538f` | 2026-03-14T23:17:09+03:00 | SAFETY: 14 audit fixes — FAULT_LATCHED latch, status checks, heartbeat | `0.7.0` |
| `678ff50` | 2026-03-15T02:25:13+03:00 | Add files via upload | `0.7.0` |
| `1bd6c4e` | 2026-03-15T02:39:36+03:00 | P0: 5 critical fixes — alarm pipeline, safety state, P/V/I limits, latched flag | `0.7.0` |
| `0f8dd59` | 2026-03-15T02:44:01+03:00 | Add files via upload | `0.7.0` |
| `de715dc` | 2026-03-15T03:02:21+03:00 | P1: 8 lab deployment fixes — async ZMQ, REAL timestamps, paths, sessions | `0.7.0` |
| `8d146bc` | 2026-03-15T03:08:22+03:00 | Add files via upload | `0.7.0` |
| `61dca77` | 2026-03-15T03:48:26+03:00 | BREAKING: instrument_id is now a first-class field on Reading dataclass | `0.7.0` |
| `9d48c41` | 2026-03-15T15:58:53+03:00 | Add files via upload | `0.7.0` |
| `2afdbc1` | 2026-03-15T16:42:06+03:00 | Add files via upload | `0.7.0` |
| `0078d57` | 2026-03-15T18:02:34+03:00 | Add files via upload | `0.7.0` |
| `dc2ea6a` | 2026-03-17T15:33:46+03:00 | Merge CRYODAQ-CODEX RC into master (v0.11.0-rc1) | `0.8.0` |
| `29652a2` | 2026-03-17T16:00:30+03:00 | chore: delete merged branches, ignore .claude/ directory | `0.9.0` |
| `cdbba6c` | 2026-03-17T16:49:26+03:00 | fix: restore MainWindow menu in launcher, add --mock flag | `0.9.0` |
| `b6ddb4e` | 2026-03-17T17:03:03+03:00 | feat: dashboard hub — Keithley quick-actions, quick log, experiment status on Overview | `0.9.0` |
| `f910c40` | 2026-03-17T17:14:25+03:00 | feat: structured shift handover — start, periodic prompts, end summary | `0.9.0` |
| `3dea162` | 2026-03-17T17:40:09+03:00 | refactor: two-column Overview layout, move ExperimentWorkspace to separate tab | `0.9.0` |
| `a23ab92` | 2026-03-17T17:53:15+03:00 | fix: Overview — readable time axis, 8-per-row temp cards by instrument, scrollable panel | `0.9.0` |
| `dd663ae` | 2026-03-17T18:15:42+03:00 | fix: Overview layout — full-width temp cards, graph+info splitter | `0.9.0` |
| `a38154a` | 2026-03-17T18:27:37+03:00 | perf: async ZMQ polling in Overview widgets to eliminate UI lag | `0.9.0` |
| `212e299` | 2026-03-17T18:33:38+03:00 | perf: throttle plot updates, optimize pyqtgraph rendering, reduce UI work per reading | `0.9.0` |
| `f4cb917` | 2026-03-17T18:51:26+03:00 | refactor: Overview — cards on top, synced temp+pressure graphs, clickable channel toggle | `0.9.0` |
| `c848393` | 2026-03-17T19:00:51+03:00 | fix: dynamic temp cards, compact experiment form, unified button colors | `0.9.0` |
| `81c5a1d` | 2026-03-17T19:12:17+03:00 | fix: tray icon duplicate, post-P0 audit fixes | `0.9.0` |
| `2136623` | 2026-03-17T19:16:46+03:00 | chore: remove dead PressureStrip class and unused imports | `0.9.0` |
| `81ef8a6` | 2026-03-17T19:42:06+03:00 | feat: continuous SRDG acquisition during calibration experiments | `0.10.0` |
| `e694d2d` | 2026-03-17T19:52:16+03:00 | feat: calibration v2 post-run pipeline — extract, downsample, breakpoints, fit | `0.10.0` |
| `38aca4f` | 2026-03-17T19:57:30+03:00 | feat: calibration v2 GUI — three-mode panel with coverage and auto-fit | `0.10.0` |
| `98a5951` | 2026-03-17T20:11:32+03:00 | chore: calibration v2 cleanup — remove legacy sessions, update docs | `0.10.0` |
| `bc41589` | 2026-03-17T20:36:54+03:00 | fix: UX polish — DateAxisItem on all graphs, Russian labels, layout fixes | `0.11.0` |
| `aad5eab` | 2026-03-17T20:41:48+03:00 | feat: experiment phase tracking — preparation through teardown | `0.11.0` |
| `d8421e6` | 2026-03-17T20:53:12+03:00 | feat: auto-log system events, auto-generate report on finalize | `0.11.0` |
| `7f0e5d1` | 2026-03-17T21:11:40+03:00 | fix: P1 audit — phase widget, empty states, auto-entry styling, DateAxisItem everywhere | `0.11.0` |
| `3b6a175` | 2026-03-17T22:06:49+03:00 | feat: calibration start button, full docs sync to Russian | `0.11.0` |
| `c22eca9` | 2026-03-18T00:10:28+03:00 | release: v0.12.0 — first production release | `0.12.0` |
| `7ee15de` | 2026-03-18T00:52:04+03:00 | feat: web dashboard — read-only monitoring page with auto-refresh | `0.13.0` |
| `e553f11` | 2026-03-18T00:58:19+03:00 | feat: telegram bot v2 — /status, /log, /temps, /phase, escalation chain | `0.13.0` |
| `ae70158` | 2026-03-18T01:00:12+03:00 | feat: pre-flight checklist before experiment start | `0.13.0` |
| `5678d96` | 2026-03-18T01:04:28+03:00 | feat: experiment form auto-fill with history and name suggestion | `0.13.0` |
| `4405348` | 2026-03-18T01:30:25+03:00 | fix: telegram bot polling debug + ensure task started | `0.13.0` |
| `88357b8` | 2026-03-18T02:16:12+03:00 | feat: alarm v2 foundation — RateEstimator and ChannelStateTracker | `0.13.0` |
| `046ab6f` | 2026-03-18T02:22:14+03:00 | feat: alarm v2 evaluator — composite, rate, threshold, stale checks | `0.13.0` |
| `3f86b42` | 2026-03-18T02:26:02+03:00 | feat: alarm v2 providers and config parser | `0.13.0` |
| `8070b2d` | 2026-03-18T02:30:59+03:00 | feat: alarm v2 integration in engine with phase-dependent evaluation | `0.13.0` |
| `ac404db` | 2026-03-18T02:32:02+03:00 | fix: remove undercool_shield false interlock, phase-gate detector_warmup | `0.13.0` |
| `d3b58bd` | 2026-03-18T02:38:33+03:00 | feat: alarm v2 GUI panel and documentation | `0.13.0` |
| `92e1369` | 2026-03-18T10:45:37+03:00 | fix: memory leak — broadcast task explosion, rate estimator trim, history cap | `0.14.0` |
| `e601ca9` | 2026-03-18T10:55:32+03:00 | fix: empty plots after GUI reconnect, experiment status wrong key | `0.14.0` |
| `c7ae2ed` | 2026-03-18T10:59:53+03:00 | feat: tray-only mode for headless engine monitoring | `0.14.0` |
| `d7c843f` | 2026-03-18T17:12:19+03:00 | fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off, alarms, pressure card, docs | `0.15.0` |
| `4f717a5` | 2026-03-18T17:23:52+03:00 | fix: keithley source-off NaN → SQLite NOT NULL crash | `0.15.0` |
| `8605a52` | 2026-03-19T11:14:49+03:00 | fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN? | `0.15.0` |
| `d0c40de` | 2026-03-19T12:19:10+03:00 | fix: thyracont V1 pressure formula, keithley output float parse, pressure exponent format | `0.15.0` |
| `f3e62f5` | 2026-03-19T12:36:06+03:00 | fix: thyracont V1 value is 6 digits (4 mantissa + 2 exponent), formula (ABCD/1000)*10^(EF-20) | `0.15.0` |
| `d94e361` | 2026-03-19T12:41:31+03:00 | fix: VISA bus lock to prevent -420 Query UNTERMINATED race | `0.15.0` |
| `552f679` | 2026-03-19T12:58:57+03:00 | fix: rate check scoped to critical channels only, disconnected sensors excluded | `0.15.0` |
| `94ec2b6` | 2026-03-19T13:15:31+03:00 | refactor: keithley P=const host-side control loop, remove blocking TSP script | `0.15.0` |
| `1b5c099` | 2026-03-19T13:36:07+03:00 | feat: keithley live P_target update + fix stop button | `0.15.0` |
| `5bc640c` | 2026-03-19T14:05:52+03:00 | fix: GPIB bus lock covers open_resource() and close(), not just query/write | `0.16.0` |
| `a0e9678` | 2026-03-19T14:13:43+03:00 | fix: GPIB bus lock covers open_resource + verify query atomically | `0.16.0` |
| `bb59488` | 2026-03-19T14:29:07+03:00 | fix: GPIB open-per-query + IFC bus reset on timeout | `0.16.0` |
| `946b454` | 2026-03-19T14:50:20+03:00 | refactor: GPIB sequential polling — single task per bus, no parallel access | `0.16.0` |
| `fd229e9` | 2026-03-19T14:58:54+03:00 | fix: GPIB clear() before every query + IFC recovery on timeout | `0.16.0` |
| `31c4bae` | 2026-03-19T15:26:17+03:00 | fix: GPIB remove clear() from hot path, add write-delay-read | `0.16.0` |
| `5448f08` | 2026-03-19T16:00:56+03:00 | fix: GPIB KRDG? command + GUI visual fixes + ZMQ crash resilience | `0.16.0` |
| `7efb8b7` | 2026-03-19T16:21:12+03:00 | refactor: GPIB persistent sessions — LabVIEW-style open-once scheme | `0.16.0` |
| `f64d981` | 2026-03-19T16:41:46+03:00 | feat: isolate ZMQ into subprocess — GUI never imports zmq | `0.16.0` |
| `856ad19` | 2026-03-20T13:04:34+03:00 | feat: Keithley safety (slew rate, compliance) + ZMQ subprocess hardening | `0.17.0` |
| `757f59e` | 2026-03-20T13:22:39+03:00 | feat: SensorDiagnosticsEngine — backend + 20 unit tests (Stage 1) | `0.17.0` |
| `6eb8dfe` | 2026-03-20T13:33:19+03:00 | feat: SensorDiagnostics — engine integration + config (Stage 2) | `0.17.0` |
| `b21bca1` | 2026-03-20T13:45:37+03:00 | feat: SensorDiagnostics GUI panel + status bar summary (Stage 3) | `0.17.0` |
| `5d7fe2b` | 2026-03-20T13:56:47+03:00 | feat: VacuumTrendPredictor — backend + 20 unit tests (Stage 1) | `0.17.0` |
| `c1b9eb5` | 2026-03-20T14:30:15+03:00 | feat: VacuumTrendPredictor — engine integration + config (Stage 2) | `0.17.0` |
| `50e30e3` | 2026-03-20T14:39:47+03:00 | feat: VacuumTrendPredictor GUI panel on Analytics tab (Stage 3) | `0.17.0` |
| `afabfe5` | 2026-03-20T16:03:45+03:00 | fix: ZMQ datetime serialization + REP socket stuck on serialization error | `0.17.0` |
| `6ef43df` | 2026-03-20T20:12:35+03:00 | feat: Phase 2 safety hardening — tests + bugfixes + LakeShore RDGST? | `0.17.0` |
| `bbb5809` | 2026-03-20T20:42:47+03:00 | feat: Phase 3 — safety correctness, reliability, phase detector | `0.17.0` |
| `4b52de8` | 2026-03-20T21:16:28+03:00 | fix: deep review — 2 bugs fixed, 2 tests added | `0.17.0` |
| `10d4d76` | 2026-03-20T22:39:17+03:00 | fix(audit): 6 bugs — safety race, SQLite shutdown, Inf filter, phase reset, GPIB leak, deque cap | `0.17.0` |
| `af94285` | 2026-03-21T00:39:25+03:00 | fix(ui): CSV BOM, sensor diag stretch, calibration stretch, reports on, adaptive liveness | `0.17.0` |
| `1ec93a6` | 2026-03-21T02:39:16+03:00 | merge: feature/ui-refactor | `0.18.0` |
| `c427247` | 2026-03-21T02:54:30+03:00 | docs: update all documentation, changelog, and version for v0.13.0 | `0.18.0` |
| `a2f4bcd` | 2026-03-21T12:01:31+03:00 | fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect | `0.18.0` |
| `1670bbe` | 2026-03-21T12:01:44+03:00 | fix(ui): card toggle signals, history load on window change, axis alignment, channel refresh | `0.18.0` |
| `2ab7283` | 2026-03-21T12:01:52+03:00 | chore: fix default channels, web version, deprecate autosweep_panel | `0.18.0` |
| `dc84f0c` | 2026-03-21T12:35:27+03:00 | fix(ui): remove QuickStart buttons from overview (caused FAULT with P=0) | `0.18.0` |
| `1dd7405` | 2026-03-21T12:35:37+03:00 | feat(ui): rename Keithley tab, add time window buttons, forecast zone | `0.18.0` |
| `f08e6bb` | 2026-03-21T12:35:47+03:00 | fix: audit wave 3 — build_ensemble guard, launcher ping, phase gap, RDGST, docs | `0.18.0` |
| `9e2ce5b` | 2026-03-21T15:20:53+03:00 | merge: final-batch — single-instance, ML forecast, flight recorder, driver fixes | `0.19.0` |
| `7618031` | 2026-03-21T16:01:14+03:00 | fix(telegram): natural channel sort, compact text, pressure log-scale Y limits | `0.19.0` |
| `4df40c3` | 2026-03-21T16:15:04+03:00 | fix(critical): atomic single-instance lock via O_CREAT|O_EXCL | `0.19.0` |
| `0603110` | 2026-03-21T16:15:13+03:00 | fix(zmq): correlation ID for command-reply routing | `0.19.0` |
| `9942da1` | 2026-03-21T16:15:23+03:00 | fix(ui): proportional history load, overview plot sync, CSV BOM | `0.19.0` |
| `6d39a08` | 2026-03-21T17:34:43+03:00 | fix(critical): move experiment I/O to thread, remove double report generation | `0.19.0` |
| `45ae750` | 2026-03-21T17:39:02+03:00 | fix(zmq): Future-per-request dispatcher with dedicated reply consumer | `0.19.0` |
| `031491a` | 2026-03-21T17:42:38+03:00 | fix(ui): "Всё"→"Сутки", pass channels to history, poll_readings resilience | `0.19.0` |
| `dd42632` | 2026-03-22T00:25:10+03:00 | fix(ui): snap graph X-axis to data start across all 7 panels | `0.19.0` |
| `0fdc507` | 2026-03-22T16:11:11+03:00 | merge: audit-v2 fixes (29 defects, 9 commits) | `0.20.0` |
| `fc1c61b` | 2026-03-22T16:35:11+03:00 | feat(storage): Parquet experiment archive — write readings.parquet alongside CSV on finalize | `0.20.0` |
| `ccf98c9` | 2026-03-22T16:44:11+03:00 | Add CI workflow for CryoDAQ with testing and linting | `0.20.0` |
| `f0c68c6` | 2026-03-22T17:28:38+03:00 | feat(archive): Parquet column in table, human-readable artifacts, parquet read fix | `0.20.0` |
| `423c6d5` | 2026-03-22T19:05:13+03:00 | fix(archive): inclusive end-date filter, add end time column | `0.20.0` |
| `8dc07f7` | 2026-03-22T19:18:57+03:00 | feat(reporting): professional human-readable reports for all experiment types | `0.20.0` |
| `a066cd7` | 2026-03-22T20:51:11+03:00 | feat(reporting): ГОСТ Р 2.105-2019 formatting, all graphs in all reports | `0.20.0` |
| `b7265bb` | 2026-03-22T21:23:13+03:00 | fix(reporting): multi-channel graphs, black headings, smart page breaks | `0.20.0` |
| `29d2215` | 2026-03-23T00:37:57+03:00 | fix: audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring | `0.20.0` |
| `ab57e01` | 2026-03-23T14:59:57+03:00 | fix(gpib): auto-recovery from hung instruments — clear bus on timeout, preventive clear | `0.21.0` |
| `ea5a8da` | 2026-03-23T15:15:20+03:00 | fix(gpib): IFC bus reset, enable unaddressing, escalating recovery | `0.21.0` |
| `86e8e8c` | 2026-03-23T15:32:17+03:00 | fix(preflight): sensor health is warning not error | `0.21.0` |
| `c10e617` | 2026-03-24T12:50:45+03:00 | fix(scheduler): standalone instrument disconnect+reconnect on consecutive errors | `0.21.0` |
| `dfd6021` | 2026-03-24T12:55:26+03:00 | fix(preflight): restore encoding + sensor health warning not error | `0.21.0` |
| `8bac038` | 2026-03-24T13:10:40+03:00 | fix(gui): non-blocking alarm v2 status poll | `0.21.0` |
| `6d0f5ba` | 2026-03-24T14:08:20+03:00 | fix(gui): bridge heartbeat false kills + launcher blocking send_command | `0.21.0` |
| `bab4d8a` | 2026-03-24T14:15:39+03:00 | feat: single-instance protection for launcher and standalone GUI | `0.21.0` |
| `4eb5f1a` | 2026-03-24T14:27:27+03:00 | fix(gui): launcher bridge health gap + conductivity blocking send_command | `0.21.0` |
| `3c46dfb` | 2026-03-24T14:41:09+03:00 | fix(gui): keithley spinbox debounce + non-blocking live update | `0.21.0` |
| `e7d4fc5` | 2026-03-24T14:48:54+03:00 | fix(gui): experiment workspace 1080p layout — phase bar + passport forms | `0.21.0` |
| `f47762d` | 2026-03-24T15:02:22+03:00 | fix: launcher non-blocking engine restart + deployment hardening | `0.21.0` |
| `f217427` | 2026-03-25T12:59:26+03:00 | fix: shift modal re-entrancy + engine --force PermissionError | `0.21.0` |
| `9676165` | 2026-03-31T03:17:03+03:00 | fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking | `0.22.0` |
| `9feaf3e` | 2026-04-01T03:57:02+03:00 | fix: audit - GUI non-blocking send_command + dead code cleanup | `0.22.0` |
| `a60abc0` | 2026-04-08T16:58:28+03:00 | fix: Phase 1 pre-deployment — unblock PyInstaller build | `0.22.0` |
| `0333e52` | 2026-04-08T17:47:20+03:00 | fix: Phase 2a safety hardening — close 4 HIGH findings | `0.22.0` |
| `8a24ead` | 2026-04-08T21:17:52+03:00 | fix: Phase 2b observability & resilience — close 8 MEDIUM findings | `0.22.0` |
| `b185fd3` | 2026-04-08T21:58:00+03:00 | fix: Phase 2c final hardening — close 8 findings before Phase 3 | `0.22.0` |
| `1698150` | 2026-04-08T22:16:31+03:00 | ui: replace Overview "Сутки" preset with "Всё" | `0.22.0` |
| `380df96` | 2026-04-09T00:45:35+03:00 | audit: deep audit pass (CC) post-2c | `0.23.0` |
| `fd99631` | 2026-04-09T00:59:45+03:00 | audit: deep audit pass (Codex overnight) post-2c | `0.23.0` |
| `fd8c8bf` | 2026-04-09T02:23:44+03:00 | chore: gitignore local audit artifacts (DEEP_AUDIT_*.md, graphify-out/) | `0.23.0` |
| `847095c` | 2026-04-09T02:39:32+03:00 | audit: cherry-pick hardening pass document from feat/ui-phase-1 | `0.23.0` |
| `5d618db` | 2026-04-09T02:58:53+03:00 | audit: verification pass - re-check 5 HIGH findings from hardening pass | `0.23.0` |
| `10667df` | 2026-04-09T03:07:45+03:00 | audit: SafetyManager exhaustive FSM analysis | `0.23.0` |
| `31dbbe8` | 2026-04-09T03:14:45+03:00 | audit: persistence-first invariant exhaustive trace | `0.23.0` |
| `3e20e86` | 2026-04-09T03:26:43+03:00 | audit: driver layer fault injection scenarios | `0.23.0` |
| `916fae4` | 2026-04-09T03:54:17+03:00 | audit: full dependency CVE sweep with version verification | `0.23.0` |
| `a108519` | 2026-04-09T04:01:17+03:00 | audit: reporting + analytics + plugins deep dive | `0.23.0` |
| `24b928d` | 2026-04-09T04:09:48+03:00 | audit: configuration files security and consistency audit | `0.23.0` |
| `7aaeb2b` | 2026-04-09T04:20:34+03:00 | audit: master triage synthesis of all audit documents | `0.23.0` |
| `995f7bc` | 2026-04-12T23:25:19+03:00 | discovery: build doc-vs-code reality map (CC + Codex review) | `0.23.0` |
| `6eb7d3e` | 2026-04-13T01:04:14+03:00 | docs: rewrite cryodaq-team-lead skill against current code reality | `0.23.0` |
| `ddf6459` | 2026-04-13T16:01:32+03:00 | docs(CLAUDE.md): add missing config files to list | `0.23.0` |
| `1d71ecc` | 2026-04-13T16:09:28+03:00 | docs(CLAUDE.md): expand module index, fix safety FSM and invariants | `0.23.0` |
| `88feee5` | 2026-04-13T16:27:03+03:00 | phase-2d-a1: web XSS + SafetyManager hardening + T regression | `0.24.0` |
| `1446f48` | 2026-04-13T17:18:12+03:00 | phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class | `0.24.0` |
| `ebac719` | 2026-04-13T17:44:12+03:00 | phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError | `0.24.0` |
| `1b12b87` | 2026-04-13T18:07:45+03:00 | phase-2d-a2: alarm config hardening + safety->experiment bridge | `0.24.0` |
| `e068cbf` | 2026-04-13T20:53:40+03:00 | phase-2d-a2-fix: close Codex findings on 1b12b87 | `0.24.0` |
| `d3abee7` | 2026-04-13T21:50:34+03:00 | phase-2d-b1: atomic file writes + WAL verification | `0.24.0` |
| `5cf369e` | 2026-04-13T22:08:49+03:00 | phase-2d-a8-followup: shield post-fault cancellation paths | `0.24.0` |
| `104a268` | 2026-04-13T22:30:24+03:00 | phase-2d-b2: persistence integrity | `0.24.0` |
| `21e9c40` | 2026-04-13T22:46:17+03:00 | phase-2d-b2-fix: drop NaN-valued statuses from persist set | `0.24.0` |
| `23929ca` | 2026-04-13T23:22:40+03:00 | phase-2d: checkpoint — Block A+B complete, update PROJECT_STATUS | `0.24.0` |
| `efe6b49` | 2026-04-14T01:14:35+03:00 | chore: ruff --fix accumulated lint debt | `0.25.0-pre` |
| `f4c256f` | 2026-04-14T01:14:55+03:00 | chore: remove accidentally committed logs/, add to .gitignore | `0.25.0-pre` |
| `74f6d21` | 2026-04-14T01:44:41+03:00 | phase-2d-jules-r2-fix: close ordering and state mutation gaps | `0.25.0-pre` |
| `89ed3c1` | 2026-04-14T02:18:37+03:00 | phase-2d-c1: config fail-closed completion + cleanup | `0.25.0-pre` |
| `0cd8a94` | 2026-04-14T02:36:54+03:00 | phase-2d: declare COMPLETE, open Phase 2e | `0.25.0-pre` |
| `445c056` | 2026-04-14T02:55:31+03:00 | phase-2e-parquet-1: experiment archive via Parquet at finalize | `0.25.0-pre` |
| `855870b` | 2026-04-14T03:26:45+03:00 | docs(audits): add BRANCH_INVENTORY.md for three-track review input | `0.25.0-pre` |
| `5ad0156` | 2026-04-14T03:31:22+03:00 | docs(audits): add repo inventory, dead code scan, and CC findings summary | `0.25.0-pre` |
| `1c75967` | 2026-04-14T03:54:44+03:00 | docs/audits: Codex round 2 extended semantic audit | `0.25.0-pre` |
| `66f9870` | 2026-04-14T03:56:15+03:00 | docs/audits: CC round 2 extended inventory | `0.25.0-pre` |
| `6535c9a` | 2026-04-14T04:15:41+03:00 | docs/audits: record remote branch cleanup | `0.25.0-pre` |
| `88c308c` | 2026-04-14T04:19:11+03:00 | docs: update PROJECT_STATUS.md numbers for round 2 audit state | `0.25.0-pre` |
| `5b3ca29` | 2026-04-14T04:19:26+03:00 | chore: commit historical pre-Phase-2c audit artifacts | `0.25.0-pre` |

---

## Confidence ratings

- **Commit coverage:** HIGH — all 205 first-parent commits were assigned to a version and checked at least at subject/stat level, with fuller reading on the major pivots.
- **Clustering accuracy:** MEDIUM — the clusters are coherent and evidence-based, but some “upload snapshot” commits still require contextual inference.
- **Version boundary proposal:** MEDIUM — 25 versions feels materially better than 10, but a human could reasonably choose something like 20 or 22 instead.
- **Version count calibration:** MEDIUM — the 20-25 target fits the history well, but the exact number is interpretive rather than objective.
- **Version name choices:** MEDIUM — the names are intentionally more specific than v1, but some could be simplified further in the final human-written changelog.
- **Boundary placement:** MEDIUM — the largest boundaries are strong; a few small ones (`0.8.0`, `0.14.0`) could plausibly be absorbed by neighbors if the final changelog wants fewer releases.
- **Context explanations:** HIGH — the why/how narratives are grounded in actual commit sequences and in the v1/archaeology context.
- **Breaking change detection:** MEDIUM — the major breaking shifts are captured, but some semantic behavior changes may still be better expressed as “Changed” rather than “Breaking” in the final changelog.

---

## Differences from v1

### Version count

- v1: 10 versions
- v2: 25 versions

### What split from v1

- v1 `0.1.0 Foundation` split into:
  - `0.1.0 Initial Scaffolding`
  - `0.2.0 Instrument Foundations`
  - `0.3.0 Workflow Skeleton`
  - `0.4.0 Operator Shell Completion`
  - `0.5.0 Safety Architecture`
  - `0.6.0 Cooldown and Overview Intelligence`
  - `0.7.0 Deployment Fix Waves`

- v1 `0.3.0 RC Convergence` split into:
  - `0.8.0 RC Merge`
  - `0.9.0 Dashboard Hub and Shift Workflow`
  - `0.10.0 Calibration V2`
  - `0.11.0 Phased Experiments and Auto Reports`

- v1 `0.12.1 Operational Surface Expansion` split into:
  - `0.13.0 Remote Ops and Alarm V2`
  - `0.14.0 Post-Release Stabilization`
  - `0.15.0 First Hardware Deployment`
  - `0.16.0 GPIB Stabilization and ZMQ Isolation`

- v1 `0.12.2 Analytics and Safety Expansion` split into:
  - `0.17.0 Diagnostics and Safety Expansion`
  - `0.18.0 UI Refactor Merge and Post-Merge Cleanup`

- v1 `0.12.3 Integration Batch and Audit Merge` split into:
  - `0.19.0 Final-Batch Integration`
  - `0.20.0 Audit-v2, Parquet v1, and Reporting`

- v1 `0.12.4 Deployment Hardening` split into:
  - `0.21.0 Recovery and Deployment Hardening`
  - `0.22.0 Pre-Phase-2d Hardening Prep`

- v1 `0.12.5 Audit Discovery and Pre-2d Hardening` split into:
  - `0.23.0 Audit Corpus and Reality Map`

- v1 `0.13.0 Structured Hardening and Archive` split into:
  - `0.24.0 Phase 2d Safety and Persistence`
  - `0.25.0-pre Current Hardening Line`

### What stayed roughly the same

- the RC merge at `dc2ea6a` still remains a major historical pivot
- the first release cut at `c22eca9` still remains a natural boundary even without tag-anchor bias
- GPIB stabilization still reads as a concentrated marathon rather than scattered bugfixes
- the audit corpus still deserves its own historical chapter rather than being hidden inside ordinary feature versions

### Version naming style change

v1 used broader labels such as “Operational Surface Expansion” and “Structured Hardening and Archive”. v2 uses narrower names like “Remote Ops and Alarm V2”, “GPIB Stabilization and ZMQ Isolation”, and “Audit Corpus and Reality Map”. This is deliberate: each name now tries to answer “what one release note would this version actually be about?” instead of “what broad era was the project in?”

### Rationale for v2 approach

v1 was valuable because it proved the history could be reconstructed semantically at all. It gave good cluster prose and a readable long-form narrative. But it was still too coarse for direct changelog assembly. Several v1 versions were really bundles of two or three distinct release-worthy efforts, which would force a human writer either to over-compress the final changelog or to re-split the history manually anyway.

v2 is better suited for the actual assembly step because it does that re-splitting upfront. The final writer can now decide to collapse neighboring versions if needed, but they do not need to rediscover boundaries from scratch. That makes v2 the better source document even though v1 remains useful as a reference narrative.
