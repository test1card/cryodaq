# OPEN cells — Montana partial-checkpoint register

The Cycle 1 register body was verified against `e642cba4` plus the changes that
landed with it. The Cycle 2 disposition is authored and awaiting the independent
review and hosted proof required by the current plan. This register is the PR's
disclosure of what remains unsealed; it is not a claim that every C1/C2/C3
surface is sealed, that physical OFF has been proven, or that the candidate is
approved for deployment.

A row marked **unexamined** records missing evidence, not a claim that the defect
is present. `Fail-closed?` answers the operator-relevant question: **No** means
the path can continue, or present a determined-looking result, without the stated
fact. **Unknown** means the surface was not examined, so neither refusal nor safe
continuation is established. **Yes, but** identifies a safe rejection that still
leaves the product or evidence claim incomplete. Empty scan roots fail in every
guard checked; that good property does not make an unmatched bypass fail closed.

`Gate` states what would close the row, and whether it blocks this checkpoint.
**BLOCKS-CHECKPOINT** rows must be closed before the PR may be signed at all.
**BLOCKS-DEPLOYMENT** rows may remain open in a non-approving, non-deployable
checkpoint, but bar any claim of release readiness, laboratory safety, or
physical-OFF proof.

## Current Cycle 2 checkpoint model

Cycle 1 ended `NOT_PR_READY`. The owner authorized Cycle 2 under the
owner-ratified plan in `ROADMAP.md`; the Cycle 1 `DO NOT MERGE` determination
retained below is historical and does not classify Cycle 2.

The binding claim is narrow: this checkpoint protects against accidental or
agent-induced validator and evidence-producer weakening through a judge loaded
from the protected default branch. It does not claim Byzantine-candidate
resistance inside pytest. Candidate tests still share a pytest process and OS
account with protected machinery, and mutate-execute-restore remains possible
in an ordinary same-authority pytest model.

Repository object measurement now binds the Cycle 2 judge to commit
`3656654d00937230390076bc60a72b279c124aa9`, tree
`2bd5e59f73c0326b2a740f7e8d731e390b2a511c`. It is exactly eight commits after
`f5d6434d20dffae62c9f03fbc12f68b03f48351b`, and that comparison changes
fourteen trust-root paths. Those measurements establish identity and inventory
only. No P1 review receipts and no protected hosted receipt bound to
`3656654d00937230390076bc60a72b279c124aa9` exist yet.

The protected CI lock is version-pinned without artifact hashes. It is an
owner-authored, candidate-compatible snapshot pending independent review and
hosted proof; it is **not reviewed evidence**.

The cumulative guard-root and relay repair is present in the current judge
commit and remains authored, not reviewed. The code roots Git object resolution
in the repository under validation and refuses a protected-path run without the
required candidate repository rather than silently downgrading. The ordinary CI
exact-checkout guard separately resolves Git objects; only the sealed export
subrun skips resolution when no repository is available. These are authored
implementation facts, not P1 completion or hosted acceptance evidence.

## What this register corrects

Three statements in the previous revision of this file were **false at the head
they shipped with**, and are corrected here:

- it said the static dashboard still routed a `Т*` channel as temperature. That
  defect was fixed by `1af677be`, with browser regressions; OC-009 is removed.
- it said the candidate step still used `continue-on-error`. It was removed by
  `4cee6901`; the corresponding "Checked and not recorded as open" note is gone.
- it recorded G4 as rejecting every `SOFTWARE-PROVABLE` declaration and ignoring
  unmarked citations. `1d2c43ad` changed both; OC-019 is removed as obsolete.

Several evidence cells previously cited working notes outside the repository.
Every citation below is an in-repo path.

| ID | Class | Surface | What is not established | Blast radius | Evidence | Why it is not closed | Fail-closed? | Gate | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

| OC-002 | C1a/C1b | Assistant paths outside engine-query adapters | RAG/infrastructure failures, composite/cache staleness and Telegram cache activity are outside the adapter AST sweep. **Narrowed:** the live diagnostics-cache path was examined this cycle and found honest — `get_summary` returns a summary only after receipt-freshness validation, and failed polls, invalid receipts and expiry clear it to `None`. | An operator can receive an empty answer or stale assistant context as if the query had authoritatively found nothing. | `tests/agents/assistant/test_c1_engine_adapter_seal.py:1-12` (explicit scope limit); `src/cryodaq/agents/assistant/query/router.py:109-112` returns an empty payload after a router failure. | The guard owns only direct `EngineQueryClient.call` adapter paths; no cross-subsystem availability inventory exists. | **No** for router failure; unproved elsewhere. | Availability inventory across assistant producers. BLOCKS-DEPLOYMENT. | Assistant/query owner |
| OC-003 | C1 | Drivers | **Examined this cycle across all 16 driver modules; no neutral-substitution defect found.** ASC malformed responses raise; LakeShore and Thyracont return explicit error-status readings or raise; Etalon produces unavailable/stale error readings rather than an empty neutral set. Keithley's empty-buffer path is a legitimate buffer result with no production operator consumer. What remains unestablished is a *contract* distinguishing legitimate protocol emptiness from collapse, so a future driver has nothing to conform to. | A future or unexamined driver path could return a neutral result for a disconnected instrument with nothing to prevent it. | `src/cryodaq/drivers/contracts.py:268-272`. | The typed contract is not designed; the current cleanliness rests on per-driver care, not a property. | **Yes** for the 16 modules read. **Unknown** as a surface property. | A `Reading` provenance type with mandatory freshness. BLOCKS-DEPLOYMENT. | Driver-contract owner |
| OC-004 | C1b | GUI retained-state presentation | No inventory or production-path test establishes that every GUI view revokes a dead producer's last reading rather than continuing to show it as current. | An operator can read a frozen temperature, pressure or source value after its producer has died. | Absence of any revocation assertion under `tests/gui/`. The GUI identifier registry described in OC-008 is not in the tree, and in any case enumerates routing sites without asserting anything about staleness. | Requires a served-state/producer-invalidation inventory and live view tests, not an identifier scan. | **Unknown.** | Producer-invalidation contract + per-view regressions. BLOCKS-DEPLOYMENT. | GUI/state owner |
| OC-005 | C1/substrate | Governance/CI evidence | C1 behaviour of the governance/CI surface is examined and **no unavailable evidence source was found rendered as a neutral pass.** **This row previously claimed a Git-index escape and that claim was wrong:** the ordinary pytest run does deselect the active guards, but that is duplicate avoidance, not an escape — strict guard execution runs the active population separately and fails closed on absence. What remains open is only that no formal authoritative-state boundary inventory exists for this surface. | A reviewer could in principle receive a green-looking evidence result from an unexamined path. | `tools/ci_candidate_runner.py:221` (the deselection) together with `tools/ci_guard_execution.py:374`, which appends `strict guard execution has no active guards` and fails when the population is empty. | No inventory exists, though the sampled paths were clean. | **Yes** for the guard-execution path examined. **Unknown** for the surface as a population. | A boundary inventory. BLOCKS-DEPLOYMENT. | CI/governance owner |

| OC-007 | C2 | Generic source authority | Generic authority is granted by a one-item `keithley_2604b` reviewed-source roster and driver-type equality, not by declared capability evidence. | A lab's otherwise valid source is rejected from CryoDAQ safety control because it is not the rostered vendor/model; operators may route it around the interlock and OFF path. | `src/cryodaq/drivers/registry.py:126-137,269-272`; `src/cryodaq/engine.py:2149-2153`. | The capability-tier adapter authority is not complete. | **Yes, but.** It rejects unrostered authority rather than inventing it, while violating the adopted no-vendor-policy direction. | Capability-derived authority via `instruments.yaml`. BLOCKS-DEPLOYMENT. | Owner + safety reviewer |
| OC-008 | C2 | Qt GUI identity routing | **67 live sites across 17 GUI modules** still let raw identifier spelling participate in routing or selection — enumerated this cycle rather than estimated, with the heaviest concentrations in `src/cryodaq/gui/shell/main_window_v2.py` (11), `src/cryodaq/gui/first_run_config.py` (11), `src/cryodaq/gui/shell/overlays/multiline_panel.py` (8) and `src/cryodaq/gui/shell/views/analytics_widgets.py` (7). | A renamed or differently spelled channel can disappear from, or be routed to the wrong, operator readout or plot. | The 67 sites were produced by an enumeration held outside the tree. **A registry recording them was deliberately NOT landed:** it keyed each site on file and line, which OC-031 shows lets a registered operation be replaced by a different spelling policy at the same line undetected. Landing it would have created the appearance of coverage without the property. | A prior migration attempt made an undeclared pressure readout vanish and was reverted (`169f7e96`, reverted by `0bea0449`). The owner must choose explicit `unclassified` presentation versus no display before a safe re-land. | **No.** Current presentation continues to use incidental identity, and no guard currently blocks new sites. | Re-key the registry per OC-031, land it, then replace each site with an exact configured binding or descriptor authority. BLOCKS-DEPLOYMENT. | GUI + product owner |

| OC-011 | C2 | Agents/assistant | **Not unexamined — concrete live instances exist.** Telegram operator surfaces infer physical meaning from channel/instrument spelling, and have no descriptor authority to consult. | The assistant can describe a channel's role or capability from a stand-specific name rather than a declaration, on `/temps`, `/pressure`, `/keithley` and `/status`. | `src/cryodaq/notifications/telegram_commands.py` classification paths; the only production constructor is `src/cryodaq/engine.py`. | Removing the inference without a descriptor contract would hide valid operator readouts — the failure mode that forced revert `0bea0449`. | **No.** | A descriptor authority reaching the Telegram surface. BLOCKS-DEPLOYMENT. | Assistant/query owner |
| OC-012 | C2 | Governance/CI | **Examined this cycle; nothing found.** All four workflows, the CI/governance runners, twelve governance tests and the registry/config references were swept. Vendor-like names occur in declared configuration and fixtures, not as capability or authority decisions — which the governing rule permits, since exact comparison against declared configuration is not inference. | A guard or procedure could privilege a vendor-specific path and make another lab's equivalent capability appear unsupported. | Sweep of `.github/workflows/`, `tools/` CI runners and `tests/governance/`. | No standing rule prevents a future violation here; the repo-wide C2 scan root does not extend beyond `src/cryodaq/**`. | **Yes** for what was read. | Extend the C2 scan root past `src/cryodaq/**`. BLOCKS-DEPLOYMENT. | CI/governance owner |
| OC-013 | C3 | Physical-OFF proof | **Narrowed this cycle.** `DEVICE_REPORTED_OFF` and `PHYSICAL_STATE_UNKNOWN` are now distinct tiers preserved through SafetyManager → scheduler → operator snapshot → engine receipt → launcher, on exact schema `cryodaq.engine_shutdown.v2` with nested `off_evidence` and a recomputed `verified_off`. What remains unestablished is that **any** available tier constitutes independent physical proof: a device-reported readback is the instrument's own account of itself. | Shutdown/restart decisions can rely on a device-reported tier as if it were physically verified. | `src/cryodaq/drivers/contracts.py`; `src/cryodaq/core/safety_manager.py`; `src/cryodaq/launcher.py` receipt validation. | Independent physical measurement is hardware/lab work that no software change can supply. | **Yes** for tier confusion (the tiers no longer collapse). **No** for a physical-OFF claim. | An independent physical measurement gate. BLOCKS-DEPLOYMENT — and the PR must state that device-reported readback is not independent physical proof. | Safety owner + lab owner |
| OC-014 | C3 | Driver outcome contract | There is no surface-wide requested/acknowledged/readback-confirmed contract for driver commands and measurements. | A caller can treat an acknowledgement as the outcome it needs, including on an OFF/recovery path, without knowing the evidence tier. | `src/cryodaq/drivers/contracts.py:268-272`. | Requires a cross-driver contract and consumer migration, not an AST pattern. | **No** for physical outcome claims; individual repaired paths refuse. | Typed outcome receipts declaring the evidence tier a claim requires. BLOCKS-DEPLOYMENT. | Driver-contract owner |
| OC-015 | C3 | Storage/reporting | **Examined this cycle across all 8 reporting and 17 storage modules; nothing found.** The report UI states that reports updated only after the child result is bound to the selected immutable generation and artifact paths; promotion validates artifacts and writes the current manifest last; a missing PDF renders as `PDF=нет` rather than success. No signed-report or provenance-success claim from a proxy was found. | A generated or signed report could state that an operation succeeded without the evidence establishing it. | Sweep of `src/cryodaq/reporting/` and `src/cryodaq/storage/`. | No common typed receipt builder exists, so the property is not enforced for future code. | **Yes** for what was read. | A receipt inventory over the reporting surface. BLOCKS-DEPLOYMENT. | Storage/reporting owner |

| OC-017 | C3 | Agents/assistant | Assistant outcome claims outside the repaired notification paths are not enumerated. | An assistant message or audit can say a command or notification succeeded from a proxy rather than terminal evidence. | `src/cryodaq/notifications/telegram.py` returns `delivered` on HTTP 200 alone; `ef022ab5` sealed only the named delivery paths. | No inventory covers assistant claims. | **Unknown.** | Terminal-evidence contract for the notification transports. BLOCKS-DEPLOYMENT. | Assistant owner |
| OC-018 | substrate | Guard coverage | Every guard on this branch is a **shape matcher, not a seal**, and every one has been defeated by the first adversary to attack it. Known named exemptions: the OFF-double guard exempts five scopes and skips `dict[...]`-annotated `emergency_off`; the C1 adapter guard's passing baseline admits one production violation; the C2 descriptor guard admits `periodic_renderer.py:142`. | A future C1/C2/C3 regression can merge with a passing guard — dynamic import construction, cross-module identity construction, or reflection all evade them. | `tests/governance/test_source_off_result_test_doubles.py:10-16,124-131`; `tests/agents/assistant/test_c1_engine_adapter_seal.py:31-36,228`; `tests/analytics/test_c2_descriptor_selection_guard.py:23-33`. | These guards intentionally scan bounded syntax, not runtime behaviour. | **No for bypasses.** **Yes** only for the empty-scan-root configuration, which every guard fails closed on. | Runtime provenance types (C1) and typed outcome receipts (C3). BLOCKS-DEPLOYMENT. | Guard owners + CI owner |
| OC-031 | substrate | C2 is **not** mechanised repo-wide | An earlier claim — that C2 was the one defect class a repo-wide sweep could mechanise — **does not hold for the sweep that was built.** An independent red-team defeated it on first contact with nine bypasses while its baseline passed cleanly at 90 detected sites equal to 90 registered sites. Most seriously, the registry keys on `(path, line, reason)`, so **a registered operation can be replaced by an entirely different spelling policy at the same line with no change to the detected set** — demonstrated by substituting `channel.startswith("Т")` at a registered GUI line, undetected. | A guard that passes while missing live defects is worse than no guard, because it is cited as coverage. | The sweep is not landed in this state; hardening is in flight. The same `(path, line)` keying defect is present in the GUI identifier registry described under OC-008. | Alias provenance is not followed through `for` targets or comprehensions; membership needles built by f-string or bound to a name are invisible; the scan globs only `*.py`, excluding `.pyw` and all non-Python presentation code. | **No.** It passes while missing the sites below. | Re-key sites to a normalised AST shape rather than a line number; follow loop and comprehension targets; recognise computed membership needles. BLOCKS-DEPLOYMENT. | Guard owners |

| OC-030 | C2 | Operator-screen identity inference (detection now added) | Four live GUI sites use the same comprehension-target form, and contain the exact Cyrillic-Te class this campaign exists to remove. | An operator readout or plot can omit or misroute a channel after a legitimate rename. | `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py:167`; `src/cryodaq/gui/dashboard/temp_plot_widget.py:136`; `src/cryodaq/gui/shell/top_watch_bar.py:1194`; `src/cryodaq/gui/shell/views/analytics_widgets.py:1626`. | Neither the GUI registry nor the repo-wide sweep detects the form. | **No.** | Detection first (OC-019), then per-site binding. BLOCKS-DEPLOYMENT. | GUI owner |
| OC-020 | substrate | Candidate immutability during execution | Mutate-execute-restore remains possible in the ordinary same-authority pytest execution model. This checkpoint does not resist a Byzantine candidate. The integrated Windows sandbox is Mandatory Integrity Control **plus** privilege stripping; it has never been measured green anywhere. | A deliberately hostile candidate can mutate protected bytes, execute them, and restore them before post-hoc verification. That residual is outside the ratified checkpoint claim but bars deployment. | Diagnostic evidence only: Linux honest `core` and `agents` controls pass through the real sandbox path; Linux `gui` reproducibly fails the same 13 distinct nodes on byte-identical inputs. On Windows, `AdjustTokenPrivileges` succeeds and the code then incorrectly treats `ERROR_NOT_ALL_ASSIGNED` during privilege removal as fatal; for privilege removal that documented success-with-warning points in the safe direction and is an error-handling defect, not evidence that the authority boundary failed. The measured 10/10 Windows probe covers Mandatory Integrity Control alone and contains zero privilege-API calls despite its docstring claiming privileges were stripped. | Neither diagnostic set closes the row. The integrated MIC-plus-privilege-stripping sandbox has not passed, and the results are not Windows acceptance or physical-safety evidence. The scratch branches carrying the diagnostic apparatus must be retained while this row remains open. | **No** against a Byzantine same-authority candidate. | **BLOCKS-DEPLOYMENT; disclosure debt. It does not block this checkpoint.** No OC-020 sandbox change is integrated in Cycle 2. | CI/evidence owner |
| OC-021 | substrate | Montana candidate gate | **OPEN for Cycle 2 evidence.** The protected-gate implementation is authored, and its local regressions exercise refusal and control behavior, but the protected hosted chain did not execute in Cycle 1. It must not be described as executed, passed, or independently verified for Cycle 2. | Without the required protected execution, merge evidence can appear complete when the independent default-branch judge has not adjudicated the candidate. | The gate moved from an in-matrix candidate step to `.github/workflows/protected-ci-evidence-gate.yml`, where the default-branch judge evaluates all eight downloaded bundles. Regression guards exist in `tests/test_ci_candidate_evidence.py` and `tests/governance/test_protected_ci_evidence_gate.py`; those local software checks are authored evidence only. Cycle 1 non-execution is recorded at lines 206-212 below. | Local refusal/control behavior does not establish the missing independent hosted execution. | **Pending.** The authored validator can refuse its local violating fixture; Cycle 2 fail-closed behavior and acceptance credit await independent review and hosted proof. | P1/P7 independent review, exact candidate binding, and successful protected hosted execution. **BLOCKS-CHECKPOINT.** | CI/governance owner |

| OC-023 | C2 | Interlock channel routing | Interlock routing still resolves channels by regex over identifier spelling rather than a declared binding. | An interlock can bind to the wrong channel, or fail to bind, after a legitimate rename — on the safety path. | Confirmed by direct reading this cycle; declared-ID coverage proves the current IDs, not the contract. | Replacing it requires descriptor-backed interlock configuration and engine-wiring changes. | **No.** | Descriptor-backed interlock configuration. BLOCKS-DEPLOYMENT. | Safety + engine-wiring owner |
| OC-024 | C3 | Archive finalisation rows | Finalisation rows carry only timestamp, instrument, channel, value, unit and status — no descriptor data — so archive grouping cannot be descriptor-derived. | An archived record cannot later be attributed to a declared measurement identity; downstream grouping falls back to spelling. | Confirmed by direct reading of the finalisation row shape this cycle. | Requires the archive-descriptor migration. | **Unknown.** | Descriptor data in finalisation rows. BLOCKS-DEPLOYMENT. | Storage owner |
| OC-025 | C2 | Telegram descriptor authority | The Telegram surface has no descriptor authority; its only production constructor is `src/cryodaq/engine.py`. | Operator command output infers physical meaning from spelling. Paired with OC-011. | `src/cryodaq/notifications/telegram_commands.py`; `src/cryodaq/engine.py`. | Removing the inference without a descriptor contract would hide valid operator readouts. | **No.** | A descriptor authority reaching the notification surface. BLOCKS-DEPLOYMENT. | Assistant + engine-wiring owner |
| OC-026 | C3 | Notification delivery proof | **IMPLEMENTED; REVIEW EVIDENCE OPEN.** `src/cryodaq/notifications/telegram.py` retains its four-tier vocabulary. Both live `agents.assistant_main.TelegramSender` send methods now stream at most 65,536 acknowledgement bytes and accept delivery only from strict UTF-8 JSON with literal `ok: true`, `result.message_id` in `1..2**63-1`, and a `result.chat` matching the requested destination. A contradictory HTTP 200 with `ok: false` remains outcome-unknown. The legacy `notifications/periodic_report.py::PeriodicReporter` is importable-but-dead by the enforced engine cutover; the live periodic chain is `agents.assistant.periodic_runtime` to `agents.assistant.periodic_telegram`, which already applies the bounded destination-bound contract. | Without these checks, an audit trail can turn malformed, misdirected, contradictory, or unbounded provider data into a determined-looking delivery outcome or unbounded memory use. | `tests/notifications/test_delivery_acknowledgement.py` exercises both live methods, exact byte boundaries, zero-consumption Content-Length refusal, early chunk-overflow stop, exact unknown settlement, identifier range, and destination binding. Defect-restoring local mutants for strict `ok`, bounds, settlement, contradictory 200, chat binding, and identifier validity all made the named guards red on 2026-08-01. | The authored behavior and local mutation results are not a frozen independent review or hosted-CI receipt. They do not claim that a human read the notification. | **Yes in the authored software behavior; acceptance is pending.** Invalid or contradictory acknowledgements fail closed to unknown/error rather than delivery. | Freeze the corrected PR object, obtain the required independent reviews, and run exact-object hosted CI. BLOCKS-DEPLOYMENT until that evidence and integration complete. | Assistant owner |
| OC-027 | C1b | GUI cold-stage declaration | The GUI re-reads `cooldown.yaml` itself to decide which channel is the cold stage, instead of consuming what the engine applied. In replay mode the replay server overrides the cold channel, so the GUI can render warm-plate data as the cold-stage steady state — silently, because a non-`None` declaration suppresses the unavailable rendering. | An operator sees a confident cold-stage readout that is not the cold stage. | `src/cryodaq/gui/shell/main_window_v2.py` `_declared_cold_stage_channel()`; the replay override in the replay server. | Repair is in flight; the engine must publish the applied declaration and the GUI must consume it. | **No.** The false declaration suppresses the unavailable path. | Engine publishes applied `channel_cold`; GUI consumes it and stops reading the file. BLOCKS-DEPLOYMENT. | GUI + engine-wiring owner |
| OC-028 | C3 | Alarm narration suppression has no upper bound | The unbounded re-narration storm is fixed by recording the attempt at the dedup gate. **The opposite bound is now missing:** the ledger uses a 30-second sliding quiet window that each refire refreshes, so continuous flapping suppresses indefinitely; transport recovery does not re-arm it; and a still-active CRITICAL alarm that emits no new `alarm_fired` event will not re-narrate. | An operator can stop being told about a CRITICAL condition that is still active — including the case where the transport was broken during the first attempt and has since recovered. | `src/cryodaq/agents/assistant/live/agent.py` ledger and gate. | The fix deliberately chose the better failure: an operator buried in repeats stops reading them. But no sustained-CRITICAL escalation or transport-recovery re-arm exists on this path. | **No.** Suppression is silent. | A re-arm on transport recovery, or an escalation for a CRITICAL that remains active across N suppressed windows. BLOCKS-DEPLOYMENT. | Assistant owner |

| OC-032 | C2 | GUI cold-stage specialist routing accepts a foreign descriptor | The GUI selects the cold stage from configuration — which is correct — but then matches on `channel_id` equality alone instead of resolving that declaration through the active descriptor manifest. A self-consistent **foreign** descriptor arriving first on a fresh GUI session is accepted as `authoritative`, and its matching channel id routes it as the cold stage. | It contaminates the cooldown plot, the raw history, the steady-state predictor, cached analytics state and phase-replay state. **Observational only — it does not reach SafetyManager or actuator control**, which is why this is not a checkpoint blocker under the blocker rule. | `src/cryodaq/gui/shell/main_window_v2.py` cold-stage routing; the regression that catches it is `tests/gui/test_f35_descriptor_specialized_routing.py`, whose two failing nodes are the entire content of the `gui` CI partition failure on both runners. Regression originated in `fbc064a8`. | The correction must resolve `cooldown.channel_cold` through the same `channel_descriptors[.local].yaml` authority the engine uses, store the exact canonical `ChannelDescriptorV1` rather than a channel string, and require canonical descriptor equality before routing. Two lanes hold the file; it is being sequenced. | **No.** The foreign descriptor is accepted as authoritative. | **CLOSED by `31e8b4ac`.** The GUI resolves `cooldown.channel_cold` through the same `channel_descriptors[.local].yaml` authority the engine uses, stores the exact canonical `ChannelDescriptorV1`, and grants the cold-stage role only on canonical descriptor equality. Both `gui` CI partitions are green on both runners at `94ad6812`. Three regressions pin it: a foreign same-`channel_id` descriptor is refused the role; **it still routes as an ordinary temperature channel** — the failure mode that forced an earlier revert, kept outside the identity check; and an authority-declared rename still routes. BLOCKS-DEPLOYMENT remains for the wider OC-008 spelling surface. | GUI owner |

| OC-033 | C2 | Critical-input authority reduced to raw channel spelling on the RUN path | **IMPLEMENTED; CYCLE 2 EVIDENCE OPEN.** `critical_channels` in `config/safety.yaml` now declares exact opaque canonical identities instead of regex selectors; startup resolves each declaration to exactly one descriptor-owned `(instrument_id, emitted_channel)` pair and **fails closed** on missing, duplicate/ambiguous, source-readback/cross-output or misclassified associations. Preconditions, operator snapshots, stale/missing/status faults and rate ingestion all use exact pair membership, and rate buffers key on the declaring canonical ID so same-label readings from different instruments can no longer merge. A regex path survives only for explicit mock mode. What remains unestablished is Cycle 2 final-candidate qualification. | Without the required final evidence, the implementation cannot be treated as independently approved at a frozen candidate or as completed checkpoint evidence. | `tests/core/test_safety_critical_input_identity.py` has 11 behavioural nodes; an unfrozen current-worktree diagnostic passes all 11 and is not reusable acceptance evidence. Ordinary hosted `CryoDAQ CI` run `30414396538` at `94ad6812` also ran both `core` jobs green, but the overall workflow was red and this was neither a protected P7 run nor independent frozen-candidate review. Both defect directions were reproduced RED before the fix: a foreign-only reading authorized RUN, and a foreign substitution while running suppressed the fault. The repaired behavior refuses the precondition and latches the fault with sources cleared and emergency-OFF commanded. | The local behavior and ordinary hosted partition results support the implementation. They do not supply a P5 frozen candidate, the two P6 final-review approvals, or the ordinary-plus-protected exact-SHA P7 receipts. | **Yes in the tested behavior; Cycle 2 acceptance is pending.** Startup refuses an unresolvable binding. | P5 freeze, both P6 independent approvals, and both successful exact-SHA P7 run IDs and artifact receipts. **BLOCKS-CHECKPOINT.** | Safety owner |
| OC-034 | substrate | Qualified-artifact promotion enforcement | The promotion refusal exists in code and refuses a missing, mismatched or wrong-digest receipt, but it is **not yet a status the repository requires**. Nothing outside the workflow prevents a release being published by another route. | A qualified-looking artifact can still be published: by uploading directly to a release outside this workflow; by altering the validator or workflow without protected-workflow or ruleset enforcement; by controlling the configured qualification workflow, or making it emit receipts for a failed qualification; or by uploading a plain wheel manually, which the validator would refuse but which never reaches the validator. | `build_scripts/artifact_promotion.py`; `.github/workflows/qualified-artifact-promotion.yml`; `tests/test_artifact_promotion.py`. The former `44 passed, 1 skipped` count is unbound historical context, not current or reusable evidence. The current file has nine tests; an unfrozen current-worktree diagnostic passes all nine. | Closure requires a **GitHub repository ruleset** — an owner action on repository settings, not a code change. The receipt's `binding_digest` is tamper detection, not a signature: authority comes from the trusted qualification workflow run, so a hand-written receipt is refused only because the workflow checks the run, not because the file is unforgeable. | **Yes** within the workflow; **no** outside it. | Configure the required status and restrict direct release upload. **Owner action. Does NOT move the SHA, so it is a P9 precondition rather than a code blocker.** BLOCKS-DEPLOYMENT. | Repository owner |
| OC-035 | substrate | Default-branch validator authority | Validators are designed to execute from the protected default-branch judge, and real hosted OIDC/REST job binding was observed in Cycle 1. The current Cycle 2 judge exists at commit `3656654d00937230390076bc60a72b279c124aa9`, tree `2bd5e59f73c0326b2a740f7e8d731e390b2a511c`; Cycle 2 must independently review that object and re-establish the hosted facts against the exact candidate. | The ratified checkpoint protects against accidental or agent-induced validator weakening. It does not resist a malicious default-branch commit, compromised runner or GitHub identity, or a same-process Byzantine candidate. | Repository comparison establishes the current judge identity, tree, eight-commit distance from `f5d6434d20dffae62c9f03fbc12f68b03f48351b`, and fourteen changed trust-root paths. `.github/workflows/protected-ci-evidence-gate.yml` and `tests/governance/test_protected_ci_evidence_gate.py` contain the authored mechanism. | The judge object and pin exist, but there are no two P1 review receipts, no protected hosted receipt bound to `3656654d00937230390076bc60a72b279c124aa9`, and no exact-candidate P7 evidence. | **Fail-closed behavior is authored, not yet accepted:** a protected-path run without the candidate repository refuses instead of downgrading. | **Checkpoint prerequisite until P1, P7, and the candidate-bound check succeed; then satisfied only for the ratified checkpoint threat model.** A required-check setting enabled after the requested fast-forward protects subsequent changes; it did not gate that fast-forward. | CI/governance owner |
| OC-036 | substrate | Protected evidence-producer substitution | The protected producer and pytest plugin come from the protected default-branch judge, so candidate copies cannot accidentally weaken them. The candidate tests still execute in the same pytest process and OS account. | The checkpoint covers accidental or agent-induced producer substitution. Deliberate plugin mutation, protocol forgery, background tampering, or equivalent hostile same-authority behavior is outside its claim. | `tools/ci_candidate_runner.py`; `.github/workflows/protected-ci-evidence-gate.yml`. The authored repair is present in judge commit `3656654d00937230390076bc60a72b279c124aa9`: it roots producer-object verification in the candidate repository and pins the protected CI lock. The protected lock is version-pinned without artifact hashes and is an owner-authored candidate-compatible snapshot, not reviewed evidence. | Independent review and hosted proof remain absent. Same-process Byzantine resistance remains open; the hashless lock also does not establish artifact immutability. | **Yes** for the specified accidental/agent-induced producer-substitution attack after Cycle 2 prerequisite evidence; **no claim** for hostile same-process behavior. | **Checkpoint prerequisite for the specified accidental/agent-induced producer-substitution attack; residual Byzantine same-process resistance is BLOCKS-DEPLOYMENT disclosure debt.** | CI/evidence owner |
| OC-037 | substrate | Release-promotion receipt carries no cryptographic authenticity | `build_scripts/artifact_promotion.py:validate_receipt` accepted any receipt whose `binding_digest` equalled `receipt_binding_digest(receipt)` - a plain SHA-256 over the receipt's own other fields. No key, no signature, no external authority: tamper detection where authentication was required. Meanwhile an actually signed receipt format existed in tree (`cryodaq/core/qualification.py`, RSA-SHA256 against an embedded root, with expiry and replay consumption) and the release path did not use it - two definitions of qualified, with release using the weaker one. | An artifact stamped `UNQUALIFIED - TEST ONLY` can be promoted on an invented receipt **by anyone who can call `promote()` directly**. *** SEVERITY IS NARROWER THAN FIRST WRITTEN, and the correction is recorded rather than quietly applied: `.github/workflows/qualified-artifact-promotion.yml` validates the receipt's PROVENANCE before calling `promote` - qualification-run `conclusion=success`, `head_sha` equal to the candidate commit, and `workflow_id` equal to `vars.QUALIFICATION_WORKFLOW_ID`, with a regex that fails closed when that variable is unset. The exploit below bypassed all of it by calling the function directly. No workflow in this repository produces a qualification receipt, so that variable names something out of tree, or nothing. *** | Deterministic reproduction: builds a real artifact through the repository's own `_wheel()` helper, invents `config_digest`, `hardware_profile_id`, `commit` and `tree`, computes the binding digest itself, and receives `status: PROMOTED` from the production `promote()` path. **CONTROL: tampering a field WITHOUT recomputing the digest is correctly refused**, so the check is not inert - it is the wrong kind of check. | A reconciliation onto the signed verifier was produced and **withheld**: it was authored from a worktree predating P3 and rewrote `tests/test_artifact_promotion.py` from scratch, losing four of P3's seven tests including `test_post_build_marks_onedir_unqualified` - P3's own UNQUALIFIED-marker guard. Being reconciled against P3's real file. | **No** as a function; **yes** in the deployed workflow, which fails closed when the qualification-workflow variable is unset. | **Disclosure row, not a checkpoint blocker**, on the strength of the workflow-layer provenance check. *** IT BECOMES A CLAUSE-2 BLOCKER the moment a qualification workflow is brought in tree, because the candidate would then author its own receipts. *** BLOCKS-DEPLOYMENT. | Packaging/CI owner |
| OC-038 | substrate | Default-branch protected evidence gate qualification | The protected workflow is present on `master`; deployment absence was the Cycle 1 defect and is no longer the current statement. The repaired successor also exists at commit `3656654d00937230390076bc60a72b279c124aa9`, tree `2bd5e59f73c0326b2a740f7e8d731e390b2a511c`. Cycle 1 nevertheless ended `NOT_PR_READY` after the guard-root defect was found. | OC-035 and OC-036 cannot receive Cycle 2 acceptance credit until this exact default-branch judge is independently reviewed and proven in hosted execution against the exact candidate. | Repository comparison binds the current judge to eight commits after `f5d6434d20dffae62c9f03fbc12f68b03f48351b` and fourteen changed trust-root paths. This is object and inventory evidence only. | The implementation is authored evidence. No P1 review receipts or protected hosted receipt bound to the current judge exist. | **Pending.** Missing required candidate-repository context refuses in the authored repair, but acceptance awaits independent review and hosted proof. | Cycle 2 prerequisite through P1 and P7; not closed by object measurement or local diagnostics. | Owner + CI/evidence owner |
| OC-039 | substrate | Fixed-port/startup race in the REQUIRED `core` partition | `tests/core/test_zmq_safety.py::test_heartbeat_has_timestamp` has a measured fixed-port/startup race. | It fails only in the safe direction: a good candidate can be rejected, but a bad candidate is not admitted. | The node failed and then passed on byte-identical inputs; that rerun was diagnostic evidence of the race, not a fix or acceptance credit. | The deterministic dynamic-port repair remains unscheduled disclosure debt. Retrying until green would weaken the gate and is forbidden. | **Yes.** A spurious failure blocks rather than admits. | **BLOCKS-DEPLOYMENT; disclosure debt. It is not scheduled work and does not independently block the checkpoint classification.** If it makes P7 red, the one-shot cycle terminates because required hosted evidence is red, not because OC-039 was promoted to a blocker. | CI owner |

## Closed during this cycle — recorded so the register is not read as static

- **OC-006 is closed.** A source channel absent from `_active_sources` is no
  longer published as `off`. The publication now reads the exact
  `SourceOffEvidence.channel_off_results` entry: `off` only when that entry is
  `DEVICE_REPORTED_OFF`, otherwise `unknown` with a `NaN` value, so an operator
  sees unknown as unknown on a channel that can energise a heater. Absence from a
  host-side bookkeeping set is no longer treated as an observation of the
  instrument. Every consumer of `analytics/keithley_channel_state/*` was traced,
  and the Keithley panel renders the unknown state visibly rather than dropping
  the readout.

- The static dashboard no longer classifies temperature from channel spelling
  (`1af677be`), with browser regressions. Former OC-009.
- `continue-on-error` was removed from the candidate step (`4cee6901`), and the
  test that mandated it was changed with it.
- G4 now resolves unmarked executable references and accepts all three result
  classes (`1d2c43ad`). Former OC-019. **That commit relaxed a guard while its
  message described a strengthening; see `docs/CLAIM_CORRECTIONS.md`.**
- OC-020 is OPEN, after two failed attempts in opposite directions. The first
  held the export read-only; the candidate owns those permissions and simply
  restored them, so it raised a bar without closing a blocker. The second was a
  real authority boundary — low integrity on Windows, UID `nobody` on Linux — and
  it defeated every attack, but it took all eight hosted CI jobs red, `core`
  included, with the candidate suite exiting before any test ran. Both layers
  were withdrawn. **Two lessons kept. A lane's red, green and control can all be
  genuine while its threat model is wrong. And a boundary proven on a local
  fixture is not proven: this one had to be demonstrated on the hosted runners,
  and was not.**
- The OFF evidence tier no longer collapses; OC-013 is narrowed to the physical
  proof claim, which no software change can close.
- An active threshold alarm now holds when its channel state disappears, instead
  of clearing. At the previous head, an **active CRITICAL alarm whose channel
  vanished silently cleared** — an all-clear manufactured from blindness.
- An active phase with a missing or unparseable start returns `None` rather than
  a numeric `0.0` elapsed time.
- `/temps`, `/pressure`, `/keithley` and `/status` render cached values as stale
  with an age, or unavailable with a reason, instead of as plain numbers.
- A completed no-op action shim no longer logs a CRITICAL success claim.
- Failed journal persistence no longer emits `event_logged`.
- The descriptor projection is bound, so a generated report carries its chart.
  **The premise was wrong and is corrected here:** nothing had unbound it. The
  projection was introduced without a production caller in `cbcf1408` and carried
  through unreferenced, so reports never had charts rather than having lost them.
- Pytest plugins load once per invocation, clearing the Ubuntu CI collection abort.

- **OC-001 is closed.** The archive adapter distinguishes an invalid request from
  an authoritative empty result, and the C1 adapter guard's
  `_KNOWN_PRODUCTION_VIOLATIONS` baseline is empty again.
- **OC-010 is closed.** `_CYRILLIC_T` and `_channel_key` are gone from the
  periodic renderer; ordering follows the authority-supplied order, and the C2
  guard's exception set is empty.
- **OC-016 is closed.** The heater target-power banner reports that the engine
  accepted the request and that actual power appears at the next measurement,
  instead of claiming execution.
- **OC-022 is closed.** `.gitattributes` pins the receipt-bound guard sources to
  LF, verified cross-platform: both guard blobs hash identically on Windows and
  Ubuntu.

## Undisclosed debt found by the whole-PR coverage rebuild

A rebuild of the coverage matrix across **31 area boundaries covering all 792
changed paths exactly once** found identity-inference debt not previously in this
register: assistant context and broker routing, three sites in the web server,
periodic notification routing, and further sites in core housekeeping, the
channel manager and the rate estimator. These are recorded here as known and
undisclosed-until-now rather than left for the next sweep to rediscover.

The same rebuild established two things this register should state plainly:

- **No whole-area, whole-defect-class cell qualifies as SEALED.** Every guard is a
  regression detector for named shapes, not a seal over a surface.
- **Some changed areas are invisible to every CI partition** — the visual assets
  and knowledge-seed READMEs entirely, plus `build.bat`, `build.sh`,
  `create_shortcut.py` and `docs-gate.yml`. The areas with the least
  whole-area review evidence are health authority, build and packaging, sinks,
  test infrastructure, and the soak and evidence scripts.

## *** SUPERSEDED CYCLE 1 DETERMINATION (HISTORICAL): DO NOT MERGE ***

Ruled 2026-07-29 by the independent reviewer under the Cycle 1 model. Cycle 1
terminated `NOT_PR_READY`; the owner-ratified plan superseded this determination
and the owner authorized Cycle 2. The text through the next divider is retained
as Cycle 1 history, not as Cycle 2 classification or review evidence.

**Two blockers are unmet, and neither can be closed by further work on this branch alone.**

**OC-020 — the interlock's honest control has never run on Windows.** The candidate sandbox child
exits `0xC0000142` (STATUS_DLL_INIT_FAILED) with empty stderr on `windows-latest` and on a
developer machine alike: it terminates before Python starts. In the reviewer's words, *"a child
that exits 0xC0000142 before Python starts is not a failing attack; it is a missing control."*
A Linux ordering defect in the same layer was found and corrected, and one ubuntu partition then
passed its honest control for the first time — **that is diagnostic evidence and is explicitly not
a closure.** A green subset does not satisfy a criterion that requires both hosted operating
systems. The restricted token must not be relaxed merely to get Python to start, and no fourth
speculative attempt should be made without a specific loader-level diagnosis.

**OC-038 — the protected evidence chain had not executed in Cycle 1.**
`workflow_run` workflows load from the default branch, where the protected
workflow was then absent. The ordinary 8/8 CI result was real, and its separate
exact-checkout guard did resolve Git objects; only the exported subrun skipped
Git resolution because no repository was present. Ordinary CI coverage was not
quietly disabled. The missing evidence was independent adjudication from the
protected default-branch judge.

*** A CLASSIFICATION ARGUMENT WAS PUT AND REJECTED, and it is recorded because rejecting it is
part of the finding. *** It was argued that OC-038 might be a P9 precondition like OC-034, since
a push to `master` does not move this PR's head SHA. The reviewer's answer: the premise is true and
insufficient — *"SHA movement is an evidence-invalidation question, not the blocker-classification
test"* — and the argument was rationalising toward the convenient answer. OC-034 governs later
promotion routes and its absence does not falsify the evidence used to review this PR; OC-038
removes the authority behind that evidence. Both requiring an owner action does not make them the
same class.

**The gate is not unsatisfiable.** A candidate copy cannot guard its own bootstrap, but an
explicitly reviewed owner bootstrap of the protected workflow — together with its full judge and
producer dependency closure, not the YAML alone — onto `master` installs the trust root. A
subsequent fresh run can then execute that workflow against the unchanged PR SHA. That is an
ordinary root-of-trust bootstrap, not an amendment to a merge property.

**The order of operations from here**, in the reviewer's sequence: record the in-flight run as
candidate-workflow evidence only; keep the Linux scratch result as diagnostics; obtain a specific
Windows loader diagnosis before any further sandbox change; close OC-020 only after honest controls
AND attacks pass on both hosted systems with independent review; then the reviewed owner bootstrap
onto `master`; then a fresh run against the frozen SHA requiring actual protected jobs, eight
successful protected executions and the ACCEPTED partition receipt; only then close OC-038 and
adjudicate OC-035/036; and finally the P9 settings actions, with the PR diff re-audited because the
default branch will have moved.

---

## Merge-blocker classification — the ratified rule applied to every row

A row blocks merge **only when exact structural evidence or deterministic reproduction**
establishes that it can (1) initiate or maintain energization, or delay, suppress or obstruct
OFF/stop; (2) bypass qualification verification or unqualified-artifact promotion refusal;
(3) present false `safe`/`OFF`/`ready`/`qualified`/`applied`/`complete` truth, or suppress a
required active safety warning, on the primary surface in a permitted unqualified mode; or
(4) make required merge evidence appear final-hash-bound, executed, or passed when it was not.
Unknown, unexamined, speculative, availability-only and safely-rejecting rows are disclosure rows.

For Cycle 2, OC-035, OC-036, and OC-038 are checkpoint prerequisites until judge
commit `3656654d00937230390076bc60a72b279c124aa9`, tree
`2bd5e59f73c0326b2a740f7e8d731e390b2a511c`, is independently reviewed and
proven by the exact candidate-bound and hosted P7 evidence. Its object identity
is pinned; its P1 and hosted acceptance evidence is not. Their eventual
satisfaction is limited to the owner's accidental/agent-induced weakening
threat model.

OC-020 and OC-039 are **BLOCKS-DEPLOYMENT disclosure debt, not checkpoint
blockers**. OC-020's ordinary same-authority mutate-execute-restore residual and
OC-036's hostile same-process residual remain open. OC-039 terminates the
one-shot cycle if it makes required P7 evidence red, because the required check
is red, not because the defect is reclassified.

The model does not claim resistance to a malicious default-branch commit,
compromised runner or GitHub identity, hostile candidate code in the same pytest
process or OS account, package-index compromise, or artifact immutability from
the version-only protected lock. The required-check setting performed after the
requested fast-forward governs later changes; it does not retroactively gate
that fast-forward.

OC-034 remains an owner repository-settings action at P9. OC-037 remains a
disclosure row under its recorded workflow-layer narrowing. OC-021 and OC-033
are open for the Cycle 2 evidence described above. Closed OC-029 and OC-032
retain their existing dispositions.

## Where this register is least trustworthy

Every entry above rests on examination that has been wrong before. Three specific
cautions for whoever reads this next:

- **Refutations deserve the scrutiny of fixes.** A lane refuted the assistant
  availability finding by examining the diagnostics cache; the advisor then
  identified a different path in the same function. A partial refutation reads
  exactly like a complete one.
- **"Unexamined" rows are the cheapest to get wrong,** because nothing contradicts
  them. Two rows previously marked unexamined turned out to have concrete live
  instances.
- **Guard rows are written by the people the guards failed to catch.** Every guard
  named here passed cleanly at the moment an adversary broke it.

## Examined and refuted — not defects

- `keithley_set_limits` does **not** claim execution from acceptance. The driver
  writes each limit and then queries `source.limitv` / `source.limiti` back from
  the device, raising on mismatch, and SafetyManager awaits that before returning
  success. Its "Engine confirmed execution" wording is earned. It was flagged as a
  sibling of the target-power defect and is not one; start and stop are likewise
  backed by output readback. The GUI is the only sender, and no Telegram or
  automation caller renders a limits success banner.

- The assistant's live diagnostics cache does **not** collapse availability: it
  returns a summary only after receipt-freshness validation, and clears to `None`
  on failed polls, invalid receipts and expiry. An engine-down probe renders both
  diagnostics and event count as unavailable.
- The forward-gap stale rate is deliberately held to avoid a safety blind window,
  and is explicitly guarded. Changing it would weaken the OFF path.
- The descriptor-first classifier's constrained legacy fallback is a documented
  compatibility contract, not an inference defect.
