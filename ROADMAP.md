# CryoDAQ — Feature Roadmap

> **Living document.** Updated 2026-07-19 for the software-side pre-lab
> readiness campaign. `CHANGELOG.md`
> is the authoritative shipped-history record; this file is only the forward
> feature map.
>
> **Current frontier:** v0.64.1 is shipped as the immutable `v0.64.1` tag, and the
> release train v0.58.0 -> v0.64.0 closed the v0.60 Known Limitations backlog.
> The active milestone is to close every safe software-side prerequisite before
> hardware validation: H3/H4 runtime/frozen-build reliability, F35 multi-lab
> extension contracts, and F36 operator-centered product readiness. Fleet-scale
> 100+ sensor / 4K projector presentation is the separate deferred F37.
> Physical gates remain governed by `docs/lab_verification_checklist.md` and
> cannot be closed by simulation.

---

## GUI design-system gate

Every GUI/UI/UX change in every roadmap feature, not only F36, must be both
informative and intentionally beautiful, and must treat
`docs/design-system/` as a co-versioned acceptance contract. Before authoring,
the slice identifies and reads the applicable tokens, rules, components,
patterns, accessibility, performance, and governance specifications. The code
must use canonical tokens/components, Russian operator wording, keyboard and
focus behavior, non-color state cues, explicit stale/disconnected truth, and
the documented frame/startup/memory budgets. A generic LabVIEW-style grid of
default-looking controls or equally weighted boxes fails this gate even when it
is functionally complete; visual hierarchy, proportion, spacing rhythm,
typography, restraint, and a recognisable CryoDAQ identity are required.
The complete existing GUI corpus is in scope: previously token-compliant
generic surfaces are not grandfathered. Each touched surface migrates in its
reviewed slice, and the untouched remainder stays in the canonical enumerated
`docs/design-system/GUI_MIGRATION_INVENTORY.md` backlog under design-system
v4.0.0 rather than being silently called complete.

If reachable production behavior shows that a design-system rule is stale,
the same reviewed slice corrects the canonical rule and its examples/tests;
when a reusable token, component, pattern, or state semantic changes, the slice
also updates design-system versioning and changelog evidence. Legacy GUI code
is not authority for new presentation behavior. A functional test pass or
screenshot alone cannot satisfy this gate.

Backend contracts retain the canonical source states `ok | caution | warning |
fault | stale | disconnected` for compatibility and provenance. Operator
presentation has one attention rung: `warning` is normalized to `caution` and
must use the same wording, icon, color, and counting behavior. Safety colors
are exclusive to safety/status meaning; experiment phase, selection, and
measurement-series identity use non-safety tokens.

---

## Status key

- ✅ **DONE** — shipped and working
- 🔧 **PARTIAL** — useful code exists, but named scope is not fully shipped
- ⬜ **NOT STARTED** — no committed implementation for the named scope
- 🔬 **RESEARCH** — methodology / physics work required before code
- ❌ **RETIRED** — intentionally superseded or folded into another feature

---

## Quick index

| # | Feature | Status | Effort | ROI |
|---|---|---|---|---|
| F1 | Parquet archive wire-up | ✅ DONE (v0.34.0; export path broadened through v0.63.0) | S | H |
| F2 | Debug mode toggle | ✅ DONE (v0.34.0) | S | H |
| F3 | Analytics placeholder widgets -> data wiring | ✅ DONE (W1-W3; F4 folded in) | M | M |
| F4 | Analytics lazy-open snapshot replay | ✅ DONE (folded into F3) | S | M |
| F5 | Engine events -> external webhook | ❌ RETIRED — folded into F31 (v0.54.0) | M | M |
| F6 | Auto-report on experiment finalize | ✅ DONE (v0.34.0) | S | H |
| F7 | Web API readings query extension | ✅ DONE (v0.58.0 REST/readings/history + existing `/ws`; no Parquet stream by design) | L | M |
| F8 | Cooldown ML prediction upgrade | 🔬 RESEARCH | L | M |
| F9 | Thermal conductivity auto-report (TIM) | ❌ RETIRED — existing analyzer/report path is sufficient until a concrete publication need appears | M | H |
| F10 | Sensor diagnostics -> alarm integration | ✅ DONE (v0.41.0) | M | M |
| F11 | Shift handover enrichment | ✅ DONE (v0.34.0; Telegram export deferred) | S | H |
| F12 | Experiment templates UI editor | ⬜ NOT STARTED | M | L |
| F13 | Vacuum leak rate estimator | ✅ DONE (v0.44.0; refined by F-X/v0.51.0 and VacuumGuard v0.64.0) | M | M |
| F14 | Remote command approval (Telegram) | ⬜ NOT STARTED — safety-sensitive, not a lab-verification blocker | M | L |
| F15 | Linux AppImage / `.deb` package | ⬜ NOT STARTED | L | L |
| F16 | Plugin hot-reload SDK + examples | ⬜ NOT STARTED | M | L |
| F17 | SQLite -> Parquet cold-storage rotation | ✅ DONE (v0.61.0 core; v0.63.0 read-side complete; v0.64.0 lifecycle fix) | M | M |
| F18 | CI/CD upgrade | 🔧 PARTIAL (v0.57.0 lint/test repair; v0.58.0 lock drift gate; v0.64.0 ubuntu+windows green) | M | L |
| F19 | F3.W3 experiment_summary enriched content | ✅ DONE (v0.43.0) | S-M | M |
| F20 | Diagnostic alarm notification polish | ✅ DONE (v0.43.0) | S | L |
| F21 | Alarm hysteresis deadband | ✅ DONE (v0.43.0) | S | M |
| F22 | Diagnostic alarm severity escalation | ✅ DONE (v0.43.0) | S | M |
| F23 | RateEstimator measurement timestamp | ✅ DONE (v0.43.0; clock-jump guard v0.59.0/v0.64.0) | S | M |
| F24 | Interlock acknowledge ZMQ command | ✅ DONE (v0.43.0) | S | M |
| F25 | SQLite WAL corruption startup gate | ✅ DONE (v0.43.0; Linux self-heal v0.64.0) | S | M |
| F26 | SQLite WAL gate backport whitelist | ✅ DONE (v0.44.0) | XS | L |
| F27 | Composition photos via Telegram | ✅ DONE (v0.50.0) | L | H |
| F28 | Гемма Live — event-driven operator helper | ✅ DONE (v0.45.0) | L | H |
| F29 | Periodic narrative reports | ✅ DONE (v0.46.x) | S-M | H |
| F30 | Live Query — current-state operator queries | ✅ DONE (v0.47.x) | M | H |
| F31 | Sinks: Markdown note writer + webhook | ✅ DONE (v0.54.0; async/offload fixes v0.55.x) | M | M |
| F32 | Knowledge-base indexer | ✅ DONE (v0.54.0; integration hardening v0.55.x) | M | M |
| F33 | Archive query interface | ✅ DONE (v0.54.0) | M+ | M |
| F34 | GUI chat overlay | ✅ DONE (v0.54.0; unified into knowledge overlay v0.55.6.1) | M | L |
| F35 | ASC hardware extension contract | 🔧 PARTIAL — descriptor persistence/receipt activation, live wire, replay/report parity, descriptor-qualified generic and specialist GUI routing, real-localhost lifecycle, conformance/reference driver, and continuous acquisition-to-display software proof committed; real-Windows frozen-build extension proof open | L | H |
| F36 | Operator-centered control-room surface | 🔧 PARTIAL — backend snapshot production is active; the panoramic dashboard is home and the POD remains an additive shift-summary route; operator, accessibility, performance, ONEDIR, WSL candidate-integration, and physical gates open | L | H |
| F-X | Physical-state alarms — CooldownAlarm + VacuumGuard | ✅ DONE (v0.51.0; SafetyManager opt-in escalation v0.64.0) | M | H |
| F-Y | Diagnostic mode rework | ⬜ NOT STARTED — re-evaluate only after lab data shows a concrete need | M | H |
| F-A | Anomaly detection widget | ❌ RETIRED | M | L |
| F-B | tau-scale formulation | ❌ RETIRED | L | M |
| F-C | Slider integration | ❌ RETIRED | M | L |
| F-D | Physics prior | ❌ RETIRED | L | M |
| F-P1 | Cooldown trajectory overlay (Analytics tab, temperature) | ✅ DONE (v0.52.0; quasi-stationary extension v0.52.2) | S | H |
| F-P2 | Vacuum leak projection overlay (Analytics tab, pressure) | ✅ DONE (v0.52.0) | S/M | H |
| F-P3 | TIM thermal conductivity asymptote (Analytics tab, R_thermal) | ✅ DONE (v0.52.0) | S | H |

Effort: **S** <=200 LOC, **M** 200-600 LOC, **L** >600 LOC.
ROI: **H** immediate operator value, **M** clear but deferred, **L** nice-to-have.

---

## Release train since v0.51.0

- **v0.52.0-v0.52.2:** F-P1/F-P2/F-P3 prediction overlays shipped on the
  Analytics tab; cooldown predictor floor became data-driven for the real
  quasi-stationary base.
- **v0.53.x:** replay mode and replay predictor bootstrap shipped.
- **v0.54.0-v0.55.x:** F31-F34, MultiLine continuous/burst path, channel
  landmarks, legacy replay maps, knowledge-base indexing, PDF/manual loaders,
  GUI overlay lifecycle fixes, and source-label hardening shipped.
- **v0.57.0-v0.60.0:** fail-closed safety edges, REST/IPC hardening,
  NaN-doctrine, authenticated REST writes, path jail, ZMQ size caps, and
  requirements-lock drift gate shipped.
- **v0.61.0-v0.64.0:** cold rotation and hot+cold reads completed,
  TSP watchdog modes (`off | best_effort | required`) shipped, SQLite
  self-heal landed, verified-off discipline closed, and retention no longer
  starves rotation.

The old v0.60 Known Limitations backlog is closed by v0.61.0-v0.64.0:
historical readers now go through the archive layer, cold rotation is enabled
by default, replay/export/calibration/report paths see rotated days, and the
retention/rotation lifecycle bug is fixed.

---

## Current milestone — software-side pre-lab readiness

Before going to the laboratory, complete and independently review every gate
that does not require real Windows hardware, a real instrument, a dummy load,
an independent final element, or an operator in the physical loop:

1. **H3/H4 runtime and packaging closure.** Atomic single-owner periodic-report
   cutover, crash/restart/election evidence, Windows ONEDIR workflow contract,
   instance-lock/lifecycle hardening, clean-SHA full suite, short soak, and the
   longest locally honest soak.
2. **F35 extension foundation.** Registry, narrow capability protocols, stable
   channel descriptors, frozen-build allowlist proof, conformance kit, and a
   passive reference-driver end-to-end proof.
3. **F36 operator product foundation.** One backend-truth snapshot for
   readiness/health/attention/experiment/data integrity, preflight and safety
   recovery UX, passive infrastructure health, ordinary-laboratory performance,
   durable review/support evidence, and design-system-governed navigation.
4. **Evidence packaging.** Exact real-Windows and physical-lab procedures,
   expected artifacts, pass/fail thresholds, rollback/abort conditions, and
   support-bundle capture must be ready before travel to the stand.

The irreducible hardware milestone then remains:

1. SQLite shim and startup gate on the laboratory Ubuntu PC.
2. H5 / ZMQ idle-death check on the current laboratory PC.
3. LakeShore runtime calibration on real hardware.
4. Keithley A8-0 must first confirm on the real 2604B firmware and Windows
   USBTMC path that the strict identity query and nonce-bound single-line ASCII
   OFF reply grammar are exact for both SMU channels. A8a-A8b upload/late-pet
   checks then run on a dummy load; A8c-A8e host-death, independent terminal
   V/I/P + trip-time, and independent final-element / common-cause proof remain
   physical blockers. Phase C stays blocked until all are evidenced; see the
   lab checklist for the full matrix.
5. Windows source-install/shortcut smoke and, separately, a genuine packaged
   ONEDIR smoke. The editable `install.bat` path cannot close the frozen gate.

Use `docs/lab_verification_checklist.md` as the turnkey protocol.

### Active evidence checkpoint — 2026-07-20

This is feature-branch evidence, not shipped history and not a release claim:

- The integrated H3/H4 runtime/lifecycle slice is committed at `026bf50`.
  Its detached clean-SHA gate completed with 4,939 passed, 11 skipped, and
  1 deselected. H4 R3a is also committed: periodic delivery now has a
  provider-neutral receipt contract and durable state-v2 migration. H4 R3b is
  implemented for the POSIX source-mode short profile. It is designed to run
  source and configuration from sealed snapshots of the exact manifest SHA,
  own all child sessions through a temporary subreaper, continuously bound the
  launcher log, and join two adjacent durable periodic deliveries across an
  assistant replacement. The fixture is deliberately limited to one passive
  mocked `LS218_1` with 16 descriptor/binding pairs; it does not exercise the
  production alarm/interlock topology. Windows retains a fail-closed unsupported
  branch. The expanded focused Linux contract gate is green, but a clean
  integrated 15-minute run on the final SHA, 12/72-hour duration evidence, and
  real-Windows ONEDIR evidence remain open.
- Recorded exact-SHA GitHub Actions checkpoint `29662599972` at
  `503c8bf8d884654256ede4f08a9e44ab7b382242` passed all eight Ubuntu/Windows
  agents, core, GUI, and remaining jobs. Safe SQLite verification passed in
  every job; both remaining jobs also passed lint, format, and requirements-lock
  drift checks. No hosted Windows ONEDIR run exists for this checkpoint. Any
  newer candidate requires its own exact-SHA eight-job pass and separate ONEDIR
  evidence before acceptance. This checkpoint does not include the current
  unsealed worktree and does not close frozen-build, soak-duration,
  physical-hardware, F35 frozen-packaging, or F36 operator/accessibility/
  performance gates. Final-candidate exact-SHA evidence remains pending.
- The bounded persistence spool is committed with FIFO, physical-cap and
  integrity gates, receipt-authorized acknowledgement, cancellation, and
  close settlement.
- F35 now selects a complete base/local live descriptor authority off-loop,
  commits canonical descriptors and readings in one SQLite transaction, and
  publishes only owner-issued committed receipts. Replay and reporting retain
  the canonical descriptor envelope through hot/cold data. The passive
  conformance harness, ASC reference TCP driver, registry adoption, and exact
  frozen-driver allowlist foundation and live D4 wire envelope are committed.
  D7 descriptor-governed generic instrument-health presentation is complete,
  without vendor/channel-name identity fallback. D7.4 proves descriptor-qualified
  ingress, launcher restart invalidation ordering, and shutdown/rebind over real
  localhost ZeroMQ on native Windows and WSL source runs. Specialist
  calibration, conductivity, analytics, Keithley readback, pressure,
  cold-stage, and MultiLine routing now consumes authoritative descriptors;
  bare or refused readings gain no specialist authority. Real-Windows
  ONEDIR/frozen packaging remains open. One
  scheduler-produced reference-extension artifact is now proven continuously
  through persistence/live wire, replay/report projection, real shell dispatch,
  and instrument-health display; mock TCP does not close physical evidence.
- F36 now has committed foundations for the snapshot wire contract,
  durable revision allocation, typed common-cut authority receipts, ordered
  composition, publication through the existing publisher, two-SUB bounded
  ingress, one GUI-thread Store, conservative pure replay sessions, and
  conservative live adapters. The SafetyManager cache and live safety/readiness
  authority are committed and fail conservative when proof is absent. The
  supervised production path consumes the actual loop-owned experiment,
  acquisition, and direct-SQLite persistence feeds. Both production launch
  roots retain one snapshot-ingress owner, pump newest coherent cuts into the
  real POD, and settle ingress before normal shutdown. Theme selection is
  validated and atomically deferred to the next ordinary launch; it does not
  touch the running acquisition process tree. The
  panoramic dashboard is the primary home surface; the POD is retained as an
  additive shift-summary route. A reviewed 1280x800 source-mode POD visual
  exists. The 12 operator scenarios, keyboard/NVDA, DPI/ONEDIR,
  startup/frame/memory/long-session, WSL final-candidate integration, and
  physical gates remain open; the screenshot alone closes none of them.
- Exact evidence collected on real Windows can close its matching Windows gate.
  Mock, replay, another operating system, CI, soak, or screenshot evidence
  cannot substitute for real-Windows, dummy-load, independent-final-element, or
  physical-laboratory evidence.

#### Current candidate status in plain language

| Area | Current state | What closes it |
|---|---|---|
| Historical published checkpoint | `503c8bf`; reported run `29662599972` passed eight jobs for that SHA only | A newer frozen SHA must earn its own evidence |
| Current worktree | Large, dirty, moving; no immutable candidate or covering CI | Integrate reviewed slices into one clean candidate, then verify live remote/PR state |
| Keithley and transport | Moving-tree focused checks exist; physical proof open | Rerun on the frozen candidate, then perform the prescribed 2604B/dummy-load/host-death/final-element procedures |
| Safety shutdown/HOLD | **Rejected in review:** settlement ownership is unbounded and one terminal child can be replayed | Correct, freeze, test, and pass both mandatory reviews |
| Safety configuration and channel bindings | Open | One sealed exact-typed configuration and zero dead/ambiguous/unintended descriptor bindings |
| Writer, operator log, assistant boundary | Open | Bounded persistence, end-to-end event identity, and a strictly read-only assistant authority |
| GUI and design system | Iterative semantic repair is locally tested; broader freshness/provenance/lifecycle and operator gates remain open | Preserve all operator truth, finish coherent cuts, and pass scenario/accessibility/performance review |
| Documentation and diagrams | Freshness gate is red; count must be rerun after final doc edits | Candidate-matched docs, metrics, and deterministic four-SVG regeneration |
| Platform/package evidence | Not started for the current dirty tree | One frozen SHA passes Windows, WSL, packaging, soak, ONEDIR, and eight-job CI |
| Reviews and PR | Not started for a final candidate | Fresh-context review plus coordinator line/semantic review, then exact-SHA PR/CI audit |

The 100+ sensor / 4K projector fleet view is deferred to F37. It does not
expand F36 or block ordinary single-machine laboratory readiness.

#### Frozen CLI-half review checkpoint — 2026-07-22

The linear proposal `503c8bf..f3e28a7` is **REJECTED FOR INTEGRATION AS-IS**.
Independent object review and isolated tests found that it is not
self-contained: USBTMC tests require absent Keithley/GPIB implementations;
physical-alarm exactness is not wired into production and leaves T11/T12
safety patterns dead; shell construction calls an absent Dashboard method;
disk severity/freshness is reconstructed or retained incorrectly; support
traffic can grant global connection authority; safety freshness is not
independent; replay mutation gates are incomplete; and typed lifecycle changes
the required version-1 snapshot shape without a protocol-version migration
while stale/disconnected READY remains optimistically rendered. Worker edits
to reviewer-owned governing paths earn no governance credit.

No proposal state in that chain is approved. The raw CLI commit `f3e28a7`
must not be merged, cherry-picked, or retained as an integration parent; only
independently reviewed reconstructed content may cross the lane boundary.
Commit `4024f72` is also rejected as a candidate because its exact changed
partition is 70 passed / 2 failed and both failures assert uncommitted
production behavior, including resurrection of an old snapshot queue after
cleanup failure. It remains the user-authorized Phase A baseline only: it earns
no evidence credit and may not be integrated unchanged. A corrective descendant
is acceptable only after every production dependency is present, the complete
`503c8bf..candidate` range and final tree are independently reviewed, the
isolated import-origin partitions and deterministic repeats pass, and shutdown,
quarantine, persistence, provenance, replay, and physical-gate invariants are
preserved.

### Montana final engineering, review, and publication checklist

> **Scope: campaign-local.** This checklist's lane assignments, inspection
> cadence, integration order, freezes, and publication sequence apply only to
> the Montana completion campaign and expire with its final reviewed
> disposition. Its accepted runtime regression guards remain durable product
> contracts.

Every item below applies to one exact frozen candidate object. Historical
passes, a moving worktree, a predecessor commit, or a review of similar code do
not transfer automatically.

- [ ] **Role-separated execution and parallel-lane reconciliation.** The
  reviewer owns governing documents, review dispositions, integration, and
  publication and does not repair product code. Implementation agents own only
  their separately assigned standing-lane code/test/config/build surfaces and
  do not edit governing documents or certify themselves. The active isolated
  CLI corrections staging lane is checked during active review checkpoints,
  overlapping work is coordinated serially, and its live Git state must agree
  with an explicit
  `DONE_FOR_REVIEW` manifest before it earns review credit. Only individually
  frozen committed objects are reviewed in a clean worktree; seeded/unrelated
  dirty files and worker-authored documentation never enter by blanket merge.
  `docs/MONTANA_IMPLEMENTATION_AGENT_SPEC.md` is the current detailed execution
  contract.
- [ ] **Learned-mistake prevention is executable.** Every confirmed agent
  mistake has a stable prevention ID, reviewer-authored governing rule or
  clarification, reviewer-owned machine-testability disposition, and, when
  machine-testable, an implementer-authored named deterministic guard in a
  required default CI partition. Preserved negative evidence proves that the
  guard detects the original failure or an equivalent fixture. Prose-only,
  docs-presence-only, pre-fix-green, skipped/xfail/deselected, mocked-away,
  non-owning-path, or CI-excluded checks earn zero closure. Weakening or
  exempting a guard reopens the prevention ID and both mandatory reviews. A
  machine-readable prevention map binds every ID to its rule, named guard,
  default-CI job, and immutable red/green evidence. A green suite contradicted
  by a deterministic reproduction creates a separate false-green prevention ID
  and cannot close with the product fix alone. See
  `docs/adr/003-governance-as-enforcement.md`.
- [ ] **Prevention registry is enforced.** The reviewer-owned
  `governance/agent_preventions.yaml` contains every confirmed campaign mistake
  and binds it to rules, named guards, default-CI jobs, and evidence state. The
  primary worker supplies `tests/governance/test_agent_preventions.py`; both
  Ubuntu and Windows `remaining` jobs reject duplicate or incomplete records,
  uncollectable/renamed guards, closed records with pending evidence, and any
  silent weakening/removal. The validator itself has red-before-fix evidence
  against duplicate, missing-guard, skipped/xfail, non-default-CI, and falsely
  closed fixtures.
- [ ] **Keithley command identity and shutdown proof.** The nonce-bound OFF
  protocol, connection identity, replay rejection, both-channel behavior, and
  shutdown races are locally verified. Real 2604B identity/reply formatting,
  terminal OFF, host-death, and independent final-element evidence remain
  physical gates until the laboratory checklist records them.
- [ ] **USBTMC desynchronization containment.** A timed-out or ambiguous
  exchange quarantines the transport until a clean reconnect; no delayed reply
  may satisfy a later command or OFF proof.
- [ ] **Transactional safety-configuration authority.** The selected base or
  complete local safety YAML is one bounded, immutable, exact-typed document;
  duplicate/unknown keys, aliases, malformed regexes, non-finite or out-of-range
  values, unsafe filesystem identities, and unreadable selected-local files
  fail closed without fallback. All scalar, list, and regex validation finishes
  before one atomic manager commit. SafetyManager cannot start unconfigured or
  reload after its configuration is sealed, and adversarial rollback/selection
  tests prove that every failed load leaves the prior authority unchanged.
- [ ] **Safety-pattern and physical-semantic authority.** One frozen descriptor
  manifest and safety-config snapshot defines the canonical-to-raw channel
  translation. Every safety, alarm, interlock, and legacy-throttle pattern that
  participates in startup has at least one exact intended live binding; raw
  acquisition never reinterprets canonical labels and prefix matches cannot
  alias neighbouring sensors. T11 remains the nitrogen plate and T12 the GM
  second stage across alarms, UI, reports, and operator documents, and they
  remain the only SafetyManager critical channels absent a separate hazard
  review. Before command ingress or RUN authority, the exact selected hashes
  must yield zero dead, ambiguous, or unintended bindings.
- [ ] **Safety-monitor and process-death containment.** First death becomes a
  visible unavailable/fault condition, fail-closed OFF escalation is bounded,
  and no restart invents healthy authority. A launcher hard kill may target
  only the exact process and only after the verified-OFF permit contract has
  settled; abandoning a still-running executor future is not shutdown.
- [ ] **Coordinated shutdown and HOLD authority.** Shutdown closes new command
  ingress first and retains one coordinator for every accepted mutation,
  scheduler/persistence tail, safety child, and reviewed-source operation. It
  may proceed to resource teardown only after exact global OFF proof and bounded
  settlement. If OFF is unverified, the engine remains in an operator-visible
  HOLD with its process, instance lock, SafetyManager children, exact driver /
  transport, logging, and retry path alive; the launcher must not classify it
  as a clean exit, restart it, release its identity, or hard-kill it. Repeated
  signals, timeout, or caller cancellation cannot convert HOLD into success.
  After true OFF, remaining owners drain and one exact exit receipt authorizes
  final process release.
- [ ] **Persistence and writer-hang containment.** Uncommitted data is never
  published, writer failure/hang is bounded and visible, and engine/writer
  ownership and shutdown settlement have deterministic regression evidence.
- [ ] **Operator-log identity and idempotency.** One stable event identity and
  payload is allocated before hot commit. An exact retry is idempotent; the same
  identity with a different payload fails visibly. Rotation/retry cannot lose or
  duplicate the event, hot+cold union deduplicates by identity rather than
  timestamp/text/order, and REST/history, replay, reports, and the observational
  assistant preserve it. Canonical fingerprints are owner-computed, registries
  are bounded, cold generations are receipted and crash-recoverable, and legacy
  rows are deterministic or explicitly marked legacy.
- [ ] **Observational assistant and ZMQ boundary.** The assistant has no control
  capability or mutation credential. It binds loopback-only with exact protocol
  and process-version identity, uses closed read-only schemas, and rejects every
  unknown or mutating query before opening/sending on ZMQ. Prefix routing cannot
  pass it an engine capability token; assistant, RAG, report, and Telegram paths
  hold no write token, source authority, or generic command proxy, and the
  assistant cannot become a second operator-log writer. Malformed replies and
  health are reported honestly; maintenance/delivery remain separate bounded
  observational authorities.
- [ ] **Shared GUI presentation cuts and lifecycle.** One GUI-thread Store
  atomically applies each global operator-snapshot revision across all summary
  widgets; independently, each measurement channel owns one bounded <=2 Hz
  display cut containing last usable value, current status, source/arrival
  times, descriptor/provenance, freshness/connectivity/identity, interval
  extrema, invalid-value, worst-status, and clock-skew evidence. A render never
  mixes global revisions or partially applies a rejected cut. Later stale,
  disconnected, or unavailable evidence preserves last coherent values and
  marks their age rather than blanking or inventing truth. Top watch, sensor
  cells, Keithley displays, conductivity/analytics display projections, and the
  panoramic workflow consume only their appropriate presentation authority;
  urgent fault annunciation remains immediate and acquisition, persistence,
  alarms, predictors, safety, and control stay full-rate and independent.
  Timers/workers/ingress owners settle and scenario/design-system/accessibility/
  DPI/performance/long-session gates pass.
- [ ] **Conductivity auto-advance freshness decision and authority.** Before
  auto-sweep is lab-ready, an operator/hazard review must choose and document
  what freshness loss does: visible PAUSE/HOLD at the current setpoint or
  verified STOP/OFF. Until that choice is frozen, automatic advance remains
  unavailable. No point may be recorded and no next setpoint sent without the
  current operation generation's accepted command plus usable post-command
  power/readback and every selected temperature sample, bounded source/arrival
  skew, and a predictor derived from those fresh samples. Stale, disconnected,
  or non-finite input, clock rollback, delayed reply, or a cached previously
  settled prediction cannot advance or auto-resume; presentation cuts never
  gain dispatch authority.
- [ ] **Documentation and architecture evidence.** README/Russian overview,
  status, protocol, architecture, operator/deployment/lab procedures, the full
  Montana report, metrics, and all four SVG maps agree with the candidate and
  are generated transactionally and deterministically.
- [ ] **One exact-candidate platform, package, soak, and CI freeze.** Freeze one
  clean candidate commit and reproduce Ruff check/format, lock drift, every
  configured test partition on native Windows and WSL/Linux, source-install /
  config smoke, the sealed final-SHA 15-minute soak, and the recorded status of
  the separate 12/72-hour elapsed soaks. Build Windows ONEDIR from that same
  commit, record the artifact hash, and pass every frozen smoke cell against
  that artifact. Push the identical commit and require all eight hosted Ubuntu /
  Windows jobs green. Dirty-worktree, predecessor-SHA, stale archive, cached
  build, or differently built artifact evidence transfers no credit; every
  unavailable gate stays explicitly open.
- [ ] **Two mandatory review receipts per gate.** Every engineering and
  evidence gate is frozen before review. One newly spawned reviewer receives
  fresh context containing only that frozen scope, its threat model,
  acceptance contract, and collected evidence; inherited campaign discussion
  is not a substitute for this independent pass. The coordinating Codex agent
  then performs a separate mandatory review of the same object. Both receipts
  bind the exact object/ranges and record findings plus local adjudication.
  Any correction invalidates both affected receipts and the corrected frozen
  object must pass both reviews again. External-model review is optional,
  additive evidence only and requires exact current-user authorization naming
  the provider and frozen scope. Its absence or quota exhaustion never blocks
  integration, PR readiness, merge, or publication. When authorized, preserve
  and hash the complete report and verify every finding locally; external
  approval never replaces either mandatory internal review or grants
  publication authority.
- [ ] **Exhaustive object/range disposition.** The generated review map covers
  every current and deleted text range plus every binary, symlink, gitlink,
  executable-mode, rename, and LFS pointer/resolved-artifact obligation. It
  records exact old/new blob identities, separate reviewer dispositions, and
  evidence hashes. Missing, truncated, unavailable, quota-limited, conditional
  without an explicitly unaffected range, or stale-hash evidence earns zero
  credit; any content, path, type, or mode change reopens the affected
  obligation. The fresh-context reviewer and coordinating Codex dispositions
  are both mandatory for the current campaign. Evidence from any additional
  external reviewer stays separately labelled and cannot be silently
  substituted for either required reviewer.
- [ ] **Semantic assurance beyond line counting.** Architecture, threat-model,
  operator-workflow, safety, concurrency/persistence, and test-quality audits
  are independent mandatory gates. A 100% line/object count never by itself
  claims that reviewers understood every behavior or hazard.
- [ ] **Frozen PR audit and publication.** After both final mandatory reviews
  pass, the exact tested hash is committed, pushed, and watched until every
  required hosted check completes green. Only that reviewed hash may open the
  ready PR. The PR diff and hosted checks are then audited again; every finding
  is adjudicated and corrected/re-reviewed on a new exact hash. A red,
  cancelled, stale, or unreviewed job keeps the gate open.

The staged target excludes only the generated review-ledger/receipt outputs
from self-coverage; their generator, schema, and tests are ordinary candidate
code and require normal review. Ledger generation must be byte-deterministic on
two consecutive runs. The generated files then carry explicit post-commit PR
review debt because an output cannot truthfully validate or embed its own final
hash. `git write-tree` writes an object only; it does not freeze the index or
worktree. Intent-to-add or unmerged index entries block the final freeze, sparse
entries remain obligations by blob identity, and carry-forward approval is off
for the final candidate.

---

## ASC scalability milestone — F35

CryoDAQ must remain usable beyond the current stand. Historically, adding an
instrument required central engine edits and name-based GUI routing. The active
branch now uses the allowlisted registry, canonical descriptor authority, and
descriptor-qualified generic and specialist routing. F35 turns that
implementation into a supported extension contract for other ASC laboratories,
with frozen-package and physical evidence still outstanding.

Execution status: F35.1 registry/capabilities and F35.2 shared-bus contracts
are committed. Within F35.3, D1 manifest authority, D2 persistence activation,
D3 committed-receipt publication, D4 live descriptor wire transport, D5 replay
parity, D6 reporting parity, and D7.1 descriptor-qualified GUI ingress are
complete on the active branch. D7 descriptor-governed generic instrument-health
presentation is complete without vendor/channel-name identity fallback. D7.4
proves the descriptor-qualified ingress, restart invalidation ordering, and
shutdown/rebind lifecycle over real localhost ZeroMQ on native Windows and WSL.
The software reference-extension end-to-end gate is complete: one
scheduler-produced artifact is followed through persistence/live wire,
replay/report projection, real shell dispatch, and instrument-health display.
Specialist calibration, conductivity, analytics, Keithley readback, pressure,
cold-stage, and MultiLine routing accepts only authoritative descriptor
semantics; bare, refused, and capacity-exhausted readings gain no specialist
authority.
The reusable passive
conformance harness, ASC reference TCP driver, registry adoption, and exact
frozen-driver allowlist are also committed foundations; real-Windows frozen
packaging remains open. Mock TCP/source evidence does not close hardware or
physical gates. F35 therefore remains partial without understating the
completed software foundations.

Scope and acceptance criteria:

1. **Driver registry outside the engine.** A built-in/allowlisted registry
   owns type lookup, construction, and strict per-driver configuration.
   `engine.py` contains no instrument-model switch. Unknown configured types
   fail visibly instead of being silently skipped.
2. **Explicit capability protocols.** Passive sensors, calibratable sensors,
   burst/waveform devices, shared-bus devices, controllable sources, and
   verified-OFF sources expose separate narrow contracts. The scheduler and
   command plane do not reach into driver-private state or transports. A
   public bus/recovery descriptor replaces resource-prefix inference and
   concrete `GPIBTransport` resets, preserves each device's declared
   connect/read timeout and polling cadence, and passes a mixed-cadence
   shared-bus conformance test.
3. **Channel descriptors, not naming heuristics.** Quantity, unit, role,
   safety class, display group, and stable channel identity are metadata.
   Generic GUI paths do not depend on `Т1..Т24`, `/pressure`, `smua/smub`,
   or a vendor/model substring.
4. **Registry-driven setup and packaging.** The first-run wizard renders
   connection fields from the registered driver schema. Development and
   frozen builds include and verify every allowlisted driver explicitly.
5. **Driver conformance kit.** A reusable test harness covers bounded
   connect/read/disconnect, cancellation, reconnect, malformed/non-finite
   input, mock mode, stable `instrument_id`, persistence-first publication,
   replay, and resource cleanup.
6. **Reference extension proof.** A new passive reference driver can be added
   with its own module, schema, config, and tests without editing engine,
   scheduler, launcher, storage, or generic GUI code; an end-to-end test proves
   acquisition, persistence, replay, reporting, and instrument-health display.
   Replay must resolve the same stable channel descriptor—including quantity,
   role, safety class, and display group—and reporting/generic GUI paths must
   consume that descriptor rather than rediscovering semantics from names.
7. **Safety boundary stays deliberate.** Arbitrary plugins never gain source
   authority by duck typing. A new hazardous actuator requires an explicit
   reviewed safety adapter, hazard analysis, verified-OFF contract, independent
   host-death protection, and physical bench evidence.

Passive measurement extensions are the first target. A generic safety-actuator
plugin system is explicitly not an acceptance criterion and must not weaken the
current safety authority.

---

## Operator product milestone — F36

CryoDAQ must become an operator-centered operating surface, not a collection
of instrument modules and feature tabs. The primary display must answer, from
backend truth: **can the run proceed, what is happening, what needs attention,
is the system degrading, and what action is safe next?** This product layer
must preserve the module-first driver architecture beneath it.

### F36.0 — Task/evidence contract freeze — ✅ DONE

Freeze 12 scripted operator scenarios covering cold start, disconnected engine,
stale data, unsafe preconditions, alarm acknowledgement, safety recovery,
cooldown deviation, storage degradation, passive infrastructure degradation,
experiment handover, replay, and support-bundle capture. Define how later
operator runs record task success, time, errors, and false
safe/ready/recording presentations; this slice does not claim those
measurements have already been collected.

Acceptance for F36.0: scenario fixtures and measurement fields are deterministic
and reusable, and no scenario requires real hazardous actuation. The target
operating display must later demonstrate at least 90% task success, median
decision time <=10 s, p95 <=20 s, and zero false safe/ready/recording states in
the F36.2 operator-scenario gate before F36 closes.

Implemented as the reviewed, still-unmeasured contract in
`docs/operator_scenario_baseline.md` and
`tests/fixtures/f36_operator_scenarios_v1.json`. This closes the baseline
definition only; it does not claim the present UI or any operator measurement
passes the target.

### F36.1 — Canonical immutable operator view-models — ✅ DONE

Create backend-owned/read-only contracts for:

- `ReadinessSummary`
- `PlantHealthSummary`
- `InfrastructureNodeHealth`
- `AttentionQueue`
- `ExperimentOperatingState`
- `DataIntegritySummary`
- `CooldownHistorySummary`
- `SupportBundleSummary`

Panels consume one revisioned snapshot rather than independently polling and
reinterpreting state. Every summary carries provenance, freshness, reason
codes, revision/time, and explicit source-state `ok | caution | warning |
fault | stale | disconnected` semantics. Presentation normalizes legacy
`warning` to the single `caution` attention rung while preserving the source
state for provenance. Unknown never becomes optimistic green.

Acceptance: model/view tests prove coherent revision cuts, defensive copies,
disconnect/stale transitions, replay compatibility, and no GUI safety
authority. Existing module panels remain usable as drill-down surfaces. The
reviewed immutable snapshot contract is committed on the active feature branch;
operator-surface acceptance remains a separate F36.2 gate.

The supporting snapshot data plane is also committed: a bounded protocol
envelope, durable global revision allocator, typed common-cut receipts,
asynchronous ordered composer, replay-compatible publisher, separate
readings/snapshot SUB paths, and one GUI-thread Store.
Pure replay sessions and conservative live adapters preserve explicit
unavailability rather than inventing authority. The committed SafetyManager
cache and live safety/readiness authority now provide truthful live safety
facts, including conservative UNKNOWN/disconnected behavior when evidence is
missing. The production engine now owns one supervised composer/publication
path. It samples the exact loop-owned experiment, acquisition, direct-SQLite
persistence, and SafetyManager feeds, allocates one durable revision only after
the complete cut validates, and publishes through the sole existing PUB
socket. Missing mandatory authority remains fail-dark; stale or ambiguous
persistence remains explicitly NOT_RECORDING/unavailable. No fallback writer
or control coupling exists, and optional F36.3-F36.5 authorities are not
synthesized.

### F36.2 — Primary Operating Display, preflight, and recovery — 🔧 PARTIAL

Build a Shift Briefing / Preflight operating surface that prioritizes
readiness, experiment state, top attention items, data integrity, and the next
documented operator action. Add the missing reasoned safety-acknowledgement and
recovery UI over the existing backend command contract; it must expose
preconditions and never bypass the safety FSM.

Reorganize navigation by operator intent, with contextual experiment creation:

- **Operate:** Home/POD, Experiment, Source, Alarms, Instruments
- **Analyze:** Analytics, Conductivity, MultiLine
- **Record and review:** Log, Review/Archive
- **More:** Calibration, Knowledge Base, Settings, Web, Engine restart

Acceptance: all 12 F36.0 scenarios pass; keyboard-only operation and non-color
state identification pass; no optimistic local state; legacy panel deep links
remain compatible during migration. After the frontend is integrated into the
real shell, launch CryoDAQ only in an isolated mock/replay configuration and
capture every reachable screen and material state. Review those screenshots
together with the scripted operator scenarios for clipping, hierarchy,
translation, focus, stale/disconnected truth, non-color cues, and design-system
conformance. Screenshot approval is evidence input, not a substitute for the
scenario, accessibility, performance, or backend-truth gates.

Current boundary: the reusable operating-display, navigation, backend-truth
models, snapshot transport, Store, production engine publication path, and
  software POD route exist. The panoramic dashboard is the primary home surface;
  the POD remains available as an additive shift summary. Both production launch
  roots retain one snapshot-ingress owner and settle it before normal shutdown.
  Theme selection is a validated next-launch preference and has no acquisition
  or process-lifecycle authority. A reviewed source-mode POD screenshot is evidence input only; no
operator, accessibility, performance, ONEDIR, WSL final-candidate integration,
long-session, or physical acceptance is claimed.

### F36.3 — Cooldown mission and durable attention history

Unify live cooldown trajectory, deviation, phase, relevant alarms, recent
history, and comparison-to-reference into one mission view. Make attention and
incident evidence durable across GUI restarts rather than relying on bounded
in-memory alarm history. Preserve the canonical alarm authority and audit
revision; UI filtering/acknowledgement never rewrites truth.

Acceptance: restart/replay tests reproduce the same incident timeline and
cooldown decision state; missing data is explicit; exported evidence points to
stable experiment/channel identities.

### F36.4 — Passive infrastructure health at ordinary lab scale

Add an allowlisted read-only `HealthTelemetryDevice` contract for compressor,
pump-station, cryocooler, and support nodes. It may report identity, heartbeat,
mode, metrics, alarms, freshness, and provenance. It must not expose
start/stop/reset/vent/purge/set commands or health-driven automatic
remediation.

Acceptance: deterministic simulators prove the configured laboratory support
nodes at <=2 Hz human-readable update cadence without unbounded widgets, poll
tasks, queues, or memory growth. The ordinary operator surface presents health,
freshness, provenance, and explicit unavailable state without adding control
authority or hiding the panoramic dashboard. The 100+ sensor / 4K projector,
aggregation, semantic-zoom, and fleet-virtualization problem belongs to F37 and
is not an F36 closure claim.

### F36.5 — Onboard documentation, read-only API, and support bundle

Ship version-matched offline operator/safety/troubleshooting documentation,
document the read-only status/view-model API, and generate a deterministic,
redacted support bundle containing versions, config fingerprints, health and
attention snapshots, recent audit/log evidence, and integrity results.

Acceptance: bundle schema and redaction tests cover tokens, credentials,
operator/private data, absolute user paths, and hostile strings; identical
inputs produce stable manifests; capture works while the engine is degraded.

### F36.6 — Design-system and product-governance gate

Every F36 UI slice, in addition to the roadmap-wide GUI gate above, must use
`docs/design-system/` as a co-versioned contract.
New or changed token/component/pattern/state semantics update the canonical
specification, examples, accessibility/performance evidence, version, and
changelog in the same slice. The industrial rule remains: quiet normal, loud
exceptions, static data legibility, Russian operator wording, and no live-value
animation.

Acceptance: WCAG 2.2 AA-target evidence (with documented exceptions),
keyboard/focus and NVDA/manual procedures, contrast/non-color states, scripted
operator scenarios, and performance budgets pass. Screenshot approval alone is
never sufficient.

### F36 strict non-goals before physical validation

- No GUI or product-assistant safety authority.
- No health-driven automatic remediation.
- No arbitrary network/device discovery.
- No remote safety/source control or cloud dependency.
- No generic hazardous-actuator SDK.
- No claim that a mock, Linux/macOS source run, or CI workflow closes real
  Windows ONEDIR, dummy-load, independent final-element, or lab gates.

F36 follows ISA-101-style situational-awareness/HMI lifecycle practice,
ISA-18.2 / IEC 62682 alarm lifecycle discipline, and Qt model/view and
accessibility architecture, adapted to CryoDAQ's existing design system and
safety boundaries.

---

## Deferred feature work

- **F37 — Fleet/projector operating view.** After ordinary lab-readiness and
  F36 operator-scenario gates, add an automatically DPI-aware scale mode for
  100+ sensors and 4K wall/projector displays: virtualized grids, aggregation,
  search/filter, semantic zoom, projector-scale typography, and an operator
  density override. Automatic layout must never silently hide channels or
  change acquisition/alarm truth. Validate both close bench use and room-scale
  viewing without replacing the ordinary panoramic dashboard.
- **F8 — Cooldown ML prediction upgrade.** Still research-gated: dataset
  curation, model evaluation, and uncertainty methodology come before code.
- **F12 — Experiment templates UI editor.** Nice-to-have operator workflow;
  not a safety or release blocker.
- **F14 — Remote command approval.** Safety-sensitive; needs a fresh threat
  model and explicit go/no-go before implementation.
- **F15 — Linux packaging.** Deployment convenience after lab verification.
- **F16 — Plugin SDK/examples.** Documentation/examples work, not core runtime.
- **F35 is not deferred.** Complete its frozen-build evidence before calling
  CryoDAQ a multi-lab ASC platform or adding another safety-critical source
  family.
- **F36 is not deferred.** Complete its safe software and operator-scenario
  gates before laboratory validation; keep its hazardous-control non-goals and
  physical acceptance gates open.
- **F18 — CI/CD residuals.** Recorded exact-SHA run `29662599972` closes the
  Ubuntu/Windows matrix gate at checkpoint `503c8bf`; every newer candidate
  still requires its own eight-job pass, and this run contains no hosted
  Windows ONEDIR evidence. Coverage publishing, release automation, and binary
  artifacts remain optional.
- **F-Y — Diagnostic mode rework.** Re-spec only if lab operation produces
  concrete diagnostic decisions that the current alarm/overlay path cannot
  support.

---

## Post-Montana engineering-quality and research roadmap

> **Scope boundary — this is the next programme, not current Montana work.**
> The items below start only after the Montana software, review, CI, publication,
> and handoff gates are closed. They are not retroactive Montana acceptance
> criteria and must not delay the current branch merely to pursue an abstract
> quality score. If future exploration exposes a violation of an existing
> Montana safety invariant, that concrete defect is handled under the normal
> safety process; otherwise this section remains post-Montana work.
> Any real-Windows, ONEDIR, soak-duration, dummy-load,
> independent-final-element, or physical-laboratory gate still open in
> `PROJECT_STATUS.md` remains open; no post-Montana analysis, simulation, or
> model transfers credit to it.

This programme orders the remaining improvement axes by expected return on
engineering time. It distinguishes inexpensive high-return work, medium-sized
work that directly supports scientific defensibility and a thesis/dissertation
defence, larger
legitimacy/certification projects, and areas where CryoDAQ should deliberately
avoid feature or architecture inflation.

### Do first after Montana — low cost, high return

#### 1. Mutation testing as a quality gate

The repository has a large test suite, but test count and line coverage do not
prove that assertions detect meaningful behavioural defects. Pilot a Python
mutation-testing tool such as `mutmut` or `cosmic-ray` on bounded, deterministic
modules, classify killed, survived, equivalent, and timed-out mutants, then add
a ratcheted CI gate once the baseline is understood.

The gate must not reward brittle assertions or indiscriminate test volume.
Generated code, platform-only launch boundaries, nondeterministic timing probes,
and hardware procedures need explicit policy rather than silent exclusion.
Safety, persistence, protocol, and state-machine code should receive the first
campaigns because surviving mutants there provide the most useful signal.

Acceptance:

- the tool invocation and exclusions are reproducible on a frozen commit;
- zero high-risk mutants remain untriaged; every non-equivalent survivor is an
  owned test gap with an explicit disposition rather than pressure to label it
  equivalent;
- timeouts and invalid mutants are reported separately and never counted as
  killed; the denominator/exclusion policy is versioned and reviewable;
- CI enforces measured per-scope baselines/ratchets and reviewed high-risk
  floors, not an arbitrary global percentage chosen before measurement;
- ordinary coverage metrics remain supporting evidence, not a substitute for
  mutation effectiveness.

#### 2. Reduce concentrated local complexity without removing guarantees

Review the `periodic_png.py` coordination surface (the T5-1 concentration,
measured at approximately 2,045 lines in the interim Montana report) and the
six-module operator-snapshot cluster. Reduce ceremony and repeated
receipt/outcome/projection plumbing where the same guarantee can be expressed
once, while preserving durable delivery, bounded shutdown, safety cutover,
single-writer ownership, provenance, and unknown-outcome semantics.

This is a targeted maintenance project, not a rewrite. Before authoring begins,
the designated integration coordinator alone defines and records the stop-list
of invariants that may not be compressed away. Measure the result with
dependency direction, cyclomatic/cognitive complexity, ownership clarity, and
deleted duplication rather than with a raw “lines removed” target. Start it
when these areas demonstrably slow review or maintenance; do not churn stable
code merely to make files shorter.

#### 3. Convert documentation drift into executable consistency checks

Several reviews found prose or docstrings claiming that production wiring was
absent after the wiring had already landed. Add structured, narrow checks that
bind important wiring claims to live registration points and runtime constants.
Prefer explicit markers, parsed inventories, and contract tests over fragile
whole-corpus phrase matching.

This is a future prevention gate. It does not defer correcting known Montana
documentation drift or closing the currently red candidate-matched
documentation-freshness gate.

Acceptance:

- a material wiring change cannot leave its authoritative status statement
  silently stale;
- missing source documents and unavailable Git metadata fail closed in the
  documentation gate rather than becoming empty input or an untracked fallback;
- checks identify the exact stale contract and remain maintainable when prose is
  reworded without changing meaning.

### Do next for scientific defensibility or thesis/dissertation defence — medium-sized work

#### 4. Persist receipt latency and clock-domain provenance (T0-1)

Capture a receipt-time value such as `recv_monotonic_ns` at one authoritative
acquisition boundary. Downstream spool, SQLite/Parquet storage, rotation,
replay projection, and `archive_reader` must copy that evidence, never
regenerate it. Because a raw monotonic value is meaningful only inside one
host/boot clock domain, persist that domain identity, paired monotonic↔UTC
calibration anchors with stated uncertainty and clock-step metadata, and the
source clock's semantics and identity. Never compare unrelated or uncalibrated
domains as if they shared an epoch.

This closes both an engineering observability gap and a scientific-method gap.
It makes the source-time-to-receipt offset estimable within stated
clock-calibration uncertainty, so the inverse analysis can demonstrate that it
is negligible at the apparatus resolution or model it as a nuisance parameter
rather than assuming it away. Unrelated or uncalibrated domains remain unknown
and are marginalized; they are never blindly subtracted.

Acceptance:

- schema migration and backward-compatible readers distinguish source time,
  receipt time, persistence time, and their clock domains;
- spool, cold rotation, Parquet, replay, reports, and exports preserve the new
  evidence without inventing values for old records;
- deterministic delay/skew, wall-clock-step, suspend/resume, reboot,
  process-restart, and unrelated-domain tests prove the interpretation
  boundaries;
- the scientific report states the measured offset distribution and how it is
  propagated or marginalized in downstream inference.

#### 5. Add a fault-injection campaign harness

Turn robustness from a collection of post-incident regressions into a
repeatable campaign. Exercise complete mock/replay runs while killing only
harness-owned, identity-checked processes; using a quota-limited disposable
filesystem or injected `ENOSPC` rather than consuming workspace/host free
space; breaking harness sockets; delaying or dropping REP replies; interrupting
test persistence; and forcing shutdown races. The harness must remain isolated
from real instruments and hazardous outputs.

Acceptance:

- scenarios are deterministic or carry explicit statistical/repetition rules;
- every injected fault has an expected fail-closed state, bounded settlement,
  durable evidence requirement, and recovery/restart contract;
- resource growth, orphan tasks/processes, duplicate writers, and false-success
  UI states are asserted, not inspected informally;
- CI runs a bounded core set, while longer campaigns produce retained nightly or
  release-candidate evidence bound to the exact commit, configuration,
  seed/fault schedule, and repetition rule;
- mock/replay campaigns cannot close host-death, real-Windows, final-element,
  or physical-laboratory gates.

### Larger projects — pursue for external legitimacy or certification

#### 6. Formally model the safety state machine; separately evaluate independent protection

Model the safety/actuation authority boundary in TLA+, a model checker, or an
equivalent formal method. State and model-check invariants under explicit
environment, fairness, and timing assumptions, including that hazardous
actuation is unreachable without the required permission and transition
evidence. Distinguish commanded OFF, readback-verified OFF, and independently
observed physical OFF while exploring cancellation, host death, duplicate
messages, and stale receipts. Treat model-to-code correspondence as a reviewed
artifact, not as an automatic proof of the implementation.

An independent watchdog is a separate hardware/system project. Another process
on the same host is not independent protection: independence must cover the
common-cause boundaries selected by the hazard analysis. It requires an
approved hazard analysis, final-element contract, and physical bench evidence.
Neither model checking nor software simulation closes that physical gate.

#### 7. Build a long-term reproducibility chain

Bind raw acquisition evidence, configuration/descriptors, processing code, and
generated conclusions so that a reported number can be regenerated years later.
Record content hashes, schema/tool versions, environment or lockfile identity,
and the exact processing commit in report manifests. Reuse the existing
append-only descriptor and authenticated-spool foundations without claiming
that they already provide an end-to-end scientific provenance chain.

Acceptance:

- tampering or missing inputs are detectable;
- regeneration starts from immutable identifiers rather than mutable paths;
- reports explain which inputs are raw observations, operator annotations,
  calibrations, transformations, and derived results;
- a clean-room replay of a frozen example reproduces the declared outputs or
  reports a bounded, explained numerical tolerance.

### Deliberately do not chase

- **More capability for its own sake.** A focused laboratory DAQ has a healthy
  ceiling. Additional features are not quality unless they answer an observed
  operator, scientific, or safety need.
- **Wholesale migration of every panel to a common base (T3-1).** Keep it in the
  backlog until duplicated behaviour creates a concrete maintenance or safety
  cost. Visual uniformity alone is insufficient justification.
- **An abstract S-tier HMI score before field evidence.** Code cannot substitute
  for real night-shift usability, alarm-load, legibility, and recovery data.
  The current target is a strong, honest operator interface with explicit open
  field-validation gates.

### Recommended post-Montana sequence

The default high-return set is roadmap items **1, 3, and 4**: establish
mutation-testing evidence, make critical documentation/wiring claims
executable, and add clock-domain-safe receipt-latency evidence for the
scientific uncertainty model. Documentation checks can proceed in parallel.

If a separate robustness campaign is justified, use the risk sequence
mutation evidence → receipt-latency evidence → isolated fault injection. Then:

1. Reduce concentrated coordinator/snapshot debt only when the measured
   maintenance return justifies the change.
2. Start formal verification only for an external audit or safety-standard
   path.
3. Evaluate independent protection only after an approved hazard analysis and
   with the required bench/final-element evidence.
4. Build the full reproducibility chain when long-horizon science,
   collaboration, or external review warrants it.

The aim is not to manufacture work in pursuit of a perfect grade. A strong,
well-evidenced production system is enough for ordinary laboratory operation,
scientific defensibility, thesis/dissertation defence, and hiring evidence once
its stated gates are closed.
“S-tier” investment is justified when CryoDAQ must demonstrate correctness to
an external auditor, safety standard, sceptical reviewer, or long-horizon
reproducibility programme—not simply because further complexity is possible.

### Phase: Agent-Native Plugin Authoring (final post-Montana phase)

This is the last planned engineering-quality phase. It begins only after the
Montana software candidate has passed its own acceptance and handoff gates and
after the higher-return post-Montana work above has been dispositioned. It does
not block or redefine the Montana PR.

This roadmap-authoring pass fixes the specification, acceptance criteria, and
architecture decisions only. It does not implement a plugin, conformance
harness, template, registration surface, safety verifier, or production
scaffold. Those artifacts are work items of this future phase.

#### Goal

Make the repository agent-native: a plugin for a new instrument should be
generated by applying versioned rules encoded in the repository, not by
reconstructing CryoDAQ's architecture from first principles. The target is a
competent mid-tier model (DeepSeek/Kimi/Flash class), not only a frontier model.
This deliberately shifts cognitive load from inference time to design time.

#### Governing principle

Rules define the ceiling of quality; the conformance gate defines the floor.
Weaker models operate closer to the floor, so the floor must be high. The main
engineering artifacts are therefore the executable contract and conformance
suite, not additional prose. Prose tells an agent what to build; automated
checks prove whether the result conforms, so model output is never accepted on
trust alone.

The contract is a living repository interface. Any accepted change to plugin
architecture, reading semantics, safety-manifest schema, or extension workflow
must update the contract, conformance harness, template, drift checks, and
version/changelog evidence in the same reviewed slice. A claim that cannot yet
be checked must be labelled as guidance and owned as a conformance gap; it must
not masquerade as an enforced obligation.

Every obligating clause receives a stable ID such as `PLUGIN-READ-001`. A
machine-readable registry maps each ID to one or more named checks, and a
meta-test enforces exact set equality: no obligation without a check, no check
without a contract ID, no duplicate ID, and no skipped or expected-failing
substitute for enforcement. A rule without its enforcing test is not added.

#### Required deliverables

1. **`PLUGIN_CONTRACT.md` — obligating, testable plugin contract.** Define the
   exact driver, panel, descriptor, and safety-manifest surfaces. Every
   obligation must map to a named automated check or an explicit physical/human
   gate. At minimum it must specify:

   - exact `Reading` shape, runtime types, finite-value policy, unit vocabulary,
     stable instrument/channel identity, descriptor provenance, timestamps, and
     status semantics—not merely “return a Reading”;
   - mandatory rejection or explicit unavailable/disconnected projection for
     disconnect sentinels, NaN/Infinity, overflow, empty and partial streams,
     wrong frame length/shape, malformed encoding, stale fragments, and other
     hostile or edge input; reject-not-crash is required, and silent loss is
     forbidden;
   - plugin-owned golden input→output vectors that anchor endianness,
     decimation, scaling, sign, units, channel mapping, boundaries, and known
     invalid frames, rather than happy-path examples alone;
   - a fixed, versioned safety-manifest schema declaring trust class,
     capabilities, actuation channels, limits and units, safe direction,
     readback/verified-OFF requirements, and the absence of actuation for a
     passive plugin;
   - panel conformance to canonical design tokens and components, Russian
     operator wording, keyboard focus/traversal/activation, and non-color state
     cues. A cell's current/stale/disconnected availability projection must not
     collapse or overwrite its independent safety-severity meaning;
   - lifecycle, cancellation, blocking-I/O, bounded-resource, persistence, and
     GUI truth obligations inherited from the repository contracts.

2. **`tests/conformance/` — plugin-independent executable floor.** Build an
   abstract harness against `PLUGIN_CONTRACT.md`, not against one vendor or
   instrument. It must discover a plugin through its public registration
   surface and exercise:

   - reading shape/type/unit/identity/provenance invariants;
   - a bounded hostile-input battery that asserts reject-not-crash,
     never-drop-silently, no optimistic state, and no accidental authority;
   - golden-vector replay with exact or explicitly bounded numerical
     tolerances;
   - safety-manifest schema, dimensional consistency, bounds, capability, trust
     class, and sign-off validation;
   - real automated panel checks for design tokens, state-axis projection,
     Russian copy, non-color cues, and keyboard behavior. Aspirational
     design-system tool names or prose do not count as enforcement;
   - deterministic lifecycle, cleanup, cancellation, and resource-limit cases
     that can run without real hardware.

   Include a template fixture and prove that the same harness can reject
   intentionally nonconformant mutations. The seeded weak-model corpus includes
   wrong reading type/shape/unit/identity, swallowed hostile input or silent
   drop, syntactically valid but physically wrong endianness/decimation/scale,
   and over-claimed capability or undeclared actuation. Each seed must fail for
   its intended obligation ID. Test count alone is not acceptance; the harness
   must demonstrate that representative failures are caught.

3. **`plugins/_template/` — conformant scaffold.** Provide a minimal driver
   stub, panel stub, descriptors/registration, golden vectors, and safety
   manifest that already pass the non-hardware conformance suite. A generating
   agent starts from this scaffold and fills instrument-specific behavior
   without inventing architecture. Placeholder behavior must be visibly
   unavailable/passive and must never imply live, safe, ready, or actuating
   state.

4. **Token-efficient `AGENTS.md` governance.** Keep only information that
   changes implementation behavior: intentional deviations from common
   patterns, hard invariants, ownership/safety boundaries, and exact
   verification commands. Point plugin work directly to
   `PLUGIN_CONTRACT.md`, `tests/conformance/`, and `plugins/_template/`; do not
   spend agent context on a redundant architecture essay. Preserve existing
   repository-wide safety and evidence rules, using a narrower nested
   `plugins/AGENTS.md` if that is the clearest compliant routing mechanism.

5. **Executable documentation-drift guard.** Fail CI when a governed contract
   or wiring claim diverges from live registration, schema, capability, or
   implementation state—for example, prose that says a plugin is “unwired”
   after production registration exists. Prefer structured markers and parsed
   registries to fragile whole-corpus wording searches. A missing source,
   unparsable claim, or unavailable Git/input receipt fails closed rather than
   silently granting freshness.

   Extend `tests/docs/test_docs_freshness.py` with a structured architecture
   module registry whose exact set equals every tracked
   `src/cryodaq/**/*.py` module, and with contract/template/registration checks
   bound to the obligation registry. Every new source module needs exactly one
   architecture entry; every entry must resolve to a tracked module. Fuzzy
   prose grep is not sufficient.

Existing files are not deleted to simplify migration. Superseded entry points
remain as explicit bounded stubs or are renamed through a reviewed compatibility
step, with deprecation tests and a removal decision recorded separately.

#### Non-negotiable safety gate

An agent may autonomously generate passive parsing, presentation, simulation,
and other non-actuation code only after the conformance suite classifies the
plugin as passive and passes it. Any plugin that declares or can reach
actuation, source authority, interlocks, safety limits, or verified-OFF behavior
requires both:

1. passing the safety-contract/conformance tests; and
2. a valid explicit human approval record bound to the exact safety-manifest
   content hash, schema version, plugin identity/version, reviewer identity,
   and approved scope.

The approval mechanism is fixed by
`docs/adr/002-plugin-safety-human-approval.md`: a detached Ed25519 human
signature binds the canonical manifest hash, schema, plugin identity/version,
approved scope, and reviewer key ID. The trusted key bundle comes from a
protected CI/review environment outside agent-writable pull-request content.
An ordinary marker, a repository-added self-key, or an agent-authored approval
cannot pass. CI fails closed when the signature or protected trust root is
missing, stale, malformed, for a different hash, or outside scope. Passing
software checks does not close the physical bench gate for an actuating plugin.
SafetyManager authority, verified-OFF, persistence-first delivery, provenance,
and independent laboratory acceptance remain unchanged.

#### Sequenced work items

1. Freeze the versioned contract/schema and stable obligation-ID registry.
2. Implement the abstract conformance harness, exact traceability meta-test,
   and weak-model hostile/mutation corpus.
3. Add the passive/unavailable template driver, panel, descriptors,
   registration, golden vectors, and safety manifest.
4. Implement the protected human-signature verifier and negative safety-gate
   matrix without granting the plugin a second actuation path.
5. Enforce exact architecture-module inventory and
   contract/template/registration drift.
6. Activate token-efficient plugin-agent routing and exact commands in
   `AGENTS.md`/a nested plugin scope.
7. Run the model-agnostic pilot and then the full static, Windows, WSL,
   packaging, review, and publication gates on one frozen candidate.

#### Model-agnostic acceptance

- Evaluate the contract with at least one representative mid-tier agent and a
  stronger reference agent on the same frozen plugin tasks. The desired model
  difference is first-try success rate and repair count, not a different final
  pass/fail standard.
- A conformant passive plugin can be generated from the template and repository
  pointers without an architecture reconstruction prompt or hidden maintainer
  knowledge.
- Both `_template` and one real passive instrument plugin generated by a
  representative mid-tier model pass the same conformance suite as a stronger
  reference model. Only first-try success rate and repair count may differ;
  final pass/fail criteria may not.
- Known failure modes in the contract have named automated checks; seeded
  nonconformant plugins are rejected for the intended reason.
- An unsigned, incorrectly signed, or hash-mismatched actuating plugin cannot
  pass CI, even when all ordinary unit tests pass.
- The template, contract, harness, registries, and governance drift together
  only through one reviewed versioned change.
- Run the conformance partitions and the complete `pytest tests/` suite, plus
  the repository's static/platform gates, on the exact candidate. Publish only
  that tested hash under the then-current Git/PR authority.

---

## Montana correction programme after exact-object review (2026-07-22)

> **Scope: campaign-local.** The lane/worktree assignments, CLI-to-Montana
> integration order, proposal freezes, and Montana-to-master sequence below
> govern only this completion campaign. They expire at its final reviewed
> disposition and do not redefine ordinary repository development. The safety,
> authority, identity, persistence, evidence, and regression invariants enforced
> by accepted production guards remain durable product contracts.

The six-commit CLI chain, concurrent `4024f72`, lifecycle-R2, safety/config-R1,
the committed shell chain, launcher, transport, driver chain, and experiment
binding are **REJECTED / NOT APPROVED**. Green focused counts do not override
the independently confirmed P0/P1 boundaries below. Rejection means that no
state may be integrated unchanged or used as evidence. The raw CLI commits must
not become integration parents. The user-authorized `4024f72` Phase A baseline
may remain in ancestry only if a corrective descendant eliminates every
rejected behavior and the reviewer approves the complete range and final tree.
The CLI target is one reconstructed, frozen, green proposal on
`review/montana-cli-corrections-staging`.

### Live two-lane integration checkpoint (2026-07-22)

- The current user transferred all Montana `tests/**` authorship and directly
  required `.github/**` guard wiring to the reviewer for this campaign only.
  Both implementation workers are now product-code-only and froze their current
  test deltas before transfer. The reviewer owns the exact registered guard-node
  paths, must preserve the frozen worker preimages, and may not edit product
  code. Reviewer-authored guards require a separate fresh-context semantic
  review and exact-tree collection check; this exception expires with the final
  Montana campaign disposition and does not redefine ordinary development.
- The active CLI correction lane is isolated at
  `C:\tmp\cryodaq-montana-cli-corrections-staging` on
  `review/montana-cli-corrections-staging`; the Montana lane remains
  `feat/montana-phase-a` in the canonical repository. Two agents must not
  author in one branch or worktree. After the CLI proposal freezes and passes
  review, one integration owner incorporates it into Phase A and all further
  correction continues on Phase A.
- The raw CLI squash contains staged `docs/**` from the rejected source
  object. The CLI worker must not edit or commit those reviewer-owned paths.
  Its proposal and the later integration select only approved implementation,
  test, configuration, and build content; documentation is reconciled by the
  reviewer after the combined implementation tree freezes.
- The 52-path CLI staged-index snapshot is **REJECTED / CORRECTIONS REQUIRED**.
  Exact review confirmed false READY retention, unbound Safety cache freshness,
  absent experiment/incarnation binding, unvalidated queue coalescing, a
  version-1 wire-shape collision, a non-constructible MainWindow/Dashboard pair,
  fail-silent annunciation startup, incomplete QThread settlement, stale disk
  evidence, unescaped backend tooltip identity, dead strict physical-alarm
  production loading, dead T11/T12 binding, and false-success USBTMC closure.
  The worktree began moving during review; only its staged index received this
  disposition and its eventual proposal requires a new frozen-object review.
- Read-only inspection of the moving CLI correction tree still finds the same
  open authority failures: cached Safety READY is not independently
  freshness-qualified; unrelated traffic can grant connection authority;
  strict physical-alarm loading remains outside production; incomplete
  USBTMC/Keithley close can return normally; Dashboard construction calls an
  absent API; disk evidence is not incarnation-bound; annunciation can treat an
  un-emitted event as acknowledged; QThread settlement is incomplete; and an
  old snapshot queue remains expected after cleanup failure. These paths remain
  assigned to the CLI lane and must not be duplicated in Phase A before the CLI
  proposal freezes.
- The moving CLI correction after 2026-07-22 11:28 remains rejected where it
  mints a GUI-side `bridge_instance_id` after receipt and stamps that identity
  onto readings drained from a reused multiprocessing queue. That is not engine
  or producer provenance: a late old-process/feeder item can be relabelled as
  current. The trusted producer/incarnation must be established by the exact
  handshake, carried unchanged through the wire cut, matched before acceptance,
  and paired with fresh per-incarnation queues; consumer code must never invent
  it. Disk freshness tests must inject late old-feeder data after drain/restart
  and prove it cannot acquire the new identity.
- The same moving CLI edit returns generic `{ok: false, error: ...}` after queue
  failure, post-enqueue cancellation, timeout, worker death, or bridge shutdown.
  Post-enqueue cancellation is dispatched/commit-unknown/retry-unsafe and must
  retain action plus request nonce for reconciliation. MainWindow and panel
  teardown also remain incomplete where workers merely wait two seconds, ignore
  the result, or are not interrupted/settled at all. Close must be rejected
  while any owned QThread, reply consumer, process, queue feeder, or callback is
  live; killing a subprocess without a terminal ownership receipt is not clean
  shutdown evidence.
- Adding `DashboardView.set_connected()` fixes the construction mismatch but not
  authority. MainWindow still derives that boolean from any recent measurement
  traffic and the dashboard uses it to enable phase, experiment, log, rename,
  and hide mutations. Data-plane traffic is not command-channel, engine,
  experiment, or Safety-owner authority. Tests that call `set_connected(True)`
  directly are branch checks only. The production gate requires a fresh exact
  engine/bridge handshake plus per-action experiment/lifecycle preconditions;
  unrelated, stale, replay, locally restamped, or foreign readings must never
  enable a mutation.
- Current staging-source focused evidence is red: snapshot/UI 306 passed and 46
  failed; USBTMC/Keithley 45 passed and 23 failed; physical/support 88 passed
  and 6 failed. These counts are diagnostic only. Confirmed P0 defects remain:
  `LiveSafetyReadinessAuthority` accepts cached READY indefinitely and its test
  repeats the same READY revision without age/liveness; ingress batch validation
  checks only type/revision before applying the last member, so earlier members
  may mix producer/mode/experiment; and Keithley OFF verification accepts bare
  numeric zero and non-nonce `print(channel.output)` evidence, allowing replay
  to prove OFF. Connect also lacks strict manufacturer/model/serial validation
  and does not settle `CancelledError` as retained authority.
- Confirmed CLI P1 defects remain: USBTMC close can detach a live close thread
  and misclassify settled cancellation; annunciation accepts
  `event_emitted=False`; TopWatchBar sends untrusted experiment identity through
  QLabel AutoText/raw tooltip; and production still invokes the permissive
  physical-alarm loader while the strict loader remains test-only. Required
  guards use one nonce-bound terminal close/OFF receipt, exact emitted-event ack,
  bounded plain text plus escaped tooltip, and strict production configuration.
  Engine construction must consume the strict loader's cooldown, vacuum, and
  landmark result as one atomic cut; missing, malformed, duplicate, aliased, or
  incomplete production configuration aborts authority publication and may not
  fall back to defaults or a separately warning-only landmark load. Landmark
  validation itself is exact: each canonical channel has only the reviewed
  role/physical/aliases fields with typed trimmed values, no control characters,
  no duplicate or cross-channel alias, and no coercion of arbitrary values to
  strings. The current helper accepts extra landmark fields and alias collisions.
  Stale fixtures must be corrected rather than weakening production: explicit
  `SafetyLifecycle.READY`, coherent cut/summary experiment IDs, schema-v2
  expectations, and top-watch cadence flush.
- Test evidence must pin `PYTHONPATH` to the worktree under test. Earlier
  staging counts that imported the primary editable checkout have zero
  candidate coverage. With staging source pinned, the retained
  lifecycle/ingress/shell partition produced 22 failures and 14 teardown
  errors, and the safety/config/transport/Keithley partition produced
  149 passes and 24 failures. These are correction evidence, not final counts.
- With Phase A source pinned, the matching safety/driver/GUI partition produced
  205 passes and one operator-log contract failure. The broader core partition
  produced 1,375 passes and 13 failures, all in ZMQ command-server supervision
  and serialization/cancellation contract tests. Those failures remain under
  line review and prevent freezing Phase A.
- Primary commit `8ff15811f72b39d532e9e0dec0c33d4858202e55` (tree
  `3bdcffd88de06c1cdb90855146620c7d4a3708be`) is **REJECTED / NOT APPROVED**.
  It commits only five test files while the production changes they exercise
  remain dirty outside the commit. An isolated `git archive` of the exact tree
  fails collection in both RAG test modules because committed
  `assistant_main.py` has no `_RAG_OFFLINE_MESSAGE`. The separately executed
  exact-tree ZMQ selection produced 13 failures and 4 passes; only the changed
  periodic test passed. Working-tree passes import uncommitted production bytes
  and have zero candidate authority. The proposal
  must be rebuilt as one self-contained product+test commit after all P0/P1
  corrections; no amend/replacement inherits approval or prior test evidence.
  The committed periodic test also replaces a deterministic barrier with up to
  five seconds of polling, and the RAG helper tests do not exercise the still-
  reachable live sink/finalization/GUI routes. The ZMQ tests validate envelopes
  but omit the reproduced retained-mutation quarantine and stop-settlement cut.
- Primary proposal `c16cabc363bf9a9dd7eb3148e9c253106f33cfa7`, parent
  `8ff15811`, tree `edb806b322e16a90ac4a89c3eac077fdc40bb074`, is
  **REJECTED / CORRECTIONS REQUIRED**. Its 32 changed blobs and modes match the
  frozen object, but the exact clean export is not self-contained:
  `assistant_main.py:66` imports
  `cryodaq.agents.assistant.shared.context_reader`, while that production file
  remains untracked outside the commit. Exact affected collection fails three
  assistant modules with `ModuleNotFoundError`. The proposal also contains zero
  of the 11 registered exact assistant/integration guard names checked during
  review; 191 selected modified tests passing against the incomplete object are
  false-green evidence, not approval. The correction descendant must include
  every required product dependency and exact guard, then rerun from a newly
  exported committed tree. Worker-reported dirty-worktree counts do not carry
  forward.
- Exact storage/scheduler review independently keeps `c16cabc` rejected.
  Scheduler cancellation drains a shared receipt queue before the shielded
  SQLite owner can settle; a later commit is stranded, can be consumed by a
  different cancellation, and can be silently evicted by `deque(maxlen=1024)`.
  Cold rotation drops operator-log request identity, the outbox has no
  production recovery caller, the keyed registry cap is not enforced at live
  admission, and a legacy stranded index can delete unproven operator rows.
  The production cross-experiment export also omits mandatory experiment
  identity while cold rows carry null identity. Exact-tree selections reporting
  30 scheduler passes and 101 storage passes plus one skip are false green for
  these boundaries.
- Read-only review observed CLI correction descendant
  `870607ffd5776f4235aae1fde10987d803b62f51`, tree
  `fedb481ce874f95b4aae9f17023d60ac9d0acdb9`, directly atop rejected
  `97cff82c`. It is **REJECTED / CORRECTIONS REQUIRED**, and its
  worktree retains 13 forbidden dirty documentation paths. Lifecycle defaults
  and disk-incarnation validation appear fail-closed, but Phase A remains red:
  phase mutation has no locked CAS; quick-log binds to the experiment current
  at execution instead of origin; late ZMQ results have no caller-facing exact
  reconciliation; GPIB drops terminal close intent and never clears successful
  recovery quarantine; Keithley cannot reconcile late close settlement by
  connection generation; assistant insight text remains Qt AutoText; and full
  real-MainWindow QThread teardown is unproven. The prevention registry names
  exact guards for every boundary; no nearby pass count can substitute. A clean
  export contained only 1 of 45 effective CLI guard nodes by exact name
  (parameterized to 2 collected cases); 44 were absent. Reported 179 focused,
  603 driver, and 20x84 passes therefore carry no approval authority.
  Independent line review found an additional P0 false green: the changed GPIB
  bus-lock test explicitly asserts that a handle remains open after cancelled
  connect, then performs an unrelated later manual disconnect. Terminal close
  intent must remain with the retained operation owner and automatically close
  or quarantine that exact generation; cancellation cannot delegate cleanup to
  a future caller.
  Remaining exact-diff review found three P2 replay false greens. Replay accepts
  and persists a noncanonical phase when exact identity is supplied; the
  Telegram test omitted identity and therefore stopped at parser rejection.
  Both replay status commands report session start instead of the exact phase
  transition timestamp, and shallow copies leave nested custom fields aliased
  into internal state. Canonical phase validation, exact transition epochs, and
  recursively detached returned state now have separate registered guards.
  The first moving CAS correction used `threading.RLock` across an awaited
  SQLite append. Because both coroutines run on the same event-loop thread,
  that lock is reentrant rather than mutually exclusive; deterministic
  reproduction entered it from a second coroutine before the first exited.
  `EXPERIMENT-ASYNC-RLOCK-FALSE-GREEN-009` requires an async mutation owner or
  equivalent admission-to-durable-settlement serialization and a barrier test.
  A live exact-name audit after both correction orders found primary 0/61 and
  CLI 1/54 effective registered guard nodes. Moving production edits therefore
  remain useful scaffolding only; another freeze on broad or renamed tests is
  forbidden.
  Moving primary review then found five production-wiring false greens:
  `close()` primitives not invoked by shutdown, dict-aware settlement hidden
  behind a production aggregate Boolean, a validated context cache never used
  by live runtime, report-intro and Telegram redirect paths outside the narrow
  Ollama guard, and query chart/response egress before or despite audit failure.
  Each now has a separate exact guard that must traverse the production caller.
- Independent Phase A line review is **REJECT / CORRECTIONS REQUIRED**. P0
  blockers are: mutation handlers are cancelled on timeout/cancellation without
  retained ownership or admission quarantine; Telegram still discovers and
  dispatches a generic live mutation capability; cold rotation discards durable
  operator-log event/request/fingerprint identity; and the launcher can
  terminate or kill the engine without an exact engine/incarnation-bound
  global-OFF and exit receipt. No focused green count overrides these authority
  failures.
- Phase A also owns the still-open experiment-identity boundary: live and replay
  creation use truncated 12-hex identifiers, reservation is not global, raw IDs
  can alias filesystem paths, delayed update/finalize/abort/recording calls can
  omit the expected experiment ID, and replay/recording receipts are not bound
  to one experiment plus engine/acquisition/archive incarnation. Required tests
  must force cross-day collisions, traversal-like IDs, delayed A-after-B
  mutations, and replay/archive replacement. Current launcher tests that treat
  terminate/kill plus process exit as successful shutdown without exact OFF
  evidence are rejected and earn zero closure.
- Recording lifecycle currently crosses experiment incarnations fail-open:
  terminal/replacement clears only the session ID while retaining acquisition
  and persistence epochs, so an A-era receipt can mark replacement experiment B
  RECORDING. A current test explicitly accepts this and is rejected. Every
  acquisition, persistence, commit, and recording receipt must bind one exact
  experiment incarnation plus engine/acquisition/persistence/feed generations;
  replacement atomically revokes the prior tuple. Replay fingerprints must be
  computed from trusted immutable archive membership and exact blobs, carried
  untruncated in evidence receipts, invalidated on seek/replacement, and stored
  in a structurally separate replay namespace.
- `MONTANA-PERSISTENCE-SHUTDOWN-OWNERSHIP-R1` is P0. The live dirty `engine.py`
  now freezes REP/supervision and starts `stop_safety_manager_with_hold()` before
  draining experiment/read/operator-log owners, correcting the previously
  reproduced observational-drain-before-OFF ordering. This is moving-tree
  evidence only and remains open until one frozen proposal proves the order with
  a blocked operator-log owner and repeated cancellation. Persisting owners stay
  retained with their dependencies in a visible post-OFF persistence HOLD until
  terminal settlement; no clean exit or stopped receipt is emitted early, and
  the safety OFF owner/internal HOLD never waits behind observational storage.
- SQLite cancellation is also a retained-authority boundary. `write_committed`
  currently loses its await/receipt path while the executor transaction keeps
  running; Scheduler treats the cancelled poll task as settled, and recording
  lifecycle emits acquisition/persistence stopped before `writer.stop()` waits
  for that abandoned executor work. Deterministic reproduction produced
  `persistence_ambiguous`, `acquisition_stopped`, and `persistence_stopped` with
  zero rows, then one late row and zero receipts after release. The existing 25x
  cancellation test codifies only “no receipt” and is rejected. Required guards
  cut before BEGIN, during transaction, after commit/before receipt, shutdown,
  and restart; one retained owner yields one final receipt/reconciliation state,
  and no stopped claim precedes settlement.
- Writer shutdown must freeze new submissions and retain every write, operator-
  log read, history read, and safety callback independently of its caller''s
  cancellable waiter. Dedicated executor shutdown currently has no real bound,
  and a blocked read reproduction kept `writer.stop()` pending after its waiter
  was cancelled. Deadline expiry enters an explicit process-retaining
  persistence HOLD; it never returns a stopped result. Tests block each executor
  lane, saturate the default executor, cancel repeatedly, and prove settlement
  or visible HOLD without a late row, callback, or file side effect.
- Production operator-log deduplication must use the durable writer authority,
  not the engine context''s bounded process-memory dictionary. Startup builds and
  validates the retained request registry before accepting commands; the real
  command calls the idempotent append API with an owner-defined canonical
  SHA-256 that excludes transport credentials. Response loss, restart, rotation,
  identical retry, and conflicting retry are tested through the actual command
  path and real SQLite writer.
- Terminal sink delivery requires a durable per-sink outbox. The current
  cancellation-based drain can return while a detached `to_thread` file sink
  creates its side effect later, and webhooks carry no stable idempotency
  identity. Persist event ID, canonical payload hash, attempt, outcome-unknown,
  and terminal receipt before reporting reconciliation success; never claim
  drain completion while a local thread can still write or a remote outcome is
  unknown.
- SQLite persistence-failure callbacks are safety-owned work. The writer
  currently retains only a done callback for `run_coroutine_threadsafe`, so
  `writer.stop()` can return before the SafetyManager callback completes.
  Retain, settle, or explicitly transfer every callback before either owner is
  torn down; blocked, failed, cancelled-stop, and late disk-full cuts are
  mandatory.
- Safety-child settlement remains rejected: child death, shutdown HOLD, caller
  cancellation, and operator retry can currently create overlapping global-OFF
  operations against one driver, and one focused test explicitly requires a
  third OFF while the retained second OFF is blocked. Two child deaths require
  two durable incarnation-bound terminal receipts but exactly one shared live
  global-OFF owner. Audit persistence failure must retain HOLD rather than mark
  settlement complete; safety restart counters require an exact
  generation-bound health receipt rather than elapsed time; and a failed
  supervisor adoption must cancel/await the newly spawned task transactionally.
- The current ZMQ supervision edit is itself rejected where it expects a second
  unknown command to succeed after a timed-out unknown command: both actions
  fail closed to MUTATION. The required guards must separately prove that an
  ordinary second mutation is rejected, a declared READ remains available, and
  only the exact emergency-OFF safe-direction command remains admitted while
  authority is quarantined. A passing test that relabels or preserves the
  unsafe second-mutation admission earns zero closure.
- Reviewer decision `MONTANA-GLOBAL-OFF-SCOPE-R1`: an omitted channel on the
  public `keithley_emergency_off` command means **global both-channel OFF**.
  Explicit `smua` or `smub` remains a visibly scoped target OFF. The current
  command path normalizes omission to legacy `smua`, while its API advertises
  the channel as optional; that ambiguity is rejected. Receipts state
  `scope=global` or the exact channel, and a failed channel proof can never
  satisfy a global receipt. Tests begin with both channels active and prove
  omitted scope owns and verifies both outputs; explicit scoped requests prove
  only their named channel and do not clear global HOLD.
- ZMQ cancellation guards must not wrap their assertions in a broad
  `except Exception`; swallowing `AssertionError` makes an optimistic reply
  pass vacuously. The REP invariant is at most one send attempt per accepted
  receive, with exactly one on ordinary and encoded-error paths; cancellation
  or a failed send must never trigger a second best-effort send on the poisoned
  socket.
- Phase A P1 corrections also remain mandatory: stable REST idempotency across
  response loss/retry; root-anchored no-follow assistant audit/retention I/O;
  exact assistant engine/protocol identity and closed decoding; offline-only RAG
  rebuild tests; total GUI classification of dispatched/unknown/retry-unsafe
  mutation outcomes; and current-context control recovery after stale
  experiment callbacks. The stable GUI partition produced 460 passes, but it
  lacks the canonical uncertainty-envelope regressions and therefore is not
  closure evidence.
- `MONTANA-ALARM-ACK-SETTLEMENT-R1` is a P0 correction. The current engine
  mutates alarm state before awaiting event publication, while `alarm_v2_ack`
  uses the fast cancellable REP tier. A timeout after state commit but before
  publication can therefore lose the only acknowledgement event; retry then
  returns success with `event_emitted=False`. One retained mutation owner must
  settle state plus a durable outbox/event, keyed by a stable request nonce and
  canonical payload hash. Duplicate nonce plus identical payload returns the
  same final receipt; duplicate nonce plus different payload conflicts. Guards
  must cut cancellation/response loss before commit, after state commit, during
  publication, and after publication, and prove exactly one state transition,
  exactly one event, and one identical durable receipt.
- `MONTANA-WEB-WRITE-RECEIPTS-R1` must also close HTTP outcome semantics. A
  committed receipt maps to 2xx; validation/stale/payload conflicts map to 4xx;
  definitely-not-dispatched maps to 503; and dispatched outcome-unknown maps to
  502/504 while preserving delivery, commit, retry-safety, request, and
  reconciliation identity. No post-dispatch exception may collapse to a
  generic 502. The current compatibility token is not action, payload, caller,
  or commit authority and must never satisfy a commit-receipt validator.
- The GUI transport must preserve that same envelope. A queue-full failure
  before enqueue is `not_dispatched/not_committed/retry_safe`; every timeout,
  worker death, malformed reply, token rotation, cancellation, or response loss
  after enqueue is `dispatched/commit_unknown/retry_unsafe` and retains action
  plus request nonce. Localized error-string parsing is not a protocol and no UI
  may auto-replay an unknown mutation. Required guards exercise the real
  exception branches rather than injecting a preconstructed unknown reply.
- GUI correlation IDs are full 128-bit nonces bound to bridge incarnation and
  cannot overwrite a pending entry; forced nonce collision regenerates or
  rejects before dispatch. Shutdown retains every already-enqueued mutation
  reconciliation owner and may not replace it with a bare bridge-shutdown
  error or drop its late reply. Every mutation surface (Dashboard, experiment
  overlay, MainWindow create, alarm panel, operator-log panel) accepts success
  only from one exact action/experiment/incarnation/request/payload/revision
  commit receipt. Bare `ok`, extra/missing keys, wrong scope, stale worker
  replies, and committed-reconciliation-failed never render Engine-confirmed.
- Telegram mutations obey the same contract. `/log` and `/phase` derive one
  stable request identity from the exact chat/update/message and semantic
  payload, require its exact durable receipt, and classify transport failure as
  pre-dispatch or outcome-unknown. Redelivering one update sequentially,
  concurrently, after timeout, and after restart produces one log row or phase
  transition and the identical receipt; missing update identity fails closed.
- Every experiment mutation requires the exact expected experiment ID and
  manager/experiment incarnation at the engine boundary; missing or blank IDs
  fail before dispatch. Commit receipts require engine/manager incarnation,
  request nonce, canonical payload hash, resulting revision, and durable
  side-effect status. Same nonce plus same payload returns the same receipt;
  same nonce plus different payload conflicts; replacement between validation
  and commit fails. Tests cover omitted IDs, finalized-ID reuse, external-ID
  reuse under a new incarnation, replacement races, and lost replies.
- Experiment identity authority must also survive process and storage boundaries.
  The current process-local lock does not serialize two engines, and transition
  journals carry no manager incarnation, transition UUID, or expected
  predecessor tuple before blindly setting or clearing active state. A durable
  CAS authority must fence every transition by manager incarnation, exact active
  ID, monotonic revision, and operation identity; a stale A journal observed
  after B exists is quarantined and never mutates B. Real two-process collision
  and injected stale-journal tests repeat 20 times.
- Twelve-hex-character experiment IDs are rejected. Daily SQLite primary keys do
  not provide a global reservation, while artifact paths are global by ID, so a
  duplicated UUID prefix across dates can overwrite metadata. Use a canonical
  full-width identity and one atomic reservation spanning every daily database
  and artifact root before any write. One canonical parser rejects traversal,
  separators, drive/UNC/ADS forms, reparse escape, metadata-directory mismatch,
  and duplicate in-root aliases at every load/attach/list API. Forced collision
  and hostile-path guards prove zero pre-existing or outside bytes change.
- Experiment evidence cannot be inferred from a time window. Hot reading rows
  currently carry no experiment or recording epoch, yet export decorates them
  with the caller-selected ID; cold rows remain unbound. Every committed reading
  and persistence receipt must carry manager incarnation, experiment ID,
  acquisition epoch, and persistence epoch at commit time. Experiment change
  terminalizes and rotates those epochs; late A data after B remains rejected or
  explicitly unbound and can never make B RECORDING. Overlapping and retroactive
  windows, delayed commits, manager restart, and old receipt replay are required
  guards, with `(manager_incarnation, revision)` as the only snapshot ordering
  key and no success receipt lacking an exact post-commit tuple.
- Replay identity is computed by the owned archive adapter from the exact opened
  bytes/manifest, never accepted as caller decoration. The full digest,
  unforgeable session identity, seek epoch, and per-row origin bind namespace and
  receipts under handle/TOCTOU protection. Distinct archives cannot share an
  identity even under forged caller input; mutation between fingerprint and read
  fails closed; restart and seek ordering remain exact. Replay stays unwired
  until those gates pass.
- Production operator-log idempotency is still process-memory-only even though a
  durable writer API exists: the engine neither initializes nor uses that API,
  and rotation removes the request identity needed after restart. The
  observational correction must also remove the live-engine RAG rebuild sink,
  reject non-loopback assistant/model endpoints before socket/session creation,
  and structurally prevent assistant output from owning an EventLogger,
  SQLiteWriter, mutation token, or generic command dispatcher. Constructor
  wiring alone is not a prevention gate.
- The current RAG rewrite is still rejected despite 29 focused RAG/GUI passes.
  Assistant private helpers now reject rebuild, but production still imports and
  registers `RAGIndexSink` from `sinks.rag_index`, and experiment terminal
  reconciliation dispatches that sink into `build_index`. The GUI also still
  enables rebuild, dispatches it, polls, and its tests require optimistic
  running/complete states. Live configuration and experiment finalization must
  be structurally unable to call `build_index`; index construction is an
  offline CLI-only operation. Acceptance requires an enabled live sink config
  plus real finalization/routing test that proves zero build dispatch, and a GUI
  test proving an offline-only disabled presentation with zero polling.
- Assistant/model egress is loopback-only by construction. `AssistantConfig`,
  `OllamaClient`, report-intro generation, and RAG indexing currently accept
  arbitrary base URLs and can send complete prompts or experiment text to a
  remote endpoint. Validate one normalized loopback origin before creating any
  socket/session; redirects, alternate schemes, userinfo, wildcard names, and
  DNS-derived trust are rejected. Knowledge-base result text and source metadata
  are untrusted plain text: no AutoText/rich interpretation, and adversarial HTML
  and control-text fixtures must render literally within bounded lengths.
- Assistant egress is persistence-first and receipt-backed. Today GUI/Telegram
  output can occur before audit persistence, Telegram HTTP failures are
  swallowed, and the router labels a target dispatched merely because its
  callback returned. Persist one egress intent and canonical payload hash before
  output; record exact per-target success/failure/outcome-unknown under the same
  audit ID. Audit failure yields zero egress, and HTTP error/timeout is never
  presented as delivered. Telegram text is escaped or sent as plain text before
  applying any tiny reviewed formatting allowlist.
- Assistant audit/retention paths must be safe under Windows reparse points and
  validation/use races. Canonically anchor ownership to the data root, reject
  every symlink/junction/reparse component, enumerate and delete through stable
  no-follow handles, and revalidate identity at use. Non-skippable junction and
  deterministic directory-swap guards prove no outside write or deletion.
  Retained audit I/O is joined before assistant stop; a retention setting is
  either wired to one safely owned housekeeping task or removed.
- Assistant observational authority is structural, not constructor convention.
  Remove `EventLogger`, SQLite writer, operator-log persisted branches, mutation
  capability, and mutation command names from the assistant runtime API and
  enforce that with imports/AST guards. Engine context caches carry producer,
  observation time, and TTL; poll failure makes old experiment/sensor context
  explicitly stale instead of phrasing it as current truth.
- The affected RAG formatting gate is also red: `ruff check` passed, but
  `ruff format --check` rejected `src/cryodaq/agents/assistant_main.py`,
  `src/cryodaq/gui/shell/overlays/knowledge_base_panel.py`, and
  `src/cryodaq/sinks/registry.py`. The periodic-PNG edit only increases a poll
  allowance from 100 to 5000 iterations; it passed 20 repetitions but does not
  alter production settlement and should use a deterministic completion barrier
  or explicit wall-clock deadline before freeze.
- Conductivity automatic advance is rejected in the current tree. Generic
  any-reading connectivity enables the sweep; cached predictor results and bare
  cached temperatures can advance it; target success lacks measured readback;
  and recorded power is the commanded value. Until operator/hazard review
  freezes PAUSE/HOLD versus verified STOP/OFF, production auto-advance must be
  unavailable. Safety-critical channel or Keithley-heartbeat freshness loss
  always remains FAULT plus verified OFF. Verified STOP/OFF is the reviewer
  recommendation; PAUSE requires a separately justified bounded safe-hold
  envelope and cannot override safety-critical loss.
- Current conductivity tests are themselves rejected where they enable Start
  from `set_connected(True)`, advance from a monkeypatched predictor plus bare
  cached temperatures and `{ok: True}`, or record commanded power as measured
  evidence. Replacement guards require reviewed-source READY bound to the exact
  experiment/incarnation, fresh power authority, request/connection-generation
  target acceptance, and timestamped measured V/I/P provenance. Until the
  governing policy is frozen, the literal production Start/auto-advance path
  remains unavailable.
- Conductivity completion is not authoritative while a bare `{ok: True}` can be
  rendered as both target settlement and OFF confirmed. Stop requires one
  immutable receipt binding action, request/operation nonce, experiment,
  channel/source generation, engine incarnation, resulting lifecycle revision,
  and `verified_off=true`; generic success remains UNKNOWN with the guard active.
  The exposed `is_auto_sweep_active()` currently has no production consumer, so
  an active sweep also fails to block experiment finalization. Any future
  re-enable requires a backend-owned operation lease that rejects finalize and
  competing manual/automation target changes until exact OFF/terminal
  settlement. Flight/table/export evidence retains values only as visibly stale
  or unavailable unless status, source/arrival time, descriptor, producer,
  experiment, incarnation, and finite post-command V/I/P/T provenance form one
  current cut. Closing the panel/application must request cancellation and join
  every real command QThread; a blocked-reply loopback gate repeats closure 20
  times with zero live QThreads, late callbacks, access violations, or lost
  outcome-unknown/OFF receipts.
- Shutdown evidence based on fake processes, fake QThreads, no-op bridges, or
  one-call assertions earns zero closure. The gate requires a real loopback
  bridge child, queues/feeders, actual QThread/ingress owner, application close,
  retained handles until every process/thread is stopped, zero late callbacks,
  and 20 clean repetitions in one unsplit process. Likewise, a private-method
  RAG test cannot close routing: the production GUI must disable/relabel live
  rebuild as offline-only and an end-to-end assistant/engine/UI guard must prove
  no dispatch, polling, or optimistic running/complete state. Launcher signal
  registration requires a behavioral resource-settlement test, not source-text
  occurrence checks.
- Test exception contracts are exact. Experiment concurrency guards must not
  accept arbitrary `BaseException` as the expected loser; Keithley safety tests
  must not use `pytest.raises(Exception)`; and GPIB cleanup must suppress only
  the expected cancellation type and re-raise earlier task failures. Telegram
  idempotency must prove identical chat/message redelivery produces one stable
  request ID, one durable row, and one identical receipt under sequential and
  concurrent delivery. Random-ID shape checks are insufficient.
- `FALSE-GREEN-001` is a merge-blocking test obligation. Every confirmed
  deterministic reviewer reproduction becomes a named automated regression that
  fails against the pre-fix production behavior and passes only after the owning
  correction. The correction commit contains production code and its regression
  atomically. A broad exception that can catch `AssertionError`, a cooperative
  sleep substituted for a cancellation-resistant owner, a fake QThread/process
  substituted for a real loopback owner, or an assertion limited to elapsed time
  or call count is non-probative and must be replaced. Tests that explicitly
  bless unsafe behavior are deleted or inverted; their former green count earns
  zero closure. Required primary regressions cover mutation quarantine plus
  READ/global-OFF admission, stop waiting for a resistant late handler, shared
  global-OFF coalescing, Windows launcher death without a receipt remaining
  HOLD, operator-log rotation/restart and publication outbox replay, alarm-ACK
  publication recovery, and persistence-stopped waiting for executor/callback
  settlement. Required CLI regressions cover READY expiry, atomic mixed-identity
  batch rejection, old-child queue rejection, post-enqueue reconciliation,
  nonce collision refusal, telemetry not enabling Dashboard mutations, real
  QThread close settlement, `event_emitted=False` not silencing, plain-text
  identity rendering, strict production config wiring, and retained USBTMC/GPIB
  close ownership. Race/cancellation/shutdown regressions run 20 times in one
  unsplit process and assert zero live threads, processes, late callbacks, or
  post-stop effects.
- An independent stable CLI selection reported 147 passed while three current
  tests or omissions still bless unsafe authority. Dashboard tests pass
  `experiment_id=None` and rely on default READY before enabling mutations;
  ingress tests accept source/mode transition without explicit producer
  replacement; and
  `test_bad_serial_with_unverified_off_retains_recovery_without_identity`
  requires `connect()` to raise while `connected is True`. The ZMQ client
  also retains successful replies forever in `_pending` and moves late results
  into an unreachable future. Replace or invert these expectations with exact
  Dashboard identity, explicit replacement, partial-connect recovery receipt,
  successful-owner removal, and late-reconciliation tests. The 147 count earns
  no closure.
- Typed lifecycle propagation is also incomplete while
  `ReadinessSummary.lifecycle` and `SafetyReadinessReceipt.lifecycle` retain
  constructor defaults and Dashboard defaults directly to READY. MainWindow
  still converts the legacy `analytics/safety_state` string set into Keithley
  mutation permission, and BottomStatusBar performs substring rendering on raw
  strings. `CLI-LIFECYCLE-DEFAULT-FALSE-GREEN-004` and
  `CLI-SHELL-TELEMETRY-AUTHORITY-FALSE-GREEN-005` require explicit typed values
  at every constructor and shell boundary; observational analytics traffic can
  never grant mutation authority.
- `PERSISTENCE-RECEIPT-RECONCILIATION-005` records the 2026-07-22 persistence
  correction escape: focused tests passed, including 30 scheduler cases at
  exact proposal `c16cabc`, while scheduler cancellation
  drained retained receipts before a shielded SQLite write finished, leaving
  the eventual commit receipt without a consumer. The current bounded
  `maxlen=1024` receipt deque can also silently evict proof. Correction requires
  exact batch/command-keyed late reconciliation, capacity exhaustion that fails
  closed without eviction, synchronous stop admission closure, a deterministic
  blocked-commit/cancel/release scheduler regression, and 20 unsplit
  repetitions. Immediate best-effort draining is not settlement. A second
  independent review found that `scheduler.py` also checks receipt cardinality
  without binding committed content: the current
  `test_scheduler_commit_receipts.py` substitutes value `2.0` for admitted value
  `1.0` and passes. `PERSISTENCE-RECEIPT-CONTENT-FALSE-GREEN-003` therefore
  requires exact admission ID, ordered input fingerprint, producer/experiment
  generation, and receipt-owner equality; a same-length different receipt must
  never settle or publish the admitted batch.
- Exact `c16cabc` storage review also confirms three independent false-green
  boundaries. `OPLOG-COLD-IDEMP-001` requires request identity to survive
  rotation/restart, live keyed capacity to fail closed before admission, and
  stranded deletion to prove every operator row was archived.
  `OPLOG-OUTBOX-002` requires a production-wired startup recovery owner rather
  than tests that call storage helpers directly. `EXP-RECEIPT-PROVENANCE-009`
  requires every hot/cold archive and cross-experiment export caller to provide
  and validate a non-null expected experiment ID. The exact named guards in the
  prevention registry must reproduce each failure before correction and pass
  afterward.
- The live GPIB correction remains **REJECT / CORRECTIONS REQUIRED** even though
  its pinned focused selection reports 10 passed. `GPIBTransport.close()` clears
  handle/resource-manager ownership before close settlement, converts a close
  exception into apparent success, and can return after a one-second timeout
  while its detached `gpib-close` thread remains live. A deterministic
  double-open reproduction opened two resources, leaked the first, and closed
  only the second. Close during an in-flight executor operation can also report
  success while the operation remains live; manager-wide cleanup suppresses
  failures and then discards the only retained owners. Query provenance loss
  still admits arbitrary ordinary writes, while the current test incorrectly
  blesses generic `OUTPUT 0` as recovery; only typed bus clear/IFC is admissible
  until settlement. Conversely, the desynchronization bit never clears after a
  verified clean close and fresh generation, so the current test also blesses
  permanent poison instead of reviewed L3 recovery. `MONTANA-GPIB-SETTLEMENT-R1`
  requires one locked lifecycle/generation owner, atomic sequential and
  concurrent already-open rejection, retained handles and resource-manager
  ownership through exact close settlement, typed incomplete-close/desync/
  unsettled receipts, a bounded owned reaper, and propagation of incomplete
  truth to every instrument owner. Poisoned generations permit only typed
  clear/IFC; verified clean close plus fresh open clears poison, but incomplete
  close never does. The gate repeats double-open, close raise/timeout/late
  settlement, cancellation-resistant I/O, stale reply, and recovery 20 times
  and proves zero live transport/close threads and zero late callbacks.
- The CLI correction lane remains **REJECT / CORRECTIONS REQUIRED**. Proposal
  commit `97cff82c047f8fb39262c16d2088dd8bf346c13f`, tree
  `f03e3224739eabb938af076c1243fc30bd7fb21b`, parent `4024f72`, was created
  while registered exact guards were absent and independently reproduced
  lifecycle-default, shell-authority, reply-consumer-generation, real-QThread,
  plain-text, and disk-freshness blockers remained. The proposal is therefore
  rejected, not an integration parent. Its 13 residual dirty/untracked
  `docs/**` paths are outside the commit and remain outside CLI implementation
  ownership. A corrective proposal must preserve the rejected object, add a new
  traceable commit, prove every registered node collectable and green, and bind
  its evidence before another freeze. A real
  queue reproduction proved that `ZMQBridge` reuses its data queue across child
  replacement and stamps an old-process reading with the newly GUI-minted
  bridge ID only after dequeue. Every child incarnation requires fresh command,
  reply, snapshot, and data queues; producer/process identity is bound before
  enqueue by the producing authority and is never post-hoc relabeled by GUI.
  Complete-batch ingress validation rejects any mixed producer, engine,
  experiment, mode, or incarnation member before applying any member.
- Dashboard mutations must not derive authority from arbitrary recent reading
  traffic. Controls start disabled and require one current authoritative engine,
  producer, experiment, and lifecycle session; stale telemetry, legacy queues,
  replay, and system/analytics traffic never establish live mutation authority.
  A current focused run still has two Dashboard gate failures.
- GUI command settlement is P0. A deterministic reproduction enqueued a command
  and then returned an ordinary cancellation with no dispatch/commit/retry or
  request identity. Pre-enqueue cancellation is definitely-not-dispatched;
  every cancellation, timeout, worker death, malformed reply, or response loss
  after enqueue is outcome-unknown and retains nonce, action, payload hash, and
  a reconciliation lookup. Removing the pending correlation is forbidden until
  terminal settlement is durably owned.
- Reply-consumer replacement is part of that settlement. `ZmqBridge.start()`
  currently waits one second, discards the old consumer reference without
  proving it stopped, replaces queues, and clears the shared stop event; a late
  old consumer can therefore resume on the new generation's queue.
  `CLI-REPLY-CONSUMER-GENERATION-FALSE-GREEN-006` requires terminal old-consumer
  settlement before queue replacement and 20 blocked-consumer repetitions.
- Shell shutdown is not closed while any real QThread can outlive its owner.
  Dashboard has no worker-aware close path, TopWatchBar''s close path is a no-op,
  and MainWindow waits one worker without requesting interruption or checking
  success. Every owner stops timers, requests interruption, performs a checked
  bounded wait, ignores close while any worker is live, and suppresses all late
  callbacks. Acceptance closes the real top-level application 20 times in one
  unsplit process with zero live threads or teardown warnings.
- Disk evidence has its own authority clock. Current shell logic ages it only
  when all measurement traffic disconnects, so unrelated live readings can keep
  an old disk cut current; bridge replacement can also leave the prior cut
  visible. `CLI-DISK-EVIDENCE-FRESHNESS-003E` requires producer/bridge
  incarnation, monotonic ordering, independent expiry, and immediate revocation
  on replacement.
- Operator-snapshot provenance keeps stable source namespace separate from an
  explicit engine-owned process incarnation. A composer-minted random value is
  not an independently injected engine identity and must not populate both
  `source` and `producer_id`. Store replacement is allowed only by an explicit
  reviewed incarnation transition; ordinary cuts cannot silently replace the
  established producer.
- The latest driver correction is only partial. The fresh nonce-bound
  `CRYODAQ_OFF_V1` readback closes the replayable bare-zero defect, but
  `connect()` still accepts any `*IDN?` string containing `2604B`; it must parse
  and exactly match configured manufacturer, model, and serial. Cancellation
  during ID query/force-OFF/watchdog setup currently bypasses the `Exception`
  cleanup path and can leave the transport open with no connected owner. A
  completed handle close that observes caller cancellation is also deliberately
  relabeled incomplete by a test, while a timed-out close detaches an inner
  daemon thread. Retain the exact handle owner through terminal settlement,
  close on every connect cut, publish one truthful closed/incomplete result,
  propagate cancellation only after state reconciliation, and block reconnect
  only while close outcome is genuinely unresolved. Repeat cancellation before
  and after each ID/OFF/close boundary 20 times with zero late thread/assertion.
- Reviewer decision `MONTANA-KEITHLEY-IDENTITY-RECOVERY-R1`: parse and exactly
  validate the configured manufacturer/model family before any TSP mutation.
  For that recognized family only, global safe-direction OFF may precede final
  serial acceptance. The returned serial must then exactly equal the configured
  USB identity (`04052028` in the current production config); a structurally
  valid different serial is not authority. If mismatch follows verified OFF,
  close and fail connection without publishing identity. If OFF cannot be
  verified, retain the handle in recovery-only quarantine under a live owner;
  expose no connected/RUN identity and admit only nonce-bound global OFF and
  settlement until terminal proof or visible HOLD. Never raise in a way that
  loses the sole recovery owner.
- Documentation freshness is red at 17 passes and 3 failures: tray-status is
  untracked, the Montana SVG index omits two files, and report metrics are stale.
  The experiment outcome wording guard is now green. Regeneration is deferred
  until all implementation authors are quiescent and one frozen index exists.
- `EVIDENCE-BINDING-001` is open. Windows ONEDIR smoke currently executes a
  copied runtime tree but hashes/uploads the original distribution without an
  equality receipt; its evidence omits HEAD tree, PR head-versus-merge identity,
  run attempt, and tested-artifact digest; one frozen boundary imports Job
  Object code from the host checkout; and ambient Python/runtime variables are
  inherited. Nightly runs the weaker legacy soak driver, while main CI uses only
  an editable install. Before PR evidence can count, uploaded bytes must equal
  executed bytes, every receipt must bind commit/tree/workflow/dependencies,
  frozen runs must prove zero source leakage, wheel and sdist must pass isolated
  installs, and 12/72-hour profiles must remain explicitly open until genuinely
  executed.
- Exact evidence acceptance additionally requires a canonical manifest of the
  copied execution tree before launch, equality with the source artifact, all
  mutable runtime configuration/data outside that tree, and a post-run rehash
  of the same executed bytes. Frozen code may not import Job Object or any other
  helper from the host checkout. Child environments are constructed from an
  allowlist and are tested against hostile `PYTHONPATH`, `PYTHONHOME`, home,
  user-site, plugin, preload, and credential-shaped variables. Candidate product
  upload occurs only after a validated PASS; `if: always()` is reserved for a
  distinctly named diagnostic artifact. The external run receipt binds committed
  and checked-out commit/tree, PR head and synthetic merge objects, workflow
  digest, event/ref/job, run ID, attempt, candidate digest, and upload digest.
  Wheel and sdist each install into an isolated checkout-free environment, and
  the sealed full-stack short profile replaces the legacy engine-only nightly
  as qualification evidence; 12/72-hour gates remain open until actually run.
- The current primary working diff passed full-tree `git diff --check` at
  2026-07-22 11:29 +03:00 after the RAG test EOF defect was corrected. The
  command still reports CRLF normalization warnings on existing paths. This is
  moving-tree hygiene evidence only; it neither freezes the candidate nor
  closes the semantic blockers and must be rerun on the proposal object.
- `AUTH-HANDSHAKE-006` replaces the failed per-slice path/blob-token workflow.
  A direct worktree-scoped mandate now grants autonomous dependency discovery
  within implementation surfaces; no special `AUTHORIZE` grammar,
  password-like token, input-blob list, or lease file is required. Proposal
  freezes, cross-worktree ownership, governing paths, secrets, hardware, Git
  publication, and independent review remain fail-closed.
- `PARALLEL-PATH-OWNERSHIP-001` corrects an overlapping reviewer instruction
  issued on 2026-07-22. Until CLI freeze/review/integration, the primary worker
  owns persistence/storage, assistant/RAG, and governance-guard implementation;
  the CLI worker owns lifecycle, snapshot, experiment, ingress, transport
  drivers, GUI, disk authority, and their tests. Shared `engine.py` work is
  edited by the CLI lane during this tranche; primary preserves its existing
  dirty bytes without further overlap. After approved CLI integration, all
  remaining shared corrections transfer serially to the single primary Montana
  lane. The standing mandate never implies dual ownership. Durable registry
  owners are maintenance defaults, not active edit permission. The exact
  `MONTANA-INTEGRATION-SEQUENCE-001.campaign_edit_owner_overrides` map assigns
  `src/cryodaq/core/experiment.py`, `src/cryodaq/engine.py`,
  `tests/core/test_experiment_adversarial.py`,
  `tests/core/test_experiment_commands.py`, and
  `tests/gui/shell/views/test_assistant_insight_panel.py` to the CLI editor for
  this tranche; it overrides durable owners for authoring only and expires with
  the campaign disposition.
- `AGENT-CONTEXT-COMPACTION-001` is the universal compaction-resilience gate.
  Every long-running Montana role owns one ignored, non-authoritative capsule at
  the exact campaign-local path in the implementation-agent contract. A capsule
  never grants authority or approval. Missing or stale state requires read-only
  live reconstruction and exact root/branch/HEAD/tree/governance/ownership
  revalidation before authoring or review claims. The reviewer capsule now
  exists; the primary and CLI worker capsules plus the implementation-owned
  schema validator remain open.
  A status-only digest is forbidden: the reviewer reproduced an identical
  porcelain-status digest across changed dirty source blobs. Each capsule must
  additionally hash a canonical sorted path/mode/current-blob manifest for its
  owned paths, and the validator must deterministically reject a changed dirty
  blob even when status text is byte-identical.
  The reviewer then produced a capsule with noncanonical nested mapping order
  and a prose forbidden-path entry. Independent validation rejected it.
  `AGENT-CONTEXT-CANONICALIZATION-FALSE-GREEN-002` requires recursive canonical
  ordering and normalized path-pattern rejection in the tracked validator.
- `MONTANA-GOVERNANCE-GUARDS-R1` is assigned to the primary implementation
  lane after its current safety-critical source edits stabilize. It adds only
  implementation-owned guards, not governing prose:
  `tests/governance/test_agent_preventions.py`,
  `tests/governance/test_agent_context_contract.py`,
  `tests/governance/test_candidate_evidence_binding.py`,
  `tests/governance/test_montana_integration_contract.py`,
  `tests/governance/test_standing_lane_authority.py`, and
  `tests/test_ci_candidate_evidence.py`. The tests must validate schema-v2
  fields and unknown-field rejection; globally unique record/coverage IDs;
  resolved runtime-to-false-green links; collectable exact guard nodes in their
  declared default-CI partitions; campaign expiry/final-disposition semantics;
  wrong-root/branch/role/forbidden-path rejection; ignored one-writer context
  capsules; missing/stale/moved/duplicate-writer/secret-shaped fixtures; exact
  committed-tree execution; and separate CLI, Montana, and master integration
  freezes. Malformed fixtures must fail closed, and the validator may not inspect
  or depend on live ignored capsules during ordinary CI.
- `GOVERNANCE-ARTIFACT-TRACKING-001` remains open until the final
  reviewer-owned governance commit deliberately includes ADR 003, the Montana
  implementation contract, both governance YAML schemas/registries, and their
  implementation-owned validators. ADR 003 is currently hidden by a local
  `.git/info/exclude` rule and the other new governance artifacts are untracked;
  ordinary status therefore cannot prove candidate inclusion. Do not edit the
  local exclude file or stage into the moving implementation index. At the
  frozen governance-commit gate, the integration owner must add the exact
  reviewed files explicitly, verify the staged manifest and blobs, and reject
  any omitted authority artifact.
- `MONTANA-PREMATURE-PROPOSAL-FALSE-GREEN-001` records the CLI worker mistake of
  freezing `97cff82c` while known blockers and absent registered guard nodes
  remained. `MONTANA-INTEGRATION-SEQUENCE-001` now requires proposal-freeze
  evidence to prove that every registered guard node is collectable in its
  declared default-CI partition and green on the exact candidate tree. A local
  commit, worker DONE sentinel, nearby green suite, or reported aggregate count
  cannot satisfy that gate.
- The 2026-07-22 live collectability checkpoint initially counted durable
  record owners and found 0/59 primary and 1/34 CLI nodes. That census mixed
  durable maintenance with temporary edit authority and would have forced four
  cross-lane guard edits. After applying the exact campaign overrides and two
  new enforcement nodes, the effective campaign census is 0/57 primary and
  1/38 CLI by exact file/node name. A lane proposal requires only its effective
  edit-owned changed-path/known-finding closure; another lane's node is an open
  dependency, never authoring permission. The combined Montana freeze requires
  the union plus integration/governance guards, and the final PR/master gate
  requires the complete candidate closure.
- `PARALLEL-GUARD-OWNER-OVERRIDE-FALSE-GREEN-001` records the reviewer mistake
  of treating durable `guard_owner` as current lane authority.
  `MONTANA-LANE-FREEZE-SCOPE-FALSE-GREEN-003` records the related mistake of
  using all-registry counts as a bounded lane-proposal gate. Their exact guards
  enforce one effective editor per path/node and distinct lane, combined, and
  final-candidate guard scopes.
- `AGENT-CONTEXT-ORDINAL-SORT-FALSE-GREEN-003` records the reviewer capsule
  digest mistake found by independent validation: PowerShell's default
  case-insensitive path sort produced a different owned-manifest digest from
  cross-platform ordinal order. The implementation validator must construct
  manifest records using byte-stable ordinal normalized-path ordering on every
  supported host and reject a capsule whose digest was produced with
  locale-sensitive or case-insensitive ordering.
- `MONTANA-AFFECTED-PARTITION-FALSE-GREEN-002` records that `97cff82c` was
  frozen after a selected 244-test run while exact exported affected partitions
  had ten red cases: two T11/T12 safety-liveness failures, six stale lifecycle
  fixture failures, one replay-ingress API failure, and one missing
  `expected_experiment_id` production-binding failure.
  Proposal evidence must enumerate the complete changed-path-to-test-partition
  closure and prove every affected partition green; a hand-selected nearby set
  cannot substitute for that manifest.
- `PHYSICAL-SAFETY-PATTERN-BINDING-FALSE-GREEN-002` binds SafetyManager's
  actual pre-bind raw-label plane to its configured critical patterns. A
  canonical-only T11/T12 resolver earns no production credit until either the
  canonical-to-single-raw binding is wired before SafetyManager admission or
  the exact raw patterns remain live. The existing parameterized liveness node
  must pass for every critical pattern.
- `USBTMC-SETTLED-CANCEL-FALSE-GREEN-002` rejects the current test expectation
  that caller cancellation makes a successfully closed resource terminally
  incomplete. Close settlement commits atomically before cancellation is
  propagated; only a false/error/unsettled close retains the handle owner and
  visible HOLD.
- `AGENT-CONTEXT-LEGACY-SELF-ASSERTED-FALSE-GREEN-004` records that merely
  creating an ignored context file is not compaction resilience. The CLI
  capsule used an unregistered legacy schema and stale aggregate-green claims;
  the primary capsule used the wrong governing-set ID, omitted governing and
  owned-path bindings, retained a stale inventory digest, and claimed it was
  waiting while live edits continued. The validator must reject legacy or
  self-asserted shapes, incomplete exact governing sets, stale state, incomplete
  owned manifests, and evidence claims not bound to the exact current object.
  Live revalidation after the correction orders reproduced the failure again:
  primary still bound obsolete governing hashes and an
  `await_reviewer_disposition` state after rejection, causing a false
  no-external-progress stop; CLI at `870607ff` still used the unregistered
  legacy shape and self-asserted readiness.
- `KEITHLEY-FORCE-OFF-FAILURE-FALSE-GREEN-002` rejects the existing test that
  requires `connected is True` after a force-OFF write fails. A sourcing
  instrument without exact fresh nonce-bound two-channel OFF proof may retain a
  typed recovery owner, but it never acquires connected, measurement, READY, or
  mutation authority.
- `KEITHLEY-IDENTITY-MISMATCH-FALSE-GREEN-003` records that proposal tests
  passed with serial `04089762` while the configured VISA identity embeds
  `04052028`. Keithley authority requires an explicit exact configured
  manufacturer, model, and serial binding; a recognized but mismatched device
  may retain only typed global-OFF/close recovery ownership and never connected
  or measurement authority.
- Exact `97cff82c` ZMQ review exposed four additional untested settlement
  states now registered as
  `CLI-UNKNOWN-NONCE-COLLISION-FALSE-GREEN-007`,
  `CLI-UNKNOWN-CAPACITY-FALSE-GREEN-008`,
  `CLI-TIMEOUT-REPLY-RACE-FALSE-GREEN-009`, and
  `CLI-PRECANCEL-DISPATCH-FALSE-GREEN-010`. Request IDs are reserved across
  pending and outcome-unknown ownership; retained unknown outcomes have bounded
  fail-closed capacity; timeout/reply races settle one owner exactly once; and
  cancellation already present before enqueue is definitely-not-dispatched.
- `CLI-STALE-EPOCH-SIDE-EFFECT-FALSE-GREEN-006` requires the active epoch and
  stopped state to be checked before decoding or validation can mutate counters,
  store state, signals, or quarantine. A malformed old-epoch delivery after
  stop has exactly zero effects.
- `DASHBOARD-RECEIPT-DEFAULT-FALSE-GREEN-002` removes the remaining test-only
  authority shortcut: Dashboard receipts require explicit lifecycle/readiness,
  exact nonempty experiment and producer/incarnation identity, monotonic
  revision, and a fresh command-authority binding. No constructor default or
  `experiment_id=None` can enable a mutation.
- `OPERATOR-SNAPSHOT-CODEC-VERSION-004` and
  `CLI-CODEC-VERSION-TEXT-FALSE-GREEN-001` bind every module description,
  codec error, diagnostic, and migration statement to the exact operator-
  snapshot wire schema constant. A v2 envelope may not be described as v1.

Required dependency order and non-overlapping author slices:

1. `MONTANA-EXPERIMENT-IDENTITY-STORE-R1` may proceed independently: full
   128-bit IDs, global reservation, exact state/path/payload binding, and path
   containment.
2. `MONTANA-CLI-LIFECYCLE-V2-R3` removes every lifecycle default/shim, makes
   stale/disconnected/replay/same-cut recovery UNKNOWN, updates live/replay
   v2 provenance, qualifies READY wording as current Safety-owner evidence and
   not run permission, and adds real recovery guards.
3. `MONTANA-SAFETY-CONFIG-EXACT-R2` implements bounded exact atomic safety,
   alarm, interlock, and physical configuration; rejects NaN/Infinity/defaults;
   makes VacuumGuard/liveness/config failure non-restartable; binds one
   immutable predictor digest per engine incarnation; and projects missing or
   invalid predictor as typed UNAVAILABLE that blocks READY/RUN while retaining
   diagnostics and OFF. Live auto-ingest may create a candidate only and must
   never overwrite or activate the safety-authoritative model.
   The frozen R2 proposal is **REJECTED / NOT APPROVED** despite 309 focused,
   568 broader, and 20 x 10 repeat passes. Its receipt names two nonexistent
   paths, and exact mock-only reproduction proves that one NaN-bearing reviewed
   curve can be dropped into a zero-curve model that is still reported
   AVAILABLE; with no predictor blocker, `request_run` enters RUNNING.
   `MONTANA-SAFETY-CONFIG-EXACT-R3` must atomically reject non-finite,
   malformed, out-of-order, out-of-range, partially dropped, zero-curve, or
   below-reviewed-minimum model data before availability is published. Every
   model array must be finite and shape-consistent. Typed UNAVAILABLE must
   install the startup/RUN blocker, while diagnostics and OFF remain available.
   Deterministic guards must cover NaN and both infinities, mixed valid/invalid
   curves, zero prepared curves, minimum-count failure, and literal RUN denial.
   It is followed by `MONTANA-SAFETY-SETTLEMENT-R1`: every safety-child
   exception, return, or cancellation creates one exact terminal receipt and
   one coalesced global-OFF owner. Internal HOLD/UNKNOWN is immediate; public
   latched fault follows durable logging. One bounded-cadence autonomous retry
   owner coalesces operator retry. Restart requires exact OFF plus explicit
   operator recovery and never restores RUN automatically.
4. `MONTANA-ZMQ-TRANSPORT-OWNERSHIP-R1` supplies command classes, full nonces
   and engine/bridge incarnations, bounded emergency-OFF admission, retained
   mutation ownership, durable terminal receipts, fresh queues, quarantine,
   redaction, socket rebuild, and shutdown without false force-kill success.
5. `MONTANA-LAUNCHER-OWNERSHIP-R1` depends on transport: exact verified-OFF
   shutdown receipts, visible retryable HOLD, construction rollback, event-loop
   finalization, both-endpoint incarnation handshake, restart/reexec/crash
   quarantine, and generation-bound worker results.
6. `MONTANA-DRIVER-AUTHORITY-R1` implements exact configured Keithley identity,
   typed nonce-bound two-channel OFF proof, retained USBTMC cancellation/close,
   GPIB desynchronization/settlement/double-open rejection, and bounded
   redacted commands. Existing safety tests must be satisfied by production
   behavior, never weakened.
7. `MONTANA-EXPERIMENT-PROTOCOL-REPLAY-R1` follows lifecycle; it enforces
   coherent experiment tuples and archive-fingerprint-bound replay evidence.
8. `MONTANA-EXPERIMENT-RECORDING-BINDING-R1` follows identity, lifecycle,
   protocol, and safety; it binds persistence receipts to exact experiment and
   acquisition/engine incarnation and quarantines manager/feed disagreement.
   Before it, `MONTANA-EXPERIMENT-MUTATION-BINDING-R1` makes
   `expected_experiment_id` mandatory with no default for phase and every
   experiment mutation and updates all engine/replay callers atomically. An
   optional compatibility keyword is forbidden.
9. `MONTANA-SNAPSHOT-INGRESS-INCARNATION-R1` follows lifecycle, protocol,
   transport, and launcher; it binds producer/mode/engine/bridge identity,
   validates complete queue batches, resets ordering only at reviewed
   incarnation replacement, and makes every portability read explicit UTF-8.
10. Shell slices then run without path overlap: `S1` snapshot presentation,
    `S2` disk evidence, `S3` top-watch authority, `S4` replay-safe mutating
    panels, `S5` exact operator-log persistence, `S6` annunciation/read-only
    async overlays, and last `S7` retained-shell integration. Experiment shell
    reconciliation runs after S1/S5/S7 and displays one exact reconciled ID and
    LIVE/REPLAY provenance.
11. Observational surfaces then close without duplicating transport:
    `MONTANA-OBS-TRUTH` consumes one typed live/replay/incarnation/experiment
    cut and never maps failure to no alarms; `MONTANA-ASSISTANT-AUTHORITY`
    removes direct SQLite/operator-log and outbound-credential ownership;
    `MONTANA-WEB-TRUTH` makes UNKNOWN/replay/stale visible and bounded;
    `MONTANA-WEB-WRITE-RECEIPTS` adds exact experiment/incarnation/nonce
    durable receipts; and `MONTANA-RAG-BOUNDARY` enforces local-only egress,
    bounded trusted corpora, admin rebuild capability, and plain untrusted
    rendering. These depend on lifecycle, experiment, transport, and the
    corresponding shell paths being frozen.

Each implementation lane operates under the reviewer-recorded, worktree-scoped
standing mandate defined by `AUTH-HANDSHAKE-006`. The worker must inspect and
preserve every pre-edit path, but no per-slice token, path/blob/mode handshake,
password, or lease file is required. Each frozen proposal must include exact
output blobs, focused and broader affected tests, Ruff check/format,
`git diff --check`, and 20 deterministic repetitions of its
cancellation/race/staleness/restart guards. Shell closure requires a clean
unsplit process with zero live-QThread, teardown, late-callback, or
access-violation evidence; split suites are diagnostic only. No software
evidence closes hardware or laboratory gates.

After the CLI and Phase A proposals freeze, each must be independently reviewed
before integration. One integration owner then incorporates only the approved
CLI content into `feat/montana-phase-a`; all remaining correction and combined
gates continue in that single Phase A lane. Only after the combined candidate is
green may the integration owner create the single reviewed implementation
correction commit. Reviewer-owned candidate documentation and generated
architecture evidence may follow in a separate reviewed governance commit after
the implementation object freezes; they must describe that exact object. The
reviewer then freezes and reviews the complete Montana diff and runs the
exact-tree Windows/WSL/full/static/package/soak gates. Montana-to-master is a
second, separately frozen integration and review gate. Push/PR/publication
remain outside this
local correction programme until explicit publication authority exists.

## References

- `PROJECT_STATUS.md` — current infrastructure state, safety invariants, and
  open lab-verification gates.
- `CHANGELOG.md` — authoritative release history and shipped-version mapping.
- `docs/architecture.md` — tracked architecture overview.
- `docs/design-system/` — tracked UI design-system source.
- `docs/lab_verification_checklist.md` — next milestone protocol.
- `AGENTS.md` / `docs/ORCHESTRATION.md` — canonical engineering and evidence
  workflow for roadmap slices.
- `docs/adr/001-agent-native-plugin-contract-and-conformance.md` — future
  plugin contract/conformance interface decision.
- `docs/adr/002-plugin-safety-human-approval.md` — future non-self-approvable
  plugin safety approval decision.
- `docs/adr/003-governance-as-enforcement.md` — current mistake-to-rule-to-guard
  governance decision.
