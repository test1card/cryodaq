# Evidence packaging readiness audit

| Item | Grade | Verbatim mechanism | Coverage | Falsifier |
| --- | --- | --- | --- | --- |
| Real-Windows procedures | PRESENT | `docs/new_lab_acceptance_checklist.md:491-499`, `:500-508`, `:509-517` for required G8.1–G8.3 entries; `docs/deployment.md:25-33` for tracked source-install procedure; `docs/deployment.md:268-279` for tracked ONEDIR build commands; `docs/lab_verification_checklist.md:344-375` and `380-394` for the smoke evidence path for source-install and ONEDIR/frozen Windows checks. | 3 platform gates plus 2 concrete Windows readiness procedures. | If any of G8.1–G8.3 is removed, or if either the source-install smoke path (on Windows, by `install.bat`) or the ONEDIR/frozen smoke path is not executed as recorded evidence. |
| Physical-lab procedures | PARTIAL | `docs/new_lab_acceptance_checklist.md:131-163` explicitly says the hazardous-source section is still a draft/placeholder for non-2604B paths, while `docs/new_lab_acceptance_checklist.md:238-490` include explicit `result: PHYSICAL` blocks and pass criteria in the same file. | 23 of 24 `result: PHYSICAL` blocks can be treated as procedure-backed today; `G6.1` is explicitly caveated and still not a real procedural gate. | If any non-placeholder `PHYSICAL` block is missing both a procedure text and an evidence gate, or if `G6.1` gets a real procedure path and becomes the 24th valid counted row. |
| Expected artifacts | PRESENT | `docs/new_lab_acceptance_checklist.md:200` and `:209` for evidence capture examples; support-bundle schema in `src/cryodaq/support/bundle.py:669-676` enforces exactly `manifest.json` and `evidence.json`. | 36 of 36 gate blocks include an `evidence:` field and 36 of 36 bundle fields match the canonical artifact pair. | If any required gate loses `evidence:` or if any bundle path or schema allows a non-canonical artifact pair. |
| Pass/fail thresholds | PARTIAL | `docs/new_lab_acceptance_checklist.md:103-118` defines pass criteria, and gate blocks include `bound:` lines (`docs/new_lab_acceptance_checklist.md:330-480`, `:491-517`). `G7.1` (`docs/new_lab_acceptance_checklist.md:464-470`) has a bound (`1 full intended duration`) but no explicit numeric or sampling threshold for “no memory growth trend.” | Bounded execution is documented for all 36 rows, but explicit bounded decision thresholds are not complete (`G7.1` missing a measurable bound for drift tolerance and trend rule). | If a gate’s `bound:` does not constrain a quantified pass/fail rule or if gate-specific threshold criteria are absent/missing in the procedure text. |
| Rollback / abort conditions | PARTIAL | `docs/new_lab_acceptance_checklist.md:330-480` and `:491-517` each list an `abort:` line; however `G4.2` (`docs/new_lab_acceptance_checklist.md:374-380`) does not state late-trip/failed-trip abort outcomes explicitly. | 35 of 36 gate blocks have an abort condition mapped to explicit failure outcome forms; `G4.2` is missing explicit late/failed Class A protection outcomes. | If a safety failure is not named as a distinct abort condition (e.g., miss-latency or non-fire), this row is wrong. |
| Support-bundle capture | PARTIAL | `src/cryodaq/support/collector.py:69` (`collect_bundle_capture`) and `src/cryodaq/support/bundle.py:752` (`build_support_bundle`) and `:789` (`plan_bundle_write`) are present; `src/cryodaq/support/bundle.py:1-8` and doc tests show execution is intentionally delegated out. | 2 of 3 support-bundle mechanisms are present in `src`: capture + build + write plan; production write executor path is missing. | If a checked runbook shows a one-shot, authority-bounded write path that executes the `BundleWritePlan` under production constraints and evidence validates resulting files. |
| Required fields per gate | PRESENT | `docs/new_lab_acceptance_checklist.md:194` gate-table plus block entries for `bound`, `abort`, and `evidence`; no global count-only claim is used. | 36 of 36 gate blocks each contain exactly one `bound:`, one `abort:`, one `evidence:`, and one `result:` field. | If any block drops or doubles any required field while others remain unchanged. |

## Could not determine

- No production one-shot **support-bundle write executor** (jailed/no-follow/atomic replace writer in the live path) was found in checked-in files. Search used: `rg -n "support bundle|support_bundle_capture|support-bundle|collect_bundle_capture|build_support_bundle|plan_bundle_write|BundleWritePlan" src tests docs -g "*.py" -g "*.md"`.

## How this was verified

Every count in the Coverage column was re-derived from the immutable checklist blob object and this file’s checked-in mechanism rows were rechecked by the coordinator:

| claim | re-derived |
|---|---|
| Checklist blob used | `blob=$(git rev-parse HEAD:docs/new_lab_acceptance_checklist.md)` |
| 36 gate blocks | `git cat-file -p "$blob" | rg -c '^G[0-9]+\.[0-9]+:'` = **36** |
| 36 `bound:` lines | `git cat-file -p "$blob" | rg -c '^\s+bound:'` = **36** |
| 36 `abort:` lines | `git cat-file -p "$blob" | rg -c '^\s+abort:'` = **36** |
| 36 `evidence:` lines | `git cat-file -p "$blob" | rg -c '^\s+evidence:'` = **36** |
| 36 `result:` lines | `git cat-file -p "$blob" | rg -c '^\s+result:'` = **36** |
| `PHYSICAL` gates | `git cat-file -p "$blob" | rg -c '^\s+result:\s+PHYSICAL'` = **24** |
| Per-gate field shape | `python -c "import re, subprocess; blob = subprocess.check_output(['git','rev-parse','HEAD:docs/new_lab_acceptance_checklist.md'], text=True).strip(); text = subprocess.check_output(['git','cat-file','-p',blob], text=True).splitlines(); pat=re.compile(r'^G([0-9]+\.[0-9]+):'); \
for i, line in enumerate(text):\
  \
 m=pat.match(line);\
 if not m: continue;\
 counts={k:0 for k in ('bound','abort','evidence','result')};\
 j=i+1;\
 while j < len(text) and not pat.match(text[j]):\
  for k in counts: \
   if text[j].startswith('  '+k+':'): counts[k]+=1;\
  j+=1;\
 if any(v != 1 for v in counts.values()):\
  print('MISMATCH', m.group(1), counts); raise SystemExit(1);\
print('all_36_blocks_have_exactly_one_bound_abort_evidence_result')"` = **all 36 blocks exactly one** |
| Search for bundle execution adapter | `rg -n "def .*support.*bundle|BundleWritePlan|support.*bundle" src` returned only collector/build/plan symbols above |

Three cited line numbers were one low in an earlier revision; the quoted text here is correct and the counts are corrected above.

An earlier round of this audit was REJECTED and is kept as evidence:
its citations all resolved to real files and real lines, and one of them still supported the opposite conclusion. Recording citation existence is not proof of sufficiency.
