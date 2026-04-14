# CryoDAQ — Retroactive Changelog Research v3

**Generated:** 2026-04-14  
**Commits covered:** 205 first-parent commits on `master` (235 total reachable commits at generation time)  
**Source data:** `git log --first-parent`, per-commit `git show --stat`, selected full commit messages/diffs, `docs/changelog/RETRO_ANALYSIS.md`, `docs/changelog/RETRO_ANALYSIS_V2.md`, `docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`, `docs/audits/BRANCH_INVENTORY.md`, `docs/audits/BRANCH_INTEGRATION_VERIFICATION.md`  
**Purpose:** source material for a rebuilt `CHANGELOG.md`. This is **not** the final changelog.  
**Count policy:** uncapped. This pass intentionally removed any target number of versions and let the history determine the boundary count.

---

## How to use this document

This is the third-pass research document for rebuilding the changelog. It supersedes both `docs/changelog/RETRO_ANALYSIS.md` and `docs/changelog/RETRO_ANALYSIS_V2.md` as the primary source material, but it does so narrowly: the main change is boundary honesty. v1 was too coarse because it treated the old `v0.12.0` tag as an anchor. v2 removed the anchor but still worked under an explicit 20-25 version target. v3 removes that target completely.

This is still a research artifact, not a polished changelog. It intentionally preserves context a final `CHANGELOG.md` would compress away: merge commits as historical events, upload/task snapshots, audit-document waves, reality-map work, and release arcs that make sense only when seen in sequence. The later human-written changelog should distill from this file, not copy it verbatim.

The practical value of v3 is auditability of the version scheme itself. Every proposed version now has an explicit `v2 origin` in the top proposal table so a human can see whether a boundary was kept, split, or merged. That makes the split decisions reviewable instead of implicit.

The future maintainer use-case stays the same: if someone asks when the project first became lab-usable, when alarm v2 truly landed, why `instrument_id` became mandatory, when GPIB stabilization stopped being ad hoc, or when audit work became a first-class part of the repository history, this document should answer that without another full walk through 205 commits.

---

## Methodology

I started from v2’s 25-version scheme and re-examined every version with one question: “does this still read as one coherent release effort if there is no target count pressure at all?” The allowed outcomes were only three: keep the v2 boundary, split it, or in rare cases merge it with a neighbor. In practice this pass found only keep-or-split decisions; nothing in v2 looked over-split enough to justify merging.

The anti-bias guardrails were explicit: no target count, no upper bound, no symmetry enforcement, and no pressure to keep the v2 number of 25. A one-commit version remained acceptable if it was historically pivotal (`dc2ea6a`, `c22eca9`). A 9-10 commit version remained acceptable if it was a tight marathon (`0.20.0`, `0.31.0`). The only thing that justified a split was a real change in work direction or release narrative.

Where v2 was already correctly chunked, I preserved its meaning and most of its prose. Where a v2 version needed splitting, I redistributed the same historical content across child versions rather than inventing new stories. The point of v3 is not to rewrite history again; it is to remove the last visible boundary bias from v2.

Known limitations remain the same as v2: this is still a first-parent narrative rather than a full branch archaeology of every side-branch commit, and some `Add files via upload` commits still require contextual inference from neighboring commits and file stats. But the boundary decisions themselves are mechanically checked against the full 205-commit first-parent chain, with no missing or overlapping assignments.

---

## Version boundary proposal

I still recommend a pure minor-version ladder with no patch releases and no `1.0.0`: `0.1.0`, `0.2.0`, ..., `0.33.0-pre`. The repository did not evolve as a stable base plus tiny patches. It evolved as intense, directionally coherent waves of work. Minor-version-only retro numbering matches that reality better than pretending there was disciplined patch semantics from the start.

### Honest count statement

This v3 reconstruction proposes **33** versions. The v3 prompt explicitly removed any target count, so `33` is simply where the natural boundaries landed after re-examining every v2 version independently. I did not aim for 25, for 30, or for any other number.

The count is higher than v2’s 25 for one reason: several v2 versions still contained two clean release stories. The strongest examples were `v2 0.4.0`, `v2 0.7.0`, `v2 0.9.0`, `v2 0.13.0`, `v2 0.17.0`, `v2 0.21.0`, `v2 0.23.0`, and `v2 0.25.0`. Once those were split honestly, the history naturally settled at 33. That is slightly above the range the prompt informally guessed, but it is the count the history supports.

| Version | Name | Date range | Commit count | First commit | Last commit | Rationale | v2 origin |
|---|---|---|---|---|---|---|---|
| `0.1.0` | Initial Scaffolding | 2026-03-14 00:29..2026-03-14 00:39 | 4 | `be52137` | `2882845` | Minimum coherent project-exists cut: rules, package skeleton, scheduler, SQLite writer, and first IPC path. | v2 0.1.0 (kept) |
| `0.2.0` | Instrument Foundations | 2026-03-14 00:43..2026-03-14 01:23 | 4 | `0c54010` | `75ebdc1` | Pivots from generic scaffold to real hardware and first alarm/analytics abstractions. | v2 0.2.0 (kept) |
| `0.3.0` | Workflow Skeleton | 2026-03-14 01:25..2026-03-14 01:59 | 4 | `e64b516` | `e4bbcb6` | Binds drivers into workflows via engine/GUI entry points, experiments, notifications, and web shell. | v2 0.3.0 (kept) |
| `0.4.0` | Third Instrument and Test Base | 2026-03-14 02:12..2026-03-14 03:27 | 9 | `33e51f3` | `da825f1` | Completes the third instrument, test floor, Russian docs, and live-tab baseline before the launcher/measurement push. | v2 0.4.0 split 1/2 |
| `0.5.0` | Launcher and Measurement Extensions | 2026-03-14 03:40..2026-03-14 05:02 | 5 | `77638b0` | `b2b4d97` | Groups the operator launcher, dual-channel/runtime extensions, conductivity workflow, predictor, and channel/connection management. | v2 0.4.0 split 2/2 |
| `0.6.0` | Safety Architecture | 2026-03-14 13:29..2026-03-14 18:18 | 8 | `603a472` | `a8e8bbf` | First governing safety pivot: SafetyManager, SafetyBroker, fail-on-silence, persistence-first. | v2 0.5.0 (kept) |
| `0.7.0` | Cooldown and Overview Intelligence | 2026-03-14 18:49..2026-03-14 22:53 | 7 | `9217489` | `9390419` | Moves from control to observability and prediction via cooldown, overview, export, and disk awareness. | v2 0.6.0 (kept) |
| `0.8.0` | Audit Safety Fixes | 2026-03-14 23:17..2026-03-15 02:44 | 4 | `e9a538f` | `0f8dd59` | First audit/P0 safety correction wave; still one story centered on immediate hazard closure. | v2 0.7.0 split 1/2 |
| `0.9.0` | Deployment Contracts and Instrument Identity | 2026-03-15 03:02..2026-03-15 18:02 | 6 | `de715dc` | `0078d57` | Separates P1 deployment fixes and the instrument_id data-model contract from the earlier emergency safety patch set. | v2 0.7.0 split 2/2 |
| `0.10.0` | RC Merge | 2026-03-17 15:33..2026-03-17 15:33 | 1 | `dc2ea6a` | `dc2ea6a` | The RC merge is itself the historical unit; later post-RC work depends on it. | v2 0.8.0 (kept) |
| `0.11.0` | Dashboard Hub and Shift Workflow | 2026-03-17 16:00..2026-03-17 17:14 | 4 | `29652a2` | `f910c40` | A compact release centered on dashboard-hub and structured shift workflow rather than later rendering refinements. | v2 0.9.0 split 1/2 |
| `0.12.0` | Overview Performance Refinement | 2026-03-17 17:40..2026-03-17 19:16 | 9 | `3dea162` | `2136623` | Captures the follow-on overview layout/performance iteration as a separate UX/perf release. | v2 0.9.0 split 2/2 |
| `0.13.0` | Calibration V2 | 2026-03-17 19:42..2026-03-17 20:11 | 4 | `81ef8a6` | `98a5951` | Calibration v2 is a tight backend→pipeline→GUI rollout and stands cleanly on its own. | v2 0.10.0 (kept) |
| `0.14.0` | Phased Experiments and Auto Reports | 2026-03-17 20:36..2026-03-17 22:06 | 5 | `bc41589` | `3b6a175` | Formalizes experiment phases, auto-logging, and auto-report generation. | v2 0.11.0 (kept) |
| `0.15.0` | First Lab-Usable Release | 2026-03-18 00:10..2026-03-18 00:10 | 1 | `c22eca9` | `c22eca9` | Explicit first lab-usable release cut; still the clearest single release boundary in history. | v2 0.12.0 (kept) |
| `0.16.0` | Remote Ops and Preflight | 2026-03-18 00:52..2026-03-18 01:30 | 5 | `7ee15de` | `4405348` | Remote monitoring, Telegram v2, and pre-flight workflow form one operator-surface expansion before the alarm rewrite. | v2 0.13.0 split 1/2 |
| `0.17.0` | Alarm V2 Rollout | 2026-03-18 02:16..2026-03-18 02:38 | 6 | `88357b8` | `d3b58bd` | Alarm v2 backend, integration, and GUI rollout are coherent enough to be isolated as their own release. | v2 0.13.0 split 2/2 |
| `0.18.0` | Post-Release Stabilization | 2026-03-18 10:45..2026-03-18 10:59 | 3 | `92e1369` | `c7ae2ed` | Immediate leak/reconnect stabilization plus tray-only mode form a compact post-release repair release. | v2 0.14.0 (kept) |
| `0.19.0` | First Hardware Deployment | 2026-03-18 17:12..2026-03-19 13:36 | 9 | `d7c843f` | `1b5c099` | Real hardware forces protocol, parsing, and control-loop corrections across the physical instrument stack. | v2 0.15.0 (kept) |
| `0.20.0` | GPIB Stabilization and ZMQ Isolation | 2026-03-19 14:05..2026-03-19 16:41 | 9 | `5bc640c` | `f64d981` | One sustained transport reliability marathon ending in ZMQ subprocess isolation. | v2 0.16.0 (kept) |
| `0.21.0` | Analytics Expansion and Keithley Safety | 2026-03-20 13:04..2026-03-20 14:39 | 7 | `856ad19` | `50e30e3` | Sensor diagnostics, vacuum trend, and Keithley safety expansion read as one analytics/safety growth release. | v2 0.17.0 split 1/2 |
| `0.22.0` | Safety Deepening and Review Fixes | 2026-03-20 16:03..2026-03-21 00:39 | 6 | `afabfe5` | `af94285` | Late-day safety phases, review fixes, and adaptive-liveness fallout form a second, distinct safety-hardening release. | v2 0.17.0 split 2/2 |
| `0.23.0` | UI Refactor Merge and Post-Merge Cleanup | 2026-03-21 02:39..2026-03-21 12:35 | 8 | `1ec93a6` | `f08e6bb` | UI refactor merge plus immediate fallout remain one merge-and-stabilize story. | v2 0.18.0 (kept) |
| `0.24.0` | Final-Batch Integration | 2026-03-21 15:20..2026-03-22 00:25 | 9 | `9e2ce5b` | `dd42632` | Final-batch merge and its critical runtime consequences are still one integration release. | v2 0.19.0 (kept) |
| `0.25.0` | Audit-v2, Parquet v1, and Reporting | 2026-03-22 16:11..2026-03-23 00:37 | 9 | `0fdc507` | `29d2215` | Audit-v2 merge, Parquet v1, CI, and professional reporting all support the same operational-credibility push. | v2 0.20.0 (kept) |
| `0.26.0` | GPIB Recovery and Preflight Tuning | 2026-03-23 14:59..2026-03-24 12:55 | 5 | `ab57e01` | `dfd6021` | Separates GPIB recovery escalation and preflight tuning from later GUI/launcher non-blocking work. | v2 0.21.0 split 1/2 |
| `0.27.0` | Non-Blocking GUI and Singleton Hardening | 2026-03-24 13:10..2026-03-25 12:59 | 8 | `8bac038` | `f217427` | Non-blocking GUI/launcher fixes and singleton enforcement form their own deployment-UX hardening release. | v2 0.21.0 split 2/2 |
| `0.28.0` | Pre-Phase-2d Hardening Prep | 2026-03-31 03:17..2026-04-08 22:16 | 7 | `9676165` | `1698150` | Explicit staging area before structured Phase 2d work. | v2 0.22.0 (kept) |
| `0.29.0` | Audit Corpus | 2026-04-09 00:45..2026-04-09 04:20 | 12 | `380df96` | `7aaeb2b` | The main audit corpus and synthesis deserve their own version before docs/reality reconciliation. | v2 0.23.0 split 1/2 |
| `0.30.0` | Reality Map and Documentation Reconciliation | 2026-04-12 23:25..2026-04-13 16:09 | 4 | `995f7bc` | `1d71ecc` | Reality-map and documentation reconciliation are discrete governance work, not just part of the audit dump. | v2 0.23.0 split 2/2 |
| `0.31.0` | Phase 2d Safety and Persistence | 2026-04-13 16:27..2026-04-13 23:22 | 10 | `88feee5` | `23929ca` | Phase 2d A+B land as one structured hardening release with a single checkpoint. | v2 0.24.0 (kept) |
| `0.32.0` | Phase 2d Closure and Fail-Closed Completion | 2026-04-14 01:14..2026-04-14 02:36 | 5 | `efe6b49` | `0cd8a94` | Late 2d closure: lint/log cleanup, Jules R2 fix, config fail-closed completion, and 2d completion declaration. | v2 0.25.0 split 1/2 |
| `0.33.0-pre` | Phase 2e Archive Kickoff and Round-2 Audit Context | 2026-04-14 02:55..2026-04-14 04:19 | 8 | `445c056` | `5b3ca29` | Phase 2e Parquet kickoff plus round-2 audit context define the current unreleased line. | v2 0.25.0 split 2/2 |

### Scheme rationale

The biggest structural lesson from v3 is that CryoDAQ’s history is more chapter-like than v2 admitted. The project did not just have “foundation”, “post-release expansion”, “deployment hardening”, and “Phase 2d”. Inside those broad eras there are repeatable release-shaped movements: complete the third instrument and test base, then add launcher and measurement extensions; add remote ops and preflight, then rewrite the alarm engine; roll out analytics, then harden safety around them; generate the audit corpus, then reconcile docs against it; close Phase 2d, then open Phase 2e.

Staying in `0.x` is still the honest choice. The project is unusually capable for its age, but the audit history is recent, a GUI merge is still pending on a side branch, and the repository itself documents ongoing Tier 1 work. Retroactive `1.0.0` would overstate stability rather than clarify history.

---
## Version 0.1.0 — Initial Scaffolding

### Boundary decision

**v2 origin:** v2 0.1.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This remains the minimum coherent project-exists cut: constraints, package scaffold, broker, scheduler, storage, and IPC all appear here and belong together.

### Date range

2026-03-14 00:29..2026-03-14 00:39

### Commit range

`be52137`..`2882845`

### Themes in this version

- repository and rules scaffold
- first driver/data abstractions
- first persistence and polling pipeline

### Cluster 0.1.0.1 — Initial Scaffolding

**Commits:** `be52137`, `dea213f`, `f7cdc00`, `2882845`  
**Goal:** Create the package, architecture contract, and first end-to-end technical skeleton.  
**Approach:** Start with explicit project rules, then add the base source tree and immediately wire persistence, scheduling, and ZMQ so later work grows on a real data path instead of stubs.

**What changed:**
- Added the architecture/constraints baseline in `CLAUDE.md`.
- Added the Python package scaffold, driver ABC, and `DataBroker`.
- Added `SQLiteWriter`, scheduler, and ZMQ bridge so the scaffold became operational.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
None yet. This is infrastructure only.

**Config file changes:**
`pyproject.toml` and the first config-bearing structure arrived here.

**API / contract changes:**
First `Reading`/driver/scheduler/broker contracts were born here.

**Internal / architectural changes:**
The core architectural triangle of CryoDAQ is already visible: poll hardware, persist locally, broadcast to clients.

**Why the order:**
Breadth first was rational. Without scheduler, persistence, and IPC, nothing else would have real integration meaning.

**Commit explanations (one line each):**
- `be52137`: Add CLAUDE.md with project architecture and constraints
- `dea213f`: Add cryodaq-team-lead skill for agent team orchestration
- `f7cdc00`: Add project foundation: pyproject.toml, directory structure, driver ABC, DataBroker
- `2882845`: Add SQLiteWriter, ZMQ bridge, and instrument Scheduler

---

## Version 0.2.0 — Instrument Foundations

### Boundary decision

**v2 origin:** v2 0.2.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

The direction changes from generic scaffold to real lab hardware and first domain-specific analytics/alarm abstractions.

### Date range

2026-03-14 00:43..2026-03-14 01:23

### Commit range

`0c54010`..`75ebdc1`

### Themes in this version

- first real LakeShore driver and GUI
- first Keithley constant-power path
- first alarm/analytics plugin abstractions

### Cluster 0.2.0.1 — Instrument Foundations

**Commits:** `0c54010`, `577b02f`, `258f643`, `75ebdc1`  
**Goal:** Move from generic framework to CryoDAQ-specific hardware control.  
**Approach:** Implement the temperature controller first, then the power source, then define the first analytics/alarm path around them.

**What changed:**
- Added the LakeShore 218S driver, temperature panel, and tests.
- Added the Keithley TSP constant-power driver and first interlock ideas.
- Added the first alarm engine and analytics plugin pipeline.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
The first live temperature UI and first visible Keithley integration appeared here.

**Config file changes:**
Initial instrument/alarm-related configuration expectations became real.

**API / contract changes:**
Drivers stopped being abstract placeholders and became concrete instrument contracts.

**Internal / architectural changes:**
The plugin idea arrives very early, which matters later when analytics and alarms become much richer.

**Why the order:**
Once scaffolding existed, the fastest path to value was to stand up the two most important hardware classes.

**Commit explanations (one line each):**
- `0c54010`: Add LakeShore 218S driver, temperature panel GUI, and tests
- `577b02f`: Keithley 2604B: TSP P=const, driver, interlocks
- `258f643`: Update CLAUDE.md with build commands, data flow, and module index
- `75ebdc1`: Add AlarmEngine, analytics plugin pipeline, and two plugins

---

## Version 0.3.0 — Workflow Skeleton

### Boundary decision

**v2 origin:** v2 0.3.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

CryoDAQ becomes more than drivers plus scheduler: engine/GUI entry points, experiments, notifications, and web monitoring turn the stack into an operator workflow shell.

### Date range

2026-03-14 01:25..2026-03-14 01:59

### Commit range

`e64b516`..`e4bbcb6`

### Themes in this version

- engine/GUI pairing
- experiment lifecycle and export
- notifications and web surface

### Cluster 0.3.0.1 — Workflow Skeleton

**Commits:** `e64b516`, `0b79fa1`, `baaec03`, `e4bbcb6`  
**Goal:** Define how operators actually use the system end to end.  
**Approach:** Bind engine and GUI together, add experiments and export, then add operator-facing remote surfaces.

**What changed:**
- Added engine and GUI entry points plus the main window shell.
- Added experiment lifecycle, replay/export, and Telegram notifications.
- Added the web dashboard and first calibration placeholder.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
This is the first version where an operator can plausibly imagine running a session through the software.

**Config file changes:**
Notification and web-facing settings became relevant for real use.

**API / contract changes:**
Experiment subsystem and remote-surface contracts are born here.

**Internal / architectural changes:**
The later “engine as source of truth, GUI/web/Telegram as clients” pattern is already visible.

**Why the order:**
Hardware and storage were already present; the next limiting factor was operator workflow.

**Commit explanations (one line each):**
- `e64b516`: Add full architecture doc and team lead SKILL v2
- `0b79fa1`: Engine + GUI: entry points, main window, alarm panel, instrument status
- `baaec03`: Experiment lifecycle, data export, replay, Telegram notifications
- `e4bbcb6`: Web dashboard, calibration stub, gitignore, updated docs

---

## Version 0.4.0 — Third Instrument and Test Base

### Boundary decision

**v2 origin:** v2 0.4.0 split 1/2  
Split from v2 0.4.0. v2 bundled this with launcher, conductivity, predictor, and connection settings; the earlier half is really about completing the instrument surface and proving the baseline with docs/tests.

### Rationale for this boundary

These nine commits read as one story: stabilize the new shell, add the third instrument, add the first serious test floor, and make all major tabs live.

### Date range

2026-03-14 02:12..2026-03-14 03:27

### Commit range

`33e51f3`..`da825f1`

### Themes in this version

- early integration fixes
- initial broad test suite
- Thyracont and live tab completion
- Russian docs/manual baseline

### Cluster 0.4.0.1 — Third Instrument and Test Base

**Commits:** `33e51f3`, `e4546df`, `734f641`, `fdbeb95`, `3cb98dd`, `641f21e`, `167eb7d`, `3dbd222`, `da825f1`  
**Goal:** Turn the rough shell into a minimally complete lab application with all three hardware classes visible and test-backed.  
**Approach:** Fix mock/test compatibility first, then add the large test drop, then complete the missing instrument and live UI surfaces, while writing the first operator-facing Russian docs.

**What changed:**
- Fixed mock-mode, timezone/WAL, and Windows event-loop issues.
- Added the first broad automated test suite and the Keithley mock config path.
- Added the Thyracont VSP63D driver, live web updates, and made all major GUI tabs active.
- Added the first Russian README and comprehensive operator manual.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
This is where the app first starts to look like a real workstation rather than a developer shell.

**Config file changes:**
`instruments.yaml` and notification/runtime docs became more concrete.

**API / contract changes:**
The third instrument and live-tab expectations became part of the runtime contract.

**Internal / architectural changes:**
The early test floor is historically important because later hardening relies on it.

**Why the order:**
Completing the third instrument and visible shell had to happen before more specialized measurement workflows.

**Commit explanations (one line each):**
- `33e51f3`: Fix mock mode: stub interlock actions, plugin loader init compat
- `e4546df`: Fix 5 test failures: timezone, WAL check, mock range, timeout setup
- `734f641`: Add comprehensive test suite: 118 tests across all modules
- `fdbeb95`: Add Keithley 2604B to instruments.yaml (USB-TMC mock)
- `3cb98dd`: Fix Windows event loop: SelectorEventLoop for pyzmq compatibility
- `641f21e`: Add README.md: architecture, quick start, project status (Russian)
- `167eb7d`: Thyracont VSP63D driver, periodic reports, live web dashboard
- `3dbd222`: Add comprehensive operator manual in Russian (docs/operator_manual.md)
- `da825f1`: GUI: Keithley, pressure, analytics panels — all tabs now live

---

## Version 0.5.0 — Launcher and Measurement Extensions

### Boundary decision

**v2 origin:** v2 0.4.0 split 2/2  
Split from v2 0.4.0. These five commits are not “third instrument completion”; they are a second wave focused on operator runtime extensions and measurement workflows.

### Rationale for this boundary

Once the base shell was complete, the work pivots to launcher behavior, dual-channel/runtime behavior, conductivity workflow, predictor/autosweep tooling, and connection management.

### Date range

2026-03-14 03:40..2026-03-14 05:02

### Commit range

`77638b0`..`b2b4d97`

### Themes in this version

- operator launcher
- dual-channel runtime extensions
- conductivity and predictor tooling
- connection/channel management

### Cluster 0.5.0.1 — Launcher and Measurement Extensions

**Commits:** `77638b0`, `dabce60`, `2f31378`, `84b01a7`, `b2b4d97`  
**Goal:** Push the completed shell into a more capable measurement workstation.  
**Approach:** Add launcher/runtime helpers, then extend Keithley behavior and measurement workflows, then expose channel and connection management explicitly.

**What changed:**
- Added operator launcher behavior and SQLite thread-safety adjustment.
- Added dual-channel Keithley control, Telegram bot commands, and portable deployment helpers.
- Added conductivity chain measurement and steady-state/auto-sweep tooling.
- Added channel manager and instrument connection settings UI.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High: launcher convenience, richer Keithley control, measurement workflows, and connection settings all become visible here.

**Config file changes:**
Connection and channel management become more operator-facing.

**API / contract changes:**
Dual-channel and channel-manager expectations start to matter to the rest of the app.

**Internal / architectural changes:**
This is the point where the workstation starts to feel tailored to the lab rather than merely complete.

**Why the order:**
These commits build on the shell completed in the previous version; they would have been premature before the third instrument and live tabs existed.

**Commit explanations (one line each):**
- `77638b0`: Operator launcher, SQLite thread-safety fix, aiohttp dependency
- `dabce60`: Keithley smua+smub, Telegram bot commands, portable deployment
- `2f31378`: Keithley control panel + thermal conductivity chain measurement
- `84b01a7`: Steady-state predictor + auto-sweep measurement panel
- `b2b4d97`: Channel manager + instrument connection settings UI

---

## Version 0.6.0 — Safety Architecture

### Boundary decision

**v2 origin:** v2 0.5.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This is the first governing-safety pivot: `SafetyManager`, `SafetyBroker`, fail-on-silence, and persistence-first all arrive here.

### Date range

2026-03-14 13:29..2026-03-14 18:18

### Commit range

`603a472`..`a8e8bbf`

### Themes in this version

- first real safety state machine
- fail-on-silence contract
- persistence-first contract

### Cluster 0.6.0.1 — Safety Architecture

**Commits:** `603a472`, `941d5e3`, `99df7eb`, `3f4b8fa`, `40b4ffb`, `efe16d3`, `dc5f3c6`, `a8e8bbf`  
**Goal:** Define the first explicit safety architecture for unattended cryogenic operation.  
**Approach:** Introduce dedicated safety ownership, review and fix the first exposed hazards, then codify the persistence-before-publish rule.

**What changed:**
- Added `SafetyManager`, `SafetyBroker`, and fail-on-silence behavior.
- Closed the first review findings around safety and thread-safety.
- Codified persistence-first ordering as a first-class invariant.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Operators would mostly experience safer default behavior, not a new surface.

**Config file changes:**
Safety and persistence rules became far more central even if schemas were still evolving.

**API / contract changes:**
This is the birth of the invariants later audits keep referring to.

**Internal / architectural changes:**
Arguably the most important early architectural release.

**Why the order:**
The author first proved the system could run, then encoded the rules needed to trust it around hardware.

**Commit explanations (one line each):**
- `603a472`: Safety architecture: SafetyManager, SafetyBroker, fail-on-silence
- `941d5e3`: Code review: 13 fixes — token revocation, safety, thread-safety, tests
- `99df7eb`: Update CLAUDE.md and README.md to current project state
- `3f4b8fa`: Add files via upload
- `40b4ffb`: Add files via upload
- `efe16d3`: Add files via upload
- `dc5f3c6`: Add files via upload
- `a8e8bbf`: SAFETY: persistence-first ordering — disk before subscribers

---

## Version 0.7.0 — Cooldown and Overview Intelligence

### Boundary decision

**v2 origin:** v2 0.6.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

The focus shifts from core safety to operator intelligence: cooldown prediction, overview dashboarding, export polish, and disk awareness belong together.

### Date range

2026-03-14 18:49..2026-03-14 22:53

### Commit range

`9217489`..`9390419`

### Themes in this version

- cooldown forecasting
- overview dashboard
- export and disk monitoring

### Cluster 0.7.0.1 — Cooldown and Overview Intelligence

**Commits:** `9217489`, `dd2dd2c`, `4dca478`, `b803967`, `7d8cc1f`, `68324c2`, `9390419`  
**Goal:** Make the system informative, not just interactive.  
**Approach:** Add a cooldown predictor end to end, then build the overview/dashboard/export surface around it and document the result.

**What changed:**
- Added cooldown predictor service, GUI, tests, and refactor support.
- Added overview dashboard, XLSX export, and disk monitoring.
- Updated docs to reflect cooldown integration and overview/export growth.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Operators got the first serious overview/dashboard experience and predictive cooldown intelligence.

**Config file changes:**
Runtime stats and overview expectations became more explicit in docs.

**API / contract changes:**
Cooldown-related services and dashboard hooks became part of the mental model.

**Internal / architectural changes:**
The system’s role expands from recorder/controller to predictor/observer.

**Why the order:**
With safety architecture in place, the next value move was insight and observability.

**Commit explanations (one line each):**
- `9217489`: Cooldown predictor integration: library refactor, service, GUI, tests
- `dd2dd2c`: Update CLAUDE.md and README.md: cooldown integration, persistence-first, stats
- `4dca478`: Add files via upload
- `b803967`: Overview dashboard, XLSX export, DiskMonitor, completed export TODOs
- `7d8cc1f`: Update CLAUDE.md and README.md: overview tab, XLSX, DiskMonitor, stats
- `68324c2`: Add files via upload
- `9390419`: Add files via upload

---

## Version 0.8.0 — Audit Safety Fixes

### Boundary decision

**v2 origin:** v2 0.7.0 split 1/2  
Split from v2 0.7.0. The first four commits are one emergency story: audit-triggered safety repair and P0 closure. The later deployment contract work is related but distinct.

### Rationale for this boundary

This release is about immediate hazard closure, not broader deployment hygiene.

### Date range

2026-03-14 23:17..2026-03-15 02:44

### Commit range

`e9a538f`..`0f8dd59`

### Themes in this version

- first audit-driven safety fixes
- P0 critical fixes
- FAULT/state/limit/heartbeat corrections

### Cluster 0.8.0.1 — Audit Safety Fixes

**Commits:** `e9a538f`, `678ff50`, `1bd6c4e`, `0f8dd59`  
**Goal:** Close the most dangerous gaps exposed by the first serious safety review.  
**Approach:** Apply the 14-audit-fix safety batch first, then tighten the most critical remaining P0 failure modes.

**What changed:**
- Closed the first 14 safety/audit issues around latch, status, and heartbeat behavior.
- Closed five P0 critical issues around alarm pipeline, safety state, and P/V/I limits.
- Preserved task/upload snapshots from the same emergency hardening session.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Mostly negative-space improvements: fewer dangerous or misleading failure modes.

**Config file changes:**
No major config redesign yet; this is runtime safety repair.

**API / contract changes:**
No headline API change; the main story is behavior correction.

**Internal / architectural changes:**
This is the first release that clearly reads as “the lab is pushing back on the prototype”.

**Why the order:**
These fixes had to land before broader deployment cleanup could be meaningfully discussed.

**Commit explanations (one line each):**
- `e9a538f`: SAFETY: 14 audit fixes — FAULT_LATCHED latch, status checks, heartbeat
- `678ff50`: Add files via upload
- `1bd6c4e`: P0: 5 critical fixes — alarm pipeline, safety state, P/V/I limits, latched flag
- `0f8dd59`: Add files via upload

---

## Version 0.9.0 — Deployment Contracts and Instrument Identity

### Boundary decision

**v2 origin:** v2 0.7.0 split 2/2  
Split from v2 0.7.0. P1 deployment fixes and the `instrument_id` data-model change form a second release with a different narrative: tightening contracts for real deployment.

### Rationale for this boundary

This is where the system stops merely fixing obvious hazards and starts formalizing deployment assumptions and data identity.

### Date range

2026-03-15 03:02..2026-03-15 18:02

### Commit range

`de715dc`..`0078d57`

### Themes in this version

- P1 lab deployment fixes
- timestamps/paths/sessions cleanup
- `Reading.instrument_id` breaking change

### Cluster 0.9.0.1 — Deployment Contracts and Instrument Identity

**Commits:** `de715dc`, `8d146bc`, `61dca77`, `9d48c41`, `2afdbc1`, `0078d57`  
**Goal:** Prepare the system for real deployment constraints after the immediate safety fires were out.  
**Approach:** Close the P1 deployment blocker set, then formalize instrument identity in the core data model.

**What changed:**
- Closed eight P1 lab deployment issues around async ZMQ, REAL timestamps, paths, and sessions.
- Introduced `instrument_id` as a first-class field on `Reading`.
- Preserved the remaining task/upload snapshots from the same stabilization wave.

**Breaking changes:**
Yes. `Reading.instrument_id` became a first-class required field.

**Operator-visible changes:**
Less visible than 0.8.0, but this release materially changes whether logs/data from multiple instruments can be trusted and correlated.

**Config file changes:**
Deployment/path/session assumptions became tighter.

**API / contract changes:**
`Reading.instrument_id` is a true breaking change for drivers and downstream consumers.

**Internal / architectural changes:**
This is the first explicit data-model contract tightening in the history.

**Why the order:**
Formal deployment/data contracts make more sense after the immediate safety emergency has been stabilized.

**Commit explanations (one line each):**
- `de715dc`: P1: 8 lab deployment fixes — async ZMQ, REAL timestamps, paths, sessions
- `8d146bc`: Add files via upload
- `61dca77`: BREAKING: instrument_id is now a first-class field on Reading dataclass
- `9d48c41`: Add files via upload
- `2afdbc1`: Add files via upload
- `0078d57`: Add files via upload

---

## Version 0.10.0 — RC Merge

### Boundary decision

**v2 origin:** v2 0.8.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

The merge is itself the historical event; later work only makes sense after this RC convergence point.

### Date range

2026-03-17 15:33..2026-03-17 15:33

### Commit range

`dc2ea6a`..`dc2ea6a`

### Themes in this version

- RC branch convergence

### Cluster 0.10.0.1 — RC Merge

**Commits:** `dc2ea6a`  
**Goal:** Converge the main development line onto the RC branch’s product shape.  
**Approach:** Merge the branch atomically instead of replaying its internal history on first-parent.

**What changed:**
- Merged the CRYODAQ-CODEX RC branch into `master`.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
The next several versions only make sense because this merge reset the product baseline.

**Config file changes:**
Inherited from the branch content.

**API / contract changes:**
Inherited from the branch content.

**Internal / architectural changes:**
This is a history-shaping merge, not a small code change.

**Why the order:**
Everything after this is post-RC work.

**Commit explanations (one line each):**
- `dc2ea6a`: Merge CRYODAQ-CODEX RC into master (v0.11.0-rc1)

---

## Version 0.11.0 — Dashboard Hub and Shift Workflow

### Boundary decision

**v2 origin:** v2 0.9.0 split 1/2  
Split from v2 0.9.0. The first four commits establish the overview as an operator hub and add structured shift handover. The later nine commits are a separate refinement marathon.

### Rationale for this boundary

These four commits already read like a complete release note: branch cleanup, launcher recovery, dashboard hub, and shift handover.

### Date range

2026-03-17 16:00..2026-03-17 17:14

### Commit range

`29652a2`..`f910c40`

### Themes in this version

- overview as operator hub
- structured shift handover
- launcher baseline polish

### Cluster 0.11.0.1 — Dashboard Hub and Shift Workflow

**Commits:** `29652a2`, `cdbba6c`, `b6ddb4e`, `f910c40`  
**Goal:** Make the overview screen the real operational center of the application.  
**Approach:** Clean post-merge leftovers, restore launcher ergonomics, then add quick actions/logging and structured shift handover.

**What changed:**
- Removed merged-branch clutter and fixed launcher/menu basics.
- Added dashboard hub quick-actions, quick log, and experiment status on Overview.
- Added structured shift handover workflow with start/prompts/end summary.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High: this is the point where Overview becomes more than a passive monitor.

**Config file changes:**
No major config churn.

**API / contract changes:**
Mostly UI-internal, but shift workflow becomes part of the operating model.

**Internal / architectural changes:**
This version sets the operator intent; the next one optimizes execution and rendering.

**Why the order:**
Shift workflow and hub semantics logically precede the later layout/performance tuning.

**Commit explanations (one line each):**
- `29652a2`: chore: delete merged branches, ignore .claude/ directory
- `cdbba6c`: fix: restore MainWindow menu in launcher, add --mock flag
- `b6ddb4e`: feat: dashboard hub — Keithley quick-actions, quick log, experiment status on Overview
- `f910c40`: feat: structured shift handover — start, periodic prompts, end summary

---

## Version 0.12.0 — Overview Performance Refinement

### Boundary decision

**v2 origin:** v2 0.9.0 split 2/2  
Split from v2 0.9.0. The second half is a sustained UX/performance iteration on Overview rather than a continuation of the shift/hub rollout.

### Rationale for this boundary

Nine consecutive commits all chase the same outcome: a readable, performant, denser overview surface under live load.

### Date range

2026-03-17 17:40..2026-03-17 19:16

### Commit range

`3dea162`..`2136623`

### Themes in this version

- layout refinement
- pyqtgraph/rendering performance
- overview graph synchronization and card density

### Cluster 0.12.0.1 — Overview Performance Refinement

**Commits:** `3dea162`, `a23ab92`, `dd663ae`, `a38154a`, `212e299`, `f4cb917`, `c848393`, `81c5a1d`, `2136623`  
**Goal:** Make the newly important Overview actually comfortable and performant to use.  
**Approach:** Iteratively rework the layout, card density, graph synchronization, and polling/rendering cost until the screen behaves well under live data.

**What changed:**
- Refactored Overview layout into a clearer two-column and then cards-on-top structure.
- Improved time-axis readability, temp-card density, splitter proportions, and compact experiment form behavior.
- Reduced UI work per reading via async polling and plot-throttle optimizations.
- Cleaned remaining tray/icon and dead-widget leftovers.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Very high: operators would feel this release immediately in readability and responsiveness.

**Config file changes:**
No major config changes.

**API / contract changes:**
Mostly UI-internal contracts.

**Internal / architectural changes:**
This is the first concentrated performance-ergonomics pass in the repository.

**Why the order:**
Once Overview became the hub, performance and layout had to catch up.

**Commit explanations (one line each):**
- `3dea162`: refactor: two-column Overview layout, move ExperimentWorkspace to separate tab
- `a23ab92`: fix: Overview — readable time axis, 8-per-row temp cards by instrument, scrollable panel
- `dd663ae`: fix: Overview layout — full-width temp cards, graph+info splitter
- `a38154a`: perf: async ZMQ polling in Overview widgets to eliminate UI lag
- `212e299`: perf: throttle plot updates, optimize pyqtgraph rendering, reduce UI work per reading
- `f4cb917`: refactor: Overview — cards on top, synced temp+pressure graphs, clickable channel toggle
- `c848393`: fix: dynamic temp cards, compact experiment form, unified button colors
- `81c5a1d`: fix: tray icon duplicate, post-P0 audit fixes
- `2136623`: chore: remove dead PressureStrip class and unused imports

---

## Version 0.13.0 — Calibration V2

### Boundary decision

**v2 origin:** v2 0.10.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

Calibration v2 is a tight backend→pipeline→GUI rollout and reads naturally as its own release.

### Date range

2026-03-17 19:42..2026-03-17 20:11

### Commit range

`81ef8a6`..`98a5951`

### Themes in this version

- continuous SRDG capture
- post-run extraction/downsampling/fitting
- three-mode calibration UI

### Cluster 0.13.0.1 — Calibration V2

**Commits:** `81ef8a6`, `e694d2d`, `38aca4f`, `98a5951`  
**Goal:** Replace the rough calibration placeholder with a real workflow.  
**Approach:** Start by capturing SRDG continuously, then add post-run extraction and fitting, then expose the whole flow through a dedicated GUI.

**What changed:**
- Added continuous SRDG acquisition during calibration experiments.
- Added post-run extraction, downsampling, breakpoint, and fit pipeline.
- Added a dedicated three-mode calibration GUI and cleaned legacy calibration sessions/docs.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High for calibration operators.

**Config file changes:**
Calibration-related expectations became more concrete.

**API / contract changes:**
Calibration pipeline and outputs matured substantially.

**Internal / architectural changes:**
Calibration becomes a first-class subsystem, not a stub.

**Why the order:**
The project had enough operational surface by now to support a specialized workflow like calibration v2.

**Commit explanations (one line each):**
- `81ef8a6`: feat: continuous SRDG acquisition during calibration experiments
- `e694d2d`: feat: calibration v2 post-run pipeline — extract, downsample, breakpoints, fit
- `38aca4f`: feat: calibration v2 GUI — three-mode panel with coverage and auto-fit
- `98a5951`: chore: calibration v2 cleanup — remove legacy sessions, update docs

---

## Version 0.14.0 — Phased Experiments and Auto Reports

### Boundary decision

**v2 origin:** v2 0.11.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

The theme here is experiment discipline: phases, auto-logging, auto-report generation, and polish around those flows.

### Date range

2026-03-17 20:36..2026-03-17 22:06

### Commit range

`bc41589`..`3b6a175`

### Themes in this version

- experiment phase tracking
- automatic operator/system logging
- automatic report generation

### Cluster 0.14.0.1 — Phased Experiments and Auto Reports

**Commits:** `bc41589`, `aad5eab`, `d8421e6`, `7f0e5d1`, `3b6a175`  
**Goal:** Make experiment execution explicitly phased and self-documenting.  
**Approach:** Improve the UI baseline, add formal phases, add auto-log/report behavior, then polish the resulting workflow and docs.

**What changed:**
- Added experiment phase tracking from preparation through teardown.
- Added automatic system-event logging and auto-generated reports on finalize.
- Polished phase-widget, empty states, styling, and documentation.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Very high: the software begins to lead operators through named phases rather than leaving lifecycle implicit.

**Config file changes:**
No major config changes.

**API / contract changes:**
Experiment phase semantics become part of the system vocabulary.

**Internal / architectural changes:**
Logging and reporting become lifecycle-coupled instead of ad hoc.

**Why the order:**
Once calibration and overview were in place, formalizing experiment lifecycle was the natural stabilizer.

**Commit explanations (one line each):**
- `bc41589`: fix: UX polish — DateAxisItem on all graphs, Russian labels, layout fixes
- `aad5eab`: feat: experiment phase tracking — preparation through teardown
- `d8421e6`: feat: auto-log system events, auto-generate report on finalize
- `7f0e5d1`: fix: P1 audit — phase widget, empty states, auto-entry styling, DateAxisItem everywhere
- `3b6a175`: feat: calibration start button, full docs sync to Russian

---

## Version 0.15.0 — First Lab-Usable Release

### Boundary decision

**v2 origin:** v2 0.12.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

Even without the deleted tag, this explicit release commit remains the clearest “first lab-usable” boundary in the history.

### Date range

2026-03-18 00:10..2026-03-18 00:10

### Commit range

`c22eca9`..`c22eca9`

### Themes in this version

- first explicit release cut

### Cluster 0.15.0.1 — First Lab-Usable Release

**Commits:** `c22eca9`  
**Goal:** Mark the first state that felt worthy of a real lab-facing release.  
**Approach:** Cut an explicit release commit.

**What changed:**
- Added the first explicit release marker.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
More about project state than feature surface.

**Config file changes:**
None.

**API / contract changes:**
None.

**Internal / architectural changes:**
This cleanly separates initial construction from post-release expansion and hardening.

**Why the order:**
The preceding versions collectively formed the first lab-usable system.

**Commit explanations (one line each):**
- `c22eca9`: release: v0.12.0 — first production release

---

## Version 0.16.0 — Remote Ops and Preflight

### Boundary decision

**v2 origin:** v2 0.13.0 split 1/2  
Split from v2 0.13.0. Remote surfaces and preflight workflow are already a coherent operator-facing release before alarm v2 begins.

### Rationale for this boundary

These five commits widen the operational surface without yet changing the alarm engine itself.

### Date range

2026-03-18 00:52..2026-03-18 01:30

### Commit range

`7ee15de`..`4405348`

### Themes in this version

- read-only web monitoring
- Telegram bot v2 and escalation
- pre-flight and experiment-form assistance

### Cluster 0.16.0.1 — Remote Ops and Preflight

**Commits:** `7ee15de`, `e553f11`, `ae70158`, `5678d96`, `4405348`  
**Goal:** Make the system operable and monitorable beyond the desktop UI.  
**Approach:** Add a read-only web dashboard, expand Telegram into a real remote-ops surface, add pre-flight checks and smarter experiment-form defaults, then stabilize Telegram polling startup.

**What changed:**
- Added read-only web monitoring page with auto-refresh.
- Added Telegram bot v2 with richer commands and escalation chain.
- Added pre-flight checklist and experiment-form auto-fill/history suggestions.
- Fixed Telegram polling startup/debug behavior.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Very high: this is the first real remote-ops release.

**Config file changes:**
Notification and web runtime settings become far more operationally relevant.

**API / contract changes:**
Remote command/status surfaces become first-class contracts.

**Internal / architectural changes:**
This release widens the operational surface without yet changing the alarm core.

**Why the order:**
Remote ops landed first; alarm v2 then built on the richer operational context.

**Commit explanations (one line each):**
- `7ee15de`: feat: web dashboard — read-only monitoring page with auto-refresh
- `e553f11`: feat: telegram bot v2 — /status, /log, /temps, /phase, escalation chain
- `ae70158`: feat: pre-flight checklist before experiment start
- `5678d96`: feat: experiment form auto-fill with history and name suggestion
- `4405348`: fix: telegram bot polling debug + ensure task started

---

## Version 0.17.0 — Alarm V2 Rollout

### Boundary decision

**v2 origin:** v2 0.13.0 split 2/2  
Split from v2 0.13.0. The alarm v2 backend, integration, and GUI are one of the clearest standalone release stories in the history.

### Rationale for this boundary

These six commits are a focused alarm-engine rewrite and rollout.

### Date range

2026-03-18 02:16..2026-03-18 02:38

### Commit range

`88357b8`..`d3b58bd`

### Themes in this version

- rate estimator and channel-state tracking
- alarm v2 evaluator/providers/config
- engine integration and GUI rollout

### Cluster 0.17.0.1 — Alarm V2 Rollout

**Commits:** `88357b8`, `046ab6f`, `3f86b42`, `8070b2d`, `ac404db`, `d3b58bd`  
**Goal:** Replace the early alarm logic with alarm v2 and expose it end to end.  
**Approach:** Lay backend foundations first, then add evaluator and providers/config, then wire the engine and GUI while fixing one interlock-side semantic issue.

**What changed:**
- Added alarm v2 foundations through `RateEstimator` and `ChannelStateTracker`.
- Added composite/rate/threshold/stale evaluation and providers/config parsing.
- Integrated alarm v2 into engine behavior and added the GUI panel plus docs.
- Fixed one false interlock/phase-gating issue exposed during rollout.

**Breaking changes:**
Alarm semantics changed materially enough that operators and config authors had to adapt.

**Operator-visible changes:**
High: alarm behavior and alarm UI both change materially here.

**Config file changes:**
Alarm configuration semantics become much richer.

**API / contract changes:**
Alarm evaluator/provider/config contracts become first-class.

**Internal / architectural changes:**
This is a major safety-surface expansion, not just a panel addition.

**Why the order:**
Once remote ops/preflight existed, upgrading the actual alarm semantics was the next obvious safety step.

**Commit explanations (one line each):**
- `88357b8`: feat: alarm v2 foundation — RateEstimator and ChannelStateTracker
- `046ab6f`: feat: alarm v2 evaluator — composite, rate, threshold, stale checks
- `3f86b42`: feat: alarm v2 providers and config parser
- `8070b2d`: feat: alarm v2 integration in engine with phase-dependent evaluation
- `ac404db`: fix: remove undercool_shield false interlock, phase-gate detector_warmup
- `d3b58bd`: feat: alarm v2 GUI panel and documentation

---

## Version 0.18.0 — Post-Release Stabilization

### Boundary decision

**v2 origin:** v2 0.14.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This is a small but coherent stabilization release immediately after the remote ops/alarm v2 surge.

### Date range

2026-03-18 10:45..2026-03-18 10:59

### Commit range

`92e1369`..`c7ae2ed`

### Themes in this version

- memory leak fix
- GUI reconnect fix
- headless tray-only monitoring

### Cluster 0.18.0.1 — Post-Release Stabilization

**Commits:** `92e1369`, `e601ca9`, `c7ae2ed`  
**Goal:** Stabilize the newly expanded operator surface after first real use.  
**Approach:** Fix the worst immediate regressions, then add a deployment-friendly headless mode.

**What changed:**
- Fixed broadcast-task memory leak and history/rate-trimming issues.
- Fixed empty plots after reconnect and a wrong experiment-status key.
- Added tray-only mode for headless engine monitoring.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Headless/tray-only mode is visible; the rest are “things stop breaking”.

**Config file changes:**
None.

**API / contract changes:**
None material.

**Internal / architectural changes:**
Shows the first true stabilization reflex after release.

**Why the order:**
Expected immediate repair release after a large surface expansion.

**Commit explanations (one line each):**
- `92e1369`: fix: memory leak — broadcast task explosion, rate estimator trim, history cap
- `e601ca9`: fix: empty plots after GUI reconnect, experiment status wrong key
- `c7ae2ed`: feat: tray-only mode for headless engine monitoring

---

## Version 0.19.0 — First Hardware Deployment

### Boundary decision

**v2 origin:** v2 0.15.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This is a hardware-reality release: the software meets real instruments and gets corrected by them.

### Date range

2026-03-18 17:12..2026-03-19 13:36

### Commit range

`d7c843f`..`1b5c099`

### Themes in this version

- first real hardware deployment fixes
- Thyracont V1 semantics
- Keithley and GPIB field corrections

### Cluster 0.19.0.1 — First Hardware Deployment

**Commits:** `d7c843f`, `4f717a5`, `8605a52`, `d0c40de`, `f3e62f5`, `d94e361`, `552f679`, `94ec2b6`, `1b5c099`  
**Goal:** Correct the software against what the actual lab hardware really does.  
**Approach:** Fix field failures first, then refine protocol and control semantics until the main hardware paths behave under real conditions.

**What changed:**
- Closed the first broad hardware deployment issue sweep spanning GPIB, Thyracont, Keithley, alarms, pressure card, and docs.
- Fixed Keithley source-off NaN crash and multiple Thyracont V1 protocol/formula assumptions.
- Fixed VISA bus race, tightened critical-channel rate semantics, and moved Keithley power control host-side.

**Breaking changes:**
Not a single public API break, but real hardware behavior assumptions changed materially.

**Operator-visible changes:**
High for anyone using the real hardware stack.

**Config file changes:**
Critical-channel semantics and protocol expectations became sharper.

**API / contract changes:**
Instrument behavior contracts changed to reflect real devices, not assumptions.

**Internal / architectural changes:**
Field deployment begins to shape the code as strongly as design intent.

**Why the order:**
Real devices are the fastest source of truth.

**Commit explanations (one line each):**
- `d7c843f`: fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off, alarms, pressure card, docs
- `4f717a5`: fix: keithley source-off NaN → SQLite NOT NULL crash
- `8605a52`: fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN?
- `d0c40de`: fix: thyracont V1 pressure formula, keithley output float parse, pressure exponent format
- `f3e62f5`: fix: thyracont V1 value is 6 digits (4 mantissa + 2 exponent), formula (ABCD/1000)*10^(EF-20)
- `d94e361`: fix: VISA bus lock to prevent -420 Query UNTERMINATED race
- `552f679`: fix: rate check scoped to critical channels only, disconnected sensors excluded
- `94ec2b6`: refactor: keithley P=const host-side control loop, remove blocking TSP script
- `1b5c099`: feat: keithley live P_target update + fix stop button

---

## Version 0.20.0 — GPIB Stabilization and ZMQ Isolation

### Boundary decision

**v2 origin:** v2 0.16.0 (kept)  
Kept as-is from v2, despite re-checking the possible split. The ZMQ subprocess isolation still reads as the capstone of the same reliability story rather than a new direction.

### Rationale for this boundary

The nine commits are one sustained engineering marathon: make transport reliable enough for continuous unattended polling, then isolate the last fragile dependency edge.

### Date range

2026-03-19 14:05..2026-03-19 16:41

### Commit range

`5bc640c`..`f64d981`

### Themes in this version

- bus locking discipline
- timeouts/clear/IFC recovery strategy
- persistent sessions
- ZMQ subprocess isolation

### Cluster 0.20.0.1 — GPIB Stabilization and ZMQ Isolation

**Commits:** `5bc640c`, `a0e9678`, `bb59488`, `946b454`, `fd229e9`, `31c4bae`, `5448f08`, `7efb8b7`, `f64d981`  
**Goal:** Make GPIB transport behavior reliable enough for continuous unattended polling.  
**Approach:** Repeatedly tighten bus-lock boundaries and recovery semantics until protocol assumptions match reality, then isolate ZMQ from the GUI process.

**What changed:**
- Widened and clarified GPIB bus-lock scope around open/close/query paths.
- Explored then refined open-per-query, IFC reset, sequential polling, and hot-path clear strategy.
- Corrected `KRDG?` details and finally moved to persistent sessions.
- Isolated ZMQ into a subprocess so the GUI no longer imports `zmq` directly.

**Breaking changes:**
Transport behavior changed enough to count as an internal breaking rewrite.

**Operator-visible changes:**
Mostly “the system stops hanging or glitching under load”.

**Config file changes:**
No major config changes.

**API / contract changes:**
Transport expectations changed materially.

**Internal / architectural changes:**
One of the project’s most important reliability marathons.

**Why the order:**
This is what happens when a real hardware bus refuses to tolerate naive assumptions.

**Commit explanations (one line each):**
- `5bc640c`: fix: GPIB bus lock covers open_resource() and close(), not just query/write
- `a0e9678`: fix: GPIB bus lock covers open_resource + verify query atomically
- `bb59488`: fix: GPIB open-per-query + IFC bus reset on timeout
- `946b454`: refactor: GPIB sequential polling — single task per bus, no parallel access
- `fd229e9`: fix: GPIB clear() before every query + IFC recovery on timeout
- `31c4bae`: fix: GPIB remove clear() from hot path, add write-delay-read
- `5448f08`: fix: GPIB KRDG? command + GUI visual fixes + ZMQ crash resilience
- `7efb8b7`: refactor: GPIB persistent sessions — LabVIEW-style open-once scheme
- `f64d981`: feat: isolate ZMQ into subprocess — GUI never imports zmq

---

## Version 0.21.0 — Analytics Expansion and Keithley Safety

### Boundary decision

**v2 origin:** v2 0.17.0 split 1/2  
Split from v2 0.17.0. The first seven commits are a clean rollout story: Keithley safety plus staged SensorDiagnostics/VacuumTrend backend→engine→GUI deployment.

### Rationale for this boundary

This is a feature-growth release centered on analytics and richer runtime diagnostics, not on audit cleanup.

### Date range

2026-03-20 13:04..2026-03-20 14:39

### Commit range

`856ad19`..`50e30e3`

### Themes in this version

- Keithley safety expansion
- SensorDiagnostics staged rollout
- VacuumTrendPredictor staged rollout

### Cluster 0.21.0.1 — Analytics Expansion and Keithley Safety

**Commits:** `856ad19`, `757f59e`, `6eb8dfe`, `b21bca1`, `5d7fe2b`, `c1b9eb5`, `50e30e3`  
**Goal:** Improve both self-observation and predictive analytics while tightening Keithley runtime safety.  
**Approach:** Add Keithley safety and subprocess hardening, then roll out SensorDiagnostics and VacuumTrend through the usual backend→engine→GUI progression.

**What changed:**
- Added Keithley safety around slew rate/compliance and some ZMQ subprocess hardening.
- Rolled out SensorDiagnostics in three stages: backend, engine integration/config, GUI.
- Rolled out VacuumTrendPredictor in three stages: backend, engine integration/config, GUI.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High on the analytics side.

**Config file changes:**
Diagnostics and vacuum trend config enter the project here.

**API / contract changes:**
The staged analytics subsystems become first-class runtime contracts.

**Internal / architectural changes:**
This version demonstrates the project’s preferred rollout style: backend first, then engine, then GUI.

**Why the order:**
After transport stabilization, richer analytics and diagnostics were the next leverage point.

**Commit explanations (one line each):**
- `856ad19`: feat: Keithley safety (slew rate, compliance) + ZMQ subprocess hardening
- `757f59e`: feat: SensorDiagnosticsEngine — backend + 20 unit tests (Stage 1)
- `6eb8dfe`: feat: SensorDiagnostics — engine integration + config (Stage 2)
- `b21bca1`: feat: SensorDiagnostics GUI panel + status bar summary (Stage 3)
- `5d7fe2b`: feat: VacuumTrendPredictor — backend + 20 unit tests (Stage 1)
- `c1b9eb5`: feat: VacuumTrendPredictor — engine integration + config (Stage 2)
- `50e30e3`: feat: VacuumTrendPredictor GUI panel on Analytics tab (Stage 3)

---

## Version 0.22.0 — Safety Deepening and Review Fixes

### Boundary decision

**v2 origin:** v2 0.17.0 split 2/2  
Split from v2 0.17.0. The remaining six commits are no longer about analytics rollout; they are a second release about safety phases, review findings, serialization fixes, and late UI fallout.

### Rationale for this boundary

These commits share one dominant story: safety and correctness deepen again after the analytics surfaces land.

### Date range

2026-03-20 16:03..2026-03-21 00:39

### Commit range

`afabfe5`..`af94285`

### Themes in this version

- ZMQ serialization correction
- Phase 2/3 safety work
- deep review and audit fixes
- late adaptive-liveness/UI fallout cleanup

### Cluster 0.22.0.1 — Safety Deepening and Review Fixes

**Commits:** `afabfe5`, `6ef43df`, `bbb5809`, `4b52de8`, `10d4d76`, `af94285`  
**Goal:** Tighten safety correctness and close the review/audit fallout exposed by the previous release.  
**Approach:** Fix a ZMQ serialization trap, then land deeper safety phases and close the resulting review and audit bug batches.

**What changed:**
- Fixed ZMQ datetime serialization and REP socket stuck-on-error behavior.
- Landed Phase 2 and Phase 3 safety/correctness work.
- Closed deep-review and audit bug batches.
- Cleaned the rollout fallout around CSV BOM, sensor diagnostics, calibration stretch, reports toggle, and adaptive liveness.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Moderate directly, high in terms of trust and correctness.

**Config file changes:**
Some diagnostics/safety-related expectations sharpen here.

**API / contract changes:**
No single hard API break, but several runtime semantics changed.

**Internal / architectural changes:**
This is the point where the project starts integrating review feedback almost as a continuous subsystem.

**Why the order:**
Once the new analytics surfaces existed, their correctness and safety interactions had to be tightened.

**Commit explanations (one line each):**
- `afabfe5`: fix: ZMQ datetime serialization + REP socket stuck on serialization error
- `6ef43df`: feat: Phase 2 safety hardening — tests + bugfixes + LakeShore RDGST?
- `bbb5809`: feat: Phase 3 — safety correctness, reliability, phase detector
- `4b52de8`: fix: deep review — 2 bugs fixed, 2 tests added
- `10d4d76`: fix(audit): 6 bugs — safety race, SQLite shutdown, Inf filter, phase reset, GPIB leak, deque cap
- `af94285`: fix(ui): CSV BOM, sensor diag stretch, calibration stretch, reports on, adaptive liveness

---

## Version 0.23.0 — UI Refactor Merge and Post-Merge Cleanup

### Boundary decision

**v2 origin:** v2 0.18.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

The `feature/ui-refactor` merge imported a substantial UI reshaping, and the following commits are the immediate cleanup necessary to make that merge viable on master.

### Date range

2026-03-21 02:39..2026-03-21 12:35

### Commit range

`1ec93a6`..`f08e6bb`

### Themes in this version

- UI refactor merge
- post-merge safety/UI cleanup
- autosweep deprecation

### Cluster 0.23.0.1 — UI Refactor Merge and Post-Merge Cleanup

**Commits:** `1ec93a6`, `c427247`, `a2f4bcd`, `1670bbe`, `2ab7283`, `dc84f0c`, `1dd7405`, `f08e6bb`  
**Goal:** Absorb the UI refactor branch and fix the regressions it surfaced.  
**Approach:** Merge first, then patch obvious safety, data-split, channel/default, and control-surface issues immediately.

**What changed:**
- Merged `feature/ui-refactor` into `master` and updated docs/version metadata.
- Fixed mixed safety/runtime issues including Thyracont fallback, SQLite read/write split, and Keithley disconnect handling.
- Fixed UI interaction fallout, removed dangerous QuickStart buttons, and deprecated `autosweep_panel`.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High.

**Config file changes:**
Default channels and version strings shifted.

**API / contract changes:**
Read/write split and deprecations matter to developers and tests.

**Internal / architectural changes:**
Merge commits often need their own cleanup release note; this is a textbook case.

**Why the order:**
Merge first, then stabilize the integrated state.

**Commit explanations (one line each):**
- `1ec93a6`: merge: feature/ui-refactor
- `c427247`: docs: update all documentation, changelog, and version for v0.13.0
- `a2f4bcd`: fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect
- `1670bbe`: fix(ui): card toggle signals, history load on window change, axis alignment, channel refresh
- `2ab7283`: chore: fix default channels, web version, deprecate autosweep_panel
- `dc84f0c`: fix(ui): remove QuickStart buttons from overview (caused FAULT with P=0)
- `1dd7405`: feat(ui): rename Keithley tab, add time window buttons, forecast zone
- `f08e6bb`: fix: audit wave 3 — build_ensemble guard, launcher ping, phase gap, RDGST, docs

---

## Version 0.24.0 — Final-Batch Integration

### Boundary decision

**v2 origin:** v2 0.19.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This release is another integration wave, but different from the UI merge: single-instance lock, ZMQ request/reply routing, experiment I/O threading, and several overview/history fixes belong together.

### Date range

2026-03-21 15:20..2026-03-22 00:25

### Commit range

`9e2ce5b`..`dd42632`

### Themes in this version

- final-batch merge
- atomic single-instance guard
- ZMQ command/reply cleanup
- experiment I/O deblocking

### Cluster 0.24.0.1 — Final-Batch Integration

**Commits:** `9e2ce5b`, `7618031`, `4df40c3`, `0603110`, `9942da1`, `6d39a08`, `45ae750`, `031491a`, `dd42632`  
**Goal:** Consolidate a batch of must-have runtime fixes before further feature work.  
**Approach:** Merge the batch, then tighten critical runtime guarantees and polish the affected operator surfaces.

**What changed:**
- Merged the final-batch branch.
- Fixed Telegram output semantics and pressure log-scale handling.
- Made single-instance locking atomic and cleaned ZMQ reply routing.
- Moved experiment I/O off the blocking path and improved overview/history behavior.

**Breaking changes:**
Archive/reporting behavior changed meaningfully, though not via one hard API break.

**Operator-visible changes:**
Moderate to high, especially in reliability and history behavior.

**Config file changes:**
No significant config churn.

**API / contract changes:**
Command/reply routing and experiment I/O assumptions changed.

**Internal / architectural changes:**
Shows growing sensitivity to anything blocking the operator path.

**Why the order:**
This kind of batch belongs before another large feature wave.

**Commit explanations (one line each):**
- `9e2ce5b`: merge: final-batch — single-instance, ML forecast, flight recorder, driver fixes
- `7618031`: fix(telegram): natural channel sort, compact text, pressure log-scale Y limits
- `4df40c3`: fix(critical): atomic single-instance lock via O_CREAT|O_EXCL
- `0603110`: fix(zmq): correlation ID for command-reply routing
- `9942da1`: fix(ui): proportional history load, overview plot sync, CSV BOM
- `6d39a08`: fix(critical): move experiment I/O to thread, remove double report generation
- `45ae750`: fix(zmq): Future-per-request dispatcher with dedicated reply consumer
- `031491a`: fix(ui): "Всё"→"Сутки", pass channels to history, poll_readings resilience
- `dd42632`: fix(ui): snap graph X-axis to data start across all 7 panels

---

## Version 0.25.0 — Audit-v2, Parquet v1, and Reporting

### Boundary decision

**v2 origin:** v2 0.20.0 (kept)  
Kept as-is from v2. Re-checked the possible split and concluded these commits still share one narrative: raise operational credibility through artifacts, CI, and reporting.

### Rationale for this boundary

Audit-v2 merge, first Parquet archive work, CI, and professional reporting all support the same “make outputs and process production-shaped” story.

### Date range

2026-03-22 16:11..2026-03-23 00:37

### Commit range

`0fdc507`..`29d2215`

### Themes in this version

- audit-v2 merge
- Parquet archive v1
- CI workflow
- professional reporting

### Cluster 0.25.0.1 — Audit-v2, Parquet v1, and Reporting

**Commits:** `0fdc507`, `fc1c61b`, `ccf98c9`, `f0c68c6`, `423c6d5`, `8dc07f7`, `a066cd7`, `b7265bb`, `29d2215`  
**Goal:** Widen the project’s operational credibility through artifact quality, CI, and audit-driven fixes.  
**Approach:** Absorb the audit-v2 fix batch, add Parquet export, add CI, then raise reporting quality substantially.

**What changed:**
- Merged audit-v2 fixes.
- Added first Parquet archive export and archive-table integration.
- Added CI workflow.
- Added professional reporting and later ГОСТ formatting, then fixed reporting layout/page-break issues.
- Closed audit regressions touching preflight, multi-day DB, overview resolver, and Parquet docs.

**Breaking changes:**
Artifact and reporting outputs became more formalized.

**Operator-visible changes:**
High for reports and archive artifacts.

**Config file changes:**
None major.

**API / contract changes:**
Archive/reporting outputs became more formalized.

**Internal / architectural changes:**
The system stops being “just a DAQ” and becomes an evidence/report producer.

**Why the order:**
After runtime integration stabilized, artifact quality became the next obvious professionalization step.

**Commit explanations (one line each):**
- `0fdc507`: merge: audit-v2 fixes (29 defects, 9 commits)
- `fc1c61b`: feat(storage): Parquet experiment archive — write readings.parquet alongside CSV on finalize
- `ccf98c9`: Add CI workflow for CryoDAQ with testing and linting
- `f0c68c6`: feat(archive): Parquet column in table, human-readable artifacts, parquet read fix
- `423c6d5`: fix(archive): inclusive end-date filter, add end time column
- `8dc07f7`: feat(reporting): professional human-readable reports for all experiment types
- `a066cd7`: feat(reporting): ГОСТ Р 2.105-2019 formatting, all graphs in all reports
- `b7265bb`: fix(reporting): multi-channel graphs, black headings, smart page breaks
- `29d2215`: fix: audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring

---

## Version 0.26.0 — GPIB Recovery and Preflight Tuning

### Boundary decision

**v2 origin:** v2 0.21.0 split 1/2  
Split from v2 0.21.0. The first five commits are clearly about recovery and preflight semantics, before the later GUI/launcher non-blocking wave begins.

### Rationale for this boundary

These commits share one deployment story: recover better from hung hardware and tune preflight semantics to operational reality.

### Date range

2026-03-23 14:59..2026-03-24 12:55

### Commit range

`ab57e01`..`dfd6021`

### Themes in this version

- GPIB auto-recovery escalation
- scheduler reconnect
- preflight severity/encoding tuning

### Cluster 0.26.0.1 — GPIB Recovery and Preflight Tuning

**Commits:** `ab57e01`, `ea5a8da`, `86e8e8c`, `c10e617`, `dfd6021`  
**Goal:** Harden the system against deployment-time transport hangs and over-strict preflight behavior.  
**Approach:** Escalate GPIB recovery strategy, add scheduler-level reconnect after repeated errors, and soften/repair preflight semantics.

**What changed:**
- Added GPIB timeout recovery and escalated IFC/unaddressing reset behavior.
- Added standalone instrument disconnect/reconnect after consecutive errors.
- Changed sensor-health preflight from hard error to warning and restored encoding handling.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Operators mostly notice fewer “stuck hardware” and overly-blocking preflight failures.

**Config file changes:**
Preflight severity semantics shifted.

**API / contract changes:**
Recovery expectations changed materially.

**Internal / architectural changes:**
This is the transport-recovery half of v2 0.21.0, separated from the later UI/launcher half.

**Why the order:**
Recovery logic and preflight tuning logically precede the next batch of non-blocking UI work.

**Commit explanations (one line each):**
- `ab57e01`: fix(gpib): auto-recovery from hung instruments — clear bus on timeout, preventive clear
- `ea5a8da`: fix(gpib): IFC bus reset, enable unaddressing, escalating recovery
- `86e8e8c`: fix(preflight): sensor health is warning not error
- `c10e617`: fix(scheduler): standalone instrument disconnect+reconnect on consecutive errors
- `dfd6021`: fix(preflight): restore encoding + sensor health warning not error

---

## Version 0.27.0 — Non-Blocking GUI and Singleton Hardening

### Boundary decision

**v2 origin:** v2 0.21.0 split 2/2  
Split from v2 0.21.0. These eight commits form their own release around non-blocking operator flows, launcher health, and singleton protections.

### Rationale for this boundary

This half is no longer about transport recovery; it is about making the GUI and launcher behave sanely under deployment stress.

### Date range

2026-03-24 13:10..2026-03-25 12:59

### Commit range

`8bac038`..`f217427`

### Themes in this version

- non-blocking alarm/bridge/command paths
- launcher and GUI health fixes
- single-instance protection
- workspace/layout/debounce cleanup

### Cluster 0.27.0.1 — Non-Blocking GUI and Singleton Hardening

**Commits:** `8bac038`, `6d0f5ba`, `bab4d8a`, `4eb5f1a`, `3c46dfb`, `e7d4fc5`, `f47762d`, `f217427`  
**Goal:** Remove blocking and duplicate-instance behavior from the operator-facing runtime paths.  
**Approach:** Make status polling and command paths non-blocking, then add singleton protection and clean the remaining launcher/workspace/live-update rough edges.

**What changed:**
- Removed blocking from alarm v2 status polling and several launcher/bridge command paths.
- Added single-instance protection for launcher and standalone GUI.
- Fixed conductivity/launcher gaps, Keithley debounce, workspace layout, non-blocking engine restart, and shift-modal re-entrancy.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
High: this is directly about whether the UI feels safe and responsive during deployment.

**Config file changes:**
No major config changes.

**API / contract changes:**
Mostly operational/runtime behavior changes.

**Internal / architectural changes:**
This is the deployment-UX half of v2 0.21.0.

**Why the order:**
Once recovery semantics were improved, the next bottleneck was blocking UI/launcher behavior.

**Commit explanations (one line each):**
- `8bac038`: fix(gui): non-blocking alarm v2 status poll
- `6d0f5ba`: fix(gui): bridge heartbeat false kills + launcher blocking send_command
- `bab4d8a`: feat: single-instance protection for launcher and standalone GUI
- `4eb5f1a`: fix(gui): launcher bridge health gap + conductivity blocking send_command
- `3c46dfb`: fix(gui): keithley spinbox debounce + non-blocking live update
- `e7d4fc5`: fix(gui): experiment workspace 1080p layout — phase bar + passport forms
- `f47762d`: fix: launcher non-blocking engine restart + deployment hardening
- `f217427`: fix: shift modal re-entrancy + engine --force PermissionError

---

## Version 0.28.0 — Pre-Phase-2d Hardening Prep

### Boundary decision

**v2 origin:** v2 0.22.0 (kept)  
Kept as-is from v2.

### Rationale for this boundary

This is the explicit pre-2d cleanup wave, not yet the big structured hardening effort itself.

### Date range

2026-03-31 03:17..2026-04-08 22:16

### Commit range

`9676165`..`1698150`

### Themes in this version

- audit-driven prep fixes
- PyInstaller unblock
- Phase 1/2a/2b/2c fix blocks

### Cluster 0.28.0.1 — Pre-Phase-2d Hardening Prep

**Commits:** `9676165`, `9feaf3e`, `a60abc0`, `0333e52`, `8a24ead`, `b185fd3`, `1698150`  
**Goal:** Clear enough obvious issues that the subsequent structured hardening can focus on deeper invariants rather than surface noise.  
**Approach:** Apply targeted audit fixes, unblock the build, then run Phase 1/2a/2b/2c closure blocks in sequence.

**What changed:**
- Fixed audit findings around `plugins.yaml`, `sensor_diagnostics`, and GUI non-blocking paths.
- Unblocked the PyInstaller build.
- Closed Phase 1, 2a, 2b, and 2c fix blocks and made one final overview preset tweak.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Mostly negative-space improvements plus the preset rename.

**Config file changes:**
Cleanup around plugins/config references.

**API / contract changes:**
Little direct API churn; mostly issue closure.

**Internal / architectural changes:**
This is the staging ground for Phase 2d.

**Why the order:**
The team is clearly preparing for a more formal hardening campaign.

**Commit explanations (one line each):**
- `9676165`: fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking
- `9feaf3e`: fix: audit - GUI non-blocking send_command + dead code cleanup
- `a60abc0`: fix: Phase 1 pre-deployment — unblock PyInstaller build
- `0333e52`: fix: Phase 2a safety hardening — close 4 HIGH findings
- `8a24ead`: fix: Phase 2b observability & resilience — close 8 MEDIUM findings
- `b185fd3`: fix: Phase 2c final hardening — close 8 findings before Phase 3
- `1698150`: ui: replace Overview "Сутки" preset with "Всё"

---

## Version 0.29.0 — Audit Corpus

### Boundary decision

**v2 origin:** v2 0.23.0 split 1/2  
Split from v2 0.23.0. The first twelve commits are a dense, self-contained audit corpus with synthesis; the later reality-map/docs commits are governance follow-through, not the corpus itself.

### Rationale for this boundary

The project spends a whole chapter auditing itself. That chapter deserves to stand on its own before documentation reconciliation begins.

### Date range

2026-04-09 00:45..2026-04-09 04:20

### Commit range

`380df96`..`7aaeb2b`

### Themes in this version

- deep audit passes
- verification and deep dives
- triage synthesis

### Cluster 0.29.0.1 — Audit Corpus

**Commits:** `380df96`, `fd99631`, `fd8c8bf`, `847095c`, `5d618db`, `10667df`, `31dbbe8`, `3e20e86`, `916fae4`, `a108519`, `24b928d`, `7aaeb2b`  
**Goal:** Build a high-confidence map of what the software actually is and what still needs hardening.  
**Approach:** Run multiple deep audit passes, then synthesize them into a master triage while keeping the artifacts in-repo.

**What changed:**
- Added CC and Codex deep audit passes.
- Added verification pass, SafetyManager deep dive, persistence trace, driver fault injection, CVE sweep, analytics/reporting/plugins deep dive, and config audit.
- Added master triage synthesis and supporting gitignore/cherry-pick glue.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Minimal directly, but this is what made later hardening targeted rather than intuitive.

**Config file changes:**
Indirectly reframed configs as safety surfaces.

**API / contract changes:**
No production API changes; this is evidence and analysis.

**Internal / architectural changes:**
The project becomes self-auditing and evidence-driven here.

**Why the order:**
Phase 2d is much easier to understand as a direct response to this version.

**Commit explanations (one line each):**
- `380df96`: audit: deep audit pass (CC) post-2c
- `fd99631`: audit: deep audit pass (Codex overnight) post-2c
- `fd8c8bf`: chore: gitignore local audit artifacts (DEEP_AUDIT_*.md, graphify-out/)
- `847095c`: audit: cherry-pick hardening pass document from feat/ui-phase-1
- `5d618db`: audit: verification pass - re-check 5 HIGH findings from hardening pass
- `10667df`: audit: SafetyManager exhaustive FSM analysis
- `31dbbe8`: audit: persistence-first invariant exhaustive trace
- `3e20e86`: audit: driver layer fault injection scenarios
- `916fae4`: audit: full dependency CVE sweep with version verification
- `a108519`: audit: reporting + analytics + plugins deep dive
- `24b928d`: audit: configuration files security and consistency audit
- `7aaeb2b`: audit: master triage synthesis of all audit documents

---

## Version 0.30.0 — Reality Map and Documentation Reconciliation

### Boundary decision

**v2 origin:** v2 0.23.0 split 2/2  
Split from v2 0.23.0. These four commits happen days later and have a different goal: reconcile docs and guidance with the reality that the audit corpus exposed.

### Rationale for this boundary

This is governance/documentation work, not more auditing.

### Date range

2026-04-12 23:25..2026-04-13 16:09

### Commit range

`995f7bc`..`1d71ecc`

### Themes in this version

- doc-vs-code reality map
- team-lead guidance rewrite
- CLAUDE.md module/config correction

### Cluster 0.30.0.1 — Reality Map and Documentation Reconciliation

**Commits:** `995f7bc`, `6eb7d3e`, `ddf6459`, `1d71ecc`  
**Goal:** Bring project documentation and guidance back into sync with the code reality discovered by the audits.  
**Approach:** Build the reality map first, then rewrite internal guidance and module/config references to match it.

**What changed:**
- Added the doc-vs-code reality map.
- Rewrote the team-lead skill against current repository reality.
- Added missing config references and expanded/fixed the `CLAUDE.md` module index and safety invariants.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Mostly invisible, but important for future maintainers and future LLM-assisted work.

**Config file changes:**
Documentation of config coverage becomes much more accurate.

**API / contract changes:**
No runtime API changes.

**Internal / architectural changes:**
This is the governance half of the audit wave.

**Why the order:**
Only after the audit corpus existed could the docs be reconciled honestly.

**Commit explanations (one line each):**
- `995f7bc`: discovery: build doc-vs-code reality map (CC + Codex review)
- `6eb7d3e`: docs: rewrite cryodaq-team-lead skill against current code reality
- `ddf6459`: docs(CLAUDE.md): add missing config files to list
- `1d71ecc`: docs(CLAUDE.md): expand module index, fix safety FSM and invariants

---

## Version 0.31.0 — Phase 2d Safety and Persistence

### Boundary decision

**v2 origin:** v2 0.24.0 (kept)  
Kept as-is from v2 after re-checking the possible split. Block A and Block B are interleaved but still read as one structured hardening release with one checkpoint and one dominant story.

### Rationale for this boundary

This is the major structured hardening release proper: safety, alarm-config hardening, fail-closed coercion, atomic file writes, shield follow-up, persistence integrity, NaN-state fix.

### Date range

2026-04-13 16:27..2026-04-13 23:22

### Commit range

`88feee5`..`23929ca`

### Themes in this version

- Block A safety hardening
- alarm config hardening
- atomic file writes and WAL verification
- persistence integrity

### Cluster 0.31.0.1 — Phase 2d Safety and Persistence

**Commits:** `88feee5`, `1446f48`, `ebac719`, `1b12b87`, `e068cbf`, `d3abee7`, `5cf369e`, `104a268`, `21e9c40`, `23929ca`  
**Goal:** Close the highest-value audit findings in a disciplined, block-structured way.  
**Approach:** Tackle safety first, then config typing, then safety->experiment/alarm config hardening, then atomic file writes/WAL, then persistence integrity and state-value filtering.

**What changed:**
- Closed web XSS and hardened `SafetyManager`, including the RUN_PERMITTED heartbeat gap and config coercion path.
- Hardened alarm config and added the safety->experiment bridge.
- Added atomic file writes and WAL verification.
- Closed post-fault shielding holes and landed the persistence-integrity block, including NaN-valued status filtering.

**Breaking changes:**
Safety/config/persistence semantics became stricter and more fail-closed.

**Operator-visible changes:**
Mostly invisible, but central to whether the system deserves trust.

**Config file changes:**
Fail-closed and stricter config behavior is a major theme.

**API / contract changes:**
Several core invariants became enforceable in code, not just in docs.

**Internal / architectural changes:**
Arguably the strongest hardening step in the repository history.

**Why the order:**
This is the direct code response to the audit-corpus version.

**Commit explanations (one line each):**
- `88feee5`: phase-2d-a1: web XSS + SafetyManager hardening + T regression
- `1446f48`: phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class
- `ebac719`: phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError
- `1b12b87`: phase-2d-a2: alarm config hardening + safety->experiment bridge
- `e068cbf`: phase-2d-a2-fix: close Codex findings on 1b12b87
- `d3abee7`: phase-2d-b1: atomic file writes + WAL verification
- `5cf369e`: phase-2d-a8-followup: shield post-fault cancellation paths
- `104a268`: phase-2d-b2: persistence integrity
- `21e9c40`: phase-2d-b2-fix: drop NaN-valued statuses from persist set
- `23929ca`: phase-2d: checkpoint — Block A+B complete, update PROJECT_STATUS

---

## Version 0.32.0 — Phase 2d Closure and Fail-Closed Completion

### Boundary decision

**v2 origin:** v2 0.25.0 split 1/2  
Split from v2 0.25.0. The first five commits are still about closing Phase 2d: cleanup, Jules R2 fixes, fail-closed completion, and declaration of completion. Parquet kickoff and round-2 docs are a new story.

### Rationale for this boundary

This is a late hardening-closure release, not yet the beginning of the archive line.

### Date range

2026-04-14 01:14..2026-04-14 02:36

### Commit range

`efe6b49`..`0cd8a94`

### Themes in this version

- cleanup of incidental debt
- Jules R2 closure fixes
- config fail-closed completion
- 2d completion declaration

### Cluster 0.32.0.1 — Phase 2d Closure and Fail-Closed Completion

**Commits:** `efe6b49`, `f4c256f`, `74f6d21`, `89ed3c1`, `0cd8a94`  
**Goal:** Finish the remaining Phase 2d contract closures cleanly before Phase 2e starts.  
**Approach:** Clean lint/log debt, close the late ordering/state-mutation gaps, complete fail-closed config work, and explicitly declare Phase 2d complete.

**What changed:**
- Cleaned accumulated lint debt and removed accidentally committed logs.
- Closed Jules round-2 ordering and state-mutation gaps.
- Completed fail-closed config work and cleanup.
- Declared Phase 2d complete and opened Phase 2e.

**Breaking changes:**
Config strictness increased again as fail-closed completion landed.

**Operator-visible changes:**
Mostly invisible except as stricter/faster startup and fewer latent edge cases.

**Config file changes:**
Fail-closed completion is the headline.

**API / contract changes:**
Config strictness increases further.

**Internal / architectural changes:**
This is the closure half of v2 0.25.0.

**Why the order:**
It had to land before the archive line and round-2 context could reasonably be described as the next chapter.

**Commit explanations (one line each):**
- `efe6b49`: chore: ruff --fix accumulated lint debt
- `f4c256f`: chore: remove accidentally committed logs/, add to .gitignore
- `74f6d21`: phase-2d-jules-r2-fix: close ordering and state mutation gaps
- `89ed3c1`: phase-2d-c1: config fail-closed completion + cleanup
- `0cd8a94`: phase-2d: declare COMPLETE, open Phase 2e

---

## Version 0.33.0-pre — Phase 2e Archive Kickoff and Round-2 Audit Context

### Boundary decision

**v2 origin:** v2 0.25.0 split 2/2  
Split from v2 0.25.0. Once `445c056` lands, the story has changed: this is now the first Phase 2e archive release, plus the docs/audit context that explains the current unreleased state.

### Rationale for this boundary

The current unreleased line is no longer “finish Phase 2d”; it is “start archive work and preserve the round-2 evidence around it”.

### Date range

2026-04-14 02:55..2026-04-14 04:19

### Commit range

`445c056`..`5b3ca29`

### Themes in this version

- Phase 2e Parquet finalize export
- branch/repo/audit inventories
- round-2 state capture

### Cluster 0.33.0-pre.1 — Phase 2e Archive Kickoff and Round-2 Audit Context

**Commits:** `445c056`, `855870b`, `5ad0156`, `1c75967`, `66f9870`, `6535c9a`, `88c308c`, `5b3ca29`  
**Goal:** Open the archive line while preserving the exact audit and repository context around it.  
**Approach:** Start with the Parquet-at-finalize archive change, then add the branch/repo/audit reference documents and status updates that contextualize the new state.

**What changed:**
- Added Parquet archive export at experiment finalize.
- Added branch inventory, repo inventory, CC/Codex round-2 audit outputs, remote branch cleanup record, and updated status numbers.
- Committed historical pre-Phase-2c audit artifacts for reference.

**Breaking changes:**
None beyond the historical behavior/contract shifts already implicit in the theme.

**Operator-visible changes:**
Archive output expands again via Parquet; otherwise this is mostly maintainership-facing context.

**Config file changes:**
No major config redesign here.

**API / contract changes:**
Finalize/archive contract now includes Phase 2e stage-1 Parquet work.

**Internal / architectural changes:**
This is the current unreleased line and should likely stay pre-release in the final numbering.

**Why the order:**
It naturally follows the 2d completion release and opens the next work line without pretending the project is already stable enough for `1.0.0`.

**Commit explanations (one line each):**
- `445c056`: phase-2e-parquet-1: experiment archive via Parquet at finalize
- `855870b`: docs(audits): add BRANCH_INVENTORY.md for three-track review input
- `5ad0156`: docs(audits): add repo inventory, dead code scan, and CC findings summary
- `1c75967`: docs/audits: Codex round 2 extended semantic audit
- `66f9870`: docs/audits: CC round 2 extended inventory
- `6535c9a`: docs/audits: record remote branch cleanup
- `88c308c`: docs: update PROJECT_STATUS.md numbers for round 2 audit state
- `5b3ca29`: chore: commit historical pre-Phase-2c audit artifacts

---

## Cross-version patterns

### Pattern: Safety architecture evolution

The safety story is no longer just one early pivot. v3 makes the repeated deepening clearer. `0.6.0` establishes the governing model with `SafetyManager`, `SafetyBroker`, fail-on-silence, and persistence-first. `0.8.0` and `0.9.0` then show the first deployment pressure on that model. `0.17.0` and `0.22.0` split what v2 compressed into one “Diagnostics and Safety Expansion” bucket: first the system grows smarter, then safety correctness and review-driven fixes catch up. Finally `0.31.0` and `0.32.0` distinguish the structured Phase 2d hardening itself from the late closure/fail-closed completion work around it.

### Pattern: Operator surface maturation

v3 also clarifies that operator UX did not arrive in one blob. `0.3.0` creates the workflow shell, `0.4.0` completes the third instrument and live tabs, `0.5.0` adds launcher/runtime/measurement extensions, `0.11.0` makes Overview a real hub, and `0.12.0` is then a dedicated rendering/layout performance release. Similarly, `0.16.0` widens remote ops and preflight surfaces before `0.17.0` upgrades alarm semantics behind them.

### Pattern: Hardware reality vs design intent

The field-contact story is sharper in v3. `0.19.0` is the first hardware deployment correction wave. `0.20.0` is the transport stabilization marathon. `0.26.0` is then specifically about recovery escalation and preflight semantics, while `0.27.0` is about making the operator-facing runtime non-blocking and singleton-safe. Those are separate chapters, not one generic “deployment hardening” phase.

### Pattern: Audit work becoming a first-class part of history

v2 already made room for the audit corpus, but v3 shows the internal seam inside it. `0.29.0` is the corpus itself: deep audit passes, verification, traces, deep dives, and triage. `0.30.0` is what happens after that evidence exists: build a reality map, rewrite guidance, and correct module/config documentation. That separation matters because the repository is no longer just writing code and then documenting it; it is auditing code, then auditing the docs that explain the code.

### Pattern: Archive/reporting maturity

The archive/reporting story also gets clearer with v3. `0.25.0` is the first professional-artifact push: Parquet v1, CI, and serious reporting. `0.31.0` hardens file-write and persistence invariants. `0.33.0-pre` then begins the Phase 2e archive line proper with Parquet-at-finalize. This makes it easier for a future maintainer to explain why archive semantics did not arrive all at once.

---

## Deprecations timeline

| Version | Item | Deprecated in | Removed in | Notes |
|---|---|---|---|---|
| `0.23.0` | `autosweep_panel` | `2ab7283` | not yet | Explicitly marked deprecated during UI refactor cleanup. |
| `0.30.0` | inaccurate `CLAUDE.md` module/config inventory | `6eb7d3e`, `ddf6459`, `1d71ecc` | not applicable | Governance/documentation deprecation rather than runtime API deprecation. |
| `0.31.0` | silent/loose safety-config assumptions | `88feee5`, `1446f48`, `ebac719`, `1b12b87` | ongoing | Replaced by progressively fail-closed config handling. |
| `0.32.0` | remaining permissive config paths in late 2d line | `89ed3c1` | ongoing | Closure/fail-closed completion pass. |
| `0.32.0` | accidentally committed runtime logs in repo | `f4c256f` | `f4c256f` | Operational hygiene cleanup. |

---

## Breaking changes timeline

| Version | Change | Commit | Affects | Migration |
|---|---|---|---|---|
| `0.9.0` | `Reading.instrument_id` becomes first-class and required | `61dca77` | drivers, storage, consumers | Ensure every driver populates `instrument_id`; update downstream assumptions. |
| `0.17.0` | alarm engine semantics shift to alarm v2 | `88357b8`, `046ab6f`, `3f86b42`, `8070b2d` | engine, GUI, operators, config authors | Migrate operator expectations and config semantics to v2 alarm behavior. |
| `0.19.0` | Keithley constant-power control moves host-side | `94ec2b6` | Keithley runtime behavior | Review assumptions about TSP-side control ownership. |
| `0.20.0` | GPIB transport behavior rewritten around sequential/persistent sessions | `946b454`, `7efb8b7` | transport layer | Treat old open-per-query assumptions as obsolete. |
| `0.23.0` | UI refactor merge changes control surface and default assumptions | `1ec93a6`, `2ab7283` | operators, tests | Update UI expectations and remove reliance on old defaults. |
| `0.24.0` | single-instance locking becomes atomic and mandatory in runtime path | `4df40c3` | launcher/engine startup | Rely on lock semantics instead of ad hoc coexistence. |
| `0.31.0` | safety/alarm config handling becomes materially stricter and more fail-closed | `1446f48`, `ebac719`, `1b12b87` | config authors | Invalid or loosely typed configs no longer limp through startup. |
| `0.32.0` | fail-closed completion tightens remaining config paths | `89ed3c1` | deployment config authors | Validate config more carefully before startup. |

---

## Operator-facing changes highlights

### Version 0.1.0
- No direct operator surface yet; this is infrastructure birth.

### Version 0.2.0
- First live temperature GUI and first visible Keithley integration appear.

### Version 0.3.0
- Engine/GUI entry points, experiments, notifications, and web monitoring become real.

### Version 0.4.0
- All main tabs go live and Russian docs/manual arrive alongside the third instrument.

### Version 0.5.0
- Launcher, dual-channel/runtime helpers, conductivity chain, and connection settings appear.

### Version 0.6.0
- Operators get cooldown prediction, overview/dashboard growth, XLSX export, and disk awareness.

### Version 0.7.0
- See per-version section.

### Version 0.8.0
- Mostly fewer dangerous edge cases; this is a trust-building fix release.

### Version 0.9.0
- Less visible, but deployment behavior and data identity become more trustworthy.

### Version 0.10.0
- See per-version section.

### Version 0.11.0
- Overview becomes a real operator hub and shift handover becomes structured.

### Version 0.12.0
- Overview readability and performance improve materially under live load.

### Version 0.13.0
- Calibration becomes a real, visible workflow.

### Version 0.14.0
- Experiments get named phases, automatic logs, and automatic reports.

### Version 0.15.0
- First explicit “lab-usable release” marker.

### Version 0.16.0
- Read-only web monitoring, Telegram v2, and pre-flight checks widen remote operability.

### Version 0.17.0
- Alarm behavior and alarm UI both change materially under alarm v2.

### Version 0.18.0
- Headless tray-only monitoring appears; some painful regressions disappear.

### Version 0.19.0
- Real hardware behavior gets corrected; pressure and Keithley interaction become more trustworthy.

### Version 0.20.0
- Operators mostly notice that GPIB polling behaves better and GUI/ZMQ separation is more robust.

### Version 0.21.0
- Diagnostics and vacuum-trend surfaces arrive; Keithley safety is deeper.

### Version 0.22.0
- Mostly invisible correctness deepening, but it improves trust.

### Version 0.23.0
- UI refactor changes the control surface; some risky controls are removed.

### Version 0.24.0
- Single-instance protection, command routing, and history behavior become more reliable.

### Version 0.25.0
- Parquet appears in archive artifacts and reports look professional.

### Version 0.26.0
- Transport hangs and preflight false-blocks become less painful.

### Version 0.27.0
- GUI/launcher feel less blocking and more deployment-safe.

### Version 0.28.0
- Mostly hardening-prep, plus a final overview preset rename.

### Version 0.29.0
- Little direct operator change, but this is the evidence base for later hardening.

### Version 0.30.0
- Mostly invisible; valuable to maintainers rather than operators.

### Version 0.31.0
- Operators mostly notice fewer invisible integrity and safety failure modes.

### Version 0.32.0
- Stricter startup/config behavior and late hardening closure.

### Version 0.33.0-pre
- Archive output expands again via Parquet finalize export.

---

## Open questions

- Is `0.15.0` still the best number for the “first lab-usable release”, or should the eventual polished changelog renumber that boundary now that the old tag no longer anchors anything?
- Should the final polished changelog keep `0.10.0` as a one-commit RC-merge release, or absorb it into `0.11.0` for readability? v3 keeps it because it is historically real, but a human-facing changelog might compress it.
- Are the upload/task snapshot commits worth surfacing explicitly in the polished changelog at all, or should they disappear into neighboring narrative paragraphs?
- Should `0.20.0` stay unsplit in the final changelog, or would a human-facing audience benefit from separating GPIB stabilization from ZMQ isolation even though v3 judged them one reliability story?
- Does the final public changelog need both `0.29.0 Audit Corpus` and `0.30.0 Reality Map and Documentation Reconciliation`, or should the public artifact compress them into one “audit and documentation reconciliation” chapter while this research doc keeps them distinct?
- Should the current line remain explicitly pre-release (`0.33.0-pre`) until Tier 1 fixes and GUI branch integration land?

---

## Chronological appendix

All 205 first-parent commits on `master`, assigned to the proposed v3 version scheme.

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
| `77638b0` | 2026-03-14T03:40:26+03:00 | Operator launcher, SQLite thread-safety fix, aiohttp dependency | `0.5.0` |
| `dabce60` | 2026-03-14T03:56:52+03:00 | Keithley smua+smub, Telegram bot commands, portable deployment | `0.5.0` |
| `2f31378` | 2026-03-14T04:07:59+03:00 | Keithley control panel + thermal conductivity chain measurement | `0.5.0` |
| `84b01a7` | 2026-03-14T04:27:20+03:00 | Steady-state predictor + auto-sweep measurement panel | `0.5.0` |
| `b2b4d97` | 2026-03-14T05:02:57+03:00 | Channel manager + instrument connection settings UI | `0.5.0` |
| `603a472` | 2026-03-14T13:29:44+03:00 | Safety architecture: SafetyManager, SafetyBroker, fail-on-silence | `0.6.0` |
| `941d5e3` | 2026-03-14T16:31:42+03:00 | Code review: 13 fixes — token revocation, safety, thread-safety, tests | `0.6.0` |
| `99df7eb` | 2026-03-14T17:20:03+03:00 | Update CLAUDE.md and README.md to current project state | `0.6.0` |
| `3f4b8fa` | 2026-03-14T17:40:40+03:00 | Add files via upload | `0.6.0` |
| `40b4ffb` | 2026-03-14T17:56:34+03:00 | Add files via upload | `0.6.0` |
| `efe16d3` | 2026-03-14T18:12:48+03:00 | Add files via upload | `0.6.0` |
| `dc5f3c6` | 2026-03-14T18:13:22+03:00 | Add files via upload | `0.6.0` |
| `a8e8bbf` | 2026-03-14T18:18:02+03:00 | SAFETY: persistence-first ordering — disk before subscribers | `0.6.0` |
| `9217489` | 2026-03-14T18:49:09+03:00 | Cooldown predictor integration: library refactor, service, GUI, tests | `0.7.0` |
| `dd2dd2c` | 2026-03-14T18:59:53+03:00 | Update CLAUDE.md and README.md: cooldown integration, persistence-first, stats | `0.7.0` |
| `4dca478` | 2026-03-14T19:13:02+03:00 | Add files via upload | `0.7.0` |
| `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs | `0.7.0` |
| `7d8cc1f` | 2026-03-14T20:08:19+03:00 | Update CLAUDE.md and README.md: overview tab, XLSX, DiskMonitor, stats | `0.7.0` |
| `68324c2` | 2026-03-14T20:26:27+03:00 | Add files via upload | `0.7.0` |
| `9390419` | 2026-03-14T22:53:45+03:00 | Add files via upload | `0.7.0` |
| `e9a538f` | 2026-03-14T23:17:09+03:00 | SAFETY: 14 audit fixes — FAULT_LATCHED latch, status checks, heartbeat | `0.8.0` |
| `678ff50` | 2026-03-15T02:25:13+03:00 | Add files via upload | `0.8.0` |
| `1bd6c4e` | 2026-03-15T02:39:36+03:00 | P0: 5 critical fixes — alarm pipeline, safety state, P/V/I limits, latched flag | `0.8.0` |
| `0f8dd59` | 2026-03-15T02:44:01+03:00 | Add files via upload | `0.8.0` |
| `de715dc` | 2026-03-15T03:02:21+03:00 | P1: 8 lab deployment fixes — async ZMQ, REAL timestamps, paths, sessions | `0.9.0` |
| `8d146bc` | 2026-03-15T03:08:22+03:00 | Add files via upload | `0.9.0` |
| `61dca77` | 2026-03-15T03:48:26+03:00 | BREAKING: instrument_id is now a first-class field on Reading dataclass | `0.9.0` |
| `9d48c41` | 2026-03-15T15:58:53+03:00 | Add files via upload | `0.9.0` |
| `2afdbc1` | 2026-03-15T16:42:06+03:00 | Add files via upload | `0.9.0` |
| `0078d57` | 2026-03-15T18:02:34+03:00 | Add files via upload | `0.9.0` |
| `dc2ea6a` | 2026-03-17T15:33:46+03:00 | Merge CRYODAQ-CODEX RC into master (v0.11.0-rc1) | `0.10.0` |
| `29652a2` | 2026-03-17T16:00:30+03:00 | chore: delete merged branches, ignore .claude/ directory | `0.11.0` |
| `cdbba6c` | 2026-03-17T16:49:26+03:00 | fix: restore MainWindow menu in launcher, add --mock flag | `0.11.0` |
| `b6ddb4e` | 2026-03-17T17:03:03+03:00 | feat: dashboard hub — Keithley quick-actions, quick log, experiment status on Overview | `0.11.0` |
| `f910c40` | 2026-03-17T17:14:25+03:00 | feat: structured shift handover — start, periodic prompts, end summary | `0.11.0` |
| `3dea162` | 2026-03-17T17:40:09+03:00 | refactor: two-column Overview layout, move ExperimentWorkspace to separate tab | `0.12.0` |
| `a23ab92` | 2026-03-17T17:53:15+03:00 | fix: Overview — readable time axis, 8-per-row temp cards by instrument, scrollable panel | `0.12.0` |
| `dd663ae` | 2026-03-17T18:15:42+03:00 | fix: Overview layout — full-width temp cards, graph+info splitter | `0.12.0` |
| `a38154a` | 2026-03-17T18:27:37+03:00 | perf: async ZMQ polling in Overview widgets to eliminate UI lag | `0.12.0` |
| `212e299` | 2026-03-17T18:33:38+03:00 | perf: throttle plot updates, optimize pyqtgraph rendering, reduce UI work per reading | `0.12.0` |
| `f4cb917` | 2026-03-17T18:51:26+03:00 | refactor: Overview — cards on top, synced temp+pressure graphs, clickable channel toggle | `0.12.0` |
| `c848393` | 2026-03-17T19:00:51+03:00 | fix: dynamic temp cards, compact experiment form, unified button colors | `0.12.0` |
| `81c5a1d` | 2026-03-17T19:12:17+03:00 | fix: tray icon duplicate, post-P0 audit fixes | `0.12.0` |
| `2136623` | 2026-03-17T19:16:46+03:00 | chore: remove dead PressureStrip class and unused imports | `0.12.0` |
| `81ef8a6` | 2026-03-17T19:42:06+03:00 | feat: continuous SRDG acquisition during calibration experiments | `0.13.0` |
| `e694d2d` | 2026-03-17T19:52:16+03:00 | feat: calibration v2 post-run pipeline — extract, downsample, breakpoints, fit | `0.13.0` |
| `38aca4f` | 2026-03-17T19:57:30+03:00 | feat: calibration v2 GUI — three-mode panel with coverage and auto-fit | `0.13.0` |
| `98a5951` | 2026-03-17T20:11:32+03:00 | chore: calibration v2 cleanup — remove legacy sessions, update docs | `0.13.0` |
| `bc41589` | 2026-03-17T20:36:54+03:00 | fix: UX polish — DateAxisItem on all graphs, Russian labels, layout fixes | `0.14.0` |
| `aad5eab` | 2026-03-17T20:41:48+03:00 | feat: experiment phase tracking — preparation through teardown | `0.14.0` |
| `d8421e6` | 2026-03-17T20:53:12+03:00 | feat: auto-log system events, auto-generate report on finalize | `0.14.0` |
| `7f0e5d1` | 2026-03-17T21:11:40+03:00 | fix: P1 audit — phase widget, empty states, auto-entry styling, DateAxisItem everywhere | `0.14.0` |
| `3b6a175` | 2026-03-17T22:06:49+03:00 | feat: calibration start button, full docs sync to Russian | `0.14.0` |
| `c22eca9` | 2026-03-18T00:10:28+03:00 | release: v0.12.0 — first production release | `0.15.0` |
| `7ee15de` | 2026-03-18T00:52:04+03:00 | feat: web dashboard — read-only monitoring page with auto-refresh | `0.16.0` |
| `e553f11` | 2026-03-18T00:58:19+03:00 | feat: telegram bot v2 — /status, /log, /temps, /phase, escalation chain | `0.16.0` |
| `ae70158` | 2026-03-18T01:00:12+03:00 | feat: pre-flight checklist before experiment start | `0.16.0` |
| `5678d96` | 2026-03-18T01:04:28+03:00 | feat: experiment form auto-fill with history and name suggestion | `0.16.0` |
| `4405348` | 2026-03-18T01:30:25+03:00 | fix: telegram bot polling debug + ensure task started | `0.16.0` |
| `88357b8` | 2026-03-18T02:16:12+03:00 | feat: alarm v2 foundation — RateEstimator and ChannelStateTracker | `0.17.0` |
| `046ab6f` | 2026-03-18T02:22:14+03:00 | feat: alarm v2 evaluator — composite, rate, threshold, stale checks | `0.17.0` |
| `3f86b42` | 2026-03-18T02:26:02+03:00 | feat: alarm v2 providers and config parser | `0.17.0` |
| `8070b2d` | 2026-03-18T02:30:59+03:00 | feat: alarm v2 integration in engine with phase-dependent evaluation | `0.17.0` |
| `ac404db` | 2026-03-18T02:32:02+03:00 | fix: remove undercool_shield false interlock, phase-gate detector_warmup | `0.17.0` |
| `d3b58bd` | 2026-03-18T02:38:33+03:00 | feat: alarm v2 GUI panel and documentation | `0.17.0` |
| `92e1369` | 2026-03-18T10:45:37+03:00 | fix: memory leak — broadcast task explosion, rate estimator trim, history cap | `0.18.0` |
| `e601ca9` | 2026-03-18T10:55:32+03:00 | fix: empty plots after GUI reconnect, experiment status wrong key | `0.18.0` |
| `c7ae2ed` | 2026-03-18T10:59:53+03:00 | feat: tray-only mode for headless engine monitoring | `0.18.0` |
| `d7c843f` | 2026-03-18T17:12:19+03:00 | fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off, alarms, pressure card, docs | `0.19.0` |
| `4f717a5` | 2026-03-18T17:23:52+03:00 | fix: keithley source-off NaN → SQLite NOT NULL crash | `0.19.0` |
| `8605a52` | 2026-03-19T11:14:49+03:00 | fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN? | `0.19.0` |
| `d0c40de` | 2026-03-19T12:19:10+03:00 | fix: thyracont V1 pressure formula, keithley output float parse, pressure exponent format | `0.19.0` |
| `f3e62f5` | 2026-03-19T12:36:06+03:00 | fix: thyracont V1 value is 6 digits (4 mantissa + 2 exponent), formula (ABCD/1000)*10^(EF-20) | `0.19.0` |
| `d94e361` | 2026-03-19T12:41:31+03:00 | fix: VISA bus lock to prevent -420 Query UNTERMINATED race | `0.19.0` |
| `552f679` | 2026-03-19T12:58:57+03:00 | fix: rate check scoped to critical channels only, disconnected sensors excluded | `0.19.0` |
| `94ec2b6` | 2026-03-19T13:15:31+03:00 | refactor: keithley P=const host-side control loop, remove blocking TSP script | `0.19.0` |
| `1b5c099` | 2026-03-19T13:36:07+03:00 | feat: keithley live P_target update + fix stop button | `0.19.0` |
| `5bc640c` | 2026-03-19T14:05:52+03:00 | fix: GPIB bus lock covers open_resource() and close(), not just query/write | `0.20.0` |
| `a0e9678` | 2026-03-19T14:13:43+03:00 | fix: GPIB bus lock covers open_resource + verify query atomically | `0.20.0` |
| `bb59488` | 2026-03-19T14:29:07+03:00 | fix: GPIB open-per-query + IFC bus reset on timeout | `0.20.0` |
| `946b454` | 2026-03-19T14:50:20+03:00 | refactor: GPIB sequential polling — single task per bus, no parallel access | `0.20.0` |
| `fd229e9` | 2026-03-19T14:58:54+03:00 | fix: GPIB clear() before every query + IFC recovery on timeout | `0.20.0` |
| `31c4bae` | 2026-03-19T15:26:17+03:00 | fix: GPIB remove clear() from hot path, add write-delay-read | `0.20.0` |
| `5448f08` | 2026-03-19T16:00:56+03:00 | fix: GPIB KRDG? command + GUI visual fixes + ZMQ crash resilience | `0.20.0` |
| `7efb8b7` | 2026-03-19T16:21:12+03:00 | refactor: GPIB persistent sessions — LabVIEW-style open-once scheme | `0.20.0` |
| `f64d981` | 2026-03-19T16:41:46+03:00 | feat: isolate ZMQ into subprocess — GUI never imports zmq | `0.20.0` |
| `856ad19` | 2026-03-20T13:04:34+03:00 | feat: Keithley safety (slew rate, compliance) + ZMQ subprocess hardening | `0.21.0` |
| `757f59e` | 2026-03-20T13:22:39+03:00 | feat: SensorDiagnosticsEngine — backend + 20 unit tests (Stage 1) | `0.21.0` |
| `6eb8dfe` | 2026-03-20T13:33:19+03:00 | feat: SensorDiagnostics — engine integration + config (Stage 2) | `0.21.0` |
| `b21bca1` | 2026-03-20T13:45:37+03:00 | feat: SensorDiagnostics GUI panel + status bar summary (Stage 3) | `0.21.0` |
| `5d7fe2b` | 2026-03-20T13:56:47+03:00 | feat: VacuumTrendPredictor — backend + 20 unit tests (Stage 1) | `0.21.0` |
| `c1b9eb5` | 2026-03-20T14:30:15+03:00 | feat: VacuumTrendPredictor — engine integration + config (Stage 2) | `0.21.0` |
| `50e30e3` | 2026-03-20T14:39:47+03:00 | feat: VacuumTrendPredictor GUI panel on Analytics tab (Stage 3) | `0.21.0` |
| `afabfe5` | 2026-03-20T16:03:45+03:00 | fix: ZMQ datetime serialization + REP socket stuck on serialization error | `0.22.0` |
| `6ef43df` | 2026-03-20T20:12:35+03:00 | feat: Phase 2 safety hardening — tests + bugfixes + LakeShore RDGST? | `0.22.0` |
| `bbb5809` | 2026-03-20T20:42:47+03:00 | feat: Phase 3 — safety correctness, reliability, phase detector | `0.22.0` |
| `4b52de8` | 2026-03-20T21:16:28+03:00 | fix: deep review — 2 bugs fixed, 2 tests added | `0.22.0` |
| `10d4d76` | 2026-03-20T22:39:17+03:00 | fix(audit): 6 bugs — safety race, SQLite shutdown, Inf filter, phase reset, GPIB leak, deque cap | `0.22.0` |
| `af94285` | 2026-03-21T00:39:25+03:00 | fix(ui): CSV BOM, sensor diag stretch, calibration stretch, reports on, adaptive liveness | `0.22.0` |
| `1ec93a6` | 2026-03-21T02:39:16+03:00 | merge: feature/ui-refactor | `0.23.0` |
| `c427247` | 2026-03-21T02:54:30+03:00 | docs: update all documentation, changelog, and version for v0.13.0 | `0.23.0` |
| `a2f4bcd` | 2026-03-21T12:01:31+03:00 | fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect | `0.23.0` |
| `1670bbe` | 2026-03-21T12:01:44+03:00 | fix(ui): card toggle signals, history load on window change, axis alignment, channel refresh | `0.23.0` |
| `2ab7283` | 2026-03-21T12:01:52+03:00 | chore: fix default channels, web version, deprecate autosweep_panel | `0.23.0` |
| `dc84f0c` | 2026-03-21T12:35:27+03:00 | fix(ui): remove QuickStart buttons from overview (caused FAULT with P=0) | `0.23.0` |
| `1dd7405` | 2026-03-21T12:35:37+03:00 | feat(ui): rename Keithley tab, add time window buttons, forecast zone | `0.23.0` |
| `f08e6bb` | 2026-03-21T12:35:47+03:00 | fix: audit wave 3 — build_ensemble guard, launcher ping, phase gap, RDGST, docs | `0.23.0` |
| `9e2ce5b` | 2026-03-21T15:20:53+03:00 | merge: final-batch — single-instance, ML forecast, flight recorder, driver fixes | `0.24.0` |
| `7618031` | 2026-03-21T16:01:14+03:00 | fix(telegram): natural channel sort, compact text, pressure log-scale Y limits | `0.24.0` |
| `4df40c3` | 2026-03-21T16:15:04+03:00 | fix(critical): atomic single-instance lock via O_CREAT|O_EXCL | `0.24.0` |
| `0603110` | 2026-03-21T16:15:13+03:00 | fix(zmq): correlation ID for command-reply routing | `0.24.0` |
| `9942da1` | 2026-03-21T16:15:23+03:00 | fix(ui): proportional history load, overview plot sync, CSV BOM | `0.24.0` |
| `6d39a08` | 2026-03-21T17:34:43+03:00 | fix(critical): move experiment I/O to thread, remove double report generation | `0.24.0` |
| `45ae750` | 2026-03-21T17:39:02+03:00 | fix(zmq): Future-per-request dispatcher with dedicated reply consumer | `0.24.0` |
| `031491a` | 2026-03-21T17:42:38+03:00 | fix(ui): "Всё"→"Сутки", pass channels to history, poll_readings resilience | `0.24.0` |
| `dd42632` | 2026-03-22T00:25:10+03:00 | fix(ui): snap graph X-axis to data start across all 7 panels | `0.24.0` |
| `0fdc507` | 2026-03-22T16:11:11+03:00 | merge: audit-v2 fixes (29 defects, 9 commits) | `0.25.0` |
| `fc1c61b` | 2026-03-22T16:35:11+03:00 | feat(storage): Parquet experiment archive — write readings.parquet alongside CSV on finalize | `0.25.0` |
| `ccf98c9` | 2026-03-22T16:44:11+03:00 | Add CI workflow for CryoDAQ with testing and linting | `0.25.0` |
| `f0c68c6` | 2026-03-22T17:28:38+03:00 | feat(archive): Parquet column in table, human-readable artifacts, parquet read fix | `0.25.0` |
| `423c6d5` | 2026-03-22T19:05:13+03:00 | fix(archive): inclusive end-date filter, add end time column | `0.25.0` |
| `8dc07f7` | 2026-03-22T19:18:57+03:00 | feat(reporting): professional human-readable reports for all experiment types | `0.25.0` |
| `a066cd7` | 2026-03-22T20:51:11+03:00 | feat(reporting): ГОСТ Р 2.105-2019 formatting, all graphs in all reports | `0.25.0` |
| `b7265bb` | 2026-03-22T21:23:13+03:00 | fix(reporting): multi-channel graphs, black headings, smart page breaks | `0.25.0` |
| `29d2215` | 2026-03-23T00:37:57+03:00 | fix: audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring | `0.25.0` |
| `ab57e01` | 2026-03-23T14:59:57+03:00 | fix(gpib): auto-recovery from hung instruments — clear bus on timeout, preventive clear | `0.26.0` |
| `ea5a8da` | 2026-03-23T15:15:20+03:00 | fix(gpib): IFC bus reset, enable unaddressing, escalating recovery | `0.26.0` |
| `86e8e8c` | 2026-03-23T15:32:17+03:00 | fix(preflight): sensor health is warning not error | `0.26.0` |
| `c10e617` | 2026-03-24T12:50:45+03:00 | fix(scheduler): standalone instrument disconnect+reconnect on consecutive errors | `0.26.0` |
| `dfd6021` | 2026-03-24T12:55:26+03:00 | fix(preflight): restore encoding + sensor health warning not error | `0.26.0` |
| `8bac038` | 2026-03-24T13:10:40+03:00 | fix(gui): non-blocking alarm v2 status poll | `0.27.0` |
| `6d0f5ba` | 2026-03-24T14:08:20+03:00 | fix(gui): bridge heartbeat false kills + launcher blocking send_command | `0.27.0` |
| `bab4d8a` | 2026-03-24T14:15:39+03:00 | feat: single-instance protection for launcher and standalone GUI | `0.27.0` |
| `4eb5f1a` | 2026-03-24T14:27:27+03:00 | fix(gui): launcher bridge health gap + conductivity blocking send_command | `0.27.0` |
| `3c46dfb` | 2026-03-24T14:41:09+03:00 | fix(gui): keithley spinbox debounce + non-blocking live update | `0.27.0` |
| `e7d4fc5` | 2026-03-24T14:48:54+03:00 | fix(gui): experiment workspace 1080p layout — phase bar + passport forms | `0.27.0` |
| `f47762d` | 2026-03-24T15:02:22+03:00 | fix: launcher non-blocking engine restart + deployment hardening | `0.27.0` |
| `f217427` | 2026-03-25T12:59:26+03:00 | fix: shift modal re-entrancy + engine --force PermissionError | `0.27.0` |
| `9676165` | 2026-03-31T03:17:03+03:00 | fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking | `0.28.0` |
| `9feaf3e` | 2026-04-01T03:57:02+03:00 | fix: audit - GUI non-blocking send_command + dead code cleanup | `0.28.0` |
| `a60abc0` | 2026-04-08T16:58:28+03:00 | fix: Phase 1 pre-deployment — unblock PyInstaller build | `0.28.0` |
| `0333e52` | 2026-04-08T17:47:20+03:00 | fix: Phase 2a safety hardening — close 4 HIGH findings | `0.28.0` |
| `8a24ead` | 2026-04-08T21:17:52+03:00 | fix: Phase 2b observability & resilience — close 8 MEDIUM findings | `0.28.0` |
| `b185fd3` | 2026-04-08T21:58:00+03:00 | fix: Phase 2c final hardening — close 8 findings before Phase 3 | `0.28.0` |
| `1698150` | 2026-04-08T22:16:31+03:00 | ui: replace Overview "Сутки" preset with "Всё" | `0.28.0` |
| `380df96` | 2026-04-09T00:45:35+03:00 | audit: deep audit pass (CC) post-2c | `0.29.0` |
| `fd99631` | 2026-04-09T00:59:45+03:00 | audit: deep audit pass (Codex overnight) post-2c | `0.29.0` |
| `fd8c8bf` | 2026-04-09T02:23:44+03:00 | chore: gitignore local audit artifacts (DEEP_AUDIT_*.md, graphify-out/) | `0.29.0` |
| `847095c` | 2026-04-09T02:39:32+03:00 | audit: cherry-pick hardening pass document from feat/ui-phase-1 | `0.29.0` |
| `5d618db` | 2026-04-09T02:58:53+03:00 | audit: verification pass - re-check 5 HIGH findings from hardening pass | `0.29.0` |
| `10667df` | 2026-04-09T03:07:45+03:00 | audit: SafetyManager exhaustive FSM analysis | `0.29.0` |
| `31dbbe8` | 2026-04-09T03:14:45+03:00 | audit: persistence-first invariant exhaustive trace | `0.29.0` |
| `3e20e86` | 2026-04-09T03:26:43+03:00 | audit: driver layer fault injection scenarios | `0.29.0` |
| `916fae4` | 2026-04-09T03:54:17+03:00 | audit: full dependency CVE sweep with version verification | `0.29.0` |
| `a108519` | 2026-04-09T04:01:17+03:00 | audit: reporting + analytics + plugins deep dive | `0.29.0` |
| `24b928d` | 2026-04-09T04:09:48+03:00 | audit: configuration files security and consistency audit | `0.29.0` |
| `7aaeb2b` | 2026-04-09T04:20:34+03:00 | audit: master triage synthesis of all audit documents | `0.29.0` |
| `995f7bc` | 2026-04-12T23:25:19+03:00 | discovery: build doc-vs-code reality map (CC + Codex review) | `0.30.0` |
| `6eb7d3e` | 2026-04-13T01:04:14+03:00 | docs: rewrite cryodaq-team-lead skill against current code reality | `0.30.0` |
| `ddf6459` | 2026-04-13T16:01:32+03:00 | docs(CLAUDE.md): add missing config files to list | `0.30.0` |
| `1d71ecc` | 2026-04-13T16:09:28+03:00 | docs(CLAUDE.md): expand module index, fix safety FSM and invariants | `0.30.0` |
| `88feee5` | 2026-04-13T16:27:03+03:00 | phase-2d-a1: web XSS + SafetyManager hardening + T regression | `0.31.0` |
| `1446f48` | 2026-04-13T17:18:12+03:00 | phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class | `0.31.0` |
| `ebac719` | 2026-04-13T17:44:12+03:00 | phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError | `0.31.0` |
| `1b12b87` | 2026-04-13T18:07:45+03:00 | phase-2d-a2: alarm config hardening + safety->experiment bridge | `0.31.0` |
| `e068cbf` | 2026-04-13T20:53:40+03:00 | phase-2d-a2-fix: close Codex findings on 1b12b87 | `0.31.0` |
| `d3abee7` | 2026-04-13T21:50:34+03:00 | phase-2d-b1: atomic file writes + WAL verification | `0.31.0` |
| `5cf369e` | 2026-04-13T22:08:49+03:00 | phase-2d-a8-followup: shield post-fault cancellation paths | `0.31.0` |
| `104a268` | 2026-04-13T22:30:24+03:00 | phase-2d-b2: persistence integrity | `0.31.0` |
| `21e9c40` | 2026-04-13T22:46:17+03:00 | phase-2d-b2-fix: drop NaN-valued statuses from persist set | `0.31.0` |
| `23929ca` | 2026-04-13T23:22:40+03:00 | phase-2d: checkpoint — Block A+B complete, update PROJECT_STATUS | `0.31.0` |
| `efe6b49` | 2026-04-14T01:14:35+03:00 | chore: ruff --fix accumulated lint debt | `0.32.0` |
| `f4c256f` | 2026-04-14T01:14:55+03:00 | chore: remove accidentally committed logs/, add to .gitignore | `0.32.0` |
| `74f6d21` | 2026-04-14T01:44:41+03:00 | phase-2d-jules-r2-fix: close ordering and state mutation gaps | `0.32.0` |
| `89ed3c1` | 2026-04-14T02:18:37+03:00 | phase-2d-c1: config fail-closed completion + cleanup | `0.32.0` |
| `0cd8a94` | 2026-04-14T02:36:54+03:00 | phase-2d: declare COMPLETE, open Phase 2e | `0.32.0` |
| `445c056` | 2026-04-14T02:55:31+03:00 | phase-2e-parquet-1: experiment archive via Parquet at finalize | `0.33.0-pre` |
| `855870b` | 2026-04-14T03:26:45+03:00 | docs(audits): add BRANCH_INVENTORY.md for three-track review input | `0.33.0-pre` |
| `5ad0156` | 2026-04-14T03:31:22+03:00 | docs(audits): add repo inventory, dead code scan, and CC findings summary | `0.33.0-pre` |
| `1c75967` | 2026-04-14T03:54:44+03:00 | docs/audits: Codex round 2 extended semantic audit | `0.33.0-pre` |
| `66f9870` | 2026-04-14T03:56:15+03:00 | docs/audits: CC round 2 extended inventory | `0.33.0-pre` |
| `6535c9a` | 2026-04-14T04:15:41+03:00 | docs/audits: record remote branch cleanup | `0.33.0-pre` |
| `88c308c` | 2026-04-14T04:19:11+03:00 | docs: update PROJECT_STATUS.md numbers for round 2 audit state | `0.33.0-pre` |
| `5b3ca29` | 2026-04-14T04:19:26+03:00 | chore: commit historical pre-Phase-2c audit artifacts | `0.33.0-pre` |

---

## Confidence ratings

- **Commit coverage:** HIGH — all 205 first-parent commits were assigned to a v3 version with no gaps or overlaps.
- **Clustering accuracy:** MEDIUM — the major splits are strongly justified, but some upload/task snapshots still require contextual inference.
- **Version count calibration:** HIGH — this pass had no target count; `33` is simply where the independently re-checked boundaries landed.
- **Boundary placement:** MEDIUM — the largest splits are clear, but a human writing the final public changelog could still choose to compress a few single-merge or short stabilization releases for readability.
- **Version name choices:** MEDIUM — the names are intentionally specific and useful, but a final public changelog may simplify some of them.
- **Context explanations:** HIGH — the why/how narratives are grounded in the actual commit sequences and the v1/v2 prior research.
- **Breaking change detection:** MEDIUM — the major contract shifts are captured, but some semantic behavior shifts may be better expressed as “Changed” than “Breaking” in the final polished artifact.

---

## Differences from v2

### Version count

- v1: 10
- v2: 25
- v3: 33

### What split from v2

- v2 `0.4.0` -> v3 `0.4.0` + `0.5.0`
- v2 `0.7.0` -> v3 `0.8.0` + `0.9.0`
- v2 `0.9.0` -> v3 `0.11.0` + `0.12.0`
- v2 `0.13.0` -> v3 `0.16.0` + `0.17.0`
- v2 `0.17.0` -> v3 `0.21.0` + `0.22.0`
- v2 `0.21.0` -> v3 `0.26.0` + `0.27.0`
- v2 `0.23.0` -> v3 `0.29.0` + `0.30.0`
- v2 `0.25.0-pre` -> v3 `0.32.0` + `0.33.0-pre`

### What merged from v2

- None. v3 did not find any v2 pair that was genuinely over-split.

### What stayed identical from v2

- v2 `0.1.0` -> v3 `0.1.0`: Initial Scaffolding (boundary unchanged)
- v2 `0.2.0` -> v3 `0.2.0`: Instrument Foundations (boundary unchanged)
- v2 `0.3.0` -> v3 `0.3.0`: Workflow Skeleton (boundary unchanged)
- v2 `0.6.0` -> v3 `0.6.0`: Safety Architecture (boundary unchanged)
- v2 `0.7.0` -> v3 `0.7.0`: Cooldown and Overview Intelligence (boundary unchanged)
- v2 `0.10.0` -> v3 `0.10.0`: RC Merge (boundary unchanged)
- v2 `0.13.0` -> v3 `0.13.0`: Calibration V2 (boundary unchanged)
- v2 `0.14.0` -> v3 `0.14.0`: Phased Experiments and Auto Reports (boundary unchanged)
- v2 `0.15.0` -> v3 `0.15.0`: First Lab-Usable Release (boundary unchanged)
- v2 `0.18.0` -> v3 `0.18.0`: Post-Release Stabilization (boundary unchanged)
- v2 `0.19.0` -> v3 `0.19.0`: First Hardware Deployment (boundary unchanged)
- v2 `0.20.0` -> v3 `0.20.0`: GPIB Stabilization and ZMQ Isolation (boundary unchanged)
- v2 `0.23.0` -> v3 `0.23.0`: UI Refactor Merge and Post-Merge Cleanup (boundary unchanged)
- v2 `0.24.0` -> v3 `0.24.0`: Final-Batch Integration (boundary unchanged)
- v2 `0.25.0` -> v3 `0.25.0`: Audit-v2, Parquet v1, and Reporting (boundary unchanged)
- v2 `0.28.0` -> v3 `0.28.0`: Pre-Phase-2d Hardening Prep (boundary unchanged)
- v2 `0.31.0` -> v3 `0.31.0`: Phase 2d Safety and Persistence (boundary unchanged)

### Rationale for v3 count

The biggest change from v2 is not philosophical; it is structural honesty. Once the target count disappeared, a handful of v2 versions stopped looking like single releases and started looking like two adjacent releases that had been kept together mostly because they fit within the old target band. The clearest examples were the two halves of v2 `0.4.0`, the split between remote ops/preflight and alarm v2 inside v2 `0.13.0`, the analytics-vs-safety seam inside v2 `0.17.0`, the recovery-vs-non-blocking seam inside v2 `0.21.0`, and the closure-vs-next-line seam inside v2 `0.25.0-pre`.

The move from 25 to 33 does not mean v2 was bad. v2 did the hard work of proving that the history could be reconstructed semantically at all, and most of its version boundaries held up. v3 is a refinement pass, not a repudiation. The unchanged versions listed above are evidence of that: the foundational cuts, the RC merge, calibration v2, phased experiments, first release, first hardware deployment, the GPIB marathon, final-batch integration, audit-v2/reporting, pre-2d prep, and Phase 2d A+B all remained intact.

Would a further v4 split add value? Probably not much. At this point the remaining candidates are mostly questions of public readability rather than hidden historical structure. In other words, v3 feels much closer to the natural grain of the history than v2 did. A future human writer can still compress versions for the final public changelog, but they should not need to discover new major boundaries from scratch.
