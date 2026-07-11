# CryoDAQ orchestration playbook

This document expands the canonical rules in [`../AGENTS.md`](../AGENTS.md).
It is tool-neutral and contains no permanent model, provider, branch, or commit
routing. Explicit task instructions select those transient details.

## 1. Authority and context

Resolve instructions in this order: host system policy, explicit current user
request, root `AGENTS.md`, nested `AGENTS.md` files for stricter additive
subtree detail, this playbook for elaboration, then task-selected
specifications. Evidence/history never promotes itself. A nested file cannot
weaken root safety, hardware, publication, evidence, or user-work rules; the
root wins any such conflict. Machine-local/user-global convenience config,
hooks, plugins, and injected memory rank below the root for those boundaries.
For all other repository-contract conflicts the root also wins; local guidance
may fill only choices the root leaves unspecified. This playbook cannot
override `AGENTS.md`.

Before acting, inspect `git status --short`, branch/HEAD, relevant diffs, source,
tests, and current tracked docs. Classify every discovered document as one of:

- **policy**: `AGENTS.md` and this playbook;
- **product truth**: roadmap, status, architecture, design system, operator and
  lab documents;
- **task specification**: explicitly selected memo, issue, or campaign plan;
- **evidence/history**: handoffs, scratchpads, generated memory, audits, model
  responses, artifacts, worktrees, and archived prompts;
- **product-agent runtime**: `config/agent.yaml` and prompt modules.

Imperative wording does not promote evidence/history into policy.

## 2. Slice lifecycle

For each independently reviewable slice:

1. **Recon:** establish live behavior, ownership boundaries, dirty files, and
   exact acceptance criteria.
2. **Design:** define authority, failure semantics, cancellation, persistence,
   compatibility, and operator-visible behavior before editing.
3. **Author:** limit file ownership; preserve unrelated work; add tests with the
   implementation.
4. **Verify:** run focused tests and repeat race-prone boundaries. Then run the
   relevant subsystem, integration, static, packaging, and full-suite gates.
5. **Challenge:** an independent reviewer inspects the frozen diff and evidence
   for unreachable assumptions, unsafe fallbacks, dual authority, and test
   weakness.
6. **Adjudicate:** reproduce each finding locally. Accept, reject, or defer it
   with code-level evidence; rerun affected gates after any change.
7. **Integrate:** when the current task authorizes staging/committing, stage
   only the slice, inspect the staged diff, and commit. Publish only under
   separate current authority.
8. **Clean-SHA proof:** for high-risk slices, verify the committed tree from an
   isolated checkout/worktree with that checkout's `src` first on `PYTHONPATH`.
   Before any loopback/process/full-suite gate, prove the test environment is
   isolated from live acquisition: no production engine/GUI is using the same
   ports or writable roots, and no real instrument endpoint is reachable from
   the test configuration. Never stop or disturb a live run merely to obtain a
   software gate; move the gate to an isolated host/configuration instead.

Never call a dirty, externally rejected, or partially verified slice complete.

## 3. Delegation

Delegate only bounded work that can proceed independently. Briefs must contain:

- objective and non-goals;
- exact allowed files and dirty-work ownership;
- current code/commit scope;
- safety and compatibility invariants;
- acceptance tests and forbidden shortcuts;
- required report format.

Use faster worker agents for precise reconnaissance, mechanical authoring, and
test construction. Use stronger reviewer agents for architecture, safety,
concurrency, adversarial review, and ambiguous adjudication. Keep author and
reviewer separate. The coordinator owns integration and verifies all claims.

External model review is optional unless the current task requires it. When
used, transmit only the approved scope, freeze/hash the reviewed files, request
severity-ranked actionable findings, and save an auditable verdict. Never send
  secrets or credentials. Send untracked private material only with explicit
  current authorization.

## 4. Review contract

A reviewer receives the intended invariant, frozen diff/files, relevant tests,
and actual gate output. The review must trace reachable behavior rather than
list generic concerns. Classify findings:

- **P0:** unsafe/catastrophic behavior or data loss reachable in intended use;
- **P1:** serious correctness, authority, lifecycle, or compatibility defect;
- **P2:** bounded defect worth fixing before the slice closes;
- **P3:** optional improvement or documentation polish.

For every P0-P2, include file/line, trigger, impact, and smallest defensible
repair. A PASS means no unresolved reachable P0-P2 in the reviewed scope; it
does not close hardware, OS, soak, or operator-acceptance gates that were not
run.

## 5. Evidence matrix

Choose evidence by risk:

| Change | Minimum evidence |
|---|---|
| Pure docs | links/anchors, guidance contradiction scan, doc tests |
| Pure logic | focused unit tests, static checks |
| Persistence/replay | failure injection, round trip, legacy compatibility |
| Async/process/election | real tasks/processes, cancellation, crash/restart, repetitions |
| GUI/UX | model/view tests, scripted operator states, design-system, accessibility and performance-budget checks, visual QA |
| Packaging | frozen/installed artifact on the target OS, not source-only import |
| Safety/hardware | simulation plus the separately authorized physical protocol; simulation never closes the physical gate |

Record exact commands and counts. Explain skips, warnings, flakes, and
environment limits. A failure seen once remains open until fixed or reproduced
and defensibly adjudicated.

## 6. Git and publication

- Preserve the worktree and inspect path-level diffs before staging.
- One commit should express one reviewed idea; do not mix incidental cleanup.
- Never use destructive reset/checkout/clean operations on user work.
- Commit messages describe the invariant and evidence, not the agent/model.
- Pushing a feature branch does not authorize tagging, release, merge, PR, or
  rewriting history. Each requires its own current authority.
- `RELEASE_CHECKLIST.md` applies only when an actual release is authorized.

## 7. GUI and product design

Operator interfaces answer: can the run proceed, what is happening, what needs
attention, is the system degrading, and what action is safe next? Build
canonical immutable view-models rather than letting panels independently poll
and reinterpret backend state.

Every UI slice identifies the applicable `docs/design-system/` rules and ships
any necessary design-system amendment with the implementation. Test truth
states (`ok`, `caution`, `warning`, `fault`, `stale`, `disconnected`) with text
or icon/position in addition to color. Fleet views must aggregate and
virtualize rather than rendering unbounded device/channel widgets.

## 8. Product assistant boundary

The shipped LLM insight/query assistant may issue only exact allowlisted
read-only engine queries and produce text for configured operator channels. It
may not send mutating/control commands, hold write credentials, control
sources, acknowledge safety state, or trigger automatic remediation. The
allowlist is enforced before socket creation and covered by behavioral tests.

Periodic PNG reporting is a separate observational artifact-delivery
subsystem. It may collect revisioned read-only snapshots and deliver generated
reports, but it has no engine mutation, safety, source, or remediation
authority. These constraints belong in code and tests as well as documentation.

Product prompt/config changes are runtime changes: review prompt injection,
privacy, auditability, deterministic fallbacks, token/latency budgets, Russian
operator language, and behavior tests. Do not apply developer-agent routing
rules to the product assistant or vice versa.

## 9. Audit evidence

Audit records for product-assistant calls use the schema implemented by
`src/cryodaq/agents/assistant/shared/audit.py`: trigger, assembled context,
prompt/model metadata, response, token/latency data, dispatched outputs, and
errors. Retention is governed by product configuration and housekeeping.

Developer review evidence should identify source commit/file hashes, reviewer
scope, findings, local adjudication, and final verdict. Raw external transcripts
belong in ignored campaign evidence unless publication is explicitly desired.

## 10. Handoffs and resumability

Use one current campaign ledger, not competing “single sources of truth.” A
handoff must contain:

```text
Objective:
Branch and reviewed HEAD:
Committed/published slices:
Dirty files and owner:
Frozen hashes or diff scope:
Evidence completed:
Open findings and honest external/physical gates:
Exact next safe command:
Publication authority:
Historical documents consulted (non-authoritative):
```

Do not embed evergreen policy or hard-code a future model in a handoff. When a
campaign closes, freeze its ledger and prompts as dated evidence so a later
session cannot mistake them for current instructions.
