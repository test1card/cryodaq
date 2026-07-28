# OPEN cells — Montana partial-checkpoint register

**Verified against `e642cba4` plus the changes landing in this commit.** This
register is the PR's disclosure of what remains unsealed. It is not a claim that
every C1/C2/C3 surface is sealed, that physical OFF has been proven, or that the
candidate is approved for deployment.

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
| OC-020 | substrate | Candidate immutability during execution | **CLOSED.** The candidate now executes with authority that cannot rewrite the exported tree, so the mutation is prevented rather than detected afterwards. On Windows a trusted launcher outside the export strips every token privilege except `SeChangeNotifyPrivilege` and drops itself to low integrity before any candidate byte runs; the export stays medium-integrity and only the state tree is low-integrity, so write-up is denied. On Linux a passwordless-`sudo` helper re-owns writable state and executes as UID/GID `nobody`. Descendants inherit the reduced authority. Post-run manifest validation is retained as defence in depth, not as the boundary. | — | `tools/candidate_sandbox.py`; `tools/candidate_evidence.py`; regressions in `tests/governance/test_candidate_evidence_binding.py`. The chmod-restore reproduction that defeated the previous fix now returns `PermissionError [WinError 5]`, exit 1, receipt refused. Delete-recreate, rename/replace, subprocess-chmod, hardlink-write, ACL-rewrite, isolated-flag and launcher-mutation attacks all refused on Windows; chmod-restore, delete-recreate, rename/replace, subprocess-chmod and hardlink-write all refused on Linux. Honest control passes on both. | Defeating it now requires higher OS authority: a medium/high token, an inherited medium-authority handle, a privileged confused deputy, an elevation broker, or privilege escalation. | **Yes.** On Linux without passwordless sudo or root, execution fails closed rather than issuing evidence. | Residual, disclosed: this is an immutable-export boundary, not instruction provenance — a candidate can still generate and execute code in memory or writable state. It cannot use that to mutate-execute-restore the sealed export. Hosted-CI confirmation on fresh runners is owed at the frozen head. | CI/evidence owner |
| OC-021 | substrate | Montana candidate gate | **CLOSED.** The gate now runs as an unconditional step in every OS/suite matrix job, with no `if` and no `continue-on-error`, and the job's final enforcement step requires `steps.montana-candidate-gate.outcome == success` under `if: always()` — so a skipped gate also fails the job. Deletion was rejected as closure because this plan relies on its contract. | — | **The gate has since MOVED, and this row moved with it.** It no longer runs inside the matrix from candidate bytes; it runs in `.github/workflows/protected-ci-evidence-gate.yml` from a SHA-pinned judge checkout, over all eight downloaded bundles. Regression guards in `tests/test_ci_candidate_evidence.py` and `tests/governance/test_protected_ci_evidence_gate.py`; a behavioural test executes the CLI and observes exit 1 on a violating bundle and exit 0 on the control. | — | **Yes.** The validator can now refuse a real candidate. | Verified independently at the frozen head under P7. | CI/governance owner |

| OC-023 | C2 | Interlock channel routing | Interlock routing still resolves channels by regex over identifier spelling rather than a declared binding. | An interlock can bind to the wrong channel, or fail to bind, after a legitimate rename — on the safety path. | Confirmed by direct reading this cycle; declared-ID coverage proves the current IDs, not the contract. | Replacing it requires descriptor-backed interlock configuration and engine-wiring changes. | **No.** | Descriptor-backed interlock configuration. BLOCKS-DEPLOYMENT. | Safety + engine-wiring owner |
| OC-024 | C3 | Archive finalisation rows | Finalisation rows carry only timestamp, instrument, channel, value, unit and status — no descriptor data — so archive grouping cannot be descriptor-derived. | An archived record cannot later be attributed to a declared measurement identity; downstream grouping falls back to spelling. | Confirmed by direct reading of the finalisation row shape this cycle. | Requires the archive-descriptor migration. | **Unknown.** | Descriptor data in finalisation rows. BLOCKS-DEPLOYMENT. | Storage owner |
| OC-025 | C2 | Telegram descriptor authority | The Telegram surface has no descriptor authority; its only production constructor is `src/cryodaq/engine.py`. | Operator command output infers physical meaning from spelling. Paired with OC-011. | `src/cryodaq/notifications/telegram_commands.py`; `src/cryodaq/engine.py`. | Removing the inference without a descriptor contract would hide valid operator readouts. | **No.** | A descriptor authority reaching the notification surface. BLOCKS-DEPLOYMENT. | Assistant + engine-wiring owner |
| OC-026 | C3 | Notification delivery proof | **Narrowed.** `src/cryodaq/notifications/telegram.py` now records four tiers and neither success tier claims a human received the message. **Two siblings remain:** `agents.assistant_main.TelegramSender` parses `ok` but marks `ok: true` as delivered without requiring `result.message_id`; and `PeriodicReporter._send_photo` logs a report as sent on a bare HTTP 200. | An audit trail can still record an operator notification as delivered when only the transport accepted it, on the assistant path and on the periodic-report path. | `src/cryodaq/agents/assistant_main.py` (`TelegramSender`) and its `output_router` delivery predicate; `src/cryodaq/notifications/periodic_report.py` (`_send_photo`). | Both are outside the lane that fixed the alarm transport, and closing the assistant one requires changing `TelegramSender`, the output-router delivery predicate, and the audit tests together. | **No** for both remaining paths. | Apply the same four-tier vocabulary to both. BLOCKS-DEPLOYMENT. | Assistant owner |
| OC-027 | C1b | GUI cold-stage declaration | The GUI re-reads `cooldown.yaml` itself to decide which channel is the cold stage, instead of consuming what the engine applied. In replay mode the replay server overrides the cold channel, so the GUI can render warm-plate data as the cold-stage steady state — silently, because a non-`None` declaration suppresses the unavailable rendering. | An operator sees a confident cold-stage readout that is not the cold stage. | `src/cryodaq/gui/shell/main_window_v2.py` `_declared_cold_stage_channel()`; the replay override in the replay server. | Repair is in flight; the engine must publish the applied declaration and the GUI must consume it. | **No.** The false declaration suppresses the unavailable path. | Engine publishes applied `channel_cold`; GUI consumes it and stops reading the file. BLOCKS-DEPLOYMENT. | GUI + engine-wiring owner |
| OC-028 | C3 | Alarm narration suppression has no upper bound | The unbounded re-narration storm is fixed by recording the attempt at the dedup gate. **The opposite bound is now missing:** the ledger uses a 30-second sliding quiet window that each refire refreshes, so continuous flapping suppresses indefinitely; transport recovery does not re-arm it; and a still-active CRITICAL alarm that emits no new `alarm_fired` event will not re-narrate. | An operator can stop being told about a CRITICAL condition that is still active — including the case where the transport was broken during the first attempt and has since recovered. | `src/cryodaq/agents/assistant/live/agent.py` ledger and gate. | The fix deliberately chose the better failure: an operator buried in repeats stops reading them. But no sustained-CRITICAL escalation or transport-recovery re-arm exists on this path. | **No.** Suppression is silent. | A re-arm on transport recovery, or an escalation for a CRITICAL that remains active across N suppressed windows. BLOCKS-DEPLOYMENT. | Assistant owner |

| OC-032 | C2 | GUI cold-stage specialist routing accepts a foreign descriptor | The GUI selects the cold stage from configuration — which is correct — but then matches on `channel_id` equality alone instead of resolving that declaration through the active descriptor manifest. A self-consistent **foreign** descriptor arriving first on a fresh GUI session is accepted as `authoritative`, and its matching channel id routes it as the cold stage. | It contaminates the cooldown plot, the raw history, the steady-state predictor, cached analytics state and phase-replay state. **Observational only — it does not reach SafetyManager or actuator control**, which is why this is not a checkpoint blocker under the blocker rule. | `src/cryodaq/gui/shell/main_window_v2.py` cold-stage routing; the regression that catches it is `tests/gui/test_f35_descriptor_specialized_routing.py`, whose two failing nodes are the entire content of the `gui` CI partition failure on both runners. Regression originated in `fbc064a8`. | The correction must resolve `cooldown.channel_cold` through the same `channel_descriptors[.local].yaml` authority the engine uses, store the exact canonical `ChannelDescriptorV1` rather than a channel string, and require canonical descriptor equality before routing. Two lanes hold the file; it is being sequenced. | **No.** The foreign descriptor is accepted as authoritative. | Canonical descriptor equality, with the generic temperature routing preserved. **A production probe confirmed refusing specialist authority does NOT make the ordinary temperature readout vanish** — the failure mode that forced an earlier revert. BLOCKS-DEPLOYMENT, and blocks CI green. | GUI owner |

| OC-033 | C2 | **Critical-input authority reduced to raw channel spelling on the RUN path** | `safety_manager.py` discards `_instrument_id` when evaluating run preconditions, so a foreign fresh reading carrying the same raw label can satisfy a critical input and contribute to RUN authorization. The stale, status and rate checks that lead to `_fault()` discard instrument ownership the same way. `safety_pattern_liveness.py` resolves canonical critical inputs to raw-label regexes. | Both directions reach actuation: a false positive helps **authorize energization**; a false negative or substitution **suppresses the `_fault()` that commands OFF**. This is the third instance of the class that produced OC-029, on the authorization side rather than the heartbeat. | `src/cryodaq/core/safety_manager.py` precondition, stale, status and rate paths; `src/cryodaq/core/safety_pattern_liveness.py`. Found by the lane that closed OC-029. | Repair in flight, reusing the exact `(instrument_id, emitted_channel)` ownership scheme that closed OC-029 rather than inventing a second identity scheme. | **No.** | Exact declared ownership for critical inputs, startup failing closed on missing/ambiguous/foreign/cross-output. **MERGE BLOCKER — clause 1.** | Safety owner |
| OC-034 | substrate | Qualified-artifact promotion enforcement | The promotion refusal exists in code and refuses a missing, mismatched or wrong-digest receipt, but it is **not yet a status the repository requires**. Nothing outside the workflow prevents a release being published by another route. | A qualified-looking artifact can still be published: by uploading directly to a release outside this workflow; by altering the validator or workflow without protected-workflow or ruleset enforcement; by controlling the configured qualification workflow, or making it emit receipts for a failed qualification; or by uploading a plain wheel manually, which the validator would refuse but which never reaches the validator. | `build_scripts/artifact_promotion.py`; `.github/workflows/qualified-artifact-promotion.yml`; `tests/test_artifact_promotion.py` (44 passed, 1 skipped). | Closure requires a **GitHub repository ruleset** — an owner action on repository settings, not a code change. The receipt's `binding_digest` is tamper detection, not a signature: authority comes from the trusted qualification workflow run, so a hand-written receipt is refused only because the workflow checks the run, not because the file is unforgeable. | **Yes** within the workflow; **no** outside it. | Configure the required status and restrict direct release upload. **Owner action. Does NOT move the SHA, so it is a P9 precondition rather than a code blocker.** BLOCKS-DEPLOYMENT. | Repository owner |
| OC-035 | substrate | Validators execute from candidate-controlled bytes | **NARROWED, NOT CLOSED.** The judge no longer comes from the candidate: both validators now run from a SHA-pinned checkout inside a protected `workflow_run` workflow, with SHA-256 verification of every validator and dependency before execution. Proven: candidate copies replaced by unconditional `SystemExit(0)` judges still yield exit 1 from the pinned copies. | What remains is (i) no cryptographic job binding — the receipt carries no GitHub-signed job identity, so cross-job substitution is resisted by time-window and log correlation only; and (ii) the required-check settings, which code cannot declare for itself. | `.github/workflows/protected-ci-evidence-gate.yml`; `tests/governance/test_protected_ci_evidence_gate.py`; candidate-weakening proof in the same file. | Closing (i) needs `job.check_run_id` in the receipt bound to a GitHub OIDC attestation and verified against the REST job ID, run ID, SHA and protected workflow identity — that field is in another lane's file and was deliberately not seized. Closing (ii) is an OWNER settings action. | **Yes** for the judge; **no** for job identity. | Bind the job cryptographically; owner requires the protected check. BLOCKS-DEPLOYMENT. | CI/governance owner |
| OC-036 | substrate | Evidence producer is candidate-controlled | Pinning the JUDGE does not pin the PRODUCER. `tools/ci_candidate_runner.py` and its pytest plugin, which emit the population receipts, still come from the candidate. A subverted producer can emit canonical, internally-consistent, SHA-bound receipts claiming positive collected and executed counts **without running the declared tests**, reproduce them in the job log, and upload hash-consistent bundles under the expected names. | The protected validator would confirm the receipts are consistent and candidate-SHA-bound, but not that pytest produced them — required merge evidence appearing executed when it was not. | Identified by the wiring lane as the attack it would use against its own gate. `tools/ci_candidate_runner.py`; the population-receipt plugin. | Needs a protected runner/plugin or a GitHub-signed execution attestation. Pinning the judge, which is done, does not reach it. | **No.** | Protect the producer, or sign the execution. BLOCKS-DEPLOYMENT. | CI/evidence owner |

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
- OC-020 is CLOSED, at the second attempt. The first fix held the export
  read-only during execution; the candidate runs as the same user and could
  simply restore write permission, so it raised a bar without closing a blocker.
  The closure is an authority boundary the candidate cannot revoke — low
  integrity on Windows, UID `nobody` on Linux — entered before any candidate byte
  executes. **The lesson kept: that first lane's red, green and control were all
  genuine. Its threat model was wrong. Real evidence does not make a blocker
  closed.**
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

## Merge-blocker classification — the ratified rule applied to every row

A row blocks merge **only when exact structural evidence or deterministic reproduction**
establishes that it can (1) initiate or maintain energization, or delay, suppress or obstruct
OFF/stop; (2) bypass qualification verification or unqualified-artifact promotion refusal;
(3) present false `safe`/`OFF`/`ready`/`qualified`/`applied`/`complete` truth, or suppress a
required active safety warning, on the primary surface in a permitted unqualified mode; or
(4) make required merge evidence appear final-hash-bound, executed, or passed when it was not.
Unknown, unexamined, speculative, availability-only and safely-rejecting rows are disclosure rows.

**Blockers: OC-033 (1), OC-035 (4), OC-036 (4).** OC-020 was a blocker under clause 4 and is now closed by an
authority boundary the candidate cannot revoke; the reproduction that defeated the previous
attempt is refused. OC-034 is deliberately NOT counted as a code blocker: its
closure is a repository-settings action that does not move the SHA, so it cannot void a review.
It is a precondition on the merge act itself, owed by the repository owner at P9. OC-029 was a blocker under clause 1 and is closed.
OC-021 was a blocker under clause 4 and is closed: the Montana gate is now an unconditional,
required step in every matrix job. OC-020 remains open — the read-only export defeats a naive
mutate-run-restore but not a `chmod`-restore bypass, which was reproduced against the fix.

Two rows were checked rather than assumed, because the rule says apply it to every row and do not
assume the count:

- **OC-023 — row, not blocker.** Interlocks bind by regex `channel_pattern`, which is
  spelling-derived identity on a safety path. But as the tree ships, those patterns match the
  declared canonical channel ids, so the interlock binds and fires. The defect is latent on a
  legitimate rename, which is a deployment concern rather than a property of the shipped tree.
- **OC-028 — row, not blocker.** Narration suppression is a secondary path. The alarm engine's
  own active set is the primary surface and is independent of the assistant's dedup ledger, so a
  suppressed re-narration does not hide an active CRITICAL from the primary surface.

Everything else is unknown, unexamined, availability-only, safely-rejecting, or observational
without reaching actuation — including OC-032, which routes a foreign descriptor as the cold stage
on an operator display but does not reach SafetyManager or actuator control.

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
