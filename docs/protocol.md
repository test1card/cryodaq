# CryoDAQ wire protocol

Compatibility policy for the three network surfaces CryoDAQ clients talk to:
engine ZMQ, assistant ZMQ, and the REST/web API. One page, mechanical rule,
no version negotiation handshake — see "The rule" below for why.

## Surfaces (proto v1)

| Surface | Address | Direction | Encoding |
|---|---|---|---|
| Engine PUB | `tcp://127.0.0.1:5555`, topic `readings` | engine → GUI/subscribers | msgpack `Reading` dict: `ts,iid,ch,v,u,st,raw,meta` |
| Engine PUB | `tcp://127.0.0.1:5555`, topic `events` | engine → assistant | JSON `EngineEvent` dict: `event_type,ts,payload,experiment_id` |
| Engine PUB | `tcp://127.0.0.1:5555`, topic `operator.snapshot` | engine/replay-compatible producer → GUI | canonical UTF-8 JSON `cryodaq.operator-snapshot` envelope v1, exactly two bytes frames |
| Engine REP | `tcp://127.0.0.1:5556` | GUI/web/assistant clients → engine | JSON command envelope, see below |
| Assistant REP | `tcp://127.0.0.1:5557` | GUI (`assistant.*`/`rag.*` commands) → assistant | same JSON command envelope |
| REST/web | `http://127.0.0.1:8080` (`/api/*`, `/api/v1/*`) | any HTTP client → web process | JSON over HTTP |

The default ZMQ addresses are loopback-only. Wildcard binds (`0.0.0.0`, `*`,
`::`) are rejected. A deployment may configure a specific interface address,
but it then owns the exposure decision described by the trust model in
`core/zmq_bridge.py`; the recommended LAN path remains an SSH tunnel to
loopback.

## Command envelope

Every REP command is `{"cmd": "<name>", ...params}` in, `{"ok": bool, ...}`
out. Since proto v1, every reply additionally carries `"proto": 1` — injected
by `ZMQCommandServer._encode_reply` (`core/zmq_bridge.py`), not per-handler, so
success replies, malformed-JSON rejects, handler timeouts/exceptions, and
recoverable serialization failures use the same envelope.

A dedicated read-only command, `protocol_version`, answers without touching
the engine's own command dispatch:

```json
{"ok": true, "proto": 1, "server": "engine", "app_version": "0.64.1"}
```

`server` is the explicit `"engine"` or `"assistant"` role of the REP server;
it does not change when an operator configures a non-default bind address.
`app_version` comes from `importlib.metadata.version("cryodaq")` (falls back
to `"dev"` if the package isn't installed, e.g. a source checkout without
`pip install -e .`).

The GUI-facing assistant discovery name is `assistant.protocol_version` so the
existing prefix router selects assistant REP. The bridge normalizes that local
alias to the standard `protocol_version` command on the wire; assistant command
handlers never see or reject the alias.

## REST

`GET /api/version` (unauthenticated, same trust as every other GET route)
returns the same triple with `server: "web"`:

```json
{"proto": 1, "server": "web", "app_version": "0.64.1"}
```

REST shares `PROTOCOL_VERSION` from `core/zmq_bridge.py` rather than
declaring its own constant — engine ZMQ, assistant ZMQ, and REST all ship
from the same package build, so one number is honest. A REST-only breaking
change still bumps the shared constant.

The public live-reading surfaces use strict JSON. A non-finite instrument
value (`NaN`, `+Infinity`, or `-Infinity`) is represented as JSON `null`; its
status and identity remain present so a client can show unavailable/stale
truth instead of accepting a non-standard numeric token.

Exactly two REST routes mutate state and both require the configured bearer
token before their request body is processed:

- `POST /api/v1/log` accepts operator text, optional tags, and an optional
  exact `experiment_id`. The caller supplies `Idempotency-Key` as an exactly
  32-character lowercase hexadecimal value, owns it, and reuses the same key for every
  retry of that request. The server copies that header to `request_id`; clients
  never put `request_id` in JSON. The server owns the author/source identity.
  When `experiment_id` is absent, the entry is explicitly
  `experiment_unbound`; it is never attached to whichever experiment happens
  to be current when the engine receives it. A supplied stale experiment ID
  is rejected by the authoritative engine owner.
- `POST /api/v1/alarms/{id}/ack` requires the exact `engine_instance_id` and
  `activation_id` returned by the current alarm snapshot. Delayed or stale
  acknowledgements fail closed.

### POST /api/v1/log settlement and retry

The `Idempotency-Key` belongs to the caller, not to one HTTP attempt. Preserve
it with the original payload until the submission is settled; never create a
new key to work around a non-2xx response. The status code is the first
settlement boundary:

| HTTP status | Proven settlement and response fields to interpret | Safe next action |
| --- | --- | --- |
| 409 | A definite non-commit. The response contains `caller_request_id`, copied from the submitted header, and an exact boolean `retry_safe`. It proves non-commit with either `committed=false` or `commit_state="not_committed"`; it is not a `publication_state="published"` or `"pending"` receipt. | Retain the same caller-owned key. Retry only when `retry_safe` is `true`; when it is `false`, resolve the rejection without blindly resubmitting or replacing the key. |
| 502 | Outcome unknown: neither success nor definite failure. A structured unknown-settlement body has `commit_state="unknown"`, `retry_safe=false`, `caller_request_id`, and `engine_settlement`. `engine_settlement` is bounded, filtered evidence only: it may be empty and may retain only safe status/correlation fields (`ok`, `committed`, `retry_safe`, `publication_state`, `commit_state`, `delivery_state`, `error_code`, `proto`, `schema`, and a matching `request_id`). It is not an authoritative settlement and cannot turn the 502 into a success or non-commit. A forwarding/transport exception can instead be FastAPI's generic 502 detail body and provides none of those structured fields. | Do not blindly retry and do not invent a new key. Reconcile using the same caller-owned identity; a generic transport 502 is unknown for the same reason. |
| 503 | The command is committed but required broker publication remains pending. The accepted receipt has `committed=true`, `retry_safe=false`, `publication_state="pending"`, and `caller_request_id`; it also carries the persisted entry/commit receipt and the pending diagnostic. | Do not issue a new mutation. Reconcile, or retry that reconciliation, with the same key until publication settles. |

Only accepted completion receipts make `publication_state` authoritative:
`"published"` at HTTP 200 or `"pending"` at HTTP 503. The HTTP 200 receipt
returns the caller key as `request_id`; the non-2xx bodies above use
`caller_request_id` for caller correlation. Do not infer a settlement from a
missing field or from an unrecognized response shape.

Clients cannot supply `author`, `source`, `request_id` in JSON,
`experiment_unbound`, or a generic engine command through these routes.
Reserved system tags are rejected rather than accepted as operator metadata.

## PUB stream (readings / events / operator snapshot)

The PUB frames are **not** touched by this policy's `proto` injection —
adding a field to a fixed-schema msgpack/JSON frame that subscribers unpack
positionally-by-key would itself be a compatibility question, not a free
add. Topic names (`readings`, `events`) and the frame shapes listed above
are frozen as part of proto v1; changing either is a v2 event (see "The
rule").

`operator.snapshot` is an additive, independent observational topic. Its
multipart representation is exactly `[b"operator.snapshot", payload]`; both
frames are built-in bytes and `payload` is exactly the canonical UTF-8 output
of `dump_operator_snapshot`. The receiver enforces the 8 MiB protocol cap
before UTF-8 or JSON decoding, then requires canonical byte equality. The
envelope's own `schema` and `version` fields govern snapshot compatibility.
The production engine publishes only complete, ordered common-cut snapshots
through its sole loop-owned publication service. The launcher and standalone
GUI each own one bounded subscriber/ingress path and apply newer coherent
revisions in the GUI thread. A pure replay-session/view-model contract accepts
the same envelope with conservative unavailable semantics, but production
`ReplayEngine` wiring remains an open reviewed slice. Missing authority fails
dark rather than synthesizing ready/healthy/recording state. This topic is
observational and grants no instrument, safety, or remediation authority.
Adding this independent topic does not alter either existing PUB frame and
therefore does not bump the shared REP/REST `PROTOCOL_VERSION`. A change to its
topic, frame count, canonical representation, schema, or semantics requires a
reviewed snapshot-envelope version migration; publishers must not dual-send a
fallback shape under the same topic.

## The rule

- **Additive field on the command envelope or REST JSON** (new key, same
  meaning for existing keys) → same major, no `PROTOCOL_VERSION` bump. This
  is the common case — new command params, new reply fields.
- **Removal, rename, or semantic change** of any existing field (command
  envelope, REST JSON, or a PUB frame shape) → bump `PROTOCOL_VERSION` in
  `core/zmq_bridge.py` and document it in `CHANGELOG.md`.
- `protocol_version` / `GET /api/version` are themselves permanent, v1-and-
  onward commands — they must keep answering even after a v2 bump so a
  client can always discover what it's talking to first.

## Client rule

- **Tolerate unknown fields.** No client in this codebase validates a REP
  reply or REST JSON body against a closed schema — an extra key is just
  ignored. `agents/assistant/shared/engine_client.py`'s `EngineQueryClient`
  does this by decoding replies into a plain `dict` without a closed schema.
- **Warn, don't block, on a newer server.** `gui/zmq_client.py`'s
  `ZmqBridge._check_proto` compares an incoming reply's `proto` against the
  client's own `CLIENT_PROTOCOL_VERSION` and logs **one** warning per bridge
  lifetime if the server is ahead — it never raises, drops the reply, or
  delays delivery. There is no operator-blocking path anywhere in this
  policy: a version mismatch is a log line, not a failure.
