# Claim corrections

Commit messages on this branch are load-bearing evidence for reviewers and the
owner. When a message claims more, less, or something different from what its
commit establishes, that mismatch is a defect of the same class being removed:
a claim unsupported by what it describes. Landed commits are not rewritten;
this record preserves the correction and its evidence.

| Commit | Claim as written | What is actually true | Evidence re-derived | Category |
| --- | --- | --- | --- | --- |
| `d29cf4bc` | "235 passed across tests/web, tests/test_rest_api.py and tests/test_web_dashboard.py, plus tests/core/test_memory_leaks.py (12 passed)." | The complete cited set was **247 passed**: 235 in the first three partitions and 12 in the memory-leak partition. Presenting 235 as the cited-set figure omitted the stated final partition. | At the landed tree, the three non-web partitions contain 196, 18, and 12 passing cases. The historical web partition contains 21, for 21 + 196 + 18 + 12 = 247. The current separate runs report 26, 196, 18, and 12; the five-case difference is from the later edit to the dashboard-unavailability contract test. | **FALSE** |
| `b1ad7ca0` | "Proven by negative case, twice and independently," including rendering the unavailable typed results. | The availability-rendering red-before is not behavioural proof. The parent `CooldownETA` rejects the newly introduced `available=` keyword with `TypeError`; other new rendering cases dereference newly introduced `.available` on old `None` results. Those failures are caused by symbols and fields added by this commit. The distinct value-level adapter cases that establish that an old failed reply is `None` where the new contract requires a typed unavailable result remain valid behavioural evidence. | The new rendering test constructs all result types with `available=False`, while the parent schemas lack those fields; the parent adapter returns `None` on failed replies. The same distinction is disclosed correctly by `ef022ab5`: it says its old `test_agent_dedup.py` red is an `AttributeError` and explicitly excludes it as proof, retaining its alarm-flow evidence instead. | **FALSE** |
| `3d6d1a22` | The broadened C2 guard is presented as the new seal without disclosing an exemption introduced with it. | The commit added a real C2 exemption for `src/cryodaq/reporting/periodic_renderer.py` at line 142, for thermometry-style sorting, while the guard comment still said C2 had no exemptions. `5354fb9c` is not implicated: its allowlist was empty when it landed; this exemption was added later. | The parent C2 guard has an empty `_ALLOWLIST`. This commit adds the `(periodic_renderer, 142)` `BLOCKED-ON-SCHEMA` entry, and the renderer's `_channel_key` performs the matched channel-name ordering. | **UNDISCLOSED** |
| `b1ad7ca0` | "927 passed, 2 skipped across tests/agents." | This was a historical measurement, not a false claim. It cannot be reproduced as a comparable count on this tree and host. | Later commits changed several tests in the partition, including the C1 seal and alarm-delivery tests. A separate current run reports 924 passed, 3 skipped, 1 deselected, and 7 failures; every failure is `WinError 1314` while creating a symlink. This host lacks the symlink privilege available to CI. | **STALE** |
| `ef022ab5` | "932 passed, 2 skipped across tests/agents." | This was a historical measurement, not a false claim. It cannot be reproduced as a comparable count on this tree and host. | The same later test changes and current host limitation apply. The current separate `tests/agents` run reaches 924 passed, 3 skipped, 1 deselected, and 7 `WinError 1314` symlink-creation failures, so it is not evidence against the landed count. | **STALE** |
| `5354fb9c` | "508 passed, 12 skipped across tests/analytics and tests/reporting." | This was a historical measurement, not a false claim. It is not comparable to the current tree. | The later C2 broadening changed the analytics guard test included in this cited set. A current analytics-only rerun was stopped by the session command window before completion; it must not be represented as a rerun of the landed count. The host also lacks the symlink privilege that CI provides, independently demonstrated by the current agents partition. | **STALE** |
| `3d6d1a22` (second and third omissions) | "Broaden two guards that asserted a class while proving one shape." | Besides the C2 allowlist entry recorded above, the same commit **narrowed** `_REGEX_METHODS` from six entries to three, and changed the C1 adapter guard's clean baseline from requiring zero findings to accepting `_KNOWN_PRODUCTION_VIOLATIONS` — specifically `archive_adapter.py:get_detail:228`. A commit titled as a broadening performed three separate narrowings, none disclosed. | `tests/agents/assistant/test_c1_engine_adapter_seal.py:31-36` declares the accepted violation and line 228 asserts equality with that set rather than emptiness. The C2 guard's direct-regex method set is three entries where the parent had six. | **UNDISCLOSED** |
| `1d2c43ad` | Presented as a G4 documentation-guard improvement. | It **relaxed** G4: it deleted the unconditional rejection of `SOFTWARE-PROVABLE` procedure declarations and added a test asserting the new acceptance. The relaxation is defensible — a genuinely software-provable procedure previously could not be expressed — but the message did not disclose that a guard stopped rejecting a class it had rejected. | `tests/docs/test_docs_freshness.py:834` now accepts `{"SOFTWARE-PROVABLE", "EXTERNALLY_EVIDENCED", "PHYSICAL"}`. The parent rejected the first unconditionally. | **UNDISCLOSED** |
| `dcdb1912` | G4 rejects a procedure claiming `SOFTWARE-PROVABLE` where the evidence is external or physical. | True in its own diff, and no longer true: `1d2c43ad` deleted that rejection. | Same evidence as the row above. | **STALE** |
| `0f505dd6` | "A driver-level OFF double that returns anything other than a `SourceOffResult` fails CI." | **The guard is not universal.** It exempts five named scopes and skips every `emergency_off` annotated `dict[...]`. Several of those exemptions are legitimate — `test_truthy_non_boolean_proof_cannot_authorize_disconnect` is a negative control that must be able to pass a truthy non-`SourceOffResult` — so the guard's design is sound. The absolute claim was not. | `tests/governance/test_source_off_result_test_doubles.py:10-16` lists `_INTENTIONAL_INVALID_SCOPES`; lines 124-131 skip exempted scopes and `dict[...]`-annotated returns. | **FALSE** |

| `14b2c432` | "Make the disclosure register true at the commit it ships with." Message describes documentation only. | The commit also carried 59 lines of `tests/core/test_safety_operator_snapshot_owner.py` -- tier test expectations whose production code was not yet landed. At the resulting pushed head that file **hangs**: the double is classified `COMMAND_ONLY`, SafetyManager correctly faults closed and never disconnects, and the test waits forever for a disconnect that should not happen. So the commit that claims to close the honesty gap silently broke `tests/core` and invalidated verification claims made after it. | Reproduced at `e642cba4`: the file times out. The tier production code landed later, in `757f4310`, after which the same file passes. | **UNDISCLOSED** |
| `14b2c432` (OC-013) | The register was rewritten to say the OFF evidence tiers "no longer collapse" and are "preserved through SafetyManager -> scheduler -> operator snapshot -> engine receipt -> launcher". | True of a patch that was **not committed at that commit**. The register described unlanded work as landed, in the document whose entire purpose is to be true at the commit it ships with. It became true at `757f4310`. | The tier production change is absent from `git show 14b2c432` and present in `757f4310`. | **FALSE at that head** |
| `6f2ef69a` | "Fold the GUI identifier sites into the one C2 registry." Message states no file under `src/cryodaq/gui/` is modified and describes only the registry. | The commit also carried the entire OC-006 change -- `src/cryodaq/core/safety_manager.py`, `tests/core/test_keithley_channel_state_publish.py` and `tests/gui/shell/overlays/test_keithley_panel.py` -- which is a safety-path publication change, not a registry change. | `git show --stat 6f2ef69a` lists four files; the message accounts for one. | **UNDISCLOSED** |
| `4520d6ac` | "The acceptance control is deterministic and synthetic. A real hosted green run" had never been accepted by the partition-execution verifier. | **True when it landed, and superseded.** The verifier has now accepted a real hosted run: `30419591227` at `eecadd51`, eight partitions, each with a non-zero collected AND executed count. The reject-only gap that commit disclosed is closed. *** It does NOT follow that merge property (b) is established: that acceptance was produced by a verifier running from the CANDIDATE, which is precisely OC-038 — the protected `workflow_run` chain has never executed because the workflow is absent from the default branch. So this is candidate-workflow evidence, not the protected acceptance receipt. *** | The acceptance was only possible after `390e4a29` taught production to publish the population receipts the verifier reads; before it, the `ubuntu/agents` job log carried zero `CRYODAQ_*` markers in 143,302 bytes while the artifact carried two. Measured after: two in the log, matching. | **STALE** |

## The mechanism behind those three, and the protocol change

All three have one cause: **`git apply --3way` stages what it applies.** Every
patch collected from a lane was therefore already in the index, and each
subsequent `git add <specific file>` followed by `git commit` swept up everything
staged, not just the file named. Explicit staging was being used, and it was not
sufficient, because the index was not empty when staging began.

Two of these were found by an independent reviewer and one by following the
mechanism the reviewer exposed. None was visible in the commit message, which is
the definition of the defect class this file records.

The protocol is now: **`git reset` immediately after every `git apply --3way`,
then stage explicitly.** Verify with `git status` that the index contains only
what the message describes, before committing.

## Prevention

Three commits above weakened or exempted a guard while their messages described a
strengthening. All three messages were written in good faith by an author who did
not notice, which is why the countermeasure cannot be prose.
`GUARD-COVERAGE-REGRESSION-034` records the mechanical form: a guard-coverage
inventory with stable challenge and exemption identifiers — never line numbers,
since line-number identity is precisely what let the `periodic_renderer` exemption
rot — compared across versions, with an exact reduction requiring a tracked
declaration rather than a trusted commit title. The check's acceptance test is
that it rejects `3d6d1a22` and `1d2c43ad` and names what each one lost.

## Coverage of this audit

An independent reviewer enumerated all 213 commits in the branch's review range
and read messages and patch hunks in full for 11 of them, selected as high-risk.
This table is therefore a sample of the highest-risk commits, not a complete
audit of 213 diffs, and must not be cited as one.
