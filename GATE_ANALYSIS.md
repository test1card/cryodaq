# GATE_ANALYSIS: Merge-base for trusted-base binding

## Finding
- `TRUSTED_BASE_SHA` is still event-dependent in current candidate-gate producer logic.
- In `main.yml`, `candidate_identity` uses PR base and merge-group base directly, uses `github.event.before` for normal `push`, and only uses merge-base for creation-push and workflow dispatch.
- `protected-ci-evidence-gate.yml` also computes `TRUSTED_BASE_SHA` from event fields inline (`github.event.pull_request.base.sha || github.event.merge_group.base.sha`) and uses that value as `--trusted-base` for candidate execution and protected proof.
- Co-versioning gate code reads the value as an absolute commit via `TRUSTED_BASE_SHA` in `tests/docs/test_docs_freshness.py` (`_strict_design_system_base`).

## Proposal (no behavior change in this lane)
Smallest gate-safe change to enforce merge-base anchoring:

1. Replace direct event-base selection for `TRUSTED_BASE_SHA` in the protected gate pipeline with a merge-base derivation step that is explicit per event type.
2. Pass a computed value equal to `git merge-base --all <candidate-sha> <target-tip>` (with singleton validation) into both `protected-run` and `protected-proof` as `--trusted-base`.
3. Keep the existing ancestor/self checks:
   - non-empty strict 40-hex commit,
   - `trusted_base != candidate`,
   - `git merge-base --is-ancestor trusted_base candidate`.
4. For merge-group and pull_request, this should resolve to the same base in ordinary cases, preserving strictness while removing event-source coupling.
5. This change should be made in `main.yml`/`protected-ci-evidence-gate.yml` candidate-identity path (or shared generator) rather than at each individual guard consumer.

## Event-type feasibility for merge-base
- `pull_request`: yes — both candidate SHA (`github.sha`) and PR base/merge target refs are available.
- `merge_group`: yes — `merge_group.base_sha` and candidate SHA are available.
- `push`: yes in `main.yml`-style bindings — `event.before`, branch ref, and fetched default branch allow merge-base; current logic already uses push-before (not merge-base) for non-creation pushes.
- `workflow_dispatch`: yes — current logic already uses merge-base fallback.