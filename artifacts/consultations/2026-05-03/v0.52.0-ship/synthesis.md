# v0.52.0 F-P audit synthesis — iter 1

Date: 2026-05-03
Commit audited: 160f4ac (after amend)
Verifiers: Codex gpt-5.5 + Gemini 0.38.2

---

## Codex findings

2 findings, both P2 (user-visible stale-overlay bugs in degradation path):

**C1 [P2] — VacuumPredictionWidget: stale vacuum forecast on no-data reply**
File: analytics_widgets.py:473-474
When no-data/ok-false arrives after a valid forecast was shown, the old code
returned without clearing the inner PredictionWidget curves. Stale projection
remained visible after bridge restart or predictor disable.
Fix: call `self._inner.set_prediction([], [], [], ci_level_pct=68.0)` on
no-data/error paths. Tests updated to reflect clearing behavior.
Status: FIXED in amend (160f4ac).

**C2 [P2] — RThermalLiveWidget: stale R∞ overlay on empty-history push**
File: analytics_widgets.py:645
When non-None RThermalData arrives with empty history, the `if history:` block
was skipped, leaving a previously-converged asymptote overlay visible with no
supporting data.
Fix: add `else` clause to hide asym_line + asym_band when history is empty.
New test `test_empty_history_hides_stale_overlay` added.
Status: FIXED in amend (160f4ac).

---

## Gemini findings

**PASS — no findings.** 8 explicit confirmations:
- GUI isolation (P0): confirmed clean
- Graceful degradation (P0): confirmed
- Phase-aware visibility (P1): confirmed
- Physics reuse (P1): confirmed
- Visual consistency (P2): confirmed (STATUS_INFO, PLOT_LINE_WIDTH, DashLine, alpha=64)
- Time normalization (P1): t0 = now - extrap_t[0] confirmed correct
- Predictor optimization (P2): duplicate-prevention confirmed
- Test coverage: 18 tests confirmed adequate

Gemini conclusion: "Commit is safe to merge. No regressions or drive-by refactors found."

---

## Cross-check

Both verifiers agree:
- GUI scope confined ✓
- Graceful degradation ✓ (Codex found 2 gaps; Gemini missed them — complementary)
- Visual design system ✓
- Physics reuse ✓

No disagreements between verifiers.

---

## Synthesis decision

All findings resolved. 21 tests pass. No unresolved issues.

PROCEED to Phase 4 (version bump, CHANGELOG, tag, merge).

Residual risks: None.
Stuck findings: None.
