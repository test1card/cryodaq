# Stream C synthesis — day-and-done repo health fixes

## Consulted

| model (actual) | response file | one-line summary |
|---|---|---|
| Codex gpt-5.5 / high | `RESPONSES/codex-04-alarm-v2-threshold.response.md` | Root cause: `threshold_expr:` in YAML is not implemented; only `threshold:` works. Fix is a YAML edit, not a code change. Patch + regression test provided. |
| Codex gpt-5.5 / high | `RESPONSES/codex-05-thyracont-probe.response.md` | TIGHTEN preferred: add checksum validation to V1 probe when `validate_checksum=True`. Preserves `validate_checksum=false` escape hatch. Patch + regression test provided. |
| Gemini 2.5-pro | `RESPONSES/gemini-03-doc-reality.response.md` | 1 CRITICAL + 2 HIGH + 4 MEDIUM doc drifts. Critical: `pyproject.toml=0.13.0` vs README `v0.33.0`. CC **verified** — confirmed true on disk. |
| Gemini 2.5-pro | `RESPONSES/gemini-05-coverage-gaps.response.md` | 4 untested safety-critical paths + 10 priority-ordered missing tests + 5 anti-pattern tests (fragile-string assertions). |

## Points of agreement

- **alarm_v2 and Thyracont patches are clean and ready to apply** — both Codex briefs returned full diffs + regression tests, no further analysis needed.
- **Doc-drift is real and measurable** — Gemini-03's version-mismatch claim verified directly by CC (`pyproject.toml` line shows `0.13.0`, README line 3 says `v0.33.0`, file counts 145 / 192 match claims).
- **Test coverage has concrete, targeted gaps** — Gemini-05's top 4 safety-critical gaps all name specific file:line sites in `safety_manager.py` + `interlock.py`.

## Points of disagreement

None across the four consultants — each answered a different non-overlapping question.

## CC decision

### 1. Apply alarm_v2 patch (Codex-04)

**YAML edit only.** Change in `config/alarms_v3.yaml` under `cooldown_stall`'s composite condition list:

```diff
-          threshold_expr: "T12_setpoint + 50"
+          threshold: 150  # threshold_expr not implemented; static threshold (~100K setpoint + 50K)
```

Add regression test `test_cooldown_stall_config_evaluates_without_threshold_keyerror` in `tests/core/test_alarm_v2.py` (test body provided in Codex-04 response).

Scope: ≤ 1 YAML line + ≤ 30 test lines. Safe.

### 2. Apply Thyracont patch (Codex-05)

**TIGHTEN** the V1 probe in `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` (~lines 163-170):

- When `self._validate_checksum` is True AND response matches prefix, also verify checksum via `self._verify_v1_checksum()`. If checksum fails, WARN log + retry next attempt instead of accepting the prefix.
- `validate_checksum=False` config escape remains unchanged — known non-VSP63D hardware still supported.

Add `test_v1_probe_rejects_checksum_mismatch` in thyracont test file (provided in Codex-05 response).

Scope: ~9 diff lines + 1 async test. Safe.

### 3. Apply doc-drift fixes (Gemini-03 top items, CC-filtered)

| # | priority | action |
|---|---|---|
| 1 | CRITICAL | Resolve `pyproject.toml` 0.13.0 vs README/CHANGELOG 0.33.0. **Architect decides intended version.** CC cannot pick unilaterally — this is a release-policy call. |
| 2 | HIGH | Update `README.md` line 3 to match resolved version |
| 3 | HIGH | Update `PROJECT_STATUS.md` file counts: 145 src, 192 tests (verified) |
| 4 | MEDIUM | Add `experiment_card.py`, `utils/` module path, `overview_panel.py`, `vacuum_trend_panel.py` to CLAUDE.md module index |
| 5 | MEDIUM | Correct design-system stats in CLAUDE.md: v1.0.1, 67 files, 141 tokens (from `docs/design-system/MANIFEST.md`) |

Items 2-5 are mechanical — CC can execute once architect picks version for item 1.

### 4. Plan for coverage gaps (Gemini-05 top 4 safety tests)

These are **queued work**, not this-session work. Backlog order:

1. `test_safety_stuck_in_run_permitted_causes_fault` (safety-critical, highest priority)
2. `test_interlock_stop_source_failure_escalates_to_fault` (safety-critical)
3. `test_stale_data_does_not_fault_in_non_running_states` (safety-critical, guards against regression)
4. `test_safety_manager_partial_stop_remains_running` (safety-critical)

Each is ~30-50 test lines. Can be batched as "safety test hardening" on one branch in a future session.

Anti-pattern tests flagged by Gemini-05 (exact-string assertions on Russian UI text, specific token-redaction format, timestamp format, mock call counts) — **defer**. They pass today and would only need rewriting if they break a refactor. Note in the `tests/` README for future maintainer.

## Recommended commit grouping

If architect approves, CC implements in this order (each on a separate branch per §5):

1. **`feat/alarm-v2-cooldown-stall-fix`** — YAML change + test. 1 day-and-done.
2. **`feat/thyracont-probe-checksum`** — driver patch + test. 1 day-and-done.
3. **`docs/version-and-module-index-reconcile`** — after architect resolves 0.13.0 vs 0.33.0 ambiguity. 1 session.
4. **`feat/safety-fsm-test-hardening`** — 4 new safety tests from Gemini-05. Batched, 1 session.

None of these are B1-blocking. They can run in parallel with / ahead of the Stream B split-context experiment.

## Rationale

- Both Codex patches are small, focused, ready to commit. Skill §4.2 slop-check: not slop — both have file:line refs, full diffs, and specific test cases.
- Gemini-03's critical doc-drift finding was verified on disk (0.13.0 vs 0.33.0), so the signal is real, not hallucinated.
- Coverage gaps are gaps, not urgent bugs — defer to a test-hardening session.

## Residual risks

1. **Version mismatch is architect-domain.** CC cannot decide 0.13.0 vs 0.33.0. Pre-answered options for architect:
   - (a) Bump `pyproject.toml` to match reality (`0.33.0` or beyond)
   - (b) Roll back `README.md` / `CHANGELOG.md` / `PROJECT_STATUS.md` to `0.13.0` (unlikely; 0.33.0 is the claimed shipped state)
   - Almost certainly (a) — but architect confirms.
2. **YAML `threshold: 150` value is a best-guess** for T12 cooldown stall. Codex-04 notes "~100K setpoint + 50K". Architect should confirm if 150 is right for the lab cryostat workflow before commit.
3. **Thyracont patch may break `validate_checksum=True` operation on a VSP63D firmware variant with non-standard probe checksums** — Codex-05 did not find evidence this exists, but noted escape hatch. Retest on real hardware before tagging v0.34.0.
4. Gemini-05 noted anti-pattern tests will break on refactor. They pass today, but a test-refactor pass is a follow-up session.

## Archived to

This synthesis + Codex-04 and Codex-05 response files (patches + tests extracted).
