# Defect classes — the below-floor ledger

One line per confirmed mistake that sits **below** the severity floor in
`AGENTS.md#primary-ai-first-rule-mistake-to-enforcement`: a defect in a test, a
guard, a control, a harness, a CI workflow, a script, documentation, or the
prevention registry itself. Fixed where it lives, recorded here, blocking
nothing.

**Deliberately, no test reads this file.** No gate validates it, no schema
constrains it, nothing fails when it drifts. The moment a guard checks the
ledger, the ledger becomes the registry again, and the registry growing four
guard-escapes per real defect is what the floor exists to stop.

**The promotion rule.** A third instance of the same class is a signal: enforce
that class once, at the boundary where every instance becomes unreachable,
instead of adding a fourth line. Count before you add.

| date | class | what happened | fixed by |
|---|---|---|---|
| 2026-08-08 | guard-exercises-helper-not-production | Guards for the OC-030 migration drove `ChannelManager` rather than the seven production widgets; reverting a widget's selector left every guard green while a declared pressure channel was drawn as a temperature. **Second instance** — see PR #18, where the guard measured the writer only. **Promotion is PARTIAL, and saying otherwise was the second false claim this row has carried.** `tools/unguarded_production_files.py` landed in this slice and does the measurement: it reverts every production file a change touches, one at a time, and reports which leave the suite green. But a repo-wide search of this tree finds it named only here and in its own usage text — **no workflow, acceptance command or governing procedure requires it**, so nothing yet stops the next change from skipping it, which is exactly what a promotion is supposed to make impossible. Wiring it into a review boundary is deliberately NOT done in this PR: that would widen a gate amendment that is already waiting on ratification. **Until that wiring lands, treat this class as unpromoted.** The first false claim was worse — an earlier version said the promotion was "taken" while the script existed only in a scratch directory. Both were caught by review, not by me. | the production-site guards added in PR #19 (not yet on this branch, so the path is deliberately not cited: the dead-path guard is right to refuse it) |
| 2026-08-08 | guard-asserts-a-false-invariant | A closure guard claimed "no spelling-selection site exists anywhere under the GUI tree" while recognising one literal spelling; ten such sites existed. Re-derived from the AST sweep. | `tests/docs/test_docs_freshness.py` |
| 2026-08-08 | control-red-for-the-wrong-reason | A red-before control deleted two lines and left an empty `if` body, so the node went red on `IndentationError` rather than the property under test — and read as a working control. Replace a removed block with `pass`, and read WHY a control is red. | control scripts |
| 2026-08-08 | symbol-named-from-memory | Four migrated symbols cited in an open-cell row did not exist. Every name now costs one lookup before it is written. | `docs/OPEN_CELLS.md` |
