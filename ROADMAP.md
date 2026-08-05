# CryoDAQ — Feature Roadmap

> **Living document.** `CHANGELOG.md` is the authoritative shipped-history
> record; this file is only the forward feature map. The active campaign, if
> any, is recorded at `docs/campaigns/`.
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

### Open-cell disposition under this threat model

| Cell | Checkpoint disposition | Required repository statement |
| --- | --- | --- |
| **OC-020** | **BLOCKS-DEPLOYMENT; disclosure debt. It does not block this checkpoint.** No OC-020 sandbox change is integrated in this cycle. | State that mutate-execute-restore remains possible in the ordinary same-authority pytest execution model and that this checkpoint does not resist a Byzantine candidate. Record the scratch evidence accurately: Linux honest `core`/`agents` controls pass; Linux `gui` reproducibly fails 13 nodes; Windows reaches successful `AdjustTokenPrivileges` and then incorrectly treats `ERROR_NOT_ALL_ASSIGNED` during privilege removal as fatal. Those are diagnostic results, not checkpoint closure, Windows acceptance, or physical-safety evidence. Retain the scratch branches while the row remains open. |
| **OC-035** | **Checkpoint prerequisite until P1, P7, and the candidate-bound check succeed; then satisfied only for the ratified checkpoint threat model.** | State that validators execute from the default-branch judge and that real hosted OIDC/REST job binding was observed. Do not say that a malicious default-branch commit, compromised runner/GitHub identity, or same-process Byzantine candidate is resisted. The required-check setting performed after the requested fast-forward protects subsequent changes, not the already-completed fast-forward. |
| **OC-036** | **BLOCKS-DEPLOYMENT residual; checkpoint prerequisite for the specified accidental/agent-induced producer-substitution attack.** | State that the protected producer and pytest plugin come from the default-branch judge and that candidate copies cannot accidentally weaken them. Also state that candidate tests still execute in the same pytest process and OS account; deliberate plugin mutation, protocol forgery, background tampering, or equivalent hostile behavior is outside the checkpoint claim. |
| **OC-037** | **BLOCKS-DEPLOYMENT; release-promotion authority debt. It does not independently block this checkpoint.** | State that RSA-SHA256 signature authority is live and distinct from workflow provenance, durable cross-run replay authority, and direct-upload/repository-settings restrictions. The candidate must not author the private signing authority or receipt-producing qualification workflow. |
| **OC-039** | **BLOCKS-DEPLOYMENT; disclosure debt. It is not scheduled work and does not independently block the checkpoint classification.** | State that the cause of the `test_heartbeat_has_timestamp` flake remains unknown and that measured listener probes falsified the fixed-port/startup explanation. It fails only in the safe direction. Do not call a retry a fix. If it makes P7 red, the one-shot cycle terminates because required hosted evidence is red, not because OC-039 was promoted to a blocker. |

### Explicitly deferred debt and non-claims

The following items are not prerequisites for P5, PR readiness, or this
checkpoint fast-forward:

- OC-020’s cross-platform in-execution authority boundary;
- OC-036’s Byzantine-candidate/same-process residual;
- OC-039’s unknown flake cause and any eventual deterministic repair;
- adding artifact hashes to `requirements-protected-ci-lock.txt`;
- OC-034/OC-037 release-promotion and direct-upload restrictions;
- physical OFF, real 2604B, dummy-load, independent-final-element, Windows
  ONEDIR, long-soak, and laboratory acceptance gates.

They continue to bar deployment, release-readiness, physical-safety, or
laboratory-acceptance claims wherever their existing contracts say so. A
successful Montana checkpoint is a reviewed software checkpoint, not a
deployable or physically verified release.

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

---

## ASC scalability milestone — F35

CryoDAQ must remain usable beyond the current stand. Historically, adding an
instrument required central engine edits and name-based GUI routing. The active
branch now uses the allowlisted registry, canonical descriptor authority, and
descriptor-qualified generic and specialist routing. F35 establishes a passive
extension foundation for other ASC laboratories; it does not yet establish a
generic hazardous-actuator adaptation contract. Frozen-package and physical
evidence also remain outstanding.

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
6. **Reference extension proof.** The current proof shows that a new passive reference driver can be added
   with its own module, schema, config, and tests without editing engine,
   scheduler, launcher, storage, or generic GUI code; an end-to-end test proves
   acquisition, persistence, replay, reporting, and instrument-health display.
   Replay must resolve the same stable channel descriptor—including quantity,
   role, safety class, and display group—and reporting/generic GUI paths must
   consume that descriptor rather than rediscovering semantics from names.
7. **Safety boundary stays deliberate.** Arbitrary plugins never gain source
   authority by duck typing. A generic hazardous-actuator extension contract is
   not implemented; a future one requires an explicit reviewed safety adapter,
   hazard analysis, an honest OFF-capability disclosure, and physical bench
   evidence.

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

**SUPERSEDED by the phase ordering below (owner-ratified, 2026-08-01;
reconciled 2026-08-05).** The item-numbered sequence that stood here assumed the
agent-native work was separable from the descriptor cluster. It is not: an
adapted lab's channels have different names by definition, so a conformance
floor built over spelling-routed identity certifies plugins into a system that
misroutes them.

**The order is Phase 0 → 1 → 2 → 3, with Phase H running in parallel throughout
and gating on nothing but the owner's time at the stand.**

- **Phase 0 — register truth and first blood.** Tier-0 register retag (merged);
  the notification delivery proof, OC-026 (merged); the OC-039 disposition.
  Proves the PR-review-merge workflow end to end at small scale.
- **Phase 1 — the descriptor spine.** The engine-loader ownership fix; then
  OC-031's registry re-key; then the OC-008/OC-030 site migrations in bounded
  batches carrying rendering evidence for every touched surface; OC-023 rides
  with the cluster under the most careful review. OC-028 and OC-004 slot in as
  independent small PRs.
- **Phase 2 — the conformance floor.** The deliverables specified later in this
  section, **in the order those specifications already give**: this summary
  deliberately does not restate a sequence, because a planning entry point that
  orders the work differently from the specification it points at will be
  followed instead of it. What the phase adds beyond those specifications is a
  single scoping rule: every conformance claim is scoped "plugin-side floor"
  until the Phase 1 site migration completes.
- **Phase 3 — the adaptation skill and the forward test.** The forward test is
  its own gate, graded by a context that did not write the contract, and runs
  only after Phase 1 completes: run earlier it either fails for the wrong
  reason or passes vacuously.
- **Phase H — hardware.** Parallel throughout, owner-paced. **Put the first
  hardware session on a calendar, not in a queue** — it is the one item that
  fails silently while everything else feels like progress.

The longer-horizon items below remain correctly ordered among themselves:

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

This is the last planned engineering-quality phase, and it is **Phase 2 and
Phase 3** of the ordering above. Its prerequisite is not "the higher-return work
above" as a whole: it is specifically the **descriptor spine** — the foundational
descriptor contract (landed), OC-031's re-key, and the OC-008/OC-030 site
migration. Work on the contract, template, harness and signed actuation gate may
proceed in parallel with that spine provided every conformance claim is scoped
"plugin-side floor" until the migration completes. Only the constrained
mid-tier-agent forward test is genuinely blocked on the completed spine.

**Owner decision, 2026-08-05 — what an unmatched channel renders as.** A channel
with no descriptor match is an **operator-visible option**: the operator chooses
whether such channels are obscured. **The default is to render the value
desaturated** (`theme.MUTED_FOREGROUND`, an existing token) **with the Russian
marker `н/о`**, and the unambiguous wording (`без дескриптора`) in the tooltip
and accessible name where there is room for it.

Three constraints follow, and each exists because of a measured failure:

- **Not `—`.** `reporting/sections.py` documents `—` as the *unavailable*
  marker, under a NaN-доктрина whose stated reason is that an operator would
  otherwise "read a confident number where none exists". An unclassified
  channel's value IS available; only its classification is missing. One glyph
  must not mean both.
- **The textual marker is load-bearing, not decorative.** The panel conformance
  obligations in this phase require non-colour state cues, and desaturation
  alone is colour-only. The marker is what makes the state accessible, and it
  may not later be "simplified" away.
- **Obscuring must be discoverable.** When hidden channels exist, show a count
  (`скрыто: N`) or keep them listed on the settings surface. A live reading that
  becomes invisible by configuration is the vanishing-readout failure returning
  through a setting — the failure that caused the `169f7e96` / `0bea0449`
  revert.

**Negative scope stands unamended.** The "deliberately do not chase" list in
this document, and the explicit exclusions in the post-Montana strategy
(Byzantine same-process resistance, repo-wide mutation ratchets, receipt-latency
provenance until a thesis chapter consumes it, the fault-injection campaign
harness, formal methods, the full reproducibility chain, and wholesale panel
migration) remain excluded. **F37 fleet/projector view is NOT in that list**: this
document keeps it as deferred feature work at its own entry below, and an earlier
draft of this paragraph reclassified it as excluded, which is a change of status
no amendment of the ordering is entitled to make. They are referenced rather
than restated so that dropping them is not quietly re-litigated.

**Owner queue — decisions that are not the coordinator's to make:**

1. Marker wording for unclassified channels beyond the default recorded above,
   if the operator-facing text should differ.
2. Refuse-versus-warn on the import-time capability-metadata drift check in
   `src/cryodaq/drivers/registry.py`. It ships fail-closed; the engine does not
   consume that table operationally, so a derived-artifact freshness gate would
   remove the failure mode rather than choose between the two.
3. OC-034 repository settings and OC-013 physical-OFF measurement — Phase H,
   closed by the owner rather than by code.

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
- `docs/campaigns/MONTANA_CAMPAIGN_ARCHIVE.md` — historical record of the
  completed/superseded campaign coordination material split out of this file
  and `PROJECT_STATUS.md`; not current policy.
