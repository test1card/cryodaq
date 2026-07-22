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
5. **Challenge:** a newly instantiated fresh-context reviewer inspects the
   frozen diff and evidence for unreachable assumptions, unsafe fallbacks,
   dual authority, and test weakness. The reviewer receives only the frozen
   scope, threat model, acceptance contract, and actual evidence needed for
   that gate; inherited campaign discussion does not count as independence.
6. **Adjudicate:** reproduce each finding locally. Accept, reject, or defer it
   with code-level evidence. The coordinator performs a separate mandatory
   review of the same frozen object. Any correction invalidates both affected
   review receipts; freeze the corrected object and repeat both reviews plus
   affected verification gates.
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

Never call a dirty, mandatory-review-rejected, or partially verified slice complete.

## 3. Delegation

Delegate only bounded work that can proceed independently. Briefs must contain:

- objective and non-goals;
- exact allowed files and dirty-work ownership;
- current code/commit scope;
- safety and compatibility invariants;
- acceptance tests and forbidden shortcuts;
- required report format.

Match delegated-agent context and capability to the task's risk, ambiguity,
and acceptance criteria. Keep author and reviewer separate. Instantiate the
gate reviewer without inherited campaign context and provide a bounded evidence
packet. The coordinator owns integration, performs a separate mandatory review,
and verifies all claims.

External-model review is additive and does not replace either the fresh-context
gate reviewer or the coordinator's mandatory review. Use scarce high-context
models for genuinely difficult architecture, safety, concurrency, or whole-
construction passes rather than routine gate approval. Quota exhaustion or
provider unavailability never blocks PR publication unless the current user
explicitly makes that provider a gate. When used, transmit only the approved
scope, freeze/hash the reviewed files, request severity-ranked actionable
findings, and persist a complete auditable verdict before assigning any
coverage. Never send secrets or credentials. Send untracked private material
only with explicit current authorization.

### 3.1 Role-separated reviewer/implementation campaigns

When the current task separates reviewer and implementation authority, use the
reviewer-owned campaign contract and one machine-readable lease map. The
reviewer owns governance, tickets, dispositions, integration, and publication;
the implementation role owns only exact leased code/test/config/build paths.
Neither role patches the other role's surface.

The first implementation turn is read-only orientation. It reports canonical
root, branch, HEAD/tree, complete dirty paths, governing-document hashes,
current ticket/disposition, and active reserved paths, then waits. Authoring
begins only after a new exact ticket binds the slice, normalized path list,
input blobs/modes, invariants, tests, and stop conditions. Directories, globs,
"likely files", old handoffs, roadmap prose, and review findings are not file
leases.

Shared-worktree implementers never touch Git state. An explicitly isolated
worker may create local review-object commits only when its ticket grants that
narrow permission; it may not integrate or publish. Before importing an
isolated lane, reconcile its progress ledger to live Git, require an exact
`DONE_FOR_REVIEW` manifest, review only the committed base..tip objects in a
clean detached worktree, and separate any worker-authored governing-document
hunks as untrusted proposals. Never stage or merge its seeded dirty tree.

Each confirmed agent mistake creates a governance incident disposition. The
reviewer records the failure mode/invariant and owns the rule change; the
implementation role receives a separate ticket for a deterministic regression
or governance guard when automation is possible. Preserve red-before-fix and
green-after-fix evidence. Prose-only prevention remains open debt; a genuinely
manual gate must name exact inputs, decision owner, evidence, and fail-closed
outcome. See `docs/adr/003-governance-as-enforcement.md`.

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

Every independently reviewable engineering slice requires two separately
attributable review receipts before it is called reviewed/complete or published
as a reviewed checkpoint:

1. a receipt from a newly instantiated fresh-context gate reviewer, bound to the exact
   frozen object and review packet; and
2. a separate receipt from the coordinator's own line/object and
   semantic review of that same object.

Changing content, path, type, mode, test evidence, or a covered acceptance
contract invalidates the affected receipts. Correct, refreeze, and repeat both
reviews. External-model verdicts remain separately labelled additive evidence;
they cannot silently satisfy either mandatory receipt.

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
Open findings and honest physical/target-OS/packaging/laboratory gates:
Exact next safe command:
Publication authority:
Historical documents consulted (non-authoritative):
```

Do not embed evergreen policy or hard-code a future model in a handoff. When a
campaign closes, freeze its ledger and prompts as dated evidence so a later
session cannot mistake them for current instructions.
