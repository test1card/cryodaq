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
