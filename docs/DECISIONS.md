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

## [Coordinator] Regenerate frozen snapshots from the staged index, last

Artifacts embedding a hash of the file inventory must be regenerated **after** all content is final
**and staged**. Regenerating against a working tree whose changes are not yet staged produces an
artifact that goes stale the moment they are staged — while the gate reports green.
