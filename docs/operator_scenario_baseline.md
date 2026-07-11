# F36.0 operator-task and evidence baseline

Status: baseline contract only; no UI conformance or operator-performance claim
Fixture: `tests/fixtures/f36_operator_scenarios_v1.json`
Contract test: `tests/test_f36_operator_scenario_contract.py`

## Purpose

F36.0 freezes twelve deterministic operator questions before the operating
surface changes. Each scenario defines the backend truth an operator starts
from, the task they must complete, the truth/reason/action that must remain
visible, and the false safe/ready/recording answers that are forbidden.

The fixture is reusable for current-UI baseline observation, future prototype
tests, replay, keyboard/accessibility review, and final F36 acceptance. It does
not assert that the current GUI passes. Human context, accessibility,
performance, timings, errors, task success and false presentations are all
deliberately `null`/empty until an observed session fills the versioned
per-scenario evidence template.

## Safety and authority boundary

- No scenario requires real hazardous actuation.
- Scenario actions are observation, navigation, acknowledgement requests,
  documented recovery preparation, handover, replay, or evidence capture.
- Alarm acknowledgement and SafetyManager recovery remain distinct tasks.
- The fixture never grants the GUI safety authority and never treats a local
  green presentation as proof of safe, ready, or recording truth.
- Unknown or stale authority must be shown as `stale` or `disconnected`, never
  optimistically converted to `ok`.
- In `f36.operator.unsafe_preconditions`, verified-OFF is explicitly confirmed
  while `safe_off` remains authoritative. Readiness is blocked by the distinct
  current non-output check `keithley_not_connected` (`SafetyManager` reason:
  `Keithley not connected`); the scenario never
  combines unsatisfied verified-OFF with a claimed `safe_off` state.

Each scenario also freezes an `allowed_interaction_class` and
`authority_boundary`. The only classes in this baseline are observation, a
confirmed local-process restart, alarm-ack request, safety-ack request,
handover-note write, and bounded support capture. Source start/stop/set/reset,
health-driven correction, and automatic correction are prohibited classes.
The machine-readable class is authoritative; prose may explain the task but
cannot broaden it or contain a prohibited control instruction.

The reviewed `operator_task` and `expected_visible.action` strings are also
frozen per stable scenario ID by normalized SHA-256 in the contract test. This
is deliberate mutation resistance, not a substitute for the structured
authority fields: any wording change requires an intentional review and hash
update. The narrow prohibited-phrase check remains defense in depth and is not
expected to recognize every unsafe paraphrase.

## Canonical presentation vocabulary

Every expected presentation uses exactly the design-system states from
`docs/design-system/patterns/state-visualization.md`:

`ok | caution | warning | fault | stale | disconnected`

Domain facts such as `safe_off`, `fault_latched`, `running`, `replay`,
`recovering`, or `not_recording` may appear in truth/reason text, but they do
not create additional presentation states. Each expected state requires at
least two signaling channels from color, shape/position, and text, following
the non-color state rule.

## The twelve scenarios

| Stable ID | Required coverage | Operator question |
|---|---|---|
| `f36.operator.cold_start` | Cold start | Has authoritative startup evidence arrived, and what is safe to inspect next? |
| `f36.operator.engine_disconnected` | Disconnected engine | Which authority path is unavailable, and what remains last-known only? |
| `f36.operator.stale_critical_data` | Stale data | Which critical value is stale, and does it block readiness? |
| `f36.operator.unsafe_preconditions` | Unsafe preconditions | Why is the run blocked, and which check must be resolved? |
| `f36.operator.alarm_acknowledgement` | Alarm acknowledgement | What is being acknowledged, and what truth remains active afterward? |
| `f36.operator.safety_recovery` | Safety recovery | Why is safety latched, and what reviewed recovery step is available? |
| `f36.operator.cooldown_deviation` | Cooldown deviation | Is cooldown off trajectory, why, and where is the evidence? |
| `f36.operator.storage_degradation` | Storage degradation | Are readings durably recording, and what storage action is safe next? |
| `f36.operator.passive_infrastructure_degradation` | Passive infrastructure degradation | Which support component degraded and what capability is affected? |
| `f36.operator.experiment_handover` | Experiment handover | What run is active, what remains unresolved, and what must the next shift know? |
| `f36.operator.replay` | Replay | Is this historical replay or live plant truth, and can it authorize action? |
| `f36.operator.support_bundle_capture` | Support-bundle capture | Can bounded redacted evidence be captured while the system is degraded? |

## Evidence procedure

The fixture declares `evidence_schema_version: 1`. For each observed run, copy
the scenario evidence template and fill four structured groups:

- `context`: app version and Git SHA, platform, DPI scale, locale, UI surface,
  and input method;
- `accessibility`: keyboard-only completion, visible focus, non-color state
  identification, accessible names, NVDA result, manual-review result, and any
  documented exception;
- `performance`: maximum frame work, fault-render latency, input latency,
  update rate, startup-to-interactive, idle memory, ZMQ-to-GUI latency,
  per-experiment and soak memory growth, soak duration, measurement method and
  artifact; per-metric `not_applicable` and reason maps prevent one global
  exception from hiding an unmeasured metric;
- `outcome`: anonymized operator/proxy and run IDs, start/decision/completion
  times, task success, decision time, errors, false presentations, artifact
  references and notes.

While `baseline_status` is `unmeasured_fixture`, every scalar evidence value is
`null` and every evidence array is empty. A partially populated fixture cannot
masquerade as the baseline contract.

Evidence artifacts must not contain credentials, hazardous-control secrets, or
unbounded raw experiment data. Baseline and target results must keep the same
scenario ID and fixture version so timing and error changes remain comparable.

The evidence contract carries the existing design-system budgets explicitly:
maximum frame work and fault rendering below 16 ms, input response below 100
ms, human-readable updates at no more than 2 Hz, startup to interactive below
2 s, idle memory below 300 MB, and ZMQ-to-GUI latency below 500 ms.
Per-experiment memory growth and at-least-12-hour soak growth each remain below
50 MB. These are target thresholds, not measurements in this baseline.

F36 closes only after the roadmap gate is measured: at least 90% task success,
median decision time at most 10 seconds, p95 at most 20 seconds, and zero false
safe/ready/recording states. This document records the measurement contract,
not those results.

## Design-system traceability

- Information hierarchy: Tier 1 truth and blocking exceptions remain visible;
  Tier 2 contains the active operator task; Tier 3 carries provenance and time.
- State visualization: exactly six states, two-channel signaling, conservative
  stale/disconnected precedence, and persistent text in every scenario.
- Accessibility: keyboard completion, visible focus, persistent non-color
  state labels and no motion-only information are required in later UI slices.
- Performance: future surfaces retain instant fault rendering, sub-100 ms input
  feedback and at-most-2 Hz human-readable live updates.

These are fixture requirements only. Visual, keyboard, NVDA, DPI, performance,
operator and Windows ONEDIR evidence remain open F36 gates.

The contract test freezes the exact stable ID-to-coverage mapping and a
scenario-specific invariant matrix for presentation state, authority class,
recording truth, safety relation, exact safety FSM, experiment truth,
interaction class, authority boundary and the no-hazard flag. It also rejects
duplicated titles/questions/tasks/conditions, unknown design-system references,
missing text signaling, prohibited control prose, premature measurements and
root schema type drift. Adversarial cases include exact and normalized variants
of `Automatically energize the source and begin the run.`; the reviewed-text
hash rejects them even when the narrow phrase check does not.
