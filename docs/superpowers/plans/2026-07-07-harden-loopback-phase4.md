# Harden-loopback — Phase 4 Implementation Plan

> **For agentic workers:** protocol as Phase 2 (Opus implements TDD-first, uncommitted,
> report to `scratchpad/montana/impl_p4_<task>.md`; Fable light sanity + commit with
> `Ref:`/`Risk:`; deep Fable+Codex gate after the phase). Never push/tag.

**Goal:** the ratified write-surface hardening: authenticated REST writes for
operator convenience (Montana self-serve), with the loopback trust model
preserved and ZERO new hardware-control paths. Release rider on v0.60.0.

**Branch:** `feat/harden-loopback` (stacked on `feat/nan-doctrine`).

**Ratified basis:** 5a (REST writes later + optional → now), 5b (auth token from
local config; reads stay open on loopback), lock-token DEPRIORITIZED (skipped —
single-operator lab; its whole job is to say "no" to the operator, violating the
"nothing blocks the operator" criterion). ZMQ/REP size caps already landed in
Phase 1. Scoping decision under the autonomous-authorization criterion:
**REST never controls the source.** Write endpoints forward only allowlisted,
non-hardware engine commands; SafetyManager-relevant control (source on/off,
setpoints, calibration apply) remains GUI/ZMQ-only. REST OFF-switches are also
excluded — OFF paths must never depend on a token check.

## Global Constraints
As Phase 2 (TDD RED evidence, `.venv/bin/python -m pytest`, ruff, no AI traces,
Russian operator text, SafetyManager sole authority). server.py/rest_api.py are
the main surfaces; keep `test_no_public_bind_in_docs` green.

---

### Task P4-1: write-auth token infrastructure

**Files:** `src/cryodaq/web/rest_api.py`, `src/cryodaq/web/server.py`,
`config/notifications.local.yaml.example`-style local-config pattern (study how
secrets load today — `notifications/_secrets.py`, `config/*.local.yaml`),
`tests/test_rest_api.py`.

Token from local config only (never the tracked yaml): `web.api_token` in
`config/web.local.yaml` (create `config/web.local.yaml.example` documenting it).
No token configured ⇒ ALL write endpoints return 403 «API token не настроен»
(fail-closed default; reads unaffected). Auth = `Authorization: Bearer <token>`
compared constant-time (`hmac.compare_digest`). GET endpoints stay tokenless.

- [ ] Failing tests: write without token → 401; wrong token → 401; no token
      configured → 403 for writes; reads never require token; token never
      appears in logs (redaction — reuse SecretStr pattern).
- [ ] Implement dependency/middleware; wire.

### Task P4-2: allowlisted write endpoints

**Files:** `src/cryodaq/web/rest_api.py`, `tests/test_rest_api.py`.

Endpoints (each forwards the EXISTING engine command; no new engine logic):
- `POST /api/v1/log` — operator-log append (author field forced to «REST»-tagged
  identity, not client-supplied impersonation).
- `POST /api/v1/alarms/{id}/ack` — alarm acknowledge.
- `POST /api/v1/experiment/note` — experiment note append (if the engine command
  exists; otherwise drop this endpoint — do NOT add engine commands).
Explicitly NOT exposed: source control, setpoints, calibration, experiment
start/finalize, config mutation. A request size cap already exists (Phase 1).

- [ ] Failing tests: each endpoint forwards the right engine command with auth;
      allowlist is closed (POST to any other /api/v1 path → 405/404, never a
      command); author/impersonation fields cannot be spoofed.
- [ ] Implement; Swagger reflects the write endpoints + auth scheme.

### Task P4-3: REP command-surface documentation + defensive rejects

**Files:** `src/cryodaq/core/zmq_bridge.py` docstring/`docs/`, small test.

The unauthenticated REP hardware-write exposure is BY-DESIGN (loopback trust
model, D7.2 accepted). Make that decision inspectable: module docstring section
listing the trust model, the accepted risk, and the compensating controls
(loopback bind, size caps, SafetyManager authority). Add a defensive reject of
commands with unknown top-level type at the dispatch boundary if not already
present (verify first — likely exists).

- [ ] Verify + document; test only if a reject was actually added.

---

## Wave plan
P4-1 → P4-2 (same files, sequential); P4-3 parallel with P4-1. Then Phase-4
Fable+Codex gate (focus: token handling, allowlist closure, impersonation,
no-new-control-path invariant), fix wave, full suite, close.
