# F10 — Sensor diagnostics → Alarm Engine v2 integration

> **Spec authored 2026-04-29 by architect (Claude Opus 4.7 web).**
> Implementation by Sonnet per overnight runner (separate doc).

---

## 0. Mandate

Sensor diagnostics (`src/cryodaq/core/sensor_diagnostics.py`) currently
detects channel anomalies (MAD-based outliers, correlation drift) and
exposes results via GUI display only. No alarm publishing. Operator must
visually notice anomaly, and may miss it during multi-hour campaigns.

Wire diagnostics → Alarm Engine v2 so prolonged anomalies become
proper alarms (warning at >5 min, critical at >15 min), with ACK and
configurable mute-on-retry.

Effort estimate: ~250 LOC + 20 tests.

---

## 1. Scope

**In:**
- New diagnostics → alarm publishing path
- Two new alarm rule types in `alarm_v2`: `sensor_anomaly_warning` 
  (5 min sustained), `sensor_anomaly_critical` (15 min sustained)
- Configurable thresholds in `config/alarms_v3.yaml`
- Hysteresis: anomaly clears → alarm clears (after configurable
  cooldown to prevent flapping)
- ACK + auto-mute window per alarm convention
- Unit tests + integration test

**Out:**
- New diagnostic algorithms (use existing MAD + correlation)
- GUI changes to alarm panel beyond ensuring new alarms render correctly
- Telegram routing (existing alarm pipeline already handles it)
- Migration of legacy alarm config files
- Cooldown_stall composite alarm refactor (separate F-task)

---

## 2. Architecture

### 2.1 Current state

`sensor_diagnostics.py` runs every 10s (configurable), per channel:
- MAD outlier check on rolling window
- Cross-channel correlation drift detection

Result: dict with `{channel_id: status}` where status ∈
`{ok, warning, critical, no_data}`. Result published to internal 
broker subscriber, GUI consumes via subscription.

`alarm_v2.py` is rule engine evaluating channel readings against 
declarative rules in `config/alarms_v3.yaml`. Existing rule types 
include `threshold`, `rate_of_change`, `composite`. Output: alarm 
events on broker.

### 2.2 Target wiring

Sensor diagnostics gets a new optional `alarm_publisher` parameter 
(injected in `engine.py` startup). When anomaly status persists past 
threshold duration, diagnostics calls 
`alarm_publisher.publish_diagnostic_alarm(...)` on the alarm engine.

Alarm Engine v2 gets two new built-in rule types:
- `sensor_anomaly_warning` — published when channel diagnostics 
  status == "warning" or "critical" for ≥5 min
- `sensor_anomaly_critical` — published when status == "critical" for 
  ≥15 min OR "warning"+"critical" continuous for ≥15 min

Alarms in `alarms_v3.yaml` reference the channel pattern as for 
existing rules. New alarm definitions ship as default config in 
addition to user-defined.

### 2.3 Data flow

```
LakeShore reading → broker
   → channel_manager → sensor_diagnostics (every 10s eval)
       → status dict {ch_id: ok|warning|critical|no_data}
   → if anomaly_window > threshold_duration:
       → alarm_engine.publish_diagnostic_alarm(channel, severity, age_s)
   → alarm_v2 raises alarm event
   → existing pipeline (GUI alarm panel + Telegram + safety_manager)
```

---

## 3. Implementation details

### 3.1 sensor_diagnostics.py changes

Add to `SensorDiagnostics.__init__`:

```python
def __init__(
    self,
    *,
    update_interval: float = 10.0,
    groups: dict | None = None,
    alarm_publisher: AlarmPublisher | None = None,  # NEW
    warning_duration_s: float = 300.0,  # NEW: 5 min default
    critical_duration_s: float = 900.0,  # NEW: 15 min default
):
    ...
    self._alarm_publisher = alarm_publisher
    self._warning_duration_s = warning_duration_s
    self._critical_duration_s = critical_duration_s
    self._anomaly_state: dict[str, _AnomalyState] = {}
```

Where `_AnomalyState` is a dataclass holding:
- `channel_id: str`
- `first_anomaly_ts: float`  # when this anomaly started (monotonic)
- `current_severity: str`  # ok / warning / critical
- `last_warning_published_ts: float | None`
- `last_critical_published_ts: float | None`

After each diagnostics evaluation, walk channel statuses:
- If status is `ok` or `no_data` and channel is in `_anomaly_state`:
  - If alarm was published, call 
    `alarm_publisher.clear_diagnostic_alarm(channel_id)`
  - Remove from `_anomaly_state`
- If status is `warning` or `critical`:
  - If channel not in state, add with first_anomaly_ts = now
  - If sustained >= warning_duration_s and not yet published warning:
    - Call `alarm_publisher.publish_diagnostic_alarm(channel, "warning", elapsed_s)`
    - Mark `last_warning_published_ts = now`
  - If sustained >= critical_duration_s and not yet published critical:
    - Call `alarm_publisher.publish_diagnostic_alarm(channel, "critical", elapsed_s)`
    - Mark `last_critical_published_ts = now`

### 3.2 alarm_v2.py changes

Add to `AlarmEngine`:

```python
def publish_diagnostic_alarm(
    self,
    channel_id: str,
    severity: Literal["warning", "critical"],
    age_seconds: float,
) -> None:
    """Publish a diagnostic-sourced alarm.
    
    Sensor diagnostics calls this when anomaly persists past 
    threshold duration. Creates / updates alarm in same shape 
    as threshold-rule alarms (broker event, ack tracking, etc.).
    """

def clear_diagnostic_alarm(self, channel_id: str) -> None:
    """Clear diagnostic alarm for channel when anomaly resolves."""
```

Internally these create / update alarm instances of new rule type
`SensorDiagnosticRule` (or extend existing rule machinery — Sonnet's
choice based on existing patterns).

The new rule type goes in `alarms_v3.yaml` schema validator as 
recognized type; concrete instances may live as auto-generated 
internally (one per channel_id seen) OR as explicit declarations 
(Sonnet's choice — recommend auto-generated to avoid yaml bloat).

### 3.3 config/alarms_v3.yaml additions

Add at top-level (or appropriate section):

```yaml
sensor_diagnostics:
  warning_duration_s: 300.0  # 5 min
  critical_duration_s: 900.0  # 15 min
  channel_pattern: ".*"  # all channels by default; can restrict
  enabled: true
```

This is config for the diagnostics → alarm publish behavior, not 
per-alarm rule. Per-channel diagnostic alarms auto-instantiate in 
the engine when first triggered.

### 3.4 engine.py wiring

In `_run_engine`, after `sensor_diagnostics` is constructed and 
after `alarm_engine` is constructed:

```python
sensor_diagnostics = SensorDiagnostics(
    update_interval=10.0,
    groups=channel_groups,
    alarm_publisher=alarm_engine,  # NEW
    warning_duration_s=cfg.get("warning_duration_s", 300.0),
    critical_duration_s=cfg.get("critical_duration_s", 900.0),
)
```

Where `cfg` is the `sensor_diagnostics:` block from `alarms_v3.yaml`.

If `alarms_v3.yaml.sensor_diagnostics.enabled: false`, do NOT pass 
`alarm_publisher` (graceful degradation — diagnostics still display, 
no alarms).

---

## 4. Acceptance criteria

1. Channel showing warning status for >5 min publishes warning alarm
2. Channel showing critical status for >15 min publishes critical alarm
3. Channel that recovers (status → ok) clears its diagnostic alarm
4. Disabling `sensor_diagnostics.enabled` config flag prevents alarm 
   publishing (diagnostics still display)
5. Adjusting `warning_duration_s` / `critical_duration_s` config 
   takes effect on next engine restart (no hot-reload needed)
6. Multiple channels each maintain independent state (no cross-channel 
   confusion)
7. Existing alarm subsystem behavior unchanged for non-diagnostic alarms
8. Tests cover all 7 above + edge cases

---

## 5. Test coverage requirements

### 5.1 Unit tests for sensor_diagnostics

`tests/core/test_sensor_diagnostics_alarm_publishing.py` (new, ~120 LOC):

- test_warning_published_after_warning_duration
- test_critical_published_after_critical_duration
- test_warning_then_critical_progression
- test_alarm_clears_when_status_returns_to_ok
- test_no_alarm_when_publisher_is_none (graceful degradation)
- test_multiple_channels_independent_state
- test_no_data_status_does_not_clear_existing_alarm
  (status no_data is ambiguous — keep alarm but log)

### 5.2 Unit tests for alarm_v2

`tests/core/test_alarm_v2_diagnostic_rule.py` (new, ~80 LOC):

- test_publish_diagnostic_alarm_creates_alarm_event
- test_publish_diagnostic_alarm_idempotent_per_channel
- test_clear_diagnostic_alarm_resolves_event
- test_diagnostic_alarm_inherits_ack_workflow

### 5.3 Integration test

`tests/integration/test_diagnostic_alarm_pipeline.py` (new, ~100 LOC):

- test_diagnostic_anomaly_to_alarm_to_telegram_pipeline
  (mock telegram client, verify alarm flows through full path)
- test_diagnostic_alarm_displayed_in_alarm_panel
  (mock GUI subscription, verify alarm event delivered)

### 5.4 Pre-existing tests

All existing tests in `tests/core/test_alarm_v2*` and 
`tests/core/test_sensor_diagnostics*` must continue passing.

---

## 6. Implementation phases (3-4 cycles)

### Cycle 1 — sensor_diagnostics.py changes + unit tests

**Branch:** `feat/f10-cycle1-diagnostics-publisher`

**Scope:** Section 3.1 + 5.1.

**Audit:** dual-verifier (new public API on SensorDiagnostics,
state tracking introduced).

**Decision rule for merge:** Sonnet judges PASS based on dual-verifier 
verdicts. Cycle 1 may auto-merge if both PASS.

### Cycle 2 — alarm_v2.py extension + unit tests

**Branch:** `feat/f10-cycle2-alarm-publisher`

**Scope:** Section 3.2 + 5.2.

**Audit:** dual-verifier (new methods on AlarmEngine, rule type
addition).

**Decision rule:** Auto-merge on dual PASS.

### Cycle 3 — Engine wiring + config + integration tests

**Branch:** `feat/f10-cycle3-integration`

**Scope:** Section 3.3 + 3.4 + 5.3.

**Depends on:** Cycle 1 + Cycle 2 merged.

**Audit:** dual-verifier (cross-component integration, config 
schema change, engine startup wiring).

**Decision rule:** STOP for architect review, do not auto-merge 
(integration risk + config schema change).

### Cycle 4 (conditional) — docs + CHANGELOG

**Only if Cycle 3 merged successfully overnight.**

Otherwise: skip; will pick up in morning bootstrap.

If autonomous: minimal CHANGELOG entry [Unreleased], ROADMAP 
F10 → ✅ DONE, vault sync deferred.

---

## 7. Hard stops

- Pre-existing `tests/core/test_sensor_diagnostics*` regression
- Pre-existing `tests/core/test_alarm_v2*` regression
- Audit dispatch fails for both verifiers (network / quota)
- Engine refuses to start with new diagnostics → alarm wiring 
  (smoke test: spawn mock engine, send shutdown after 30s)
- Cycle 3 reveals fundamental design issue — STOP, write incomplete 
  handoff

---

## 8. Spec deviations encouraged

If Sonnet finds during recon that:

- AlarmEngine already has analogous publishing pattern from another 
  source — adapt the new methods to follow the existing pattern 
  (don't invent new method shapes)
- SensorDiagnostics already has anomaly persistence tracking — extend 
  rather than duplicate
- Config file schema has a different conventional location for 
  service configs — follow existing convention, don't force the 
  spec's location

In each case: document the deviation in cycle handoff with reasoning. 
Architect reviews and ratifies in morning. Spec is starting position, 
not unalterable contract.

---

## 9. End of spec

Sonnet reads ROADMAP.md F10 entry first, then this spec.

Cycle 1 trigger comes from overnight runner (separate doc).
