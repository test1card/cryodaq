# ADR 002: Plugin safety approval uses a protected human signature

- Status: Accepted for the post-Montana roadmap phase
- Date: 2026-07-21
- Implementation status: Deferred; this ADR adds no verifier or trust root

## Context

An ordinary approval file is agent-writable and therefore cannot prove human
authorization. A public key committed in the same pull request is also
insufficient: an agent could generate its own key pair, replace the key, and
sign its own manifest. Actuation and safety-limit changes need a
machine-checkable human gate that is outside the generated change's authority.

## Decision

Passive parsing, simulation, and panel code may pass the ordinary conformance
floor. Any plugin that declares or can reach actuation, source authority,
interlocks, safety limits, or verified-OFF behavior additionally requires a
detached Ed25519 human signature.

The safety manifest is canonicalized with a fixed versioned JSON canonical
form. The approval envelope binds at least:

- domain separator and approval schema version;
- SHA-256 of the exact canonical safety manifest;
- manifest schema version;
- plugin identity and version;
- exact approved capability/scope;
- human reviewer key ID.

CI verifies the signature against a trusted public-key bundle supplied by a
protected CI/review environment outside pull-request-controlled repository
content. Agents and ordinary plugin pull requests cannot write that bundle or
the corresponding private keys. A repository copy or CODEOWNERS entry may
document expected identities, but it is not the trust root by itself.

Missing trust material, signature, field, scope, or exact hash; unknown key;
stale schema; malformed canonical form; repository-added self-key; or a
manifest changed after signing fails closed. The verifier and workflow are
themselves protected, reviewed surfaces. An agent may never approve its own
safety path.

SafetyManager remains the sole actuation authority. A manifest declares trust,
limits, and channels; it does not create a second command path. A valid
software signature does not close dummy-load, final-element, real-instrument,
or laboratory evidence gates.

## Consequences

Actuating plugin CI cannot be fully reproduced without access to the protected
public trust bundle, and provider/branch-protection setup becomes an activation
prerequisite. This is intentional: local or generated evidence must not be able
to counterfeit human safety approval.
