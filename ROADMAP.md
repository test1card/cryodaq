# CryoDAQ — Feature Roadmap

> **Living document.** Updated 2026-07-08 after v0.64.0. `CHANGELOG.md`
> is the authoritative shipped-history record; this file is only the forward
> feature map.
>
> **Current frontier:** v0.64.0 is shipped from master `67b6301`, and the
> release train v0.58.0 -> v0.64.0 closed the v0.60 Known Limitations backlog.
> The next milestone is hardware lab verification via
> `docs/lab_verification_checklist.md`, not a new code batch.

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
| F35 | ASC hardware extension contract | 🔧 PARTIAL — generic acquisition backbone exists; registry/capabilities/metadata are missing | L | H |
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

## Current milestone

No release-blocking feature batch is queued.

The remaining milestone is hardware lab verification:

1. SQLite shim and startup gate on the laboratory Ubuntu PC.
2. H5 / ZMQ idle-death check on the current laboratory PC.
3. LakeShore runtime calibration on real hardware.
4. Keithley TSP watchdog armed-mode pass on dummy load only.
5. Windows frozen-build smoke (`install.bat`, shortcut, launcher).

Use `docs/lab_verification_checklist.md` as the turnkey protocol.

---

## ASC scalability milestone — F35

CryoDAQ must remain usable beyond the current stand. The existing
`InstrumentDriver -> Scheduler -> SQLite -> DataBroker` path is a strong
module boundary, but adding a new instrument type still requires central
`engine.py` edits and several GUI paths infer semantics from deployed model or
channel names. F35 turns that internal modularity into a supported extension
contract for other ASC laboratories.

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

## Deferred feature work

- **F8 — Cooldown ML prediction upgrade.** Still research-gated: dataset
  curation, model evaluation, and uncertainty methodology come before code.
- **F12 — Experiment templates UI editor.** Nice-to-have operator workflow;
  not a safety or release blocker.
- **F14 — Remote command approval.** Safety-sensitive; needs a fresh threat
  model and explicit go/no-go before implementation.
- **F15 — Linux packaging.** Deployment convenience after lab verification.
- **F16 — Plugin SDK/examples.** Documentation/examples work, not core runtime.
- **F35 is not deferred.** Implement it after the current lab-readiness
  integration/frozen gates and before calling CryoDAQ a multi-lab ASC
  platform or adding another safety-critical source family.
- **F18 — CI/CD residuals.** Matrix and green full suite are done; coverage
  publishing, release automation, and binary artifacts remain optional.
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
