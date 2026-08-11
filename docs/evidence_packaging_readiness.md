# Evidence packaging readiness audit

| Item | Grade | Verbatim mechanism | Coverage | Falsifier |
| --- | --- | --- | --- | --- |
| Real-Windows procedures | PRESENT | `docs/new_lab_acceptance_checklist.md:492` "`preconditions: production OS and machine are identified`" and `docs/new_lab_acceptance_checklist.md:494` "`bound: 1 target-host acceptance run`"; `docs/new_lab_acceptance_checklist.md:502` "`target: 1 frozen build`"; `docs/new_lab_acceptance_checklist.md:511` "`target: 1 unattended launch path`"; `docs/deployment.md:373` "`CryoDAQ's supported lab platforms are Windows 10/11 and Linux`". | 3 of 3 platform readiness gates plus 1 OS-support line. | If any of G8.1, G8.2, G8.3 is removed or the platform line no longer declares Windows 10/11, this row is wrong. |
| Physical-lab procedures | PRESENT | `docs/new_lab_acceptance_checklist.md:238` "`result: PHYSICAL`" and `docs/new_lab_acceptance_checklist.md:490` "`result: PHYSICAL`". | 24 of 36 gate blocks are explicitly marked `result: PHYSICAL`. | If a listed physical gate lacks `result: PHYSICAL` or a non-physical gate is misclassified as `PHYSICAL`, this row is wrong. |
| Expected artifacts | PRESENT | `docs/new_lab_acceptance_checklist.md:200` "`evidence: interpreter and dependency record`" and `docs/new_lab_acceptance_checklist.md:209` "`evidence: version and policy record`". Every gate block has an `evidence:` line, and support-bundle shape is fixed to `"manifest.json"` and `"evidence.json"` (`src/cryodaq/support/bundle.py:671-674`). | 36 of 36 gate blocks include `evidence:` and support-bundle artifact paths are canonical. | If any required gate misses an `evidence:` field or support-bundle no longer permits only the canonical artifact pair, this row is wrong. |
| Pass/fail thresholds | PRESENT | `docs/new_lab_acceptance_checklist.md:197` "`bound: 1 runtime comparison`" and `docs/new_lab_acceptance_checklist.md:260` "`bound: 60 minutes observation`" and `docs/new_lab_acceptance_checklist.md:485` "`bound: 60 s restart and 60 s plus 2P gap`". | 36 of 36 gate blocks include `bound:` criteria that bound execution and pass/fail decisions. | If a gate has no `bound:` line, or if that bound is not actually measured during execution, this row is wrong. |
| Rollback / abort conditions | PRESENT | `docs/new_lab_acceptance_checklist.md:198` "`abort: runtime differs from production target`", `docs/new_lab_acceptance_checklist.md:207` "`abort: imported sqlite3 cannot be identified`", and `docs/new_lab_acceptance_checklist.md:216` "`abort: volume is the OS volume without approved margin`". | 36 of 36 gate blocks include an `abort:` line. | If any gate can fail safety checks without a named abort condition, this row is wrong. |
| Support-bundle capture | PARTIAL | `src/cryodaq/support/collector.py:69` "`def collect_bundle_capture(`" and `src/cryodaq/support/bundle.py:752` "`def build_support_bundle(capture: BundleCapture) -> SupportBundle:`". | 2 of 2 support-bundle mechanisms are present: capture assembly and deterministic bundle build; no checked operator runbook line was found for the one-shot trigger path. | If a one-shot operator command and post-capture mandatory check are added and verified in checked documentation, this row should become PRESENT. |

## Could not determine

- No one-shot operator command path for manual support-bundle capture was found in checked-in files. Search used: `rg -n "support bundle|support_bundle_capture|support-bundle|collect_bundle_capture|build_support_bundle|plan_bundle_write" src tests docs -g "*.py" -g "*.md"`.

## How this was verified

Every count in the Coverage column was re-derived by the coordinator before this file was committed,
not taken from the lane that wrote it:

| claim | re-derived |
|---|---|
| 36 gate blocks | `grep -cE '^G[0-9]+\.[0-9]+:'` = **36** |
| 36 of 36 `abort:` | `grep -cE '^\s+abort:'` = **36** |
| 36 of 36 `evidence:` | `grep -cE '^\s+evidence:'` = **36** |
| 36 of 36 `bound:` | `grep -cE '^\s+bound:'` = **36** |
| 24 of 36 `result: PHYSICAL` | `grep -cE '^\s+result: PHYSICAL'` = **24** |

Three cited line numbers were one low; the quoted text was verbatim-correct in every case and the
numbers are corrected above. An earlier round of this audit was REJECTED and is kept as evidence:
its citations all resolved to real files and real lines, and one of them still supported the
opposite conclusion. Checking that a citation resolves is not checking that it supports.
