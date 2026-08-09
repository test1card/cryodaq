# Montana Campaign Archive

> **Historical campaign record — not current policy.** This file preserves
> the Montana completion campaign's lane assignments, checklists, exact-SHA
> review dispositions, and correction programme as they existed during
> active work, extracted verbatim from `ROADMAP.md` and `PROJECT_STATUS.md`.
> It has no bearing on ordinary repository development and is superseded by
> `ROADMAP.md`/`PROJECT_STATUS.md` for anything still open. See `AGENTS.md`
> "Rule scope and promotion" for why campaign-local material lives here
> instead of in the product roadmap/status. `PROJECT_STATUS.md`'s
> classification of its own campaign-local material rests on content-shape
> judgment (no `Scope: campaign-local` banner existed in that file at
> extraction time), not on an explicit banner as in `ROADMAP.md`; that
> distinction is recorded here for anyone auditing the split later.

## From ROADMAP.md

<!-- was ROADMAP.md:1-16 (opening banner) in the pre-split working tree,
     C:\tmp\montana-integration, feat/montana-phase-a, 2026-07-25 (uncommitted) -->

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


<!-- was ROADMAP.md:181-493 (Active evidence checkpoint, Current candidate
     status table, Frozen CLI-half review checkpoint, and the banner-marked
     "Montana final engineering, review, and publication checklist") -->

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


<!-- was ROADMAP.md:1202-2183 (banner-marked "Montana correction programme
     after exact-object review (2026-07-22)", including the "Live two-lane
     integration checkpoint" subsection) -->

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

## From PROJECT_STATUS.md

<!-- was PROJECT_STATUS.md:1-8 (opening metadata block) in the pre-split
     working tree, C:\tmp\montana-integration, feat/montana-phase-a,
     2026-07-25 (uncommitted) -->

# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-07-22 *(release baseline v0.64.1 + active Montana correction campaign)*
**Релизная ветка:** master
**Активная campaign-ветка:** `feat/montana-phase-a` (current committed HEAD `c16cabc` rejected as a candidate; последний published checkpoint `503c8bf`)
**Релизная граница:** tag `v0.64.1`
**Версия пакета:** 0.64.1 (released 2026-07-08)


<!-- was PROJECT_STATUS.md:9-140 (Проверяемая таблица программных
     доказательств + Final-candidate evidence / review-state narrative).
     No explicit Scope: banner existed in PROJECT_STATUS.md; this range is
     classified campaign-local on content-shape (exact-SHA checkpoints,
     rejected-HEAD dispositions), not banner evidence. -->

## Проверяемая таблица программных доказательств

| Объект | Полный SHA | ОС / среда | Проверяемая команда или запись | Результат и граница |
|---|---|---|---|---|
| Выпущенная основа `v0.64.1` | `f5d6434d20dffae62c9f03fbc12f68b03f48351b` (аннотированный tag object проверяется отдельно) | Git-объект; не runtime-гейт | `git rev-parse v0.64.1^{}` и `git show -s v0.64.1` | Фиксирует выпущенный source baseline; не доказывает текущее поведение Montana. |
| Исторический Montana CI checkpoint | `7607bc19eca51e5d76d917be2c7a27a6788ff62f` | GitHub-hosted `windows-latest` + `ubuntu-latest` | `gh run view 29488046377` | Все восемь agents/core/GUI/remaining jobs PASS. Не переносится на более новый SHA и не закрывает ONEDIR/soak/hardware. |
| Последний опубликованный checkpoint | `503c8bf8d884654256ede4f08a9e44ab7b382242` | GitHub-hosted `windows-latest` + `ubuntu-latest` | `gh run view 29662599972 --json headSha,status,conclusion,jobs,url` | PASS: восемь matrix jobs завершены успешно; safe-SQLite во всех jobs, lint/format/lock в remaining jobs. Hosted Windows ONEDIR evidence для этого SHA отсутствует. Не включает текущий незапечатанный worktree. |
| Текущий final candidate | **pending после интеграции** | Windows, native-ext4 WSL/Linux, Windows ONEDIR, затем hosted CI | Сначала `git rev-parse HEAD` + clean tree; затем команды из `docs/lab_verification_checklist.md` и новый `gh run view <run-id>` | Нельзя заявлять PASS, пока один и тот же frozen SHA не пройдёт все применимые гейты. |

**Final-candidate evidence:** pending. Две изолированные implementation lanes
остаются незапечатанными: primary `feat/montana-phase-a` имеет rejected HEAD
`c16cabc`, а CLI correction `review/montana-cli-corrections-staging` имеет
rejected proposal HEAD `97cff82c` / tree `f03e3224`; primary остаётся широко
dirty, а CLI worktree содержит active uncommitted product/test corrections plus
13 preserved dirty/untracked `docs/**` paths вне implementation ownership. Ни
один объект не является approvable proposal. Raw CLI commit `f3e28a7`
не является допустимым integration parent; только независимо проверенное
reconstructed content может перейти в Phase A. Ни один текущий dirty blob не
покрыт run `29662599972`, и PR ещё не открыт.

До code-complete остаются: retained ZMQ mutation authority/quarantine и stop
settlement; full 128-bit globally reserved experiment identity и обязательное
mutation/recording/replay binding; exact verified-OFF launcher HOLD; USBTMC /
Keithley incomplete-close settlement; sealed safety configuration и production
physical-alarm binding; durable hot+cold operator-log idempotency; удаление
Telegram/RAG/assistant mutation and second-writer authority; exact GUI
lifecycle/freshness/incarnation cuts; QThread settlement; protocol,
architecture, report и SVG reconciliation. После двух proposal freezes reviewer
сначала отдельно проверяет CLI и Phase A objects; один integration owner затем
переносит только approved CLI implementation content в Phase A, и все combined
gates продолжаются в одной ветке.
Exact-candidate evidence tooling также open: Windows smoke исполняет runtime
copy, но hashes/uploads исходный dist без equality receipt; PR head и synthetic
merge SHA не различаются внутри evidence; host checkout участвует в одном
frozen boundary; nightly использует legacy unsealed soak; editable CI не
доказывает wheel/sdist completeness.
Current full-tree `git diff --check` passed at 2026-07-22 11:29 +03:00 after the
RAG test EOF defect was corrected; CRLF normalization warnings remain. This is
moving-tree hygiene evidence only and must be repeated on the frozen proposal.

**Текущий review state:** обе implementation lanes имеют disposition
**REJECT / CORRECTIONS REQUIRED**. Независимое воспроизведение доказало, что
текущий ZMQ server после timed-out mutation допускает вторую mutation и может
вернуться из `stop()`, пока первая mutation ещё способна commit; один текущий
test прямо сохраняет это небезопасное поведение. Experiment IDs остаются
12-hex, не globally reserved и не path-contained; launcher может
`terminate()/kill()` без exact OFF/exit receipt; Telegram сохраняет generic
mutation capability; production operator-log dedup остаётся process-memory-only,
а cold rotation удаляет request identity. CLI moving tree всё ещё сохраняет
false READY, dead strict physical-alarm production wiring, incomplete transport
and QThread settlement, missing Dashboard API и небезопасный annunciation ack.
SafetyManager child-death/HOLD/retry paths также могут запускать overlapping
global-OFF owners; один текущий test требует третью OFF попытку при всё ещё
blocked второй. Durable child receipt failure ошибочно считается settled, а
restart health может быть восстановлен только по elapsed time.
Recording lifecycle сохраняет acquisition/persistence epochs после replacement,
поэтому A-era receipt может ошибочно отметить experiment B как RECORDING;
replay fingerprint остаётся caller decoration и replay metadata делит live
namespace. Conductivity auto-advance также активен вопреки открытому hazard
decision: до frozen PAUSE/HOLD-versus-verified-STOP/OFF policy он должен быть
unavailable, а safety-critical freshness loss всегда ведёт к FAULT/OFF.

Persistence shutdown has a P0 ordering defect: the engine drains potentially
unbounded operator-log/SQLite owners before starting verified global OFF, so a
hung observational write can prevent OFF forever. Cancellation also abandons the
SQLite receipt path while the executor transaction continues: a reproduced run
emitted persistence/acquisition stopped with zero rows, then committed one late
row with zero receipts. OFF must start independently, persistence owners remain
retained in visible HOLD, and no stopped receipt may precede terminal settlement.

New P0 review evidence: alarm acknowledgement can commit state and then lose its
only event when the fast REP timeout cancels publication; command-server stop
does not settle retained/uncertain mutation owners. REST currently returns HTTP
200 for stale or unknown writes, and GUI transport exceptions erase delivery,
commit, retry-safety, action, and request identity. Experiment mutations still
accept an implicit current experiment and their receipts lack incarnation,
nonce, payload fingerprint, and durable retry lookup. These require retained
owners, durable outbox/receipts, exact HTTP outcome mapping, structured GUI
unknown-state propagation, and mandatory experiment/incarnation binding.

The moving CLI correction is not yet acceptable: its GUI-generated bridge UUID
is stamped onto data after receipt from a reused queue, so late old-producer data
can be relabelled as current disk evidence. Its cancellation/shutdown paths also
erase dispatched/unknown command identity and leave several QThread owners on
unchecked bounded waits. Trusted producer identity must cross the wire unchanged,
queues must be incarnation-fresh, and close must prove every owner settled.
The new Dashboard API removes one construction error, but MainWindow still
derives its mutation-enabling `connected` flag from arbitrary recent measurement
traffic. Data flow is not command/engine/experiment authority; production must
use a fresh exact handshake and per-action lifecycle preconditions.
Pinned staging tests remain red: snapshot/UI 306/46, USBTMC/Keithley 45/23,
physical/support 88/6. Cached READY has no age/liveness, ingress validates only
batch type/revision before taking the newest mixed member, Keithley accepts bare
zero as OFF proof, and USBTMC cancellation can detach a live close thread.
Annunciation still accepts `event_emitted=False`, tooltip identity is AutoText,
and strict physical-alarm loading is not used by production.

The current RAG correction is also incomplete. Assistant helper tests are green,
but the production sink registry still constructs `RAGIndexSink`, experiment
terminal dispatch still reaches `build_index`, and the GUI still presents and
tests running/complete live rebuild states. Live finalization must have no RAG
mutation sink; rebuild remains offline CLI-only.
The affected RAG Ruff lint gate passes, but Ruff formatting is red for
`assistant_main.py` and `sinks/registry.py`. A periodic-PNG test also widens a
poll loop from 100 to 5000 iterations without changing production settlement;
that is diagnostic evidence, not closure.

Focused counts `23 passed`, `83 passed`, `460 passed`, `205 passed` и
другие moving-tree результаты являются только correction evidence: они не
закрывают перечисленные контрпримеры и не получают exact-candidate credit.
Воспроизводимый docs-freshness gate: `17 passed / 3 failed`; tray contract,
SVG parity и report metrics остаются красными. Experiment outcome wording gate
теперь green отдельно, но не закрывает остальные candidate-finalization items.
**Final review evidence:** pending. Для одного замороженного candidate нужен
детерминированный object/range ledger: все текущие и удалённые текстовые строки,
binary/symlink/gitlink, mode, rename и LFS pointer/resolved artifact получают
точные blob identities и отдельные reviewer dispositions. В текущей campaign
обязателен полный task-designated primary review; evidence дополнительных
внешних reviewers маркируется раздельно и не подменяет обязательного reviewer.
Missing, truncated,
quota-limited, unavailable и stale-hash evidence дают нулевое покрытие; любое
изменение снова открывает затронутый объект. Обязательны два disposition:
полный task-designated fresh-context review и отдельная coordinator re-review;
evidence дополнительных внешних reviewers маркируется раздельно и не
подменяет ни один обязательный disposition. Даже 100% такого ledger не заменяет
отдельные architecture, threat-model, operator, safety, concurrency и test
quality audits.

**Фронтир:** Release train v0.58.0 → v0.64.0 отгружен 2026-07-07/08.
После релиза активна software-side pre-lab campaign: H3/H4 runtime/ONEDIR,
F35 ASC extension contract и F36 operator readiness из `ROADMAP.md`; F37 fleet/
projector scale остаётся deferred.

<!-- was PROJECT_STATUS.md:374-483 (review-disposition tail of
     "Открытые задачи" item 4: exact-commit/tree rejections, false-green
     records, governance-registry census). Content-shape classification,
     no explicit banner. -->

   **Current reviewer disposition is CORRECTIONS_REQUIRED for both moving
   implementation lanes.** Primary Phase A advanced to local proposal
   `c16cabc363bf9a9dd7eb3148e9c253106f33cfa7`, tree
   `edb806b322e16a90ac4a89c3eac077fdc40bb074`, but that commit is rejected:
   its 32 committed blobs match the manifest while committed
   `assistant_main.py` imports an uncommitted/untracked `context_reader.py`.
   Clean-export collection fails three assistant modules with
   `ModuleNotFoundError`, and zero of 11 checked registered exact
   assistant/integration guard names are present. The earlier `8ff15811`
   proposal remains rejected for the same exact-tree evidence class. Independent
   exact-object storage review also rejects `c16cabc`: scheduler cancellation
   can strand, cross-attribute, or silently evict late commit receipts; cold
   rotation drops operator-log request identity; outbox recovery is not wired
   into production; live keyed admission can exceed its cap; legacy stranded
   rotation can delete unproven operator rows; and production archive export
   omits mandatory experiment identity. The observed 30 scheduler passes and
   101 storage passes plus one skip do not cover those production boundaries.
   The CLI correction lane produced proposal commit
   `97cff82c047f8fb39262c16d2088dd8bf346c13f`, tree
   `f03e3224739eabb938af076c1243fc30bd7fb21b`, parent
   `4024f72cc29fc0780b3d18ccf962f16a44ab92ef`; the reviewer disposition is
   **REJECT / CORRECTIONS REQUIRED**. The commit was created while registered
   exact guards were absent and independently reproduced lifecycle-default,
   shell-authority, reply-consumer-generation, real-QThread, plain-text, and
   disk-freshness blockers remained. Candidate-pinned execution passed 244
   nearby tests while all 24 then-registered CLI guard nodes were absent; exact
   exported affected partitions then failed 10 cases: 2 T11/T12 liveness plus
   8 lifecycle-fixture, replay-ingress, and experiment-binding cases.
   A later CLI correction descendant was observed at
   `870607ffd5776f4235aae1fde10987d803b62f51`, tree
   `fedb481ce874f95b4aae9f17023d60ac9d0acdb9`. Exact-object disposition is
   **REJECT / CORRECTIONS REQUIRED**. Its 27 reported blobs and modes match,
   but a clean export contains only 1 of 45 effective CLI guard nodes by exact
   name; 44 are absent. The reported 179 focused, 603 driver, and 20x84 passes
   do not exercise the registered failure boundaries.
   Lifecycle defaults and disk-incarnation checks appear improved, but locked
   experiment CAS, origin-bound quick-log, caller-visible late ZMQ settlement,
   retained GPIB/Keithley close settlement, recovery quarantine clearing, Qt
  plain-text rendering, and complete real-QThread teardown remain open. Its
  worktree still contains 13 forbidden dirty documentation paths.
   Independent line review additionally found that a new GPIB test explicitly
   blesses a live handle after cancelled connect and relies on a later manual
   disconnect. This is P0 false-green evidence; terminal close settlement must
   remain owned and automatic for the exact handle generation.
   USBTMC also converts a successfully settled handle close into false terminal
   incomplete state when caller cancellation is propagated, and its current
   test explicitly blesses that result. Its 13 residual dirty/untracked `docs/**`
   paths are outside the proposal commit and remain untouched. The current dirty
   primary engine now starts retained
   SafetyManager shutdown before observational persistence drains, shields
   experiment reply owners, requires the expected ID for phase advance, improves
   hot operator-log idempotency, and rejects registered live RAG rebuilding.
   These are provisional uncommitted improvements, not approval. Reproduced P0
   gates still include SQLite commits landing after `persistence_stopped` without
   receipts, ZMQ mutation owners escaping timeout quarantine, overlapping global
   OFF owners, omitted OFF scope becoming `smua`, old subprocess readings being
   relabeled with a new GUI incarnation, Dashboard mutation authority derived
   from arbitrary telemetry, and post-enqueue cancellation losing outcome-
   unknown identity. Real QThread and executor settlement, durable operator-log
   idempotency/outbox ownership, strict Keithley OFF proof, lifecycle freshness,
   full-batch ingress identity, and exact producer incarnation are also open.
   Passing focused counts are diagnostic only until each lane freezes one exact
   commit/tree and the reviewer reruns the affected and broader gates.
   Independent 2026-07-22 audits additionally rejected the live GPIB delta
   despite 10 focused passes: close can lose ownership and return success while
   a close/I/O thread remains live, double-open leaks the first resource, and
   desynchronization admits ordinary writes. Conductivity automatic sweep also
   remains unavailable because arbitrary telemetry can enable it, cached data
   can advance it, commanded power is recorded as measured evidence, and bare
   success is rendered as verified OFF. Experiment/replay remains blocked on
   durable cross-process CAS, full globally reserved identity, commit-time
   experiment/epoch provenance, stale-journal rejection, canonical paths, and
   adapter-computed archive fingerprints. Exact correction gates are maintained
   in `ROADMAP.md`.
   The AI-first governing layer now distinguishes repository-universal,
   product-contract, and Montana campaign-local rules. The reviewer-owned
   `governance/agent_preventions.yaml` currently contains 37 unique open
   runtime/governance prevention records,
   66 separately identified false-green coverage pairs, and 110 declared record
   guard nodes. Structural local parsing
   confirms unique IDs, resolved runtime-to-coverage links, and durable
   product-contract authority. The required implementation-owned validators are
   still absent, 12 referenced guard files do not yet exist, named-node
   collectability and default-CI inclusion remain unproven, and immutable
   red/green evidence is pending. A read-only live registry-to-worktree check on
   2026-07-22 initially found **0 of 59** durable primary-owner nodes and **1 of
   34** durable CLI-owner nodes present by registered file/node name. That
   census incorrectly mixed durable maintenance ownership with Montana's active
   edit authority. The exact campaign override map now yields an effective
   **0 of 57 primary** and **1 of 38 CLI** checkpoint after adding its two
   enforcement nodes. Aggregate focused-pass counts and capsule assertions
   therefore provide no proposal-freeze evidence for either moving lane, but a
   bounded lane is responsible only for its effective edit-owned affected
   closure; the combined/final gates require the union.
   `AGENT-CONTEXT-COMPACTION-001` now defines
   one ignored capsule per long-running role. Capsule presence is transient
   ignored evidence and is therefore checked live rather than counted in this
   tracked status document. Both worker capsules currently fail the live
   contract: CLI uses an unregistered legacy shape with stale green assertions;
   primary binds the wrong governing-set ID, incomplete hashes/owned paths,
  stale inventory, and a wait state contradicted by active edits. They grant no
  continuity until each worker rewrites only its own capsule under the current
  schema and the validator passes. ADR 003 remains
   Revalidation after explicit correction orders reproduced the same failure:
   primary still waited on obsolete governing hashes after rejection, while
   CLI still self-certified `870607ff` through the legacy capsule. Both capsules
   therefore carry zero continuity or freeze authority.
   locally ignored and the Montana contract plus governance schemas/registry are
   untracked; explicit candidate-manifest inclusion is therefore an open
   governance gate, not an assumed Git side effect.

<!-- was PROJECT_STATUS.md:484-491 ("Открытые задачи" item 5: exact-SHA CI
     checkpoint 29662599972 for 503c8bf). Content-shape classification,
     no explicit banner. NOTE: removing this item leaves the surrounding
     ordered list numbered 1,2,3,4,6 (no 5) in PROJECT_STATUS.md, since
     renumbering was outside the two authorized wording-change exceptions
     for this split -- flagged to the requester, not silently fixed. -->

5. Recorded exact-SHA CI checkpoint `29662599972` для `503c8bf`: все восемь
   agents/core/GUI/remaining jobs PASS на Ubuntu и Windows. Safe SQLite
   verification прошла во всех jobs; lint и requirements-lock drift
   checks PASS в обоих remaining jobs. Hosted Windows ONEDIR evidence в этом
   run отсутствует. Каждый новый candidate требует свой exact-SHA eight-job PASS
   и отдельный ONEDIR gate;
   frozen-build, soak-duration, physical-hardware, F35 frozen-packaging и F36
   operator/accessibility/performance/scenario gates остаются открыты.

## Out-of-tree campaign records (recorded 2026-08-10)

The campaign's working corpus never lived in this repository. It was
consolidated on 2026-08-09/10 out of the machine temp directory into a durable,
agent-agnostic workspace folder named `cryodaq-workspace`, kept beside the
repository checkout on the maintainer machine (deliberately not a tracked
path; a private remote for it is queued with the owner as OB-008 in
`docs/OBLIGATIONS.md`). What it holds:

- **`evidence/pr1/`** — the authoritative PR #1 approval records the owner
  ruled are internal rather than GitHub review states: the approver transcripts
  and verdict files (sol, fable, glm-5.2, kimi), the merge card, and the PR's
  review/comment JSON exports.
- **`evidence/lanes/`** — the review-lane stores: briefs, per-lane result
  verdicts, and full transcripts.
- **`archive/`** — the retired campaign process layer (cycle plans, state-file
  history, superseded plans and handovers) plus a byte-exact preservation
  snapshot of the entire pre-consolidation corpus, taken 2026-08-09 before
  anything was moved or deleted.
- **`STATE.md`** — the single live agent state file that superseded the
  campaign's state documents; its history is the workspace's git log.

Deferred owner directions found in that corpus are registered in
`docs/OBLIGATIONS.md`; durable owner rulings from it are recorded in
`docs/DECISIONS.md`. Nothing in the workspace is repository policy: it is
evidence and working state, selected per `AGENTS.md` "Rule scope and
promotion".

## Owner-ratified P0-P9 plan, extracted from ROADMAP.md

<!-- Extracted verbatim 2026-08-10 on branch docs/agent-layer-obligations,
     source commit d05856ecb3e0d5002e37083f32f4b2d7acf5927f (ROADMAP.md lines 142-293
     at that commit). Author of the plan: the independent reviewer (gpt-5.6-sol),
     2026-07-29, owner-ratified. Extraction ruling: Fable, 2026-08-10 - the live-
     sounding Prerequisite phases cost a measured day of phase-system conflation
     after the campaign closed. The body below is byte-faithful; the Open-cell
     disposition and deferred-debt subsections stayed in ROADMAP.md as live
     disclosure, and the snapshot-sequencing amendment (P2-P5) also stayed
     there as live regeneration authority - the documentation gate anchors the
     two-artifact regeneration requirement on its P3 bullet. Their verbatim
     copies below are the historical record; ROADMAP.md carries the live text. -->

<!-- Authored by the independent reviewer (gpt-5.6-sol) at the owner's request,
     2026-07-29, after the owner ratified the checkpoint threat model. It supersedes
     the earlier campaign plan, whose stop lever was unreachable by construction:
     P5 became available only after convergence, while every finding reopened
     authoring. The bounded-cycle rule below exists to prevent a recurrence. -->

## Montana PR-readiness and checkpoint publication — owner-ratified plan (2026-07-29)

> **Campaign-local scope.** This section supersedes the 2026-07-29
> `DO NOT MERGE` determination and blocker classification in
> `docs/OPEN_CELLS.md` for this checkpoint only. Historical evidence is retained
> and labelled superseded rather than deleted.
>
> The owner’s binding threat-model decision is:
>
> **This checkpoint protects against accidental or agent-induced validator and
> evidence-producer weakening, enforced by a judge loaded from the protected
> default branch. It does not claim Byzantine-candidate resistance inside
> pytest, and must never be described as if it does.**
>
> In particular, this checkpoint does not establish resistance to candidate
> code deliberately attacking the same pytest process or OS account; compromise
> of `master`, GitHub Actions, OIDC, a hosted runner, or the package index;
> artifact immutability under a lock without `--require-hashes`; physical OFF;
> real-instrument behavior; packaged Windows behavior; or laboratory acceptance.

### Bounded-cycle rule

P0 and P1 are prerequisites for starting the integration cycle. The cycle
starts when P2 begins and permits exactly one integration object and one P5
frozen SHA.

The cycle terminates immediately with one of these outcomes:

- **PR_READY:** P0-P8 pass for one unchanged P5 SHA.
- **NOT_PR_READY:** any prerequisite check is red, cancelled, missing, stale, or
  bound to another SHA; either mandatory reviewer withholds approval; a covered
  byte or mode changes after P5; or the integration topology differs from P2.
- **MERGED_P9_OPEN:** `master` has already been fast-forwarded at P9, but a
  post-fast-forward check or settings verification fails.

There is no correction, retry-until-green, refreeze, or “one more review”
sub-loop in this plan. A diagnostic rerun earns no acceptance credit. After a
terminal failure, further authoring requires a new owner-authorized bounded
cycle. Deferred disclosure rows do not extend this cycle and do not become
merge prerequisites merely because work on them remains possible.

### Cycle 2 — why the trust root moved, and what P1 must now qualify

Cycle 1 ended `NOT_PR_READY` when the hosted protected gate failed. The cause was
not the bootstrap: **the protected evidence path could never have run.** The guard
registry resolved red-reproduction receipts, and the Git objects they bind, against
the location of its own module rather than the tree under validation.

That made one check behave two ways. The ordinary run imports those tools from the
sealed export, which has no `.git`, so object resolution was skipped. The protected
run imports the *same* tools from the judge checkout, which is a repository, so
resolution switched on and searched for the candidate's objects in the judge's
object database, where they cannot exist — and the judge branch carries no
`governance/` directory at all.

The current Cycle 2 judge pin is commit
`3656654d00937230390076bc60a72b279c124aa9`, tree
`2bd5e59f73c0326b2a740f7e8d731e390b2a511c`. Its trust-root range is eight commits
after `f5d6434d20dffae62c9f03fbc12f68b03f48351b` and changes fourteen paths. That
range repairs the root confusion with two authorities that must not be conflated:
`root`, the materialized tree receipts are read from, and `git_repository`, the
candidate's real checkout used only to resolve objects. `require_git_resolution`
is fail-closed and keyed on the protected path alone, so a missing repository
refuses rather than silently degrading. The range also pins
`requirements-protected-ci-lock.txt` in `_PROTECTED_PRODUCER_FILES`, bounds and
labels the protected failure relay, and makes its Windows byte cap independent of
newline translation.

**P1 must qualify all of it.** The exact commit, tree, ancestry distance, and path
inventory above are object measurements, not completion evidence. The range is
authored and not independently reviewed; no P1 review receipts and no protected
hosted receipt bound to `3656654d00937230390076bc60a72b279c124aa9` exist yet.
The reviewer who ruled on any part of the repair's design is not thereby a
reviewer of its implementation: P1's two reviewers must be independent of the
authors of the eight-commit trust-root range.

### Amendment — snapshot sequencing (P2-P5), 2026-07-29

The independent reviewer's P4 dry run found a contradiction in the phases below: **P2 and P3
necessarily stale the frozen architecture snapshots, while the contract permits no further content
commit to regenerate them.** As written, the cycle could not pass its own documentation-freshness
gate. That is a defect in this plan, not in the tree. The reviewer's amendment, adopted:

* **P2** prepares the specified merge with `--no-commit`, resolves only the authorised integration
  paths, and does **not** create `I` yet.
* **P3** reconciles the governance test, stages all final P2/P3 content, updates the frozen inventory
  rows in `docs/MONTANA_REFACTOR_REPORT.md`, stages those, then regenerates **both** shipped
  generated artifacts — `docs/architecture-montana-important.svg` **and**
  `docs/current_candidate_metrics.md` — from that final staged index, and stages both.
  The generator writes the two artifacts from one frozen snapshot, so regenerating only the SVG
  leaves the metrics tree hash stale and fails the P4 freshness gate; both writes are therefore
  authorised and required here. `docs/refactor/` outputs are
  neither touched nor promoted. The integration coordinator then creates the sole merge commit `I`
  with the required parents.
* **P4** runs from a clean detached checkout of that finalised `I`, documentation freshness included.
* **P5** freezes `F := I`. No additional content commit and no further snapshot regeneration.

This keeps exactly one integration object, makes staged-index-last generation possible, and hands P4
an immutable coherent object rather than one it must itself repair.

### Ordered phases

| Phase | Owner | Merge status | Measurable exit criteria |
| --- | --- | --- | --- |
| **P0 — Record the owner decision and reconcile claims** | Governance reviewer; repository owner supplies the ruling but does not sign review evidence | **Prerequisite** | Add an `[Owner]` entry to `docs/DECISIONS.md`; update `docs/OPEN_CELLS.md`, `PROJECT_STATUS.md`, and this roadmap so the earlier determination is explicitly superseded. Bind the judge to commit `3656654d00937230390076bc60a72b279c124aa9`, tree `2bd5e59f73c0326b2a740f7e8d731e390b2a511c`, eight commits after `f5d6434d20dffae62c9f03fbc12f68b03f48351b`, with fourteen changed trust-root paths. Record that the protected lock is version-pinned without artifact hashes and is owner-authored pending independent review. `tests/docs/test_docs_freshness.py` and the applicable governance consistency tests pass. No live document continues to list OC-020 as `BLOCKS-CHECKPOINT` or describes Byzantine resistance as a checkpoint guarantee. |
| **P1 — Qualify the default-branch trust root** | Two reviewers independent of the authors of the eight-commit range ending at `3656654d00937230390076bc60a72b279c124aa9`: one depth-and-delta reviewer and one fresh-context `BREADTH` reviewer; CI/evidence owner collects hosted evidence | **Prerequisite** | Both review receipts bind exact commit `3656654d00937230390076bc60a72b279c124aa9`, exact tree `2bd5e59f73c0326b2a740f7e8d731e390b2a511c`, and the complete fourteen-path diff against merge base `f5d6434d20dffae62c9f03fbc12f68b03f48351b`. The receipts explicitly disposition the hashless protected lock and the complete cumulative trust-root repair, including the Windows relay-bound correction at the judge tip. A hosted `CryoDAQ protected CI evidence gate` run against an unchanged known-green candidate records `github.workflow_sha == 3656654d00937230390076bc60a72b279c124aa9`, eight successful `protected execution (<os>, <suite>)` jobs, eight `PROTECTED EXECUTION ACCEPTED` results, a successful `protected CI evidence gate` job, and an uploaded `cryodaq-partition-proof-<run-id>-<attempt>` artifact. Record the run ID and artifact digest. No such review or hosted receipt is asserted here; any contrary review verdict or hosted failure ends the plan before integration. |
| **P2 — Prepare the single final integration without committing** | Integration reviewer/coordinator, not a trust-root author acting alone | **Prerequisite** | Prepare the specified merge with `--no-commit`; its eventual parents must be exactly the pre-integration Montana tip and `master@3656654d00937230390076bc60a72b279c124aa9`, and `3656654d00937230390076bc60a72b279c124aa9` must be an ancestor of the eventual `I`. Resolve the added/added workflow conflict by taking the judge workflow blob unchanged. Carry `requirements-protected-ci-lock.txt` from the judge; retain the candidate’s product `requirements-lock.txt`, since the judge copy remains byte-identical to `f5d6434d20dffae62c9f03fbc12f68b03f48351b`. The two bootstrapped judge modules remain byte-identical to the candidate copies. No other conflict resolution or cleanup enters the prepared merge. P2 remains uncommitted and does **not** create `I`. |
| **P3 — Reconcile the workflow contract, refresh snapshots, and create `I`** | Governance-test owner plus integration reviewer/coordinator for the final staged object | **Prerequisite** | Update `tests/governance/test_protected_ci_evidence_gate.py` to require installation from `requirements-protected-ci-lock.txt`, reject installation from the product lock, require the protected lock in both immutable-object verification loops, retain the step-level `job.check_run_id` assertions, and retain the candidate-weakened-judge negative control. Stage all final P2/P3 content, update the frozen inventory rows and regenerate both `docs/architecture-montana-important.svg` and `docs/current_candidate_metrics.md` from that final staged index as specified by the amendment; do not touch or promote `docs/refactor/`. Then create the sole integration commit `I` with the exact P2 parents. The workflow blob in `I` remains the exact `3656654d00937230390076bc60a72b279c124aa9` blob. The protected-workflow governance test and `tests/test_ci_candidate_evidence.py` pass from a clean checkout of `I`. |
| **P4 — Exact integration verification** | Verification owner, separate from P2/P3 authoring | **Prerequisite** | From a clean detached checkout of `I`, record passing results for `python scripts/check_lock_drift.py`, `python -m pytest -q tests/governance/test_protected_ci_evidence_gate.py tests/test_ci_candidate_evidence.py`, applicable prevention-registry and documentation-freshness tests, `python -m ruff check --no-cache` over the changed Python files, and `python -m ruff format --check --no-cache` over those files. Record exact commands, versions, counts, skips, and output hashes. The workflow and protected-lock blobs equal their `3656654d00937230390076bc60a72b279c124aa9` blobs; the product-lock blob equals the pre-integration candidate blob. A failure ends the cycle; P4 does not authorize a correction. |
| **P5 — Freeze the exact integration object** | Integration reviewer/coordinator | **Prerequisite** | Set `F := I` and `T := tree(I)` without creating another commit. In an isolated clean checkout, create the ignored evidence artifact `.audit-run/montana-pr-readiness/<F>/P5-freeze.json` containing `F`, `T`, exact parents, complete Git path/mode/blob manifest, diff digest against `3656654d00937230390076bc60a72b279c124aa9`, and governing-document blob IDs. Record its SHA-256. Tracked content is clean at `I`. The existing user-owned `docs/refactor/` material is neither added nor deleted. Any later content, path, or mode change terminates this cycle rather than producing another P5 SHA. |
| **P6 — Two independent final reviews** | Depth-and-delta reviewer plus a newly instantiated, context-independent `BREADTH` reviewer; neither may be an author of `F` | **Prerequisite** | Persist complete receipts as `.audit-run/montana-pr-readiness/<F>/P6-depth-and-delta.json` and `P6-breadth.json`, each binding `F`, `T`, the P5 manifest digest, exact reviewed range, reviewer identity/model, mandate, findings, and verdict. Both verdicts must be `approved`; disagreements must be recorded. Any P0-P2 finding or non-approval produces `NOT_PR_READY`; there is no in-cycle repair. |
| **P7 — Run exact-SHA hosted evidence** | CI/evidence owner | **Prerequisite** | Push only `F`. The ordinary `CryoDAQ CI` run for `F` completes all eight Ubuntu/Windows × agents/core/gui/remaining jobs green without retry credit. The default-branch `CryoDAQ protected CI evidence gate` also succeeds for `F`, uses `JUDGE_SHA == 3656654d00937230390076bc60a72b279c124aa9`, produces eight protected bundles, eight accepted protected-execution messages, and `cryodaq-partition-proof-<run-id>-<attempt>`. Record both run IDs, all job conclusions, and artifact digests in the P5 evidence directory. A red occurrence of OC-039 still terminates this cycle because the required check is red; that does not reclassify OC-039 as a defect blocker, and rerunning until green is forbidden. |
| **P8 — Issue the PR-readiness disposition** | Coordinator/integration reviewer | **Prerequisite** | Verify that the proposed PR head is exactly `F`, the base is `master@3656654d00937230390076bc60a72b279c124aa9`, the PR path/mode inventory equals the P5 manifest, both P6 receipts approve `F`, and both P7 workflows are green for `F`. Emit `montana-pr-readiness-disposition-<F>.json` with status `PR_READY`, the two review-receipt digests, run IDs, check conclusions, and all deferred rows. Only this exact SHA may be opened or marked ready. Any PR-head change produces `NOT_PR_READY`. |
| **P9 — Exact fast-forward, repository-rule authority, and handoff** | Repository owner for the outward actions; coordinator verifies resulting state | **Publication step after PR readiness** | Fast-forward `master` from `3656654d00937230390076bc60a72b279c124aa9` to exactly `F`; no squash, replacement merge, amend, or different tree is permitted. Verify `origin/master == F`. The repository is currently personal-hosted, so its available required-status setting may be used as a fail-closed operational fallback but is not equivalent to, and must not be credited as, a native ruleset required-workflow binding: required status checks do not bind the workflow or event, and can reuse an earlier success for the same SHA when a later pull request B presents it. Migrate the repository to an organization/enterprise host that supports ruleset required workflows, bind the protected workflow for both `pull_request` and `merge_group`, and verify the rule through GitHub API/UI evidence. The required workflow must publish only its native job checks; no manually created or patched check run has admission authority. Because any rule is enabled after the requested fast-forward, state explicitly that it did not gate this fast-forward; the merge itself relied on P7’s exact-SHA check. Trigger or observe one post-fast-forward ordinary/protected run with `github.workflow_sha == F`; require the same eight protected executions and accepted partition proof. The run can prove the merged object but cannot substitute for the missing native repository-rule authority. Until host migration and native binding are verified, the result is `MERGED_P9_OPEN`; only then can P9 yield `MERGED_CHECKPOINT`. A post-fast-forward failure also yields `MERGED_P9_OPEN` and stops without rollback or further correction under this plan. |

