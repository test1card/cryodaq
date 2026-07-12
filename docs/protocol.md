# CryoDAQ wire protocol

Compatibility policy for the three network surfaces CryoDAQ clients talk to:
engine ZMQ, assistant ZMQ, and the REST/web API. One page, mechanical rule,
no version negotiation handshake — see "The rule" below for why.

## Surfaces (proto v1)

| Surface | Address | Direction | Encoding |
|---|---|---|---|
| Engine PUB | `tcp://127.0.0.1:5555`, topic `readings` | engine → GUI/subscribers | msgpack `Reading` dict: `ts,iid,ch,v,u,st,raw,meta` |
| Engine PUB | `tcp://127.0.0.1:5555`, topic `events` | engine → assistant | JSON `EngineEvent` dict: `event_type,ts,payload,experiment_id` |
| Engine PUB (reserved, not yet activated) | `tcp://127.0.0.1:5555`, topic `operator.snapshot` | future engine/replay → GUI | canonical UTF-8 JSON `cryodaq.operator-snapshot` envelope v1, exactly two bytes frames |
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
The pure frame codec reserves this contract but does not activate a publisher,
subscriber, engine, replay, or GUI route; those remain separate reviewed
slices.
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
