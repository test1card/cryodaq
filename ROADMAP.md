# CryoDAQ — Feature Roadmap

> **Living document.** Updated 2026-07-13 for the software-side pre-lab
> readiness campaign. `CHANGELOG.md`
> is the authoritative shipped-history record; this file is only the forward
> feature map.
>
> **Current frontier:** v0.64.1 is shipped as the immutable `v0.64.1` tag, and the
> release train v0.58.0 -> v0.64.0 closed the v0.60 Known Limitations backlog.
> The active milestone is to close every safe software-side prerequisite before
> hardware validation: H3/H4 runtime/frozen-build reliability, F35 multi-lab
> extension contracts, and F36 operator-centered product/fleet readiness.
> Physical gates remain governed by `docs/lab_verification_checklist.md` and
> cannot be closed by simulation.

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
| F35 | ASC hardware extension contract | 🔧 PARTIAL — descriptor persistence/receipt activation, live wire, replay/report parity, generic GUI, real-localhost lifecycle, conformance/reference driver, and continuous acquisition-to-display software proof committed; specialized shell routing and frozen-build extension proof open | L | H |
| F36 | Operator-centered control-room surface and fleet readiness | 🔧 PARTIAL — snapshot plane, live safety authority, and fail-conservative recording/integrity projections committed; production activation and atomic shell cutover open | L | H |
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
   recovery UX, passive infrastructure health, fleet-scale performance,
   durable review/support evidence, and design-system-governed navigation.
4. **Evidence packaging.** Exact real-Windows and physical-lab procedures,
   expected artifacts, pass/fail thresholds, rollback/abort conditions, and
   support-bundle capture must be ready before travel to the stand.

The irreducible hardware milestone then remains:

1. SQLite shim and startup gate on the laboratory Ubuntu PC.
2. H5 / ZMQ idle-death check on the current laboratory PC.
3. LakeShore runtime calibration on real hardware.
4. Keithley A8a-A8b upload/late-pet checks on dummy load; A8c-A8e host-death,
   independent terminal V/I/P + trip-time, and independent final-element /
   common-cause proof remain physical blockers. Phase C stays blocked until
   all are evidenced; see the lab checklist for the full matrix.
5. Windows frozen-build smoke (`install.bat`, shortcut, launcher).

Use `docs/lab_verification_checklist.md` as the turnkey protocol.

### Active evidence checkpoint — 2026-07-14

This is feature-branch evidence, not shipped history and not a release claim:

- The integrated H3/H4 runtime/lifecycle slice is committed at `026bf50`.
  Its detached clean-SHA gate completed with 4,939 passed, 11 skipped, and
  1 deselected. H4 R3a is also committed: periodic delivery now has a
  provider-neutral receipt contract and durable state-v2 migration. H4 R3b
  remains in active implementation for the launcher-owned socketpair,
  bounded framed transfer, durable runner ledger, and ACK authority. The
  short and 72-hour soaks and real-Windows ONEDIR evidence remain open.
- Recorded exact-SHA GitHub Actions checkpoint `29321460151` at `cd208a2`
  passed all eight Ubuntu/Windows agents, core, GUI, and remaining
  jobs. Safe SQLite verification passed in every job; both remaining jobs also
  passed lint and requirements-lock drift checks. Any newer candidate requires
  its own exact-SHA eight-job pass before acceptance. This checkpoint does not
  close frozen-build, soak-duration, physical-hardware, F35 frozen-packaging,
  or F36 production-activation gates.
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
  localhost ZeroMQ on native Windows and WSL source runs. Specialized shell
  routing heuristics and real-Windows ONEDIR/frozen packaging remain open. One
  scheduler-produced reference-extension artifact is now proven continuously
  through persistence/live wire, replay/report projection, real shell dispatch,
  and instrument-health display; mock TCP does not close physical evidence.
- F36 now has committed foundations for the snapshot wire contract,
  durable revision allocation, typed common-cut authority receipts, ordered
  composition, publication through the existing publisher, two-SUB bounded
  ingress, one GUI-thread Store, conservative pure replay sessions, and
  conservative live adapters. The SafetyManager cache and live safety/readiness
  authority are committed and fail conservative when proof is absent. Pure
  recording/persistence owners and their fail-conservative live projections
  are committed, but actual loop-owned experiment/acquisition/persistence
  integration is still open;
  production recording therefore remains `UNKNOWN` and data integrity remains
  unavailable. Atomic shell cutover, all operator scenarios, and
  screenshot/visual QA remain open.
- No software, mock, replay, CI, soak, or screenshot evidence closes a real
  Windows, dummy-load, independent-final-element, or physical-laboratory gate.

---

## ASC scalability milestone — F35

CryoDAQ must remain usable beyond the current stand. The existing
`InstrumentDriver -> Scheduler -> SQLite -> DataBroker` path is a strong
module boundary, but adding a new instrument type still requires central
`engine.py` edits and several GUI paths infer semantics from deployed model or
channel names. F35 turns that internal modularity into a supported extension
contract for other ASC laboratories.

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
Specialized shell routing heuristics remain open.
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

## Operator product and fleet-readiness milestone — F36

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
codes, revision/time, and explicit `ok | caution | warning | fault | stale |
disconnected` semantics. Unknown never becomes optimistic green.

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
missing. Pure recording/persistence owners and fail-conservative live
projections are also committed, but they are not yet integrated with the actual
loop-owned experiment, acquisition, and persistence feeds. Until that
integration lands, production
recording remains `UNKNOWN`, data integrity remains unavailable, and optional
F36.3-F36.5 authorities are not synthesized.

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
models, snapshot transport, and Store foundations exist. Production server/live
activation and the atomic shell cutover are still open, so the legacy shell is
not yet retired and no screenshot or operator-scenario closure is claimed.

### F36.3 — Cooldown mission and durable attention history

Unify live cooldown trajectory, deviation, phase, relevant alarms, recent
history, and comparison-to-reference into one mission view. Make attention and
incident evidence durable across GUI restarts rather than relying on bounded
in-memory alarm history. Preserve the canonical alarm authority and audit
revision; UI filtering/acknowledgement never rewrites truth.

Acceptance: restart/replay tests reproduce the same incident timeline and
cooldown decision state; missing data is explicit; exported evidence points to
stable experiment/channel identities.

### F36.4 — Passive infrastructure health and fleet scale

Add an allowlisted read-only `HealthTelemetryDevice` contract for compressor,
pump-station, cryocooler, and support nodes. It may report identity, heartbeat,
mode, metrics, alarms, freshness, and provenance. It must not expose
start/stop/reset/vent/purge/set commands or health-driven automatic
remediation.

Acceptance: a deterministic simulator proves at least 100 devices and 2,000
channels at <=2 Hz human-readable update cadence, without unbounded widgets,
poll tasks, queues, or memory growth. Aggregated/virtualized views meet the
design-system frame, input, startup, and idle-memory budgets.

### F36.5 — Onboard documentation, read-only API, and support bundle

Ship version-matched offline operator/safety/troubleshooting documentation,
document the read-only status/view-model API, and generate a deterministic,
redacted support bundle containing versions, config fingerprints, health and
attention snapshots, recent audit/log evidence, and integrity results.

Acceptance: bundle schema and redaction tests cover tokens, credentials,
operator/private data, absolute user paths, and hostile strings; identical
inputs produce stable manifests; capture works while the engine is degraded.

### F36.6 — Design-system and product-governance gate

Every F36 UI slice must use `docs/design-system/` as a co-versioned contract.
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
- **F18 — CI/CD residuals.** Recorded exact-SHA run `29321460151` closes the
  Ubuntu/Windows matrix gate at checkpoint `cd208a2`; every newer candidate
  still requires its own eight-job pass. Coverage publishing, release
  automation, and binary artifacts remain optional.
- **F-Y — Diagnostic mode rework.** Re-spec only if lab operation produces
  concrete diagnostic decisions that the current alarm/overlay path cannot
  support.

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
