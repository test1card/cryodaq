# Decisions

Durable record of decisions that shaped this repository, with **who made each one**.

Read this before changing something that looks arbitrary. Most entries exist because the
obvious-looking alternative was tried and failed, or because a measurement contradicted an
assumption everyone held.

**Authorship marks matter.**

- **[Owner]** — direction, scope, product behaviour, outward-facing acts, hardware gates.
  An agent may *question* these with evidence but must not silently reverse them.
- **[Coordinator]** — engineering and review calls made by a maintaining agent. These are
  revisable on evidence: bring a measurement, not an opinion.

Entries are append-only. Superseding an entry means adding a new one that says so and why —
never editing history.

Formal single-topic architecture decisions live in `docs/adr/`. This file is the running log of
review, process, and scope calls that do not warrant an ADR but must not be lost.

---

## [Owner] Documentation lives in two trees

`README.md` and `docs/` are for humans. `AGENTS.md` and the files it links are for agents.
They may cross-reference, but neither is a dumping ground for the other.

**Why:** a lab forking this repo should be able to point a cheap model at the agent tree and get
working without reading the human narrative, and read the human tree without wading through
machine instructions.

## [Owner] Uncommitted means unreviewed

Work that has not been committed has not been approved by an independent reviewer, regardless of
who wrote it or how confident they were.

**Why it earned its place:** applying this to one campaign's uncommitted work surfaced four
regressions and one internal contradiction that had been invisible because the test partition
containing them aborted partway through and never printed a failure summary. Its exit code was
being read as a verdict.

## [Owner] Gate by blast radius, not by convenience

Three tiers, chosen deliberately:

| gate | scope | when |
|---|---|---|
| smoke | fastest partition + tests for changed files | docs, config, single-file edits |
| targeted | only the partition(s) containing changed files | one subsystem |
| full | every partition | before publication, cross-cutting changes, characterising a flake |

**Always full-gate before publication.** A cheap tier must state plainly what it did *not* cover;
otherwise it becomes a new false-green surface, which is the exact failure this repo's guard
culture exists to prevent.

## [Owner] One architecture graph, not four

Of four generated architecture SVGs, one ships: `docs/architecture-montana-important.svg`. The
exhaustive all-files variant renders over a thousand files and is a provenance artifact, not a
document a human or a weak model can read.

---

## [Coordinator] A guard lands in the same change as the thing it guards

Never publish a test asserting content that arrives in a later change, and never publish content
whose guard arrives later.

**Why:** the first case fails CI on arrival; the second lets the content rot unguarded in between.
This forced a test file to be split hunk-by-hunk across publication units.

## [Coordinator] Never backfill a documented gap from untracked content

If an audit finds a rule missing from tracked documentation, that gap is raised and reviewed on its
own merits. It is never quietly filled from an untracked local file.

**Why it is not theoretical:** an untracked local rules file was found to contain two rules
contradicted by the tree — a stale line-length figure, and a source-encoding rule with 49
counterexamples and zero supporting instances. Promoting that file wholesale, as originally
planned, would have published both as reviewed policy, where they would have inherited the
credibility of the documentation around them.

## [Coordinator] One canonical treatment for a cross-cutting state; deviations recorded, not blessed

Where one contract has many presentations (see
`docs/design-system/patterns/command-outcome-unknown.md`), the design system names **one** canonical
treatment and records every departure as a deviation with a migration note — including deviations
introduced deliberately.

**Why:** documenting several coexisting treatments as equally valid makes no choice and hands a
forking lab a menu. A variant is sanctioned only together with the *condition* under which it is
correct, so the rule generalises instead of grandfathering one file.

## [Coordinator] Colour is never the sole carrier of an operator state

Every state that changes colour must also change text, or an accessible description, or both.

## [Coordinator] Unknown truth resolves pessimistically

An unknown outcome renders as stale, disconnected, or unavailable — never as an optimistic green,
and never as an empty success. A surface with no authoritative snapshot says so rather than
claiming an empty set.

## [Coordinator] A control-flow argument is a hypothesis until a probe discriminates fixed from unfixed

**Why this is stated so bluntly:** during one review campaign, seven separate findings that
explained all available evidence turned out to be wrong under measurement — several of them the
coordinator's own. Every finding that survived was executed; every one that was merely reasoned was
withdrawn. Related: `n=1` on a non-deterministic gate is not a result, and two processes exiting
with the same status is not evidence that they failed for the same reason.

## [Coordinator] Fix the code or fix the test — but say which, with evidence

When a test fails, the question is never "how do I make this green." It is "which side is wrong."
A test rewritten to match code must record *why* the old expectation was wrong, or the next reader
will restore it. A guard must be watched failing before it is trusted: red before the fix, green
after, red again on revert.

## [Coordinator] The governance substrate is not separable from the product

Guards reference product tests, documentation references guards, and guards assert that the
documentation and CI exist. Attempting to publish the agent substrate as its own unit produced two
files that could not pass their own tests in isolation.

**Consequence:** the registry lands *with* the product, never after it.

## [Coordinator] Reproduce a CI failure under CI's own process and import conditions

Two defaults differ between a developer machine and this repository's CI, and both have silently
invalidated local "green" runs:

- **Multiprocessing start method.** Linux CI runs Python 3.14, where the default became
  `forkserver`; a developer on 3.12 gets `fork`. Under `fork` a child is a complete copy the
  instant `Process.start()` returns, so releasing a parent-side handle straight afterwards is
  safe. Under `forkserver` and `spawn`, `start()` only *writes* the pickle — the child rebuilds
  named POSIX semaphores later — so the same release unlinks the name out from under it. A bug of
  this shape is invisible on `fork` and unconditional on `forkserver`. Force the method
  (`multiprocessing.set_start_method("forkserver", force=True)` via a `-p` plugin) rather than
  waiting twenty minutes for CI to tell you.
- **Which `cryodaq` is imported.** A second worktree does not get its own editable install. Tests
  run from it import the *primary* checkout's package unless `PYTHONPATH=<worktree>/src` is set,
  so a source fix appears to do nothing and an unrelated tree's bugs appear to be yours. Check
  `python -c "import cryodaq; print(cryodaq.__file__)"` before trusting any result from a
  worktree.

**Why it is stated here:** each produced a confident, wrong local verdict before it was caught,
and neither announces itself — the failure looks like a flake or a mystery.

## [Coordinator] A test-only fake must not silently absorb the behaviour it stands in for

A frozen test clock whose `sleep()` waits on an `Event` that is never set is a good unit-test
fake: any path that sleeps deadlocks loudly instead of passing by accident. It is a trap for a
test that drives a *real* coordinator loop, where sleeping is the normal steady state.

**What it cost:** two crash-recovery tests hooked a persistence seam the delivery path never
reaches, so the simulated crash never fired. Nothing failed. The loop simply reconciled, slept,
and hung — taking the whole `remaining` partition down with it, on both operating systems, with
no failure summary. A test that cannot fail and a test that hangs are one defect seen from two
sides.

**Consequence:** when a test names a seam ("crash before the success commit"), prove the seam is
on the path — assert the hook ran, or watch the test fail with the hook removed.

## [Coordinator] Guards that read the Git index run against the checkout, never the sealed candidate

The exported candidate tree has no `.git`. A guard calling `git ls-files` or `git check-ignore`
cannot run there and must be listed in `ACTIVE_CHECKOUT_REMAINING_FILES`/`_NODES`, which both
excludes it from the exported suite and requires it in the workflow's exact-checkout step.

**Why not let such a guard skip when `.git` is absent:** a skip is indistinguishable from a pass
in the evidence bundle — exactly the false-green surface the sealed-candidate design exists to
remove.

## [Coordinator] Regenerate frozen snapshots from the staged index, last

Artifacts embedding a hash of the file inventory must be regenerated **after** all content is final
**and staged**. Regenerating against a working tree whose changes are not yet staged produces an
artifact that goes stale the moment they are staged — while the gate reports green.

## [Owner] 2026-07-29 — Montana checkpoint threat model and Cycle 2 authority

> This checkpoint protects against accidental or agent-induced validator and
> evidence-producer weakening, enforced by a judge loaded from the protected
> default branch. It does not claim Byzantine-candidate resistance inside
> pytest, and must never be described as if it does.

Cycle 1 terminated `NOT_PR_READY`. The owner authorized Cycle 2 under the
owner-ratified plan in `ROADMAP.md`. This decision defines checkpoint scope and
authorizes the cycle; it is not review evidence. The owner supplied the ruling
and does not sign the independent review or hosted-evidence receipts required
by the plan.

## [Coordinator] Native required-workflow identity is not a status name

A repository rule admits a candidate only when it natively binds the required
workflow identity and the current `pull_request` or `merge_group` run identity.
A required-status name cannot provide that authority: required status checks do
not account for workflow or event identity, and an earlier success for the same
commit can be reused when a later pull request B presents that commit.

This repository is currently personal-hosted and therefore needs migration to
an organization/enterprise host with ruleset required-workflow support before
that admission invariant can close. The personal-repository required-status
setting remains useful as a fail-closed operational fallback, but it is
non-equivalent evidence and must never be described as native workflow binding.
The required workflow must use its native `pull_request` and `merge_group`
job checks; manually creating or patching a check run does not gain admission
authority.

The tempting `pull_request_target` workaround was rejected because GitHub binds
that trigger’s `GITHUB_SHA` and `GITHUB_REF` to the pull request’s base/default
branch, while a required status must pass on the latest pull-request head SHA.
That native job therefore cannot prove the candidate head merely because it can
read the pull-request payload.

## [Owner] 2026-08-05 — Unmatched channels render desaturated with a Russian marker

A channel with no descriptor match is an **operator-visible option**: the
operator chooses whether such channels are obscured. The default renders the
channel **desaturated** with the Russian marker `н/о`, and the unambiguous
wording (`без дескриптора`) in the tooltip and accessible name.

**Which element the desaturation lands on is a design-system question, not part
of the owner's ruling.** An earlier draft of this entry put
`theme.MUTED_FOREGROUND` on the numeric value; `RULE-DATA-005` holds the value at
`FOREGROUND` in normal, caution, fault and stale alike, and carries state on the
chrome, the label and the marker. The unclassified state takes the same
treatment, for the same reason as the `—` constraint below: the reading is
available and correct, and a dimmed number claims the reading is degraded when
only its classification is missing. The contract is
`docs/design-system/patterns/state-visualization.md`.

Owner, on the marker: *"н/о это норм вариант, оператор не обезьяна, а другие
варианты слишком длинные для маленького поля под число"* — the field is a narrow
numeric one and the operator is trained.

Three constraints ride with the decision, each from a measured failure:

- **Not `—`.** `src/cryodaq/reporting/sections.py` documents `—` as the
  UNAVAILABLE marker, under a NaN-доктрина whose stated reason is that an
  operator would otherwise "read a confident number where none exists". An
  unclassified channel's value IS available; only its classification is missing,
  so one glyph must not carry both meanings.
- **The textual marker is load-bearing, not decorative.** The panel conformance
  obligations require non-colour state cues; desaturation alone is colour-only.
- **Obscuring must be discoverable.** When hidden channels exist, show a count
  (`скрыто: N`) or keep them listed on the settings surface. A live reading that
  becomes invisible by configuration is the vanishing-readout failure returning
  through a setting — the failure behind the `169f7e96` / `0bea0449` revert.

This decision gates the OC-008/OC-030 site migrations; its absence is what the
ratified plan names as the cause of that revert.

## [Owner] 2026-08-05 — A still-active CRITICAL must break its own silence

The alarm-narration ledger gets **both** bounds (owner: *"a+b i agree"*):

- **A — a narration that reached nobody buys no silence.** If no target accepted
  it, that alarm is re-armed rather than held quiet for the full window.

  **A is bounded, and the unbounded reading was reviewed out.** "The next
  occurrence is not suppressed" is not what shipped: during a transport outage
  every refire would become another generation and send, which is the storm the
  window exists to prevent, arriving by the recovery path. The retry is admitted
  once `window_s` has elapsed since the failed attempt. Allowing an attempt also
  clears the failure marker, so the bound is measured against the attempt in
  flight and not against one already superseded — without that, a refire during
  an in-flight retry starts a second one, because the default Ollama timeout is
  longer than the 30 s window.

  **A cancelled attempt counts as undelivered.** `stop()` cancels in-flight
  handlers and `CancelledError` is a `BaseException`, so it does not reach the
  `except Exception` paths that report the outcome. The gate has already moved
  its clock by then, so a killed narration would otherwise buy real silence.
- **B — a CRITICAL that stays active is re-narrated on a bounded interval**,
  currently 300 s, rather than being silenced for as long as it keeps firing.

  **What is bounded is ADMISSION, not receipt, and two earlier versions of this
  entry said otherwise.** The clock is anchored at CONFIRMED DELIVERY rather
  than at the moment the gate admitted an attempt, so the interval between
  admissions of a live CRITICAL is `300 s + one refire interval` measured from
  when the operator was last told.

  It does **not** follow that the operator hears from us within that interval.
  Between admission and delivery sit the hourly rate limit — which can reject an
  admitted escalation outright until its bucket drains — the inference
  semaphore, context assembly, audit-intent persistence, generation, and
  sequential per-recipient transport acknowledgements. No end-to-end deadline
  spans them. A rejected or slow attempt reports undelivered and is retried, so
  silence is not permanent; that is a weaker statement than a bound and is
  deliberately written as one. The first version of this entry claimed 300 s
  flat, the second claimed `300 s + refire + timeout_s`, and both were false.
  A real received-to-received deadline would be a design change beyond OC-028.

  **An outcome belongs to the attempt that produced it.** Two inferences can run
  concurrently and each may take up to `timeout_s`, so the same alarm can have
  two narrations in flight. A late failure from a superseded attempt must not
  re-arm an alarm a newer attempt already delivered, and an attempt settles
  once — so a cancellation arriving after a successful send cannot overwrite a
  delivery the operator has read.

**Why the interval is elapsed time and not a count of suppressed events.** The
decision was first phrased as "after 10 suppressed windows (5 minutes)". Those
are not the same thing: an alarm re-firing every second reaches ten suppressed
events in ten seconds. The operator-facing meaning is the wall-clock silence, so
that is what the code measures and what
`tests/agents/assistant/test_agent_narration_floor.py` asserts — the longest gap
between narrations of a live CRITICAL, not the number of them.

**Severity scope needs no separate rule.** `_should_handle` already filters this
path to CRITICAL, so every event reaching the ledger is CRITICAL and there is no
lower severity here to treat differently.

**What made this reachable at all:** `mark_delivered` existed but appeared
exactly once in `src/` — its own definition. Production never reported a delivery
outcome, only tests called it, so a narration lost to a broken transport was
indistinguishable from one the operator read. The outcome is now reported from
the dispatch path.
