# P7 locked mutation catalogue

**State:** `LOCKED-FOR-P7`  
**Authored against:** commit `f190bc5be647ea8d9f82e8c82ce6049074219722`,
tree `14408112a64c93bf7e540de1b383750521b40b77`  
**Cardinality:** exactly 42 cells: Q1-Q6, B1-B7, E1-E8, D1-D7,
R1-R7, T1-T5, G1-G2.

This catalogue defines the falsifiable boundary of the sealed P7 review round.
A P7 finding counts only when exact structural evidence or deterministic
reproduction maps it to one locked cell below or directly to one of these merge
invariants:

1. **no energization**;
2. **OFF remains available**;
3. **no false safe truth**;
4. **exact evidence**.

The cells are behavior specifications, not line-number or implementation
specifications. P7 may not add, remove, merge, split, or soften a cell. The
coordinator must freeze and record the exact Git blob of this file before
distributing the P7 packet. Any later byte change invalidates the lock and every
review receipt over it. Statuses below describe this authored-against tree.
In-flight lanes satisfy their owed cells in the final candidate evidence packet;
they do not rewrite this catalogue.

## Common acceptance and evidence-attack rules

A genuine RED must execute the production invocation path far enough to
discriminate the mutated behavior from the locked behavior. Import errors,
attribute errors, type errors, collection errors, or fixture-construction errors
caused only by a newly introduced symbol are not valid RED evidence. Nor is a
RED valid when it depends only on a test double returning a shape that
production cannot return. In particular, a bare boolean double cannot stand in
for a typed production receipt or OFF-evidence result.

Every cell also carries an evidence self-attack. Its guard must be challenged by
changing the guard's own policy at the same semantic location so the forbidden
behavior is permitted while syntax, path, and line identity remain as stable as
possible. The cell is not covered if that substitution stays green. This is the
cross-family form of the failures recorded in `docs/CLAIM_CORRECTIONS.md`: a
clean baseline was changed to an accepted violation, a six-method set was cut
to three, and a documentation guard stopped rejecting a class while the
surrounding claim still said it had strengthened. Qualification cells also
receive stale, replayed, and wrong-build receipt self-attacks. A coverage claim
therefore requires both:

- the production-behavior mutation produces the specified RED; and
- the same-location guard-policy substitution cannot preserve a green gate.

A refusal cell is incomplete without its good-case control. A control must use
the same production boundary and prove that valid qualification, exact
identity, or verified OFF remains usable; a permanently refusing system is not
a passing safety system.

## Q — qualification receipt (6)

These cells assume lane P2 supplies one exact typed, freshness-bounded,
single-candidate qualification receipt and makes it a prerequisite for
energizing authority, never for OFF. Lane P3 binds promotion to the exact
qualified artifact/build/tree. Lane P4 supplies the exact configuration,
binding, and hardware-profile digests consumed by that receipt.

### Q1 — missing qualification receipt

- **Invariant:** no energization.
- **Mutation:** an energizing request is admitted when no qualification receipt
  is present, or absence is normalized to an empty/default successful receipt.
- **Observable:** refusal at the arming boundary; no source-start call, no ON
  write, and an explicit qualification-missing reason.
- **Acceptance:** a genuine RED is an admitted energizing request or observed ON
  attempt with the receipt absent. A parser exception or a newly missing
  fixture attribute is not RED.
- **Status:** owed by lane P2.
- **Control:** the same request with one current exact receipt reaches the
  normal arming decision.
- **Evidence self-attack:** replace the guard's required-presence predicate with
  an optional/default predicate at the same semantic site; the guard test must
  fail for the missing-receipt behavior, not for construction.

### Q2 — malformed qualification receipt

- **Invariant:** no energization.
- **Mutation:** a receipt with an extra key, missing key, wrong exact type,
  duplicate semantic field, non-canonical encoding, invalid digest, or
  truthy-but-non-receipt value is accepted.
- **Observable:** refusal naming malformed qualification; no energizing
  authority is created.
- **Acceptance:** each malformed form must reach the production decoder and be
  refused. An `AttributeError` from handing a new object to an old test helper,
  or a bare `True` accepted/rejected only by a double, is not RED.
- **Status:** owed by lane P2.
- **Control:** one canonical typed receipt with the complete exact field set is
  accepted.
- **Evidence self-attack:** narrow the guard's schema/type checks while keeping
  its line and test name stable; the guard must catch the lost rejection.

### Q3 — stale or replayed qualification receipt

- **Invariant:** no energization.
- **Mutation:** an expired receipt, a receipt consumed by an earlier arming
  attempt, or a receipt from a prior process/candidate incarnation authorizes
  the current arming attempt.
- **Observable:** refusal as stale/replayed and no source-start dispatch.
- **Acceptance:** deterministic clock/incarnation control must show that the
  exact previously valid receipt is rejected only after expiry, consumption, or
  incarnation change. Merely corrupting its shape is not this cell's RED.
- **Status:** owed by lane P2.
- **Control:** a fresh, unused receipt for the current incarnation is accepted
  within its freshness budget.
- **Evidence self-attack:** replay a byte-identical formerly valid receipt and
  separately relax the guard's age/incarnation comparison at the same semantic
  site; either escape must make the guard RED.

### Q4 — wrong build or tree

- **Invariant:** exact evidence.
- **Mutation:** a qualification receipt for a different commit, Git tree,
  packaged build, or candidate artifact is accepted for the running candidate.
- **Observable:** receipt invalidation and refusal to arm or promote, with the
  mismatched object identity reported.
- **Acceptance:** use two valid object identities and swap only the receipt
  binding. RED is acceptance of the wrong object, not failure to import the
  alternate build.
- **Status:** owed by lanes P2 and P3.
- **Control:** the same receipt bound to the exact running/promoted
  commit/tree/build is accepted.
- **Evidence self-attack:** present a valid receipt from the immediately prior
  build, then weaken exact object equality to presence/prefix equality at the
  same policy site; the gate must fail.

### Q5 — wrong configuration or binding digest

- **Invariant:** no energization.
- **Mutation:** a receipt remains valid after the applied safety configuration,
  descriptor binding set, or hazard-binding manifest changes.
- **Observable:** receipt invalidation and arming refusal identifying the
  configuration/binding mismatch.
- **Acceptance:** change one behavior-relevant configuration or binding byte
  while preserving a well-formed receipt. A parse failure from making the file
  invalid does not count.
- **Status:** owed by lanes P2 and P4.
- **Control:** byte-identical applied configuration and binding inputs produce
  the expected digest and allow normal arming evaluation.
- **Evidence self-attack:** substitute the guard's exact digest comparison with
  a constant, omitted field, or ambient-current recomputation at the same
  semantic location; the coverage guard must RED.

### Q6 — wrong hardware profile

- **Invariant:** no energization.
- **Mutation:** a qualification receipt for another stand, instrument set,
  output topology, or hazard profile authorizes this hardware profile.
- **Observable:** refusal as hardware-profile mismatch; no ON attempt.
- **Acceptance:** two individually valid profiles must be used, with only the
  profile binding crossed. A rejection caused by an unknown test-only profile
  shape is not RED.
- **Status:** owed by lanes P2 and P4.
- **Control:** the exact declared profile for the active stand and output
  topology is accepted.
- **Evidence self-attack:** replace exact profile equality with a vendor name,
  raw label, prefix, or any-profile-present check at the same policy site; the
  guard must catch the substitution.

## B — binding and ownership (7)

Identity may select an object only when the value came from the authority that
declared that object. It may be compared opaquely for exact equality; its
spelling must not be interpreted as capability or ownership. The locked
hazardous identity is the declared `(instrument_id, emitted_channel, output)`
triple, with the descriptor/binding authority that declared it.

### B1 — instrument authority discarded

- **Invariant:** no energization.
- **Mutation:** ownership comparison drops `instrument_id`, so a foreign
  instrument with an otherwise matching channel/output satisfies a critical
  input or hazardous-source precondition.
- **Observable:** RUN/arming refusal for the foreign reading; no source-start
  dispatch.
- **Acceptance:** a well-formed production reading from a second declared
  instrument must be rejected solely because the instrument owner differs.
- **Status:** owed by lane RUN-authorization-ownership.
- **Control:** the same emitted channel/output from the declaring instrument
  satisfies the precondition.
- **Evidence self-attack:** delete the instrument dimension from the guard's
  expected identity at the same semantic site; the test must fail on false RUN
  authorization, not on tuple arity.

### B2 — emitted-channel equality weakened to spelling inference

- **Invariant:** no energization.
- **Mutation:** exact `emitted_channel` equality is replaced by raw-label,
  substring, prefix, suffix, regex, case-folded, or token-based matching.
- **Observable:** foreign/near-neighbour feedback is refused; if already
  running, loss of exact feedback faults and commands OFF.
- **Acceptance:** a near-neighbour string that contains the expected spelling
  must reach the production matcher and fail ownership while an authority-
  declared rename succeeds.
- **Status:** covered by
  `tests/core/test_safety_heartbeat_identity.py`.
- **Control:** the descriptor-authorized renamed emitted channel remains live.
- **Evidence self-attack:** substitute exact equality with one spelling
  operation at the same guard location; the guard must RED even if the detected
  path and line are unchanged.

### B3 — output ownership discarded or cross-wired

- **Invariant:** no energization.
- **Mutation:** ownership comparison drops `output`, or permits one output's
  feedback/OFF proof to satisfy another output.
- **Observable:** the unsatisfied output blocks RUN or causes fault/OFF; the
  sibling output's evidence is not consumed for it.
- **Acceptance:** one production-shaped feedback item whose text mentions both
  output names must not satisfy two active outputs.
- **Status:** covered by
  `tests/core/test_safety_heartbeat_identity.py` and
  `tests/core/test_safety_dual_channel.py`.
- **Control:** one exact declared feedback item per active output keeps the
  system running; legitimate channel-scoped stop leaves the other output's
  ownership intact.
- **Evidence self-attack:** collapse per-output expected identities into a
  shared set at the same semantic site; the guard must fail on the unsatisfied
  output rather than on fixture shape.

### B4 — foreign heartbeat suppresses emergency OFF

- **Invariant:** OFF remains available.
- **Mutation:** a foreign instrument whose channel merely contains a hazardous
  output spelling refreshes that output's heartbeat and suppresses the
  stale-heartbeat fault/OFF trigger.
- **Observable:** transition to fault, exactly one global OFF request, and
  removal of active-source truth when only foreign feedback is fresh.
- **Acceptance:** this branch's original defect shape must reproduce with a
  production `Reading`: foreign `instrument_id`, near-matching channel text,
  and no exact owner feedback. RED is continued RUNNING or zero OFF calls.
- **Status:** covered by
  `tests/core/test_safety_heartbeat_identity.py`.
- **Control:** exact declared feedback for each active output remains RUNNING
  with no OFF call.
- **Evidence self-attack:** change the guard from exact triple ownership back to
  substring/regex membership at the same semantic location; the test must fail.

### B5 — critical-input owner reduced to raw channel spelling

- **Invariant:** no energization.
- **Mutation:** RUN preconditions, stale/status checks, or rate checks discard
  the critical reading's instrument owner and accept a foreign fresh reading
  with the same raw/canonical channel label.
- **Observable:** the foreign input remains an explicit missing/foreign
  blocker; RUN is refused. While running, substitution cannot suppress the
  required fault/OFF.
- **Acceptance:** exercise both directions with production readings: a foreign
  fresh value cannot authorize RUN, and it cannot keep the owner stale check
  healthy.
- **Status:** owed by lane RUN-authorization-ownership.
- **Control:** the exact declared critical-input owner can authorize the
  otherwise qualified RUN and remains valid through stale/status/rate checks.
- **Evidence self-attack:** preserve the raw channel key while replacing the
  owner-qualified comparison with raw-label lookup at the same site; both the
  false-positive RUN and false-negative OFF variants must be caught.

### B6 — descriptor accepted without declaring authority

- **Invariant:** no false safe truth.
- **Mutation:** a self-consistent foreign, ambient, or first-arriving descriptor
  is treated as authoritative without exact resolution through the frozen
  hazard/descriptor manifest.
- **Observable:** refusal to grant specialist, critical, heartbeat, or output
  ownership; startup/qualification fails on an unbound descriptor.
- **Acceptance:** use two valid descriptors with the same public channel id but
  different declaring identity. RED is acceptance of the foreign descriptor,
  not schema rejection.
- **Status:** owed by lane P4.
- **Control:** the manifest-resolved canonical descriptor is accepted, and
  ordinary non-hazard presentation remains available where its own contract
  permits it.
- **Evidence self-attack:** replace canonical descriptor equality with
  `channel_id` equality or first-arrival authority at the same policy site; the
  guard must fail.

### B7 — missing, duplicate, ambiguous, or cross-output binding accepted

- **Invariant:** no energization.
- **Mutation:** startup accepts no binding, duplicate bindings, one binding
  claimed by multiple outputs, or a binding owned by a foreign reviewed source.
- **Observable:** startup/qualification refusal naming the missing, ambiguous,
  cross-output, or foreign association before acquisition can grant RUN.
- **Acceptance:** each invalid association must remain schema-valid and reach
  production liveness/binding validation. A YAML/parser failure is not RED.
- **Status:** covered by
  `tests/core/test_safety_heartbeat_identity.py` and
  `tests/core/test_startup_safety_liveness_gate.py`.
- **Control:** one unambiguous declared binding per required output validates
  cleanly.
- **Evidence self-attack:** shrink the invalid-association method set or change
  the accepted baseline at the same semantic site; the guard must report the
  lost case.

## E — OFF triggers (8)

Each cell here asks whether the triggering condition reaches the fault/OFF
decision. Delivery after that decision is owned by D1-D7.

### E1 — explicit emergency-OFF request becomes state-only

- **Invariant:** OFF remains available.
- **Mutation:** an explicit emergency-OFF request changes software state or
  returns success without invoking the hazardous-source OFF owner.
- **Observable:** the production driver OFF path is invoked; verified failure
  latches fault rather than claiming SAFE_OFF.
- **Acceptance:** RED is a missing OFF invocation, success without verified
  evidence, or safe state after unverified OFF. A mock method-name mismatch is
  not RED.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** verified OFF reaches the expected non-energized lifecycle without
  a false fault.
- **Evidence self-attack:** replace the guard's driver-call/evidence assertion
  with state-name-only success at the same site; the mutation must be caught.

### E2 — hard interlock trip does not request fault/OFF

- **Invariant:** OFF remains available.
- **Mutation:** a configured hard interlock threshold trips locally but its
  emergency action is dropped, downgraded, or treated as an ordinary stop.
- **Observable:** interlock trip context reaches SafetyManager, fault latches,
  and the emergency-OFF action is requested.
- **Acceptance:** a production-bound canonical reading beyond the configured
  threshold must exercise the real action dispatcher. Directly calling the
  callback is not RED evidence.
- **Status:** covered by
  `tests/core/test_interlock_action_dispatch.py` and
  `tests/core/test_interlock_descriptor_canonical.py`.
- **Control:** a safe-side reading does not trip; a configured soft
  `stop_source` action retains its intentionally non-latching semantics when
  OFF is verified.
- **Evidence self-attack:** change the action mapping or default at the same
  semantic location while retaining the interlock name; the guard must fail.

### E3 — critical-input silence/staleness does not fault

- **Invariant:** OFF remains available.
- **Mutation:** a required critical input can age past its stale deadline while
  RUNNING without fault and OFF.
- **Observable:** stale-input fault, emergency-OFF request, and no continued
  RUNNING truth.
- **Acceptance:** deterministic clock control must cross the deployed freshness
  boundary with the real monitor active. Deleting the input field from a helper
  is not RED.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** fresh exact-owner input remains non-faulting; outside RUNNING the
  same absence blocks readiness rather than inventing a running fault.
- **Evidence self-attack:** relax the age comparison, monitored-state set, or
  required-input set at the same policy site; the guard must catch continued
  RUNNING.

### E4 — invalid/non-usable critical evidence is treated as healthy

- **Invariant:** OFF remains available.
- **Mutation:** NaN, infinity on the non-trip side, error status, timeout, or
  persistent non-usable critical evidence is accepted as a healthy value.
- **Observable:** explicit blocker before RUN or debounced fault/OFF while
  RUNNING, according to the production contract.
- **Acceptance:** use production `Reading` status/value combinations. RED is
  continued authority after the required debounce, not a float conversion
  exception.
- **Status:** covered by `tests/core/test_safety_fixes.py` and
  `tests/core/test_interlock_nan_debounce.py`.
- **Control:** finite `OK` evidence follows normal threshold behavior and resets
  the non-usable debounce where specified.
- **Evidence self-attack:** delete a status/non-finite case from the guard's
  method set at the same site; the missing case must turn the guard RED.

### E5 — critical rate-of-change hazard does not fault

- **Invariant:** OFF remains available.
- **Mutation:** the rate estimator ignores or misclassifies an exact-owner
  critical temperature whose deployed rate limit is exceeded.
- **Observable:** rate fault latches and emergency OFF is requested within the
  bounded monitor window.
- **Acceptance:** feed timestamped production readings through the real rate
  path. Direct mutation of a cached rate or a test-only non-temperature shape
  is not RED.
- **Status:** covered by `tests/core/test_safety_fixes.py` and
  `tests/core/test_safety_manager.py`.
- **Control:** safe-rate critical temperature and non-critical/non-temperature
  channels do not spuriously fault.
- **Evidence self-attack:** remove one critical-owner/rate predicate while
  keeping the test location stable; the guard must fail on missing fault/OFF.

### E6 — hazardous-output heartbeat loss does not fault

- **Invariant:** OFF remains available.
- **Mutation:** an active hazardous output loses its exact declared feedback,
  but the monitor remains RUNNING or accepts unrelated traffic as liveness.
- **Observable:** heartbeat fault, one global OFF request, and cleared active
  source truth.
- **Acceptance:** stop only the exact owner's feedback while continuing
  unrelated valid traffic. RED is continued RUNNING or no OFF.
- **Status:** covered by
  `tests/core/test_safety_heartbeat_identity.py`.
- **Control:** exact declared feedback per active output stays RUNNING.
- **Evidence self-attack:** replace exact feedback population with any
  keithley-like/raw-label population at the same semantic site; the guard must
  fail.

### E7 — safety evidence overflow is warning-only

- **Invariant:** OFF remains available.
- **Mutation:** required safety-broker overflow drops evidence but emits only a
  warning or continues as healthy instead of faulting.
- **Observable:** overflow reaches SafetyManager, fault latches, and OFF is
  requested.
- **Acceptance:** overflow the real bounded safety queue through its production
  callback. Directly invoking `_fault()` or returning a test-only overflow
  token is not RED.
- **Status:** covered by `tests/core/test_safety_manager.py` and
  `tests/core/test_safety_broker_maxsize.py`.
- **Control:** ordinary bounded traffic does not fault and remains fully
  evaluable.
- **Evidence self-attack:** downgrade or detach the overflow callback at the
  same policy site; the guard must fail on continued authority.

### E8 — supervised safety-owner death does not trigger fault/OFF

- **Invariant:** OFF remains available.
- **Mutation:** a required monitor/driver child dies during ready, RUN, or
  in-flight start, but its prior authority remains current and OFF is not
  requested.
- **Observable:** readiness/authority revocation before reuse; during energetic
  or in-flight state, fault and retained OFF settlement.
- **Acceptance:** terminate the real owned task at the race boundary. Merely
  setting a `connected=False` double is not this cell's RED.
- **Status:** covered by
  `tests/core/test_safety_operator_snapshot_owner.py`.
- **Control:** expected orderly stop settles children and invalidates readiness
  without manufacturing a failure.
- **Evidence self-attack:** remove the done-owner check or keep the prior
  snapshot current at the same semantic site; the guard must fail.

## D — OFF delivery (7)

These cells begin after an OFF/stop trigger exists. They ask whether the
hardware-safe path remains reachable and settles truthfully.

### D1 — qualification interlock blocks OFF

- **Invariant:** OFF remains available.
- **Mutation:** missing, stale, malformed, or mismatched qualification blocks
  emergency OFF, stop, shutdown OFF, or OFF verification along with energizing
  commands.
- **Observable:** OFF dispatch proceeds on the dedicated safe authority while
  ordinary/energizing requests remain refused.
- **Acceptance:** an unqualified production composition must still reach the
  hardware OFF owner. RED is refusal/delay of OFF, not merely the expected
  refusal of ON.
- **Status:** owed by lane P2.
- **Control:** qualification refusal continues to block every energizing
  request; valid qualification does not change OFF semantics.
- **Evidence self-attack:** move the qualification dependency above the common
  command dispatcher so it captures OFF at the same semantic site; the guard
  must fail.

### D2 — ordinary command blockage queues or suppresses OFF

- **Invariant:** OFF remains available.
- **Mutation:** a blocked, timed-out, saturated, or quarantined ordinary command
  lane prevents dedicated global OFF or launcher shutdown OFF from dispatching.
- **Observable:** dedicated safe ingress dispatches global OFF within its
  hardware-safe timeout while ordinary mutations remain quarantined.
- **Acceptance:** block the real ordinary REP/handler path and send OFF through
  the production safe endpoint. A helper that bypasses transport is not RED
  evidence.
- **Status:** covered by
  `tests/core/test_zmq_command_server_supervision.py`.
- **Control:** ordinary mutations remain rejected during quarantine, while
  permitted read-only queries retain their specified behavior.
- **Evidence self-attack:** route safe actions back through the ordinary queue
  at the same composition site; the real blocked-REP guard must fail.

### D3 — in-flight ON/start outruns triggered OFF

- **Invariant:** no energization.
- **Mutation:** cancellation or an OFF request during an in-flight source start
  allows a later ON/config write or a RUN success receipt after OFF has claimed
  authority.
- **Observable:** start owner settles, full OFF completes, and no RUN receipt or
  late ON write appears.
- **Acceptance:** inject cancellation/OFF at every production write boundary.
  A test that cancels before dispatch only is insufficient.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** an uninterrupted qualified start completes and publishes RUN
  only after its required hardware evidence.
- **Evidence self-attack:** remove one post-await authority recheck at the same
  semantic site; the corresponding boundary case must turn RED.

### D4 — transport quarantine obstructs or forges OFF

- **Invariant:** OFF remains available.
- **Mutation:** query desynchronization blocks OFF writes, permits ordinary
  traffic during quarantine, or lets delayed bytes satisfy a new OFF proof.
- **Observable:** OFF-only recovery traffic is issued; ordinary traffic stays
  blocked; stale/delayed replies cannot create verified-OFF evidence.
- **Acceptance:** exercise the real transport command/reply sequence and delayed
  bytes. A double returning a boolean OFF result is not RED evidence.
- **Status:** covered by
  `tests/drivers/test_keithley_connect_safety.py` and
  `tests/drivers/test_keithley_disconnect_verified_off.py`.
- **Control:** a clean current-generation OFF write plus exact fresh readback
  produces device-reported OFF.
- **Evidence self-attack:** allow a legacy zero, prior nonce, or delayed queue
  reply at the same proof site; the guard must fail.

### D5 — global OFF skips a declared output

- **Invariant:** no energization.
- **Mutation:** global OFF uses active bookkeeping, a default output, or one
  successful channel proof and therefore skips another declared hazardous
  output.
- **Observable:** OFF writes/readbacks cover every declared output; one unknown
  or ON result makes global OFF unverified.
- **Acceptance:** both-output production behavior must be observed, including
  the partial-success case. Counting calls on a one-output fake is not RED.
- **Status:** covered by `tests/core/test_safety_dual_channel.py`,
  `tests/drivers/test_keithley_dual_channel.py`, and
  `tests/drivers/test_keithley_connect_safety.py`.
- **Control:** channel-scoped stop affects only its target, while global OFF
  covers both.
- **Evidence self-attack:** replace the declared-output iteration with
  active-set/default-output iteration at the same policy site; the guard must
  fail.

### D6 — caller cancellation abandons the OFF owner

- **Invariant:** OFF remains available.
- **Mutation:** cancelling one waiter cancels, loses, duplicates, or falsely
  completes the shared hardware OFF owner.
- **Observable:** the exact owner remains retained until terminal settlement;
  all waiters receive the same verified result or fail-closed outcome.
- **Acceptance:** cancel and repeatedly cancel waiters after OFF dispatch, at
  multiple hardware await boundaries. Pre-dispatch cancellation alone is not
  sufficient.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** concurrent uncancelled OFF callers share one driver owner and a
  later independent OFF request receives a fresh owner.
- **Evidence self-attack:** remove shielding/retention or reuse a settled owner
  at the same site; the guard must fail on ownership truth.

### D7 — teardown destroys the OFF path before exact settlement

- **Invariant:** OFF remains available.
- **Mutation:** launcher/engine teardown closes command transport, releases
  process ownership, or force-reaps the child before exact verified-OFF receipt
  and owner settlement.
- **Observable:** HOLD retains the command/process path until exact receipt and
  clean exit; unverified OFF never creates a shutdown-complete receipt.
- **Acceptance:** use the real launcher/engine process boundary. Receipt without
  exit, exit without receipt, malformed receipt, and timed-out child must remain
  HOLD.
- **Status:** covered by
  `tests/integration/test_launcher_shutdown_ownership.py`,
  `tests/test_launcher_shutdown_ownership.py`, and
  `tests/core/test_zmq_command_server_supervision.py`.
- **Control:** exact shutdown receipt plus clean process exit releases the
  owner.
- **Evidence self-attack:** weaken the release predicate to receipt-only,
  exit-only, or truthy result at the same policy site; the guard must fail.

## R — races and ordering (7)

Every R cell requires at least 100 iterations on native Windows and at least
100 iterations on real Linux. One passing iteration is not evidence. WSL is
installed; the available distributions are `Ubuntu`, `Ubuntu-22.04`,
`CryoDAQ-Ubuntu`, and `CryoDAQ-Debian`. P7 uses `Ubuntu` unless the evidence
packet records another real-Linux runner. Its current `python3` is 3.12.3 and
does not have pytest, so the runner must first create an isolated environment
and install the repository's pinned/runtime test dependencies, including
pytest. Absence of that preparation is an open gate, not a product result.

For each named node below, native Windows uses the repository interpreter with
`PYTHONPATH` set to the exact candidate's `src` and a unique `--basetemp` per
iteration. Real Linux is invoked in this form, with the node and basetemp
substituted and all output passed through NUL removal:

```text
wsl -d Ubuntu -- bash -lc "cd /mnt/c/tmp/p6-catalogue && export PYTHONPATH=\$PWD/src; for i in \$(seq 1 100); do python3 -m pytest -q '<node>' --basetemp /tmp/cryodaq-p7-<cell>-\$i || exit 1; done 2>&1 | tr -d '\0'"
```

The final P7 command must substitute the frozen candidate path if it is not
`C:\tmp\p6-catalogue`. Each iteration must reach the production concurrency
boundary; looping a structural/helper-only assertion does not satisfy the
cell.

### R1 — concurrent global OFF requests split ownership

- **Invariant:** OFF remains available.
- **Mutation:** simultaneous global OFF requests create competing hardware
  owners, duplicate writes, cross-attribute results, or allow one waiter to
  cancel the shared operation.
- **Observable:** one exact hardware owner, one terminal evidence result shared
  consistently, and no abandoned waiter.
- **Acceptance:** RED is duplicate/contradictory ownership or lost settlement
  under synchronized concurrent entry, not an incidental timeout from an
  undersized test deadline.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** after settlement, a later independent OFF request creates a
  fresh owner rather than reusing the terminal one.
- **Evidence self-attack:** replace the shared-owner/lock assertion with
  per-caller success at the same semantic site; the guard must fail.
- **Execution:** run
  `tests/core/test_safety_manager.py::test_simultaneous_global_off_requests_share_one_driver_owner`
  and the cancelled-waiter companion for **at least 100 iterations on native
  Windows and at least 100 on real Linux** using the family commands above.

### R2 — cancellation races an in-flight start

- **Invariant:** no energization.
- **Mutation:** cancellation at a start/config/write/readback boundary permits a
  late ON write, commits RUN after OFF, or returns before the hardware owner
  settles.
- **Observable:** no late ON, no RUN receipt, full OFF settlement, and retained
  uncertain truth until settlement.
- **Acceptance:** the race must be synchronized at production await/write
  boundaries; probabilistic sleeps alone are insufficient.
- **Status:** covered by `tests/core/test_safety_manager.py`.
- **Control:** an uninterrupted qualified start reaches RUN once with exact
  evidence.
- **Evidence self-attack:** remove one authority recheck/cancellation shield at
  the same policy site; the corresponding synchronized case must fail.
- **Execution:** run
  `tests/core/test_safety_manager.py::test_cancelled_start_settles_before_full_off_at_every_write_boundary`
  for **at least 100 iterations on native Windows and at least 100 on real
  Linux** using the family commands above.

### R3 — shutdown races queued output mutation

- **Invariant:** no energization.
- **Mutation:** an output mutation received or queued around shutdown admission
  executes after shutdown has claimed authority.
- **Observable:** shutdown latch wins; queued/later mutation is refused before
  handler dispatch, while global OFF still executes.
- **Acceptance:** synchronize receipt, queueing, and admission cut through the
  real command server. A direct call after a pre-set boolean is not enough.
- **Status:** covered by
  `tests/core/test_zmq_command_server_supervision.py`.
- **Control:** a mutation fully admitted before shutdown follows its exact
  settlement contract and cannot be silently reclassified as not dispatched.
- **Evidence self-attack:** move the shutdown-latch check after handler dispatch
  at the same semantic site; the guard must fail.
- **Execution:** run
  `tests/core/test_zmq_command_server_supervision.py::test_real_server_shutdown_latch_rejects_queued_output_mutation`
  for **at least 100 iterations on native Windows and at least 100 on real
  Linux** using the family commands above.

### R4 — reconnect/replacement accepts stale generation authority

- **Invariant:** no energization.
- **Mutation:** a prior generation's callback, task completion, reply, or
  receipt restores readiness or invalidates/replaces a newer owner after
  reconnect.
- **Observable:** old-generation evidence is ignored for current authority;
  replacement waits for old-owner settlement and requires fresh identity/OFF
  proof.
- **Acceptance:** use two real owner generations and deliver the old event after
  the new generation exists. Merely comparing generation integers in a helper
  is not RED evidence.
- **Status:** covered by
  `tests/core/test_safety_operator_snapshot_owner.py` and
  `tests/gui/test_zmq_client_shutdown.py`.
- **Control:** current-generation callback/receipt updates current authority
  once the predecessor has exactly settled.
- **Evidence self-attack:** drop the generation comparison at the same policy
  site; the delayed old callback must turn the guard RED.
- **Execution:** run
  `tests/core/test_safety_operator_snapshot_owner.py::test_prior_generation_done_callback_cannot_invalidate_restarted_children`
  and the reconnect/replacement companion for **at least 100 iterations on
  native Windows and at least 100 on real Linux** using the family commands
  above.

### R5 — quarantine accepts a late reply as current proof

- **Invariant:** no false safe truth.
- **Mutation:** a delayed pre-quarantine/pre-reconnect reply satisfies a later
  query or OFF proof and clears quarantine/current uncertainty.
- **Observable:** delayed bytes remain attributed to the old nonce/generation;
  current OFF stays unknown until fresh exact proof.
- **Acceptance:** the delayed reply must traverse the production transport
  sequence. Supplying a stale return value directly from a fake method is not
  RED.
- **Status:** covered by
  `tests/drivers/test_keithley_connect_safety.py`.
- **Control:** a fresh unique-nonce current-generation query proves OFF and
  permits the specified recovery.
- **Evidence self-attack:** accept one-behind or prior-process nonce evidence at
  the same proof site; the guard must fail.
- **Execution:** run
  `tests/drivers/test_keithley_connect_safety.py::test_one_behind_stale_queue_never_proves_off`
  and the prior-process replay companion for **at least 100 iterations on
  native Windows and at least 100 on real Linux** using the family commands
  above.

### R6 — safety queue saturation erases a transient hazard

- **Invariant:** OFF remains available.
- **Mutation:** concurrent/saturated publication evicts or reorders a transient
  hazardous sample so later safe samples erase it before evaluation.
- **Observable:** the hazardous sample is evaluated or the fail-loud overflow
  path faults and requests OFF; silent continuation is forbidden.
- **Acceptance:** drive the real bounded safety path at its saturation boundary
  with a synchronized hazardous item. Direct overflow-callback invocation is
  not RED evidence.
- **Status:** covered for fail-loud overflow by
  `tests/core/test_safety_broker_maxsize.py` and
  `tests/core/test_safety_manager.py`.
- **Control:** high-volume traffic within capacity preserves order and does not
  spuriously fault.
- **Evidence self-attack:** restore drop/continue behavior or detach the
  overflow-to-fault callback at the same semantic site; the guard must fail.
- **Execution:** run the production saturation nodes in
  `tests/core/test_safety_broker_maxsize.py` plus
  `tests/core/test_safety_manager.py::test_broker_overflow_triggers_fault` for
  **at least 100 iterations on native Windows and at least 100 on real Linux**
  using the family commands above.

### R7 — shutdown, child death, and retained settlement interleave

- **Invariant:** exact evidence.
- **Mutation:** simultaneous shutdown/child death/cancellation releases process
  or safety ownership, emits shutdown complete, or closes transport before all
  exact owners settle.
- **Observable:** deterministic HOLD until every required owner and exact OFF
  receipt settles; no false complete receipt.
- **Acceptance:** exercise real tasks/processes and transport identity. Equal
  exit codes or helper-level task completion are not proof of identical
  settlement.
- **Status:** covered by
  `tests/integration/test_launcher_shutdown_ownership.py`,
  `tests/test_launcher_shutdown_ownership.py`, and
  `tests/core/test_shutdown_settlement.py`.
- **Control:** exact verified-OFF receipt plus clean terminal owners releases
  once, without permanent HOLD.
- **Evidence self-attack:** reduce the all-owner predicate to first-completed,
  process-exited, or receipt-present at the same semantic site; the guard must
  fail.
- **Execution:** run
  `tests/integration/test_launcher_shutdown_ownership.py::test_real_launcher_shutdown_settles_every_owner_before_releasing_lock`
  and the simultaneous-settlement companions for **at least 100 iterations on
  native Windows and at least 100 on real Linux** using the family commands
  above.

## T — operator and evidence truth (5)

### T1 — unknown or unverified state is presented as safe

- **Invariant:** no false safe truth.
- **Mutation:** unknown, disconnected, stale, active, faulted, or
  physical-state-unknown evidence is rendered/published as safe or verified
  OFF.
- **Observable:** explicit unknown/blocked/disconnected/fault truth with no
  optimistic safe/verified flag.
- **Acceptance:** production snapshot/result types must cross the real owner and
  presentation boundary. A newly added enum missing from an old test double is
  not RED.
- **Status:** covered by
  `tests/engine_wiring/test_operator_safety_snapshot.py`,
  `tests/core/test_source_off_result_consumers.py`, and
  `tests/gui/shell/test_main_window_v2_safety_staleness.py`.
- **Control:** exact device-reported OFF with all readiness conditions may
  render the narrowly earned safe/ready truth; it is not represented as
  independent physical proof.
- **Evidence self-attack:** change pessimistic unknown mapping to the safe
  default at the same policy site; the guard must fail.

### T2 — absence from bookkeeping is presented as OFF

- **Invariant:** no false safe truth.
- **Mutation:** a hazardous output absent from an active-source set, cache, or
  latest reading is published/rendered as OFF without per-output OFF evidence.
- **Observable:** `unknown`, not `off`, for the absent output; no fabricated
  zero/verified flag.
- **Acceptance:** remove only the bookkeeping entry while keeping output truth
  unobserved. RED is an OFF claim, not a missing widget attribute.
- **Status:** covered by
  `tests/core/test_keithley_channel_state_publish.py` and
  `tests/gui/shell/overlays/test_keithley_panel.py`.
- **Control:** exact current per-output device-reported OFF renders OFF without
  claiming independent physical verification.
- **Evidence self-attack:** restore the empty-active-set-to-OFF shortcut at the
  same semantic site; the guard must fail.

### T3 — ready or qualified is inferred rather than earned

- **Invariant:** no false safe truth.
- **Mutation:** readiness or qualification becomes true from lifecycle name,
  connected status, defaults, cached prior receipt, empty blockers, or
  self-assertion without current exact OFF, owner, configuration, profile, and
  candidate evidence.
- **Observable:** explicit blocked/unqualified status with bounded reasons;
  energizing controls/requests remain disabled/refused.
- **Acceptance:** remove each required fact independently through the production
  authority boundary. A constructor failure from a newly required field is not
  RED.
- **Status:** owed by lanes P2 and P3; current readiness controls are covered by
  `tests/core/test_safety_operator_snapshot_owner.py` and
  `tests/engine_wiring/test_operator_safety_snapshot.py`.
- **Control:** the complete current exact fact set earns ready/qualified and
  permits the normal arming decision.
- **Evidence self-attack:** change the required-fact conjunction to any
  optimistic subset at the same policy site; both status and energizing
  authority guards must fail.

### T4 — applied or complete is claimed from acceptance/proxy evidence

- **Invariant:** exact evidence.
- **Mutation:** command acceptance, write acknowledgement, HTTP success,
  process exit, test exit zero, generated artifact presence, or pre-run hash is
  reported as applied/complete without the terminal evidence the claim
  requires.
- **Observable:** explicit accepted/pending/unknown/failed status until exact
  applied or complete receipt; required-status failure for incomplete merge
  evidence.
- **Acceptance:** keep the proxy success while withholding terminal evidence.
  RED is the false applied/complete claim, not a new result-field
  `AttributeError` or production-impossible double.
- **Status:** covered by
  `tests/core/test_startup_safety_liveness_gate.py`,
  `tests/test_ci_candidate_evidence.py`, and
  `tests/core/test_zmq_command_server_supervision.py`.
- **Control:** exact applied snapshot/terminal send/execution receipt earns the
  corresponding narrow claim.
- **Evidence self-attack:** weaken the terminal-evidence predicate to a proxy at
  the same semantic site; the guard must fail even when the message/test name
  remains unchanged.

### T5 — required active warning is silently cleared or suppressed

- **Invariant:** no false safe truth.
- **Mutation:** an active required CRITICAL warning clears, disappears, or is
  represented as resolved when its input becomes missing/unusable or its
  evaluator/transport fails.
- **Observable:** the warning remains active with unknown/unavailable evidence,
  or an equally prominent explicit degradation replaces it; no all-clear is
  emitted.
- **Acceptance:** first activate the real warning, then remove/corrupt the
  evidence through the production evaluator. An inactive alarm that simply
  does not fire is a different behavior and not this cell's RED.
- **Status:** covered by `tests/core/test_alarm_v2.py` and
  `tests/core/test_alarm_v2_integration.py`.
- **Control:** authoritative safe-side recovery clears the warning through the
  normal hysteresis/recovery contract.
- **Evidence self-attack:** change missing/error evaluation from hold-active to
  clear at the same semantic site; the guard must fail on false all-clear.

## G — merge-evidence substrate (2)

### G1 — mutate, execute, restore preserves candidate evidence

- **Invariant:** exact evidence.
- **Mutation:** after candidate identity is frozen, mutate an executed required
  guard at the same semantic location so it permits its forbidden behavior,
  run the gate, restore the original bytes before post-run hash/clean checks,
  and still obtain valid candidate evidence.
- **Observable:** candidate receipt invalidation or required-status failure that
  specifically identifies missing in-execution integrity; the restored final
  hash must not rehabilitate the run.
- **Acceptance:** the mutation must be syntactically valid, collect normally,
  and allow the selected tests/validators to execute. The mutation should be
  capable of making the guarded unsafe behavior pass, then be byte-restored.
  A RED caused by syntax/import failure, or by the mutated test itself failing,
  does not prove this cell.
- **Status:** owed by lane G1.
- **Control:** a byte-stable candidate executes the same gates and produces a
  valid exact-object receipt.
- **Evidence self-attack:** this cell is itself the same-line policy
  substitution attack. Repeat it against more than one guard shape, including
  an accepted-baseline set and a method-set predicate, so the integrity
  mechanism is not proved by one file-specific watch.

### G2 — omitted/inactive validator or zero-collected partition passes

- **Invariant:** exact evidence.
- **Mutation:** remove a required validator from active workflow wiring, mark it
  inactive/deselected/skipped while retaining its file/registry entry, or run a
  declared CI partition that collects zero tests and exits successfully; the
  candidate still receives passed/complete status.
- **Observable:** required-status failure naming the omitted/inactive validator
  or zero-collected partition; no complete candidate receipt.
- **Acceptance:** exercise the production workflow-equivalent runner and
  required-status aggregation. A synthetic unit call to a validator that the
  workflow never invokes is not enough. Zero collection must be an otherwise
  valid pytest invocation, not an import/collection crash.
- **Status:** owed by lanes G2 and P8.
- **Control:** every declared required validator is actively invoked and
  collected, every declared partition collects a positive expected population,
  and the exact completed set earns passed status.
- **Evidence self-attack:** edit the validator/partition inventory predicate at
  the same semantic location so the omitted item or zero population is treated
  as acceptable; the gate must still fail from an independent required-status
  boundary.

## Minimum contracts assumed from in-flight lanes

The catalogue does not prescribe their mechanisms. It assumes only:

- **P2 — arming interlock:** one exact typed, freshness-bounded,
  current-incarnation qualification receipt gates all energizing authority;
  missing/malformed/stale/mismatched evidence refuses; OFF/stop/shutdown OFF
  never depends on qualification; a fully valid receipt has an accept control.
- **P3 — packaging/promotion boundary:** qualification and promotion bind the
  exact commit, tree, packaged build/artifact, and terminal promotion result;
  an unqualified or differently bound artifact cannot be promoted.
- **P4 — hazard manifest:** one frozen, bounded, unambiguous authority declares
  hardware profile, instrument, emitted channel, output, critical input,
  descriptor, and behavior-relevant configuration/binding digests; absence,
  ambiguity, duplication, or foreign ownership fails closed.
- **P8 — partition-execution proof:** the candidate declares every required CI
  partition and its expected positive collected population, records actual
  collection and terminal execution, and fails required status for missing,
  inactive, skipped, deselected, zero-collected, or incomplete partitions.
- **G1 — evidence immutability:** executed candidate/guard bytes have integrity
  evidence covering the whole execution interval; mutate-execute-restore
  invalidates the receipt independently of final cleanliness.
- **G2 — validator wiring:** every required validator is active on the default
  candidate path, its execution is represented in required status, and omission
  or inactivity cannot be normalized to pass.
- **RUN-authorization-ownership:** every critical-input precondition, stale,
  status, and rate decision retains exact declared owner identity; foreign,
  missing, duplicate, ambiguous, and cross-output evidence cannot authorize RUN
  or suppress fault/OFF.

## Coverage ledger at the authored-against tree

“Covered” means a real production-path regression exists at this head. It does
not claim that the final candidate, the required R-family repetitions, hosted
CI, packaging, WSL/Linux, Windows, or physical hardware gates have passed.

- **Covered by existing tests (29):** B2-B4, B7; E1-E8; D2-D7; R1-R7;
  T1-T2, T4-T5.
- **Owed by named lanes (13):** Q1-Q6; B1, B5-B6; D1; T3; G1-G2.
- **Not yet covered without a named owner:** none.

All fixed family counts were filled with distinct reachable behaviors; no cell
was added merely to reach 42.

## Blind spots and required human work

This is a bounded catalogue, not a completeness proof. Its known blind spots
are part of the lock:

- A novel defect may fall outside all 42 mutations. It counts in P7 only when
  exact evidence maps it directly to a merge invariant. Reviewers must perform
  a breadth pass rather than searching only for the named examples.
- Single mutations do not exhaust compound failures, correlated Byzantine
  evidence, or two individually safe changes whose composition is unsafe.
  Humans must inspect authority composition, not only mutation score.
- Software cannot establish independent physical OFF, correct wiring, correct
  sensor placement, final-element action, trip time, or suitability of a
  threshold/profile. Those remain human laboratory gates in
  `docs/lab_verification_checklist.md`.
- A mutation test proves that one oracle notices one change; it does not prove
  the oracle is the correct hazard requirement. A safety owner must review the
  manifest/profile and the good-case controls.
- Production-unreachable doubles, especially bare booleans or ad hoc receipt
  shapes, can manufacture RED or green. Reviewers must trace each case through
  the real decoder, owner, transport, and status boundary.
- Same-line substitution attacks do not exhaust dynamic import, reflection,
  generated code, alias flow, non-Python assets, environment-conditioned paths,
  or changes outside the scanner root. Human breadth review must inspect the
  exact frozen diff and workflow, not trust a path/line inventory.
- The R cells do not cover every scheduler or kernel interleaving. The required
  100+100 repetitions are a floor, not proof of race absence; reviewers must
  inspect synchronization and ownership structure.
- The lock is authored before dependent lanes land. Their evidence can satisfy
  owed cells, but a changed contract that no longer meets the minimum assumptions
  is a blocker, not permission to reinterpret a cell.
- The catalogue itself can be attacked. P7 must compare the exact frozen blob,
  all 42 IDs, field presence, family counts, statuses, and controls before
  accepting review evidence. A reordered or softened catalogue is a new object
  and voids the round.

## First adversarial target

The first attack should be **G1**. A same-line policy substitution inside a
required guard, followed by execute and byte-for-byte restore, can make every
downstream cell appear green while leaving the final tree and post-run hash
unchanged. If G1 is not independently sealed, the catalogue can bound the
questions but cannot establish that the executed candidate or guards were the
locked object.
