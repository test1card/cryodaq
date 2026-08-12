# Evidence packaging readiness audit

| Item | Grade | Verbatim mechanism | Coverage | Falsifier |
| --- | --- | --- | --- | --- |
| Real-Windows procedures | PRESENT | docs/new_lab_acceptance_checklist.md:491-499, :500-508, :509-517 for required G8.1–G8.3 entries; docs/deployment.md:25-33 for tracked source-install procedure; docs/deployment.md:425-434 for the PyInstaller ONEDIR build procedure; docs/lab_verification_checklist.md:344-375 and 380-394 for the source-install and ONEDIR/frozen Windows smoke procedures. | 3 platform gates plus 2 concrete Windows readiness procedures. | If any of G8.1–G8.3 is removed, or if either the source-install smoke path (on Windows, by install.bat) or the ONEDIR/frozen smoke path is not executed as recorded evidence. |
| Physical-lab procedures | PARTIAL | docs/new_lab_acceptance_checklist.md:131-163 explicitly says the hazardous-source section is still a draft/placeholder for non-2604B paths; its result: PHYSICAL blocks and pass criteria are procedure shapes in the generic template. The stand-specific procedure source is docs/lab_verification_checklist.md, whose named sections are not the template’s 36 Gx.y blocks. | The template-derived 23-of-24 count is not a stand-ready coverage count. The stand checklist establishes named laboratory procedures, but this audit does not re-derive a per-gate physical readiness total for it. | If the stand checklist is independently assessed gate-by-gate and produces a documented count, or if any claimed template procedure shape lacks both procedure text and an evidence gate. |
| Expected artifacts | PRESENT | docs/new_lab_acceptance_checklist.md:200 and :209 for evidence capture examples; support-bundle schema in src/cryodaq/support/bundle.py:669-676 enforces exactly manifest.json and evidence.json. | 36 of 36 gate evidence fields are present; separately, 2 of 2 canonical support-bundle artifacts are enforced (manifest.json and evidence.json). | If any required gate loses evidence: or if any bundle path or schema allows a non-canonical artifact pair. |
| Pass/fail thresholds | PARTIAL | docs/new_lab_acceptance_checklist.md:103-118 defines pass criteria, and gate blocks include bound: lines (docs/new_lab_acceptance_checklist.md:330-480, :491-517). G3.1 still says reference uncertainty must be “small compared with” the alarm band without an allowed ratio or magnitude. G7.1 (docs/new_lab_acceptance_checklist.md:464-470) has a bound (1 full intended duration) but no explicit numeric or sampling threshold for “no memory growth trend.” | Bounded execution is documented for all 36 template rows, but at least G3.1 and G7.1 lack measurable decision thresholds; the row cannot be upgraded on the G7.1 example alone. | If a gate’s bound: does not constrain a quantified pass/fail rule or if gate-specific threshold criteria are absent/missing in the procedure text. |
| Rollback / abort conditions | PARTIAL | docs/new_lab_acceptance_checklist.md:330-480 and :491-517 each list an abort: line; G4.2 (:374-380) does not state late-trip/failed-trip abort outcomes explicitly, and G4.4 requires alarm strictly before interlock but does not name an abort outcome for equality/concurrent or indistinguishable firing. | The prior 35-of-36 count is not supportable: G4.2 and G4.4 are named abort-coverage gaps. | If a safety failure is not named as a distinct abort condition, including miss-latency, non-fire, or simultaneous/indistinguishable alarm and interlock firing, this row is wrong. |
| Support-bundle capture | PARTIAL | src/cryodaq/support/collector.py:69 (collect_bundle_capture), src/cryodaq/support/bundle.py:752 (build_support_bundle), and :789 (plan_bundle_write) are present; the production write executor is absent from the checked-in live path. | 3 of 4 stages are present: capture, build, and write-plan creation. The fourth stage, production execution of the write plan, is missing; a write plan is not counted as delivery. | If a checked runbook shows a one-shot, authority-bounded write path that executes the BundleWritePlan under production constraints and evidence validates resulting files. |
| Required fields per gate | PRESENT | docs/new_lab_acceptance_checklist.md:194 gate-table plus block entries for bound, abort, and evidence; no global count-only claim is used. | 36 of 36 template gate blocks each contain exactly one bound:, one abort:, one evidence:, and one result: field. | If any block drops or doubles any required field while others remain unchanged. |

## Could not determine

- No production one-shot support-bundle write executor (jailed/no-follow/atomic replace writer in the live path) was found in checked-in files. Search used: rg -n "support bundle|support_bundle_capture|support-bundle|collect_bundle_capture|build_support_bundle|plan_bundle_write|BundleWritePlan" src tests docs -g "*.py" -g "*.md".

## How this was verified

Every template count in the Coverage column was re-derived from the immutable checklist blob recorded below; the stand-specific procedure statement was checked against docs/lab_verification_checklist.md; and the mechanism rows were rechecked by the coordinator:

| claim | re-derived |
|---|---|
| Checklist blob used | docs/new_lab_acceptance_checklist.md at HEAD = c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 |
| 36 gate blocks | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^G[0-9]+\.[0-9]+:' = 36 |
| 36 bound: lines | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^\s+bound:' = 36 |
| 36 abort: lines | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^\s+abort:' = 36 |
| 36 evidence: lines | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^\s+evidence:' = 36 |
| 36 result: lines | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^\s+result:' = 36 |
| PHYSICAL gates | git cat-file -p c6dc3aeb7523fa7c5e8478752573e5d2c44348a5 | rg -c '^\s+result:\s+PHYSICAL' = 24; this remains a template count, not a stand count |
| Per-gate field shape | The executable heredoc below checks every template block. |
| Search for bundle execution adapter | rg -n "def .*support.*bundle|BundleWritePlan|support.*bundle" src returned only collector/build/plan symbols above; no production executor was found. |

```bash
python - <<'PY'
import re, subprocess
blob = 'c6dc3aeb7523fa7c5e8478752573e5d2c44348a5'
text = subprocess.check_output(['git', 'cat-file', '-p', blob], text=True).splitlines()
pat = re.compile(r'^G([0-9]+\.[0-9]+):')
for i, line in enumerate(text):
    match = pat.match(line)
    if not match:
        continue
    counts = {key: 0 for key in ('bound', 'abort', 'evidence', 'result')}
    j = i + 1
    while j < len(text) and not pat.match(text[j]):
        for key in counts:
            if text[j].startswith('  ' + key + ':'):
                counts[key] += 1
        j += 1
    if any(value != 1 for value in counts.values()):
        print('MISMATCH', match.group(1), counts)
        raise SystemExit(1)
print('all_36_blocks_have_exactly_one_bound_abort_evidence_result')
PY
```

The immutable template object has 36 gate blocks, 36 each of bound:, abort:, evidence:, and result:, and 24 PHYSICAL blocks. These are template-derived counts, not claims that the stand checklist has the same block structure.

Three cited line numbers were one low in an earlier revision; the ONEDIR citation and all counts are corrected above.

An earlier round of this audit was REJECTED and is kept as evidence: its citations all resolved to real files and real lines, and one of them still supported the opposite conclusion. Recording citation existence is not proof of sufficiency.
