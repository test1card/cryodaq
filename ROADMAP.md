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

### Montana final engineering, review, and publication checklist

Every item below applies to one exact frozen candidate object. Historical
passes, a moving worktree, a predecessor commit, or a review of similar code do
not transfer automatically.

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
  object must pass both reviews again. External-model reviews from any
  separately authorized provider/model are additive architecture or high-context
  evidence only: absence, quota exhaustion, or approval from them neither
  blocks nor authorizes PR publication.
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

---

## References

- `PROJECT_STATUS.md` — current infrastructure state, safety invariants, and
  open lab-verification gates.
- `CHANGELOG.md` — authoritative release history and shipped-version mapping.
- `docs/architecture.md` — tracked architecture overview.
- `docs/design-system/` — tracked UI design-system source.
- `docs/lab_verification_checklist.md` — next milestone protocol.
- `AGENTS.md` / `docs/ORCHESTRATION.md` — canonical engineering and evidence
  workflow for roadmap slices.
