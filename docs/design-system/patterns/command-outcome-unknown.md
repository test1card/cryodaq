---
title: Command-Outcome-Unknown State
keywords: outcome unknown, delivery_state, commit_state, retry-safety, idempotent, mutation, timeout, reconciliation, ИСХОД НЕИЗВЕСТЕН
applies_to: what a GUI surface shows and does when a dispatched mutating command's outcome cannot be proven
status: canonical
references: rules/color-rules.md, rules/accessibility-rules.md, patterns/state-visualization.md, patterns/real-time-data.md, patterns/operator-evidence-and-retention.md
last_updated: 2026-07-26
---

# Command-Outcome-Unknown State

This is a distinct operator-facing state from the `ok | caution | fault | stale
| disconnected` severity/freshness vocabulary in `patterns/state-visualization.md`.
That vocabulary describes **data health** — is a channel's current value
trustworthy. This pattern describes **mutation-outcome uncertainty** — after the
GUI dispatched a command that changes something (Start a source, acknowledge an
alarm, save an experiment field, advance a phase), did it take effect? A channel
can be perfectly healthy while a command sent about it has an unknown outcome,
and the two facts must not be collapsed into one indicator.

## The canonical state: shared transport contract

Every instance in the table below is a presentation of one shared contract
implemented once, in `src/cryodaq/gui/zmq_client.py`:

- A dispatched **mutating** command (never a `READ`) whose reply cannot be
  observed before cancellation, timeout, or an exception is moved from the
  pending-command table into a retained `_outcome_unknown: dict[str, Future]`
  set (`_retain_unknown_owner_locked()`). `send_command()` then returns a
  result dict carrying `"outcome_unknown": True`, plus `"delivery_state"` and
  `"commit_state"` keys describing what is and is not known about the attempt.
  `READ` commands are retry-safe by construction and never enter this set.
- **Exit** happens only when a late reply is routed and matched to the
  retained request (`_route_reply_locked()`), promoting it to a
  `LateCommandResult`; the owning surface then consumes it through
  `reconcile_late_result()`. Nothing may declare a mutation resolved on any
  weaker evidence than this exact matched reply.
- **Enforced, not advisory:** `_close_locked()` — the bridge's terminal
  shutdown path — **raises `RuntimeError`** if `_outcome_unknown` (or
  `_late_results`) is non-empty at close. The transport layer physically
  cannot shut down with a forgotten unresolved mutation; this is a stronger
  pessimism guarantee than any single widget's presentation, and it is the
  reason none of the presentation instances below may treat "connection
  dropped" as license to silently forget an in-flight command.

## The canonical entry classifier: `command_outcome.result_outcome_unknown()`

Deciding *whether* a given mutation reply counts as outcome-unknown is a
separate axis from how that state is then presented (below). Until the
2026-07-25 fix, `ExperimentOverlay` and `KeithleyPanel` each carried their own
private copy of this predicate, and both classified purely by matching six
English/Russian error-prose substrings (`"timeout"`, `"тайм-аут"`, etc.).
Prose-only matching misclassified genuinely-unknown outcomes as ordinary,
resolved refusals whenever the reply carried none of those substrings — for
`keithley_start` this could tell the operator a hazardous source command was
refused when the source may in fact be ON.

`src/cryodaq/gui/shell/command_outcome.py::result_outcome_unknown()` is now
the single canonical classifier. Both surfaces call it instead of
reimplementing the check: `experiment_overlay.py`'s `_result_outcome_unknown`
(:783-785) and `keithley_panel.py`'s `_result_outcome_unknown` (:758-760) are
now thin delegates to this shared function. Its rule, in order:

1. A non-dict reply is unknown (fails closed).
2. Structured settlement evidence is checked **first**. `_handler_timeout`
   and `outcome_unknown` must be exact booleans and a true value is unknown.
   Otherwise, only an exactly typed `(delivery_state, commit_state)` tuple in
   the mutation terminal-tuple contract resolves the outcome. A delivery state
   alone, a read/audit state, a malformed or unrecognised value, an incoherent
   pair, or a false boolean flag without terminal commit evidence is unknown.
3. Error-prose substring matching is only a **fallback**, for reply shapes
   that carry none of the structured keys above at all.
4. `not_committed` / `not_dispatched` commit/delivery states are truthful,
   *resolved* refusals (e.g. `mutation_protocol_incompatible`,
   `command_authority_quarantined`) and must **never** be folded into
   "unknown", even though they sound adjacent to the unresolved case.

The mutation, read, and assistant-audit vocabularies live separately in
`core/command_reply_contract.py`; only the mutation terminal tuples can
resolve this classifier. The command-outcome regression suite scans literal
state spellings constructed under `src/` (dict literals, `dict(...)`, indexed
assignment, `update()`, and joined literal keys). It deliberately cannot prove
that a reply reaches a mutation command or follow interprocedural/runtime-built
keys; runtime classification remains fail-closed unless the actual tuple is
terminal.

Any new surface implementing this pattern must call this shared function for
its entry check rather than reimplementing prose matching locally.

## The rule: colour is never the sole carrier of this state

**Canonical presentation, and the rule that governs it:** `STATUS_CAUTION`
colour **plus** explicit, distinct operator-facing text **plus**
`setAccessibleName`/`setAccessibleDescription`. All three channels are
required together, same reasoning as the two-channel rule in
`patterns/state-visualization.md` — but for this state, text is not optional
even when colour is present, because the text is what tells the operator
**what to do next** (wait, re-check, do not retry blindly), which colour alone
cannot express. A caution-coloured label with no explanatory text fails this
pattern even though it would satisfy ordinary severity signalling.

This is the majority treatment (5 of 9 traced instances) and it is the only
sub-family that carries all three channels simultaneously. New surfaces
implementing this state **must** use it unless they meet the per-row exception
below.

### Sanctioned variant: button relabel + proactive tooltip (per-row context)

`AlarmPanel`'s acknowledgement button changing its own label to `ПОВТОРИТЬ`
and carrying a proactively-set tooltip (not gated on a rejected click) is a
**sanctioned variant, not a deviation** — but only under the specific condition
that makes a shared panel-wide status label actively wrong: **the surface
presents multiple independent instances of the outcome-unknown state at once**
(one alarm row's acknowledgement outcome is unrelated to another row's), so a
single panel-wide banner would be ambiguous about which instance it refers to.
Under that condition, the cue belongs on the exact control it describes, not on
a shared label. A surface that only ever has **one** live mutation in flight at
a time (Keithley's per-channel Start/Stop, the quick-log composer, the phase
stepper) does not meet this condition and should prefer the canonical
panel-level label.

### Deviation: fixed muted colour, text-only (migration-noted)

`ConductivityPanel` and `MultiLinePanel` use a **fixed `MUTED_FOREGROUND`**
status label whose colour never escalates to `STATUS_CAUTION`; only the label
text (prefixed `ИСХОД НЕИЗВЕСТЕН`) distinguishes this state from ordinary
progress text. This is **not a defect** — the text is explicit, proactive, and
carries the required accessible description — but it is a weaker visual
signal than the canonical treatment for the same class of state, and it means
an operator scanning by colour alone (rather than reading text) will not
notice the transition. **Migration note:** when either panel's status label is
next touched for an unrelated reason, add `STATUS_CAUTION` styling to the
outcome-unknown branch to converge on the canonical treatment; do not do a
standalone recolour-only change purely to close this note.

### Deviation: no colour styling at all (most worth converging)

`ExperimentOverlay`'s `_set_operation_status()` applies no colour styling in
any of its three call sites (card save, phase advance, finalize/abort) — text
and accessible name/description only. This is the **weakest treatment in the
family** and the one most worth converging, for two reasons: it is strictly
behind the `(b)` deviation above (no colour at all, versus a fixed muted
colour), and it is the **highest-stakes surface** — the finalize/abort call
site ends an experiment. **Migration note:** prioritize this surface over the
`(b)` deviation above when design-system capacity is available.

### Deviation: tooltip/accessible-description only, not glanceable (Keithley)

`KeithleyPanel`'s per-channel unknown-outcome latch is a deviation, not a
fifth legitimate treatment. The 2026-07-25 fix closed the defect that this
document's tracing found — the latch previously had **no proactive cue at
all**, only a reactive rejection banner after an attempted command — by
adding `setToolTip()`/`setAccessibleDescription()` on the blocked Start/Stop
buttons, set the moment `_latch_unknown_outcome()` fires and cleared
symmetrically by `_maybe_reconcile_unknown_outcome()`. That fix stopped there
deliberately, at the reviewer's direction, and did not reach canonical: a
tooltip carries no colour and requires hover or screen-reader focus to
perceive, so it is not glanceable the way a status label is. The honest
record is that the fix closed the proactivity defect and stopped short of the
canonical treatment, not that it fixed the gap completely. **Migration note:**
the remaining distance to canonical is a visible status element (a label or
badge on the channel block, styled `STATUS_CAUTION`, carrying the same
`authorization_reason()` text) that is glanceable without hover or focus;
implement it as its own reviewed slice rather than folding it into an
unrelated future change to this file. As with Keithley's own latch, remember
this tooltip is conditional on connectivity/read-only (see the instance table
below) and must not be described as an unconditional latch indicator even
after it gains a glanceable counterpart.

## Instance table

| Surface (file) | Entry | Exit | Cue sub-family | Proactive / reactive | Pessimism notes | Structural guarantees |
|---|---|---|---|---|---|---|
| `zmq_client.py` (shared contract, not a presentation) | non-READ command times out / is cancelled / raises after dispatch | matched late reply via `_route_reply_locked()` → `reconcile_late_result()` | n/a — transport layer | n/a | READ commands never enter the retained set; every return path is a `dict`, never `None`/non-dict | `_close_locked()` **raises** if any request remains retained — terminal close cannot silently forget a mutation |
| `command_outcome.py` (`result_outcome_unknown()`, shared contract, not a presentation) | called by `experiment_overlay.py` and `keithley_panel.py` at their own Entry, in place of a private per-surface predicate | n/a — this is the classifier consulted at each caller's Entry, not a state with its own exit | n/a — classification logic, not a cue sub-family | n/a | canonical entry classifier (see "The canonical entry classifier" above); replaces two former private duplicates that matched only error-prose, which could misclassify a genuinely unknown outcome as a resolved refusal | structured `outcome_unknown` / `commit_state` / `delivery_state` checked before the prose fallback; `not_committed` / `not_dispatched` are truthful refusals, never folded into "unknown"; non-dict replies fail closed to unknown |
| `quick_log_block.py` (`QuickLogBlock.set_submission_state`, orchestrated by `dashboard_view.py`) | `_log_result_is_unknown(result)` true, or a disk-persisted unresolved entry restored at construction | `confirm_submission()` after `_log_commit_receipt_matches()` proves the exact same message committed | canonical (a) | proactive | default entry check is `if not isinstance(result, dict): return True` — fails closed on malformed input; Send stays enabled but reconciles by the *same* message/key, not a blind new mutation | — |
| `phase_aware_widget.py` (`PhaseAwareWidget.set_operation_state`, orchestrated by `dashboard_view.py`) | `_phase_result_is_unknown(result)` true after phase-advance, or an inexact reconciliation read | `on_status_update()` once an authoritative `experiment_status` read matches the expected phase | canonical (a) | proactive | auto-polls an authoritative **read** every 5s to resolve — never a blind mutation retry | — |
| `operator_log_panel.py` (`show_unknown`) | connection lost before commit confirmation, or a disk-persisted unresolved submit restored at construction | operator-confirmed reconciliation of the retained submit context | canonical (a) | proactive | persistent banner (`persistent=True`), never auto-clears while unresolved | — |
| `calibration_panel.py` (`show_unknown`) | six call sites across run/export/apply operations | matching operation-specific reconciliation | canonical (a) | proactive | `auto_clear=False` while unresolved | — |
| `keithley_panel.py` (`_latch_unknown_outcome` / `_unknown_outcome_requires`, per-channel) | stale reply after connection-generation turnover, or `_result_outcome_unknown(result)` true (delegates to the shared `command_outcome.result_outcome_unknown()` — structured `outcome_unknown`/`commit_state`/`delivery_state` decide first, prose is only a fallback) | `_maybe_reconcile_unknown_outcome()` — requires **both** a fresh source-state observation **and** a fresh Safety observation past the latched revision, not merely "connection is back" | deviation — tooltip/accessible-description only, no colour, not glanceable (see "Deviation: tooltip/accessible-description only" above) | proactive since the 2026-07-25 fix (`_update_control_enablement()` now sets `setToolTip`/`setAccessibleDescription` on the blocked Start/Stop buttons while latched, cleared symmetrically on reconcile) — previously reactive (visible only after a rejected command attempt); the fix closed the proactivity defect and stopped there, short of canonical | `authorization_reason()` returns this text only when `_read_only` is false and `_connected` is true — **the tooltip is conditional on connectivity, not a guaranteed latch indicator.** While disconnected or read-only, the tooltip reads the connectivity/read-only reason instead; the latch text reappears once connectivity returns and `_update_control_enablement()` re-runs. Do not describe this tooltip as unconditionally reflecting latch state. | Per-channel scope: blocks only that channel's Start/Stop, not the other channel or Emergency OFF |
| `conductivity_panel.py` (`_latch_auto_outcome_unknown`) | disconnect while active, non-`ok` reply to *any* in-sweep command (including `keithley_stop`), or enqueue failure | `_commit_auto_stop()` / `_commit_auto_complete()` — reached only after an authoritative `result.get("ok") is True` for the exact expected command and generation | deviation (b) | proactive | stricter than most instances: *any* non-`ok` reply latches unknown, not only timeout-shaped ones — deliberate for an unattended auto-sweep; `get_auto_state()` documents that external finalize-guards must treat outcome-unknown as part of the blocking `"stabilizing"` state | — |
| `multiline_panel.py` (`_latch_burst_outcome_unknown`) | disconnect or read-only revocation while active/in-flight, non-`ok` reply, or enqueue failure | authoritative `ok: True` reply for the matching action plus generation/staleness match | deviation (b) | proactive | **the latched button's label changes to "Остановить" and clicking it while latched routes to `multiline.burst_stop`, not a repeat of the ambiguous original action** — control flow steers the operator toward the safe direction structurally, not just by warning text | Latched state also (re)starts the status-poll timer to actively resolve via a read, not a mutation retry |
| `alarm_panel.py` (`_pending_ack_states[key] == "outcome_unknown"`, per alarm row) | `_on_ack_v2_result()` when settlement is none of published / pending / aborted, or a worker construction exception before dispatch | operator clicks the relabelled row button → `_retry_pending_ack()` reuses the **identical retained command object** | sanctioned variant (d) | proactive | three-way settlement classification (`validate_alarm_ack_wire_result`): published (exit), pending (retained, distinct substate — commit succeeded, publication unproven), **aborted is terminal and is *not* collapsed into unknown** | `request_id` is **deterministically derived** from `(alarm_name, engine_instance_id, activation_id, operator, reason)` — retry is structurally idempotent, not hopefully-idempotent; per-row gating does not block unrelated alarms |
| `experiment_overlay.py` (`_result_outcome_unknown`, three call sites: card save, phase advance, finalize/abort) | any of the three mutation result handlers finds `_result_outcome_unknown(result)` true (delegates to the shared `command_outcome.result_outcome_unknown()` — structured `outcome_unknown`/`commit_state`/`delivery_state` decide first, prose is only a fallback) | a later authoritative status read reconciles state, or a fresh operator action after reading the explicit warning text — no built-in reconciliation poller for these three, unlike Conductivity/MultiLine/PhaseAwareWidget | deviation (c) | proactive | all three call sites include an explicit operator-facing instruction not to retry blindly; **`_result_outcome_unknown()` (:783-785) now delegates to the shared classifier, which guards `isinstance(result, dict)` before any `.get(...)` call** — this closes the previously recorded inconsistency in defensive posture against `keithley_panel.py`/`dashboard_view.py` | finalize/abort is the highest-stakes call site — it ends an experiment |

## Common mistakes

1. **Treating outcome-unknown as a severity state.** It is not `caution`
   about data — it is a distinct fact about a command. Do not fold it into
   the `patterns/state-visualization.md` severity ladder or reuse a channel's
   health indicator to show it.
2. **Colour-only unknown-outcome cue.** Fails the rule above even where the
   channel's own severity indicator might permit colour-only signalling for
   other reasons.
3. **Silent auto-retry of a mutation on reconnect.** Every instance in this
   table requires either an authoritative reconciling read or an explicit
   operator action; reconnecting alone must never resend a mutating command.
4. **Clearing the cue on "connection is back" alone.** `keithley_panel.py`'s
   two-observation requirement (fresh source state *and* fresh Safety) is the
   strict version of this; even the simplest instances require the *specific*
   expected reply/receipt, not merely restored connectivity.
5. **New panel, new spelling, no documentation.** See the enforcement
   guard below — a new outcome-unknown-bearing GUI file must be added to this
   table in the same reviewed slice that introduces it.

## Related patterns

- `patterns/state-visualization.md` — the orthogonal `ok | caution | fault |
  stale | disconnected` severity/freshness vocabulary this pattern does not
  replace or fold into.
- `patterns/real-time-data.md` — passive data-stream freshness, a different
  mechanism from command-outcome uncertainty.
- `patterns/operator-evidence-and-retention.md` — retaining last-known
  evidence while truth is unproven, the same discipline this pattern applies
  to command outcomes specifically.

## Enforcement

`tests/docs/test_docs_freshness.py::test_outcome_unknown_gui_instances_are_documented_in_design_system`
scans `src/cryodaq/gui/**/*.py` for the pattern's known symbol vocabulary and
asserts every matched file is named in this document. See that test's
docstring for the exact pattern and its known limitation: it is an empirically
verified, not theoretically complete, match against the current naming
variety (`outcome_unknown`, `unknown_outcome`, `show_unknown`,
`set_submission_state`, `set_operation_state`, `ИСХОД НЕИЗВЕСТЕН`) — a
sufficiently novel future spelling could still evade it, which is a known gap
recorded here rather than a claimed guarantee.

## Changelog

- 2026-07-26 (v4.0.4): Narrowed the canonical classifier from independently
  recognised state values to coherent mutation settlement tuples. Read and
  assistant-audit state names now have separate vocabularies and cannot release
  a hazardous mutation's unknown-outcome latch.
- 2026-07-26 (v4.0.4): Corrected the canonical classifier contract so only
  exactly typed, recognised structured settlement values may resolve an
  outcome; malformed evidence now fails closed to unknown. Added an executable
  guard that compares every literal settlement value emitted under `src/` with
  the shared core vocabulary.
- 2026-07-26 (v4.0.4): Documented `command_outcome.py::result_outcome_unknown()`
  as the canonical entry classifier now shared by `experiment_overlay.py` and
  `keithley_panel.py`, replacing their former private per-surface prose-only
  duplicates; updated both instance-table rows and closed the stale
  `isinstance` inconsistency note on `experiment_overlay.py` now that it
  delegates to the guarded shared function.
- 2026-07-25 (v4.0.3): Initial pattern — canonical treatment, sanctioned
  per-row variant, two recorded deviations with migration notes, and the
  nine-instance table with structural-guarantee findings from source tracing.
