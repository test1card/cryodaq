# Montana implementation-agent contract

**Status:** active reviewer-owned execution contract for the Montana completion
campaign.

**Scope:** campaign-local. Its canonical worktrees, branches, lane separation,
integration order, proposal sequence, and completion mechanics apply only to the
Montana completion campaign and expire when that campaign receives its final
reviewed disposition. They are not the repository's ordinary day-to-day Git or
review workflow. Universal rules remain in `AGENTS.md`; durable product
invariants remain after this campaign through their production guards.

**Primary objective:** complete every open Montana engineering, evidence,
review, and publication gate in `ROADMAP.md`, without weakening CryoDAQ's
fail-closed, verified-OFF, persistence-first, provenance, or operator-truth
contracts.

This document is deliberately explicit enough for a competent mid-tier coding
agent. The implementation agent applies these instructions; it must not infer
the architecture, redefine completion, or substitute its own risk judgment for
the roadmap and reviewer.

## 1. Authority and role split

The current user appointed two unequal, complementary roles:

| Role | Owns | Must not do |
|---|---|---|
| Implementation agent | Product code, configuration, build scripts, focused verification, and implementation evidence within its reviewer-assigned worktree lane | Edit tests or CI during the active reviewer-guard-author tranche; edit governing documents; push, open a PR, certify its own work, operate hardware, or leave its assigned lane |
| Reviewer/coordinator | `AGENTS.md`, `ROADMAP.md`, status/architecture/operator/design-system/governance documents, this contract, tests and directly required CI guard wiring during the active reviewer-guard-author tranche, review findings/dispositions, Git integration/publication, and final acceptance | Edit product code, configuration, or build scripts; self-certify reviewer-authored guards |

The implementation agent may read every repository file. A direct current
user/reviewer mandate may establish a standing autonomous lane by naming the
canonical worktree, branch, objective, and allowed implementation surfaces.
Within that lane it may discover and edit directly required paths under
`src/`, `config/`, `scripts/`, `build_scripts/`, `tools/`, or packaging
metadata without per-slice tokens, exact input-blob lists, or
lease-file handshakes. It records pre-edit blobs in ignored evidence and never
stages that evidence. Orientation itself is zero-write. It may not edit any of
these reviewer-owned surfaces:

- `AGENTS.md`, `ROADMAP.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`,
  `RELEASE_CHECKLIST.md`, `README.md`, or `README.ru.md`;
- `docs/**`, including architecture, protocol, operator, deployment,
  laboratory, design-system, ADR, and report files;
- this implementation contract or reviewer disposition ledgers;
- `tests/**` and `.github/**` for the duration of the active
  reviewer-guard-author tranche;
- Git history, index, branches, tags, remotes, releases, or pull requests.

When code makes a governing document stale, the implementation agent records
the exact required delta in
`scratchpad/montana/exec/implementation_agent_doc_requests.md`. It does not
apply the delta. The reviewer adjudicates and authors it after reviewing the
code.

The reviewer never repairs code directly. Every code correction is returned to
the implementation agent as a bounded finding with exact behavior, evidence,
and acceptance criteria.

### 1.1 Campaign-local reviewer guard authorship

The current user explicitly transferred all Montana test/guard authorship and
directly required CI guard wiring to the reviewer on 2026-07-22. This is a
campaign-local exception to the repository's ordinary role split, not a
repository-universal change. It expires when the combined Montana candidate
receives its final campaign disposition.

- Both implementation workers are product-code-only. They must not edit,
  format, stage, commit, rename, delete, or create `tests/**` or `.github/**`.
- Before the reviewer edits a test or CI path previously touched by a worker,
  that worker freezes the current bytes and returns a complete
  `TEST_PATHS_FROZEN` manifest. The reviewer verifies the manifest against live
  state and preserves the frozen bytes as the test preimage.
- The reviewer derives its exact writable guard set from every `guard` node in
  `governance/agent_preventions.yaml`, plus only directly required CI wiring.
  This authority never extends to `src/**`, `config/**`, build scripts, or
  packaging metadata.
- Reviewer-authored tests must exercise the real production boundary. A renamed
  nearby test, helper-only test, manually arranged private state, mock that
  bypasses the owner under test, or test that merely calls cleanup directly is
  a false green and receives its own prevention disposition.
- A guard asserts only facts causally required by its named invariant. It must
  not create a false red by pinning an incidental prefix, translation, ordering,
  formatting detail, or private representation that the invariant does not
  require.
- The reviewer cannot approve its own tests. A fresh delegated reviewer and the
  final exact-tree coordinator review must independently inspect their semantics
  and collection before any product correction receives credit.

### 1.2 Shared-repository and parallel-worktree rule

The primary reviewer and primary implementation agent collaborate in this
repository, but they never co-author the same authority surface.

- The implementation agent owns product-code, configuration, build, or
  packaging surfaces in its current standing worktree lane. A narrow exact
  path/blob ticket applies only when the reviewer deliberately selects one for a
  bounded high-risk slice.
- The reviewer owns roadmap, policy, architecture, status, operator,
  design-system, ADR, report, review-ledger, and publication surfaces.
- Neither role edits the other role's files, even to apply an apparently
  obvious correction; it writes a finding or documentation request instead.
- One path has one active owner. A proposal freeze revokes authoring on that
  proposal until the reviewer returns a disposition.

The active CLI correction lane is
`C:\\tmp\\cryodaq-montana-cli-corrections-staging` on
`review/montana-cli-corrections-staging`. It is a separate proposal lane, not an
integrated dependency and not an alternative source of roadmap authority. The
raw predecessor `C:\\tmp\\cryodaq-cli-montana-half` is explicitly excluded:
no active role reads, stats, hashes, executes, imports, tests, or reconstructs
from it. The reviewer checks only the authorized staging lane's live Git state,
tests, and blockers. Already-authored `docs/**` hunks in staging are untrusted
documentation proposals: the reviewer independently adopts them in a
reviewer-owned slice or excludes them from implementation integration.

During the current pre-integration tranche, ownership is deliberately disjoint:

- primary lane: persistence/storage ownership and settlement plus assistant/RAG
  product corrections;
- CLI lane: lifecycle/snapshot/experiment/ingress/transport-driver/GUI/disk
  product corrections;
- reviewer lane: the union of registered primary, CLI, integration, and
  governance guards, their test paths, and directly required CI guard wiring;
- shared surfaces, including `src/cryodaq/engine.py`, transfer serially. While
  the CLI lane is active, it owns new edits needed there for its correction;
  the primary lane preserves its pre-existing dirty bytes but does not add
  overlapping edits. After the CLI proposal freezes, receives reviewer approval,
  and is integrated, remaining shared corrections transfer to the single primary
  Montana lane.

The reviewer records every transfer. A broad message that accidentally names an
already-owned path does not create dual ownership; the current explicit matrix
and latest reviewer correction govern. Workers report rather than edit across a
conflict.

When the CLI lane reports completion, do not merge its dirty worktree or trust
its self-reported ledger. Reconcile the ledger to live Git, identify each exact
base..commit range, recreate the proposal in a clean detached review worktree,
freeze all blobs/modes, and run the review and evidence gates in M10. Only
reviewed commits may enter the integration candidate; seeded or unrelated
dirty files never do.

## 2. Sources of truth and startup ritual

At the beginning of every fresh session or compacted continuation, read these
files in this order:

1. `AGENTS.md` completely;
2. `ROADMAP.md`, especially "Montana final engineering, review, and publication
   checklist";
3. this file completely;
4. `PROJECT_STATUS.md` for open physical and release-boundary gates;
5. this agent's own ignored context capsule from section 9, when it exists;
6. `scratchpad/montana/exec/implementation_agent_doc_requests.md`, when it
   exists and this agent owns it;
7. the current reviewer ticket or standing-lane disposition selected by the
   live roadmap/contract.

The first orientation is strictly read-only. Missing or stale optional
coordination files are reported but do not block a standing worktree-scoped
mandate. A wrong root, branch, frozen-object identity, role boundary, or
unexplained concurrent edit remains blocking.

Then run, without changing the tree:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
```

Record the branch, HEAD/tree, complete dirty-file list, current slice, file
ownership, exact next command, and unresolved blocker in this agent's own
ignored context capsule before authoring. Never infer current state from an old
handoff, old CI run, another agent's capsule, another worktree, or a reviewer
report over a different blob.

Do not pull, reset, checkout, clean, stash, stage, commit, rebase, merge, or
switch branches. The reviewer owns Git integration. Do not touch an unexplained
dirty file. If a reviewer ticket names an already-dirty file, first preserve:

```powershell
git hash-object <path>
git diff --binary -- <path>
```

in ignored evidence under `.audit-run/implementation-agent/<slice-id>/`, plus a
byte-exact pre-formatter copy. Record post-author and post-formatter blob IDs
separately.

## 3. Slice and review protocol

Only one implementation slice per author worktree may be in AUTHORING at a
time. Multiple author worktrees require reviewer-recorded ownership and serial
coordination wherever repo-relative paths overlap; no lease file is required by
a standing lane mandate. Slow read-only tests may run while an agent analyzes a
disjoint next slice, but no author may touch a frozen candidate.

Each slice uses this lifecycle:

```text
UNSTARTED -> ORIENTED -> LANE_ASSIGNED -> AUTHORED -> AUTHOR_GATES_PASS
          -> MANIFEST_FROZEN -> PROPOSAL_OBJECT_CREATED
          -> FRESH_REVIEW -> CODEX_REVIEW -> REVIEW_BAD | REVIEW_GOOD
REVIEW_BAD -> CORRECTING -> AUTHOR_GATES_PASS -> MANIFEST_FROZEN
REVIEW_GOOD -> INTEGRATION_QUEUED -> INTEGRATION_FROZEN
            -> POST_INTEGRATION_REVIEW_BAD | POST_INTEGRATION_REVIEW_GOOD
POST_INTEGRATION_REVIEW_BAD -> CORRECTING
POST_INTEGRATION_REVIEW_GOOD -> CANDIDATE_INCLUDED
```

`REVIEW_GOOD` is a reviewer decision, never an implementer declaration. A file
change after freeze invalidates every receipt covering its changed ranges.
The reviewer uses Git-only operations to materialize the exact frozen author
patch as a local proposal commit/tree in a clean review worktree; it does not
repair code or resolve code conflicts by editing. Reviews bind that immutable
proposal object. A dirty blob manifest alone is author evidence, not a final
review object, and bad proposal commits never enter the integration candidate.

Confirmed agent mistakes use a paired prevention lifecycle:

```text
MISTAKE_CONFIRMED -> PREVENTION_ID_ASSIGNED -> RULE_AUTHORED
                  -> GUARD_RED -> FIXED_GREEN -> PREVENTION_REVIEWED -> CLOSED
```

The reviewer owns the rule, machine-testability disposition, and, for this
campaign's active reviewer-guard-author tranche, the deterministic guard. The
implementation agent owns only the separately assigned product correction. A
machine-testable incident remains open without preserved
red-before-fix and green-after-fix evidence in its default CI partition. No
slice containing or exposing a confirmed mistake may reach `REVIEW_GOOD`,
`POST_INTEGRATION_REVIEW_GOOD`, or `CANDIDATE_INCLUDED` until its prevention ID
maps to the governing rule, named guard, required CI job, and immutable evidence.
A deterministic reviewer reproduction that contradicts a green suite creates a
second false-green prevention ID; the implementation agent must convert that
reproduction into a default-partition regression before the product correction
can earn review credit.

The canonical prevention registry is `governance/agent_preventions.yaml`.
Implementation agents read but never edit it. During this tranche the reviewer
owns `tests/governance/test_agent_preventions.py` and any directly required CI
implementation; the validator runs in both default `remaining` matrix jobs.
Missing or uncollectable guard nodes keep the associated proposal rejected.

For each standing-lane tranche, or for a narrow exact ticket when deliberately
selected, the reviewer records:

- slice ID and objective;
- allowed and forbidden files;
- the violated contract and failure reproduction;
- invariants that must remain true;
- required deterministic tests and broader gates;
- documentation deltas to request, not author;
- stop/escalation conditions.

The implementation agent returns a frozen manifest containing:

- base HEAD and every old/new blob ID;
- exact file list and `git diff --stat`;
- a concise behavior-level diff explanation;
- every command, exit code, pass/fail/skip count, platform, interpreter, and
  elapsed time;
- repetition counts/seeds for concurrency tests;
- unresolved warnings, unavailable gates, and proposed doc deltas;
- the exact command the reviewer should run first.

Place it at
`.audit-run/implementation-agent/<slice-id>/frozen-manifest.md`. Do not claim a
moving worktree is frozen. After writing the manifest, re-hash every covered
file and stop authoring until the reviewer responds.

The reviewer performs a fresh-context independent review and a separate
coordinator review. Findings are classified:

- **P0:** could energize hardware, bypass safety/authority, lose authoritative
  evidence, or corrupt data silently;
- **P1:** release blocker: incorrect lifecycle, concurrency, persistence,
  protocol, operator truth, or bounded-resource behavior;
- **P2:** material robustness, maintainability, test, or documentation issue;
- **P3:** optional polish with no release effect.

All validated P0/P1 findings and in-scope P2 findings are corrected and
re-reviewed. A reviewer may explicitly defer P2/P3 only in the governing
roadmap/status documents.

## 4. Global invariants for every code slice

Every implementation decision must preserve all of these:

1. SafetyManager remains the sole authority for energetic output. Classification,
   GUI, web, Telegram, assistant, drivers, or plugins never become alternative
   actuation owners.
2. Hazardous output defaults OFF. Unknown, timeout, cancellation, process
   death, malformed input, missing evidence, and stale identity fail closed.
3. A command that may already have been dispatched is never reported as safe to
   retry. Mutation execution remains owned until exact settlement.
4. Emergency OFF remains available during uncertainty; ordinary mutations do
   not.
5. Acquisition facts are persisted before acquisition fan-out. Derived,
   system, replay, and presentation facts are explicitly typed and never
   masquerade as persisted acquisition evidence.
6. Stable instrument/channel identity and descriptor provenance survive hot
   storage, rotation, replay, reporting, web, and GUI projection.
7. No unbounded queue, collection, JSON/YAML document, archive materialization,
   process wait, executor future, or shutdown owner is introduced.
8. Blocking I/O stays off the engine event loop. Caller cancellation never
   abandons a still-running owner whose side effect matters.
9. The GUI displays backend truth, preserves last coherent values under stale
   evidence, never seeds optimistic green/ready/recording state, and never gains
   control authority from presentation state.
10. Mocks, replay, source-mode tests, screenshots, and CI do not close physical,
    real-instrument, final-element, or independently observed OFF gates.
11. Existing user work is preserved. No broad cleanup, deletion, drive-by
    formatting, or unrelated refactor is allowed.
12. A test is corrected at the strengthened contract boundary. Production
    safety/authority/persistence is never weakened to preserve an obsolete
    expectation.

## 5. Ordered implementation programme

The headings below group responsibilities; their numeric labels are not the
execution order. Use this dependency graph unless the reviewer records a
reviewed dependency-order change in the campaign roadmap:

```text
G00 -> M00
M00 -> M01
M00 -> M04                 (may run in a disjoint isolated lane)
M01 -> M05
M04 + M05 -> M03
M01 + M03 + M04 + M05 -> M02
M01 + M05 -> M06
M01 + M06 -> M07
M02 + M03 + M04 + M05 + M06 + M07 -> M08 -> M09 -> M10
```

The active CLI correction lane currently owns its staged USBTMC,
physical-alarm/configuration, and GUI snapshot/disk/annunciation corrections.
The primary lane does not copy from or edit that worktree. Repo-relative overlap
is coordinated serially: only the approved CLI object enters integration, then
one Phase A owner performs all further combined corrections. Reviews of M02/M03
cannot close before their M04/M05 inputs are integrated, because later changes
would invalidate the earlier safety proof.

For this campaign, `MONTANA-INTEGRATION-SEQUENCE-001` contains the exact
machine-readable edit-owner overrides. They take precedence over durable
registry `correction_owner` / `guard_owner` values for authoring only. A lane
proposal must collect and pass every guard in its exact changed-path and
known-finding closure whose effective campaign editor is that lane. Another
lane's guard is a dependency, never permission to edit it. The combined Montana
freeze reruns the union of both accepted lane manifests plus integration and
governance guards; the final PR/master gates use the complete candidate-required
registry/default-CI closure.
The "likely files" lists aid discovery; they are not blanket write permission.

### G00 — executable governing-layer bootstrap

Before product authoring, the reviewer freezes the governance rule registry and
authors the deterministic validators/tests for this tranche, including guards
that:

- enforce unique prevention IDs and exact mapping from each machine-testable
  incident to a named enabled test in a required CI partition;
- reject missing/duplicate IDs, prose-only or pre-fix-green substitutes,
  skip/xfail/deselection, and deletion of both mapping and guard;
- validate `DONE_FOR_REVIEW` manifests against live branch/HEAD/tree/commit
  range and reject stale ledgers;
- validate persisted external-review receipts, hashes, exact object manifests,
  and terminal sentinels using seeded malformed/truncated fixtures.

The behavior regression remains in the owning subsystem; a documentation
string-presence assertion is not a substitute. A confirmed mistake is not
closed until its guard is red on the preserved faulty state or an equivalent
negative fixture and green after correction.

### M00 — live inventory and executable baseline

**Purpose:** replace stale campaign assumptions with exact current evidence.

The implementation agent runs the hosted-CI-equivalent Windows partitions,
focused known-failure probes, Ruff, format scope from the workflow's declared
baseline, lock drift, and documentation tests. It changes no files in M00.

Before any loopback, subprocess, integration, or full-suite probe, record an
isolation preflight: no production engine/GUI owns the test ports or writable
roots, the test configuration cannot reach a real instrument endpoint, and
the command will use isolated temporary/output paths. Move an unsafe test to an
isolated host/configuration; never stop a live acquisition run for evidence.

Required baseline outputs include:

- core, GUI, agents/reporting, and remaining pytest partitions;
- `python -m ruff check src tests`;
- the exact changed-file format command encoded in `.github/workflows/main.yml`;
- `python scripts/check_lock_drift.py`;
- `python -m pytest -q tests/docs/test_docs_freshness.py`;
- a list of tests that pass only because they assert obsolete weaker behavior;
- exact localhost/Windows/WSL/package gates that cannot yet run.

Do not fix while collecting. Return one failure inventory with each failure
classified as production defect, stale test, stale document, environment gate,
or unknown.

### M01 — command authority, strict wire, and outcome truth

**Purpose:** prevent overlapping/late mutations and make every boundary preserve
dispatch/commit uncertainty exactly.

Known live defect to reproduce first: a mutation handler times out, reports
`dispatched/unknown/retry_safe=false`, a second mutation is admitted, then the
first shielded operation late-commits. The current `_detach_handler_task()` and
`_uncertain_authority_tasks` scaffolding does not enforce quarantine.

Likely files:

- `src/cryodaq/core/command_authority.py`;
- `src/cryodaq/core/zmq_bridge.py` and `zmq_subprocess.py`;
- `src/cryodaq/gui/zmq_client.py`;
- engine/assistant/web clients that encode or decode the same command contract;
- focused ZMQ, GUI-client, web, assistant, and launcher-handshake tests.

Required behavior:

1. Exact command classes are READ, MUTATION, and SAFE_DIRECTION. Unknown actions
   default to MUTATION.
2. READ timeout may cancel and settle its read owner.
3. MUTATION or SAFE_DIRECTION timeout/caller cancellation never cancels the
   execution owner. It returns dispatched/unknown/not-retry-safe and enters
   authority quarantine until exact terminal settlement.
4. While quarantined, READ and emergency OFF are admitted; ordinary mutations
   reject before dispatch with a stable `command_authority_uncertain` outcome.
5. Socket replacement, protocol error, client restart, or server restart never
   clears execution uncertainty.
6. Shutdown freezes ordinary mutation ingress, settles retained handlers, and
   does not close the context while an execution owner can still commit.
7. Each REP receive produces at most one reply send. Cancellation never causes
   a second best-effort send.
8. One shared bounded strict JSON contract rejects duplicate keys, non-finite
   and overflowing numbers, BOM/lone-surrogate/invalid UTF-8, scalar roots,
   excessive depth/items/bytes, non-string keys, and cyclic/non-serializable
   replies. Replies require exact dictionary root, exact boolean `ok`, exact
   integer protocol (boolean rejected), size cap, and phase-accurate outcomes.
9. GUI, subprocess, launcher, assistant, and web distinguish failure before
   enqueue, before dispatch, dispatched unknown, committed, and reconciled.
   They never collapse all transport failures into one retryable string.
10. Secret/capability material and raw exception text never enter replies or
    logs.

Deterministic gates include late-commit quarantine, OFF-during-quarantine,
read-during-quarantine, socket replacement, cancellation at every await,
one-send-per-receive, hostile codec corpora, protocol mismatch, missing/malformed
phase fields, shutdown settlement, and repeated execution.

### M02 — coordinated shutdown, HOLD, and launcher ownership

**Purpose:** ensure no process manager can destroy the owner responsible for
proving hazardous outputs OFF.

Required state machine:

```text
RUNNING -> QUIESCING -> INITIAL_OFF_PROOF
        -> HOLD (when OFF is unverified; process/status/retry owners remain)
        -> RETAINED_OWNER_DRAIN -> ORDERED_GLOBAL_OFF_PROOF
        -> DOWNSTREAM_TEARDOWN -> EXACT_RELEASE_RECEIPT -> CLEAN_EXIT
```

Likely files:

- `src/cryodaq/engine.py`;
- `src/cryodaq/core/safety_manager.py` and `zmq_bridge.py`;
- `src/cryodaq/engine_wiring/supervision.py` and shutdown owners;
- `src/cryodaq/launcher.py`, instance-lock/shutdown-sentinel modules;
- safety, supervision, launcher, and real helper-process integration tests.

Required behavior:

1. A synchronous, idempotent safety cut is registered before the first shutdown
   await. It permanently rejects new energizing/rearm work and increments the
   abort generation once.
2. Ordinary mutations freeze; READ/status and emergency OFF remain live.
3. An initial global OFF proof runs before waiting on hung non-safety owners,
   while driver, SafetyManager children, logging, writer, status, and retry
   paths remain alive.
4. Accepted mutation identities, experiment/scheduler/persistence tails,
   supervisor children, safety children, and reviewed-source operations retain
   one coordinator until settlement.
5. After every possible late mutation settles, a fresh ordered global OFF proof
   runs. Only that proof can authorize downstream teardown.
6. Unverified OFF enters operator-visible HOLD. Repeated signals, cancellation,
   deadline, or retry cannot turn HOLD into success or multiply settlement
   owners.
7. The engine emits one exact release receipt bound to nonce, PID/start identity,
   generation, verified-OFF evidence, and owner settlement. Receipt and clean
   exit are both required.
8. Windows launcher uses a private graceful request and never calls
   `TerminateProcess`/`kill` while OFF is unverified or any safety/mutation
   owner remains unsettled. After the exact verified-OFF release permit has
   settled, a bounded exact-process termination may reap a stuck post-safety
   process without being represented as graceful engine settlement. POSIX
   sends SIGTERM once but never escalates during HOLD. Manual restart obeys the
   same contract.
9. Bridge/status/tray remain live and visibly report HOLD until exact release.
10. Supervisor restart timers are explicitly owned/cancelled and cannot spawn
    after quiescence.

Required tests cover blocked durable logging with many stop retries,
simultaneous child deaths, accepted-but-not-stepped RUN, in-flight RUN, hung
mutation, repeated signal/cancel, wrong/stale/forged/reparse receipt, exit
without receipt, receipt without exit, Windows `CREATE_NO_WINDOW`, POSIX HOLD,
manual restart, and real Windows/WSL helper races.

### M03 — fail-loud interlock transport and physical semantics

**Purpose:** make loss of T1-T10 threshold evidence fail closed without changing
physical thresholds or sensor assignments.

Known reproduction: InterlockEngine's real 10,000-entry DataBroker
`DROP_OLDEST` subscription can lose a transient T1=400 K breach after 10,000
newer T1=300 K samples; no trip occurs. Staleness is not a substitute because
fresh safe samples continue, and SafetyManager directly watches only T11/T12.

Required behavior:

1. Every reading used by an absolute interlock threshold reaches evaluation
   through a fail-loud, frozen safety path. Overflow or evaluator death latches
   a visible SafetyManager fault.
2. No extra component gains actuation authority. Interlock evaluation requests
   action through SafetyManager exactly as before.
3. Ordering and identity are preserved across persistence commit and safety
   evaluation. Do not copy presentation metadata into safety authority.
4. Transient and non-monotone hazards cannot be evicted silently. Safe samples
   arriving later do not erase an unevaluated hazardous sample.
5. T11/T12 physical bindings and T1-T10 mobile semantics remain unchanged
   unless the reviewer obtains a separate human hazard decision.
6. Startup freezes the complete subscriber/evaluator set before acquisition.
   Missing evaluator, overflow callback, or dead task refuses RUN authority.

Required tests include the exact 10,001-sample transient reproduction,
overflow/evaluator death, concurrent batch publish, shutdown/restart, duplicate
and out-of-order evidence, canonical/raw identity mapping, and proof that only
SafetyManager performs the resulting OFF transition.

### M04 — Keithley, transport, and safety-configuration closure

**Purpose:** close software-side hazardous-source and configuration gates while
leaving prescribed physical evidence open.

Sub-slices are independently frozen:

1. **Keithley identity/OFF proof:** exact finite-zero readback grammar,
   nonce/generation/connection binding, both channels, delayed/replayed reply
   rejection, disconnect/shutdown races, watchdog and abort-generation
   ownership.
2. **USBTMC/GPIB desynchronization:** ambiguous query places the transport in an
   OFF-writes-only quarantine; delayed bytes cannot satisfy a later query or OFF
   proof; only clean reconnect with new identity clears it.
3. **Transactional safety configuration:** one bounded immutable exact-typed
   YAML; duplicate/unknown keys, aliases, unsafe paths, malformed regex,
   non-finite/range/type errors fail before one atomic commit; failed reload
   leaves prior authority byte-identical; startup refuses unsealed config.
4. **Pattern/binding proof:** frozen descriptor manifest plus selected safety
   config yields zero dead, ambiguous, neighbouring-prefix, or unintended
   safety/alarm/interlock bindings. Raw acquisition never reinterprets canonical
   labels.

Do not alter a threshold, physical sensor assignment, safe-direction rule, or
verified-OFF policy without a reviewer-issued human/hazard decision. Software
tests cannot close real 2604B firmware, dummy-load, host-death, independent
terminal V/I/P, trip-time, or final-element gates.

### M05 — persistence, writer containment, and operator-log identity

**Purpose:** make publication and operator records durable, bounded,
idempotent, and complete across restart and cold rotation.

Required acquisition behavior:

- uncommitted acquisition readings never reach live or safety fan-out;
- commit receipts, cardinality, descriptors, and provenance match exact
  persisted rows;
- writer lock/busy/disk-full/hang/cancellation is bounded and visible;
- derived/system/replay readings use explicit non-acquisition publication types
  instead of weakening the acquisition invariant;
- shutdown retains the writer and every accepted persistence owner until the
  contract permits teardown.

Required operator-log behavior:

1. Production startup initializes durable idempotency before `log_entry`
   ingress becomes available.
2. Engine dispatch calls the durable idempotent append path, not the legacy
   unkeyed append, and a bounded RAM cache is never the authority.
3. Canonical SHA-256 fingerprints cover accepted persisted semantics after
   scope resolution and exclude transport epoch/capability fields.
4. Same key/same content returns the same receipt across process restart and
   cache eviction; same key/different content rejects without write.
5. Cold schema v2 preserves row ID and nullable request ID/fingerprint with
   exact pairing/types, index/schema receipts, and v1 public-read compatibility.
   Private idempotency fields never leak through public payloads.
6. Registry capacity rejects before accepting a row that would make the next
   restart unprovable.
7. Hot+cold reads are bounded by rows, bytes, sources, and deadline; verify
   checksum/schema/path authority; partial or corrupt results are explicitly
   unavailable/incomplete, never empty-current success.
8. REST accepts a stable bounded idempotency key, binds it to content, returns
   accurate HTTP/commit phases, and does not generate a new identity for a
   retry. Both web GET routes send explicit `log_scope`.
9. Telegram derives a stable key only from exact update identity; malformed
   identity rejects before dispatch; unknown outcome remains unknown.
10. GUI unknown attempts persist exact pending identity/payload across GUI
    restart, lock duplicate authoring, and clear only after exact reconciliation.
11. Replay blocks `log_entry` at the shared authority gate. The assistant stays
    read-only; do not grant it a writer to satisfy stale configuration prose.

Required tests use a real writer plus real engine dispatcher across restart,
cache eviction, rotation/deletion, corrupt v1/v2 archives, capacity, web
integration, HTTP retry/conflict/unknown, Telegram redelivery, GUI process
restart, replay authority, and assistant no-write boundaries.

### M06 — bounded history, replay, web, and assistant observation

**Purpose:** ensure historical/operator truth cannot become unbounded, partial,
ambiguous, or protocol-forged.

Required behavior:

1. History applies one global row/source/byte/deadline budget before
   materialization, including filtered multi-channel queries. It returns an
   exact completeness/truncation/error receipt.
2. Unusable numeric evidence crosses JSON as `null` plus status/quality and
   identity, never NaN/Infinity and never silent omission. Plots render gaps;
   statistics exclude unusable points explicitly.
3. Cross-channel results expose source/arrival time and skew so comparisons do
   not pretend asynchronous values are simultaneous.
4. Pressure/vacuum queries use exact descriptor-qualified identities and units;
   insufficient fresh evidence clears old conclusions visibly.
5. Web auth executes before body parsing; actual received bytes, not only
   `Content-Length`, are bounded. Web ZMQ uses the shared strict codec. A bad
   broadcast item cannot kill the pump; inbound WebSocket text is bounded and
   rejected if unsupported.
6. Assistant queries use the exact read allowlist, strict bounded codec, scoped
   receipts, no mutation-envelope/capability fields, and no raw transport error
   leakage. No-data, unavailable, incomplete, and protocol-invalid remain
   distinct.
7. Replay validates the entire source and identities before opening a
   ready-looking server or publishing any reading. It owns an immutable
   validated spool, streams in bounded/O(1) memory, and rejects source mutation
   between validation and playback.
8. Replay mutation compatibility is exact: only explicitly approved replay-local
   metadata actions exist, capability discovery/validation is real, and every
   live mutation is blocked before dispatch.
9. Launcher adoption validates exact protocol/server/app/process identity,
   bounds replies, and cleans sockets/contexts on every failure.

Required tests cover hostile JSON, oversized/filtered history, cold deadlines,
null/status projection, partial receipts, archive traversal/checksum/schema,
web chunked/lying length, pump survival, assistant wrong-proto/scalar/truthy-ok,
replay invalid/mutating source before first publish, source swaps, large-source
memory bounds, and launcher spoof responders.

### M07 — GUI operator truth and lifecycle, surgical only

**Purpose:** finish the existing operator-centric GUI without a ground-up
dashboard replacement.

The current dashboard is intentionally information-dense. Do not remove,
summarize away, or hide current values, status, provenance, controls, or
unexpected conditions. Every GUI change must state what becomes better, what
could become worse, and why the trade aligns with safety and operator workflow.

Required code corrections include:

- one GUI-thread Store atomically accepts or rejects each complete global
  operator-snapshot revision across every summary consumer; a render never
  mixes or partially applies revisions;
- each measurement channel owns one bounded <=2 Hz display cut containing the
  last usable value, current status, source and arrival times,
  descriptor/provenance, freshness/connectivity/identity, interval extrema,
  invalid-value evidence, worst status, and clock skew. Top watch, cells,
  specialist panels, and analytics consume this authority rather than
  independently reconstructing truth;

1. Isolate each reading sink. One overview/panel exception cannot prevent later
   sinks from receiving the same reading; failures remain visible in bounded
   diagnostics.
2. Bound bridge-to-Qt draining per tick with fair continuation and backlog
   evidence. Do not freeze the UI by synchronously draining an arbitrary queue.
3. Replace `ZmqCommandWorker.finished = Signal(dict)` shadowing with a distinct
   result signal plus inherited `QThread.finished`; use one deterministic
   retention/prune lifecycle.
4. Preserve last coherent values when evidence becomes stale/disconnected,
   dim/mark them with age and non-color cues, and never blank useful truth.
5. Keep display updates understandable at <=2 Hz while acquisition, safety,
   persistence, alarms, and control remain full-rate.
6. Explicitly show cross-channel skew; reserve safety colors only for safety
   meaning; active phases use a non-safety accent; T11/T12 labels name the
   nitrogen plate and GM second stage.
7. Responsive auto-adjustment may reflow controls and deliberately scroll dense
   tables, but no current value/status/provenance may be clipped without a full
   accessible path.
8. Preserve keyboard access, Russian operator wording, non-color cues, DPI,
   memory/frame/startup budgets, and replay mutation disablement.

The implementation agent edits GUI code/tests only. It records required token,
component, pattern, accessibility, performance, version, changelog, and
change-impact deltas for the reviewer. It does not edit `docs/design-system/**`.

Required tests are scenario/behavior tests, not screenshot approval alone:
faulting sink continuation, bounded backlog, worker deletion/restart,
stale-value preservation, no optimistic seed, replay safety, keyboard/DPI,
operator scenarios, long-session memory/frame budgets, and isolated mock/replay
every-screen visual evidence after integration.

Conductivity auto-advance remains disabled until a human/reviewer fixes the
freshness-loss behavior (PAUSE/HOLD or verified STOP/OFF). The implementation
agent must stop rather than choose.

### M08 — reviewer-owned documentation and architecture reconciliation

The implementation agent does not edit this slice. It supplies structured doc
requests with exact code blobs and claims. The reviewer updates README/Russian
overview, status, protocol, architecture, operator/deployment/lab procedures,
design system, full Montana report, metrics, ADRs, and both important/all-file
SVG levels.

Implementation-agent responsibilities are limited to:

- report new modules, registration/wiring, schemas, commands, state machines,
  changed operator behavior, and exact test evidence;
- run reviewer-requested generators in dry-run/check mode when they do not
  mutate governing files;
- identify stale docstrings in code and correct them only when the reviewer
  includes those source files in a code ticket.

Known reconciliation points include protocol v2 vs stale v1 prose, strict wire
claims, command-authority quarantine, verified-OFF/release FSM, DataBroker
acquisition-vs-derived semantics, remote non-energetic Telegram writes, T11/T12
open physical binding gates, operator-log v2, and candidate-matched inventories.

### M09 — exact-candidate platform, package, soak, and CI evidence

After M01-M08 are integrated and reviewed, the reviewer freezes one candidate
commit. No authoring lane may touch it while evidence runs.

Repeat the isolation preflight from M00 before every loopback/process/full-suite
partition. Record test ports, temporary/writable roots, real-instrument
reachability result, and confirmation that no live acquisition process was
disturbed. A missing or unsafe preflight gives the partition zero evidence.

The implementation agent runs or assists with exact commands requested by the
reviewer for:

- Ruff check and workflow-exact changed-file format gate;
- requirements-lock drift;
- every configured pytest partition on native Windows;
- the same Linux-sensitive partitions in real WSL/Linux;
- source-install and configuration smoke;
- sealed final-SHA 15-minute mock soak, plus honest status of separate 12/72-hour
  elapsed-duration evidence;
- Windows ONEDIR build from the exact candidate, artifact SHA-256, and every
  frozen smoke cell against that artifact;
- real localhost/process tests where the contract requires those properties.

Evidence must name commit/tree, platform, Python/dependency lock, command,
environment, pass/fail/skip count, duration, artifact hash, and retained logs.
An unavailable environment remains OPEN. Do not mock WSL, Windows, localhost,
packaging, elapsed time, or hardware properties.

Any failure reopens the owning engineering slice. Fix in a new code ticket,
review again, integrate, freeze a new commit, and rerun every invalidated gate.

### M10 — exhaustive review, integration, and PR

The reviewer owns this stage. The implementation agent stops authoring and
answers questions about frozen code.

The reviewer requires:

1. one fresh-context subagent review and one independent coordinator review for
   every engineering/evidence gate;
2. an exhaustive object/range map over additions, modifications, deletions,
   renames, binary/mode/symlink/gitlink/LFS obligations and exact blobs;
3. independent architecture, threat-model, operator-workflow, safety,
   concurrency/persistence, test-quality, docs, packaging, and platform audits;
4. correction and full re-review of every changed range;
5. a clean exact candidate whose locally reproduced gates match the object to be
   pushed;
6. all eight hosted Ubuntu/Windows CI jobs green on that same hash;
7. a second audit of the ready PR diff and hosted evidence;
8. when and only when the current user explicitly authorizes transmission to a
   named external model/provider for an exact frozen object, one additional
   read-only external audit under that authorization's scope.

External-model review is optional additive evidence, never a mandatory Montana
gate and never a replacement for the fresh-context internal reviewer and
coordinator reviews. Without exact current-user authorization, no source,
manifest, threat model, or evidence is sent externally and no integration,
ready, merge, or publication gate is blocked merely because an external service
is absent. When authorized, preserve and hash the complete report and verify
every finding locally; corrections still create a new candidate and reopen the
affected internal coverage.

The implementation agent never interprets review coverage, external-model
opinion, a green subset, or line-count completion as PR authority.

## 6. Post-Montana Agent-Native Plugin Authoring phase

This phase is downstream of Montana convergence and does not authorize plugin
implementation now. A half-migrated repository teaches weaker agents
inconsistent idioms, so it begins only after the Montana PR and higher-return
post-Montana work are dispositioned by the reviewer.

When activated, the implementation agent follows `PLUGIN_CONTRACT.md`,
`tests/conformance/`, and `plugins/_template/`; it does not reconstruct the
architecture. Every obligation has a named automated check. A prose-only rule
does not count as added.

The future ordered work is:

1. versioned contract/schema with obligation IDs;
2. abstract conformance harness and hostile weak-model failure battery;
3. passive/unavailable template driver, panel, descriptors, vectors, and
   manifest;
4. cryptographically human-signed safety approval bound to exact manifest hash,
   protected trust roots, and CI verification;
5. architecture-module and contract/template drift enforcement;
6. token-efficient plugin-agent routing and exact commands;
7. model-agnostic pilot: the template and one real instrument plugin generated
   by a representative mid-tier model must reach the same conformance floor as
   a frontier model. Only first-try rate/repair count may differ.

No agent may self-approve actuation or safety limits. SafetyManager remains sole
authority, and software conformance never closes physical acceptance.

## 7. Exact verification discipline

Focused tests run first. Use a unique, bounded temporary directory and disable
cache reuse where it could obscure the object under test. Typical Windows
commands are:

```powershell
python -m pytest -q <focused paths> --basetemp <unique-path> --disable-warnings
python -m ruff check <changed Python paths>
python -m ruff format --check <changed Python paths>
git diff --check -- <slice paths>
python -m compileall -q <changed source paths>
```

For concurrency, persistence, cancellation, election, safety, or lifecycle
work, repeat the deterministic boundary enough times to expose scheduling
escapes and report the exact count. Never make tests pass by increasing sleeps,
loosening exact types/schemas, accepting unknown outcomes, swallowing errors,
mocking the property under test, or weakening production behavior.

The final `python -m pytest -q tests/` command is necessary but not sufficient.
Partition, target-OS, real-localhost, frozen-build, soak, and physical gates
retain their separate meaning.

## 8. Stop and escalate

Stop authoring and write a precise blocker when any of these occurs:

- a behavior choice changes physical thresholds, sensor assignments,
  PAUSE/HOLD vs STOP/OFF, remote authority, verified-OFF meaning, or operator
  responsibility;
- the needed fix requires a governing-document edit;
- an allowed file has unexplained concurrent changes or exact preimage evidence
  cannot be preserved;
- a required path is outside the assigned implementation surfaces or belongs
  to another active lane;
- a test would need real hardware, hazardous output, destructive host resource
  exhaustion, or a mocked substitute for the required property;
- the candidate or evidence object moves during verification;
- a command would discard user work, alter Git history, publish externally, or
  install/upgrade dependencies without explicit authority;
- a failure cannot be classified after focused reproduction.

Report the concrete evidence, alternatives, safety/operator consequences, and
the smallest decision the reviewer/user must make. Do not guess.

## 9. Compaction-safe per-agent context

Montana applies repository-universal `AGENT-CONTEXT-COMPACTION-001` with one
ignored capsule and one writer per active role:

- primary implementation agent:
  `.audit-run/montana/context/primary_implementation.yaml` in the primary
  worktree;
- CLI implementation agent:
  `.audit-run/montana/context/cli_implementation.yaml` in the authorized CLI
  staging worktree;
- reviewer/coordinator: `.audit-run/montana/context/reviewer.yaml` in the
  primary worktree;
- each delegated reviewer:
  `.audit-run/montana/context/reviews/<canonical-task-name>.yaml` in the primary
  worktree.

Each agent writes only its own path by atomic replacement. Capsules follow
`governance/agent_context_schema.yaml`, remain ignored and non-authoritative,
contain no secrets, and expire when the Montana campaign receives its final
reviewed disposition. Keep a concise current-state header and only the latest
bounded event window. Immutable per-slice history lives in hash-addressed frozen
manifests/evidence, not an unbounded context-hostile chat diary. Every capsule
must contain at least:

Montana's `governing_set_id` is `montana-governance-v1` and its exact set is:
`AGENTS.md`, `ROADMAP.md`, `PROJECT_STATUS.md`,
`docs/MONTANA_IMPLEMENTATION_AGENT_SPEC.md`,
`docs/adr/003-governance-as-enforcement.md`,
`governance/agent_preventions.yaml`, and
`governance/agent_context_schema.yaml`. CLI and delegated lanes read these
canonical primary-worktree files without editing them. The capsule path basename
must equal the schema-valid `path_slug`; canonical task IDs containing `/` are
stored separately in `agent_id` and never used directly as path traversal.

```text
schema / agent ID / safe path slug / role / monotonic sequence / supersedes:
canonical root / branch / HEAD / tree / dirty inventory and owned-blob manifest digests:
governing-set ID / exact governing files and SHA-256 hashes:
last acknowledged instruction sequence / active assignment and state:
owned paths and pre-edit blobs / forbidden paths and excluded worktrees:
proposal or freeze identity / publication state:
dependencies / open findings and prevention IDs:
exact commands, results, environment, and evidence paths:
doc-change requests / open physical, target-OS, packaging, soak, and lab gates:
exact next action / updated-at timestamp:
authority: none; live user, governance, and Git must be revalidated
```

The implementation agent also owns
`scratchpad/montana/exec/implementation_agent_doc_requests.md`. Each request
names the code blob, governing file/section, old claim, new verified claim, and
supporting test. The reviewer owns all dispositions and governing edits.

After compaction, never resume from memory alone. Re-read the files in section
2 and verify every recorded root, branch, HEAD/tree, governing hash, dirty
ownership, and proposal blob against the live tree before continuing. A missing
or stale capsule is reconstructed from a zero-write orientation and grants no
scope or approval. The first post-orientation write is the agent's own valid
capsule; no product or review claim may precede it.

## 10. First-orientation handshake

A fresh implementation agent does not begin by choosing a roadmap item. It
first reads `AGENTS.md`, `ROADMAP.md`, this contract, `PROJECT_STATUS.md`, the
  agent's own context capsule/doc-request ledger when present, and the current
  reviewer ticket or standing disposition. Its first response is read-only and
  contains:

```text
ROLE: implementation only; reviewer owns governance, review, Git integration,
      publication, and completion
REPOSITORY / BRANCH / HEAD / TREE:
LIVE DIRTY PATHS AND ASSIGNED OWNERS:
ACTIVE CLI-HALF ASSIGNMENTS THAT MUST NOT BE DUPLICATED:
CURRENT ROADMAP STAGE AND TICKET:
ALLOWED PATHS:
FORBIDDEN GOVERNING PATHS:
VIOLATED CONTRACT AND REPRODUCTION:
INVARIANTS THAT MUST SURVIVE:
PLANNED FOCUSED / BROADER / REPEAT GATES:
OPEN PRODUCT OR SAFETY DECISIONS:
CONFIRMED MISTAKES / PREVENTION IDS:
REVIEWER-AUTHORED RULES OR CLARIFICATIONS:
MACHINE-TESTABILITY / REQUIRED GUARDS / RED-GREEN EVIDENCE:
DEFAULT CI PARTITION / FORBIDDEN WEAKENING:
EXACT NEXT READ-ONLY COMMAND:
```

The reviewer compares that orientation to live Git and the roadmap. A direct
current user/reviewer message naming the canonical worktree, branch, objective,
and implementation surfaces starts a standing autonomous lane. No special
`AUTHORIZE` grammar, input-blob list, password-like token, or lease file is
required. Silence, a roadmap guess, an external audit, or an old handoff is not
permission. Exact path/blob authorization may still be selected explicitly for
a narrow high-risk slice, but it is not the default and never overrides the
standing lane's forbidden governing, Git-publication, secret, hardware, or
cross-worktree boundaries.
