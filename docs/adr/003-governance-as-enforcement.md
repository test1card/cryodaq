# ADR 003: Confirmed agent mistakes become enforceable governance

- Status: Accepted repository-universal decision; Montana is its first campaign application
- Date: 2026-07-21

## Context

Warnings such as "be careful" do not prevent vibecoding failures. A rule that
exists only in prose can be forgotten, misread, or optimized away by a weaker
agent. CryoDAQ already has evidence that test-enforced rules hold more reliably
than prose-only rules.

## Decision

Every confirmed agent mistake receives one durable disposition with:

1. an incident/failure-mode ID and exact reachable consequence;
2. the violated or newly discovered invariant;
3. the reviewer-owned rule addition, clarification, or link to the canonical
   procedure;
4. a deterministic automated regression or governance guard whenever the
   failure is machine-testable;
5. red-before-fix and green-after-fix evidence bound to exact objects; and
6. a reviewer disposition that names remaining human or physical gates.

The reviewer owns `AGENTS.md`, roadmap, orchestration, design-system, and other
governing text. The implementation agent owns the separately assigned product or
governance-test change. Neither may self-certify the combined correction. A
machine-testable mistake is not closed until the guard exists and passes; a
prose rule without a guard remains explicit governance debt.

An explicit current-user campaign mandate may transfer guard/test authorship to
the reviewer for one named campaign without changing that universal default.
Such an override must be machine-readable, expire with a named campaign
disposition, prohibit implementation workers from editing the transferred guard
paths, prohibit the reviewer from editing product code, require frozen preimages
before ownership transfer, and require independent semantic review of the
reviewer-authored guards. The reviewer still cannot self-certify either the
guard or the product correction it is intended to enforce.

If automation is genuinely impossible, the disposition must explain why and
define a precise human gate with inputs, decision owner, evidence, and failure
state. "Use judgment" is not a gate.

Guards cannot be weakened, skipped, expected-failed, deleted, or scoped around
the original trigger merely to restore green CI. A proposed guard change must
show that the invariant is enforced equivalently or more strongly. Corrections
reopen affected review coverage.

## Enforcement registry

`governance/agent_preventions.yaml` is the canonical machine-readable registry.
Each record contains a unique stable ID, status, scope, authority source,
applicability and expiry where local, class, separate `correction_owner`,
`guard_owner`, and `disposition_owner`, consequence, invariant, governing
references, named guard nodes, required default-CI jobs, and red/green evidence
state. The reviewer owns every rule, registry entry, and final disposition;
implementation roles own only the corrections and guards assigned to them.
Record owners are durable maintenance and disposition-routing defaults. They do
not grant live edit authority in a parallel campaign. A campaign-local record
may supply exact path/node edit-owner overrides; those overrides take precedence
for authoring only, must resolve every affected path/node to exactly one lane,
and expire with the campaign disposition. Lane proposal evidence covers its
effective edit-owned affected closure, while combined/final evidence covers the
required union. This distinction prevents both dual authoring and an unrelated
other-lane guard from deadlocking a bounded proposal.
Closed machine-testable records require immutable
commit/tree/run or artifact bindings for both red and green evidence. Open
records may name pending evidence, but they must already name the required guard
and CI partition so the obligation cannot disappear from handoff context.

Confirmed green-suite escapes are represented in the registry's
`false_green_pairs` collection. Each entry is a separate stable coverage
prevention ID linked to one runtime prevention ID, one exact behavior guard, its
default-CI partition, status, scope, and independent red/green evidence. Pair
status uses the same open/reopened/closed lifecycle as runtime records; a pair
cannot close before its runtime record or with pending evidence. The validator
requires pair IDs to be globally unique, runtime links to resolve, and the named
guard to remain collectable and required; a generic meta-test alone cannot close
a pair.

The registry is also the durable authority for the exact product-contract
invariants it records. A campaign roadmap may supply discovery evidence and
temporary sequencing, but expiry of that campaign cannot expire the product
contract. Campaign-local records transition to `expired` only after the named
expiry condition is satisfied and an immutable reviewer disposition is bound;
they remain historical, cannot authorize new work, and are never deleted or
misrepresented as universally active.

Long-running agents additionally maintain one-writer ignored context capsules
under `AGENT-CONTEXT-COMPACTION-001`. The tracked schema is
`governance/agent_context_schema.yaml`; the transient capsules are recovery
evidence only and never policy, authority, approval, or committed product data.
Missing or stale state requires live read-only reconstruction and exact-object
revalidation before further work claims.

`tests/governance/test_agent_preventions.py` is the required implementation-owned
validator. It runs in the existing Ubuntu and Windows `remaining` CI matrix and
must reject duplicate IDs, unknown fields/statuses/scopes, campaign records
without authority/applicability/expiry/final-disposition semantics, missing rule references,
uncollectable named guards, non-default-CI guards, closed entries with pending
evidence, overlapping/unassigned campaign edit overrides, durable-owner
precedence over an active override, incorrect lane-versus-combined guard scope,
and removal or weakening without an explicit reopened disposition.
The registry and validator are reviewed together. By default only the reviewer
edits the registry and only the implementation role edits the validator/tests;
an explicit campaign-local reviewer-guard-author override may transfer the
validator/tests under the independent-review conditions above.

## Consequences

Agent mistakes create small additional test and governance work. That cost is
accepted because it turns incidents into repository memory that a mid-tier
agent can apply mechanically and that CI can reject when violated.
